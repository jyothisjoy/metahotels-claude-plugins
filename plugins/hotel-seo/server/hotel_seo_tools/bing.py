"""Bing Webmaster Tools API: incoming links (instead of Search Console's Links export, which has no
API) and Bing sitemap status (instead of the Bing sitemap screenshot in the re-check).

Needs a Bing Webmaster API key (Bing Webmaster Tools -> Settings -> API access -> API key), stored
once per machine with `hotel-seo-bing-login` (typed by the user, hidden). One key covers every site
in that Bing account.
"""
import argparse
import getpass
import json
import re
from datetime import datetime, timezone

import requests

from . import paths

CONFIG = paths.HOME / 'bing.json'
BASE = 'https://ssl.bing.com/webmaster/api.svc/json/'


def configured():
    return (True, '') if CONFIG.exists() else (False, f'no Bing API key: run hotel-seo-bing-login ({CONFIG})')


def _call(method, **params):
    key = json.loads(CONFIG.read_text())['api_key']
    r = requests.get(BASE + method, params=dict(params, apikey=key), timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f'Bing {method}: {r.status_code} {r.text[:200]}')
    return r.json().get('d')


def _date(v):
    m = re.search(r'/Date\((-?\d+)', str(v or ''))
    return datetime.fromtimestamp(int(m.group(1)) / 1000, tz=timezone.utc).date().isoformat() if m else v


def _site(site):
    """Bing site URLs are the registered form, e.g. https://hotel.com/ ; match ours to one."""
    sites = [x.get('Url', '') for x in _call('GetUserSites') or []]
    host = re.sub(r'^https?://(www\.)?', '', site).strip('/')
    for s in sites:
        if re.sub(r'^https?://(www\.)?', '', s).strip('/') == host:
            return s, sites
    return None, sites


def report(site, out_dir='', max_pages=20, detail_targets=10):
    ok, why = configured()
    if not ok:
        return {'checked': False, 'reason': why}
    try:
        bsite, sites = _site(site)
        if not bsite:
            return {'checked': True, 'found': False,
                    'reason': f'{site} is not in this Bing Webmaster account (add and verify it there; '
                              'it can be imported from Search Console)', 'sites_in_account': sites[:30]}
        targets, page, total = [], 0, 1
        while page < total and page < max_pages:
            d = _call('GetLinkCounts', siteUrl=bsite, page=page) or {}
            targets += [{'page': x.get('Url'), 'links': x.get('Count')} for x in d.get('Links') or []]
            total = int(d.get('TotalPages') or 1)
            page += 1
        targets.sort(key=lambda x: -(x['links'] or 0))
        details = {}
        for t in targets[:detail_targets]:
            d = _call('GetUrlLinks', siteUrl=bsite, link=t['page'], page=0) or {}
            details[t['page']] = [{'from': x.get('Url'), 'anchor': x.get('AnchorText')} for x in d.get('Details') or []][:50]
        feeds = [{'sitemap': f.get('Url'), 'status': f.get('Status'), 'urls': f.get('UrlCount'),
                  'last_crawled': _date(f.get('LastCrawled')), 'submitted': _date(f.get('Submitted'))}
                 for f in _call('GetFeeds', siteUrl=bsite) or []]
    except Exception as e:
        return {'checked': False, 'reason': f'{type(e).__name__}: {str(e)[:300]}'}
    domains = {}
    for links in details.values():
        for l in links:
            dom = re.sub(r'^https?://(www\.)?', '', l['from'] or '').split('/')[0]
            domains[dom] = domains.get(dom, 0) + 1
    result = {'checked': True, 'found': True, 'bing_site': bsite,
              'linked_pages': len(targets), 'total_links': sum(t['links'] or 0 for t in targets),
              'top_linked_pages': targets[:25], 'linking_domains_sample': dict(sorted(domains.items(), key=lambda kv: -kv[1])[:30]),
              'links_to_top_pages': details, 'sitemaps': feeds}
    if out_dir:
        out = paths.resolve(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / 'bing.json').write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding='utf-8')
        result['file'] = str(out / 'bing.json')
    return result


def login():
    """hotel-seo-bing-login: store the Bing Webmaster API key (typed, hidden)."""
    argparse.ArgumentParser(description='Save the Bing Webmaster Tools API key.').parse_args()
    key = getpass.getpass('Bing Webmaster API key (hidden): ').strip()
    if not key:
        raise SystemExit('Nothing saved.')
    paths.HOME.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps({'api_key': key}))
    try:
        CONFIG.chmod(0o600)
    except OSError:
        pass
    try:
        sites = [x.get('Url') for x in _call('GetUserSites') or []]
        print(f'Saved. The key sees {len(sites)} sites.')
    except Exception as e:
        print(f'Saved, but the test call failed: {e}')


if __name__ == '__main__':
    login()
