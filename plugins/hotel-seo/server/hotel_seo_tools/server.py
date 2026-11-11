"""hotel-seo-tools: the MCP server behind the hotel-seo skill.

Long tasks (crawls take 10-30 min, Custom Search a few minutes) run as
background jobs: the tool waits up to `wait_seconds`, then returns a job id
that job_status picks up. That keeps every call inside client timeouts,
including the desktop app's.
"""
import csv
import json
import re
from concurrent.futures import ThreadPoolExecutor
import threading
import time
import traceback
import uuid

from mcp.server.fastmcp import FastMCP

from . import (__version__, apikeys, audit, bing, booking_engine, bookingcom, checks, codechecks, docs, execute,
               facts, geo, group, health, imports, indexing, keyword_map, keywords, librecrawl, librecrawl_proc, mirai,
               monthly, pagecheck, parity, paths, pdf, preflight, questions, report, seo_check as seo_check_mod, sites,
               word)
from . import execute_report

mcp = FastMCP('hotel-seo-tools')

_jobs = {}
_lock = threading.Lock()
MAX_WAIT = 50


def _off_loop(fn, *args, **kwargs):
    """Run fn on a worker thread. Playwright's sync API refuses to run on the
    thread that owns the MCP server's asyncio loop."""
    with ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(fn, *args, **kwargs).result()


def _start_job(kind, fn, *args, **kwargs):
    job_id = f'{kind}-{uuid.uuid4().hex[:8]}'
    job = {'id': job_id, 'kind': kind, 'state': 'running', 'started': time.time(),
           'progress': '', 'result': None, 'error': None}

    def progress(done, total):
        job['progress'] = f'{done} crawled / {total} discovered'

    if kind == 'crawl':
        kwargs['progress'] = progress
    elif kind in ('audit', 'recheck', 'mirai', 'presend', 'keyword_map', 'content_scan', 'preflight', 'monthly', 'serp'):
        kwargs['progress'] = lambda msg: job.__setitem__('progress', msg)

    def run():
        try:
            job['result'] = fn(*args, **kwargs)
            job['state'] = 'done'
        except Exception as e:  # noqa: BLE001 - surface any failure to Claude
            job['error'] = f'{e}\n{traceback.format_exc(limit=3)}'
            job['state'] = 'failed'

    with _lock:
        _jobs[job_id] = job
    threading.Thread(target=run, daemon=True).start()
    return job


def _wait(job, wait_seconds):
    deadline = time.time() + max(0, min(wait_seconds, MAX_WAIT))
    while job['state'] == 'running' and time.time() < deadline:
        time.sleep(1)
    out = {'job_id': job['id'], 'kind': job['kind'], 'state': job['state'],
           'elapsed_s': round(time.time() - job['started'])}
    if job['state'] == 'running':
        out['progress'] = job['progress']
        out['next'] = f'Call job_status("{job["id"]}") to keep waiting.'
    elif job['state'] == 'done':
        out['result'] = job['result']
    else:
        out['error'] = job['error']
    return out


@mcp.tool()
def health_check(google: bool = True) -> str:
    """Check this machine's hotel-seo setup: uv, LibreCrawl, Chromium, Google sign-in
    (GA4 + Search Console). Returns a table with a fix for every failing row."""
    return health.as_table(_off_loop(health.run, google=google))


@mcp.tool()
def crawl_site(url: str, out_dir: str, js: bool = False, max_urls: int = 0, wait_seconds: int = 45) -> dict:
    """Crawl a hotel website with LibreCrawl (starts LibreCrawl if needed) and write the crawl
    files: internal_all, canonicals, directives, structured_data, hreflang, inlinks_4xx,
    inlinks_3xx, images_missing_alt, issues CSVs, overview.md and crawl.json.

    url: the homepage, e.g. https://hotel.com/
    out_dir: folder for the files, e.g. "hotel.com/crawl-2026-10-14" (relative paths resolve
      against the working folder). Crawls take 10-30 min: if state is "running", call job_status.
    js: render JavaScript (slower; only if the plain crawl misses content)."""
    job = _start_job('crawl', librecrawl.crawl, url, out_dir, js=js, max_urls=max_urls or None)
    return _wait(job, wait_seconds)


@mcp.tool()
def job_status(job_id: str, wait_seconds: int = 45) -> dict:
    """Wait for a background job (crawl, custom search, redirect test) and return its result."""
    job = _jobs.get(job_id)
    if not job:
        return {'error': f'unknown job {job_id}. Jobs are lost if the MCP server restarted; '
                         'for crawls use list_crawls + export_crawl.'}
    return _wait(job, wait_seconds)


@mcp.tool()
def list_crawls(limit: int = 20) -> list:
    """Saved LibreCrawl crawls on this machine (newest first)."""
    return librecrawl.list_saved(limit)


@mcp.tool()
def export_crawl(crawl_id: int, out_dir: str) -> dict:
    """Write the crawl files for a saved crawl (e.g. after the MCP server restarted mid-crawl)."""
    return librecrawl.export_saved(crawl_id, out_dir)


