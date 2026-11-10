"""Google Business Profile: the hotel's listing, how guests find and use it, its reviews, and whether
the listing matches the website.

Needs, once per machine: the Google sign-in with Business Profile (hotel-seo-auth --with-gbp), as an
account that manages the hotel's profile (owner or manager), and these APIs enabled on the
metahotels-analytics Cloud project, which Google has approved for Business Profile API access:
  My Business Account Management API, My Business Business Information API,
  Business Profile Performance API, Google My Business API (reviews).

Google has no read-only scope for Business Profile. This module only reads (GET requests); changes go
through gbp_write.py, and only after the user approves a proposed change file.

Calls:
  locations(query)                                    every profile the account can see
  report(location, out_dir, crawl_dir, site, months)  listing, performance, search terms, reviews,
                                                      and the listing compared with the website
"""
import json
import math
import re
from collections import Counter
from datetime import date, timedelta
from urllib.parse import urlparse

import requests

from . import paths

GBP_SCOPE = 'https://www.googleapis.com/auth/business.manage'
ACCOUNTS = 'https://mybusinessaccountmanagement.googleapis.com/v1'
INFO = 'https://mybusinessbusinessinformation.googleapis.com/v1'
PERF = 'https://businessprofileperformance.googleapis.com/v1'
V4 = 'https://mybusiness.googleapis.com/v4'
READ_MASK = ('name,title,storeCode,languageCode,phoneNumbers,categories,storefrontAddress,websiteUri,'
             'regularHours,specialHours,latlng,openInfo,metadata,profile,labels')
DAILY_METRICS = {
    'BUSINESS_IMPRESSIONS_MOBILE_SEARCH': 'views_search_mobile',
    'BUSINESS_IMPRESSIONS_DESKTOP_SEARCH': 'views_search_desktop',
    'BUSINESS_IMPRESSIONS_MOBILE_MAPS': 'views_maps_mobile',
    'BUSINESS_IMPRESSIONS_DESKTOP_MAPS': 'views_maps_desktop',
    'WEBSITE_CLICKS': 'website_clicks',
    'CALL_CLICKS': 'calls',
    'BUSINESS_DIRECTION_REQUESTS': 'directions',
    # Reserve with Google bookings only, NOT hotel bookings (those come from Mirai). Business Profile chat
    # (BUSINESS_CONVERSATIONS) ended on 31 Jul 2024, so it isn't read.
    'BUSINESS_BOOKINGS': 'reserve_with_google_bookings',
}
STARS = {'ONE': 1, 'TWO': 2, 'THREE': 3, 'FOUR': 4, 'FIVE': 5}
APIS = {  # host -> (name in Cloud console, library id), for "enable this API" hints
    'mybusinessaccountmanagement': ('My Business Account Management API', 'mybusinessaccountmanagement.googleapis.com'),
    'mybusinessbusinessinformation': ('My Business Business Information API',
                                      'mybusinessbusinessinformation.googleapis.com'),
    'businessprofileperformance': ('Business Profile Performance API', 'businessprofileperformance.googleapis.com'),
    'mybusiness.': ('Google My Business API', 'mybusiness.googleapis.com'),
}


def configured():
    if not paths.GA_CREDENTIALS.exists():
        return False, 'no Google sign-in: run hotel-seo-auth --with-gbp'
    if GBP_SCOPE not in json.loads(paths.GA_CREDENTIALS.read_text()).get('scopes', []):
        return False, 'the Google sign-in has no Business Profile permission: run hotel-seo-auth --with-gbp'
    return True, ''


class GbpError(RuntimeError):
    pass


_token = {}


def _auth():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    creds = _token.get('creds')
    if creds is None:
        creds = Credentials.from_authorized_user_info(json.loads(paths.GA_CREDENTIALS.read_text()), [GBP_SCOPE])
        _token['creds'] = creds
    if not creds.valid:
        creds.refresh(Request())
    return {'Authorization': f'Bearer {creds.token}'}


