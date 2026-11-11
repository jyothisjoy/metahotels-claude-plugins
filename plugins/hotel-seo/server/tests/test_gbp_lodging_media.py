"""Business Profile hotel amenities (Lodging API) and the photo check. All Google calls are mocked."""
import copy
import json
from datetime import date

import pytest

from hotel_seo_tools import gbp, gbp_lodging, gbp_media, gbp_write

LODGING = {
    'name': 'locations/42/lodging',
    'metadata': {'updateTime': '2026-10-01T00:00:00Z'},
    'policies': {'checkinTime': {'hours': 14}, 'checkoutTime': {'hours': 12}, 'smokeFreeProperty': True,
                 'paymentOptions': {'creditCard': True}},
    'pools': {'poolException': 'DEPENDENT_ON_SEASON'},
    'connectivity': {'wifiAvailable': True, 'freeWifi': True},
    'services': {'languagesSpoken': [{'languageCode': 'ar', 'spoken': True}]},
    'wellness': {'spa': False},
}


def _facts(tmp_path, rows):
    f = tmp_path / 'hotel-facts.json'
    f.write_text(json.dumps({'facts': rows}), encoding='utf-8')
    return str(f)


# ---------- flatten ----------

def test_flatten_values_exceptions_and_not_set():
    f = gbp_lodging.flat(LODGING)
    assert f['policies.checkinTime'] == {'value': '14:00'}
    assert f['policies.paymentOptions.creditCard'] == {'value': 'yes'}
    assert f['wellness.spa'] == {'value': 'no'}
    assert f['services.languagesSpoken[ar].spoken'] == {'value': 'yes'}
    assert gbp_lodging.state(f['pools.pool']) == 'exception: dependent on season'
    assert 'name' not in f and not any(k.startswith('metadata') for k in f)
    rows = {r['field']: r['value'] for r in gbp_lodging.table(LODGING)}
    assert rows['parking.parkingAvailable'] == 'not set'          # key field Google has nothing for
    assert rows['pools.pool'].startswith('exception')             # kept distinct from "not set"
    assert gbp_lodging.flat({'policies': {'checkinTime': {}}})['policies.checkinTime'] == {'value': '00:00'}


# ---------- comparison ----------

def test_compare_mismatch_gap_match_unconfirmed(tmp_path):
    ff = _facts(tmp_path, [
        {'kind': 'checkin_time', 'subject': 'property', 'value': '15:00', 'fact': 'Check-in time: 15:00',
         'source': 'hotel questionnaire, 1 Nov 2026'},                      # mismatch (GBP 14:00)
        {'fact': 'Check-out time: 12:00', 'source': 'hotel info sheet, 1 Nov 2026'},          # match
        {'fact': 'Parking: free', 'source': 'hotel info sheet, 1 Nov 2026'},                 # gap x2
        {'fact': 'Breakfast: included', 'source': 'Booking.com, 1 Nov 2026'},                # never confirmation
        {'fact': 'Pets: not allowed', 'source': 'hotel email, 2 Nov 2026', 'superseded': True},  # superseded
    ])
    c = gbp_lodging.compare(LODGING, ff)
    assert [(m['field'], m['gbp'], m['confirmed']) for m in c['mismatches']] == [('policies.checkinTime', '14:00', '15:00')]
    assert {g['field'] for g in c['gaps']} == {'parking.parkingAvailable', 'parking.freeParking'}
    assert [m['field'] for m in c['matches']] == ['policies.checkoutTime']
    unconf = {u['field'] for u in c['unconfirmed']}
    assert 'connectivity.freeWifi' in unconf and 'wellness.spa' in unconf
    assert 'policies.checkinTime' not in unconf
    assert c['changes'] == {'policies.checkinTime': '15:00', 'parking.parkingAvailable': True, 'parking.freeParking': True}
    assert not any('breakfast' in k.lower() or 'pets' in k for k in c['changes'])


def test_compare_hotel_beats_engine_and_same_weight_conflict_proposes_nothing(tmp_path):
    ff = _facts(tmp_path, [
        {'kind': 'checkin_time', 'value': '16:00', 'fact': 'Check-in from 16:00', 'source': 'booking engine, 1 Nov 2026'},
        {'kind': 'checkin_time', 'value': '15:00', 'fact': 'Check-in 15:00', 'source': 'hotel contact, 2 Nov 2026'},
        {'fact': 'Wi-Fi: free', 'source': 'booking engine, 1 Nov 2026'},
        {'fact': 'Wi-Fi: paid', 'source': 'booking engine, 3 Nov 2026'},
    ])
    c = gbp_lodging.compare(LODGING, ff)
    assert c['changes']['policies.checkinTime'] == '15:00'
    assert 'connectivity.freeWifi' not in c['changes']
    assert [x['field'] for x in c['conflicting_facts']] == ['connectivity.freeWifi']


