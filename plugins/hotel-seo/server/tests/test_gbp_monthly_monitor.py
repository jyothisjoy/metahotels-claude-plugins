"""Business Profile in the monthly report (API block, Chrome fallback, page 06) and in the daily monitor (Google
changes, edits outside our log, low and unanswered reviews, first-run baseline). No live Google calls."""
import json
from datetime import date

import pytest

from hotel_seo_tools import gbp, group, monitor, monthly

DOMAIN = 'example-hotels.com'


@pytest.fixture
def hotel(tmp_path, monkeypatch):
    monkeypatch.setenv('HOTEL_SEO_HOME', str(tmp_path))
    group.save(DOMAIN, {'name': 'Example Group', 'site': f'https://{DOMAIN}/'},
               [{'slug': 'park', 'name': 'Example Park Hotel', 'paths': ['/'], 'city': 'Dubai',
                 'gsc_property': f'sc-domain:{DOMAIN}', 'ga4_property': 'properties/1'}])
    return tmp_path


def _link(tmp_path):
    (tmp_path / DOMAIN / 'hotel.json').write_text(json.dumps({'gbp': {
        'location': 'locations/42', 'account': 'accounts/1', 'title': 'Example Park Hotel'}}), encoding='utf-8')


def _perf(month, views=1000, mobile=700, rwg=0):
    return {'month': month, 'views': views, 'views_search': 600, 'views_maps': views - 600, 'views_mobile': mobile,
            'website_clicks': 120, 'calls': 30, 'directions': 45, 'reserve_with_google_bookings': rwg,
            'website_click_rate_pct': 12.0}


REVIEWS = {'average_rating': 4.4, 'total': 6, 'reviews': [
    {'review_id': 'r6', 'stars': 5, 'date': '2026-11-05', 'replied': True},
    {'review_id': 'r5', 'stars': 3, 'date': '2026-10-20', 'replied': False},
    {'review_id': 'r4', 'stars': 5, 'date': '2026-10-12', 'replied': True},
    {'review_id': 'r3', 'stars': 4, 'date': '2026-10-02', 'replied': True},
    {'review_id': 'r2', 'stars': 4, 'date': '2026-09-15', 'replied': True},
    {'review_id': 'r1', 'stars': 5, 'date': '2025-10-03', 'replied': True}]}


@pytest.fixture
def api(monkeypatch):
    calls = {'daily': []}
    monkeypatch.setattr(gbp, 'configured', lambda: (True, ''))

    def daily(loc, s, e):
        calls['daily'].append((loc, s, e))
        return [_perf(f'{s:%Y-%m}', views={2026: 1000, 2025: 400}[s.year] if s.month == 10 else 800,
                      rwg=2 if (s.year, s.month) == (2026, 10) else 0)]
    monkeypatch.setattr(gbp, '_daily', daily)
    monkeypatch.setattr(gbp, '_keywords', lambda loc, s, e: [
        {'keyword': 'hotel near dubai mall', 'impressions': 340, 'below': None},
        {'keyword': 'example park hotel', 'impressions': 120, 'below': None},
        {'keyword': 'cheap stay downtown', 'impressions': None, 'below': 15}])
    monkeypatch.setattr(gbp, '_reviews', lambda account, loc, limit=200: REVIEWS)
    return calls


# ---------------------------------------------------------------- monthly: collecting

