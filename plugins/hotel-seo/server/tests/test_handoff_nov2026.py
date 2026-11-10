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


def test_execute_plan_gates(tmp_path, monkeypatch):
    monkeypatch.setattr(execute, '_seo_plugin', lambda site: 'Yoast SEO')
    monkeypatch.setattr(execute, '_live_h1', lambda site, url: ['Old H1'])
    d = tmp_path / 'hotel.com'
    (d / 'lists').mkdir(parents=True)
    (d / 'hotel.json').write_text(json.dumps({'preferences': {'client_approval': True}}))
    lst = {'hotel': 'H', 'site': 'https://hotel.com', 'title': 'Priority SEO List', 'date': '10 Nov', 'sections': [
        {'number': 'A', 'title': 'Titles', 'checks': [{'type': 'title', 'url': '/rooms/', 'expected': 'Rooms | H'}]},
        {'number': 'B', 'title': 'Redirect', 'checks': [{'type': 'redirect', 'source': '/old/', 'expected': '/offers/'}]},
        {'number': 'C', 'title': 'Copy', 'blocks': [{'table': {'columns': ['Where', 'Now', 'Change to'], 'rows': [
            ['/rooms/', 'up to 5 guests', 'up to 8 guests [CONFIRM]']]}}]},
        {'number': 'D', 'title': 'Held', 'hold': 'waiting for hotel details', 'checks': [{'type': 'status', 'url': '/x/',
                                                                                            'expected': 200}]},
        {'number': 'E', 'title': 'Price', 'checks': [{'type': 'text_present', 'url': '/offers/', 'text': 'Save 20% now'}]}]}
    lf = d / 'lists' / 'priority.json'
    lf.write_text(json.dumps(lst))
    p = execute.plan(str(lf))
    assert p['client_approval_required'] and p['blockers'][0]['batch'] == 'seo-fields'
    whys = ' '.join(s['why'] for s in p['skipped'])
    assert '[CONFIRM]' in whys and 'held' in whys and 'price' in whys
    pf = p['plan_file']
    import pytest
    with pytest.raises(PermissionError):
        execute.start_batch(pf, 'redirects', approved=False)
    with pytest.raises(PermissionError):
        execute.start_batch(pf, 'redirects', approved=True)          # client approval missing
    execute.record_client_approval(pf, 'Mr Yunus, email 10 Nov')
    with pytest.raises(PermissionError):
        execute.start_batch(pf, 'seo-fields', approved=True)         # Yoast blocker
    b = execute.start_batch(pf, 'redirects', approved=True)
    it = b['items'][0]
    execute.record_item(pf, it['id'], before={'exists': False})
    execute.record_item(pf, it['id'], after=it['new'], written=True, tool='redirects-create')
    assert execute.undo_steps(pf)['steps'][0]['do'].startswith('redirects-delete')


# ---------------------------------------------------------------- Business Profile posts on hotel profiles

def test_hotel_posts_policy():
    from hotel_seo_tools import gbp_write
    import pytest
    for bad in ({'type': 'OFFER', 'summary': 'x'}, {'summary': 'Enjoy 20% off weekends'},
                {'summary': 'Pool open', 'url': 'https://h.com/offers/summer/'}):
        with pytest.raises(gbp_write.GbpError):
            gbp_write._hotel_post_policy(bad)
    gbp_write._hotel_post_policy({'summary': 'The spa now offers couples massages'})
