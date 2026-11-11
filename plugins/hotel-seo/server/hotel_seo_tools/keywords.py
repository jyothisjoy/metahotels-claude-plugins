"""Keyword Planner through the Google Ads API: search volumes, competition and bid ranges.

Needs, once per machine:
  - the Google sign-in (hotel-seo-auth) to include the Ads permission; the signed-in
    account must have access to the MetaHotels Google Ads manager account
  - ~/.metahotels-seo/google/ads.json with the account IDs (not secret), written by
    `hotel-seo-ads-login`

No developer token: Google retired them on 9 Sep 2026. API access now comes from the Google Cloud
project that owns the OAuth client (metahotels-analytics), and Keyword Planner needs that project
at **Basic** access or higher (Explorer blocks KeywordPlanIdeaService). Cloud console → Google Ads
API → Overview shows the level.

Two calls:
  ideas(seeds, url)      GenerateKeywordIdeas: new keywords from seed words and/or the hotel's site
  volumes(keywords)      GenerateKeywordHistoricalMetrics: numbers for keywords we already have
                         (e.g. the money searches from Search Console)

Both write keywords-<date>.csv / .json in out_dir. Default market: United Arab Emirates, English.
"""
import argparse
import csv
import json
import re
from datetime import date

from . import paths

ADS_CONFIG = paths.GOOGLE_DIR / 'ads.json'
ADS_SCOPE = 'https://www.googleapis.com/auth/adwords'
# Google Ads geo target and language constants (developers.google.com/google-ads/api/data/geotargets)
GEO = {'EG': 2818, 'AE': 2784, 'SA': 2682, 'GB': 2826, 'IN': 2356, 'RU': 2643, 'DE': 2276, 'US': 2840, 'KW': 2414,
       'QA': 2634, 'OM': 2512, 'BH': 2048, 'FR': 2250, 'IT': 2380, 'CN': 2156, 'KZ': 2398, 'PK': 2586}
LANG = {'en': 1000, 'ar': 1019, 'ru': 1031, 'de': 1001, 'fr': 1002, 'it': 1004, 'zh': 1017, 'hi': 1023}


def configured():
    if not ADS_CONFIG.exists():
        return False, f'{ADS_CONFIG} missing: run hotel-seo-ads-login'
    if not paths.GA_CREDENTIALS.exists():
        return False, 'no Google sign-in: run hotel-seo-auth'
    adc = json.loads(paths.GA_CREDENTIALS.read_text())
    if ADS_SCOPE not in adc.get('scopes', []):
        return False, 'the Google sign-in has no Ads permission: run hotel-seo-auth'
    return True, ''


def _client():
    cfg = json.loads(ADS_CONFIG.read_text())
    adc = json.loads(paths.GA_CREDENTIALS.read_text())
    from google.ads.googleads.client import GoogleAdsClient
    # No developer token (retired; google-ads >= 32 no longer requires one): access comes from the
    # Cloud project behind the OAuth client.
    return GoogleAdsClient.load_from_dict({
        'login_customer_id': str(cfg['login_customer_id']).replace('-', ''),
        'client_id': adc['client_id'], 'client_secret': adc['client_secret'],
        'refresh_token': adc['refresh_token'], 'use_proto_plus': True,
    }), str(cfg.get('customer_id') or cfg['login_customer_id']).replace('-', '')


_GEO_CACHE = {}


def geo_id(client, place, country_code=''):
    """Google Ads geo target constant id for a country code (AE), a numeric id, or a place name (Dubai, Al Barsha)."""
    p = str(place).strip()
    if p.isdigit():
        return p
    if p.upper() in GEO:
        return str(GEO[p.upper()])
    key = (p.lower(), country_code.upper())
    if key in _GEO_CACHE:
        return _GEO_CACHE[key]
    svc = client.get_service('GeoTargetConstantService')
    req = client.get_type('SuggestGeoTargetConstantsRequest')
    req.locale = 'en'
    if country_code:
        req.country_code = country_code.upper()
    req.location_names.names.append(p)
    res = svc.suggest_geo_target_constants(request=req)
    for s in res.geo_target_constant_suggestions:
        g = s.geo_target_constant
        if g.status.name == 'ENABLED':
            _GEO_CACHE[key] = str(g.id)
            return _GEO_CACHE[key]
    raise ValueError(f'no Google Ads location found for "{p}"')