def test_monthly_gbp_block_from_the_api(hotel, api):
    _link(hotel)
    ctx = monthly.context(DOMAIN, 'park')
    g = monthly._gbp(ctx, monthly.periods('2026-10'), today=date(2026, 11, 10))
    assert g['status'] == 'ok' and g['source'] == 'Business Profile API' and g['location'] == 'locations/42'
    assert g['current']['views'] == 1000 and g['current']['views_desktop'] == 300
    assert g['previous']['views'] == 800 and g['last_year']['views'] == 400
    assert g['current']['reserve_with_google_bookings'] == 2
    assert [c[0] for c in api['daily']] == ['locations/42'] * 3
    terms = g['search_terms']
    assert terms['month'] == '2026-10' and terms['rows'][0]['display'] == '340'
    assert terms['rows'][2]['display'] == '< 15'               # Google's threshold kept as given
    rv = g['reviews']
    assert rv['rating_now'] == 4.4 and rv['total_now'] == 6
    assert rv['current'] == {'complete': True, 'new': 3, 'replied': 2, 'unanswered': 1, 'avg_stars': 4.0}
    assert rv['previous']['new'] == 1 and rv['last_year']['new'] == 1
    assert rv['total_month_end'] == 5                           # one review came after 31 Oct
    assert rv['rating_month_end'] == 4.3 and rv['rating_month_end_approx'] is True


def test_monthly_gbp_period_older_than_the_reviews_read_is_not_counted():
    rows = [{'review_id': str(i), 'stars': 5, 'date': '2026-10-15', 'replied': True} for i in range(300)]
    rv = monthly._gbp_reviews({'average_rating': 4.8, 'total': 900, 'reviews': rows}, monthly.periods('2026-10'))
    assert rv['current']['complete'] is False and rv['current']['new'] is None
    assert rv['rating_month_end'] == 4.8 and rv['total_month_end'] == 900   # nothing since 31 Oct: exact
    later = [{**r, 'date': '2026-11-05'} for r in rows]
    rv = monthly._gbp_reviews({'average_rating': 4.8, 'total': 900, 'reviews': later}, monthly.periods('2026-10'))
    assert 'rating_month_end' not in rv and rv['previous']['new'] is None


def test_monthly_gbp_not_linked_or_not_signed_in_falls_back(hotel, monkeypatch):
    ctx = monthly.context(DOMAIN, 'park')
    g = monthly._gbp(ctx, monthly.periods('2026-10'))
    assert g['status'].startswith('not available') and 'gbp_link' in g['status']
    _link(hotel)
    monkeypatch.setattr(gbp, 'configured', lambda: (False, 'no Google sign-in: run hotel-seo-auth'))
    assert monthly._gbp(ctx, monthly.periods('2026-10'))['status'] == \
        'not available: no Google sign-in: run hotel-seo-auth'


# ---------------------------------------------------------------- monthly: page 06

def _data(gbp_block):
    return {'hotel': 'Example Park Hotel', 'month': '2026-10', 'brand_terms': ['example park'],
            'periods': {'current': ['2026-10-01', '2026-10-31'], 'previous': ['2026-09-01', '2026-09-30'],
                        'last_year': ['2025-10-01', '2025-10-31']},
            'gsc': {'status': 'not available: test'}, 'ga4': {'status': 'not available: test'},
            'mirai': {'status': 'not available'}, 'parity': {'status': 'not available'},
            'index': {'status': 'not available'}, 'work': {'items': [], 'build_plan_steps': []},
            'tracked': {'keywords': []}, 'gbp': gbp_block}


def _page06(hotel, gbp_block, manual=None):
    md = hotel / DOMAIN / 'monthly-2026-10'
    md.mkdir(parents=True, exist_ok=True)
    (md / 'data.json').write_text(json.dumps(_data(gbp_block)), encoding='utf-8')
    if manual is not None:
        (md / 'manual.json').write_text(json.dumps(manual), encoding='utf-8')
    r = monthly.build(DOMAIN, 'park', '2026-10')
    doc = json.loads(open(r['file'], encoding='utf-8').read())
    return next(p for p in doc['monthly']['pages'] if p['eyebrow'].startswith('06')), r


def _api_block(hotel, api):
    _link(hotel)
    return monthly._gbp(monthly.context(DOMAIN, 'park'), monthly.periods('2026-10'), today=date(2026, 11, 10))


