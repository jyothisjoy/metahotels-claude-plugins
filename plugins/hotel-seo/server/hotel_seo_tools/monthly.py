"""Monthly Report: one client-facing report per hotel per calendar month, plus a group page.

Folders, per hotel folder (a single-hotel site: <domain>/ itself; a group: <domain>/hotels/<slug>/):
  <hotel dir>/monthly-settings.json          Search Console / GA4 property and home page (found once, reused)
  <hotel dir>/tracked-keywords.json          keywords followed every month (proposed from the keyword map,
                                               confirmed by the user)
  <hotel dir>/work-log.csv                   work done by hand: date, what, page, who
  <hotel dir>/monthly-<YYYY-MM>/data.json    every number for the month (collect)
  <hotel dir>/monthly-<YYYY-MM>/serp.json    Serper positions (serp.run)
  <hotel dir>/monthly-<YYYY-MM>/manual.json  what Claude read in Chrome (Business Profile, Search Console security)
  <hotel dir>/monthly-<YYYY-MM>/narrative.json  Claude's plain-language lines (numbers checked against the data)
  <hotel dir>/monthly-<YYYY-MM>/monthly-report.json  the document (render_report)
  group/monthly-<YYYY-MM>/                     the group page (group sites only)

Every number comes from code: Search Console, GA4, Mirai, rate parity, URL Inspection, Serper, execute logs.
The period is a calendar month compared with the month before and the same month last year.
"""
import calendar
import csv
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from . import ga4, group as grp, paths

MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October',
          'November', 'December']
GSC_LAG_DAYS = 3
COUNTRIES = {
    'are': 'United Arab Emirates', 'ind': 'India', 'gbr': 'United Kingdom', 'sau': 'Saudi Arabia',
    'kwt': 'Kuwait', 'qat': 'Qatar', 'omn': 'Oman', 'bhr': 'Bahrain', 'egy': 'Egypt', 'jor': 'Jordan',
    'lbn': 'Lebanon', 'pak': 'Pakistan', 'bgd': 'Bangladesh', 'lka': 'Sri Lanka', 'npl': 'Nepal', 'phl': 'Philippines',
    'usa': 'United States', 'can': 'Canada', 'aus': 'Australia', 'nzl': 'New Zealand', 'deu': 'Germany',
    'fra': 'France', 'ita': 'Italy', 'esp': 'Spain', 'nld': 'Netherlands', 'bel': 'Belgium', 'che': 'Switzerland',
    'aut': 'Austria', 'swe': 'Sweden', 'nor': 'Norway', 'dnk': 'Denmark', 'fin': 'Finland', 'irl': 'Ireland',
    'pol': 'Poland', 'cze': 'Czechia', 'rou': 'Romania', 'hun': 'Hungary', 'grc': 'Greece', 'prt': 'Portugal',
    'tur': 'Türkiye', 'rus': 'Russia', 'ukr': 'Ukraine', 'kaz': 'Kazakhstan', 'uzb': 'Uzbekistan', 'aze': 'Azerbaijan',
    'arm': 'Armenia', 'geo': 'Georgia', 'irn': 'Iran', 'irq': 'Iraq', 'syr': 'Syria', 'yem': 'Yemen', 'sdn': 'Sudan',
    'mar': 'Morocco', 'dza': 'Algeria', 'tun': 'Tunisia', 'lby': 'Libya', 'nga': 'Nigeria', 'gha': 'Ghana',
    'ken': 'Kenya', 'eth': 'Ethiopia', 'zaf': 'South Africa', 'uga': 'Uganda', 'tza': 'Tanzania', 'chn': 'China',
    'hkg': 'Hong Kong', 'twn': 'Taiwan', 'jpn': 'Japan', 'kor': 'South Korea', 'sgp': 'Singapore', 'mys': 'Malaysia',
    'idn': 'Indonesia', 'tha': 'Thailand', 'vnm': 'Vietnam', 'bra': 'Brazil', 'mex': 'Mexico', 'arg': 'Argentina',
    'col': 'Colombia', 'chl': 'Chile', 'mdv': 'Maldives', 'afg': 'Afghanistan', 'isr': 'Israel', 'cyp': 'Cyprus',
}


# ---------------------------------------------------------------- periods and formatting

def default_month(today=None):
    today = today or date.today()
    first = today.replace(day=1)
    last_month = first - timedelta(days=1)
    return f'{last_month.year}-{last_month.month:02d}'


def periods(month):
    """{'current', 'previous', 'last_year'}: (start, end) dates of calendar months."""
    if not re.fullmatch(r'\d{4}-\d{2}', month or ''):
        raise ValueError('month must be YYYY-MM, e.g. 2026-10')
    y, m = map(int, month.split('-'))
    if not 1 <= m <= 12:
        raise ValueError('month must be YYYY-MM with a month 01-12')

    def rng(yy, mm):
        return date(yy, mm, 1), date(yy, mm, calendar.monthrange(yy, mm)[1])
    py, pm = (y, m - 1) if m > 1 else (y - 1, 12)
    return {'current': rng(y, m), 'previous': rng(py, pm), 'last_year': rng(y - 1, m)}


def label(month, short=False):
    y, m = map(int, month.split('-'))
    return f'{MONTHS[m - 1][:3] if short else MONTHS[m - 1]} {y}'


def provisional(month, today=None):
    """Search Console needs a few days after the month ends; a report run earlier is provisional."""
    end = periods(month)['current'][1]
    return (today or date.today()) <= end + timedelta(days=GSC_LAG_DAYS)


def fmt(v, dec=0):
    if v is None:
        return '–'
    if isinstance(v, str):
        return v
    if dec:
        return f'{v:,.{dec}f}'
    return f'{round(v):,}'


def change(cur, prev, lower_is_better=False, dec=0, pct_min=20):
    """▲ / ▼ line: percentage only when the base is at least pct_min (3 → 12 is "+9", not "+300%")."""
    if cur is None:
        return {'text': 'not measured', 'dir': None}
    if prev is None:
        return {'text': 'no earlier data', 'dir': None}
    diff = cur - prev
    if abs(diff) < (0.05 if dec else 0.5):
        return {'text': f'• same as before ({fmt(prev, dec)})', 'dir': 'flat'}
    good = diff < 0 if lower_is_better else diff > 0
    arrow = '▲' if good else '▼'
    if lower_is_better:                       # positions: smaller is better
        return {'text': f"{arrow} {'up' if good else 'down'} from {fmt(prev, dec)}", 'dir': 'up' if good else 'down'}
    if prev and abs(prev) >= pct_min:
        pct = round(100 * diff / prev)
        return {'text': f"{arrow} {'+' if diff > 0 else '−'}{abs(pct)}% (from {fmt(prev, dec)})",
                'dir': 'up' if good else 'down'}
    return {'text': f"{arrow} {'+' if diff > 0 else '−'}{fmt(abs(diff), dec)} (from {fmt(prev, dec)})",
            'dir': 'up' if good else 'down'}


# ---------------------------------------------------------------- hotel context

def _host(u):
    return urlparse(u or '').netloc.lower().replace('www.', '')


_GSC_FOUND = {}


def _gsc_property(host):
    if host not in _GSC_FOUND or _GSC_FOUND[host][0] is None:
        _GSC_FOUND[host] = _find_gsc_property(host)
    return _GSC_FOUND[host]


def _find_gsc_property(host):
    from .analysis import _gsc
    s = _gsc()
    if s is None:
        return None, 'no Search Console sign-in (run hotel-seo-auth)'
    r = s.get('https://www.googleapis.com/webmasters/v3/sites', timeout=60)
    if r.status_code != 200:
        return None, f'Search Console {r.status_code}: {r.text[:150]}'
    sites = [x['siteUrl'] for x in r.json().get('siteEntry', [])
             if x.get('permissionLevel') != 'siteUnverifiedUser']
    for cand in (f'sc-domain:{host}', f'https://{host}/', f'https://www.{host}/', f'http://{host}/'):
        if cand in sites:
            return cand, ''
    return None, f'no Search Console property for {host} visible to the signed-in account'


