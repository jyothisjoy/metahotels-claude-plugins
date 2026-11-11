"""Daily monitors: what changed on a hotel site since the last run, before anyone notices.

Each run takes a snapshot and compares it with the previous one (~/.metahotels-seo/monitor/<host>.json):
  - posts: new posts, new or growing suspicious posts (junk, backdated: the Al Bahar "cache" posts)
  - Search Console: spam search terms that weren't there before (last 7 days)
  - booking links on the homepage and the pages it links to: newly dead (4xx/5xx) links
  - tags that fire on the rendered homepage: GTM / GA4 / Ads IDs added or gone
  - homepage: status, title, noindex, canonical; defacement text
  - REST routes (MCP / site control) that answer without logging in
The first run is the baseline (kept per machine in ~/.metahotels-seo/monitor/<host>.json). Reports go to <out_dir>,
by default the site folder of the work folder: <domain>/monitor/ for a single hotel, <domain>/group/monitor/ for a
group (paths.py / group.py layout); ~/.metahotels-seo/monitor/reports when the work folder has no <domain>/ folder
(e.g. the scheduled run started outside it).

Run from Claude (monitor_site), or on a schedule with the hotel-seo-monitor command, which reads the
site list from ~/.metahotels-seo/monitor/sites.json.
"""
import argparse
import hashlib
import json
import re
from datetime import date, datetime
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from . import analysis, audit, paths
from .librecrawl import UA

DIR = paths.HOME / 'monitor'
SITES = DIR / 'sites.json'


def _host(site):
    return urlparse(site if '//' in site else f'https://{site}').netloc.replace('www.', '')


def _site_url(site):
    return site.rstrip('/') if '//' in site else f'https://{site.strip("/")}'


def report_dir(site):
    """Default report folder: the site folder of the hotel's work folder, else the machine-wide reports folder."""
    host = _host(site)
    d = paths.resolve(host)
    if d.is_dir():
        from . import group as grp
        reg = grp.load(d)
        return (grp.site_dir(d, reg) if reg else d) / 'monitor'
    return DIR / 'reports'


def _page_state(r, soup):
    robots = soup.find('meta', attrs={'name': re.compile('^robots$', re.I)})
    canon = soup.find('link', rel=lambda v: v and 'canonical' in v)
    types = []
    for t in soup.find_all('script', type='application/ld+json'):
        types += re.findall(r'"@type"\s*:\s*"([^"]+)"', t.get_text() or '')
    return {'status': r.status_code,
            'noindex': 'noindex' in (((robots.get('content') or '') if robots else '')
                                     + ' ' + r.headers.get('X-Robots-Tag', '')).lower(),
            'canonical': canon.get('href', '') if canon else '',
            'title': (soup.title.get_text() if soup.title else '').strip(),
            'h1': [h.get_text(' ', strip=True) for h in soup.find_all('h1')][:3],
            'schema_types': sorted(set(types))}