def _hint(url, status, body):
    host = urlparse(url).netloc
    api = next((v for k, v in APIS.items() if host.startswith(k)), None)
    up = body.upper()
    if api and ('SERVICE_DISABLED' in up or 'HAS NOT BEEN USED' in up or 'IS DISABLED' in up):
        return (f' Enable the {api[0]}: https://console.cloud.google.com/apis/library/{api[1]}'
                f'?project={paths.GCP_PROJECT}')
    if status == 429 or 'QUOTA' in up:
        return (f' A quota of 0 means Google has not approved Business Profile API access for the '
                f'{paths.GCP_PROJECT} project (the approval is per project, not per account).')
    if status in (401, 403):
        return (' The signed-in account must be an owner or manager of the profile, and the sign-in must '
                'include Business Profile (hotel-seo-auth --with-gbp).')
    return ''


def _call(method, url, params=None, body=None):
    r = requests.request(method, url, params=params, json=body, headers=_auth(), timeout=60)
    if r.status_code not in (200, 204):
        raise GbpError(f'{r.status_code} from {urlparse(url).netloc}: {r.text[:500]}' + _hint(url, r.status_code, r.text))
    return r.json() if r.content else {}


def _get(url, params=None):
    return _call('GET', url, params)


def _pages(url, key, params=None):
    params = dict(params or {})
    while True:
        data = _get(url, params)
        yield from data.get(key, [])
        if not data.get('nextPageToken'):
            return
        params['pageToken'] = data['nextPageToken']


def _safe(fn):
    def wrap(*a, **kw):
        ok, why = configured()
        if not ok:
            return {'checked': False, 'reason': why}
        try:
            return fn(*a, **kw)
        except GbpError as e:
            return {'checked': False, 'reason': str(e)}
        except Exception as e:  # noqa: BLE001 - sign-in failures etc. as a readable reason
            return {'checked': False, 'reason': f'{type(e).__name__}: {str(e)[:400]}'}
    wrap.__name__, wrap.__doc__ = fn.__name__, fn.__doc__
    return wrap


# ---------- listing ----------

def _accounts():
    return list(_pages(f'{ACCOUNTS}/accounts', 'accounts', {'pageSize': 20}))


def _addr(loc):
    a = loc.get('storefrontAddress') or {}
    return ', '.join(x for x in [*a.get('addressLines', []), a.get('locality', ''), a.get('administrativeArea', ''),
                                 a.get('postalCode', ''), a.get('regionCode', '')] if x)


def _summary(loc, account=''):
    md = loc.get('metadata') or {}
    return {
        'location': loc['name'], 'account': account, 'title': loc.get('title', ''),
        'address': _addr(loc), 'website': loc.get('websiteUri', ''),
        'phone': (loc.get('phoneNumbers') or {}).get('primaryPhone', ''),
        'primary_category': ((loc.get('categories') or {}).get('primaryCategory') or {}).get('displayName', ''),
        'maps_url': md.get('mapsUri', ''), 'place_id': md.get('placeId', ''),
        'open_status': (loc.get('openInfo') or {}).get('status', ''),
        'has_voice_of_merchant': md.get('hasVoiceOfMerchant'),   # False: unverified or suspended
    }


def _all_locations():
    for acc in _accounts():
        for loc in _pages(f'{INFO}/{acc["name"]}/locations', 'locations', {'readMask': READ_MASK, 'pageSize': 100}):
            yield acc['name'], loc


@_safe
def locations(query=''):
    """Every Business Profile location the signed-in account manages, optionally filtered by text in the
    name, address or website."""
    q = (query or '').lower()
    rows = [_summary(loc, acc) for acc, loc in _all_locations()]
    if q:
        rows = [r for r in rows if q in ' '.join(str(v) for v in r.values()).lower()]
    return {'checked': True, 'count': len(rows), 'locations': rows}


def _find(location):
    """Accept "locations/123", "123", a website host or part of the name; return (account, location dict)."""
    want = str(location).strip()
    lid = want.split('/')[-1] if re.fullmatch(r'(locations/)?\d+', want) else ''
    host = re.sub(r'^https?://(www\.)?', '', want.lower()).strip('/')
    hits = []
    for acc, loc in _all_locations():
        site = re.sub(r'^https?://(www\.)?', '', (loc.get('websiteUri') or '').lower()).strip('/')
        if lid and loc['name'].split('/')[-1] == lid:
            return acc, loc
        if not lid and (host and site and (site == host or site.startswith(host + '/') or host.startswith(site + '/'))
                        or want.lower() in (loc.get('title') or '').lower()):
            hits.append((acc, loc))
    if len(hits) == 1:
        return hits[0]
    names = [f"{l.get('title')} ({l['name']}, {l.get('websiteUri', '')})" for _, l in hits[:15]]
    raise GbpError(f'"{location}" matches {len(hits)} profiles' + (': ' + '; '.join(names) if names else '')
                   + '. Pass the exact "locations/<id>" from gbp_locations.')