def context(group_dir, slug):
    """Hotel, site, path prefixes, properties (found once and saved in monthly-settings.json)."""
    reg = grp.load(group_dir)
    if not reg:
        raise FileNotFoundError(f'no site.json in {group_dir}: run the full report (or detect_hotels + save_group) '
                                'first')
    hotel = next((h for h in reg['hotels'] if h['slug'] == slug), None)
    if not hotel:
        raise LookupError(f'no hotel {slug} in site.json; hotels: {[h["slug"] for h in reg["hotels"]]}')
    gd = paths.resolve(group_dir)
    hdir = grp.hotel_dir(group_dir, slug, reg)
    hdir.mkdir(parents=True, exist_ok=True)
    site = reg['group']['site'].rstrip('/') + '/'
    host = _host(site)
    prefixes = hotel.get('paths') or ['/']
    sf = hdir / 'monthly-settings.json'
    st = json.loads(sf.read_text(encoding='utf-8')) if sf.exists() else {}
    notes = []
    if not st.get('gsc_property'):
        st['gsc_property'] = hotel.get('gsc_property') or reg['group'].get('gsc_property') or ''
        if not st['gsc_property']:
            st['gsc_property'], why = _gsc_property(host)
            if why:
                notes.append(why)
    if not st.get('ga4_property'):
        st['ga4_property'] = hotel.get('ga4_property') or reg['group'].get('ga4_property') or ''
        if not st['ga4_property']:
            prop, name = ga4.find_property(host)
            st['ga4_property'] = prop or ''
            if prop:
                st['ga4_name'] = name
            else:
                notes.append(name)
    st['home_url'] = st.get('home_url') or (site.rstrip('/') + (prefixes[0] if prefixes != ['/'] else '/'))
    sf.write_text(json.dumps(st, indent=1), encoding='utf-8')
    return {'reg': reg, 'hotel': hotel, 'site': site, 'host': host, 'prefixes': prefixes, 'hotel_dir': hdir,
            'group_dir': gd, 'settings': st, 'notes': notes, 'single': grp.is_single(reg)}


def month_dir(ctx, month):
    d = ctx['hotel_dir'] / f'monthly-{month}'
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------- tracked keywords

def tracked_file(ctx):
    return ctx['hotel_dir'] / 'tracked-keywords.json'


def propose_tracked(group_dir, slug, per_cluster=2, limit=30, min_volume=30):
    """Tracked keywords from the keyword map: the main search of each non-brand cluster (highest score first) and
    its biggest variants, plus brand searches. Saved unconfirmed; the user confirms or edits."""
    ctx = context(group_dir, slug)
    km_file = ctx['hotel_dir'] / 'keywords' / 'keyword-map.json'
    disc, maps = [], []
    if km_file.exists():
        kmap = json.loads(km_file.read_text(encoding='utf-8'))
        vol = {}
        kcsv = km_file.with_name('keyword-map-keywords.csv')
        if kcsv.exists():
            with open(kcsv, encoding='utf-8-sig', newline='') as fh:
                for r in csv.DictReader(fh):
                    try:
                        vol[r['keyword']] = int(float(r.get('volume') or 0))
                    except ValueError:
                        pass
        # the hotel's own area and landmarks first, broad city-wide searches last
        order = {'place': 0, 'landmark': 0, 'room': 1, 'facility': 1, 'audience': 2, 'stars': 2, 'intent': 3,
                 'type': 4}
        clusters = sorted(kmap.get('clusters', []), key=lambda c: (order.get(c.get('kind'), 3), -c.get('score', 0)))
        for c in clusters:
            words = sorted((k for k in dict.fromkeys([c['primary_keyword']] + c.get('keywords', []))
                            if vol.get(k, 0) >= min_volume), key=lambda k: -vol.get(k, 0))[:per_cluster]
            for w in words:
                if len(disc) < limit and w not in [d['keyword'] for d in disc]:
                    disc.append({'keyword': w, 'type': 'discovery', 'volume': vol.get(w) or c.get('volume'),
                                 'cluster': c.get('head'), 'target_page': c.get('target_page') or '',
                                 'target': 'Page 1'})
            if c.get('kind') in ('place', 'landmark', 'type') and len(maps) < 5:
                maps.append(c['primary_keyword'])
    name = ctx['hotel']['name']
    city = ctx['hotel'].get('city') or ''
    brand = list(dict.fromkeys(x for x in (name.lower(), f'{name} {city}'.strip().lower()) if x))
    data = {'confirmed': False, 'proposed': str(date.today()),
            'keywords': disc + [{'keyword': b, 'type': 'brand', 'target': 'Top 3'} for b in brand],
            'maps_keywords': maps,
            'note': 'Proposed from the keyword map. Confirm or edit (save_tracked_keywords) before the first Serper '
                    'run; the list then stays the same every month so months compare.'}
    tracked_file(ctx).write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding='utf-8')
    return data


def save_tracked(group_dir, slug, keywords, maps_keywords=None):
    ctx = context(group_dir, slug)
    clean = []
    for k in keywords:
        k = {'keyword': k} if isinstance(k, str) else dict(k)
        k['keyword'] = re.sub(r'\s+', ' ', str(k.get('keyword', '')).strip().lower())
        if k['keyword'] and k['keyword'] not in [c['keyword'] for c in clean]:
            k.setdefault('type', 'discovery')
            k.setdefault('target', 'Page 1' if k['type'] == 'discovery' else 'Top 3')
            clean.append(k)
    old = json.loads(tracked_file(ctx).read_text(encoding='utf-8')) if tracked_file(ctx).exists() else {}
    data = {'confirmed': True, 'confirmed_on': str(date.today()), 'keywords': clean,
            'maps_keywords': list(maps_keywords if maps_keywords is not None else old.get('maps_keywords', []))}
    tracked_file(ctx).write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding='utf-8')
    return data


def load_tracked(ctx):
    f = tracked_file(ctx)
    return json.loads(f.read_text(encoding='utf-8')) if f.exists() else None


# ---------------------------------------------------------------- Search Console

def _gsc_period(prop, start, end, prefixes, home_url, terms):
    from .keyword_map import _gsc_rows
    whole = not prefixes or prefixes == ['/']
    pages = _gsc_rows(prop, start, end, ['page'], prefixes) or []
    if whole:
        tot_rows = _gsc_rows(prop, start, end, ['date'], None) or []
    else:
        tot_rows = pages
    clicks = sum(r['clicks'] for r in tot_rows)
    impr = sum(r['impressions'] for r in tot_rows)
    pos = (sum(r['position'] * r['impressions'] for r in tot_rows) / impr) if impr else None
    queries = _gsc_rows(prop, start, end, ['query'], prefixes) or []
    countries = _gsc_rows(prop, start, end, ['country'], prefixes) or []
    devices = _gsc_rows(prop, start, end, ['device'], prefixes) or []
    if not tot_rows and not queries:
        # no data at all (property newer than the period, or no impressions): show "–", never zeros
        return {'from': str(start), 'to': str(end), 'no_data': True, 'clicks': None, 'impressions': None,
                'ctr_pct': None, 'position': None, 'brand': {'clicks': None, 'impressions': None},
                'non_brand': {'clicks': None, 'impressions': None}, 'hidden_queries_clicks': None,
                'home': {'url': home_url, 'position': None}, 'pages_with_impressions': 0, 'countries': [],
                'devices': {}, 'queries': {}}
    home = next((r for r in pages if r['keys'][0].rstrip('/') == home_url.rstrip('/')), None)
    b = [r for r in queries if is_brand(r['keys'][0], terms)]
    nb = [r for r in queries if not is_brand(r['keys'][0], terms)]
    return {
        'from': str(start), 'to': str(end), 'totals_by': 'property' if whole else 'pages under the hotel paths',
        'clicks': clicks, 'impressions': impr, 'ctr_pct': round(100 * clicks / impr, 2) if impr else None,
        'position': round(pos, 1) if pos else None,
        'brand': {'clicks': sum(r['clicks'] for r in b), 'impressions': sum(r['impressions'] for r in b)},
        'non_brand': {'clicks': sum(r['clicks'] for r in nb), 'impressions': sum(r['impressions'] for r in nb)},
        'hidden_queries_clicks': max(0, clicks - sum(r['clicks'] for r in queries)),
        'home': {'url': home_url, 'clicks': home['clicks'], 'impressions': home['impressions'],
                 'position': round(home['position'], 1)} if home else {'url': home_url, 'position': None},
        'pages_with_impressions': len(pages),
        'countries': [{'code': r['keys'][0], 'country': COUNTRIES.get(r['keys'][0], r['keys'][0].upper()),
                       'clicks': r['clicks'], 'impressions': r['impressions']}
                      for r in sorted(countries, key=lambda r: -r['clicks'])],
        'devices': {r['keys'][0].lower(): {'clicks': r['clicks'], 'impressions': r['impressions']} for r in devices},
        'queries': {r['keys'][0]: [r['clicks'], r['impressions'], round(r['position'], 1)]
                    for r in sorted(queries, key=lambda r: -r['impressions'])},
    }


# ---------------------------------------------------------------- other sources

def _mirai(ctx, per, out):
    from . import mirai
    mid = ctx['hotel'].get('mirai_id')
    if not mid:
        return {'status': 'not available: no Mirai ID for this hotel in site.json'}
    ok, why = mirai.configured()
    if not ok:
        return {'status': f'not available: {why}'}
    res = {'status': 'ok', 'mirai_id': mid}
    for k, (s, e) in per.items():
        r = mirai.reservations(mid, str(s), str(e), by='booking', out_dir=str(out / 'mirai'))
        res[k] = {f: r.get(f) for f in ('bookings', 'cancelled', 'revenue', 'room_nights', 'adr', 'currency',
                                         'avg_length_of_stay', 'warning') if r.get(f) is not None}
        if r.get('warning') and not r.get('bookings') and not r.get('cancelled'):
            # Mirai had nothing at all for the hotel then (not yet connected): "–", never 0
            res[k].update({'no_data': True, 'bookings': None, 'revenue': None, 'room_nights': None, 'adr': None})
        res[k]['from'], res[k]['to'] = str(s), str(e)
    cur = next((res[k].get('currency') for k in per if res[k].get('currency')), '')
    for k in per:
        if not res[k].get('currency'):
            res[k]['currency'] = cur
    return res


