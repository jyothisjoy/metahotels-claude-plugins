"""Business Profile: review replies (pending -> drafts -> lint -> changes) and the business-profile batch in execute
(plan from findings, locked fields, unlinked hotels, changes.json, undo as a reverse proposal). No Google calls."""
import json
from datetime import date
from pathlib import Path

import pytest

from hotel_seo_tools import execute, execute_report, gbp, gbp_reviews, gbp_write, group

TODAY = date(2026, 11, 11)


def _rev(rid, stars, text, created, reply=None, reply_at=None, updated=None, name='Sara Ahmed'):
    r = {'reviewId': rid, 'starRating': stars, 'comment': text, 'createTime': f'{created}T10:00:00Z',
         'updateTime': f'{updated or created}T10:00:00Z', 'reviewer': {'displayName': name}}
    if reply:
        r['reviewReply'] = {'comment': reply, 'updateTime': f'{reply_at or created}T12:00:00Z'}
    return r


RAW = [
    _rev('r1', 'FIVE', 'Lovely pool and very helpful staff at reception.', '2026-11-08'),
    _rev('r2', 'FOUR', 'Good stay.', '2026-11-01', reply='Thank you!', reply_at='2026-11-02'),
    _rev('r3', 'TWO', 'Room was noisy.', '2026-10-01', reply='Sorry to hear.', reply_at='2026-10-02',
         updated='2026-11-05'),
    _rev('r4', 'ONE', 'الغرفة كانت متسخة والخدمة بطيئة', '2026-06-01', name='Omar K'),
    _rev('r5', 'FIVE', '(Translated by Google) Great breakfast\n\n(Original)\nПрекрасный завтрак', '2026-11-09',
         name='A Google User'),
]


# ---------------------------------------------------------------- review replies

def test_pending_filter_and_fields():
    rows = gbp_reviews.select_pending(RAW, today=TODAY)
    assert [r['review_id'] for r in rows] == ['r5', 'r1', 'r3', 'r4']        # newest first; r2 is answered
    by = {r['review_id']: r for r in rows}
    assert by['r3']['reason'].startswith('the guest edited') and by['r3']['existing_reply'] == 'Sorry to hear.'
    assert by['r1']['first_name'] == 'Sara' and by['r1']['stars'] == 5 and by['r1']['language'] == 'en'
    assert by['r4']['language'] == 'ar' and by['r4']['check_with_user_first'] and by['r4']['first_name'] == 'Omar'
    assert by['r5']['first_name'] == '' and by['r5']['language'] == 'other'
    assert by['r5']['comment'] == 'Прекрасный завтрак' and by['r5']['comment_translated'] == 'Great breakfast'
    recent = gbp_reviews.select_pending(RAW, since_days=30, today=TODAY)
    assert [r['review_id'] for r in recent] == ['r5', 'r1', 'r3']           # r4 is from June


CONTACT = {'email': ['reservations@example-hotel.com'], 'phone': ['+971 4 123 4567']}


def _lint(reply, rid='r1', stars=5, lang='en', name='Sara Ahmed', first='Sara'):
    review = {'review_id': rid, 'stars': stars, 'language': lang, 'reviewer': name, 'first_name': first}
    return gbp_reviews.lint_reply(reply, review, 'Example Hotel Apartments', 'Dubai', CONTACT)


def test_lint_good_english_reply_passes():
    r = _lint('Thank you, Sara. We are glad the pool and our reception team made your stay easy. We hope to see '
              'you again.')
    assert r['problems'] == []


def test_lint_blocks_price_offer_length_personal_data_and_missing():
    assert any('price' in p for p in _lint('Thank you, Sara. Rooms start from AED 300 next time.')['problems'])
    assert any('code' in p for p in _lint('Thank you, Sara. Use code WELCOME10 when you book again.')['problems'])
    long = 'Thank you, Sara. ' + 'We enjoyed having you with us at the pool. ' * 20
    assert any('characters' in p for p in _lint(long)['problems'])
    p = _lint('Thank you, Sara Ahmed. We hope room 1204 was comfortable.')['problems']
    assert any('surname' in x for x in p) and any('1204' in x for x in p)
    p = _lint('Thank you, Sara. Your booking number 88231 is noted.')['problems']
    assert any('booking' in x for x in p)
    assert any('no reply' in x for x in _lint('   ')['problems'])
    assert any('link' in x for x in _lint('Thank you, Sara. See www.example-hotel.com for more.')['problems'])
    assert any('argues' in x for x in _lint("Thank you, Sara. That is not true, the pool was open.")['problems'])