def test_page06_from_the_api(hotel, api):
    page, r = _page06(hotel, _api_block(hotel, api))
    cards = page['components'][0]['cards']
    by = {c['label']: c for c in cards}
    assert by['Google rating']['value'] == '4.4 ★' and by['Google rating']['change'] == '6 Google reviews'
    views = by['people viewed the Business Profile (Google Search and Maps)']
    assert views['value'] == '1,000' and views['change'] == '▲ +25% (from 800)'
    assert any(c['label'].startswith('Reserve with Google') and 'not the hotel' in c['label'] for c in cards)
    table = next(c for c in page['components'] if c.get('title', '').startswith('Business Profile: this month'))
    assert table['table']['columns'] == ['', 'October 2026', 'September 2026', 'October 2025']
    rows = {row[0]: row[1:] for row in table['table']['rows']}
    assert rows['Profile views'] == ['1,000', '800', '400']
    assert rows['· on desktop'][:2] == ['300', '100']
    assert rows['New Google reviews'] == ['3', '1', '1']
    grid = next(c['grid2'] for c in page['components'] if 'grid2' in c)
    assert grid[0]['table']['rows'][2] == ['cheap stay downtown', '< 15']
    assert '3 new reviews' in grid[1]['text'] and '1 not answered' in grid[1]['text']
    assert 'about 4.3 ★ from 5' in grid[1]['text'] and grid[1]['tone'] == 'bad'
    assert any('Business Profile API' in c.get('note', '') for c in page['components'])
    assert not page['_missing'] and not any(m.startswith('06') for m in r['not_available'])


def test_page06_no_reserve_with_google_when_zero(hotel, api, monkeypatch):
    monkeypatch.setattr(gbp, '_daily', lambda loc, s, e: [_perf(f'{s:%Y-%m}')])
    page, _ = _page06(hotel, _api_block(hotel, api))
    assert not any('Reserve with Google' in c['label'] for c in page['components'][0]['cards'])
    table = next(c for c in page['components'] if c.get('title', '').startswith('Business Profile: this month'))
    assert not any('Reserve' in row[0] for row in table['table']['rows'])


def test_page06_manual_fills_only_what_the_api_cannot(hotel, api):
    manual = {'gbp': {'rating': 3.9, 'reviews': 99, 'profile_views': 5, 'booking_clicks': 17, 'checked': '2026-11-03'}}
    page, _ = _page06(hotel, _api_block(hotel, api), manual)
    by = {c['label']: c for c in page['components'][0]['cards']}
    assert by['Google rating']['value'] == '4.4 ★'                    # API wins
    assert by['booking clicks from the profile (read in Chrome)']['value'] == '17'
    assert 'people viewed the Business Profile' not in by             # the Chrome-only label isn't used
    note = page['components'][-1]['note'] if 'note' in page['components'][-1] else \
        next(c['note'] for c in page['components'] if 'note' in c)
    assert 'Booking clicks read in Chrome on 3 Nov 2026' in note


def test_page06_api_without_reviews_uses_the_chrome_rating(hotel, api):
    block = _api_block(hotel, api)
    block.pop('reviews')
    page, _ = _page06(hotel, block, {'gbp': {'rating': 4.1, 'reviews': 210, 'checked': '2026-11-03'}})
    by = {c['label']: c for c in page['components'][0]['cards']}
    assert by['Google rating']['value'] == '4.1 ★' and by['Google rating']['change'] == '210 Google reviews'
    grid = next(c['grid2'] for c in page['components'] if 'grid2' in c)
    assert grid[1]['text'] == 'Reviews not available this month.'