@pytest.mark.parametrize('text,expect', [
    ('free', (True, True)), ('Included in all rates', (True, True)), ('extra charge (AED 60)', (True, False)),
    ('not included', (True, False)), ('No', (False, None)), ('not offered', (False, None)),
    ('no charge', (True, True)), ('free of charge', (True, True)),('free valet, paid public parking', (True, None)), ('yes', (True, None)),
    ('ask the front desk', (None, None)),
])
def test_avail_free_reading(text, expect):
    assert gbp_lodging._avail_free(text) == expect


def test_fact_times():
    assert gbp_lodging._time('from 3 pm') == '15:00'
    assert gbp_lodging._time('15.30') == '15:30'
    assert gbp_lodging._time('age 18') is None


# ---------- write: validation, updateMask, skip-if-changed ----------

@pytest.fixture
def live(monkeypatch, tmp_path):
    state = {'lodging': copy.deepcopy(LODGING), 'calls': []}
    monkeypatch.setattr(gbp, 'configured', lambda: (True, ''))
    monkeypatch.setattr(gbp_write, 'KEY_FILE', tmp_path / 'key')
    monkeypatch.setattr(gbp_write, 'LOG', tmp_path / 'log.jsonl')
    monkeypatch.setattr(gbp_write, '_find', lambda loc: ('accounts/1', {
        'name': 'locations/42', 'title': 'Royal M', 'categories': {'primaryCategory': {'displayName': 'Hotel'}}}))

    def fake_get(url, params=None):
        assert url == f'{gbp.LODGING}/locations/42/lodging' and params == {'readMask': '*'}
        return copy.deepcopy(state['lodging'])
    monkeypatch.setattr(gbp_lodging, '_get', fake_get)

    def fake_call(method, url, params=None, body=None):
        state['calls'].append((method, url, params, body))
        return body
    monkeypatch.setattr(gbp_write, '_call', fake_call)
    return state


def test_lodging_change_validation_and_mask(live, tmp_path):
    r = gbp_write.propose('locations/42', {'lodging': {'policies.checkinTime': '15:00',
                                                       'parking': {'freeParking': True},
                                                       'pools.pool': 'DEPENDENT_ON_SEASON',     # already so: left out
                                                       'wellness.spa': None}}, str(tmp_path))
    assert r['checked'], r
    c = json.loads(open(r['change_file'], encoding='utf-8').read())
    op = c['ops'][0]
    assert op['kind'] == 'lodging' and op['method'] == 'PATCH'
    assert op['url'] == 'https://mybusinesslodging.googleapis.com/v1/locations/42/lodging'
    assert op['params']['updateMask'].split(',') == [
        'policies.checkinTime', 'policies.checkinTimeException', 'parking.freeParking', 'parking.freeParkingException',
        'wellness.spa', 'wellness.spaException']
    assert op['body'] == {'name': 'locations/42/lodging', 'policies': {'checkinTime': {'hours': 15, 'minutes': 0}},
                          'parking': {'freeParking': True}}
    assert op['before'] == {'policies.checkinTime': '14:00', 'parking.freeParking': 'not set', 'wellness.spa': 'no'}
    assert op['after'] == {'policies.checkinTime': '15:00', 'parking.freeParking': 'yes', 'wellness.spa': 'not set'}
    assert '14:00' in r['preview'] and '15:00' in r['preview']
    assert live['calls'] == []                                     # propose sends nothing
    assert gbp_write._op_target_ok(op, c)


@pytest.mark.parametrize('bad', [{'policies.checkinTime': '3pm-ish'}, {'property.roomsCount': 'many'},
                                 {'parking.freeParking': 'yes'}, {'policies.petsPolicy': True}, {}])
def test_lodging_change_rejects_bad_values(live, tmp_path, bad):
    r = gbp_write.propose('locations/42', {'lodging': bad}, str(tmp_path))
    assert not r['checked']


def test_lodging_apply_sends_reads_back_and_logs(live, tmp_path, monkeypatch):
    r = gbp_write.propose('locations/42', {'lodging': {'policies.checkinTime': '15:00'}}, str(tmp_path))

    def after_patch(method, url, params=None, body=None):
        live['calls'].append((method, url, params, body))
        live['lodging']['policies']['checkinTime'] = {'hours': 15}
        return body
    monkeypatch.setattr(gbp_write, '_call', after_patch)
    a = gbp_write.apply(r['change_file'], r['change_id'])
    assert a['status'] == 'applied' and a['results'][0]['read_back'] == 'live now'
    assert live['calls'][0][2] == {'updateMask': 'policies.checkinTime,policies.checkinTimeException'}
    assert 'Check-in time' in (tmp_path / 'log.jsonl').read_text(encoding='utf-8')