def _parity(ctx, per):
    from . import parity
    mid = ctx['hotel'].get('mirai_id')
    ok, why = parity.configured()
    if not ok:
        return {'status': f'not available: {why}'}
    if not mid:
        return {'status': 'not available: no Mirai ID for this hotel in site.json'}
    res = {'status': 'ok'}
    for source in ('gha', 'web'):
        block = {}
        for k in ('current', 'previous'):
            s, e = per[k]
            r = parity.report(mirai_id=mid, source=source, date_from=str(s), date_to=str(e))
            if not r.get('checked') or not r.get('found'):
                block[k] = {'status': 'not available: ' + str(r.get('reason', 'no data'))}
                continue
            block[k] = {'dates': r['dates'], 'currency': r.get('currency'), 'overall': r['overall'],
                        'by_ota': [{x: o.get(x) for x in ('name', 'checks', 'priced', 'Beat', 'Meet', 'Lose',
                                                         'avg_lose_gap_pct')} for o in r['by_ota']],
                        'worst': [{x: w.get(x) for x in ('date', 'ota', 'stay', 'site_price', 'ota_price', 'gap_pct')}
                                  for w in r.get('worst_losses', [])[:5]]}
        res['google_hotel_ads' if source == 'gha' else 'website'] = block
    return res


def _index(ctx, month, out):
    from . import indexing
    prop = ctx['settings'].get('gsc_property')
    if not prop:
        return {'status': 'not available: no Search Console property'}
    r = indexing.inspect_all(prop, ctx['site'], str(out / 'indexing'), max_age_days=10)
    if not r.get('checked'):
        return {'status': 'not available: ' + str(r.get('reason', ''))}
    cache = json.loads(indexing._cache_file(prop).read_text(encoding='utf-8')) if indexing._cache_file(prop).exists() else {}
    pre = ctx['prefixes']

    def mine(u):
        p = urlparse(u).path or '/'
        return _host(u) == ctx['host'] and (pre == ['/'] or any(p.startswith(x) for x in pre))
    rows = {u: v for u, v in cache.items() if mine(u)}
    indexed = sum(1 for v in rows.values() if v.get('verdict') == 'PASS')
    return {'status': 'ok', 'indexed': indexed, 'inspected': len(rows),
            'not_indexed': len(rows) - indexed, 'not_yet_inspected': r.get('not_yet_inspected', 0),
            'by_state': _count(v.get('coverage') or '(no state)' for v in rows.values()),
            'note': 'URL Inspection of every sitemap and crawled URL (our own count, not the Search Console '
                    'Pages report)'}


def _count(it):
    out = {}
    for x in it:
        out[x] = out.get(x, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def _work(ctx, month):
    s, e = periods(month)['current']
    items = []
    gd = ctx['group_dir']
    runs = list(ctx['hotel_dir'].glob('execute-*/changes.json'))
    if not ctx['single']:
        runs += list((gd / 'group').glob('execute-*/changes.json'))
    for f in runs:
        try:
            ch = json.loads(f.read_text(encoding='utf-8'))
        except ValueError:
            continue
        for c in ch:
            at = (c.get('at') or '')[:10]
            if not (str(s) <= at <= str(e)):
                continue
            page = c.get('page') or ''
            if f.parent.parent.name == 'group' and page and grp.hotel_for(page, ctx['reg']) != ctx['hotel']['slug']:
                continue
            items.append({'date': at, 'source': 'execute', 'field': c.get('field') or '', 'page': page,
                          'finding': c.get('finding') or '', 'new': c.get('new') if isinstance(c.get('new'), str)
                          else ''})
    log = ctx['hotel_dir'] / 'work-log.csv'
    if log.exists():
        with open(log, encoding='utf-8-sig', newline='') as fh:
            for r in csv.DictReader(fh):
                d = (r.get('date') or '')[:10]
                if str(s) <= d <= str(e):
                    items.append({'date': d, 'source': 'work log', 'field': '', 'page': r.get('page', ''),
                                  'what': r.get('what', ''), 'who': r.get('who', '')})
    by_field = _count(i['field'] for i in items if i['source'] == 'execute')
    steps = []
    plans = sorted(ctx['hotel_dir'].glob('audit-*/build-plan.json'))
    if plans:
        bp = json.loads(plans[-1].read_text(encoding='utf-8'))
        for sec in bp.get('sections', []):
            if 'step' in sec.get('title', '').lower():
                for b in sec.get('blocks', []):
                    steps += [str(x) for x in (b.get('ol') or b.get('ul') or [])]
    return {'items': sorted(items, key=lambda i: i['date']), 'execute_by_field': by_field,
            'pages_changed': len({i['page'] for i in items if i['source'] == 'execute' and i['page']}),
            'build_plan_steps': steps, 'build_plan': str(plans[-1]) if plans else ''}


def add_work_log(group_dir, slug, day, what, page='', who='MetaHotels'):
    ctx = context(group_dir, slug)
    date.fromisoformat(day)
    f = ctx['hotel_dir'] / 'work-log.csv'
    new = not f.exists()
    with open(f, 'a', newline='', encoding='utf-8-sig' if new else 'utf-8') as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(['date', 'what', 'page', 'who'])
        w.writerow([day, what, page, who])
    return {'file': str(f), 'added': {'date': day, 'what': what, 'page': page, 'who': who}}


MANUAL_FIELDS = {
    'gbp': {'rating': float, 'reviews': int, 'calls': int, 'directions': int, 'website_clicks': int,
            'booking_clicks': int, 'profile_views': int, 'searches': int, 'period': str, 'source': str,
            'checked': str, 'note': str},
    'security': {'security_issues': str, 'manual_actions': str, 'source': str, 'checked': str, 'note': str},
}


def import_manual(group_dir, slug, month, data):
    """Save what Claude read in Chrome. data = {"gbp": {...}, "security": {...}}; unknown fields are refused."""
    ctx = context(group_dir, slug)
    periods(month)
    out = {}
    for block, fields in MANUAL_FIELDS.items():
        if block not in data:
            continue
        clean = {}
        for k, v in (data[block] or {}).items():
            if k not in fields:
                raise ValueError(f'{block}.{k} is not a known field; allowed: {", ".join(fields)}')
            if v is None or v == '':
                continue
            clean[k] = fields[k](str(v).replace(',', '')) if fields[k] in (int, float) else str(v)
        clean.setdefault('checked', str(date.today()))
        clean.setdefault('source', 'Claude in Chrome' + (' (Google Business Profile)' if block == 'gbp'
                                                         else ' (Search Console)'))
        out[block] = clean
    f = month_dir(ctx, month) / 'manual.json'
    old = json.loads(f.read_text(encoding='utf-8')) if f.exists() else {}
    old.update(out)
    f.write_text(json.dumps(old, indent=1, ensure_ascii=False), encoding='utf-8')
    return {'file': str(f), 'saved': old}


# ---------------------------------------------------------------- collect

def collect(group_dir, slug, month='', progress=None):
    """Every number for one hotel's month -> monthly-<month>/data.json. Each block has a status."""
    month = month or default_month()
    per = periods(month)
    ctx = context(group_dir, slug)
    out = month_dir(ctx, month)
    say = progress or (lambda m: None)
    from .keyword_map import brand_terms
    terms = brand_terms(ctx['hotel'], ctx['reg'])
    data = {'hotel': ctx['hotel']['name'], 'slug': slug, 'site': ctx['site'], 'paths': ctx['prefixes'],
            'month': month, 'periods': {k: [str(a), str(b)] for k, (a, b) in per.items()},
            'provisional': provisional(month), 'collected': datetime.now().strftime('%Y-%m-%d %H:%M'),
            'settings': {k: v for k, v in ctx['settings'].items()}, 'brand_terms': terms, 'notes': list(ctx['notes'])}
    prop = ctx['settings'].get('gsc_property')
    if prop:
        say('Search Console')
        try:
            data['gsc'] = {'status': 'ok', 'property': prop,
                           **{k: _gsc_period(prop, s, e, ctx['prefixes'], ctx['settings']['home_url'], terms)
                              for k, (s, e) in per.items()}}
        except RuntimeError as e:
            data['gsc'] = {'status': f'not available: {e}'}
    else:
        data['gsc'] = {'status': 'not available: no Search Console property'}
    gp = ctx['settings'].get('ga4_property')
    if gp:
        say('GA4')
        try:
            data['ga4'] = {'status': 'ok', 'property': gp, 'filter': 'landing page under ' + ', '.join(ctx['prefixes'])
                           if ctx['prefixes'] != ['/'] else 'whole property',
                           **{k: ga4.period(gp, s, e, ctx['prefixes']) for k, (s, e) in per.items()}}
        except RuntimeError as e:
            data['ga4'] = {'status': f'not available: {e}'}
    else:
        data['ga4'] = {'status': 'not available: no GA4 property'}
    say('Mirai bookings')
    try:
        data['mirai'] = _mirai(ctx, per, out)
    except Exception as e:  # noqa: BLE001 - one source failing must not stop the report
        data['mirai'] = {'status': f'not available: {type(e).__name__}: {str(e)[:200]}'}
    say('rate parity')
    try:
        data['parity'] = _parity(ctx, per)
    except Exception as e:  # noqa: BLE001
        data['parity'] = {'status': f'not available: {type(e).__name__}: {str(e)[:200]}'}
    say('pages in Google (URL Inspection)')
    try:
        data['index'] = _index(ctx, month, out)
    except Exception as e:  # noqa: BLE001
        data['index'] = {'status': f'not available: {type(e).__name__}: {str(e)[:200]}'}
    data['work'] = _work(ctx, month)
    tr = load_tracked(ctx)
    data['tracked'] = tr or {'confirmed': False, 'keywords': []}
    (out / 'data.json').write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding='utf-8')
    return {'file': str(out / 'data.json'), 'provisional': data['provisional'],
            'status': {k: (data[k].get('status') if isinstance(data.get(k), dict) else None)
                       for k in ('gsc', 'ga4', 'mirai', 'parity', 'index')},
            'work_items': len(data['work']['items']), 'tracked_keywords': len(data['tracked'].get('keywords', [])),
            'tracked_confirmed': bool(data['tracked'].get('confirmed')), 'notes': data['notes']}