@mcp.tool()
def read_crawl_file(path: str, columns: list[str] | None = None, where: dict | None = None,
                    contains: str = '', offset: int = 0, limit: int = 100) -> dict:
    """Read rows from a crawl CSV (or the text of overview.md / any .md/.json file).

    columns: keep only these columns. where: exact matches, e.g. {"status_code": "404"}.
    contains: case-insensitive text that must appear somewhere in the row.
    Use offset/limit to page through large files (for non-CSV files, offset is a character offset
    and up to 60,000 characters come back)."""
    p = paths.resolve(path)
    if p.suffix.lower() != '.csv':
        text = p.read_text(encoding='utf-8')
        return {'file': str(p), 'length': len(text), 'offset': offset, 'text': text[offset:offset + 60000]}
    with open(p, encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    if where:
        rows = [r for r in rows if all(str(r.get(k, '')) == str(v) for k, v in where.items())]
    if contains:
        c = contains.lower()
        rows = [r for r in rows if any(c in str(v).lower() for v in r.values())]
    total = len(rows)
    rows = rows[offset:offset + limit]
    if columns:
        rows = [{k: r.get(k, '') for k in columns} for r in rows]
    return {'file': str(p), 'total_matching': total, 'offset': offset, 'returned': len(rows), 'rows': rows}


@mcp.tool()
def custom_search(crawl_dir: str, terms: list[str], case_sensitive: bool = False,
                  text_only: bool = False, wait_seconds: int = 45) -> dict:
    """Custom Search: fetch every 200 page from a crawl and count each term (old-operator names,
    other hotels' names, false claims). Writes custom_search.csv in crawl_dir.
    Use case_sensitive for names that are also ordinary words."""
    job = _start_job('search', librecrawl.custom_search, crawl_dir, terms,
                     case_sensitive=case_sensitive, text_only=text_only)
    return _wait(job, wait_seconds)


@mcp.tool()
def test_redirects(out_dir: str, pairs: list[dict] | None = None, file: str = '', wait_seconds: int = 45) -> dict:
    """List-mode redirect test. Give pairs [{"source": url, "expected": url}] or a file
    (.txt one URL per line, or .csv with source,expected). A row PASSes when the first hop is
    a 301 and it ends on the expected URL with a 200. Writes redirect_test.csv in out_dir."""
    if file:
        items = librecrawl.read_pairs_file(file)
    else:
        items = [(p['source'], p.get('expected', '')) for p in (pairs or [])]
    if not items:
        return {'error': 'Give pairs or a file.'}
    job = _start_job('redirects', librecrawl.test_redirects, items, out_dir)
    return _wait(job, wait_seconds)


@mcp.tool()
def render_report(out_dir: str, json_path: str = '', data: dict | None = None, crawl_dir: str = '', facts_file: str = '',
                  allow_unverified: bool = False, keep_html: bool = False, google_doc: bool = True, folder_id: str = '',
                  docx: bool = True) -> dict:
    """Render one document (Audit Report, Build Plan, Web Team List, Group Summary, Execute Report, Re-check, Monthly
    Report or Group Monthly Summary) to PDF,
    the same content as Word (.docx) and as a Google Doc (re-rendering updates the same Doc and keeps the file number).
    Give json_path (e.g. <hotel dir>/audit-<date>/audit-report.json from build_audit_report) or the same object as
    data. Findings with more than 25 URLs: the first 25 show in the document; every URL goes to a CSV next to it and a
    Google Sheet linked from the finding. No page or item limit.

    [CONFIRM] guard: with crawl_dir and/or facts_file (<hotel dir>/hotel-facts.json), every fact-like phrase (sizes,
    distances, counts, prices, times, "24-hour", tiers, stars) must be on the live site, in the hotel's confirmed facts
    (hotel sheet, hotel contact, booking engine, or Booking.com + booking engine agreeing), or marked [CONFIRM].
    Otherwise nothing is rendered and the unverified phrases come back. allow_unverified=true only for Re-check
    documents that quote the live site."""
    if not json_path and not data:
        return {'error': 'Give json_path or data.'}
    doc = pdf.load(data or json_path)
    guard = facts.check(doc, crawl_dir, facts_file) if (crawl_dir or facts_file) else {
        'checked': False, 'reason': 'no crawl_dir or facts_file given'}
    if guard.get('unverified') and not allow_unverified:
        return {'rendered': False, 'confirm_guard': guard,
                'next': 'Mark each phrase [CONFIRM], correct it to what the site says, or add it to hotel-facts.json '
                        'with its source (add_facts); then render again.'}
    pdf.validate(doc)
    stem = pdf.file_name(doc, paths.resolve(out_dir))[:-4]
    url_lists = _off_loop(docs.prepare_url_lists, doc, out_dir, stem, folder_id, google_doc)
    result = _off_loop(pdf.render, doc, out_dir, keep_html=keep_html)
    out = {'rendered': True, **result, 'url_lists': url_lists,
           'confirm_guard': {k: v for k, v in guard.items() if k != 'unverified'}}
    if docx:
        try:
            out['docx'] = _off_loop(word.render, doc, result['file'])
        except Exception as e:  # noqa: BLE001 - the PDF is done; say what failed
            out['docx_error'] = f'{type(e).__name__}: {str(e)[:300]}'
    if google_doc:
        out['google_doc'] = _off_loop(docs.publish, doc, out_dir, result['file'], folder_id=folder_id,
                                      docx_file=out.get('docx', ''))
    return out


@mcp.tool()
def audit_site(crawl_dir: str, gsc_property: str = '', hotel_city: str = '', mirai_id: str = '',
               group_dir: str = '', wait_seconds: int = 45) -> dict:
    """Compute every count and finding in code from a finished crawl. Fetches each 200 page once and
    reports, with full counts and URLs:
    - per page: H1s, titles, metas, canonicals, robots, JSON-LD (invalid blocks, every business /
      review / FAQ block with name, geo, sameAs, priceRange, reviews), GTM/gtag in raw HTML
    - canonicals that point to a redirect or 404 (Google indexes neither address)
    - titles: repeated or keyword-stuffed suffixes, WordPress default titles, duplicates, meta coverage
    - SEO plugin: active (REST) and actually printing into the HTML; robots.txt, sitemap_index /
      wp-sitemap status and which post types they list; Search Console's submitted sitemaps live status
    - indexable booking / account pages (/search/, /checkout/...), date / author / tag archives,
      thin page groups (/facility/, /nearby/...), near-empty pages, odd slugs
    - links: broken and redirected targets grouped by target with page counts and a sitewide flag;
      replace_pairs.csv (old -> final address) for a bulk search-and-replace
    - booking links: dead, old booking-step addresses, past check-in dates, other currencies, and links
      that open ANOTHER hotel's booking engine (mirai_id = this hotel's Mirai ID; names from the parity roster)
    - copy: phone numbers and odd country codes, different distances for one landmark, prices in the
      text, out-of-season wording, old years in titles, another city in headings (hotel_city, else
      read from the schema), blog post author names, blog posts with no link to rooms or booking
    - WordPress REST: SEO and Redirection plugins, public users, suspicious / junk / backdated posts
      (date gaps and ID order) with trend and "still being created", Media Library alt text, a leftover
      llms.txt, and whether MCP / site-control routes (/wp-json/mcp, elementor-mcp...) answer without login
    - full coverage: pages the crawl didn't reach (sitemaps, WordPress posts and pages) are scanned too
    - tracking: the homepage is rendered in Chromium and the tags that actually fire are recorded
      (tags_rendered); use those, never the raw-HTML IDs, for any statement about tracking
    - Search Console (gsc_property, e.g. "sc-domain:hotel.com"): spam queries, brand share now vs the
      90 days before, non-brand searches at positions 4-20, pages by impressions, old http/www
      versions still getting clicks, booking pages in search, Arabic searches
    Writes findings.json, findings.md, site_text.json and replace_pairs.csv in crawl_dir. Use these
    numbers in the lists; never count by hand. Background job: poll job_status."""
    job = _start_job('audit', audit.audit, crawl_dir, site_property=gsc_property, hotel_city=hotel_city,
                     mirai_id=mirai_id, group_dir=group_dir)
    return _wait(job, wait_seconds)


@mcp.tool()
def inspect_pages(urls: list[str], out_dir: str, mobile: bool = True, wait_seconds: int = 45) -> dict:
    """Render pages in headless Chromium (desktop, plus mobile if mobile=true) and record what guests
    and Google see: tags that actually fire (GTM, GA4, Google Ads, Meta pixel), visible H1s, title,
    meta, canonical, JSON-LD types, pop-ups/overlays, consent banner, console errors, screenshots.
    Use on the homepage, 2-3 room pages, offers, contact and one blog post. Background job."""
    vps = ('desktop', 'mobile') if mobile else ('desktop',)
    job = _start_job('inspect', pagecheck.inspect, urls, out_dir, viewports=vps)
    return _wait(job, wait_seconds)


@mcp.tool()
def recheck_list(list_json: str, out_dir: str, crawl_dir: str = '', wait_seconds: int = 45) -> dict:
    """Re-check a list against the live site using the `checks` stored on each section. Marks every
    item Done / Partly / Open / Manual and writes recheck-results, a Re-check list JSON (status table
    + lettered sections for what is still missing) and an open-items list JSON (the original list
    with only unfinished items) in out_dir, ready for render_report. crawl_dir: a fresh crawl,
    used for "sitewide" checks. Background job."""
    job = _start_job('recheck', checks.recheck, list_json, out_dir, crawl_dir=crawl_dir)
    return _wait(job, wait_seconds)


@mcp.tool()
def mirai_reservations(hotel_id: str, date_from: str = '', date_to: str = '', by: str = 'booking',
                       out_dir: str = '', wait_seconds: int = 45) -> dict:
    """Bookings of one hotel from the Mirai XML API (credentials: MIRAI_USER / MIRAI_PASS in the work
    folder's .env). Returns bookings, cancellations and rate, no-shows, revenue, room nights, ADR,
    length of stay, booking window, check-in weekday, by booking month and by stay month (seasonality),
    revenue and room nights per OFFER NAME and ROOM TYPE (packages sold that have no page), boards,
    channel, promo codes, member-rate modifiers, club sign-ups vs existing members, guest country,
    language, families, non-refundable share, extras. No guest names, emails or phones are kept.
    by: "booking" = bookings made between the dates (default 1 Mar this year → today);
        "checkin" = arrivals between the dates (default today → +90 days, what is on the books).
    Dates yyyy-mm-dd. out_dir: where the per-booking JSON goes (e.g. "<domain>/mirai").
    Mirai allows one call per 3 minutes and 31 days per call; windows are cached and shared by every
    hotel of the login, so the first long range takes a while (background job). Says so if
    credentials aren't set up: use the Reservations Excel export instead."""
    if not mirai.configured()[0]:
        return mirai.reservations(hotel_id)
    job = _start_job('mirai', mirai.reservations, hotel_id, date_from, date_to, by=by, out_dir=out_dir)
    return _wait(job, wait_seconds)


@mcp.tool()
def booking_engine_snapshot(site: str, hotel_id: str, out_dir: str, crawl_dir: str = '', facts_file: str = '',
                            peak_month: int = 12, stays: list[dict] | None = None, slug: str = '',
                            wait_seconds: int = 45) -> dict:
    """Read what the hotel actually sells from its live Mirai booking engine, in a browser session.
    Opens <site>/search/?idtokenprovider=<hotel_id> for 3 sample stays (next weekend, ~30 days out, mid
    peak_month; 1 night, 2 adults) and keeps the engine's own data: rooms (size, max occupancy, beds,
    amenities, availability), rates and offers with their discount, the member (club) discount, boards,
    cancellation terms, prices and taxes, and the lowest price per night for each month shown.
    Then renders the site's room, offer and loyalty pages (from crawl_dir) and compares: room sizes,
    offers sold with no page, offer pages with no rate on sale, member discount claimed on the site.
    facts_file (<domain>/hotel-facts.json): adds the engine's facts with source "booking engine, <date>"
    so the [CONFIRM] guard accepts them. stays: optional [{"label", "checkin": "yyyy-mm-dd", "nights",
    "adults"}]. Writes booking_engine.json / booking_engine.md and screenshots in out_dir. Read-only:
    never selects a room or starts a booking. Background job.
    slug: on a group site, the hotel's slug — only its own pages (partition.json, including shared /room/ pages its
    pages link to) are compared, never another hotel's."""
    only = group.pages_of(crawl_dir, slug) if (slug and crawl_dir) else None
    job = _start_job('booking_engine', booking_engine.snapshot, site, hotel_id, out_dir, stays=stays,
                     crawl_dir=crawl_dir, facts_file=facts_file, peak_month=peak_month, only_urls=only)
    return _wait(job, wait_seconds)


@mcp.tool()
def keyword_ideas(out_dir: str, seeds: list[str] | None = None, url: str = '', countries: list[str] | None = None,
                  language: str = 'en', limit: int = 300) -> dict:
    """Google Ads Keyword Planner: new keyword ideas with average monthly searches, competition, top-of-page
    bid range and monthly volumes. Seeds: up to 20 words (area + "hotel", room types, the non-brand
    Search Console queries); url: the hotel's site. countries: ISO codes (default ["AE"]; feeder markets
    such as GB, SA, IN, RU, DE); language: en, ar, ru... Run once per language you need. Writes
    keywords-ideas-<date>.csv/.json in out_dir. Says so if Google Ads isn't set up on this machine."""
    return _off_loop(keywords.ideas, seeds, url, out_dir, tuple(countries or ['AE']), language, limit)


@mcp.tool()
def keyword_volumes(keywords_list: list[str], out_dir: str, countries: list[str] | None = None,
                    language: str = 'en') -> dict:
    """Google Ads Keyword Planner numbers for keywords we already have (e.g. the money searches from
    Search Console, the titles we plan to write): average monthly searches, competition, bid range,
    monthly volumes, close variants. Writes keywords-volumes-<date>.csv/.json in out_dir."""
    return _off_loop(keywords.volumes, keywords_list, out_dir, tuple(countries or ['AE']), language)


@mcp.tool()
def rate_parity(mirai_id: str = '', hotel: str = '', days: int = 7, source: str = 'web', out_dir: str = '') -> dict:
    """Rate parity from the daily Magic Parity feed (the files behind the 6am leak report): share of
    checks where the hotel's own site Beats / Meets / Loses against each OTA, by OTA, device, guest
    country and lead time, the average gap, unsolved losses and the worst losing checks with
    screenshots. source: "web" (website vs OTAs) or "gha" (Google Hotel Ads). Prefer mirai_id; hotel
    name matching must hit exactly one hotel. Losing on 20%+ of priced checks goes at the top of the
    executive summary: page fixes won't win a booking the OTA sells cheaper."""
    return _off_loop(parity.report, hotel, mirai_id, days, source, out_dir)


@mcp.tool()
def index_status(gsc_property: str, site: str, out_dir: str, crawl_dir: str = '', extra_urls: list[str] | None = None,
                 daily_budget: int = 1900, wait_seconds: int = 45) -> dict:
    """Search Console page indexing for every crawled and sitemap URL, through the URL Inspection API:
    groups URLs the way the Page indexing report does (Submitted and indexed, Crawled - currently not
    indexed, Discovered - currently not indexed, Soft 404, Page with redirect, Alternate page with
    proper canonical, Google chose different canonical, ...) and lists where Google's canonical
    differs from the declared one. Google allows 2,000 inspections a day per property: results are
    cached, URLs inspected in the last 7 days are skipped, and a run stops at daily_budget, so run it
    again on later days for big sites. extra_urls: e.g. old URLs from a 404 export. Background job."""
    job = _start_job('index_status', indexing.inspect_all, gsc_property, site, out_dir, crawl_dir=crawl_dir,
                     extra_urls=extra_urls, daily_budget=daily_budget)
    return _wait(job, wait_seconds)


@mcp.tool()
def bing_report(site: str, out_dir: str = '') -> dict:
    """Bing Webmaster Tools: pages with incoming links and their link counts, who links to the top
    pages (with anchor text), and Bing's sitemap status (replaces the Search Console Links export and
    the Bing sitemap screenshot). Says so if the Bing API key isn't set up on this machine."""
    return _off_loop(bing.report, site, out_dir)


@mcp.tool()
def presend_check(list_json: str, crawl_dir: str = '', wait_seconds: int = 45) -> dict:
    """Live diff before sending a list: runs the draft list's checks against the live site now.
    Items already fixed (the agency may have done them since the crawl) are dropped; partly fixed
    items stay, titled "(partly done)" with a note of what is already live. Writes
    <list>-presend.json next to the draft: render that file, not the draft. Background job."""
    job = _start_job('presend', checks.presend, list_json, crawl_dir=crawl_dir)
    return _wait(job, wait_seconds)


@mcp.tool()
def import_facts_sheet(sheet: str, facts_file: str, filled_on: str = '') -> dict:
    """Read the hotel information sheet in code (.xlsx, .csv, or a Google Sheets link shared "anyone
    with the link") and add every filled field to hotel-facts.json with source "hotel info sheet,
    <filled_on>", so the [CONFIRM] guard accepts those facts. Other formats (PDF, Word): read them
    yourself and add the facts by hand with the same source."""
    return imports.facts_sheet(sheet, facts_file, filled_on)


@mcp.tool()
def import_keyword_csv(files: list[str], out_dir: str, label: str = '') -> dict:
    """Read Keyword Planner CSV exports (Keyword Planner → Download keyword ideas; English, Arabic,
    worldwide, a country) straight from the files: keywords, average monthly searches (or the range
    shown), competition, bid range, monthly volumes. Arabic keeps its order (copy-paste reverses it).
    Writes keywords-planner-<label>-<date>.csv/.json in out_dir. Use this until the Keyword Planner
    API is set up."""
    return imports.keyword_csv(files, out_dir, label)


@mcp.tool()
def librecrawl_control(action: str = 'status') -> str:
    """Start, stop or check the local LibreCrawl (action: status | start | stop).
    Crawls start it automatically; this is for troubleshooting or opening the browser GUI."""
    if action == 'start':
        return librecrawl_proc.start() + f' at {paths.LIBRECRAWL_URL}'
    if action == 'stop':
        return librecrawl_proc.stop()
    return ('running' if librecrawl_proc.is_running() else 'not running') + f' at {paths.LIBRECRAWL_URL}'


# ---------------------------------------------------------------- claude-seo scripts

@mcp.tool()
def seo_check(script: str, args: list[str] | None = None, timeout_s: int = 300, background: bool = False,
              wait_seconds: int = 45) -> dict:
    """Run one of claude-seo's vendored scripts (MIT) the agents use: render_page.py, fetch_page.py, parse_html.py,
    metadata_template.py, content_quality.py, content_humanize.py, content_verify.py, sitemap_discovery.py,
    schema_generate.py, pagespeed_check.py, crux_history.py, lcp_subparts.py, lighthouse_agentic.py, agentic_check.py,
    agent_ux_check.py, agentic_fix.py, google_auth.py, backlinks_auth.py, commoncrawl_graph.py, verify_backlinks.py,
    moz_api.py, bing_webmaster.py, validate_backlink_report.py, keywordseverywhere_api.py, seo_updates.py.
    args are the script's command-line arguments, e.g. ["https://hotel.com/", "--mode", "auto", "--json"]. API keys
    (Google, Moz, Bing, Geoapify) are added automatically and never returned: never pass a key. Large output is saved
    in full to .seo-check/ (read it with read_crawl_file). background=true for long runs (commoncrawl_graph)."""
    if background:
        job = _start_job('seo_check', seo_check_mod.run, script, args, timeout_s=max(timeout_s, 1800))
        return _wait(job, wait_seconds)
    return _off_loop(seo_check_mod.run, script, args, timeout_s)


@mcp.tool()
def seo_check_list() -> dict:
    """The claude-seo scripts seo_check can run, with what each does."""
    return seo_check_mod.listing()


@mcp.tool()
def download_images(urls: list[str], out_dir: str) -> dict:
    """Download images (e.g. those missing alt text) into out_dir so they can be looked at (Read the file) before
    alt text is written. Returns {url: local_path} plus failures. Images only, up to 15 MB each."""
    import hashlib
    import requests
    od = paths.resolve(out_dir)
    od.mkdir(parents=True, exist_ok=True)
    saved, failed = {}, {}
    for u in dict.fromkeys(urls):
        try:
            r = requests.get(u, timeout=40, stream=True, headers={'User-Agent': 'Mozilla/5.0 (MetaHotels-SEO-check)'})
            ct = r.headers.get('content-type', '')
            if r.status_code != 200 or not ct.startswith('image/'):
                failed[u] = f'{r.status_code} {ct}'
                continue
            ext = {'image/jpeg': '.jpg', 'image/png': '.png', 'image/webp': '.webp', 'image/gif': '.gif',
                   'image/avif': '.avif', 'image/svg+xml': '.svg'}.get(ct.split(';')[0], '.img')
            name = re.sub(r'[^A-Za-z0-9._-]+', '-', u.rsplit('/', 1)[-1].split('?')[0])[:80]
            f = od / (hashlib.sha1(u.encode()).hexdigest()[:8] + '-' + (name if name.endswith(ext) else name + ext))
            size = 0
            with open(f, 'wb') as fh:
                for chunk in r.iter_content(65536):
                    size += len(chunk)
                    if size > 15 * 1024 * 1024:
                        raise ValueError('larger than 15 MB')
                    fh.write(chunk)
            saved[u] = str(f)
        except Exception as e:  # noqa: BLE001
            failed[u] = f'{type(e).__name__}: {str(e)[:120]}'
    return {'saved': saved, 'failed': failed}


# ---------------------------------------------------------------- hotel groups

@mcp.tool()
def detect_hotels(crawl_dir: str) -> dict:
    """Tell a hotel group from a single hotel by the site's page structure, and propose the hotels: a group has
    several hotel sections under one parent path (Hotel schema, booking links, sub-pages each); a single hotel covers
    the whole domain (paths ["/"]). Returns type ("group" / "single") and slug, name, paths, city, Mirai ID per
    hotel. Show it to the user to confirm, ask for each hotel's Booking.com URL, then save_group."""
    out = group.detect(crawl_dir)
    hs = out.get('hotels') or []
    out['type'] = 'single' if len(hs) == 1 and hs[0].get('paths') == ['/'] else 'group'
    return out


@mcp.tool()
def save_group(group_dir: str, group_info: dict, hotels: list[dict]) -> dict:
    """Write <domain>/site.json after the user confirmed the hotels. group_info: {name, site, gsc_property,
    ga4_property}. hotels: [{slug, name, paths, city, country, mirai_id, booking_com_url, gsc_property, ga4_property}].
    One hotel with paths ["/"] = single-hotel site: its files go straight into <domain>/ (no group/ or hotels/ folders,
    no Group Summary). A group gets <domain>/group/ for site-wide work and <domain>/hotels/<slug>/ per hotel.
    Returns "folders": use folders[slug] as <hotel dir> and folders["site"] as <site dir> in every later step."""
    try:
        reg = group.save(group_dir, group_info, hotels)
    except ValueError as e:
        return {'error': str(e)}
    folders = {h['slug']: str(group.hotel_dir(group_dir, h['slug'], reg)) for h in reg['hotels']}
    folders['site'] = str(group.site_dir(group_dir, reg))
    return {**reg, 'folders': folders}


@mcp.tool()
def partition_crawl(crawl_dir: str, group_dir: str) -> dict:
    """Assign every crawled page to a hotel (longest path prefix) or to 'group' (shared pages). Writes
    <crawl>/partition.json, which the agents, the keyword map and the report use."""
    return group.partition(crawl_dir, group_dir)


# ---------------------------------------------------------------- facts: Booking.com, cross-check

@mcp.tool()
def bookingcom_extractor() -> dict:
    """The JavaScript to run with Claude in Chrome (javascript_tool) on a hotel's Booking.com page, and how."""
    return {'how': bookingcom.HOW_TO, 'javascript': bookingcom.EXTRACT_JS}


@mcp.tool()
def import_bookingcom(hotel_dir: str, chunks: list[str] | None = None, page_json: str = '',
                      facts_file: str = '') -> dict:
    """Save what the Booking.com extractor returned and turn it into facts. Pass the chunks read with
    window.__hotelseo_json.slice(...) in order (see bookingcom_extractor), or page_json (the JSON string or a file).
    Facts go to hotel-facts.json with source "Booking.com, <date>" and are cross-checked with the hotel's
    booking-engine snapshot: Booking.com-only facts stay unconfirmed; facts the engine agrees with are confirmed;
    disagreements go to facts-conflicts.json (they become findings)."""
    if chunks:
        page_json = ''.join(chunks)
        try:
            json.loads(page_json)
        except ValueError as e:
            return {'error': f'the joined chunks are not valid JSON ({e}); re-read every chunk in order'}
    if not page_json:
        return {'error': 'give chunks or page_json'}
    return bookingcom.import_page(page_json, hotel_dir, facts_file)


@mcp.tool()
def crosscheck_facts(facts_file: str, engine_json: str = '') -> dict:
    """Re-run the Booking.com vs booking-engine comparison (e.g. after booking_engine_snapshot ran later).
    engine_json defaults to the latest booking_engine.json under the hotel folder."""
    hd = paths.resolve(facts_file).parent
    return bookingcom.crosscheck(facts_file, engine_json or bookingcom.latest_engine_snapshot(hd))


@mcp.tool()
def add_facts(facts_file: str, facts: list[str], source: str) -> dict:
    """Add facts by hand with their source and date, e.g. source "hotel contact, 24 Oct 2026" or "hotel info sheet
    (PDF), 20 Oct 2026". Facts from Booking.com alone don't count as confirmed."""
    return bookingcom.add_facts(facts_file, facts, source)


# ---------------------------------------------------------------- maps

@mcp.tool()
def geo_lookup(query: str) -> dict:
    """Geocode an address or place (OpenStreetMap Nominatim): lat, lon, display name, address parts."""
    return _off_loop(geo.geocode, query)


@mcp.tool()
def nearby_places(lat: float, lon: float, radius_m: int = 5000, kinds: list[str] | None = None) -> dict:
    """Places near a hotel, nearest first: hotel (competitors), airport, metro_station, mall, beach, attraction, venue,
    hospital, university, marina. OpenStreetMap Overpass, plus Geoapify when its key is set (key never returned)."""
    return _off_loop(geo.nearby, lat, lon, radius_m, kinds)


# ---------------------------------------------------------------- keywords

@mcp.tool()
def build_keyword_map(group_dir: str, slug: str, crawl_dir: str, countries: list[str] | None = None,
                      languages: list[str] | None = None, extra_keywords: list[str] | None = None,
                      competitor_urls: list[str] | None = None, radius_m: int = 5000, wait_seconds: int = 45) -> dict:
    """Non-brand keyword map for one hotel: candidates from its facts and location (places, landmarks, type, stars,
    facilities, rooms, audiences), Keyword Planner ideas (seeds + competitor URLs), volumes for the hotel's city,
    country and feeder markets (countries: e.g. ["AE", "GB", "SA"]), brand filter, score = volume x intent x fit,
    clusters with one target page each, Search Console (16 months, this hotel's pages) for status: ranks / shows but
    low / invisible / no page. extra_keywords: FLOW Find ideas, Arabic versions. Writes <hotel dir>/keywords/."""
    job = _start_job('keyword_map', keyword_map.build, group_dir, slug, crawl_dir, countries=countries,
                     languages=tuple(languages or ['en']), extra_keywords=tuple(extra_keywords or ()),
                     competitor_urls=tuple(competitor_urls or ()), radius_m=radius_m)
    return _wait(job, wait_seconds)


@mcp.tool()
def assign_keyword_owners(group_dir: str) -> dict:
    """Across a group's hotels: a cluster several hotels in the same city share is owned by one (best score), so
    hotels don't compete for the same search. Run after every hotel's keyword map."""
    return keyword_map.assign_group(group_dir)


# ---------------------------------------------------------------- code checks on every page

@mcp.tool()
def content_scan(crawl_dir: str, out_dir: str, group_dir: str = '', slug: str = '', wait_seconds: int = 45) -> dict:
    """Every page of a hotel, in code: content_quality.py (filler, AI patterns, density, repetition), word count vs
    the hotel page-type floors, metadata_template.py over all title/description pairs. Writes content-scan.json for
    seo-content and seo-geo to cite."""
    job = _start_job('content_scan', codechecks.content_scan, crawl_dir, out_dir, group_dir=group_dir, slug=slug)
    return _wait(job, wait_seconds)


# ---------------------------------------------------------------- agent checks

@mcp.tool()
def agent_preflight(group_dir: str, crawl_dir: str, slugs: list[str] | None = None, wait_seconds: int = 45) -> dict:
    """Before the agents run: probe each of the 11 agents' inputs (real calls) for the site and each hotel.
    Status per agent: OK / degraded (runs with a named gap) / blocked (cannot run: reported as not assessed)."""
    job = _start_job('preflight', preflight.preflight, group_dir, crawl_dir, slugs)
    return _wait(job, wait_seconds)


@mcp.tool()
def validate_agent_output(run_dir: str, agent: str, scope: str, crawl_dir: str, group_dir: str = '',
                          attempt: int = 1) -> dict:
    """After an agent finishes: check findings/<agent>.json against the contract (schema, coverage of the hotel's key
    pages, counts equal to audit_site's, no invented URLs, severity, evidence, fix, checks, actions, agent rules:
    INP not FID, Lighthouse X/N, backlink validator, FLOW credit, [CONFIRM] guard, no secrets) and record the status in
    <run>/agent-status.json. attempt=2 on the re-run; a second failure is recorded as "not assessed"."""
    res = preflight.validate(run_dir, agent, scope, crawl_dir, group_dir)
    res['recorded'] = preflight.record(run_dir, agent, res, attempt)
    return res


# ---------------------------------------------------------------- reports

@mcp.tool()
def build_audit_report(group_dir: str, slug: str, run_date: str = '') -> dict:
    """Merge audit_site + booking engine + facts conflicts + every agent's findings for one hotel into its Audit Report
    and Web Team List (<hotel dir>/audit-<date>/audit-report.json, web-team.json, audit-data.json). Scores in code:
    8 weighted categories (Booking path & facts 15%, Technical 18.7, Content 19.55, On-Page 17, Schema 8.5,
    Performance 8.5, AI Search 8.5, Images 4.25), Local / Maps / Backlinks separate. Severity floor applied,
    duplicates merged (agents restating a core check replace it). Render the results with render_report."""
    return report.build(group_dir, slug, run_date or None)


@mcp.tool()
def build_group_summary(group_dir: str, run_date: str = '') -> dict:
    """Group Summary (group sites only): hotels x scores, site-wide findings once, keyword ownership, agent status per
    hotel. A single-hotel site has none (returns skipped)."""
    return report.build_group(group_dir, run_date or None)


# ---------------------------------------------------------------- site MCP (sites.csv)

@mcp.tool()
def sites_csv_status() -> dict:
    """sites.csv in the work folder: rows, complete / incomplete rows by name, duplicate hosts. Never shows a password."""
    return sites.summary()


@mcp.tool()
def site_mcp_status(site: str) -> dict:
    """Connect to a site's WordPress MCP endpoint with its sites.csv login: tools (read / write) and what the site
    supports (Rank Math, Redirection, Elementor, cache plugin, Polylang, the user's capabilities)."""
    return _off_loop(sites.status, site)


@mcp.tool()
def site_mcp_read(site: str, tool: str, args: dict | None = None) -> dict:
    """Call a READ tool on a site's MCP server (get-*, list-*, seo-get-*, elementor-get-*, redirects-list,
    content-integrations-status...). Write tools are refused here: changes only go through execute_plan /
    run_execute_batch, in batches the user approved."""
    try:
        return _off_loop(sites.call, site, tool, args or {})
    except (PermissionError, LookupError, RuntimeError, ValueError, FileNotFoundError) as e:
        return {'error': str(e)}


# ---------------------------------------------------------------- execute

@mcp.tool()
def execute_plan(group_dir: str, slug: str, only: list[str] | None = None) -> dict:
    """/hotel-seo execute, step 1 (dry run, nothing written): resolve every action of the hotel's latest audit report
    (and Build Plan pages) to the site's MCP tools, read each current value, and group them into batches:
    booking-path, seo-fields, redirects, elementor-text, schema, alt-text, post-status, menus, new-pages, chrome, group.
    slug="group" plans the group batch (site-wide settings, shared templates). Skips Web Team items, holds,
    [CONFIRM], prices / discounts. Show each batch's table to the user before running it."""
    try:
        return _off_loop(execute.plan, group_dir, slug, only)
    except (ConnectionError, FileNotFoundError, LookupError) as e:
        return {'error': str(e)}


@mcp.tool()
def run_execute_batch(plan_file: str, batch: str, approved: bool = False) -> dict:
    """/hotel-seo execute, step 2: run ONE batch the user approved (approved=true only after they said yes to its
    table). Saves before-values, writes, stops at the first error, purges the cache, re-checks each finding live."""
    try:
        return _off_loop(execute.run_batch, plan_file, batch, approved)
    except (PermissionError, LookupError, RuntimeError, ConnectionError) as e:
        return {'error': str(e)}


@mcp.tool()
def record_chrome_step(plan_file: str, item_id: str, done: bool = True, note: str = '') -> dict:
    """After doing a chrome-batch step with Claude in Chrome: mark it done (or not, with why) so the Execute Report
    and the Agency Fix List know."""
    try:
        return execute.record_chrome_step(plan_file, item_id, done, note)
    except LookupError as e:
        return {'error': str(e)}


@mcp.tool()
def execute_reports(group_dir: str, slug: str, plan_file: str = '') -> dict:
    """After an execute run: build the Execute Report (every change made: page, before -> after, live re-check; what
    waits for the hotel; undo) and the Agency Fix List (every SEO finding execute did not finish, step by step with
    the exact text to paste, for the SEO agency; developer items stay in the Web Team List). Render both with
    render_report(out_dir, json_path=..., google_doc=false) for PDF + Word."""
    try:
        return execute_report.build(group_dir, slug, plan_file)
    except (FileNotFoundError, LookupError, StopIteration) as e:
        return {'error': str(e) or 'unknown hotel'}


# ---------------------------------------------------------------- questions for the hotel

@mcp.tool()
def hotel_questions(group_dir: str, slug: str) -> dict:
    """Questions for the hotel (run after build_audit_report and the Build Plan, before rendering): every [CONFIRM]
    and held item, room sizes / guests / beds (site vs booking engine vs Booking.com), distances, and basic facts
    not yet confirmed, as an xlsx for the hotel to fill (Reports/NN - <Hotel> Questions for the Hotel (date).xlsx).
    The reports' markers become [CONFIRM Q7] / [CONFIRM R2] so each gap points at its row. Then read
    hotel-questions.json and call edit_hotel_questions to word the questions for hotel staff."""
    try:
        return questions.build(group_dir, slug)
    except (FileNotFoundError, StopIteration) as e:
        return {'error': str(e) or 'unknown hotel'}


@mcp.tool()
def edit_hotel_questions(group_dir: str, slug: str, edits: list[dict]) -> dict:
    """Word the Questions sheet for hotel staff: [{"id": "Q4", "question": "<one clear ask>", "now": "<what the
    site / booking engine shows>"}], {"id": "Q9", "drop": true} for anything that is not a question for the hotel
    (its markers are removed from the reports), {"id": "Q12", "merge_into": "Q3"} for the same ask twice.
    Rewrites the xlsx."""
    return questions.edit(group_dir, slug, edits)


@mcp.tool()
def import_hotel_answers(group_dir: str, slug: str, xlsx_path: str) -> dict:
    """Read the filled-in Questions for the Hotel xlsx: answers saved, confirmed facts added to hotel-facts.json
    (source "hotel questionnaire, <date>, <who>"), and the site text that contradicts the answers listed as
    corrections. execute_plan then includes the answered items and a "hotel-answers" batch."""
    try:
        return questions.import_answers(group_dir, slug, xlsx_path)
    except FileNotFoundError as e:
        return {'error': str(e)}


@mcp.tool()
def undo_execute(plan_file: str) -> dict:
    """Write back the before-values of an execute run, newest first (redirects it created are deleted, pages it
    created go back to draft)."""
    return _off_loop(execute.undo, plan_file)


# ---------------------------------------------------------------- monthly report

def _collect_all(group_dir, month, hotels, progress=None):
    reg = group.load(group_dir)
    if not reg:
        raise FileNotFoundError(f'no site.json in {group_dir}')
    slugs = hotels or [h['slug'] for h in reg['hotels']]
    out = {}
    for n, s in enumerate(slugs, 1):
        say = (lambda m, s=s, n=n: progress(f'hotel {n}/{len(slugs)} {s}: {m}')) if progress else None
        try:
            out[s] = monthly.collect(group_dir, s, month, progress=say)
        except Exception as e:  # noqa: BLE001 - one hotel failing must not stop the others
            out[s] = {'error': f'{type(e).__name__}: {e}'}
    return {'month': month or monthly.default_month(), 'hotels': out}


@mcp.tool()
def monthly_collect(group_dir: str, month: str = '', hotels: list[str] | None = None, wait_seconds: int = 45) -> dict:
    """/hotel-seo monthly, step 1: every number for the calendar month (YYYY-MM; default: last month) per hotel:
    Search Console (clicks, brand / non-brand, main-page position, countries, queries), GA4 (Google visits,
    engagement, AI-assistant visits), Mirai direct bookings, rate parity, pages in Google (URL Inspection), work done
    (execute logs + work-log.csv); each for the month, the month before and the same month last year. Writes
    <hotel dir>/monthly-<month>/data.json. Runs in the background (job_status). "provisional" = run within 3 days
    of the month's end (Search Console not final yet)."""
    job = _start_job('monthly', _collect_all, group_dir, month, hotels)
    return _wait(job, wait_seconds)


@mcp.tool()
def tracked_keywords(group_dir: str, slug: str, propose: bool = False) -> dict:
    """The hotel's tracked keywords (checked every month with Serper). propose=true builds a list from the keyword map
    (top non-brand clusters + brand searches), saved unconfirmed: show it to the user, then save_tracked_keywords."""
    if propose:
        return monthly.propose_tracked(group_dir, slug)
    ctx = monthly.context(group_dir, slug)
    return monthly.load_tracked(ctx) or {'keywords': [], 'next': 'Call tracked_keywords(propose=true).'}


@mcp.tool()
def save_tracked_keywords(group_dir: str, slug: str, keywords: list, maps_keywords: list[str] | None = None) -> dict:
    """Confirm the tracked keywords (after the user agreed). Each item: "keyword" or {"keyword", "type": "discovery" |
    "brand", "target": "Page 1" | "Top 5" | "Top 3", "target_page"}. maps_keywords: searches checked on Google Maps
    from the hotel's area. Keep the list stable month to month so months compare."""
    return monthly.save_tracked(group_dir, slug, keywords, maps_keywords)


@mcp.tool()
def serp_ranks(group_dir: str, slug: str, month: str = '', confirm: bool = False, wait_seconds: int = 45) -> dict:
    """Exact Google positions (Serper, the hotel's city, top 30) and map pack for the confirmed tracked keywords, plus
    Google Maps position from the hotel's area for maps_keywords. confirm=false returns the most credits it can use;
    confirm=true runs it (background job). Saved to monthly-<month>/serp.json; a re-run only checks what is missing."""
    if not confirm:
        return monthly.serp_run(group_dir, slug, month, confirm=False)
    job = _start_job('serp', monthly.serp_run, group_dir, slug, month, True)
    return _wait(job, wait_seconds)


@mcp.tool()
def import_monthly_manual(group_dir: str, slug: str, month: str, data: dict) -> dict:
    """Save what you read in Chrome for the month: {"gbp": {"rating", "reviews", "profile_views", "searches", "calls",
    "directions", "website_clicks", "booking_clicks", "period", "note"}, "security": {"security_issues",
    "manual_actions", "note"}} ("None" when Search Console shows none). Only numbers as shown on the page."""
    try:
        return monthly.import_manual(group_dir, slug, month, data)
    except ValueError as e:
        return {'error': str(e)}


@mcp.tool()
def add_work_log(group_dir: str, slug: str, date: str, what: str, page: str = '', who: str = 'MetaHotels') -> dict:
    """Add work done by hand (not through execute) to <hotel dir>/work-log.csv: date YYYY-MM-DD, what (plain words,
    e.g. "Google Business Profile: categories, amenities and photos updated"), page URL if any."""
    try:
        return monthly.add_work_log(group_dir, slug, date, what, page, who)
    except ValueError as e:
        return {'error': f'{e} (date must be YYYY-MM-DD)'}


@mcp.tool()
def save_monthly_narrative(group_dir: str, slug: str, month: str, narrative: dict) -> dict:
    """Your plain-language lines for the Monthly Report: cover_lead, headline, keywords_note, ai_note, work_intro,
    funnel_note, maps_note, title_01, title_04, title_05, next (list of what comes next). Refused when a number in it
    is not in the month's data or the built report, or a hotel fact fails the [CONFIRM] guard."""
    return monthly.save_narrative(group_dir, slug, month, narrative)


@mcp.tool()
def build_monthly_report(group_dir: str, slug: str, month: str = '') -> dict:
    """Assemble the hotel's Monthly Report (monthly-<month>/monthly-report.json) from data.json, serp.json, manual.json
    and narrative.json. Lists what was not available. Render it with render_report(out_dir=<hotel>/Reports,
    json_path=...) without crawl_dir / facts_file (the narrative was already checked)."""
    try:
        return monthly.build(group_dir, slug, month)
    except (FileNotFoundError, LookupError, ValueError) as e:
        return {'error': str(e)}


@mcp.tool()
def build_monthly_group(group_dir: str, month: str = '') -> dict:
    """Group Monthly Summary (group sites only; a single hotel has none): hotels side by side (Google visits, non-brand clicks, AI visits,
    bookings, revenue, tracked keywords on page 1) and the hotel report file names. Build and render the hotels first."""
    try:
        return monthly.build_group(group_dir, month)
    except FileNotFoundError as e:
        return {'error': str(e)}


def main():
    mcp.run()


if __name__ == '__main__':
    main()
