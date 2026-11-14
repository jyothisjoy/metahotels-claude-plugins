"""Hotel questions -> answers -> execute gate -> execute reports; keyword reasons."""
import json
from pathlib import Path

import pytest
from openpyxl import load_workbook

from hotel_seo_tools import execute, execute_report, group, keyword_map, questions


def test_room_pattern_matches_how_sites_write_room_names():
    rx = questions.room_pattern('One Bedroom Apartment')
    for t in ('One Bedroom Apartment', '1-Bedroom', '1 Bedroom suite', 'one bed apartment'):
        assert rx.search(t), t
    assert not rx.search('Two Bedroom Apartment')


def test_owner_is_the_nearest_room_name_before_the_size():
    rooms = [('R1', questions.room_pattern('Studio Apartment')), ('R2', questions.room_pattern('One Bedroom'))]
    text = 'Studio Apartment 68 sqm, king bed. Other rooms: One Bedroom 70 sqm'
    assert questions._owner(text, text.index('68'), rooms) == 'R1'
    assert questions._owner(text, text.index('70'), rooms) == 'R2'


def test_answer_states():
    room = {'sheet': 'Rooms', 'answer': {'size_m2': 68, 'max_adults': 2}}
    assert execute._answer_state('R1', room, 'Studio 68 m² [CONFIRM R1]') == 'yes'
    assert execute._answer_state('R1', room, 'Studio 53 m² [CONFIRM R1]') == 'value'
    assert execute._answer_state('R1', room, 'sleeps up to 2 guests [CONFIRM R1]') == 'yes'
    assert execute._answer_state('R1', {'sheet': 'Rooms'}, 'x') == 'waiting'
    dist = {'sheet': 'Distances', 'answer': {'road_km': 3.1}}
    assert execute._answer_state('D1', dist, '3.1 km from the metro') == 'yes'
    assert execute._answer_state('D1', dist, '2.8 km from the metro') == 'value'
    q = {'sheet': 'Questions'}
    assert execute._answer_state('Q1', dict(q, answer={'answer': 'Yes'}), '') == 'yes'
    assert execute._answer_state('Q1', dict(q, answer={'answer': 'No, remove it'}), '') == 'no'
    assert execute._answer_state('Q1', dict(q, answer={'answer': 'Check-in is 15:00'}), '') == 'value'


def test_gate_strips_confirmed_markers_only():
    answers = {'Q1': {'sheet': 'Questions', 'answer': {'answer': 'yes'}},
               'Q2': {'sheet': 'Questions', 'answer': None}}
    ok, why, ids, _ = execute._hotel_gate('Check-in 14:00 [CONFIRM Q1].', answers)
    assert ok and ids == ['Q1']
    assert execute._strip_confirmed({'t': 'Check-in 14:00 [CONFIRM Q1].'}, ids) == {'t': 'Check-in 14:00.'}
    assert execute._hotel_gate('x [CONFIRM Q2]', answers)[1] == 'waiting for the hotel (Q2)'
    assert 'no question number' in execute._hotel_gate('x [CONFIRM]', answers)[1]
    hold_ok = execute._hotel_gate('{}', answers, hold_q='Q1')
    assert hold_ok[0] and hold_ok[2] == []


def test_explain_gives_plain_reasons():
    c = {'kind': 'landmark', 'head': 'dubai investment park metro station', 'distance_m': 2400, 'volume': 320,
         'keywords': ['hotel near dip metro', 'hotels close to dip metro'], 'intent': 'booking',
         'status': 'shows but low', 'gsc_position': 14.2, 'gsc_impressions': 118}
    why = keyword_map.explain(c, city='dubai', market='Dubai')
    assert why[0].startswith('Dubai Investment Park Metro Station is 2.4 km from the hotel')
    assert '320 searches a month across 2 searches' in why[1]
    assert any('position 14.2' in w for w in why)