def test_page06_chrome_fallback_unchanged(hotel):
    manual = {'gbp': {'rating': 4.6, 'reviews': 812, 'profile_views': 5400, 'calls': 41, 'booking_clicks': 9,
                      'checked': '2026-11-03', 'period': 'Oct 2026'}}
    page, _ = _page06(hotel, {'status': 'not available: no Business Profile linked to this hotel (gbp_link)'}, manual)
    labels = [c['label'] for c in page['components'][0]['cards']]
    assert labels == ['Google rating', 'people viewed the Business Profile', 'calls from the profile',
                      'booking clicks from the profile']
    assert page['components'][1]['note'] == 'Google Business Profile, Oct 2026; read in Chrome on 3 Nov 2026.'


def test_page06_nothing_checked(hotel):
    page, r = _page06(hotel, {'status': 'not available: no Business Profile linked to this hotel (gbp_link)'})
    assert 'Business Profile not checked' in page['_missing']
    assert 'Business Profile API' in page['components'][0]['text']


# ---------------------------------------------------------------- monitor

LOC = {'name': 'locations/42', 'title': 'Example Park Hotel', 'websiteUri': 'https://example-hotels.com/',
       'phoneNumbers': {'primaryPhone': '+971 4 000 0000'},
       'categories': {'primaryCategory': {'displayName': 'Hotel'}, 'additionalCategories': [{'displayName': 'Spa'}]},
       'storefrontAddress': {'addressLines': ['1 Example St'], 'locality': 'Dubai', 'regionCode': 'AE'},
       'regularHours': {'periods': [{'openDay': 'MONDAY', 'openTime': {}, 'closeDay': 'MONDAY',
                                     'closeTime': {'hours': 24}}]},
       'metadata': {}}


def _state(loc=None, gu=None, reviews=None, today=date(2026, 11, 11)):
    return monitor.gbp_state(loc or LOC, gu or {}, reviews if reviews is not None else {'reviews': []}, today)


def test_gbp_state_fields_and_google_updated():
    loc = {**LOC, 'metadata': {'hasGoogleUpdated': True, 'hasPendingEdits': True}}
    gu = {'location': {**LOC, 'websiteUri': 'https://booking.example.com/'},
          'diffMask': 'websiteUri,regularHours.periods', 'pendingMask': 'phoneNumbers'}
    s = _state(loc, gu, {'average_rating': 4.4, 'total': 6, 'reviews': REVIEWS['reviews']})
    assert s['fields']['website'] == 'https://example-hotels.com/'
    assert s['fields']['hours'] == 'MON 00:00-24:00' and s['fields']['categories'] == 'Hotel | Spa'
    assert s['google_updated'] == {'website': 'https://booking.example.com/', 'hours': 'MON 00:00-24:00'}
    assert s['pending_edits'] is True and s['pending_fields'] == ['phone']
    assert s['unanswered_old'] == ['r5']                        # 3 stars, 20 Oct, no reply
    assert 'reviewer' not in json.dumps(s)


SINCE = '2026-11-10T07:00:00'


def test_first_run_is_a_baseline():
    alerts, changes = monitor.compare(None, {'gbp': {'park': _state()}}, gbp_changes=[])
    assert alerts == [] and changes[0].startswith('First run')
    # an older site snapshot without Business Profile data: the profile's first check is a baseline too
    gu = {'location': {**LOC, 'title': 'Other'}, 'diffMask': 'title'}
    new = {'gbp': {'park': _state({**LOC, 'metadata': {'hasGoogleUpdated': True}}, gu)}, 'home': {'status': 200}}
    alerts, changes = monitor.compare({'taken': SINCE, 'home': {'status': 200}}, new, gbp_changes=[])
    assert alerts == []
    assert any('baseline saved' in c and 'business name' in c for c in changes)


