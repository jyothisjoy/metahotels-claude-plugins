"""Search Console page indexing, URL by URL, through the URL Inspection API.

The Page indexing report's lists ("Crawled – currently not indexed", "Soft 404", ...) are not in
Google's API, but URL Inspection returns each URL's coverage state. This module inspects every
crawled page and every sitemap URL and groups them the way the report does.

Quota (Google's published limits): 2,000 inspections a day and 600 a minute per Search Console
property. Results are cached per property in ~/.metahotels-seo/url-inspection/, URLs inspected in
the last `max_age_days` are not re-inspected, and a run stops at `daily_budget`, so a big site is
covered over a few days by running again. URLs only Google remembers (old spam pages, deleted
sections) never appear in a crawl or sitemap: those need the server's access logs.
"""
import csv
import json
import re
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urljoin, urlparse

import requests

from . import paths

ENDPOINT = 'https://searchconsole.googleapis.com/v1/urlInspection/index:inspect'
CACHE_DIR = paths.HOME / 'url-inspection'
# Search Console's Page indexing reasons, for the order of the summary
ORDER = ['Submitted and indexed', 'Indexed, not submitted in sitemap', 'Crawled - currently not indexed',
         'Discovered - currently not indexed', 'Soft 404', 'Not found (404)', 'Page with redirect',
         'Alternate page with proper canonical tag', 'Duplicate, Google chose different canonical than user',
         'Duplicate without user-selected canonical', 'Excluded by ‘noindex’ tag', 'Blocked by robots.txt',
         'Server error (5xx)', 'URL is unknown to Google']


def _session():
    if not paths.GSC_TOKEN.exists():
        return None
    from google.auth.transport.requests import AuthorizedSession
    from google.oauth2.credentials import Credentials
    creds = Credentials.from_authorized_user_info(json.loads(paths.GSC_TOKEN.read_text()), paths.gsc_scopes())
    return AuthorizedSession(creds)


def _cache_file(prop):
    return CACHE_DIR / (re.sub(r'[^\w.-]', '_', prop) + '.json')


def _sitemap_urls(site, limit=None):
    s = requests.Session()
    s.headers['User-Agent'] = 'Mozilla/5.0'
    todo, seen, urls = [urljoin(site, '/sitemap_index.xml'), urljoin(site, '/sitemap.xml')], set(), []
    while todo and (limit is None or len(urls) < limit):
        sm = todo.pop(0)
        if sm in seen:
            continue
        seen.add(sm)
        try:
            r = s.get(sm, timeout=20)
        except requests.RequestException:
            continue
        if r.status_code != 200:
            continue
        locs = re.findall(r'<loc>\s*([^<\s]+)\s*</loc>', r.text)
        if '<sitemapindex' in r.text[:3000]:
            todo.extend(locs)
        else:
            urls.extend(locs)
    return list(dict.fromkeys(urls))[:limit]


def _crawl_urls(crawl_dir):
    from .librecrawl import is_page
    data = json.loads((paths.resolve(crawl_dir) / 'crawl.json').read_text(encoding='utf-8'))
    return [u['url'] for u in data['urls'] if is_page(u) and not urlparse(u['url']).query]


def _in_property(url, prop):
    if prop.startswith('sc-domain:'):
        host = urlparse(url).netloc.lower()
        dom = prop.split(':', 1)[1].lower()
        return host == dom or host.endswith('.' + dom)
    return url.startswith(prop)