def test_lint_complaint_needs_apology_and_confirmed_contact():
    p = _lint('Thank you for the feedback about the noise.', rid='r3', stars=2)['problems']
    assert any('apology' in x for x in p) and any('offline contact' in x for x in p)
    p = _lint('We are sorry the room was noisy. Please write to us at someone@gmail.com so we can look into it.',
              rid='r3', stars=2)['problems']
    assert any('not a confirmed hotel contact' in x for x in p)
    ok = _lint('We are sorry the room was noisy, Sara. Please write to reservations@example-hotel.com so our duty '
               'manager can look into it.', rid='r3', stars=2)
    assert ok['problems'] == []


def test_lint_arabic_review_needs_native_arabic_reply():
    arabic = ('نعتذر عن تجربتك، ونأسف لأن الغرفة لم تكن نظيفة. نرجو التواصل معنا على reservations@example-hotel.com '
              'لنتابع الأمر مباشرة.')
    assert _lint(arabic, rid='r4', stars=1, lang='ar', name='Omar K', first='Omar')['problems'] == []
    p = _lint('We are sorry. Please write to reservations@example-hotel.com.', rid='r4', stars=1, lang='ar',
              name='Omar K', first='Omar')['problems']
    assert any('Arabic' in x for x in p)


@pytest.fixture
def hotel(tmp_path, monkeypatch):
    monkeypatch.setenv('HOTEL_SEO_HOME', str(tmp_path))
    group.save('example-hotels.com', {'name': 'Example', 'site': 'https://example-hotels.com/'},
               [{'slug': 'ex', 'name': 'Example Hotel Apartments', 'paths': ['/'], 'city': 'Dubai'}])
    d = tmp_path / 'example-hotels.com'
    (d / 'hotel-facts.json').write_text(json.dumps({'facts': [
        {'fact': 'Reservations email: reservations@example-hotel.com', 'source': 'hotel contact, 1 Nov 2026'},
        {'fact': 'Phone: +971 4 123 4567', 'source': 'hotel contact, 1 Nov 2026'},
        {'fact': 'Email: old@example-hotel.com', 'source': 'Booking.com, 1 Oct 2026'}]}), encoding='utf-8')
    return d


def test_pending_writes_drafts_and_check_returns_changes(hotel, monkeypatch):
    monkeypatch.setattr(gbp, 'configured', lambda: (True, ''))
    monkeypatch.setattr(gbp, 'hotel_location', lambda g, s: {'location': 'locations/1', 'account': 'accounts/9'})
    monkeypatch.setattr(gbp_reviews, '_fetch', lambda account, loc, limit=200: RAW[:2])
    r = gbp_reviews.pending('example-hotels.com', 'ex')
    assert r['checked'] and r['pending'] == 1 and r['contacts']['email'] == ['reservations@example-hotel.com']
    f = Path(r['drafts_file'])
    assert f.parent == hotel / 'gbp' and f.with_suffix('.md').exists()
    doc = json.loads(f.read_text(encoding='utf-8'))
    assert doc['location'] == 'locations/1' and doc['max_chars'] == gbp_reviews.REPLY_MAX_CHARS
    chk = gbp_reviews.check_drafts(str(f))
    assert not chk['ready'] and not chk['review_sheet'] and any('no reply' in p for p in chk['problems'])
    reply = 'Thank you, Sara. We are glad the pool and the reception team looked after you.'
    doc['replies'][0]['reply'] = reply
    f.write_text(json.dumps(doc, ensure_ascii=False), encoding='utf-8')
    chk = gbp_reviews.check_drafts(str(f))
    assert chk['ready'] and chk['location'] == 'locations/1' and 'changes' not in chk   # posted only from the sheet
    x = Path(chk['review_sheet'])
    assert x.exists() and x.parent.parent == hotel / 'Reports' and x.name.endswith(').xlsx')
    assert 'Review Replies' in x.name and gbp_reviews.latest_sheet(hotel) == x
    got = gbp_reviews.read_sheet(x)
    assert got['replies'] == [{'review_id': 'r1', 'reply': reply}] and not got['problems']
    assert got['location'] == 'locations/1'

    # the hotel edits the final reply: the edited text is what is proposed, linted again
    from openpyxl import load_workbook
    wb = load_workbook(x)
    ws = wb['Replies']
    head = [c.value for c in ws[1]]
    ws.cell(row=2, column=head.index('Final reply (edit here)') + 1, value='Use code SAVE10 for 10% off next time!')
    wb.save(x)
    bad = gbp_reviews.import_sheet(x)
    assert bad['problems'] and 'change_id' not in bad
    ws.cell(row=2, column=head.index('Final reply (edit here)') + 1, value=reply + ' See you again soon.')
    wb.save(x)
    calls = []
    monkeypatch.setattr(gbp_write, 'propose', _fake_propose(calls))
    ok = gbp_reviews.import_sheet(x)
    assert ok['change_id'] and calls[0][1] == {'review_replies': [{'review_id': 'r1',
                                                                  'reply': reply + ' See you again soon.'}]}
    assert load_workbook(x)['Replies'].cell(row=2, column=head.index('Status') + 1).value.startswith('Proposed')
    assert gbp_reviews.read_sheet(x)['replies'] == []                 # proposed rows are not proposed twice