def serp_run(group_dir, slug, month='', confirm=False, progress=None):
    """Serper positions for the confirmed tracked keywords. confirm=False only returns the credit estimate."""
    from . import apikeys, serp
    month = month or default_month()
    ctx = context(group_dir, slug)
    tr = load_tracked(ctx)
    if not tr or not tr.get('keywords'):
        return {'ready': False, 'reason': 'no tracked keywords: call tracked_keywords first'}
    if not tr.get('confirmed'):
        return {'ready': False, 'reason': 'tracked keywords not confirmed yet: show them to the user, then '
                                          'save_tracked_keywords'}
    if not apikeys.get('serper'):
        return {'ready': False, 'reason': 'no Serper key: add SERPER_API=... to the work folder .env'}
    kws = [k['keyword'] for k in tr['keywords']]
    mk = tr.get('maps_keywords') or []
    est = serp.estimate(kws, mk)
    if not confirm:
        return {'ready': True, 'keywords': len(kws), 'maps_keywords': len(mk), 'max_credits': est,
                'next': 'Run again with confirm=true to check them.'}
    latlng = None
    if mk:
        from . import geo
        facts = ctx['hotel_dir'] / 'hotel-facts.json'
        addr = ''
        if facts.exists():
            fj = json.loads(facts.read_text(encoding='utf-8'))
            addr = next((f.get('value') for f in fj.get('facts', []) if f.get('kind') == 'address'), '') or ''
        g = geo.geocode(addr) if addr else None
        if not (g and g.get('lat')):   # Booking.com addresses (PO box etc.) often fail; the hotel name usually works
            g = geo.geocode(f"{ctx['hotel']['name']}, {ctx['hotel'].get('city', '')}")
        if g and g.get('lat'):
            latlng = (g['lat'], g['lon'])
    return serp.run(month_dir(ctx, month) / 'serp.json', kws, ctx['site'], ctx['prefixes'], ctx['hotel']['name'],
                    ctx['hotel'].get('city') or 'Dubai', ctx['hotel'].get('country') or 'United Arab Emirates',
                    latlng, mk, progress)


# ---------------------------------------------------------------- report building

def _g(d, *keys, default=None):
    for k in keys:
        if not isinstance(d, dict) or k not in d:
            return default
        d = d[k]
    return d


def _ok(block):
    return isinstance(block, dict) and block.get('status') == 'ok'


def _pill(pos, target=None):
    if pos is None:
        return {'text': 'not in top 30' if target is not None else '–', 'pill': 'grey'}
    p = float(pos)
    return {'text': fmt(p, 1) if p % 1 else fmt(p), 'pill': 'green' if p <= 10 else 'amber' if p <= 20 else 'red'}


def _hotel_prev_data(ctx, month):
    """Earlier months' data.json for this hotel (for index and parity history)."""
    out = {}
    for d in sorted(ctx['hotel_dir'].glob('monthly-*/data.json')):
        m = d.parent.name.replace('monthly-', '')
        if m < month:
            try:
                out[m] = json.loads(d.read_text(encoding='utf-8'))
            except ValueError:
                pass
    return out


def build(group_dir, slug, month=''):
    """monthly-<month>/monthly-report.json from data.json (+ serp.json, manual.json, narrative.json)."""
    month = month or default_month()
    ctx = context(group_dir, slug)
    md = month_dir(ctx, month)
    df = md / 'data.json'
    if not df.exists():
        raise FileNotFoundError(f'no {df}: run monthly_collect first')
    data = json.loads(df.read_text(encoding='utf-8'))
    serp_d = json.loads((md / 'serp.json').read_text(encoding='utf-8')) if (md / 'serp.json').exists() else {}
    manual = json.loads((md / 'manual.json').read_text(encoding='utf-8')) if (md / 'manual.json').exists() else {}
    nar = json.loads((md / 'narrative.json').read_text(encoding='utf-8')) if (md / 'narrative.json').exists() else {}
    doc = _assemble(ctx, month, data, serp_d, manual, nar)
    (md / 'monthly-report.json').write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding='utf-8')
    missing = [p['eyebrow'] + ': ' + n for p in doc['monthly']['pages'] for n in p.get('_missing', [])]
    return {'file': str(md / 'monthly-report.json'), 'pages': len(doc['monthly']['pages']),
            'provisional': data.get('provisional'), 'not_available': missing,
            'narrative': 'present' if nar else 'missing: write it with save_monthly_narrative, then build again',
            'out_dir': str(ctx['hotel_dir'] / 'Reports')}