def test_google_updated_field_alerts_once_with_severity():
    old = {'park': _state()}
    gu = {'location': {**LOC, 'websiteUri': 'https://ota.example/', 'categories': {
        'primaryCategory': {'displayName': 'Resort'}}}, 'diffMask': 'websiteUri,categories'}
    new = {'park': _state({**LOC, 'metadata': {'hasGoogleUpdated': True}}, gu)}
    alerts, _ = monitor.compare_gbp(old, new, [], SINCE)
    assert any(a.startswith('[High]') and 'Google changed the website link to "https://ota.example/"' in a
               for a in alerts)
    assert any(a.startswith('[Medium]') and 'Google changed the categories' in a for a in alerts)
    again, _ = monitor.compare_gbp(new, new, [], SINCE)             # still waiting: no repeat alert
    assert again == []


def test_external_edit_vs_our_logged_change():
    old = {'park': _state()}
    new = {'park': _state({**LOC, 'phoneNumbers': {'primaryPhone': '+971 4 111 1111'}})}
    alerts, _ = monitor.compare_gbp(old, new, [], SINCE)
    assert alerts == ['[High] Business Profile (Example Park Hotel): phone changed outside our changes (not in the '
                      'gbp_apply log): "+971 4 000 0000" → "+971 4 111 1111".']
    log = [{'when': '2026-11-10T09:00:00+00:00', 'id': 'gbp-change-1', 'location': 'locations/42', 'status': 'applied',
            'changes': [{'what': 'Phone', 'before': '+971 4 000 0000', 'after': '+971 4 111 1111'}]}]
    alerts, changes = monitor.compare_gbp(old, new, log, SINCE)
    assert alerts == [] and any('changed by our change gbp-change-1' in c for c in changes)
    stale = [{**log[0], 'when': '2026-10-01T09:00:00+00:00'}]       # logged before the last run: not this edit
    assert monitor.compare_gbp(old, new, stale, SINCE)[0]
    other = [{**log[0], 'location': 'locations/7'}]                 # another profile's change
    assert monitor.compare_gbp(old, new, other, SINCE)[0]
    addr = {'park': _state({**LOC, 'storefrontAddress': {'addressLines': ['2 New St'], 'locality': 'Dubai'}})}
    assert monitor.compare_gbp(old, addr, [], SINCE)[0][0].startswith('[Medium]')


def test_pending_edits_not_sent_by_us():
    old = {'park': _state()}
    loc = {**LOC, 'metadata': {'hasPendingEdits': True}}
    new = {'park': _state(loc, {'pendingMask': 'websiteUri'})}
    alerts, _ = monitor.compare_gbp(old, new, [], SINCE)
    assert alerts and alerts[0].startswith('[Medium]') and 'not sent by us' in alerts[0]
    log = [{'when': '2026-11-10T09:00:00+00:00', 'id': 'c2', 'location': 'locations/42', 'status': 'applied',
            'changes': [{'what': 'Website link', 'before': 'a', 'after': 'b'}]}]
    alerts, changes = monitor.compare_gbp(old, new, log, SINCE)
    assert alerts == [] and any('edits waiting for Google review' in c for c in changes)


def test_new_low_review_alerts():
    old = {'park': _state(reviews={'reviews': [{'review_id': 'a', 'stars': 5, 'date': '2026-11-01', 'replied': True}]})}
    revs = {'reviews': [{'review_id': 'b', 'stars': 1, 'date': '2026-11-11', 'comment': 'Dirty room', 'replied': False},
                        {'review_id': 'c', 'stars': 4, 'date': '2026-11-11', 'replied': False},
                        {'review_id': 'old', 'stars': 2, 'date': '2025-03-01', 'replied': True},
                        {'review_id': 'a', 'stars': 5, 'date': '2026-11-01', 'replied': True}]}
    alerts, _ = monitor.compare_gbp(old, {'park': _state(reviews=revs)}, [], SINCE)
    assert alerts == ['[High] Business Profile (Example Park Hotel): new 1-star review (2026-11-11): "Dirty room". '
                      'Reply today.']