def test_contacts_only_from_confirmed_facts(hotel):
    c = gbp_reviews.contacts(hotel / 'hotel-facts.json')
    assert c['email'] == ['reservations@example-hotel.com'] and c['phone'] == ['+971 4 123 4567']


# ---------------------------------------------------------------- execute: business-profile batch

class FakeSite:
    def __init__(self, site):
        self.site, self.tools, self.types = site, set(), {}


def _fake_propose(calls):
    def propose(location, changes, out_dir='', allow_risky=False):
        calls.append((location, changes))
        cid = f'{len(calls):08x}'
        (key, val), = changes.items() if len(changes) == 1 else [('multi', changes)]
        op = {'kind': 'attributes' if key == 'attributes' else 'listing', 'rows': [[key, f'old {key}', val]],
              'before': {'websiteUri': 'http://old.example'}}
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        f = out / f'gbp-change-20261111-{cid}.json'
        f.write_text(json.dumps({'id': cid, 'location': location, 'expires': '2026-11-12T10:00:00+00:00',
                                 'warnings': [], 'ops': [op]}), encoding='utf-8')
        return {'checked': True, 'change_id': cid, 'change_file': str(f), 'preview': f'change {cid}'}
    return propose


@pytest.fixture
def audit(hotel, monkeypatch):
    run = hotel / 'audit-2026-11-10'
    run.mkdir()
    rep = {'title': 'Audit Report', 'hotel': 'Example', 'sections': [
        {'number': 1, 'title': 'Business Profile has no description', 'severity': 'Medium', 'category': 'Local',
         'owner': 'seo', 'finding_id': 'local-gbp-description', 'blocks': [{'p': '**Fix:** Add the description.'}],
         'checks': [], 'actions': [
             {'type': 'gbp', 'field': 'description', 'value': 'Serviced apartments in Al Barsha with a rooftop pool.'},
             {'type': 'gbp', 'field': 'primary_category', 'value': 'Resort hotel'},
             {'type': 'gbp', 'field': 'website', 'value': 'https://example-hotels.com/'}]},
        {'number': 2, 'title': 'Hours', 'severity': 'Low', 'category': 'Maps', 'owner': 'seo',
         'finding_id': 'maps-gbp-hours', 'blocks': [{'p': '**Fix:** Open 24 hours.'}], 'checks': [], 'actions': [
             {'type': 'gbp', 'field': 'regular_hours', 'value': [{'day': 'MONDAY', 'open': '00:00', 'close': '24:00'}]},
             {'type': 'gbp', 'field': 'description', 'value': 'A second description.'}]}]}
    (run / 'audit-report.json').write_text(json.dumps(rep), encoding='utf-8')
    monkeypatch.setattr(execute, 'Site', FakeSite)
    monkeypatch.setattr(gbp, 'configured', lambda: (True, ''))
    calls = []
    monkeypatch.setattr(gbp_write, 'propose', _fake_propose(calls))
    return calls