# ---------- performance ----------

def _daily(loc_name, start, end):
    params = [('dailyMetrics', m) for m in DAILY_METRICS]
    for k, d in (('startDate', start), ('endDate', end)):
        params += [(f'dailyRange.{k}.year', d.year), (f'dailyRange.{k}.month', d.month), (f'dailyRange.{k}.day', d.day)]
    data = _get(f'{PERF}/{loc_name}:fetchMultiDailyMetricsTimeSeries', params)
    by_month = {}
    for group in data.get('multiDailyMetricTimeSeries', []):
        for s in group.get('dailyMetricTimeSeries', []):
            key = DAILY_METRICS.get(s.get('dailyMetric'), s.get('dailyMetric'))
            for dv in (s.get('timeSeries') or {}).get('datedValues', []):
                d = dv['date']
                month = f"{d['year']}-{d['month']:02d}"
                row = by_month.setdefault(month, Counter())
                row[key] += int(dv.get('value') or 0)
    months = []
    for m in sorted(by_month):
        r = by_month[m]
        views = sum(r[k] for k in ('views_search_mobile', 'views_search_desktop', 'views_maps_mobile',
                                   'views_maps_desktop'))
        months.append({'month': m, 'views': views, 'views_search': r['views_search_mobile'] + r['views_search_desktop'],
                       'views_maps': r['views_maps_mobile'] + r['views_maps_desktop'],
                       'views_mobile': r['views_search_mobile'] + r['views_maps_mobile'],
                       **{k: r[k] for k in ('website_clicks', 'calls', 'directions', 'reserve_with_google_bookings')},
                       'website_click_rate_pct': round(100 * r['website_clicks'] / views, 2) if views else None})
    return months


def _keywords(loc_name, start, end):
    params = {'monthlyRange.startMonth.year': start.year, 'monthlyRange.startMonth.month': start.month,
              'monthlyRange.endMonth.year': end.year, 'monthlyRange.endMonth.month': end.month, 'pageSize': 100}
    rows = []
    for k in _pages(f'{PERF}/{loc_name}/searchkeywords/impressions/monthly', 'searchKeywordsCounts', params):
        v = k.get('insightsValue') or {}
        # Google hides small counts: "threshold" means fewer than that many
        rows.append({'keyword': k.get('searchKeyword', ''),
                     'impressions': int(v['value']) if 'value' in v else None,
                     'below': int(v['threshold']) if 'threshold' in v else None})
        if len(rows) >= 500:
            break
    rows.sort(key=lambda r: -(r['impressions'] or 0))
    return rows


# ---------- reviews ----------

