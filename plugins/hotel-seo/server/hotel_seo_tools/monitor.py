"""Daily monitors: what changed on a hotel site since the last run, before anyone notices.

Each run takes a snapshot and compares it with the previous one (~/.metahotels-seo/monitor/<host>.json):
  - posts: new posts, new or growing suspicious posts (junk, backdated: the Al Bahar "cache" posts)
  - Search Console: spam search terms that weren't there before (last 7 days)
  - booking links on the homepage and the pages it links to: newly dead (4xx/5xx) links
  - tags that fire on the rendered homepage: GTM / GA4 / Ads IDs added or gone
  - homepage: status, title, noindex, canonical; defacement text
  - REST routes (MCP / site control) that answer without logging in
  - Business Profile, for each hotel linked with gbp_link: fields Google changed itself (hours, phone, website,
    categories, address, name), listing changes not in our gbp_apply log, edits waiting for Google review, new 1-2
    star reviews, reviews unanswered for more than 7 days. Alerts start with [High] / [Medium].
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
from datetime import date, datetime, timedelta
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
    try:
        snap['gbp'], why = gbp_snapshot(site)
    except Exception as e:  # noqa: BLE001
        snap['gbp'], why = {}, f'{type(e).__name__}: {str(e)[:200]}'
    if why:
        snap['gbp_reason'] = why
    return snap


# ---------------------------------------------------------------- Google Business Profile

GBP_FIELDS = ('title', 'phone', 'website', 'hours', 'categories', 'address')
GBP_HIGH = {'title', 'phone', 'website', 'hours'}         # the rest are Medium
GBP_LABELS = {'title': 'business name', 'phone': 'phone', 'website': 'website link', 'hours': 'opening hours',
              'categories': 'categories', 'address': 'address'}
GBP_LOW_STARS = 2               # a new review with this many stars or fewer: High
GBP_UNANSWERED_DAYS = 7         # an unanswered review older than this: Medium
GBP_REVIEWS_READ = 100
# Business Information API field paths (diffMask / pendingMask) -> the fields above
_GBP_MASK = (('title', 'title'), ('phoneNumbers', 'phone'), ('websiteUri', 'website'), ('regularHours', 'hours'),
             ('specialHours', 'hours'), ('moreHours', 'hours'), ('categories', 'categories'),
             ('storefrontAddress', 'address'), ('latlng', 'address'), ('serviceArea', 'address'))
# gbp_apply log labels ("Website link", "Opening hours", "BUSINESS NAME (risky)" ...) -> the fields above
_GBP_LOG = (('website', 'website'), ('phone', 'phone'), ('hours', 'hours'), ('categor', 'categories'),
            ('address', 'address'), ('name', 'title'), ('title', 'title'))


def _gbp_hours(h):
    def t(x):
        x = x or {}
        return f"{x.get('hours', 0):02d}:{x.get('minutes', 0):02d}"
    return '; '.join(f"{p.get('openDay', '')[:3]} {t(p.get('openTime'))}-"
                     f"{(p.get('closeDay', '')[:3] + ' ') if p.get('closeDay') != p.get('openDay') else ''}"
                     f"{t(p.get('closeTime'))}" for p in (h or {}).get('periods', []))


def _gbp_fields(loc):
    """The watched listing fields as plain strings (so snapshots compare with ==)."""
    from .gbp import _addr
    ph = loc.get('phoneNumbers') or {}
    cat = loc.get('categories') or {}
    return {'title': loc.get('title', ''),
            'phone': ', '.join(x for x in [ph.get('primaryPhone', ''), *ph.get('additionalPhones', [])] if x),
            'website': loc.get('websiteUri', ''), 'hours': _gbp_hours(loc.get('regularHours')),
            'categories': ' | '.join(x for x in [(cat.get('primaryCategory') or {}).get('displayName', '')]
                                     + [c.get('displayName', '') for c in cat.get('additionalCategories', [])] if x),
            'address': _addr(loc)}


def _gbp_mask(mask):
    out = []
    for part in (mask or '').split(','):
        f = next((v for k, v in _GBP_MASK if part.strip().startswith(k)), None)
        if f and f not in out:
            out.append(f)
    return out


def gbp_state(loc, google_updated, reviews, today=None):
    """One hotel's Business Profile state for the monitor: watched fields, fields Google changed (with Google's
    value), pending edits, and the newest reviews (no reviewer names)."""
    today = today or date.today()
    md = loc.get('metadata') or {}
    gu = google_updated or {}
    gfields = _gbp_fields(gu.get('location') or {}) if gu.get('location') else {}
    changed = _gbp_mask(gu.get('diffMask')) if md.get('hasGoogleUpdated') or gu.get('diffMask') else []
    cutoff = (today - timedelta(days=GBP_UNANSWERED_DAYS)).isoformat()
    revs = [{'id': r.get('review_id', ''), 'stars': r.get('stars'), 'date': r.get('date', ''),
             'replied': bool(r.get('replied')), 'comment': (r.get('comment') or '')[:160]}
            for r in (reviews or {}).get('reviews', [])]
    return {'location': loc.get('name', ''), 'title': loc.get('title', ''), 'fields': _gbp_fields(loc),
            'google_updated': {f: gfields.get(f, '') for f in changed},
            'pending_edits': bool(md.get('hasPendingEdits')), 'pending_fields': _gbp_mask(gu.get('pendingMask')),
            'reviews': revs,
            'unanswered_old': sorted(r['id'] for r in revs if not r['replied'] and r['date'] and r['date'] < cutoff),
            'rating': (reviews or {}).get('average_rating'), 'review_count': (reviews or {}).get('total')}


def gbp_snapshot(site):
    """{slug: gbp_state} for every hotel of the site whose Business Profile is linked (gbp_link), and a reason when
    none is checked. A hotel whose read fails gets {"error": ...}."""
    from . import gbp
    from . import group as grp
    host = _host(site)
    d = paths.resolve(host)
    reg = grp.load(d) if d.is_dir() else None
    if not reg:
        return {}, 'no site.json for this site in the work folder'
    linked = {h['slug']: gbp.hotel_location(host, h['slug']) for h in reg.get('hotels', [])}
    linked = {k: v for k, v in linked.items() if v.get('location')}
    if not linked:
        return {}, 'no hotel linked to its Business Profile (gbp_link)'
    ok, why = gbp.configured()
    if not ok:
        return {}, why
    out = {}
    for slug, link in linked.items():
        name = link['location']
        try:
            loc = gbp._get(f'{gbp.INFO}/{name}', {'readMask': gbp.READ_MASK})
            md = loc.get('metadata') or {}
            gu = gbp._get(f'{gbp.INFO}/{name}:getGoogleUpdated', {'readMask': gbp.READ_MASK}) \
                if md.get('hasGoogleUpdated') or md.get('hasPendingEdits') else {}
            account = link.get('account') or gbp._find(name)[0]
            revs = gbp._reviews(account, name, GBP_REVIEWS_READ)
            out[slug] = gbp_state(loc, gu, revs)
        except Exception as e:  # noqa: BLE001 - one profile failing must not stop the monitor
            out[slug] = {'error': f'{type(e).__name__}: {str(e)[:300]}'}
    return out, ''


def gbp_log(path=None):
    """Our applied Business Profile changes (gbp_apply's ~/.metahotels-seo/gbp-changes.jsonl)."""
    if path is None:
        from .gbp_write import LOG as path
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding='utf-8').splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def _when(s):
    try:
        d = datetime.fromisoformat(str(s).replace('Z', '+00:00'))
    except ValueError:
        return None
    return d if d.tzinfo else d.astimezone()      # a naive time is this machine's local time