def test_plan_builds_business_profile_batch_and_skips_locked(audit, monkeypatch):
    monkeypatch.setattr(gbp, 'hotel_location', lambda g, s: {'location': 'locations/1'})
    r = execute.plan('example-hotels.com', 'ex')
    pl = json.loads(Path(r['plan_file']).read_text(encoding='utf-8'))
    items = pl['batches'][execute.GBP_BATCH]
    assert [i['gbp_key'] for i in items] == ['website', 'regular_hours']      # no description on hotel profiles
    web = next(i for i in items if i['gbp_key'] == 'website')
    assert web['gbp_value'] == 'https://example-hotels.com/?' + execute.GBP_UTM
    assert all(i['change_id'] and Path(i['change_file']).exists() and i['location'] == 'locations/1' for i in items)
    assert all('description' not in c[1] for c in audit)
    assert sum(execute.GBP_NO_DESCRIPTION in s['reason'] for s in pl['skipped']) == 2
    reasons = {(s['finding'], s['reason'].split(' ')[0]) for s in pl['skipped']}
    assert any('locked' in s['reason'] for s in pl['skipped'])                       # primary category
    assert ('local-gbp-description', 'Business') in reasons
    assert all('primary_category' not in c[1] for c in audit)
    assert r['table'][execute.GBP_BATCH][0][-1].startswith('change ')


def test_plan_unlinked_hotel_skips_batch_with_message(audit, monkeypatch):
    monkeypatch.setattr(gbp, 'hotel_location', lambda g, s: {})
    r = execute.plan('example-hotels.com', 'ex')
    assert execute.GBP_BATCH not in r['batches'] and not audit
    assert r['business_profile']['status'] == 'skipped' and 'gbp_link' in r['business_profile']['reason']
    assert any('gbp_link' in s['reason'] for s in r['skipped_reasons'])


def test_plan_derives_website_link_from_gbp_report(hotel, monkeypatch):
    run = hotel / 'audit-2026-11-10'
    run.mkdir()
    (run / 'audit-report.json').write_text(json.dumps({'sections': []}), encoding='utf-8')
    (hotel / 'gbp').mkdir()
    (hotel / 'gbp' / 'gbp-2026-11-09.json').write_text(json.dumps({'generated': '2026-11-09', 'vs_website': {
        'website': {'website_uri': 'http://example-hotels.com', 'status': 200, 'redirects': 1,
                    'final_url': 'https://example-hotels.com/', 'utm': False,
                    'problems': ['website link redirects 1x', 'no UTM tags']}}}), encoding='utf-8')
    monkeypatch.setattr(execute, 'Site', FakeSite)
    monkeypatch.setattr(gbp, 'configured', lambda: (True, ''))
    monkeypatch.setattr(gbp, 'hotel_location', lambda g, s: {'location': 'locations/1'})
    calls = []
    monkeypatch.setattr(gbp_write, 'propose', _fake_propose(calls))
    r = execute.plan('example-hotels.com', 'ex')
    assert calls == [('locations/1', {'website': 'https://example-hotels.com/?' + execute.GBP_UTM})]
    assert r['batches'] == {execute.GBP_BATCH: 1}


