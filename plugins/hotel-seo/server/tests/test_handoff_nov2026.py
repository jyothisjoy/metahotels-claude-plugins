"""Offline tests for the Abar / Rose handoff fixes (Nov 2026) and the checks added with them.

Run: uv run --with pytest python -m pytest -q tests      (from plugins/hotel-seo/server)
"""
import json

from hotel_seo_tools import analysis, checks, consistency, execute, facts


# ---------------------------------------------------------------- one landmark, one distance

def test_distance_belongs_to_the_longest_place_before_it():
    texts = {
        'a': 'The Market Mall in Green Community 1.6 km away, and Green Community 0.9 km. Mall of the Emirates 22 km.',
        'b': 'Green Community: 0.9 km. Dubai Marina 21.7 km, Global Village 26.7 km.',
    }
    rows = consistency.distance_rows(texts)
    assert rows == []            # the Market Mall figure and the three "Emirates" places are not conflicts


def test_distance_conflict_and_facts_file(tmp_path):
    f = tmp_path / 'hotel-facts.json'
    f.write_text(json.dumps({'facts': [{'fact': 'Green Community: 0.9 km by road', 'source': 'hotel, 1 Nov'}]}))
    rows = consistency.distance_rows({'a': 'Green Community is 1 km from the hotel.'}, str(f))
    assert rows and rows[0]['facts_says'] == '0.9'


def test_hotel_name_is_not_a_landmark():
    rows = consistency.distance_rows({'a': 'Abar Hotel Apartments 0.9 km', 'b': 'Abar Hotel Apartments 11.9 km'},
                                     brand='abarhotels')
    assert rows == []


# ---------------------------------------------------------------- facts: the hotel's answer wins

def test_hotel_answer_supersedes_engine_and_guard(tmp_path):
    ff = str(tmp_path / 'hotel-facts.json')
    facts.add_facts(ff, ['Two Bedroom Apartment: up to 5 guests'], 'booking engine, 1 Nov 2026')
    r = facts.add_facts(ff, ['Two Bedroom Apartment: up to 8 guests (4 adults + 4 children)'],
                        'hotel (Mr Yunus, email 6 Nov 2026)')
    assert r['superseded'] == ['Two Bedroom Apartment: up to 5 guests']
    assert r['engine_corrections'] and r['engine_corrections'][0]['kind'] == 'guests'
    later = facts.add_facts(ff, ['2 Bedroom Apartment: up to 6 guests'], 'booking engine, 10 Nov 2026')
    stored = json.loads(open(ff, encoding='utf-8').read())['facts']
    assert stored[-1]['superseded'] and later['added']
    doc = {'hotel': 'H', 'sections': [{'number': 'A', 'title': 'x',
                                        'blocks': [{'paste': 'It sleeps 5 guests. It sleeps 8 guests.'}]}]}
    unverified = [u['phrase'] if isinstance(u, dict) else u for u in facts.check(doc, '', ff)['unverified']]
    assert '5 guests' in unverified and '8 guests' not in unverified


def test_bookingcom_alone_is_not_confirmation():
    assert not facts.is_confirmed_source('Booking.com, 1 Nov')
    assert facts.is_hotel_source('hotel (Mr Yunus, email 6 Nov)')


def test_sq_ft_sizes_are_guarded(tmp_path):
    (tmp_path / 'site_text.json').write_text(json.dumps({'u': 'Each apartment is 700–807 sq ft.'}))
    doc = {'hotel': 'H', 'sections': [{'number': 'A', 'title': 'x',
                                        'blocks': [{'paste': 'The One Bedroom is 700–807 sq ft; the Three is 1,500 sq ft.'}]}]}
    unverified = [u['phrase'] if isinstance(u, dict) else u for u in facts.check(doc, str(tmp_path))['unverified']]
    assert unverified == ['1,500 sq ft']


# ---------------------------------------------------------------- copy, Unicode, hreflang, robots