def _reviews(account, loc_name, limit=200):
    url = f'{V4}/{account}/{loc_name}/reviews'
    params = {'pageSize': 50, 'orderBy': 'updateTime desc'}
    out, head = [], {}
    while len(out) < limit:
        data = _get(url, params)
        head = head or {'average_rating': data.get('averageRating'), 'total': data.get('totalReviewCount')}
        for r in data.get('reviews', []):
            reply = r.get('reviewReply') or {}
            # No reviewer names: not needed for SEO work, and they are guests' names.
            out.append({'review_id': r.get('reviewId', ''), 'stars': STARS.get(r.get('starRating'), None), 'date': (r.get('createTime') or '')[:10],
                        'comment': (r.get('comment') or '').split('(Original)')[0].strip()[:1500],
                        'replied': bool(reply), 'reply_date': (reply.get('updateTime') or '')[:10],
                        'reply': (reply.get('comment') or '')[:1500]})
        if not data.get('nextPageToken'):
            break
        params['pageToken'] = data['nextPageToken']
    stars = Counter(r['stars'] for r in out)
    recent = [r for r in out if r['date'] >= (date.today() - timedelta(days=90)).isoformat()]
    unanswered = [r for r in out if not r['replied']]
    lag = []
    for r in out:
        if r['replied'] and r['reply_date'] and r['date']:
            lag.append((date.fromisoformat(r['reply_date']) - date.fromisoformat(r['date'])).days)
    return {**head, 'fetched': len(out), 'stars': {k: stars.get(k, 0) for k in (5, 4, 3, 2, 1)},
            'last_90_days': len(recent),
            'last_90_days_avg': round(sum(r['stars'] or 0 for r in recent) / len(recent), 2) if recent else None,
            'reply_rate_pct': round(100 * (len(out) - len(unanswered)) / len(out), 1) if out else None,
            'median_reply_days': sorted(lag)[len(lag) // 2] if lag else None,
            'unanswered_low': [r for r in unanswered if (r['stars'] or 5) <= 3][:20],
            'reviews': out}


# ---------- listing vs website ----------

def _digits(s):
    d = re.sub(r'\D', '', s or '')
    return d[2:] if d.startswith('00') else d


def _host(u):
    return re.sub(r'^www\.', '', urlparse(u if '//' in (u or '') else f'//{u}').netloc.lower())


def _km(a, b):
    (la1, lo1), (la2, lo2) = a, b
    p = math.pi / 180
    h = (math.sin((la2 - la1) * p / 2) ** 2
         + math.cos(la1 * p) * math.cos(la2 * p) * math.sin((lo2 - lo1) * p / 2) ** 2)
    return 12742 * math.asin(math.sqrt(h))


def _norm_name(s):
    return re.sub(r'[^a-z0-9؀-ۿ]+', ' ', (s or '').lower()).strip()


def _website_check(uri, site):
    out = {'website_uri': uri}
    if not uri:
        out['problem'] = 'no website on the profile'
        return out
    q = urlparse(uri).query
    out['utm'] = 'utm_' in q
    try:
        r = requests.get(uri, timeout=30, allow_redirects=True, headers={'User-Agent': 'Mozilla/5.0 hotel-seo'})
        out.update(status=r.status_code, final_url=r.url, redirects=len(r.history))
    except requests.RequestException as e:
        out.update(status=None, error=str(e)[:200])
    probs = []
    if out.get('status') != 200:
        probs.append(f"website link ends on {out.get('status') or out.get('error')}")
    if out.get('redirects'):
        probs.append(f"website link redirects {out['redirects']}x to {out.get('final_url')}")
    if site and _host(uri) != _host(site):
        probs.append(f'website link is on {_host(uri)}, the hotel site is {_host(site)}')
    if not out['utm']:
        probs.append('no UTM tags: GA4 counts profile visits as Google organic, not as Business Profile')
    out['problems'] = probs
    return out


def _compare(loc, crawl_dir, site):
    """Listing vs the website's schema and tel: links (from audit_site's findings.json)."""
    out = {'website': _website_check(loc.get('websiteUri', ''), site)}
    if not crawl_dir:
        out['schema'] = 'no crawl_dir: run audit_site first and pass its crawl folder to compare name, phone, address'
        return out
    f = paths.resolve(crawl_dir) / 'findings.json'
    if not f.exists():
        out['schema'] = f'{f} missing: run audit_site on this crawl first'
        return out
    findings = json.loads(f.read_text(encoding='utf-8'))
    rep = findings.get('report', {})
    from .analysis import BUSINESS_TYPES
    blocks = [b for b in rep.get('schema', {}).get('blocks', []) if b.get('type') in BUSINESS_TYPES]
    title = loc.get('title', '')
    gbp_phone = _digits((loc.get('phoneNumbers') or {}).get('primaryPhone', ''))
    ll = loc.get('latlng') or {}
    gbp_geo = (ll.get('latitude'), ll.get('longitude')) if ll else None
    addr = loc.get('storefrontAddress') or {}
    diffs, rows = [], []
    for b in blocks:
        row = {'type': b['type'], 'name': b.get('name', ''), 'pages': b.get('pages'), 'urls': b.get('urls', [])}
        if b.get('name') and _norm_name(b['name']) != _norm_name(title):
            row['name_differs'] = True
        if b.get('telephone') and gbp_phone and _digits(b['telephone'])[-9:] != gbp_phone[-9:]:
            row['phone_differs'] = b['telephone']
        if b.get('geo') and gbp_geo and ',' in b['geo']:
            try:
                la, lo = (float(x) for x in b['geo'].split(','))
                km = _km((la, lo), gbp_geo)
                row['geo_km_from_profile'] = round(km, 2)
            except ValueError:
                pass
        if b.get('locality') and addr.get('locality') and _norm_name(b['locality']) != _norm_name(addr['locality']):
            row['locality_differs'] = f"{b['locality']} (profile: {addr['locality']})"
        rows.append(row)
    if not blocks:
        diffs.append('the website has no Hotel / LodgingBusiness schema to match the profile against')
    for r in rows:
        where = f"{r['type']} \"{r['name']}\" on {r['pages']} pages"
        if r.get('name_differs'):
            diffs.append(f'name: profile "{title}", schema {where}')
        if r.get('phone_differs'):
            diffs.append(f"phone: profile {(loc.get('phoneNumbers') or {}).get('primaryPhone')}, schema "
                         f"{r['phone_differs']} ({where})")
        if r.get('geo_km_from_profile', 0) > 0.2:
            diffs.append(f"location: schema coordinates are {r['geo_km_from_profile']} km from the profile pin ({where})")
        if r.get('locality_differs'):
            diffs.append(f"city: schema {r['locality_differs']} ({where})")
    site_phones = [p['number'] for p in rep.get('phones', {}).get('numbers', []) if p.get('in_tel_links')]
    if gbp_phone and site_phones and not any(_digits(p)[-9:] == gbp_phone[-9:] for p in site_phones):
        diffs.append(f"phone: profile {(loc.get('phoneNumbers') or {}).get('primaryPhone')} is in no tel: link on the "
                     f"site (site uses {', '.join(site_phones[:3])})")
    maps = (loc.get('metadata') or {}).get('mapsUri', '')
    linked = any(b.get('maps_sameas') for b in blocks)
    if blocks and not linked:
        diffs.append(f'no business schema links to the Google profile (add {maps or "the Maps URL"} to sameAs or hasMap)')
    out['schema'] = {'blocks': rows, 'differences': diffs, 'profile_maps_url': maps}
    return out


def _listing_checks(loc, google_updated):
    c, notes = loc.get('categories') or {}, []
    prim = (c.get('primaryCategory') or {}).get('displayName', '')
    if prim and not re.search(r'hotel|resort|inn|lodging|motel|hostel|apartment', prim, re.I):
        notes.append(f'primary category is "{prim}", not a lodging category')
    if not (loc.get('profile') or {}).get('description'):
        notes.append('no business description')
    if (loc.get('openInfo') or {}).get('status') not in (None, '', 'OPEN'):
        notes.append(f"profile status {(loc.get('openInfo') or {}).get('status')}")
    md = loc.get('metadata') or {}
    if md.get('hasPendingEdits'):
        notes.append('edits waiting for Google review')
    if md.get('duplicateLocation'):
        notes.append(f"Google marks this as a duplicate of {md['duplicateLocation']}")
    if md.get('hasGoogleUpdated') and google_updated.get('diffMask'):
        notes.append(f"Google changed these fields itself (accept or reject in the profile): {google_updated['diffMask']}")
    return notes


@_safe
def report(location, out_dir='', crawl_dir='', site='', months=12, reviews_limit=200):
    """Listing, monthly performance, search terms, reviews and the listing-vs-website comparison
    for one location. Writes gbp-<date>.json / .md in out_dir."""
    account, loc = _find(location)
    name = loc['name']
    errors = {}
    try:
        gu = _get(f'{INFO}/{name}:getGoogleUpdated', {'readMask': READ_MASK})
    except GbpError as e:
        gu, errors['google_updated'] = {}, str(e)
    try:
        attrs = [a.get('name', '').split('/')[-1] for a in _get(f'{INFO}/{name}/attributes').get('attributes', [])
                 if a.get('values') not in ([False], None)]
    except GbpError as e:
        attrs, errors['attributes'] = [], str(e)

    end = date.today() - timedelta(days=3)          # Performance data lags a few days
    start = (end.replace(day=1) - timedelta(days=31 * (months - 1))).replace(day=1)
    try:
        perf = _daily(name, start, end)
    except GbpError as e:
        perf, errors['performance'] = [], str(e)
    kw_end = end.replace(day=1) - timedelta(days=1)  # last complete month
    kw_start = (kw_end - timedelta(days=88)).replace(day=1)
    try:
        kws = _keywords(name, kw_start, kw_end)
    except GbpError as e:
        kws, errors['search_terms'] = [], str(e)
    try:
        revs = _reviews(account, name, reviews_limit)
    except GbpError as e:
        revs, errors['reviews'] = {}, str(e)

    result = {
        'checked': True, 'generated': date.today().isoformat(), 'listing': _summary(loc, account),
        'listing_notes': _listing_checks(loc, gu),
        'categories': [(loc.get('categories') or {}).get('primaryCategory', {}).get('displayName', '')]
                      + [c.get('displayName', '') for c in (loc.get('categories') or {}).get('additionalCategories', [])],
        'description': (loc.get('profile') or {}).get('description', ''),
        'attributes_on': attrs,
        'performance_by_month': perf,
        'search_terms': {'months': f'{kw_start:%Y-%m} to {kw_end:%Y-%m}', 'rows': kws},
        'reviews': revs,
        'vs_website': _compare(loc, crawl_dir, site or loc.get('websiteUri', '')),
        'errors': errors,
    }
    if out_dir:
        out = paths.resolve(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        stem = out / f'gbp-{date.today().isoformat()}'
        stem.with_suffix('.json').write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding='utf-8')
        stem.with_suffix('.md').write_text(_md(result), encoding='utf-8')
        result['files'] = [str(stem.with_suffix('.json')), str(stem.with_suffix('.md'))]
    # keep the tool reply small: full review text and all search terms are in the files
    short = dict(result)
    short['reviews'] = {k: v for k, v in revs.items() if k != 'reviews'}
    short['search_terms'] = {'months': result['search_terms']['months'], 'top': kws[:40], 'total': len(kws)}
    return short


def _md(r):
    L = [f"# Business Profile: {r['listing']['title']} ({r['generated']})", '',
         f"- Profile: {r['listing']['location']} · {r['listing']['maps_url']}",
         f"- Address: {r['listing']['address']}", f"- Phone: {r['listing']['phone']}",
         f"- Website link: {r['listing']['website']}", f"- Categories: {', '.join(c for c in r['categories'] if c)}", '']
    if r['listing_notes']:
        L += ['## Listing notes', *[f'- {n}' for n in r['listing_notes']], '']
    vs = r['vs_website']
    L += ['## Listing vs website', *[f'- {p}' for p in vs['website'].get('problems', [])]]
    if isinstance(vs.get('schema'), dict):
        L += [f'- {d}' for d in vs['schema']['differences']] or ['- schema name, phone, city and pin match the profile']
    else:
        L.append(f"- {vs.get('schema')}")
    L.append('')
    if r['performance_by_month']:
        L += ['## Performance by month', '',
              '| Month | Views | Search | Maps | Website clicks | Calls | Directions | Click rate |',
              '|---|---:|---:|---:|---:|---:|---:|---:|']
        for m in r['performance_by_month']:
            L.append(f"| {m['month']} | {m['views']} | {m['views_search']} | {m['views_maps']} | {m['website_clicks']} "
                     f"| {m['calls']} | {m['directions']} | {m['website_click_rate_pct'] or ''}% |")
        L.append('')
    kw = r['search_terms']['rows']
    if kw:
        L += [f"## Searches that showed the profile ({r['search_terms']['months']})", '']
        L += [f"- {k['keyword']}: {k['impressions'] if k['impressions'] is not None else '< ' + str(k['below'])}"
              for k in kw[:60]]
        L.append('')
    rv = r['reviews']
    if rv:
        L += ['## Reviews', f"- {rv.get('average_rating')} average from {rv.get('total')} reviews; "
              f"{rv.get('last_90_days')} in the last 90 days (avg {rv.get('last_90_days_avg')})",
              f"- Stars: {rv.get('stars')}", f"- Replied to {rv.get('reply_rate_pct')}% "
              f"(median {rv.get('median_reply_days')} days)",
              f"- Unanswered 1-3 star reviews: {len(rv.get('unanswered_low', []))}", '']
    if r['errors']:
        L += ['## Not available', *[f'- {k}: {v}' for k, v in r['errors'].items()], '']
    return '\n'.join(L)