def _assemble(ctx, month, data, serp_d, manual, nar):
    name = ctx['hotel']['name']
    short = re.sub(r'\s+(hotel apartments|hotel|resort|apartments)$', '', name, flags=re.I) or name
    gsc, ga, mi, par, idx, work = (data.get(k) or {} for k in ('gsc', 'ga4', 'mirai', 'parity', 'index', 'work'))
    C, P, Y = 'current', 'previous', 'last_year'
    mlabel, plabel, ylabel = label(month), label(_month_of(data['periods'][P][0])), label(_month_of(data['periods'][Y][0]))
    pages, cover_cards = [], []

    # ---- 01 where the hotel stands
    cards, missing = [], []
    if _ok(ga):
        v, pv = _g(ga, C, 'organic', 'sessions'), _g(ga, P, 'organic', 'sessions')
        cards.append({'value': fmt(v), **_chg(v, pv), 'label': 'visits to the website from Google search'})
        er, ep = _g(ga, C, 'organic', 'engagement_rate_pct'), _g(ga, P, 'organic', 'engagement_rate_pct')
        cards.append({'value': f'{fmt(er, 1)}%' if er is not None else '–', **_chg_points(er, ep),
                      'label': f"of Google visitors actively browse the site ({fmt(_g(ga, C, 'organic', 'avg_engagement_s'))} s "
                               'average engagement)'})
    else:
        missing.append('GA4 ' + str(ga.get('status', 'not collected')))
    if _ok(gsc):
        bc, bp = _g(gsc, C, 'brand', 'clicks'), _g(gsc, P, 'brand', 'clicks')
        cards.append({'value': fmt(bc), **_chg(bc, bp), 'label': f'clicks from people searching the {short} name'})
        hp, hpp = _g(gsc, C, 'home', 'position'), _g(gsc, P, 'home', 'position')
        cards.append({'value': fmt(hp, 1), **_chg_pos(hp, hpp),
                      'label': 'average Google position of the hotel\'s main page'})
    else:
        missing.append('Search Console ' + str(gsc.get('status', 'not collected')))
    if _ok(idx):
        prev_idx = [v.get('index', {}).get('indexed') for m, v in _hotel_prev_data(ctx, month).items()
                    if _ok(v.get('index'))]
        pi = prev_idx[-1] if prev_idx else None
        cards.append({'value': fmt(idx['indexed']), **_chg(idx['indexed'], pi),
                      'label': 'website pages now listed in Google'})
    else:
        missing.append('Pages in Google ' + str(idx.get('status', 'not collected')))
    if _ok(ga):
        a, ap = _g(ga, C, 'ai', 'sessions'), _g(ga, P, 'ai', 'sessions')
        cards.append({'value': fmt(a), **_chg(a, ap), 'label': 'visits from AI assistants such as ChatGPT'})
    comps = [{'cards': cards}]
    if _ok(gsc):
        prev_c = {c['code']: c['clicks'] for c in _g(gsc, P, 'countries', default=[])}
        rows = []
        for c in _g(gsc, C, 'countries', default=[])[:5]:
            ch = change(c['clicks'], prev_c.get(c['code']))
            rows.append([c['country'], fmt(c['clicks']), {'text': ch['text'].split(' (')[0].replace('▲ ', '').replace('▼ ', ''),
                                                          'pill': 'green' if ch['dir'] == 'up' else 'red' if ch['dir'] == 'down' else 'grey'}])
        countries = {'title': 'Where the guests come from', 'table': {'columns': ['Country', 'Google clicks', f'vs {plabel[:3]}'],
                                                                     'align': ['l', 'r', 'r'], 'rows': rows}}
    else:
        countries = None
    sec = manual.get('security')
    if sec:
        clean = all(str(sec.get(k, '')).strip().lower() in ('none', 'no issues', 'no issues detected', '0', 'no')
                    for k in ('security_issues', 'manual_actions') if k in sec)
        health = {'title': 'Healthy, verified website' if clean else 'Search Console reports issues',
                  'text': (f"Google reports **no security issues and no penalties** on {ctx['host']} "
                           f"(Search Console, checked {_short_date(sec.get('checked', ''), year=True)})." if clean else
                           f"Security issues: {sec.get('security_issues', '–')}. Manual actions: "
                           f"{sec.get('manual_actions', '–')} (Search Console, checked {_short_date(sec.get('checked', ''), year=True)})."),
                  'tone': 'good' if clean else 'bad'}
    else:
        health = {'title': 'Search Console health', 'text': 'Security issues and manual actions not checked this month.',
                  'tone': 'muted'}
        missing.append('Search Console security: not checked this month')
    comps.append({'grid2': [countries or {'title': 'Where the guests come from', 'text': 'Search Console not available.'},
                            health]})
    yoy = _yoy_rows(gsc, ga, mi, C, P, Y)
    if yoy:
        comps.append({'title': 'This month, last month and a year ago',
                      'table': {'columns': ['', mlabel, plabel, ylabel], 'align': ['l', 'r', 'r', 'r'], 'rows': yoy}})
    if nar.get('headline'):
        comps.append({'callout': {'label': 'The headline:', 'text': nar['headline']}})
    pages.append({'eyebrow': f'01 · Where {short} stands this month', 'title': nar.get('title_01') or
                  f'{mlabel} on Google', 'intro': f"Data from Google Search Console and Google Analytics for "
                  f"{ctx['host']}, {mlabel} compared with {plabel} and {ylabel}.", 'components': comps,
                  '_missing': missing})
    cover_cards = [c for c in cards if c['label'].startswith(('visits to the website', 'clicks from people',
                                                             'average Google position'))][:3]

    # ---- 02 keywords
    comps, missing = [], []
    tracked = {k['keyword']: k for k in (data.get('tracked') or {}).get('keywords', [])}
    sq = (serp_d or {}).get('search', {})
    if _ok(gsc):
        qn, qp = _g(gsc, C, 'queries', default={}), _g(gsc, P, 'queries', default={})
        terms = data.get('brand_terms') or []
        brand = [(q, v) for q, v in qn.items() if is_brand(q, terms)][:5]
        if brand:
            comps.append({'title': f'Brand searches: people looking for {short}',
                          'table': {'columns': ['Search term', 'Google views', 'Clicks', 'Position'],
                                    'align': ['l', 'r', 'r', 'r'],
                                    'rows': [[q, fmt(v[1]), fmt(v[0]), _pill(v[2])] for q, v in brand]}})
        disc = [k for k, t in tracked.items() if t.get('type') != 'brand']
        if disc:
            rows = []
            sq_prev = _serp_last_month(ctx, month, sq)
            for k in disc:
                g, gp_ = qn.get(k), qp.get(k)
                s = sq.get(k)
                rows.append([k, fmt(g[1]) if g else '0', _pill(g[2]) if g else {'text': 'not showing', 'pill': 'grey'},
                             _pill(gp_[2]) if gp_ else {'text': '–', 'pill': 'grey'},
                             (_pill(s.get('position'), True) if s else {'text': 'not checked', 'pill': 'grey'}),
                             (_pill(sq_prev[k].get('position'), True) if k in sq_prev else {'text': '–', 'pill': 'grey'}),
                             ('in map pack' + (f" #{s['map_pack']['hotel_position']}" if s['map_pack'].get('hotel_position') else ' (not listed)')
                              if s and (s.get('map_pack') or {}).get('shown') else ('no map pack' if s else '–')),
                             {'text': tracked[k].get('target', 'Page 1'), 'pill': 'grey'}])
            comps.append({'title': 'Discovery searches: guests who don\'t know the hotel yet',
                          'text': 'Search Console average position this month and last month, and the exact Google '
                                  f"position on {_serp_date(sq)} from {_serp_loc(sq) or 'the hotel city'} (Serper)." if sq else
                          'Search Console average position this month and last month. Exact Google positions were '
                          'not checked this month.',
                          'table': {'columns': ['Search term', 'Google views', f'Position {mlabel[:3]}',
                                                f'Position {plabel[:3]}', 'Google today', 'Google last month',
                                                'Map pack', 'Target'],
                                    'align': ['l', 'r', 'r', 'r', 'r', 'r', 'l', 'r'], 'rows': rows}})
            if not sq:
                missing.append('exact Google positions (Serper) not checked')
        else:
            nb = [(q, v) for q, v in qn.items() if not is_brand(q, terms)][:12]
            if nb:
                comps.append({'title': 'Discovery searches',
                              'table': {'columns': ['Search term', 'Google views', 'Clicks', 'Position'],
                                        'align': ['l', 'r', 'r', 'r'],
                                        'rows': [[q, fmt(v[1]), fmt(v[0]), _pill(v[2])] for q, v in nb]}})
            missing.append('no tracked keywords confirmed yet')
        nbi, nbp = _g(gsc, C, 'non_brand', 'impressions'), _g(gsc, P, 'non_brand', 'impressions')
        comps.append({'cards': [
            {'value': fmt(_g(gsc, C, 'non_brand', 'clicks')),
             **_chg(_g(gsc, C, 'non_brand', 'clicks'), _g(gsc, P, 'non_brand', 'clicks')),
             'label': 'clicks from searches that don\'t name the hotel'},
            {'value': fmt(nbi), **_chg(nbi, nbp), 'label': 'times the hotel appeared for those searches'},
            {'value': fmt(_g(gsc, C, 'hidden_queries_clicks')), 'change': '', 'dir': None,
             'label': 'clicks from rare searches Google does not list (privacy)'}]})
    else:
        missing.append('Search Console ' + str(gsc.get('status', '')))
    comps.append({'note': 'Page 1 = top 10 results. Targets are goals, measured monthly in Search Console. Google '
                          'rankings can\'t be guaranteed by anyone, but every change in this programme is aimed at '
                          'these searches.'})
    if nar.get('keywords_note'):
        comps.append({'callout': {'label': 'Why this matters:', 'text': nar['keywords_note']}})
    pages.append({'eyebrow': '02 · Keywords', 'title': f'What guests search, and where {short} ranks',
                  'intro': f'Search Console figures for {mlabel}.', 'components': comps, '_missing': missing})

    # ---- 03 AI assistants
    comps, missing = [], []
    if _ok(ga):
        cur, prv, ly = (_g(ga, k, 'ai', default={}) for k in (C, P, Y))
        comps.append({'cards': [
            {'value': fmt(cur.get('sessions')), **_chg(cur.get('sessions'), prv.get('sessions')),
             'label': 'visits from AI assistants'},
            {'value': fmt(cur.get('engaged_sessions')), **_chg(cur.get('engaged_sessions'), prv.get('engaged_sessions')),
             'label': 'of them browsed the site (engaged visits)'},
            {'value': fmt(ly.get('sessions')), 'change': f'{ylabel}', 'dir': None,
             'label': 'AI assistant visits a year ago'}]})
        names = {b['assistant'] for k in (C, P, Y) for b in _g(ga, k, 'ai', 'by_assistant', default=[])}
        if names:
            def n(k, a):
                return next((b['sessions'] for b in _g(ga, k, 'ai', 'by_assistant', default=[]) if b['assistant'] == a), 0)
            rows = [[a] + ['–' if _g(ga, k, 'no_data') else fmt(n(k, a)) for k in (C, P, Y)]
                    for a in sorted(names, key=lambda a: -n(C, a))]
            comps.append({'title': 'Visits by assistant', 'table': {'columns': ['Assistant', mlabel, plabel, ylabel],
                                                                     'align': ['l', 'r', 'r', 'r'], 'rows': rows}})
        comps.append({'note': 'Counted by Google Analytics when a guest clicks a link to the site inside ChatGPT, '
                              'Perplexity, Gemini, Copilot, Claude and similar assistants. Answers that mention the '
                              'hotel without a click are not counted; Google\'s AI Overviews are part of Google search.'})
    else:
        missing.append('GA4 ' + str(ga.get('status', '')))
    if nar.get('ai_note'):
        comps.append({'callout': {'label': 'AI search:', 'text': nar['ai_note']}})
    pages.append({'eyebrow': '03 · AI assistants', 'title': 'Guests arriving from ChatGPT and other AI assistants',
                  'intro': f'Google Analytics, {mlabel}.', 'components': comps, '_missing': missing})

    # ---- 04 work done
    comps, missing = [], []
    items = work.get('items') or []
    if items:
        groups = {}
        for i in items:
            key = i.get('what') or _field_label(i.get('field'))
            g = groups.setdefault(key, {'title': key, 'pages': set(), 'dates': set()})
            if i.get('page'):
                g['pages'].add(i['page'])
            g['dates'].add(i['date'])
        tl = []
        for g in sorted(groups.values(), key=lambda g: min(g['dates'])):
            d1, d2 = min(g['dates']), max(g['dates'])
            when = _short_date(d1) + ('' if d1 == d2 else f' – {_short_date(d2)}')
            tl.append({'when': when, 'title': g['title'] + (f" ({len(g['pages'])} page{'s' if len(g['pages']) != 1 else ''})"
                                                            if g['pages'] else ''),
                       'items': [urlparse(p).path or p for p in sorted(g['pages'])]})
        comps.append({'timeline': tl})
    else:
        comps.append({'text': 'No changes were logged this month (execute runs or the work log).'})
        missing.append('no work logged this month')
    nxt = nar.get('next') or []
    if nxt:
        comps.append({'title': 'Coming next', 'list': nxt})
    pages.append({'eyebrow': '04 · Work done', 'title': nar.get('title_04') or f'What we changed in {mlabel}',
                  'intro': nar.get('work_intro') or 'Changes made on the live site this month: through the site\'s content tools '
                           '(each checked live afterwards) and by the MetaHotels team.',
                  'components': comps, '_missing': missing})

    # ---- 05 search to booking
    comps, missing = [], []
    funnel = []
    if _ok(gsc):
        funnel.append({'eyebrow': 'Found', 'value': fmt(_g(gsc, C, 'impressions')),
                       'label': 'times the hotel appeared in Google search'})
        funnel.append({'eyebrow': 'Chosen', 'value': fmt(_g(gsc, C, 'brand', 'impressions')),
                       'label': f'searches for the {short} name'})
    if _ok(ga):
        funnel.append({'eyebrow': 'Visited', 'value': fmt(_g(ga, C, 'all', 'sessions')),
                       'label': f"visits to {ctx['host']}"})
    if _ok(mi) and _g(mi, C, 'bookings') is not None:
        funnel.append({'eyebrow': 'Booked', 'value': fmt(_g(mi, C, 'bookings')),
                       'label': f"direct bookings, {_g(mi, C, 'currency') or ''} {fmt(_g(mi, C, 'revenue'))}".strip(),
                       'dark': True})
    if funnel:
        comps.append({'funnel': funnel})
    if _ok(mi):
        rows = []
        for lab, k in ((mlabel, C), (plabel, P), (ylabel, Y)):
            b = mi.get(k) or {}
            money = (lambda v: '–' if v is None else f"{b.get('currency') or ''} {fmt(v)}".strip())
            rows.append([lab, fmt(b.get('bookings')), fmt(b.get('room_nights')), money(b.get('revenue')),
                         money(b.get('adr')) if b.get('bookings') else '–'])
        comps.append({'title': f"Direct bookings on {ctx['host']}",
                      'table': {'columns': ['Booked in', 'Bookings', 'Room nights', 'Revenue', 'Average rate'],
                                'align': ['l', 'r', 'r', 'r', 'r'], 'rows': rows}})
    else:
        missing.append('Mirai ' + str(mi.get('status', '')))
    par_block = None
    if _ok(par):
        src = par.get('google_hotel_ads') if (par.get('google_hotel_ads') or {}).get(C, {}).get('overall') else par.get('website')
        cur = (src or {}).get(C) or {}
        prv = (src or {}).get(P) or {}
        if cur.get('overall'):
            o = cur['overall']
            po = prv.get('overall') or {}
            lose_otas = [x for x in cur.get('by_ota', []) if (x.get('Lose') or 0) > 0][:5]
            par_block = {'title': 'Official site vs the OTAs' + (' on Google' if src is par.get('google_hotel_ads') else ''),
                         'table': {'columns': ['', mlabel, plabel], 'align': ['l', 'r', 'r'], 'rows': [
                             ['Official site cheaper (Beat)', f"{fmt(o.get('Beat'), 1)}%", f"{fmt(po.get('Beat'), 1)}%" if po else '–'],
                             ['Same price (Meet)', f"{fmt(o.get('Meet'), 1)}%", f"{fmt(po.get('Meet'), 1)}%" if po else '–'],
                             ['OTA cheaper (Lose)', f"{fmt(o.get('Lose'), 1)}%", f"{fmt(po.get('Lose'), 1)}%" if po else '–'],
                             ['Price checks', fmt(o.get('priced')), fmt(po.get('priced')) if po else '–']]},
                         'text': ('OTAs most often below the official site: ' + ', '.join(
                             f"{x['name']} ({fmt(x['Lose'], 1)}% of checks, {fmt(x.get('avg_lose_gap_pct'), 1)}% cheaper on average)"
                             for x in lose_otas) + '.') if lose_otas else 'No OTA was cheaper than the official site.'}
    if par_block:
        comps.append(par_block)
    else:
        missing.append('rate parity ' + str(par.get('status', 'no data for the month')))
    if nar.get('funnel_note'):
        comps.append({'callout': {'label': 'From search to booking:', 'text': nar['funnel_note']}})
    pages.append({'eyebrow': '05 · From search to booking', 'title': nar.get('title_05') or
                  'Guests are finding the hotel. Price decides where they book.',
                  'intro': f'{mlabel}: Google Search Console, Google Analytics, the booking engine (Mirai) and rate '
                           'parity checks.', 'components': comps, '_missing': missing})

    # ---- 06 Google Maps & Business Profile
    comps, missing = [], []
    gbp = manual.get('gbp')
    if gbp:
        cards = []
        if gbp.get('rating') is not None:
            cards.append({'value': f"{gbp['rating']} ★", 'change': f"{fmt(gbp.get('reviews'))} Google reviews",
                          'dir': None, 'label': 'Google rating'})
        for k, lab in (('profile_views', 'people viewed the Business Profile'), ('calls', 'calls from the profile'),
                       ('directions', 'direction requests'), ('website_clicks', 'website clicks from the profile'),
                       ('booking_clicks', 'booking clicks from the profile')):
            if gbp.get(k) is not None:
                cards.append({'value': fmt(gbp[k]), 'change': '', 'dir': None, 'label': lab})
        comps.append({'cards': cards})
        comps.append({'note': f"Google Business Profile, {gbp.get('period') or mlabel}; read on {_short_date(gbp.get('checked', ''), year=True)}."})
    else:
        comps.append({'text': 'Business Profile numbers not checked this month (needs Manager access for '
                              'metahotels.m@gmail.com and Chrome).'})
        missing.append('Business Profile not checked')
    maps = (serp_d or {}).get('maps') or {}
    if maps:
        comps.append({'title': 'Google Maps position, searched from the hotel\'s area',
                      'table': {'columns': ['Search', 'Hotel\'s position on the map', 'Top result'],
                                'align': ['l', 'r', 'l'],
                                'rows': [[k, _pill(v.get('position'), True) if v.get('position') else
                                          {'text': f"not in top {v.get('results', 0)}", 'pill': 'grey'},
                                          (v.get('top') or [{}])[0].get('title', '')] for k, v in maps.items()]}})
        comps.append({'note': 'One search point (the hotel\'s area) on the check date; map results change with where '
                              'the guest is.'})
    if nar.get('maps_note'):
        comps.append({'callout': {'label': 'Google Maps:', 'text': nar['maps_note']}})
    pages.append({'eyebrow': '06 · Google Maps', 'title': f'Making {short} the first hotel guests see nearby',
                  'intro': '', 'components': comps, '_missing': missing})

    # ---- 07 why MetaHotels
    about = (paths.PACKAGE_DIR / 'templates' / 'monthly-about.md').read_text(encoding='utf-8')
    bullets = [l[2:].strip() for l in about.splitlines() if l.startswith('- ')]
    nm = _next_month(month)              # the next report covers nm and comes out early the month after
    out_month = _next_month(nm)
    pages.append({'eyebrow': '07 · Why MetaHotels', 'title': 'One team for the whole guest journey',
                  'intro': '', 'components': [{'checks': bullets},
                                              {'note': f'Next report: early {label(out_month)}, covering {label(nm)}.'}],
                  '_missing': []})

    cover = {'eyebrow': f'MetaHotels · Monthly search report · {mlabel}', 'title': name,
             'subtitle': 'Monthly Search Report',
             'lead': nar.get('cover_lead') or f'How {short} did on Google, in AI assistants and in direct bookings in '
                                               f'{mlabel}, and what we changed on {ctx["host"]}.',
             'cards': [dict(c) for c in cover_cards],
             'prepared': 'Prepared by MetaHotels · Dubai', 'date': _win_date()}
    if data.get('provisional'):
        cover['badge'] = 'Provisional: Search Console data for the last days of the month is not final yet.'
    doc = {'title': 'Monthly Report', 'hotel': name, 'short_name': name, 'site': ctx['site'],
           'date': label(month, short=True), 'month': month, 'file_number': 'auto',
           'subtitle': f'{mlabel}: search, AI assistants, work done and direct bookings',
           'monthly': {'cover': cover, 'pages': pages, 'footer': f'{name} · Monthly Search Report · {mlabel}'},
           'footer': '', 'sections': []}
    doc['sections'] = to_sections(doc)
    return doc


