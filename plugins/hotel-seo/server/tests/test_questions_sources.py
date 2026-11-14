"""Questions for the Hotel: the four added sources (Business Profile amenities, name / address / phone, wrong facts
in AI answers, area claims in new copy), stable ids, imports and corrections. No live calls."""
import copy
import json

import pytest
from openpyxl import load_workbook

from hotel_seo_tools import consistency, gbp, gbp_lodging, group, questions

SITE = 'https://example-hotels.com/'
PAGE = 'https://example-hotels.com/contact/'
OTHER = 'https://example-hotels.com/about/'
LODGING = {'name': 'locations/42/lodging',
           'policies': {'checkinTime': {'hours': 14}},
           'pools': {'pool': True},
           'wellness': {'spa': False},
           'connectivity': {'freeWifi': True}}


def _w(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')


@pytest.fixture
def hotel(tmp_path, monkeypatch):
    monkeypatch.setenv('HOTEL_SEO_HOME', str(tmp_path))
    group.save('example-hotels.com', {'name': 'Example', 'site': SITE},
               [{'slug': 'ex', 'name': 'Example Hotel Apartments', 'paths': ['/'], 'city': 'Dubai'}])
    d = tmp_path / 'example-hotels.com'
    run = d / 'audit-2026-10-25'
    _w(run / 'audit-report.json', {'title': 'Audit Report', 'sections': [
        {'number': 1, 'title': 'Loyalty tiers', 'finding_id': 'f-loyalty', 'owner': 'seo',
         'blocks': [{'p': '**Fix:** Gold from 15 nights [CONFIRM].'}], 'actions': [], 'checks': []}]})
    _w(d / 'hotel-facts.json', {'facts': [
        {'kind': 'checkin_time', 'subject': 'property', 'value': '15:00', 'fact': 'Check-in from 15:00',
         'source': 'Booking.com, 1 Nov 2026'},
        {'kind': 'phone', 'subject': 'property', 'value': '+971 4 111 2222', 'fact': 'Phone: +971 4 111 2222',
         'source': 'Booking.com, 1 Nov 2026'},
        {'kind': 'name', 'subject': 'property', 'value': 'Example Hotel Apartments',
         'fact': 'Property name: Example Hotel Apartments', 'source': 'Booking.com, 1 Nov 2026'},
        {'kind': 'nearby', 'subject': 'property', 'value': [{'place': 'Dubai Mall', 'distance': '12 km'}],
         'fact': 'Nearby on Booking.com: Dubai Mall 12 km', 'source': 'Booking.com, 1 Nov 2026'},
        {'kind': 'parking', 'subject': 'property', 'value': 'paid', 'fact': 'Parking: paid',
         'source': 'booking engine, 1 Nov 2026'},
        {'fact': 'Check-out time: 12:00', 'source': 'hotel info sheet, 20 Oct 2026'},
    ]})
    _w(d / 'crawl-2026-10-25' / 'site_text.json', {
        PAGE: 'Contact us. Call +971 4 111 2222 or write to us. Example Hotel Apts, Al Barsha.',
        OTHER: 'About Example Hotel Apts. Our restaurant phone is +971 4 555 0000.'})
    _w(run / 'code' / 'consistency.json', {'nap': {
        'phone': {'+97141112222': [PAGE]}, 'name': {'Example Hotel Apts': [PAGE, OTHER]},
        'address': {'Street 5, Al Barsha': [PAGE]}}})
    _w(d / 'gbp' / 'gbp-2026-11-01.json', {'listing': {
        'title': 'Example Hotel Apartments', 'address': 'Street 5, Al Barsha, Dubai', 'phone': '+971 4 999 8888',
        'website': 'https://example-hotels.com/?utm_source=gbp'}})
    _w(d / 'monthly-2026-10' / 'manual.json', {'ai_panel': {'checked': '2026-10-28', 'results': [
        {'id': 'p1', 'prompt': 'hotels near dubai mall', 'engine': 'chatgpt', 'named': True, 'cited': False,
         'description_correct': False, 'errors': ['Says check-in is from 12:00', 'Says the hotel opened in 2015']},
        {'id': 'p1', 'prompt': 'hotels near dubai mall', 'engine': 'perplexity', 'named': True, 'cited': True,
         'description_correct': False, 'errors': ['Says the hotel opened in 2015', 'Says check-out is at 11:00']},
    ]}})
    return d


def _items(r):
    return json.loads(open(r['file'], encoding='utf-8').read())['items']


def _by(items, sheet, **kw):
    return [i for i in items if i['sheet'] == sheet and all(i.get(k) == v for k, v in kw.items())]


def _fill(xlsx, answers, out):
    """answers: [(sheet, id, header, value)]."""
    wb = load_workbook(xlsx)
    for sheet, qid, header, value in answers:
        ws = wb[sheet]
        col = [c.value for c in ws[1]].index(header) + 1
        row = next(r for r in range(2, ws.max_row + 1) if ws.cell(row=r, column=1).value == qid)
        ws.cell(row=row, column=col, value=value)
    wb.save(out)
    return str(out)


def _amenities(d, lodging=LODGING, day='2026-11-02'):
    _w(d / 'gbp' / f'amenities-{day}.json', {'checked': True, 'lodging': lodging, 'saved': day})


# ---------------------------------------------------------------- Business Profile

def test_business_profile_rows_and_merge_into_facts(hotel):
    first = questions.build('example-hotels.com', 'ex')
    f_checkin = _by(_items(first), 'Facts', kind='checkin_time')[0]['id']
    _amenities(hotel)
    r = questions.build('example-hotels.com', 'ex')
    items = _items(r)
    b = {i['field']: i for i in _by(items, 'Business Profile')}
    # unconfirmed values Google shows -> rows; what the booking engine shows is never asked (it is proposed)
    assert {'pools.pool', 'wellness.spa'} <= set(b)
    assert 'parking.parkingAvailable' not in b and 'parking.freeParking' not in b
    assert b['wellness.spa']['gbp'] == 'no' and b['wellness.spa']['id'].startswith('B')
    assert b['pools.pool']['refs'][0]['doc'] == 'gbp/amenities-2026-11-02.json'
    # fields the Facts sheet already asks: merged into that row, same id, no Business Profile row
    assert 'policies.checkinTime' not in b and 'connectivity.freeWifi' not in b
    f = _by(items, 'Facts', kind='checkin_time')[0]
    assert f['id'] == f_checkin and 'Google Business Profile shows: Check-in time: 14:00' in f['we_have']
    assert 'Free Wi-Fi: yes' in _by(items, 'Facts', kind='wifi')[0]['we_have']
    wb = load_workbook(r['xlsx'])
    assert 'Business Profile' in wb.sheetnames
    assert [c.value for c in wb['Business Profile'][1]][-1] == 'Correct answer'


def test_business_profile_answers_become_lodging_facts_and_changes(hotel):
    _amenities(hotel)
    r = questions.build('example-hotels.com', 'ex')
    b = {i['field']: i['id'] for i in _by(_items(r), 'Business Profile')}
    filled = _fill(r['xlsx'], [('Business Profile', b['wellness.spa'], 'Correct answer', 'Yes'),
                               ('Business Profile', b['pools.pool'], 'Correct answer', "Don't know")],
                   hotel / 'filled.xlsx')
    imp = questions.import_answers('example-hotels.com', 'ex', filled)
    assert 'business_profile' in imp
    facts = json.loads((hotel / 'hotel-facts.json').read_text(encoding='utf-8'))['facts']
    spa = [x for x in facts if x.get('kind') == 'lodging']
    assert [(x['subject'], x['value']) for x in spa] == [('wellness.spa', 'Yes')]       # "Don't know" adds nothing
    assert spa[0]['source'].startswith('hotel questionnaire')
    cmp_ = gbp_lodging.compare(LODGING, str(hotel / 'hotel-facts.json'))
    assert cmp_['changes'].get('wellness.spa') is True
    # rebuilt: the answered row keeps its id and answer; the spa is no longer "unconfirmed" so no new row
    again = _items(questions.build('example-hotels.com', 'ex'))
    spa_rows = _by(again, 'Business Profile', field='wellness.spa')
    assert len(spa_rows) <= 1 and all(x['id'] == b['wellness.spa'] for x in spa_rows)


def test_amenities_tool_saves_the_record(monkeypatch, tmp_path):
    monkeypatch.setattr(gbp, 'configured', lambda: (True, ''))
    monkeypatch.setattr(gbp_lodging, '_get', lambda url, params=None: copy.deepcopy(
        {} if 'getGoogleUpdated' in url else LODGING))
    out = gbp_lodging.amenities('locations/42', facts_file=str(tmp_path / 'none.json'), out_dir=str(tmp_path / 'gbp'))
    saved = json.loads(open(out['file'], encoding='utf-8').read())
    assert saved['lodging']['wellness'] == {'spa': False} and 'lodging' not in out
    assert any(u['field'] == 'wellness.spa' for u in saved['unconfirmed'])


def test_answer_value_reading():
    assert gbp_lodging.answer_value('policies.checkinTime', '3 pm') == '15:00'
    assert gbp_lodging.answer_value('property.roomsCount', 'We have 84 apartments') == '84'
    assert gbp_lodging.answer_value('wellness.spa', 'No') == 'no'
    assert gbp_lodging.answer_value('wellness.spa', "don't know") is None


# ---------------------------------------------------------------- name / address / phone

def test_nap_values_on_facts_rows(hotel):
    items = _items(questions.build('example-hotels.com', 'ex'))
    phone = _by(items, 'Facts', kind='phone')[0]
    assert phone['we_have'].startswith('These differ:')
    for v in ('Website: “+97141112222”', 'Google Business Profile: “+971 4 999 8888”', 'Booking.com: “+971 4 111 2222”'):
        assert v in phone['we_have']
    assert any(r['doc'] == 'gbp/gbp-2026-11-01.json' for r in phone['refs'])
    name = _by(items, 'Facts', kind='name')                       # added: the site says "Example Hotel Apts"
    assert len(name) == 1 and name[0]['differs']
    assert not _by(items, 'Facts', kind='website')                # same host everywhere: not asked
    address = _by(items, 'Facts', kind='address')[0]
    assert not address['differs']                                 # "Street 5, Al Barsha" is part of the full one
    # one F row per field: phone appears once
    assert len(_by(items, 'Facts', kind='phone')) == 1


def test_nap_correction_only_where_the_phrase_is_on_the_page(hotel):
    r = questions.build('example-hotels.com', 'ex')
    items = _items(r)
    ids = {k: _by(items, 'Facts', kind=k)[0]['id'] for k in ('phone', 'name')}
    filled = _fill(r['xlsx'], [('Facts', ids['phone'], 'Correct answer', '+971 4 999 8888'),
                               ('Facts', ids['name'], 'Correct answer', 'Example Hotel Apartments Dubai')],
                   hotel / 'filled.xlsx')
    questions.import_answers('example-hotels.com', 'ex', filled)
    corr = questions.corrections('example-hotels.com', 'ex')
    phone = [c for c in corr if c['question'] == ids['phone']]
    assert [(c['url'], c['find'], c['replace']) for c in phone] == [(PAGE, '+971 4 111 2222', '+971 4 999 8888')]
    assert phone[0]['match_mode'] == 'phone' and phone[0]['pages'] == [PAGE]
    # the restaurant number on the other page is not the hotel's phone: left alone
    assert not any('555' in c['find'] for c in corr)
    name = [c for c in corr if c['question'] == ids['name']]
    assert {c['url'] for c in name} == {PAGE, OTHER} and all(c['find'] == 'Example Hotel Apts' for c in name)


def test_nap_no_correction_when_phrase_absent(hotel):
    _w(hotel / 'crawl-2026-10-25' / 'site_text.json', {PAGE: 'Contact us by email.'})
    r = questions.build('example-hotels.com', 'ex')
    pid = _by(_items(r), 'Facts', kind='phone')[0]['id']
    filled = _fill(r['xlsx'], [('Facts', pid, 'Correct answer', '+971 4 999 8888')], hotel / 'filled.xlsx')
    questions.import_answers('example-hotels.com', 'ex', filled)
    assert not [c for c in questions.corrections('example-hotels.com', 'ex') if c['question'] == pid]


def test_consistency_reads_nap_from_page():
    h = ('<a href="tel:+971 4 111 2222">Call</a><script type="application/ld+json">{"@context": "https://schema.org",'
         ' "@type": "Hotel", "name": "Example", "telephone": "+97141112222", "address": {"@type": "PostalAddress", '
         '"streetAddress": "Street 5", "addressLocality": "Dubai"}}</script>')
    n = consistency.nap(h)
    assert n['phone'] == {'+971 4 111 2222'} and n['name'] == {'Example'} and n['address'] == {'Street 5, Dubai'}
    probs = consistency._nap_problems({'name': {'Example': ['/a'], 'Example Hotel': ['/b']}})
    assert probs and 'name differs' in probs[0]


# ---------------------------------------------------------------- AI answers

def test_ai_errors_grouped_and_confirmed_skipped(hotel):
    items = _items(questions.build('example-hotels.com', 'ex'))
    ai = [i for i in items if i.get('type') == 'ai_error']
    assert len(ai) == 1                                        # "opened in 2015" from two engines -> one question
    q = ai[0]
    assert 'ChatGPT and Perplexity say' in q['question'] and 'opened in 2015' in q['question']
    assert '28 Oct 2026' in q['now'] and q['refs'][0]['doc'] == 'monthly-2026-10/manual.json'
    # check-in is an open Facts row: merged there, not a second question
    assert '“check-in is from 12:00”' in _by(items, 'Facts', kind='checkin_time')[0]['we_have']
    # check-out is confirmed by the hotel info sheet: a fix elsewhere, not a question
    assert not any('check-out' in json.dumps(i).lower() for i in ai)
    again = _items(questions.build('example-hotels.com', 'ex'))
    assert [i['id'] for i in again if i.get('type') == 'ai_error'] == [q['id']]


# ---------------------------------------------------------------- area claims

def _claims(hotel_dir):
    return questions.save_claims('example-hotels.com', 'ex', [
        {'claim': 'Dubai Mall is 15 minutes by car', 'kind': 'travel_time', 'place': 'Dubai Mall',
         'where': 'https://example-hotels.com/location/'},
        {'claim': 'Global Village is open from 4 pm', 'kind': 'opening_hours', 'where': 'content/winter.md'},
        {'claim': 'Expo City is 20 km away', 'kind': 'distance', 'place': 'Expo City',
         'source': 'https://maps.example/expo', 'checked': '2026-11-05'},
    ])


def test_save_claims_and_questions(hotel):
    saved = _claims(hotel)
    assert saved['claims'] == 3 and len(saved['unsourced']) == 2
    items = _items(questions.build('example-hotels.com', 'ex'))
    mall = _by(items, 'Distances', place='Dubai Mall')
    assert len(mall) == 1                                      # merged into Booking.com's Dubai Mall row
    assert 'new copy: “Dubai Mall is 15 minutes by car”' in mall[0]['site_says']
    assert mall[0]['claims'][0]['key'].startswith('claim:')
    assert not _by(items, 'Distances', place='Expo City')      # sourced: not asked
    gv = [i for i in items if i.get('type') == 'area_claim']
    assert len(gv) == 1 and "Don't know" in gv[0]['question'] and gv[0]['page'] == 'content/winter.md'


def test_dont_know_removes_the_claim(hotel):
    _claims(hotel)
    r = questions.build('example-hotels.com', 'ex')
    items = _items(r)
    gv = next(i for i in items if i.get('type') == 'area_claim')
    mall = _by(items, 'Distances', place='Dubai Mall')[0]
    filled = _fill(r['xlsx'], [('Questions', gv['id'], 'Hotel answer', "Don't know"),
                               ('Distances', mall['id'], 'Distance by road (km)', "don't know")],
                   hotel / 'filled.xlsx')
    imp = questions.import_answers('example-hotels.com', 'ex', filled)
    assert {x['claim'] for x in imp['remove_from_copy']} == {'Global Village is open from 4 pm',
                                                             'Dubai Mall is 15 minutes by car'}
    facts = json.loads((hotel / 'hotel-facts.json').read_text(encoding='utf-8'))['facts']
    assert not any(x.get('kind') in ('area_claim', 'distance') for x in facts)      # not confirmed
    claims = json.loads(next((hotel / 'copy').glob('claims-*.json')).read_text(encoding='utf-8'))['claims']
    assert all(c['status'].startswith('remove') for c in claims if not c['source'])
    again = _items(questions.build('example-hotels.com', 'ex'))
    assert [i['id'] for i in again if i.get('type') == 'area_claim'] == [gv['id']]   # kept with its answer, not re-asked
    assert not any(c for d in _by(again, 'Distances') for c in d.get('claims') or [])


def test_claim_confirmed_by_value(hotel):
    _claims(hotel)
    r = questions.build('example-hotels.com', 'ex')
    gv = next(i for i in _items(r) if i.get('type') == 'area_claim')
    filled = _fill(r['xlsx'], [('Questions', gv['id'], 'Hotel answer', 'It opens at 5 pm')], hotel / 'f.xlsx')
    imp = questions.import_answers('example-hotels.com', 'ex', filled)
    assert imp['remove_from_copy'] == []
    facts = json.loads((hotel / 'hotel-facts.json').read_text(encoding='utf-8'))['facts']
    assert any(x.get('kind') == 'area_claim' and x['value'] == 'It opens at 5 pm' for x in facts)


# ---------------------------------------------------------------- stable ids

def test_ids_stable_across_rebuilds(hotel):
    _amenities(hotel)
    _claims(hotel)
    one = {(i['sheet'], i.get('field') or i.get('kind') or i.get('place') or i.get('key')): i['id']
           for i in _items(questions.build('example-hotels.com', 'ex'))}
    # a new profile field and an extra fact that closes the Wi-Fi Facts row
    lod = copy.deepcopy(LODGING)
    lod['wellness']['sauna'] = True
    _amenities(hotel, lod, '2026-11-09')
    facts = json.loads((hotel / 'hotel-facts.json').read_text(encoding='utf-8'))
    facts['facts'].append({'kind': 'wifi', 'subject': 'property', 'value': 'free', 'fact': 'Wi-Fi: free',
                           'source': 'hotel contact, 9 Nov 2026'})
    (hotel / 'hotel-facts.json').write_text(json.dumps(facts), encoding='utf-8')
    two = {(i['sheet'], i.get('field') or i.get('kind') or i.get('place') or i.get('key')): i['id']
           for i in _items(questions.build('example-hotels.com', 'ex'))}
    for k, v in two.items():
        if k in one:
            assert one[k] == v, k
    assert ('Facts', 'wifi') not in two
    new_b = two[('Business Profile', 'wellness.sauna')]
    assert new_b not in one.values()
    # the Wi-Fi Facts id is not reused for something else
    assert one[('Facts', 'wifi')] not in [v for k, v in two.items()]