def test_copy_lint_skips_quoted_columns_and_flags_tells():
    doc = {'sections': [{'number': 'D', 'title': 'Titles', 'blocks': [
        {'table': {'columns': ['Page', 'Now', 'Title'], 'rows': [['/', 'Nestled in the heart of Deira', 'keep']]}},
        {'paste': 'Welcome to Riviera — your oasis. The best hotel in Deira.'}]}]}
    out = ' '.join(checks.lint_copy(doc))
    assert 'Nestled' not in out and 'stock opening' in out and 'em dash' in out and 'superlative' in out


def test_hidden_characters_ignored_in_rechecks():
    assert checks._clean('Deluxe​ Room­ | Hotel﻿') == checks._clean('deluxe room | hotel')


def test_hreflang_codes():
    ok = analysis._hreflang_code_ok
    assert ok('en-gb') and ok('ar-AE') and ok('x-default') and ok('es-419')
    assert not ok('en-uk') and not ok('jp') and not ok('english')


def test_robots_longest_match_and_groups():
    txt = 'User-agent: *\nDisallow: /wp-admin/\nAllow: /wp-admin/admin-ajax.php\n\n' \
          'User-agent: OAI-SearchBot\nDisallow: /\nAllow: /rooms/\n'
    assert not analysis.robots_allowed(txt, 'OAI-SearchBot', '/')
    assert analysis.robots_allowed(txt, 'OAI-SearchBot', '/rooms/deluxe/')
    assert analysis.robots_allowed(txt, 'Googlebot', '/wp-admin/admin-ajax.php')
    assert not analysis.robots_allowed(txt, 'Googlebot', '/wp-admin/x')


def test_impressions_anomaly_window():
    from datetime import date
    assert analysis.gsc_anomaly_note((date(2025, 11, 1), date(2026, 1, 30)))
    assert not analysis.gsc_anomaly_note((date(2026, 8, 1), date(2026, 10, 30)))


# ---------------------------------------------------------------- execute

def test_elementor_widget_key():
    out = execute.elementor_settings({'widgetType': 'text-editor', 'settings': {'editor': '<p>old</p>'}}, 'New', 'title')
    assert out['settings'] == {'editor': '<p>New</p>'}
    assert execute.elementor_settings({'widgetType': 'heading', 'settings': {'title': 'x'}}, 'H1')['settings'] == {'title': 'H1'}


def test_elementor_key_in_execute_resolution():
    # the rebuild's execute resolves elementor_text actions itself: a key the widget doesn't render is remapped
    el = {'id': 'e1', 'widgetType': 'text-editor', 'settings': {'editor': '<p>old</p>'}}
    assert execute._rendered_settings(el, {'title': 'New'}) == {'editor': '<p>New</p>'}
    assert execute._rendered_settings(el, {'editor': '<p>x</p>'}) == {'editor': '<p>x</p>'}
    assert execute._rendered_settings(el, {'title': 'a', 'editor': 'b'}) == {'title': 'a', 'editor': 'b'}


def test_execute_client_approval_gate(tmp_path):
    """v2.0.0's client-approval gate, ported to the rebuild's execute (the plan.json execute_plan writes; the rebuild
    replaced v2.0.0's list-based plan / start_batch / record_item / undo_steps)."""
    import pytest
    (tmp_path / 'hotel.json').write_text(json.dumps({'preferences': {'client_approval': True, 'units': 'sqft'}}))
    assert execute.hotel_preferences(tmp_path) == {'client_approval': True, 'units': 'sqft'}
    assert execute.hotel_preferences(tmp_path / 'nowhere') == {}
    pf = tmp_path / 'execute-2026-11-10' / 'plan.json'
    pf.parent.mkdir()
    pf.write_text(json.dumps({
        'site': 'https://hotel.com', 'hotel': 'h', 'client_approval_required': True, 'client_approval': None,
        'batches': {'chrome': [{'id': 'a1', 'finding': 'f1', 'page': 'https://hotel.com/x/', 'new': ['step 1'],
                                'via': 'chrome', 'action': {'type': 'chrome'}}]}}))
    with pytest.raises(PermissionError):
        execute.run_batch(str(pf), 'chrome', approved=False)
    with pytest.raises(PermissionError):
        execute.run_batch(str(pf), 'chrome', approved=True)          # client approval missing
    with pytest.raises(ValueError):
        execute.record_client_approval(str(pf), '  ')
    execute.record_client_approval(str(pf), 'Mr Yunus, email 10 Nov')
    out = execute.run_batch(str(pf), 'chrome', approved=True)
    assert out['via'] == 'chrome' and out['steps'][0]['id'] == 'a1'