def _win_date():
    d = datetime.now()
    return f'{d.day} {MONTHS[d.month - 1]} {d.year}'


def _month_of(day):
    return day[:7]


def _next_month(month):
    y, m = map(int, month.split('-'))
    return f'{y + (m == 12)}-{(m % 12) + 1:02d}'


def _serp_last_month(ctx, month, sq):
    """{keyword: last month's Serper result} for the "Google last month" column. A keyword is left out (shown "–")
    when last month was not checked or was checked from another location, country, language or device."""
    y, m = map(int, month.split('-'))
    f = ctx['hotel_dir'] / f'monthly-{y - (m == 1)}-{(m - 2) % 12 + 1:02d}' / 'serp.json'
    try:
        prev = json.loads(f.read_text(encoding='utf-8')).get('search', {}) if f.exists() else {}
    except ValueError:
        return {}
    same = ('location', 'gl', 'hl', 'device')
    return {k: p for k, p in prev.items() if isinstance(p, dict) and k in sq
            and all((p.get(x) or '') == (sq[k].get(x) or '') for x in same)}


def _short_date(d, year=False):
    try:
        dd = date.fromisoformat(d)
        return f'{dd.day} {MONTHS[dd.month - 1][:3]}' + (f' {dd.year}' if year else '')
    except ValueError:
        return d


