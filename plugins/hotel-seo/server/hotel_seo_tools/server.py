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

from . import __version__, audit, checks, facts, health, librecrawl, librecrawl_proc, mirai, pagecheck, paths, pdf

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
    elif kind in ('audit', 'recheck', 'mirai'):
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
                     facts_file: str = '', allow_unverified: bool = False, keep_html: bool = False) -> dict:
    """Render one list (Priority, Nice-to-Have, Web Team or Re-check) to PDF in the standard format.
    Give json_path (a file following lists.schema.json) or the same object as data. file_number
    "auto" numbers it after the highest "NN - ..." PDF in the work folder. The result warns when
    the last page is nearly empty.

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
    return {'rendered': True, **result, 'confirm_guard': {k: v for k, v in guard.items() if k != 'unverified'}}


@mcp.tool()
def audit_site(crawl_dir: str, gsc_property: str = '', hotel_city: str = '', wait_seconds: int = 45) -> dict:
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
    - booking links: dead, old booking-step addresses, past check-in dates, other currencies
    - copy: phone numbers and odd country codes, different distances for one landmark, prices in the
      text, out-of-season wording, old years in titles, another city in headings (hotel_city, else
      read from the schema), blog post author names, blog posts with no link to rooms or booking
    - WordPress REST: SEO and Redirection plugins, exposed namespaces, public users, suspicious /
      backdated posts with trend, Media Library alt text
    - Search Console (gsc_property, e.g. "sc-domain:hotel.com"): spam queries, brand share now vs the
      90 days before, non-brand searches at positions 4-20, pages by impressions, old http/www
      versions still getting clicks, booking pages in search, Arabic searches
    Writes findings.json, findings.md, site_text.json and replace_pairs.csv in crawl_dir. Use these
    numbers in the lists; never count by hand. Background job: poll job_status."""
    job = _start_job('audit', audit.audit, crawl_dir, site_property=gsc_property, hotel_city=hotel_city)
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