def snapshot(site, gsc_property=''):
    site = _site_url(site)
    host = _host(site)
    s = requests.Session()
    s.headers['User-Agent'] = UA
    snap = {'taken': datetime.now().isoformat(timespec='seconds'), 'site': site}

    r = audit._get(s, site + '/', allow_redirects=True)
    home = {'status': r.status_code if r is not None else 0, 'final_url': r.url if r is not None else ''}
    links, texts, pages = [], {}, {}
    if r is not None and r.status_code == 200:
        soup = BeautifulSoup(r.text, 'html.parser')
        robots = soup.find('meta', attrs={'name': re.compile('^robots$', re.I)})
        canon = soup.find('link', rel=lambda v: v and 'canonical' in v)
        home.update({'title': (soup.title.get_text() if soup.title else '').strip(),
                     'noindex': 'noindex' in ((robots.get('content') or '') if robots else '').lower()
                     + r.headers.get('X-Robots-Tag', '').lower(),
                     'canonical': canon.get('href', '') if canon else ''})
        internal = []
        for a in soup.find_all('a', href=True):
            href = urljoin(r.url, a['href']).split('#')[0]
            if audit.is_booking_href(href) or audit.BOOK_TEXT.search(a.get_text(' ')):
                links.append({'source': r.url, 'href': href, 'text': a.get_text(' ', strip=True)[:80]})
            elif _host(href) == host and href.startswith('http') and not urlparse(href).query:
                internal.append(href)
        texts[r.url] = soup.get_text(' ')
        # booking links on the pages the homepage links to (rooms, offers, menu pages)
        for u in list(dict.fromkeys(internal))[:40]:
            pr = audit._get(s, u)
            if pr is not None and pr.status_code != 200:
                pages[u] = {'status': pr.status_code}
            if pr is None or pr.status_code != 200 or 'html' not in pr.headers.get('content-type', ''):
                continue
            ps = BeautifulSoup(pr.text, 'html.parser')
            pages[u] = _page_state(pr, ps)
            for a in ps.find_all('a', href=True):
                href = urljoin(u, a['href']).split('#')[0]
                if audit.is_booking_href(href) or audit.BOOK_TEXT.search(a.get_text(' ')):
                    links.append({'source': u, 'href': href, 'text': a.get_text(' ', strip=True)[:80]})
            for t in ps(['script', 'style']):
                t.decompose()
            texts[u] = ps.get_text(' ')
    snap['home'] = home
    # the key pages the homepage links to (rooms, offers, contact, menu pages): a template or plugin update,
    # or a staging push, can noindex or strip them all without touching the homepage
    snap['pages'] = pages
    rb = audit._get(s, site + '/robots.txt')
    rtext = rb.text if rb is not None and rb.status_code == 200 else ''
    snap['robots_txt'] = {'status': rb.status_code if rb is not None else 0,
                          'hash': hashlib.sha1(rtext.encode()).hexdigest()[:12] if rtext else '',
                          'blocks_googlebot_home': not analysis.robots_allowed(rtext, 'Googlebot', '/'),
                          'ai_search_bots_blocked': [b for b in analysis.AI_SEARCH_BOTS
                                                     if not analysis.robots_allowed(rtext, b, '/')]}
    bl = audit.check_booking_links(links) if links else {'dead': [], 'unique_links_checked': 0}
    snap['booking_links_checked'] = bl['unique_links_checked']
    snap['booking_dead'] = sorted({f"{d['href']} ({d['status']}) on {d['source']}" for d in bl['dead']})
    snap['defacement'] = [h['text'] for h in analysis.hacked_text(texts)]

    wp = audit.wordpress(site)
    if wp.get('is_wordpress_api'):
        ps = wp['posts']
        snap['posts'] = {'total': ps['total'], 'suspicious_count': ps['suspicious_count'],
                         'suspicious_ids': sorted(x['id'] for x in ps['suspicious']),
                         'suspicious_titles': {str(x['id']): f"{x['title'] or x['slug']} (dated {x['published'][:10]})"
                                               for x in ps['suspicious']},
                         'latest_suspicious_change': ps['latest_suspicious_change']}
        snap['open_routes'] = [m['namespace'] for m in wp.get('mcp_endpoints', []) if m['open_without_login']]
        snap['users_public'] = wp.get('users', [])
    if gsc_property:
        sp = audit.gsc_spam_queries(gsc_property, days=7)
        snap['spam_queries'] = sorted({h['query'] for h in sp.get('spam_hits', [])}) if sp.get('checked') else None
        if not sp.get('checked'):
            snap['spam_queries_reason'] = sp.get('reason')
    try:
        from . import pagecheck
        res = pagecheck.inspect([site + '/'], DIR / 'render' / host, viewports=('desktop',))
        t = res['results'][0].get('tags_fired') or {}
        snap['tags'] = {'gtm': t.get('gtm', []), 'ga4': t.get('ga4', []), 'google_ads': t.get('google_ads', []),
                        'meta_pixel': t.get('meta_pixel', False)}
    except Exception as e:  # noqa: BLE001
        snap['tags'] = None
        snap['tags_reason'] = str(e)[:200]
    return snap