FIELD_LABELS = {'title': 'SEO titles updated', 'description': 'Meta descriptions updated', 'robots': 'Indexing settings fixed',
                'canonical': 'Canonical tags fixed', 'alt': 'Image alt text written', 'redirect': 'Redirects added',
                'schema': 'Hotel information code (schema) updated', 'h1': 'Page headings (H1) fixed',
                'status': 'Expired pages unpublished', 'menu': 'Menu links fixed', 'content': 'Page text updated'}


def _field_label(field):
    f = (field or '').lower()
    for k, v in FIELD_LABELS.items():
        if k in f:
            return v
    return (field or 'Site change').replace('_', ' ').capitalize()


def _serp_date(sq):
    d = sorted({v.get('checked') for v in sq.values() if v.get('checked')})
    return _short_date(d[-1]) if d else ''


def _serp_loc(sq):
    return next((v.get('location', '').split(',')[0] for v in sq.values() if v.get('location')), '')


def _chg(cur, prev, dec=0, pct_min=20):
    c = change(cur, prev, dec=dec, pct_min=pct_min)
    return {'change': c['text'], 'dir': c['dir']}


def _chg_pos(cur, prev):
    """Google position: smaller is better."""
    c = change(cur, prev, lower_is_better=True, dec=1)
    return {'change': c['text'], 'dir': c['dir']}


def _chg_points(cur, prev):
    """A rate in percent: the change is in percentage points."""
    if cur is None or prev is None:
        return {'change': 'no earlier data', 'dir': None}
    d = round(cur - prev, 1)
    if abs(d) < 0.05:
        return {'change': f'• same as before ({fmt(prev, 1)}%)', 'dir': 'flat'}
    return {'change': f"{'▲' if d > 0 else '▼'} {'+' if d > 0 else '−'}{fmt(abs(d), 1)} points (from {fmt(prev, 1)}%)",
            'dir': 'up' if d > 0 else 'down'}


def _edit1(a, b):
    """True when a and b differ by at most one letter (added, missing or changed)."""
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    s, l = (a, b) if len(a) < len(b) else (b, a)
    return any(l[:i] + l[i + 1:] == s for i in range(len(l)))


def is_brand(q, terms):
    """Brand search, including one-letter misspellings of the hotel's own name words ("abrar hotel" for Abar)."""
    from .keyword_map import is_brand as exact
    if exact(q, terms):
        return True
    words = [t for t in terms if ' ' not in t and len(t) >= 4]
    return any(_edit1(w, t) for w in re.findall(r'[a-z0-9]+', (q or '').lower()) if len(w) >= 4 for t in words)


def _yoy_rows(gsc, ga, mi, C, P, Y):
    rows = []
    if _ok(gsc):
        rows.append(['Google clicks'] + [fmt(_g(gsc, k, 'clicks')) for k in (C, P, Y)])
        rows.append(['Times shown in Google'] + [fmt(_g(gsc, k, 'impressions')) for k in (C, P, Y)])
        rows.append(['Non-brand clicks'] + [fmt(_g(gsc, k, 'non_brand', 'clicks')) for k in (C, P, Y)])
    if _ok(ga):
        rows.append(['Visits from Google'] + [fmt(_g(ga, k, 'organic', 'sessions')) for k in (C, P, Y)])
        rows.append(['Visits from AI assistants'] + [fmt(_g(ga, k, 'ai', 'sessions')) for k in (C, P, Y)])
    if _ok(mi):
        rows.append(['Direct bookings'] + [fmt(_g(mi, k, 'bookings')) for k in (C, P, Y)])
    return rows


# ---------------------------------------------------------------- Word / Google Doc sections

def _cell(c):
    return c.get('text', '') if isinstance(c, dict) else ('' if c is None else str(c))


def _comp_blocks(c):
    out = []
    if c.get('title'):
        out.append({'h3': c['title']})
    if c.get('text'):
        out.append({'p': c['text']})
    if 'cards' in c:
        out.append({'table': {'columns': ['Figure', 'What it is', 'Change'],
                              'rows': [[f"**{x['value']}**", x['label'], x.get('change', '')] for x in c['cards']]}})
    if 'table' in c:
        out.append({'table': {'columns': c['table']['columns'],
                              'rows': [[_cell(x) for x in r] for r in c['table']['rows']]}})
    if 'grid2' in c:
        for sub in c['grid2']:
            out += _comp_blocks(sub)
    if 'callout' in c:
        out.append({'note': f"**{c['callout']['label']}** {c['callout']['text']}"})
    if 'funnel' in c:
        out.append({'table': {'columns': ['Step', 'Number', 'What it is'],
                              'rows': [[x['eyebrow'], f"**{x['value']}**", x['label']] for x in c['funnel']]}})
    if 'timeline' in c:
        for t in c['timeline']:
            out.append({'p': f"**{t['when']}:** {t['title']}"})
            if t.get('items'):
                out.append({'ul': [f'`{i}`' for i in t['items']]})
    if 'list' in c:
        out.append({'ul': c['list']})
    if 'checks' in c:
        out.append({'ul': ['✓ ' + x for x in c['checks']]})
    if 'note' in c:
        out.append({'p': f"*{c['note']}*"})
    return out


def to_sections(doc):
    m = doc['monthly']
    cv = m['cover']
    secs = [{'title': cv['subtitle'], 'blocks': [{'p': cv['lead']}] +
             ([{'warning': cv['badge']}] if cv.get('badge') else []) +
             ([{'table': {'columns': ['Figure', 'What it is', 'Change'],
                          'rows': [[f"**{x['value']}**", x['label'], x.get('change', '')] for x in cv['cards']]}}]
              if cv.get('cards') else [])}]
    for p in m['pages']:
        blocks = ([{'p': p['intro']}] if p.get('intro') else [])
        for c in p['components']:
            blocks += _comp_blocks(c)
        secs.append({'title': f"{p['eyebrow']}: {p['title']}", 'blocks': blocks or [{'p': '–'}]})
    return secs


# ---------------------------------------------------------------- narrative

NUM = re.compile(r'(?<![\w.])[+\-−]?\d[\d,]*(?:\.\d+)?')
NARRATIVE_FIELDS = ('cover_lead', 'headline', 'keywords_note', 'ai_note', 'work_intro', 'funnel_note', 'maps_note',
                    'title_01', 'title_04', 'title_05', 'next')


