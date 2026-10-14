"""LibreCrawl crawl, export, Custom Search and redirect test for hotel sites.

Talks to the local LibreCrawl API (see librecrawl_proc for starting it) and
writes the crawl files the playbook reads. Ported from the SEO Updates
tools/librecrawl.py script that was tested on albaharhotelandresort.com.
"""
import csv
import json
import os
import re
import time
from collections import Counter
from urllib.parse import urlparse

import requests

from . import librecrawl_proc, paths

# Matches the old Screaming Frog setup: 2 threads, about 2-3 URL/s.
HOTEL_SETTINGS = {
    'maxDepth': 10,  # LibreCrawl's maximum; it rejects higher values
    'maxUrls': 5000,
    'concurrency': 2,
    'crawlDelay': 1,
    'followRedirects': True,
    'crawlExternalLinks': False,
    'respectRobotsTxt': True,
    'discoverSitemaps': True,
    'enablePageSpeed': False,
    'enableJavaScript': False,
}

UA = 'Mozilla/5.0 (compatible; MetaHotels-SEO-check/1.0)'


def api_base():
    return paths.LIBRECRAWL_URL + '/api'


def api():
    """A session on the local LibreCrawl, starting it first if needed."""
    librecrawl_proc.start()
    s = requests.Session()
    r = s.get(f'{api_base()}/user/info', timeout=10)
    if r.status_code == 401:
        raise RuntimeError('LibreCrawl is not in local mode (got 401). Run /hotel-seo init again.')
    return s


def write_csv(path, fieldnames, rows):
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)


def one_line(text):
    return re.sub(r'\s+', ' ', text or '').strip()


# ---------------------------------------------------------------- export

def page_status(u):
    """LibreCrawl stores a redirecting URL with the final page's 200 and content.
    Report it the way Screaming Frog does: as the first hop's 3xx."""
    if u.get('redirects'):
        return u['redirects'][0].get('status_code')
    return u.get('status_code')


def is_page(u):
    """A real 200 HTML page (not a redirect, not an image or file)."""
    return page_status(u) == 200 and 'html' in (u.get('content_type') or 'text/html')


def fill_redirect_targets(urls):
    """Saved crawls drop redirected_to; look the final URL up again."""
    s = requests.Session()
    s.headers['User-Agent'] = UA
    for u in urls:
        if u.get('redirects') and not u.get('redirected_to'):
            try:
                u['redirected_to'] = s.head(u['url'], allow_redirects=True, timeout=15).url
            except requests.RequestException:
                u['redirected_to'] = ''


def indexability(u, home_host):
    if u.get('redirects'):
        return 'Non-indexable', 'redirect'
    if u.get('status_code') != 200:
        return 'Non-indexable', f"status {u.get('status_code')}"
    if 'noindex' in (u.get('robots') or '').lower():
        return 'Non-indexable', 'noindex'
    canon = u.get('canonical_url') or ''
    if canon and canon.rstrip('/') != (u.get('redirected_to') or u['url']).rstrip('/'):
        return 'Non-indexable', 'canonicalised'
    return 'Indexable', ''