def compare(old, new):
    """Alerts (need action) and changes (worth knowing) between two snapshots."""
    alerts, changes = [], []
    if not old:
        return alerts, ['First run: baseline saved; changes show from the next run.']
    oh, nh = old.get('home', {}), new.get('home', {})
    if nh.get('status') != 200:
        alerts.append(f"Homepage returns {nh.get('status')}")
    if nh.get('noindex') and not oh.get('noindex'):
        alerts.append('Homepage is now NOINDEX: Google will drop it')
    if oh.get('title') and nh.get('title') != oh.get('title'):
        changes.append(f"Homepage title changed: \"{oh.get('title')}\" → \"{nh.get('title')}\"")
    if oh.get('canonical') and nh.get('canonical') != oh.get('canonical'):
        alerts.append(f"Homepage canonical changed: {oh.get('canonical')} → {nh.get('canonical')}")
    if new.get('defacement'):
        alerts.append(f"Defacement text on the site: {new['defacement']}")
    orb, nrb = old.get('robots_txt') or {}, new.get('robots_txt') or {}
    if nrb.get('blocks_googlebot_home') and not orb.get('blocks_googlebot_home'):
        alerts.append('robots.txt now blocks Googlebot from the homepage (staging setting pushed live?)')
    nb = sorted(set(nrb.get('ai_search_bots_blocked') or []) - set(orb.get('ai_search_bots_blocked') or []))
    if nb and orb:
        alerts.append(f"robots.txt now blocks AI search crawlers: {nb}")
    if orb.get('hash') and nrb.get('hash') and orb['hash'] != nrb['hash']:
        changes.append('robots.txt changed')
    # key pages: only pages seen in both runs, so a menu change isn't reported as a breakage
    op_, np2 = old.get('pages') or {}, new.get('pages') or {}
    for u in sorted(set(op_) & set(np2)):
        o, n = op_[u], np2[u]
        if n.get('status') != o.get('status') and n.get('status', 0) >= 400:
            alerts.append(f"{u} now returns {n.get('status')} (was {o.get('status')})")
            continue
        if n.get('noindex') and not o.get('noindex'):
            alerts.append(f"{u} is now NOINDEX")
        if o.get('canonical') and n.get('canonical') != o.get('canonical'):
            alerts.append(f"{u} canonical changed: {o['canonical']} → {n.get('canonical') or '(none)'}")
        if o.get('h1') and not n.get('h1'):
            alerts.append(f"{u} lost its H1 (was \"{o['h1'][0]}\")")
        lost = sorted(set(o.get('schema_types') or []) - set(n.get('schema_types') or []))
        if lost and set(lost) & {'Hotel', 'Resort', 'LodgingBusiness', 'HotelRoom', 'Offer', 'BreadcrumbList'}:
            alerts.append(f"{u} lost schema: {lost}")
        if o.get('title') and n.get('title') != o.get('title'):
            changes.append(f"{u} title: \"{o['title']}\" → \"{n.get('title')}\"")
    new_dead = sorted(set(new.get('booking_dead', [])) - set(old.get('booking_dead', [])))
    if new_dead:
        alerts.append(f"{len(new_dead)} booking link(s) newly dead: " + '; '.join(new_dead[:8]))
    fixed = sorted(set(old.get('booking_dead', [])) - set(new.get('booking_dead', [])))
    if fixed:
        changes.append(f"{len(fixed)} dead booking link(s) fixed")
    op, np_ = old.get('posts') or {}, new.get('posts') or {}
    if np_:
        added = sorted(set(np_.get('suspicious_ids', [])) - set(op.get('suspicious_ids', [])))
        if added:
            alerts.append(f"{len(added)} new suspicious post(s) (total now {np_['suspicious_count']}): "
                          + '; '.join(np_['suspicious_titles'].get(str(i), str(i)) for i in added[:8]))
        if np_.get('total', 0) > op.get('total', 0) and not added:
            changes.append(f"{np_['total'] - op.get('total', 0)} new post(s) (total {np_['total']})")
    opened = sorted(set(new.get('open_routes') or []) - set(old.get('open_routes') or []))
    if opened:
        alerts.append(f"REST routes now answering without login: {opened}")
    if new.get('open_routes'):
        changes.append(f"Still open without login: {new['open_routes']}")
    new_users = sorted(set(new.get('users_public') or []) - set(old.get('users_public') or []))
    if new_users and old.get('users_public') is not None:
        alerts.append(f"New WordPress user(s): {new_users}")
    if new.get('spam_queries') is not None and old.get('spam_queries') is not None:
        sq = sorted(set(new['spam_queries']) - set(old['spam_queries']))
        if sq:
            alerts.append(f"New spam search terms in Search Console: {sq[:10]}")
    ot, nt = old.get('tags'), new.get('tags')
    if ot and nt:
        for k in ('gtm', 'ga4', 'google_ads'):
            gone, came = sorted(set(ot[k]) - set(nt[k])), sorted(set(nt[k]) - set(ot[k]))
            if gone:
                alerts.append(f"{k.upper()} tag stopped firing on the homepage: {gone}")
            if came:
                changes.append(f"New {k.upper()} tag firing: {came}")
        if ot.get('meta_pixel') and not nt.get('meta_pixel'):
            alerts.append('Meta pixel stopped firing on the homepage')
    return alerts, changes