@pytest.fixture
def site(tmp_path, monkeypatch):
    monkeypatch.setenv('HOTEL_SEO_HOME', str(tmp_path))
    group.save('example-hotels.com', {'name': 'Example', 'site': 'https://example-hotels.com/'},
               [{'slug': 'ex', 'name': 'Example Hotel Apartments', 'paths': ['/'], 'city': 'Dubai'}])
    d = tmp_path / 'example-hotels.com'
    run = d / 'audit-2026-10-25'
    run.mkdir()
    rep = {'title': 'Audit Report', 'hotel': 'Example', 'date': '25 Oct', 'sections': [
        {'number': 1, 'title': 'Room sizes', 'severity': 'High', 'category': 'Content', 'owner': 'seo',
         'finding_id': 'f-rooms', 'blocks': [{'p': '**Fix:** Studio Apartment: 68 m² [CONFIRM]. Sleeps 2.'}],
         'actions': [{'type': 'seo_fields', 'url': 'https://example-hotels.com/room/studio/',
                      'fields': {'description': 'Studio Apartment of 68 m² [CONFIRM] in Dubai.'}}], 'checks': []},
        {'number': 2, 'title': 'Loyalty tiers', 'severity': 'Medium', 'category': 'Content', 'owner': 'seo',
         'finding_id': 'f-loyalty', 'blocks': [{'p': '**Fix:** Gold from 15 nights [CONFIRM].'}], 'actions': [],
         'checks': []},
        {'number': 3, 'title': 'Robots fine', 'severity': 'Info', 'category': 'Technical', 'owner': 'seo',
         'finding_id': 'f-robots', 'blocks': [{'p': '**Fix:** No change needed.'}], 'actions': [], 'checks': []},
        {'number': 4, 'title': 'Title too long', 'severity': 'Low', 'category': 'On-Page', 'owner': 'seo',
         'finding_id': 'f-title', 'blocks': [{'p': '**Fix:** Shorten it.'}],
         'actions': [{'type': 'seo_fields', 'url': 'https://example-hotels.com/', 'fields': {'title': 'Short'}}],
         'checks': [{'type': 'title', 'url': '/', 'expected': 'Short'}]}]}
    (run / 'audit-report.json').write_text(json.dumps(rep), encoding='utf-8')
    (d / 'booking-engine').mkdir()
    (d / 'booking-engine' / 'booking_engine.json').write_text(json.dumps({'website_vs_engine': {'rooms': [
        {'room': 'Studio Apartment', 'engine_size': '68 m²', 'engine_max_occupancy': 2,
         'site_page': 'https://example-hotels.com/room/studio/', 'sizes_on_page': ['53', '68'],
         'occupancy_on_page': ['2']}]}}), encoding='utf-8')
    crawl = d / 'crawl-2026-10-25'
    crawl.mkdir()
    (crawl / 'site_text.json').write_text(json.dumps({
        'https://example-hotels.com/room/studio/': 'Studio Apartment 53 sqm with a king bed. Other rooms: '
                                                   'One Bedroom Apartment 70 sqm'}), encoding='utf-8')
    return d


def test_questions_build_import_and_corrections(site):
    r = questions.build('example-hotels.com', 'ex')
    # the engine shows the Studio's size and guests: never asked, so no Rooms sheet for the hotel
    assert r['rooms'] == 0 and r['rooms_from_engine'] == 1 and r['questions'] >= 1
    rep = json.loads((site / 'audit-2026-10-25' / 'audit-report.json').read_text(encoding='utf-8'))
    text = json.dumps(rep, ensure_ascii=False)
    assert '[CONFIRM R1]' in text and '[CONFIRM Q' in text and '[CONFIRM]' not in text
    again = questions.build('example-hotels.com', 'ex')
    assert again['questions'] == r['questions']
    wb = load_workbook(r['xlsx'])
    assert 'Rooms' not in wb.sheetnames
    wb['Questions'].cell(row=2, column=7, value='Yes')
    filled = site / 'filled.xlsx'
    wb.save(filled)
    imp = questions.import_answers('example-hotels.com', 'ex', str(filled))
    assert imp['answered'] == 1
    corr = questions.corrections('example-hotels.com', 'ex')
    assert [(c['find'], c['replace']) for c in corr] == [('53 sqm', '68 sqm')]     # not the One Bedroom's 70 sqm