def _ours(log, location, field, since):
    """The gbp_apply change that set this field on this profile after `since`, or None."""
    lid = str(location).split('/')[-1]
    t0 = _when(since)
    for r in reversed(log):
        if str(r.get('location', '')).split('/')[-1] != lid or r.get('status') == 'failed':
            continue
        t = _when(r.get('when'))
        if t0 and t and t < t0:
            continue
        for c in r.get('changes', []):
            what = str(c.get('what', '')).lower()
            if next((f for k, f in _GBP_LOG if k in what), None) == field:
                return r
    return None


def _any_ours(log, location, since):
    lid, t0 = str(location).split('/')[-1], _when(since)
    return any(str(r.get('location', '')).split('/')[-1] == lid and r.get('status') != 'failed'
               and not (t0 and _when(r.get('when')) and _when(r.get('when')) < t0) for r in log)


def _sev(field):
    return 'High' if field in GBP_HIGH else 'Medium'


def compare_gbp(old, new, log, since):
    """Business Profile alerts and changes for one site: {slug: gbp_state} then and now. A hotel seen for the first
    time is a baseline: no alerts. Alerts start with their severity: [High] / [Medium]."""
    alerts, changes = [], []
    for slug, n in sorted((new or {}).items()):
        if n.get('error'):
            changes.append(f"Business Profile ({slug}) not checked: {n['error']}")
            continue
        o = (old or {}).get(slug)
        who = f"Business Profile ({n.get('title') or slug})"
        if not o or o.get('error'):
            changes.append(f"{who}: baseline saved" + (
                f"; Google's own changes waiting: {', '.join(GBP_LABELS[f] for f in n['google_updated'])}"
                if n.get('google_updated') else '') + '.')
            continue
        for f in GBP_FIELDS:                              # fields Google changed itself
            if f in n.get('google_updated', {}) and f not in (o.get('google_updated') or {}):
                alerts.append(f"[{_sev(f)}] {who}: Google changed the {GBP_LABELS[f]} to "
                              f"\"{n['google_updated'][f]}\" (listing: \"{n['fields'].get(f, '')}\"). Accept or "
                              'reject it in the profile.')
        for f in GBP_FIELDS:                              # changed since the last run
            a, b = (o.get('fields') or {}).get(f), (n.get('fields') or {}).get(f)
            if a is None or a == b:
                continue
            mine = _ours(log, n.get('location') or o.get('location', ''), f, since)
            if mine:
                changes.append(f"{who}: {GBP_LABELS[f]} changed by our change {mine.get('id', '')} "
                               f"(\"{a}\" → \"{b}\").")
            else:
                alerts.append(f"[{_sev(f)}] {who}: {GBP_LABELS[f]} changed outside our changes (not in the gbp_apply "
                              f"log): \"{a}\" → \"{b}\".")
        if n.get('pending_edits') and not o.get('pending_edits'):
            fs = n.get('pending_fields') or []
            ours = all(_ours(log, n.get('location', ''), f, since) for f in fs) if fs else \
                _any_ours(log, n.get('location', ''), since)
            (changes if ours else alerts).append(
                ('' if ours else '[Medium] ') + f"{who}: edits waiting for Google review"
                + (f" ({', '.join(GBP_LABELS[f] for f in fs)})" if fs else '')
                + ('' if ours else ', not sent by us') + '.')
        seen = {r['id'] for r in o.get('reviews') or []}
        day0 = (str(since)[:10]) if since else ''
        for r in n.get('reviews') or []:
            if r['id'] in seen or not r.get('stars') or r['stars'] > GBP_LOW_STARS:
                continue
            if day0 and r.get('date') and r['date'] < (date.fromisoformat(day0) - timedelta(days=1)).isoformat():
                continue                                  # an old review that moved into the newest ones read
            alerts.append(f"[High] {who}: new {r['stars']}-star review ({r.get('date')})"
                          + (f": \"{r['comment']}\"" if r.get('comment') else '') + '. Reply today.')
        aged = sorted(set(n.get('unanswered_old') or []) - set(o.get('unanswered_old') or []))
        if aged:
            dates = {r['id']: r for r in n.get('reviews') or []}
            alerts.append(f"[Medium] {who}: {len(aged)} review(s) unanswered for more than {GBP_UNANSWERED_DAYS} days: "
                          + '; '.join(f"{(dates.get(i) or {}).get('stars', '?')}★ {(dates.get(i) or {}).get('date', '')}"
                                      for i in aged[:8]) + '.')
        still = len(set(n.get('unanswered_old') or []) & set(o.get('unanswered_old') or []))
        if still:
            changes.append(f"{who}: {still} older review(s) still unanswered.")
        if n.get('rating') is not None and o.get('rating') is not None and n['rating'] != o['rating']:
            changes.append(f"{who}: rating {o['rating']} → {n['rating']} ({n.get('review_count')} reviews).")
    return alerts, changes