# ---------------------------------------------------------------- Business Profile posts on hotel profiles

def test_hotel_posts_policy():
    from hotel_seo_tools import gbp_write
    import pytest
    for bad in ({'type': 'OFFER', 'summary': 'x'}, {'summary': 'Enjoy 20% off weekends'},
                {'summary': 'Pool open', 'url': 'https://h.com/offers/summer/'}):
        with pytest.raises(gbp_write.GbpError):
            gbp_write._hotel_post_policy(bad)
    gbp_write._hotel_post_policy({'summary': 'The spa now offers couples massages'})


# ---------------------------------------------------------------- Disparity / Best Rate calendar

def _calendar(tmp_path, name, rows):
    f = tmp_path / name
    f.write_text('Date,Weekday,Hotel,Parity Status,Bookings,Day Type\n' + '\n'.join(rows) + '\n', encoding='utf-8')
    return str(f)


def test_parity_calendar_counts_and_saturday_gap(tmp_path):
    from datetime import date
    from hotel_seo_tools import parity_calendar
    rows = []
    for d in range(1, 32):
        dt = date(2026, 8, d)
        st = 'No record' if dt.weekday() == 5 else 'Best Rates/Corrected'
        rows.append(f'{dt},{dt:%a},Gewan Palace New Alamein,{st},{4 if d == 3 else 0},x')
    r = parity_calendar.import_calendars([_calendar(tmp_path, 'aug.csv', rows)], str(tmp_path / 'out'))
    m = r['months'][0]
    assert (m['best_rate_days'], m['disparity_days'], m['no_record_days']) == (26, 0, 5)
    assert m['no_record_pattern'] == 'every Sat' and m['bookings'] == 4
    assert r['parity']['rows'][0][0] == 'Aug 2026' and r['working_rows'] and not r['lead_lines']


def test_parity_calendar_disparity_is_not_parity(tmp_path):
    from hotel_seo_tools import parity_calendar
    rows = [f'2026-09-{d:02d},x,H,{"Disparity" if d <= 10 else "Lose" if d == 11 else "Odd" if d == 12 else "Best Rates/Corrected"},1,x'
            for d in range(1, 31)]
    r = parity_calendar.import_calendars([_calendar(tmp_path, 'sep.csv', rows)], str(tmp_path / 'out'))
    m = r['months'][0]
    assert m['disparity_days'] == 11 and m['longest_disparity_run_days'] == 11 and m['unknown_statuses'] == ['Odd']
    assert r['lead_lines'] and any('Odd' in q for q in r['questions_for_metahotels'])


def test_parity_calendar_in_audit_report(tmp_path):
    """The rebuild has no Priority list: build_audit_report adds the calendar from <hotel dir>/parity/."""
    from hotel_seo_tools import parity_calendar, report
    assert report.parity_calendar_block(tmp_path, 'Gewan Palace') is None
    rows = [f'2026-09-{d:02d},x,Gewan Palace New Alamein,{"Disparity" if d <= 10 else "Best Rates/Corrected"},1,x'
            for d in range(1, 31)]
    rows += [f'2026-09-{d:02d},x,Other Hotel Cairo,Best Rates/Corrected,0,x' for d in range(1, 31)]
    parity_calendar.import_calendars([_calendar(tmp_path, 'sep.csv', rows)], str(tmp_path / 'parity'))
    pc = report.parity_calendar_block(tmp_path, 'Gewan Palace New Alamein')
    assert len(pc['parity']['rows']) == 1 and pc['parity']['rows'][0][2] == '10'
    assert pc['lead_lines'] and 'parity-calendar.json' in pc['parity']['note']
