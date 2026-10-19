"""hotel-seo-tools: the MCP server behind the hotel-seo skill.

Long tasks (crawls take 10-30 min, Custom Search a few minutes) run as
background jobs: the tool waits up to `wait_seconds`, then returns a job id
that job_status picks up. That keeps every call inside client timeouts,
including the desktop app's.
"""
import csv
import json
from concurrent.futures import ThreadPoolExecutor
import threading
import time
import traceback
import uuid

from mcp.server.fastmcp import FastMCP

from . import (__version__, audit, bing, booking_engine, checks, docs, facts, health, imports, indexing, keywords,
               librecrawl, librecrawl_proc, mirai, monitor, pagecheck, parity, paths, pdf, word)

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
    elif kind in ('audit', 'recheck', 'mirai', 'presend'):
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
def render_lists_pdf(out_dir: str, json_path: str = '', data: dict | None = None, crawl_dir: str = '',
                     facts_file: str = '', allow_unverified: bool = False, keep_html: bool = False,
                     google_doc: bool = True, folder_id: str = '', docx: bool = True) -> dict:
    """Render one list (Priority, Nice-to-Have, Web Team or Re-check) to PDF in the standard format,
    the same content as a Word file next to it (docx=true) and as a Google Doc (google_doc=true; the
    agency copies from Docs, PDFs break their formatting). Re-rendering the same list updates the same
    Doc, so its link stays the same, and keeps the same file number.
    File names: "<NN> - <hotel> <list> (<date>)", where a re-check list is "Priority Re-check 2" and
    the re-issued list "Priority Open Items after Re-check 2" (recheck_list sets the round).
    folder_id: a Google Drive folder for the Doc (default: the folder set with hotel-seo-docs-folder,
    else My Drive). Without Google sign-in for Docs it says so and writes a .docs.html file to import.
    Give json_path (a file following lists.schema.json) or the same object as data. file_number
    "auto" numbers it after the highest "NN - ..." PDF in the work folder. The result warns when
    the last page is nearly empty, and when a non-Priority list has items on the homepage, rooms,
    offers, contact or booking path (severity rule).

    [CONFIRM] guard: with crawl_dir (a crawl that audit_site has run on) and/or facts_file
    (<domain>/hotel-facts.json), every fact-like phrase (sizes, distances, counts, prices, times,
    "24-hour", tiers, stars) must appear on the live site, in the facts file, or be marked [CONFIRM].
    Otherwise nothing is rendered and the unverified phrases come back. allow_unverified=true only
    for Re-check lists that quote the live site."""
    if not json_path and not data:
        return {'error': 'Give json_path or data.'}
    doc = pdf.load(data or json_path)
    guard = facts.check(doc, crawl_dir, facts_file) if (crawl_dir or facts_file) else {
        'checked': False, 'reason': 'no crawl_dir or facts_file given'}
    if guard.get('unverified') and not allow_unverified:
        return {'rendered': False, 'confirm_guard': guard,
                'next': 'Mark each phrase [CONFIRM] in the list, correct it to what the site says, or add it '
                        'to hotel-facts.json with its source; then render again.'}
    result = _off_loop(pdf.render, doc, out_dir, keep_html=keep_html)
    out = {'rendered': True, **result, 'confirm_guard': {k: v for k, v in guard.items() if k != 'unverified'}}
    if docx:
        try:
            out['docx'] = _off_loop(word.render, doc, result['file'])
        except Exception as e:  # noqa: BLE001 - the PDF is done; say what failed
            out['docx_error'] = f'{type(e).__name__}: {str(e)[:300]}'
    sev = facts.severity_check(doc)
    if sev:
        out['severity_warning'] = {
            'sections': sev,
            'next': 'These touch the homepage, rooms, offers, contact or the booking path, which belong on the '
                    'Priority list. Move them, or add "not_priority_because" to the section if it is deliberate.'}
    if google_doc:
        out['google_doc'] = _off_loop(docs.publish, doc, out_dir, result['file'], folder_id=folder_id,
                                      docx_file=out.get('docx', ''))
    return out


@mcp.tool()
def audit_site(crawl_dir: str, gsc_property: str = '', hotel_city: str = '', mirai_id: str = '',
               wait_seconds: int = 45) -> dict:
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
                     mirai_id=mirai_id)
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
    with only unfinished items) in out_dir, ready for render_lists_pdf. crawl_dir: a fresh crawl,
    used for "sitewide" checks. Background job."""
    job = _start_job('recheck', checks.recheck, list_json, out_dir, crawl_dir=crawl_dir)
    return _wait(job, wait_seconds)


@mcp.tool()
def mirai_reservations(hotel_id: str, date_from: str = '', date_to: str = '', wait_seconds: int = 45) -> dict:
    """Bookings from the Mirai XML API: count, revenue, ADR, length of stay, booking window, by booking
    month and by stay month (seasonality), channel source, promo codes, offer IDs, guest country.
    Dates yyyy-mm-dd (default 1 Mar this year → today). Mirai allows one call per 3 minutes and 31 days
    per call, so long ranges take a while (background job). If credentials aren't set up it says so:
    use the Reservations Excel export instead."""
    if not mirai.configured():
        return mirai.reservations(hotel_id)
    job = _start_job('mirai', mirai.reservations, hotel_id, date_from, date_to)
    return _wait(job, wait_seconds)


@mcp.tool()
def booking_engine_snapshot(site: str, hotel_id: str, out_dir: str, crawl_dir: str = '', facts_file: str = '',
                            peak_month: int = 12, stays: list[dict] | None = None, wait_seconds: int = 45) -> dict:
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
    never selects a room or starts a booking. Background job."""
    job = _start_job('booking_engine', booking_engine.snapshot, site, hotel_id, out_dir, stays=stays,
                     crawl_dir=crawl_dir, facts_file=facts_file, peak_month=peak_month)
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
    Priority list: page fixes won't win a booking the OTA sells cheaper."""
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
def monitor_site(site: str, gsc_property: str = '', out_dir: str = '', add_to_schedule: bool = False,
                 wait_seconds: int = 45) -> dict:
    """Monitors: what changed on a hotel site since the last run. Alerts on new or growing suspicious
    (junk / backdated) posts, new spam search terms in Search Console (gsc_property), newly dead
    booking links, tags that stopped firing on the rendered homepage, a homepage noindex / canonical /
    status change, defacement text, new WordPress users and REST (MCP) routes that answer without
    login. The first run saves the baseline. add_to_schedule: also add the site to the list the
    scheduled hotel-seo-monitor command runs daily. Background job."""
    if add_to_schedule:
        monitor.add_site(site, gsc_property)
    job = _start_job('monitor', monitor.run, site, gsc_property, out_dir)
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


def main():
    mcp.run()


if __name__ == '__main__':
    main()