def compare(old, new, gbp_changes=None):
    """Alerts (need action) and changes (worth knowing) between two snapshots. gbp_changes: our applied Business
    Profile changes (default: read from the gbp_apply log when the snapshot has Business Profile data)."""
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
    if new.get('gbp'):
        ga, gc = compare_gbp(old.get('gbp'), new['gbp'], gbp_log() if gbp_changes is None else gbp_changes,
                             old.get('taken'))
        alerts += ga
        changes += gc
    return alerts, changes


def run(site, gsc_property='', out_dir=''):
    DIR.mkdir(parents=True, exist_ok=True)
    host = _host(site)
    state = DIR / f'{host}.json'
    old = json.loads(state.read_text(encoding='utf-8')) if state.exists() else None
    new = snapshot(site, gsc_property)
    alerts, changes = compare(old, new)
    for slug, g in (new.get('gbp') or {}).items():      # a failed read keeps the last good state as the baseline
        if g.get('error') and ((old or {}).get('gbp') or {}).get(slug) and not old['gbp'][slug].get('error'):
            new['gbp'][slug] = {**old['gbp'][slug], 'last_error': g['error']}
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
              f"rendered tags {'(not checked)' if new.get('tags') is None else ''}, "
              f"Business Profile: {len(new.get('gbp') or {})} linked profile(s)"
              f"{' (not checked: ' + new['gbp_reason'] + ')' if new.get('gbp_reason') else ''}"]
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