def test_unanswered_reviews_age_into_a_medium_alert():
    revs = {'reviews': [{'review_id': 'x', 'stars': 4, 'date': '2026-11-03', 'replied': False}]}
    old = {'park': _state(reviews=revs, today=date(2026, 11, 10))}       # 7 days old: not yet
    new = {'park': _state(reviews=revs, today=date(2026, 11, 11))}       # 8 days old
    assert old['park']['unanswered_old'] == [] and new['park']['unanswered_old'] == ['x']
    alerts, _ = monitor.compare_gbp(old, new, [], SINCE)
    assert alerts == ['[Medium] Business Profile (Example Park Hotel): 1 review(s) unanswered for more than 7 days: '
                      '4★ 2026-11-03.']
    alerts, changes = monitor.compare_gbp(new, new, [], SINCE)
    assert alerts == [] and any('1 older review(s) still unanswered' in c for c in changes)
    assert monitor.GBP_UNANSWERED_DAYS == 7 and monitor.GBP_LOW_STARS == 2


def test_gbp_snapshot_reads_linked_hotels(hotel, monkeypatch):
    assert monitor.gbp_snapshot(DOMAIN) == ({}, 'no hotel linked to its Business Profile (gbp_link)')
    _link(hotel)
    monkeypatch.setattr(gbp, 'configured', lambda: (True, ''))
    urls = []

    def get(url, params=None):
        urls.append(url)
        return {**LOC, 'metadata': {'hasGoogleUpdated': True}} if not url.endswith(':getGoogleUpdated') else \
            {'location': {**LOC, 'title': 'Google Name'}, 'diffMask': 'title'}
    monkeypatch.setattr(gbp, '_get', get)
    monkeypatch.setattr(gbp, '_reviews', lambda account, loc, limit=200: REVIEWS)
    snap, why = monitor.gbp_snapshot(DOMAIN)
    assert why == '' and snap['park']['google_updated'] == {'title': 'Google Name'}
    assert urls[1].endswith('locations/42:getGoogleUpdated')
    monkeypatch.setattr(gbp, '_reviews', lambda *a, **k: (_ for _ in ()).throw(gbp.GbpError('403 no access')))
    snap, _ = monitor.gbp_snapshot(DOMAIN)
    assert snap['park']['error'].startswith('GbpError: 403')


def test_run_baseline_then_alerts_and_keeps_state_on_errors(hotel, monkeypatch, tmp_path):
    monkeypatch.setattr(monitor, 'DIR', tmp_path / 'mon')
    monkeypatch.setattr(monitor, 'gbp_log', lambda path=None: [])
    snaps = iter([
        {'taken': '2026-11-10T07:00:00', 'home': {'status': 200}, 'gbp': {'park': _state()}},
        {'taken': '2026-11-11T07:00:00', 'home': {'status': 200}, 'gbp': {'park': _state(
            {**LOC, 'websiteUri': 'https://elsewhere.example/'})}},
        {'taken': '2026-11-12T07:00:00', 'home': {'status': 200}, 'gbp': {'park': {'error': 'GbpError: 503'}}},
    ])
    monkeypatch.setattr(monitor, 'snapshot', lambda site, gsc='': next(snaps))
    out = str(tmp_path / 'reports')
    first = monitor.run(DOMAIN, out_dir=out)
    assert first['baseline'] and first['alerts'] == []
    second = monitor.run(DOMAIN, out_dir=out)
    assert len(second['alerts']) == 1 and second['alerts'][0].startswith('[High]')
    assert 'website link changed outside our changes' in open(second['report'], encoding='utf-8').read()
    third = monitor.run(DOMAIN, out_dir=out)
    assert third['alerts'] == [] and any('not checked: GbpError: 503' in c for c in third['changes'])
    saved = json.loads((tmp_path / 'mon' / f'{DOMAIN}.json').read_text(encoding='utf-8'))
    assert saved['gbp']['park']['fields']['website'] == 'https://elsewhere.example/'   # last good state kept
    assert saved['gbp']['park']['last_error'] == 'GbpError: 503'