def _nums_in(obj, out):
    if isinstance(obj, dict):
        for v in obj.values():
            _nums_in(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _nums_in(v, out)
    elif isinstance(obj, bool):
        return
    elif isinstance(obj, (int, float)):
        out.update(_variants(float(obj)))
    elif isinstance(obj, str):
        for t in NUM.findall(obj):
            out.update(_variants(_num(t)))


def _num(t):
    try:
        return float(t.replace(',', '').replace('−', '-').lstrip('+'))
    except ValueError:
        return None


def _variants(v):
    if v is None:
        return set()
    v = abs(v)
    return {round(v, 1), float(round(v))}


def save_narrative(group_dir, slug, month, narrative):
    """Check, then save Claude's lines. Every number must come from the month's data or the built report."""
    month = month or default_month()
    ctx = context(group_dir, slug)
    md = month_dir(ctx, month)
    unknown = [k for k in narrative if k not in NARRATIVE_FIELDS]
    if unknown:
        return {'saved': False, 'error': f'unknown fields {unknown}; allowed: {", ".join(NARRATIVE_FIELDS)}'}
    data = json.loads((md / 'data.json').read_text(encoding='utf-8'))
    serp_d = json.loads((md / 'serp.json').read_text(encoding='utf-8')) if (md / 'serp.json').exists() else {}
    manual = json.loads((md / 'manual.json').read_text(encoding='utf-8')) if (md / 'manual.json').exists() else {}
    allowed = set()
    _nums_in(data, allowed)
    _nums_in(serp_d, allowed)
    _nums_in(manual, allowed)
    _nums_in(_assemble(ctx, month, data, serp_d, manual, {}), allowed)
    allowed.update(float(i) for i in range(0, 13))
    bad = []
    texts = [(k, v) for k, v in narrative.items() if isinstance(v, str)] + \
            [(f'next[{i}]', v) for i, v in enumerate(narrative.get('next') or [])]
    for k, text in texts:
        for t in NUM.findall(str(text)):
            v = _num(t)
            if v is None or 1990 <= abs(v) <= 2100:
                continue
            if not (_variants(v) & allowed):
                bad.append({'field': k, 'number': t, 'context': str(text)[:160]})
    guard = {}
    crawl = sorted(ctx['group_dir'].glob('crawl-*'))
    facts_file = ctx['hotel_dir'] / 'hotel-facts.json'
    if crawl or facts_file.exists():
        from . import facts
        mini = {'sections': [{'title': k, 'blocks': [{'p': str(v)}]} for k, v in texts]}
        guard = facts.check(mini, str(crawl[-1]) if crawl else '', str(facts_file) if facts_file.exists() else '')
    unverified = guard.get('unverified') or []
    if bad or unverified:
        return {'saved': False, 'numbers_not_in_data': bad, 'confirm_guard': unverified,
                'next': 'Use only numbers from data.json / the report (or remove them); mark hotel facts [CONFIRM] '
                        'or use confirmed facts; then save again.'}
    (md / 'narrative.json').write_text(json.dumps(narrative, indent=1, ensure_ascii=False), encoding='utf-8')
    return {'saved': True, 'file': str(md / 'narrative.json')}


# ---------------------------------------------------------------- group page

def build_group(group_dir, month=''):
    """Group Monthly Summary: one row per hotel from each hotel's data.json, plus links to the hotel reports."""
    month = month or default_month()
    reg = grp.load(group_dir)
    if not reg:
        raise FileNotFoundError('no site.json')
    if grp.is_single(reg):
        return {'skipped': True, 'reason': 'single-hotel site: no group page; the hotel\'s Monthly Report is the whole '
                                           'report'}
    gd = paths.resolve(group_dir)
    C, P = 'current', 'previous'
    rows, tot, missing = [], dict.fromkeys(('v', 'vp', 'nb', 'nbp', 'ai', 'aip', 'b', 'bp')), []
    reports = []
    for h in reg['hotels']:
        f = gd / 'hotels' / h['slug'] / f'monthly-{month}' / 'data.json'
        if not f.exists():
            missing.append(h['name'])
            continue
        d = json.loads(f.read_text(encoding='utf-8'))
        ga, gsc, mi = d.get('ga4') or {}, d.get('gsc') or {}, d.get('mirai') or {}
        v, vp = _g(ga, C, 'organic', 'sessions'), _g(ga, P, 'organic', 'sessions')
        nb, nbp = _g(gsc, C, 'non_brand', 'clicks'), _g(gsc, P, 'non_brand', 'clicks')
        ai, aip = _g(ga, C, 'ai', 'sessions'), _g(ga, P, 'ai', 'sessions')
        b, bp = _g(mi, C, 'bookings'), _g(mi, P, 'bookings')
        for k, x in (('v', v), ('vp', vp), ('nb', nb), ('nbp', nbp), ('ai', ai), ('aip', aip), ('b', b), ('bp', bp)):
            if x is not None:        # a total only counts hotels that were measured; none measured -> "–"
                tot[k] = (tot[k] or 0) + x
        serp_f = f.parent / 'serp.json'
        page1 = '–'
        if serp_f.exists():
            sq = json.loads(serp_f.read_text(encoding='utf-8')).get('search', {})
            disc = [k['keyword'] for k in (d.get('tracked') or {}).get('keywords', []) if k.get('type') != 'brand']
            page1 = f"{sum(1 for k in disc if (sq.get(k) or {}).get('position') and sq[k]['position'] <= 10)} / {len(disc)}"
        rows.append([h['name'], fmt(v), _chg(v, vp)['change'].split(' (')[0], fmt(nb), _chg(nb, nbp)['change'].split(' (')[0],
                     fmt(ai), fmt(b) if b is not None else '–',
                     f"{_g(mi, C, 'currency') or ''} {fmt(_g(mi, C, 'revenue'))}".strip() if b is not None else '–', page1])
        rep = sorted((gd / 'hotels' / h['slug'] / 'Reports').glob(f'* {h["name"]} Monthly Report ({label(month, True)}).pdf'))
        reports.append(f"{h['name']}: " + (f'`{rep[-1].name}`' if rep else 'not rendered yet'))
    mlabel = label(month)
    name = reg['group'].get('name') or 'Group'
    comps = [{'cards': [
        {'value': fmt(tot['v']), **_chg(tot['v'], tot['vp']), 'label': 'visits from Google search, all hotels'},
        {'value': fmt(tot['nb']), **_chg(tot['nb'], tot['nbp']), 'label': 'clicks from searches that don\'t name a hotel'},
        {'value': fmt(tot['ai']), **_chg(tot['ai'], tot['aip']), 'label': 'visits from AI assistants'},
        {'value': fmt(tot['b']), **_chg(tot['b'], tot['bp']), 'label': 'direct bookings (Mirai)'}]},
        {'title': 'Hotel by hotel', 'table': {'columns': ['Hotel', 'Google visits', 'vs last month', 'Non-brand clicks',
                                                         'vs last month', 'AI visits', 'Bookings', 'Revenue',
                                                         'Tracked on page 1'],
                                             'align': ['l', 'r', 'r', 'r', 'r', 'r', 'r', 'r', 'r'], 'rows': rows}},
        {'title': 'Hotel reports', 'list': reports}]
    if missing:
        comps.append({'note': 'Not collected this month: ' + ', '.join(missing) + '.'})
    pages = [{'eyebrow': f'01 · {name} in {mlabel}', 'title': 'All hotels at a glance',
              'intro': 'Totals add up the hotels\' own sections of the site (Search Console and Google Analytics '
                       'filtered by each hotel\'s pages).', 'components': comps, '_missing': []}]
    cover = {'eyebrow': f'MetaHotels · Monthly search report · {mlabel}', 'title': name,
             'subtitle': 'Group Monthly Summary', 'lead': f'Every hotel of {name} in {mlabel}: Google, AI assistants and '
                                                         'direct bookings.',
             'cards': comps[0]['cards'][:3], 'prepared': 'Prepared by MetaHotels · Dubai', 'date': _win_date()}
    doc = {'title': 'Group Monthly Summary', 'hotel': name, 'short_name': name, 'site': reg['group']['site'],
           'date': label(month, short=True), 'month': month, 'file_number': 'auto',
           'monthly': {'cover': cover, 'pages': pages, 'footer': f'{name} · Group Monthly Summary · {mlabel}'},
           'footer': '', 'sections': []}
    doc['sections'] = to_sections(doc)
    out = gd / 'group' / f'monthly-{month}'
    out.mkdir(parents=True, exist_ok=True)
    (out / 'monthly-report.json').write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding='utf-8')
    return {'file': str(out / 'monthly-report.json'), 'hotels': len(rows), 'not_collected': missing,
            'out_dir': str(gd / 'group' / 'Reports')}