def export_files(data, out, start_url):
    os.makedirs(out, exist_ok=True)
    urls = data.get('urls', [])
    links = data.get('links', [])
    issues = data.get('issues', [])
    home_host = urlparse(start_url).netloc.replace('www.', '')

    with open(os.path.join(out, 'crawl.json'), 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)

    internal = [u for u in urls if urlparse(u['url']).netloc.replace('www.', '') == home_host
                and ('html' in (u.get('content_type') or 'text/html') or page_status(u) != 200)]
    fill_redirect_targets(internal)
    pages = [u for u in internal if is_page(u)]
    by_url = {u['url']: u for u in urls}

    # internal_all.csv  (Screaming Frog: Internal > All)
    rows = []
    for u in internal:
        idx, why = indexability(u, home_host)
        title = one_line(u.get('title'))
        meta = one_line(u.get('meta_description'))
        rows.append({
            'url': u['url'], 'status_code': page_status(u),
            'redirected_to': u.get('redirected_to', ''),
            'indexability': idx, 'indexability_status': why,
            'title': title, 'title_length': len(title),
            'meta_description': meta, 'meta_description_length': len(meta),
            'h1': one_line(u.get('h1')), 'h2_count': len(u.get('h2') or []),
            'canonical_url': u.get('canonical_url', ''), 'meta_robots': u.get('robots', ''),
            'word_count': u.get('word_count', 0), 'response_time_ms': round(u.get('response_time') or 0),
            'size_bytes': u.get('size', 0), 'depth': u.get('depth'),
            'inlinks': len(u.get('linked_from') or []), 'lang': u.get('lang', ''),
            'og_site_name': (u.get('og_tags') or {}).get('site_name', ''),
            'content_type': u.get('content_type', ''),
        })
    write_csv(os.path.join(out, 'internal_all.csv'), list(rows[0].keys()) if rows else ['url'], rows)

    # canonicals.csv  (Canonicals > All)
    rows = []
    for u in pages:
        canon = u.get('canonical_url') or ''
        if not canon:
            state = 'missing'
        elif canon.rstrip('/') == u['url'].rstrip('/'):
            state = 'self'
        else:
            state = 'canonicalised'
        rows.append({'url': u['url'], 'canonical_url': canon, 'state': state})
    write_csv(os.path.join(out, 'canonicals.csv'), ['url', 'canonical_url', 'state'], rows)

    # directives.csv  (Directives > All; meta robots only, no X-Robots-Tag header)
    rows = [{'url': u['url'], 'meta_robots': u.get('robots', ''),
             'noindex': 'noindex' in (u.get('robots') or '').lower(),
             'nofollow': 'nofollow' in (u.get('robots') or '').lower()}
            for u in pages]
    write_csv(os.path.join(out, 'directives.csv'), ['url', 'meta_robots', 'noindex', 'nofollow'], rows)

    # structured_data.csv  (Structured Data > All; extraction only, not validated)
    rows = []
    for u in pages:
        types = []
        for block in u.get('json_ld') or []:
            for node in (block.get('@graph') if isinstance(block, dict) and '@graph' in block else [block]):
                if isinstance(node, dict):
                    t = node.get('@type')
                    types.extend(t if isinstance(t, list) else [t] if t else [])
        rows.append({'url': u['url'], 'jsonld_blocks': len(u.get('json_ld') or []),
                     'jsonld_types': ', '.join(str(t) for t in types),
                     'microdata_items': len(u.get('schema_org') or []),
                     'jsonld': json.dumps(u.get('json_ld') or [], ensure_ascii=False)})
    write_csv(os.path.join(out, 'structured_data.csv'),
              ['url', 'jsonld_blocks', 'jsonld_types', 'microdata_items', 'jsonld'], rows)

    # hreflang.csv
    rows = [{'url': u['url'], 'hreflang': json.dumps(u.get('hreflang'), ensure_ascii=False)}
            for u in pages if u.get('hreflang')]
    write_csv(os.path.join(out, 'hreflang.csv'), ['url', 'hreflang'], rows)

    # inlinks_4xx.csv and inlinks_3xx.csv  (Bulk Export > Response Codes)
    broken, redirected = [], []
    for l in links:
        t = by_url.get(l['target_url'])
        status = l.get('target_status')
        if status is None and t:
            status = t.get('status_code')
        row = {'source_url': l['source_url'], 'target_url': l['target_url'],
               'target_status': status, 'anchor_text': one_line(l.get('anchor_text')),
               'placement': l.get('placement', ''), 'is_internal': l.get('is_internal')}
        if status == 0 or (isinstance(status, int) and status >= 400):
            broken.append(row)
        if t and t.get('redirects'):
            row = dict(row, redirects_to=t.get('redirected_to', ''),
                       hops=len(t['redirects']), first_hop_status=t['redirects'][0]['status_code'])
            redirected.append(row)
    write_csv(os.path.join(out, 'inlinks_4xx.csv'),
              ['source_url', 'target_url', 'target_status', 'anchor_text', 'placement', 'is_internal'], broken)
    write_csv(os.path.join(out, 'inlinks_3xx.csv'),
              ['source_url', 'target_url', 'first_hop_status', 'hops', 'redirects_to', 'anchor_text',
               'placement', 'is_internal'], redirected)

    # images_missing_alt.csv  (Bulk Export > Images > Missing Alt Text Inlinks)
    rows, seen = [], set()
    for u in pages:
        for img in u.get('images') or []:
            alt = (img.get('alt') or '').strip()
            if img.get('has_alt') and alt:
                continue
            key = (u['url'], img.get('src'))
            if key in seen:
                continue
            seen.add(key)
            rows.append({'page_url': u['url'], 'image_src': img.get('src', ''),
                         'alt_state': 'empty alt=""' if img.get('has_alt') else 'no alt attribute'})
    write_csv(os.path.join(out, 'images_missing_alt.csv'), ['page_url', 'image_src', 'alt_state'], rows)

    # issues.csv  (LibreCrawl's own issue list)
    write_csv(os.path.join(out, 'issues.csv'), ['url', 'type', 'category', 'issue', 'details'], issues)

    # overview.md  (Reports > Crawl Overview)
    codes = Counter(page_status(u) for u in internal)
    idx = Counter(indexability(u, home_host)[0] for u in internal)
    lines = [f"# Crawl overview: {start_url}", '',
             f"- Crawl ID: {data.get('crawl_id')}  status: {data.get('status')}",
             f"- Internal URLs: {len(internal)}  (all URLs incl. external checks: {len(urls)})",
             f"- Links: {len(links)}  broken link rows: {len(broken)}  links to redirects: {len(redirected)}",
             '- Status codes: ' + ', '.join(f'{k}: {v}' for k, v in sorted(codes.items(), key=lambda x: str(x[0]))),
             '- Indexability: ' + ', '.join(f'{k}: {v}' for k, v in idx.items()),
             '', '## Issues', '']
    for name, n in Counter(i['issue'] for i in issues).most_common():
        lines.append(f'- {name}: {n}')
    with open(os.path.join(out, 'overview.md'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')

    return {
        'out_dir': str(out),
        'crawl_id': data.get('crawl_id'),
        'internal_urls': len(internal),
        'all_urls': len(urls),
        'links': len(links),
        'broken_link_rows': len(broken),
        'links_to_redirects': len(redirected),
        'status_codes': {str(k): v for k, v in codes.items()},
        'indexability': dict(idx),
        'files': sorted(f for f in os.listdir(out) if f.endswith(('.csv', '.md', '.json'))),
        'overview_md': '\n'.join(lines),
    }


# ---------------------------------------------------------------- crawl

def crawl(url, out_dir, js=False, max_urls=None, progress=None):
    """Crawl a site with the hotel settings and write the crawl files."""
    s = api()
    settings = dict(HOTEL_SETTINGS)
    if js:
        settings['enableJavaScript'] = True
    if max_urls:
        settings['maxUrls'] = max_urls
    r = s.post(f'{api_base()}/save_settings', json=settings).json()
    if not r.get('success'):
        raise RuntimeError(f'Could not save LibreCrawl settings: {r}')

    r = s.post(f'{api_base()}/start_crawl', json={'url': url}).json()
    if not r.get('success'):
        raise RuntimeError(f'Could not start crawl: {r}')
    crawl_id = r['crawl_id']

    while True:
        st = s.get(f'{api_base()}/crawl_status', params={'stats_only': 1}).json()
        status = st.get('status')
        stats = st.get('stats', {})
        if progress:
            progress(stats.get('crawled', 0), stats.get('discovered', 0))
        if status not in ('running', 'paused', 'starting'):
            break
        time.sleep(5)

    data = s.get(f'{api_base()}/crawl_status').json()
    data['crawl_id'] = crawl_id
    return export_files(data, paths.resolve(out_dir), url)


def export_saved(crawl_id, out_dir):
    s = api()
    r = s.get(f'{api_base()}/crawls/{crawl_id}').json()
    if not r.get('success'):
        raise RuntimeError(f'Could not load crawl {crawl_id}: {r}')
    data = {'urls': r['urls'], 'links': r['links'], 'issues': r['issues'],
            'crawl_id': crawl_id, 'status': r['crawl'].get('status'),
            'stats': {'baseUrl': r['crawl'].get('base_url', '')}}
    return export_files(data, paths.resolve(out_dir), r['crawl'].get('base_url', ''))


def list_saved(limit=20):
    s = api()
    r = s.get(f'{api_base()}/crawls/list', params={'limit': limit}).json()
    return [{'id': c['id'], 'status': c.get('status'), 'started_at': c.get('started_at'),
             'urls_crawled': c.get('urls_crawled'), 'base_url': c.get('base_url')}
            for c in r.get('crawls', [])]


# ---------------------------------------------------------------- custom search

def custom_search(crawl_dir, terms, case_sensitive=False, text_only=False, delay=0.5):
    """Custom Search: fetch every 200 HTML page from a crawl and count each term."""
    from bs4 import BeautifulSoup
    crawl_dir = paths.resolve(crawl_dir)
    with open(crawl_dir / 'crawl.json', encoding='utf-8') as f:
        data = json.load(f)
    start = (data.get('stats') or {}).get('baseUrl') or data['urls'][0]['url']
    host = urlparse(start).netloc.replace('www.', '')
    pages = [u['url'] for u in data['urls']
             if is_page(u) and urlparse(u['url']).netloc.replace('www.', '') == host]
    rows = []
    s = requests.Session()
    s.headers['User-Agent'] = UA
    for url in pages:
        try:
            html = s.get(url, timeout=20).text
        except requests.RequestException as e:
            rows.append({'url': url, 'term': '', 'count': '', 'snippet': f'fetch error: {e}'})
            continue
        hay = BeautifulSoup(html, 'html.parser').get_text(' ') if text_only else html
        for term in terms:
            hits = [m.start() for m in re.finditer(re.escape(term), hay, 0 if case_sensitive else re.I)]
            if hits:
                i = hits[0]
                rows.append({'url': url, 'term': term, 'count': len(hits),
                             'snippet': one_line(hay[max(0, i - 80):i + len(term) + 80])})
        time.sleep(delay)
    out = crawl_dir / 'custom_search.csv'
    write_csv(out, ['url', 'term', 'count', 'snippet'], rows)
    found = Counter(r['term'] for r in rows if r['term'])
    return {'pages_searched': len(pages), 'pages_with_term': {t: found.get(t, 0) for t in terms},
            'file': str(out), 'matches': rows[:200]}


# ---------------------------------------------------------------- redirect list test

def test_redirects(pairs, out_dir, delay=0.5):
    """List mode: follow each URL and record the chain.

    pairs: list of (source, expected) where expected may be ''. A row passes when
    the first hop is a 301 and it ends on the expected URL with a 200.
    """
    s = requests.Session()
    s.headers['User-Agent'] = UA
    rows = []
    for src, expected in pairs:
        try:
            r = s.get(src, timeout=20, allow_redirects=True)
            chain = ' > '.join(f'{h.status_code} {h.url}' for h in r.history)
            final, final_status, hops = r.url, r.status_code, len(r.history)
            first = r.history[0].status_code if r.history else r.status_code
        except requests.RequestException as e:
            chain, final, final_status, hops, first = f'error: {e}', '', 0, 0, 0
        result = ''
        if expected:
            result = 'PASS' if final.rstrip('/') == expected.rstrip('/') and final_status == 200 and first == 301 else 'FAIL'
        rows.append({'source': src, 'first_status': first, 'hops': hops, 'final_url': final,
                     'final_status': final_status, 'expected': expected, 'result': result, 'chain': chain})
        time.sleep(delay)
    out_dir = paths.resolve(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / 'redirect_test.csv'
    write_csv(out, ['source', 'first_status', 'hops', 'final_url', 'final_status', 'expected', 'result', 'chain'], rows)
    return {'tested': len(rows), 'results': dict(Counter(r['result'] or 'no expectation' for r in rows)),
            'file': str(out), 'rows': rows}


def read_pairs_file(path):
    """A .txt (one URL per line) or .csv with columns source,expected."""
    path = paths.resolve(path)
    with open(path, encoding='utf-8-sig') as f:
        if str(path).lower().endswith('.csv'):
            return [(r['source'].strip(), (r.get('expected') or '').strip()) for r in csv.DictReader(f)]
        return [(line.strip(), '') for line in f if line.strip() and not line.startswith('#')]