def test_execute_reports_split_done_agency_and_waiting(site):
    questions.build('example-hotels.com', 'ex')
    run = site / 'audit-2026-10-25'
    rep = json.loads((run / 'audit-report.json').read_text(encoding='utf-8'))
    title_action = rep['sections'][3]['actions'][0]
    ed = site / 'execute-2026-10-25'
    ed.mkdir()
    plan = {'site': 'https://example-hotels.com', 'source_run': str(run), 'approved': [{'batch': 'seo-fields'}],
            'batches': {'seo-fields': [{'id': 'a1', 'finding': 'f-title', 'action': title_action, 'page': '/',
                                        'field': 'title'}]},
            'done': ['a1'], 'recheck': {'f-title': {'status': 'Done'}},
            'skipped': [{'finding': 'f-rooms', 'action': 'seo_fields', 'reason': 'waiting for the hotel (R1)'}]}
    (ed / 'plan.json').write_text(json.dumps(plan), encoding='utf-8')
    (ed / 'changes.json').write_text(json.dumps([{'id': 'a1', 'finding': 'f-title', 'page': '/', 'field': 'title',
                                                  'old': 'Long', 'new': 'Short'}]), encoding='utf-8')
    r = execute_report.build('example-hotels.com', 'ex')
    ex_doc = json.loads(open(r['execute_report'], encoding='utf-8').read())
    ag = json.loads(open(r['agency_fix_list'], encoding='utf-8').read())
    assert r['changes'] == 1 and 'Done' in json.dumps(ex_doc)
    titles = [s['title'] for s in ag['sections'] if s.get('number')]
    assert 'Title too long' not in titles                     # done by execute
    assert 'Robots fine' not in titles                        # no action needed
    wait = next(s for s in ag['sections'] if s['title'].startswith('Do not change yet'))
    assert {row[0] for row in wait['blocks'][1]['table']['rows']} >= {'Room sizes', 'Loyalty tiers'}


def test_rooms_always_follow_the_booking_engine(site):
    """What the engine's /search page shows is always right, whatever the hotel says."""
    r = questions.build('example-hotels.com', 'ex')
    corr = questions.corrections('example-hotels.com', 'ex')
    assert [(c['find'], c['replace'], c['source'], c['finding']) for c in corr] == [
        ('53 sqm', '68 sqm', 'booking engine', 'booking-room_size_mismatch')]
    room = next(i for i in questions.load('example-hotels.com', 'ex')['items'] if i['sheet'] == 'Rooms')
    assert execute._answer_state('R1', room, 'Studio Apartment: 68 m²') == 'yes'     # not "waiting" any more
    assert execute._answer_state('R1', room, 'Studio Apartment: 53 m²') == 'value'
    # a hotel answer that says otherwise does not move the site: the engine value is used
    data = questions.load('example-hotels.com', 'ex')
    for i in data['items']:
        if i['sheet'] == 'Rooms':
            i['answer'] = {'size_m2': 60}
    qf = sorted(site.glob('audit-*/hotel-questions.json'))[-1]
    qf.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    corr = questions.corrections('example-hotels.com', 'ex')
    assert [(c['find'], c['replace']) for c in corr] == [('53 sqm', '68 sqm')]
    room = next(i for i in questions.load('example-hotels.com', 'ex')['items'] if i['sheet'] == 'Rooms')
    assert execute._answer_state('R1', room, 'Studio Apartment: 68 m²') == 'yes'


class _NoSite:
    """execute.Site stand-in: no MCP tools, so nothing is resolved (the gate runs before any of that)."""
    def __init__(self, site):
        self.site, self.tools, self.types, self.integrations = site, set(), {}, {}
        self.single, self.hotel_paths = True, []

    def post_id(self, url):
        raise LookupError(url)


def test_execute_asks_before_running_without_the_hotel_answers(site, monkeypatch):
    monkeypatch.setattr(execute, 'Site', _NoSite)
    r = questions.build('example-hotels.com', 'ex')
    p = execute.plan('example-hotels.com', 'ex')
    assert p['needs_decision'] and 'plan_file' not in p
    assert p['questions']['answered'] == 0 and p['questions']['questions'] >= 1
    assert p['waiting_on_hotel']['findings'] >= 1 and 'ignore_unanswered=true' in p['next']
    go = execute.plan('example-hotels.com', 'ex', ignore_unanswered=True)
    pl = json.loads(Path(go['plan_file']).read_text(encoding='utf-8'))
    assert pl['questions_ignored'] and go['questions']['open'] >= 1
    # the hotel filled the sheet in place: execute imports it and plans without asking
    wb = load_workbook(r['xlsx'])
    wb['Questions'].cell(row=2, column=7, value='Yes')
    wb.save(r['xlsx'])
    again = execute.plan('example-hotels.com', 'ex')
    assert 'needs_decision' not in again and again['questions']['answered'] >= 1