def _targets(client, req, countries, language, country_code=''):
    for c in countries:
        if str(c).upper() in ('WORLD', 'WORLDWIDE', 'ALL'):
            continue                    # no geo target = worldwide
        req.geo_target_constants.append(client.get_service('GeoTargetConstantService')
                                        .geo_target_constant_path(geo_id(client, c, country_code)))
    req.language = client.get_service('GoogleAdsService').language_constant_path(str(LANG.get(language, language)))
    req.keyword_plan_network = client.enums.KeywordPlanNetworkEnum.GOOGLE_SEARCH


def _row(text, m):
    vols = [{'month': f'{v.year}-{int(v.month) - 1:02d}' if int(v.month) > 1 else f'{v.year}-?',
             'searches': v.monthly_searches} for v in m.monthly_search_volumes]
    return {'keyword': text, 'avg_monthly_searches': m.avg_monthly_searches,
            'competition': m.competition.name, 'competition_index': m.competition_index,
            'low_top_bid': round(m.low_top_of_page_bid_micros / 1e6, 2),
            'high_top_bid': round(m.high_top_of_page_bid_micros / 1e6, 2),
            'monthly': vols}


def _save(rows, out_dir, kind, meta):
    out = paths.resolve(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = out / f'keywords-{kind}-{date.today().isoformat()}'
    with open(stem.with_suffix('.csv'), 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['keyword', 'avg_monthly_searches', 'competition', 'low_top_bid', 'high_top_bid'])
        for r in rows:
            w.writerow([r['keyword'], r['avg_monthly_searches'], r['competition'], r['low_top_bid'], r['high_top_bid']])
    stem.with_suffix('.json').write_text(json.dumps(dict(meta, rows=rows), indent=1, ensure_ascii=False),
                                         encoding='utf-8')
    return [str(stem.with_suffix('.csv')), str(stem.with_suffix('.json'))]


def _safe(fn):
    """Turn Google Ads / sign-in failures into a readable reason instead of a traceback."""
    def wrap(*a, **kw):
        try:
            return fn(*a, **kw)
        except Exception as e:
            name = type(e).__name__
            msg = str(e)
            failure = getattr(e, 'failure', None)
            if failure is not None:
                msg = '; '.join(err.message for err in failure.errors)[:500]
            hint, up = '', (name + ' ' + msg + ' ' + str(e)).upper()
            if any(k in up for k in ('CLOUD_PROJECT_NOT_APPROVED', 'ACTION_NOT_PERMITTED', 'DEVELOPER_TOKEN',
                                     'ACCESS LEVEL', 'NOT ALLOWED FOR EXPLORER')):
                hint = (f' Keyword Planner needs the {paths.GCP_PROJECT} Cloud project at Basic access or higher '
                        '(Cloud console → Google Ads API → Overview); Explorer blocks it.')
            elif name == 'RefreshError' or 'PERMISSION' in up:
                hint = (' The signed-in Google account needs access to the Ads manager account, and the sign-in '
                        'must include Ads (run hotel-seo-auth).')
            return {'checked': False, 'reason': f'{name}: {msg[:400]}.{hint}'}
    wrap.__name__, wrap.__doc__ = fn.__name__, fn.__doc__
    return wrap


@_safe
def ideas(seeds=None, url='', out_dir='.', countries=('AE',), language='en', limit=None, country_code=''):
    ok, why = configured()
    if not ok:
        return {'checked': False, 'reason': why}
    client, cid = _client()
    req = client.get_type('GenerateKeywordIdeasRequest')
    req.customer_id = cid
    _targets(client, req, countries, language, country_code)
    seeds = [s for s in (seeds or []) if s][:20]          # Google Ads accepts at most 20 seed keywords
    if seeds and url:
        req.keyword_and_url_seed.url = url
        req.keyword_and_url_seed.keywords.extend(seeds)
    elif seeds:
        req.keyword_seed.keywords.extend(seeds)
    elif url:
        req.site_seed.site = url.split('//')[-1].split('/')[0]
    else:
        return {'checked': False, 'reason': 'give seed keywords and/or the hotel URL'}
    rows = []
    for idea in client.get_service('KeywordPlanIdeaService').generate_keyword_ideas(request=req):
        rows.append(_row(idea.text, idea.keyword_idea_metrics))
        if limit and len(rows) >= limit:
            break
    rows.sort(key=lambda r: -(r['avg_monthly_searches'] or 0))
    meta = {'kind': 'ideas', 'seeds': seeds, 'url': url, 'countries': list(countries), 'language': language}
    files = _save(rows, out_dir, 'ideas', meta)
    out = {'checked': True, 'count': len(rows), 'files': files}
    if len(rows) <= 400:
        out['rows'] = rows
    else:
        out['first_rows'] = rows[:100]
        out['note'] = f'{len(rows)} ideas: all of them are in {files[1]}'
    return out


@_safe
def volumes(keywords, out_dir='.', countries=('AE',), language='en', country_code='', save=True):
    ok, why = configured()
    if not ok:
        return {'checked': False, 'reason': why}
    client, cid = _client()
    kws = list(dict.fromkeys(k.strip().lower() for k in keywords if k and k.strip()))
    rows = []
    for i in range(0, len(kws), 5000):          # well under the API's 10,000-keyword request limit
        req = client.get_type('GenerateKeywordHistoricalMetricsRequest')
        req.customer_id = cid
        _targets(client, req, countries, language, country_code)
        req.keywords.extend(kws[i:i + 5000])
        resp = client.get_service('KeywordPlanIdeaService').generate_keyword_historical_metrics(request=req)
        rows += [dict(_row(r.text, r.keyword_metrics), close_variants=list(r.close_variants)) for r in resp.results]
    rows.sort(key=lambda r: -(r['avg_monthly_searches'] or 0))
    meta = {'kind': 'volumes', 'countries': list(countries), 'language': language}
    out = {'checked': True, 'count': len(rows), 'requested': len(kws), 'rows': rows}
    if save:
        out['files'] = _save(rows, out_dir, 'volumes', meta)
    return out


def login():
    """hotel-seo-ads-login: store the Google Ads account IDs for Keyword Planner (no secrets)."""
    ap = argparse.ArgumentParser(description='Save the Google Ads account IDs for Keyword Planner. '
                                             'No developer token: Google retired them on 9 Sep 2026.')
    ap.add_argument('--manager', help='manager (MCC) account ID, e.g. 437-179-3247')
    ap.add_argument('--customer', help='account to run Keyword Planner in (default: the manager)')
    args = ap.parse_args()
    mcc = (args.manager or input('Manager account ID (e.g. 123-456-7890): ')).strip()
    cid = (args.customer or (input('Account to run Keyword Planner in (Enter = same as manager): ')
                             if not args.manager else '')).strip() or mcc
    if not re.fullmatch(r'\d{3}-?\d{3}-?\d{4}', mcc) or not re.fullmatch(r'\d{3}-?\d{3}-?\d{4}', cid):
        raise SystemExit('Nothing saved: account IDs look like 123-456-7890.')
    paths.GOOGLE_DIR.mkdir(parents=True, exist_ok=True)
    ADS_CONFIG.write_text(json.dumps({'login_customer_id': mcc, 'customer_id': cid}, indent=2))
    print(f'Saved to {ADS_CONFIG}. If the Google sign-in has no Ads permission yet, run '
          'hotel-seo-auth once.')


if __name__ == '__main__':
    login()