def run(site, gsc_property='', out_dir=''):
    DIR.mkdir(parents=True, exist_ok=True)
    host = _host(site)
    state = DIR / f'{host}.json'
    old = json.loads(state.read_text(encoding='utf-8')) if state.exists() else None
    new = snapshot(site, gsc_property)
    alerts, changes = compare(old, new)
    state.write_text(json.dumps(new, indent=1, ensure_ascii=False), encoding='utf-8')
    out = paths.resolve(out_dir) if out_dir else report_dir(site)
    out.mkdir(parents=True, exist_ok=True)
    stamp = date.today().isoformat()
    lines = [f'# Monitor: {host} · {stamp}', '', f"Compared with {old['taken'] if old else 'nothing (first run)'}.", '']
    lines += ['## Alerts', ''] + ([f'- {a}' for a in alerts] or ['- none']) + ['']
    lines += ['## Changes', ''] + ([f'- {c}' for c in changes] or ['- none']) + ['']
    lines += [f"Checked: homepage, {new.get('booking_links_checked', 0)} booking links, "
              f"{(new.get('posts') or {}).get('total', 'n/a')} posts, Search Console spam terms "
              f"{'(not checked: ' + str(new.get('spam_queries_reason')) + ')' if new.get('spam_queries') is None else ''}, "
              f"rendered tags {'(not checked)' if new.get('tags') is None else ''}"]
    report = out / f'monitor-{host}-{stamp}.md'
    report.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return {'site': host, 'alerts': alerts, 'changes': changes, 'report': str(report), 'baseline': old is None}


def sites():
    return json.loads(SITES.read_text(encoding='utf-8')) if SITES.exists() else []


def add_site(site, gsc_property=''):
    DIR.mkdir(parents=True, exist_ok=True)
    lst = [x for x in sites() if _host(x['site']) != _host(site)]
    lst.append({'site': _site_url(site), 'gsc_property': gsc_property})
    SITES.write_text(json.dumps(lst, indent=1), encoding='utf-8')
    return lst


def main():
    """hotel-seo-monitor: run the monitors for the given sites, or every site in sites.json."""
    ap = argparse.ArgumentParser(description='Daily hotel site monitors (see ~/.metahotels-seo/monitor).')
    ap.add_argument('sites', nargs='*', help='domains; default: every site in sites.json')
    ap.add_argument('--gsc', default='', help='Search Console property for a single site')
    ap.add_argument('--add', action='store_true', help='add the given site(s) to sites.json and exit')
    args = ap.parse_args()
    if args.add:
        for s in args.sites:
            add_site(s, args.gsc)
        print(f'{len(sites())} site(s) in {SITES}')
        return
    todo = [{'site': s, 'gsc_property': args.gsc} for s in args.sites] or sites()
    if not todo:
        raise SystemExit(f'No sites: give domains or add them with --add ({SITES}).')
    any_alert = False
    for t in todo:
        try:
            res = run(t['site'], t.get('gsc_property', ''))
        except Exception as e:  # noqa: BLE001 - one broken site must not stop the others
            print(f"{t['site']}: FAILED {e}")
            continue
        any_alert |= bool(res['alerts'])
        print(f"{res['site']}: {len(res['alerts'])} alert(s), {len(res['changes'])} change(s) -> {res['report']}")
        for a in res['alerts']:
            print(f'  ALERT {a}')
    raise SystemExit(1 if any_alert else 0)


if __name__ == '__main__':
    main()