def test_run_batch_logs_changes_and_undo_proposes_reverse(audit, monkeypatch):
    monkeypatch.setattr(gbp, 'hotel_location', lambda g, s: {'location': 'locations/1'})
    r = execute.plan('example-hotels.com', 'ex')
    with pytest.raises(PermissionError):
        execute.run_batch(r['plan_file'], execute.GBP_BATCH)              # never without the user's yes

    def apply(change_file, confirm):
        c = json.loads(Path(change_file).read_text(encoding='utf-8'))
        assert confirm == c['id']
        c['results'] = [{'op': 'listing', 'what': 'x', 'result': 'sent', 'read_back': 'live now'}]
        Path(change_file).write_text(json.dumps(c), encoding='utf-8')
        return {'checked': True, 'change_id': c['id'], 'status': 'applied', 'results': c['results']}
    monkeypatch.setattr(gbp_write, 'apply', apply)
    res = execute.run_batch(r['plan_file'], execute.GBP_BATCH, approved=True)
    assert res['done'] == 2 and res['failed'] is None
    ed = Path(r['plan_file']).parent
    changes = json.loads((ed / 'changes.json').read_text(encoding='utf-8'))
    assert len(changes) == 2
    for c in changes:
        assert {'id', 'finding', 'page', 'field', 'old', 'new', 'at'} <= set(c)
        assert c['page'] == '' and c['via'] == 'business_profile' and c['field'].startswith('Business Profile: ')
        assert 'description' not in c['field']               # the monthly report would call it a meta description
    before = json.loads((ed / 'before.json').read_text(encoding='utf-8'))
    assert {b['undo'] for b in before.values()} == {'gbp-reverse'}
    pl = json.loads(Path(r['plan_file']).read_text(encoding='utf-8'))
    assert pl['recheck']['local-gbp-description']['status'] == 'Done'

    rep = execute_report.build('example-hotels.com', 'ex')
    ex_doc = json.loads(Path(rep['execute_report']).read_text(encoding='utf-8'))
    assert any(s['title'].startswith('Google Business Profile: 2') for s in ex_doc['sections'])
    ag = json.loads(Path(rep['agency_fix_list']).read_text(encoding='utf-8'))
    assert not any('Business Profile' in s.get('title', '') or s.get('title') == 'Hours' for s in ag['sections'])

    audit.clear()
    u = execute.undo(r['plan_file'])
    assert u['restored'] == 0 and len(u['business_profile']) == 2 and 'NOT undone' in u['next']
    assert all(c == ('locations/1', {'website': 'http://old.example'}) for c in audit)


def test_reverse_changes_from_logged_before_values(tmp_path):
    f = tmp_path / 'gbp-change-20261111-abcdef12.json'
    f.write_text(json.dumps({'id': 'abcdef12', 'location': 'locations/1', 'ops': [
        {'kind': 'listing', 'before': {
            'websiteUri': 'https://example-hotels.com/',
            'profile': {'description': 'Old text.'},
            'regularHours': {'periods': [{'openDay': 'MONDAY', 'openTime': {}, 'closeDay': 'MONDAY',
                                          'closeTime': {'hours': 24}}]},
            'specialHours': {'specialHourPeriods': [{'startDate': {'year': 2026, 'month': 12, 'day': 31},
                                                      'closed': True}]},
            'categories': {'primaryCategory': {'name': 'categories/gcid:hotel'},
                           'additionalCategories': [{'name': 'categories/gcid:spa', 'displayName': 'Spa'}]}}},
        {'kind': 'attributes', 'before': {'has_pool': {'name': 'attributes/has_pool', 'values': [True]},
                                          'has_spa': None,
                                          'url_reservations': {'uriValues': [{'uri': 'https://b.example/'}]}}},
        {'kind': 'listing', 'before': {'phoneNumbers': {'primaryPhone': '+97141234567'}}}],
        'results': [{'result': 'sent'}, {'result': 'sent'}, {'result': 'skipped'}]}), encoding='utf-8')
    loc, rev, notes = execute.reverse_changes(str(f))
    assert loc == 'locations/1' and notes == []
    assert rev == {'website': 'https://example-hotels.com/', 'description': 'Old text.',
                   'regular_hours': [{'day': 'MONDAY', 'open': '00:00', 'close': '24:00', 'close_day': 'MONDAY'}],
                   'special_hours': [{'date': '2026-12-31', 'closed': True}],
                   'additional_categories': ['categories/gcid:spa'],
                   'attributes': {'has_pool': True, 'has_spa': None, 'url_reservations': 'https://b.example/'}}
    # the skipped phone op is not reversed


def test_utm_and_locked_fields():
    assert execute.gbp_url_with_utm('https://x.com/a?lang=en#top') == f'https://x.com/a?lang=en&{execute.GBP_UTM}#top'
    assert execute.gbp_url_with_utm('https://x.com/?utm_source=gbp') == 'https://x.com/?utm_source=gbp'
    for f in ('title', 'address', 'primary_category'):
        with pytest.raises(ValueError, match='locked'):
            execute._gbp_change({'type': 'gbp', 'field': f, 'value': 'x'})
    with pytest.raises(ValueError, match='own path'):
        execute._gbp_change({'type': 'gbp', 'field': 'posts', 'value': [{}]})