def inspect_all(gsc_property, site, out_dir, crawl_dir='', extra_urls=None, daily_budget=1900,
                max_age_days=7, progress=None):
    s = _session()
    if s is None:
        return {'checked': False, 'reason': 'no Search Console sign-in (run hotel-seo-auth)'}
    urls = list(dict.fromkeys((extra_urls or []) + (_crawl_urls(crawl_dir) if crawl_dir else [])
                              + _sitemap_urls(site)))
    urls = [u for u in urls if _in_property(u, gsc_property)]
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cf = _cache_file(gsc_property)
    cache = json.loads(cf.read_text(encoding='utf-8')) if cf.exists() else {}
    today = date.today().isoformat()
    used_today = sum(1 for v in cache.values() if v.get('inspected', '')[:10] == today)
    fresh_after = (date.today() - timedelta(days=max_age_days)).isoformat()
    todo = [u for u in urls if cache.get(u, {}).get('inspected', '') < fresh_after]
    budget = max(0, daily_budget - used_today)
    done, errors, stopped = 0, [], ''
    for n, u in enumerate(todo[:budget], 1):
        try:
            r = s.post(ENDPOINT, json={'inspectionUrl': u, 'siteUrl': gsc_property, 'languageCode': 'en-US'},
                       timeout=60)
        except Exception as e:
            errors.append(f'{u}: {e}')
            continue
        if r.status_code == 429:
            stopped = 'Google quota reached (429); run again tomorrow to continue'
            break
        if r.status_code != 200:
            errors.append(f'{u}: {r.status_code} {r.text[:150]}')
            if r.status_code in (401, 403) and len(errors) >= 3 and done == 0:
                stopped = f'Search Console refused ({r.status_code}): is {gsc_property} visible to the signed-in account?'
                break
            continue
        res = (r.json().get('inspectionResult') or {}).get('indexStatusResult') or {}
        cache[u] = {'inspected': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                    'verdict': res.get('verdict'), 'coverage': res.get('coverageState', ''),
                    'indexing': res.get('indexingState'), 'robots': res.get('robotsTxtState'),
                    'fetch': res.get('pageFetchState'), 'last_crawl': res.get('lastCrawlTime', ''),
                    'google_canonical': res.get('googleCanonical', ''), 'user_canonical': res.get('userCanonical', ''),
                    'crawled_as': res.get('crawledAs', ''), 'in_sitemaps': res.get('sitemap', []),
                    'referring': (res.get('referringUrls') or [])[:3]}
        done += 1
        if done % 25 == 0:
            cf.write_text(json.dumps(cache, ensure_ascii=False), encoding='utf-8')
            if progress:
                progress(f'inspected {done}/{min(len(todo), budget)}')
        time.sleep(0.15)                      # under 600 a minute
    cf.write_text(json.dumps(cache, ensure_ascii=False), encoding='utf-8')

    rows = [dict(url=u, **cache[u]) for u in urls if u in cache]
    groups = defaultdict(list)
    for r in rows:
        groups[r['coverage'] or '(no state)'].append(r['url'])
    canon = [r for r in rows if r['google_canonical'] and r['user_canonical']
             and r['google_canonical'].rstrip('/') != r['user_canonical'].rstrip('/')]
    out = paths.resolve(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / 'index_status.csv', 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, ['url', 'coverage', 'verdict', 'last_crawl', 'google_canonical', 'user_canonical',
                               'robots', 'fetch', 'crawled_as', 'inspected'], extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)
    order = {k: i for i, k in enumerate(ORDER)}
    summary = {k: len(v) for k, v in sorted(groups.items(), key=lambda kv: order.get(kv[0], 99))}
    left = len([u for u in urls if u not in cache])
    result = {'checked': True, 'property': gsc_property, 'urls_known': len(urls), 'inspected_now': done,
              'covered': len(rows), 'not_yet_inspected': left,
              'by_state': summary, 'google_chose_other_canonical': [
                  {'url': r['url'], 'google': r['google_canonical'], 'declared': r['user_canonical']} for r in canon][:50],
              'examples': {k: v[:10] for k, v in groups.items() if k not in ('Submitted and indexed',)},
              'file': str(out / 'index_status.csv'), 'errors': errors[:10], 'stopped': stopped}
    if left:
        result['next'] = (f'{left} URLs still to inspect (2,000 a day per property); run index_status again '
                          'tomorrow to continue. Cached results are reused.')
    (out / 'index_status.json').write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding='utf-8')
    return result