def test_lodging_apply_skips_when_changed_since_proposal(live, tmp_path):
    r = gbp_write.propose('locations/42', {'lodging': {'policies.checkinTime': '15:00'}}, str(tmp_path))
    live['lodging']['policies']['checkinTime'] = {'hours': 13}     # someone edited the profile meanwhile
    a = gbp_write.apply(r['change_file'], r['change_id'])
    assert a['results'][0]['result'] == 'skipped' and live['calls'] == []


def test_lodging_host_allowed():
    assert 'mybusinesslodging.googleapis.com' in gbp_write.ALLOWED_HOSTS


def test_amenities_tool_output(monkeypatch, tmp_path):
    monkeypatch.setattr(gbp, 'configured', lambda: (True, ''))
    gu = {'lodging': {'policies': {'checkinTime': {'hours': 13}}}, 'diffMask': 'policies.checkinTime'}
    monkeypatch.setattr(gbp_lodging, '_get', lambda url, params=None: copy.deepcopy(
        gu if url.endswith(':getGoogleUpdated') else LODGING))
    ff = _facts(tmp_path, [{'fact': 'Check-in time: 15:00', 'source': 'hotel info sheet, 1 Nov 2026'}])
    r = gbp_lodging.amenities('locations/42', facts_file=ff)
    assert r['checked'] and r['has_lodging_data']
    assert r['changes'] == {'lodging': {'policies.checkinTime': '15:00'}}
    assert r['google_changed'] == [{'field': 'policies.checkinTime', 'label': 'Check-in time',
                                    'google_value': '13:00', 'profile_value': '14:00'}]
    assert 'Parking' in r['key_fields_not_set']


# ---------- photos ----------

def _m(cat, day, who_views=None, fmt='PHOTO'):
    m = {'mediaFormat': fmt, 'createTime': f'{day}T10:00:00Z'}
    if cat:
        m['locationAssociation'] = {'category': cat}
    if who_views is not None:
        m['insights'] = {'viewCount': str(who_views)}
    return m


def test_photo_counts_and_flags():
    owner = [_m('ROOMS', '2026-09-01', 100), _m('ROOMS', '2024-01-05', 50), _m('EXTERIOR', '2024-06-01', 10),
             _m('LOGO', '2025-01-01'), _m('COVER', '2026-01-01'), _m('INTERIOR', '2026-02-01', fmt='VIDEO')]
    guests = [_m(None, '2026-10-01', 5) for _ in range(14)]
    s = gbp_media.summarise(owner, guests, today=date(2026, 11, 11))
    cats = {c['category']: c for c in s['by_category']}
    assert cats['ROOMS']['owner'] == 2 and cats['ROOMS']['owner_newest'] == '2026-09-01'
    assert cats['ROOMS']['owner_oldest'] == '2024-01-05'
    assert cats['PROFILE']['owner'] == 1                         # LOGO is counted as PROFILE
    assert cats['UNCATEGORISED']['guest'] == 14 and cats['INTERIOR']['videos'] == 1
    assert s['owner_photos'] == 6 and s['guest_photos'] == 14 and s['owner_share_pct'] == 30.0
    assert s['total_views'] == 230
    flags = ' | '.join(s['flags'])
    assert 'COMMON_AREA' in flags and 'FOOD_AND_DRINK' in flags and 'no owner photo of the rooms' not in flags
    assert 'EXTERIOR is from 2024-06-01' in flags and 'ROOMS is from' not in flags
    assert f'only 20 photos' in flags and 'only 6 owner photos' in flags
    assert 'guests posted 14 photos' in flags


def test_photos_lists_owner_and_customer_media(monkeypatch):
    monkeypatch.setattr(gbp, 'configured', lambda: (True, ''))
    seen = []

    def fake_get(url, params=None):
        seen.append((url, dict(params)))
        if url.endswith('/customers'):
            return {'mediaItems': [_m(None, '2026-10-01')], 'totalMediaItemCount': 1}
        if 'pageToken' not in params:
            return {'mediaItems': [_m('ROOMS', '2026-10-01')], 'totalMediaItemCount': 2, 'nextPageToken': 't'}
        return {'mediaItems': [_m('EXTERIOR', '2026-10-02')]}
    monkeypatch.setattr(gbp_media, '_get', fake_get)
    r = gbp_media.photos('locations/42', account='accounts/1')
    assert r['checked'] and r['owner_photos'] == 2 and r['guest_photos'] == 1
    assert seen[0] == ('https://mybusiness.googleapis.com/v4/accounts/1/locations/42/media', {'pageSize': 100})
    assert seen[-1] == ('https://mybusiness.googleapis.com/v4/accounts/1/locations/42/media/customers', {'pageSize': 200})
    assert r['total_views'] is None
