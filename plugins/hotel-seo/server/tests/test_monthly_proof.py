"""Monthly proof: AI-answer panel (questions, import validation, trend, "not run") and the per-change readback
against similar unchanged pages (labels, windows, grouping)."""
import json
from datetime import date

import pytest

from hotel_seo_tools import group, monthly, monthly_proof as mp

HOST = 'example-hotels.com'


@pytest.fixture
def hotel(tmp_path, monkeypatch):
    monkeypatch.setenv('HOTEL_SEO_HOME', str(tmp_path))
    group.save(HOST, {'name': 'Example Group', 'site': f'https://{HOST}/'},
               [{'slug': 'park', 'name': 'Example Park Hotel', 'paths': ['/'], 'city': 'Dubai',
                 'gsc_property': f'sc-domain:{HOST}', 'ga4_property': 'properties/1'}])
    hd = tmp_path / HOST
    (hd / 'keywords').mkdir(parents=True)
    (hd / 'keywords' / 'keyword-map.json').write_text(json.dumps({'city': 'Dubai', 'clusters': [
        {'kind': 'place', 'head': 'Barsha Heights', 'primary_keyword': 'hotel in barsha heights', 'score': 50},
        {'kind': 'landmark', 'head': 'Mall of the Emirates', 'primary_keyword': 'hotel near mall of the emirates',
         'score': 40},
        {'kind': 'audience', 'head': 'family', 'primary_keyword': 'family hotel barsha heights', 'score': 30},
        {'kind': 'facility', 'head': 'with kitchen', 'primary_keyword': 'hotel with kitchen barsha heights',
         'score': 20},
        {'kind': 'room', 'head': 'studio apartment', 'primary_keyword': 'studio apartment barsha heights',
         'score': 10}]}), encoding='utf-8')
    (hd / 'hotel-facts.json').write_text(json.dumps({'facts': [{'fact': 'Check-in 15:00', 'source': 'hotel'}]}),
                                         encoding='utf-8')
    for month, ai in (('2026-09', 46), ('2026-08', 16)):
        md = hd / f'monthly-{month}'
        md.mkdir()
        data = {'hotel': 'Example Park Hotel', 'month': month, 'brand_terms': ['example park'],
                'periods': {k: [str(a), str(b)] for k, (a, b) in monthly.periods(month).items()},
                'gsc': {'status': 'not available: test'},
                'ga4': {'status': 'ok', 'current': {'organic': {'sessions': 832}, 'all': {'sessions': 3500},
                                                    'ai': {'sessions': ai, 'by_assistant': []}},
                        'previous': {'organic': {'sessions': 320}, 'all': {'sessions': 1200},
                                     'ai': {'sessions': 16, 'by_assistant': []}},
                        'last_year': {'organic': {'sessions': None}, 'all': {'sessions': None},
                                      'ai': {'sessions': None}}},
                'mirai': {'status': 'not available'}, 'parity': {'status': 'not available'},
                'index': {'status': 'not available'}, 'work': {'items': [], 'build_plan_steps': []},
                'tracked': {'keywords': []}}
        (md / 'data.json').write_text(json.dumps(data), encoding='utf-8')
    return tmp_path


def _ctx():
    return monthly.context(HOST, 'park')


# ---------------------------------------------------------------- prompts

def test_prompts_built_from_keyword_map(hotel):
    data = mp.prompts_tool(_ctx())
    ps = [p['prompt'] for p in data['prompts']]
    assert len(ps) == mp.PROMPT_TARGET and len(set(ps)) == len(ps)
    assert data['confirmed'] is False
    assert any('Barsha Heights' in p for p in ps)
    assert any('Mall of the Emirates' in p for p in ps)
    assert any(p.startswith('Family hotel in Barsha Heights with kitchen') for p in ps)
    assert sum(1 for p in data['prompts'] if p['kind'] == 'brand') == 2
    assert all('Example Park Hotel' in p['prompt'] for p in data['prompts'] if p['kind'] == 'brand')
    assert data['facts_to_check'] == ['Check-in 15:00']
    assert (hotel / HOST / 'ai-prompts.json').exists()


def test_prompts_saved_set_keeps_ids_and_is_reused(hotel):
    first = mp.prompts_tool(_ctx())['prompts']
    keep = first[2]['prompt']
    saved = mp.prompts_tool(_ctx(), prompts=[keep, {'prompt': 'Hotel in Dubai with free shuttle to Dubai Mall',
                                                    'kind': 'discovery'}])
    assert saved['confirmed'] is True
    assert saved['prompts'][0]['id'] == first[2]['id']
    assert saved['prompts'][1]['id'] not in {p['id'] for p in first if p['prompt'] == keep}
    again = mp.prompts_tool(_ctx())                    # a plain read returns the saved set, not a new proposal
    assert [p['prompt'] for p in again['prompts']] == [p['prompt'] for p in saved['prompts']]
    with pytest.raises(ValueError):
        mp.save_prompts(_ctx(), [{'prompt': 'x', 'kind': 'other'}])


# ---------------------------------------------------------------- panel import

def _panel(results, **kw):
    return {'checked': '2026-10-04', 'results': results, **kw}


def _r(pid, engine, named=True, cited=False, position=None, **kw):
    return {'prompt': pid, 'engine': engine, 'named': named, 'cited': cited, 'position': position, **kw}


def test_panel_import_saves_validated_block(hotel):
    ps = mp.prompts_tool(_ctx(), prompts=['Best hotel in Barsha Heights', 'Tell me about Example Park Hotel'])
    out = monthly.import_manual(HOST, 'park', '2026-09', {'ai_panel': _panel([
        _r('p1', 'ChatGPT', named='yes', cited='no', position=2, hotels_named=5, competitors='Rove; Booking.com',
           description_correct='yes'),
        _r('Tell me about Example Park Hotel', 'google ai overview', named=True, cited=True, position=1,
           description_correct=False, errors=['says check-in 14:00 (fact: 15:00)']),
        _r('p1', 'perplexity', named=False)], not_run={})})
    saved = json.loads((hotel / HOST / 'monthly-2026-09' / 'manual.json').read_text(encoding='utf-8'))['ai_panel']
    assert saved == out['saved']['ai_panel']
    assert [r['engine'] for r in saved['results']] == ['chatgpt', 'google_ai', 'perplexity']
    assert saved['results'][0]['competitors'] == ['Rove', 'Booking.com']
    assert saved['results'][1]['id'] == ps['prompts'][1]['id']
    assert saved['prompts_in_set'] == 2


@pytest.mark.parametrize('bad, msg', [
    (_r('p1', 'bing'), 'engine'),
    (_r('p9', 'chatgpt'), 'not one of the saved questions'),
    (_r('p1', 'chatgpt', named=False, position=3), 'not named'),
    (_r('p1', 'chatgpt', description_correct=False), 'list the errors'),
    (_r('p1', 'chatgpt', description_correct=True, errors=['x']), 'errors listed'),
    (_r('p1', 'chatgpt', named=False, description_correct=True), 'no description'),
    (_r('p1', 'chatgpt', position=6, hotels_named=4), 'beyond'),
    (_r('p1', 'chatgpt', named='maybe'), 'yes / no'),
    ({**_r('p1', 'chatgpt'), 'rank': 1}, 'not a known field'),
    ({'prompt': 'p1', 'engine': 'chatgpt'}, 'required'),
])
def test_panel_import_refuses_bad_rows(hotel, bad, msg):
    mp.prompts_tool(_ctx(), prompts=['Best hotel in Barsha Heights'])
    with pytest.raises(ValueError, match=msg):
        monthly.import_manual(HOST, 'park', '2026-09', {'ai_panel': _panel([bad])})


def test_panel_import_refuses_duplicates_empty_and_missing_prompt_set(hotel):
    with pytest.raises(ValueError, match='ai_prompts first'):
        monthly.import_manual(HOST, 'park', '2026-09', {'ai_panel': _panel([_r('p1', 'chatgpt')])})
    mp.prompts_tool(_ctx(), prompts=['Best hotel in Barsha Heights'])
    with pytest.raises(ValueError, match='twice'):
        monthly.import_manual(HOST, 'park', '2026-09', {'ai_panel': _panel([_r('p1', 'chatgpt'), _r('p1', 'ChatGPT')])})
    with pytest.raises(ValueError, match='no results'):
        monthly.import_manual(HOST, 'park', '2026-09', {'ai_panel': _panel([])})
    with pytest.raises(ValueError, match='also listed as not run'):
        monthly.import_manual(HOST, 'park', '2026-09', {'ai_panel': _panel([_r('p1', 'chatgpt')],
                                                                          not_run={'chatgpt': 'login'})})
    with pytest.raises(ValueError, match='not a known block'):
        monthly.import_manual(HOST, 'park', '2026-09', {'ai_answers': {}})
    assert not (hotel / HOST / 'monthly-2026-09' / 'manual.json').exists()


# ---------------------------------------------------------------- panel in the report

def _page(doc, eyebrow):
    return next(p for p in doc['monthly']['pages'] if p['eyebrow'].startswith(eyebrow))


def _panel_table(page):
    return next(c for c in page['components'] if c.get('title') == 'What AI answers say when guests ask')


def test_panel_trend_vs_last_month(hotel):
    mp.prompts_tool(_ctx(), prompts=['Best hotel in Barsha Heights', 'Hotel near Mall of the Emirates'])
    monthly.import_manual(HOST, 'park', '2026-08', {'ai_panel': _panel([
        _r('p1', 'chatgpt', named=False), _r('p2', 'chatgpt', named=True, position=3)], checked='2026-09-03')})
    monthly.import_manual(HOST, 'park', '2026-09', {'ai_panel': _panel([
        _r('p1', 'chatgpt', named=True, cited=True, position=1, competitors=['Rove Barsha']),
        _r('p2', 'chatgpt', named=True, position=2, competitors=['Rove Barsha', 'Booking.com']),
        _r('p1', 'perplexity', named=False, competitors=['Rove Barsha'])],
        not_run={'google_ai': 'AI Mode not offered in this browser'})})
    monthly.build(HOST, 'park', '2026-09')
    doc = json.loads((hotel / HOST / 'monthly-2026-09' / 'monthly-report.json').read_text(encoding='utf-8'))
    page = _page(doc, '03')
    rows = {r[0]: r for r in _panel_table(page)['table']['rows']}
    assert rows['ChatGPT'][1:5] == ['2 of 2', '1 of 2', '#1.5', '–']
    assert rows['ChatGPT'][5] == {'text': '▲ from 1 of 2', 'pill': 'green'}
    assert rows['Perplexity'][1] == '0 of 1' and rows['Perplexity'][5]['text'] == 'not run last month'
    assert rows['Google AI Mode / AI Overview'][1] == {'text': 'not run', 'pill': 'grey'}
    assert rows['Google AI Mode / AI Overview'][5] == 'AI Mode not offered in this browser'
    others = next(c for c in page['components'] if c.get('title') == 'Also named in the answers')
    assert others['list'][0] == 'Rove Barsha (3 answers)'
    assert any('not a ranking' in c.get('note', '') for c in page['components'])
    # GA4 AI visits still lead the page
    assert page['components'][0]['cards'][0]['value'] == '46'


def test_panel_not_run_shows_not_run_not_zeros(hotel):
    r = monthly.build(HOST, 'park', '2026-09')
    doc = json.loads((hotel / HOST / 'monthly-2026-09' / 'monthly-report.json').read_text(encoding='utf-8'))
    comp = _panel_table(_page(doc, '03'))
    assert 'not run' in comp['text'] and 'table' not in comp
    assert any('AI answer check not run' in m for m in r['not_available'])


def test_panel_summary_trend_drop_and_same():
    prev = {'checked': '2026-09-03', 'results': [_full('p1', 'chatgpt', True), _full('p2', 'chatgpt', True)]}
    cur = {'checked': '2026-10-03', 'results': [_full('p1', 'chatgpt', True), _full('p2', 'chatgpt', False)]}
    rows = mp.panel_components(cur, prev, 'October 2026')[0][0]['table']['rows']
    assert rows[0][5] == {'text': '▼ from 2 of 2', 'pill': 'red'}
    rows = mp.panel_components(cur, cur, 'October 2026')[0][0]['table']['rows']
    assert rows[0][5]['text'] == 'same as last month (1 of 2)'


def _full(pid, engine, named):
    return {'id': pid, 'prompt': pid, 'engine': engine, 'named': named, 'cited': False, 'position': 1 if named else None,
            'competitors': [], 'description_correct': None, 'errors': []}


# ---------------------------------------------------------------- readback

def test_windows_exclude_the_change_day():
    (b0, b1), (a0, a1) = mp.windows('2026-09-15', 28)
    assert (b0, b1, a0, a1) == (date(2026, 8, 18), date(2026, 9, 14), date(2026, 9, 16), date(2026, 10, 13))
    assert (b1 - b0).days + 1 == 28 and (a1 - a0).days + 1 == 28
    assert mp.windows('2026-09-15', 56)[1][1] == date(2026, 11, 10)


def _row(path, clicks, impressions, position=8.0):
    return {'keys': [f'https://www.{HOST}{path}'], 'clicks': clicks, 'impressions': impressions, 'position': position}


def _fetch(change_day, page_before, page_after, ctrl_before=(100, 1000), ctrl_after=(105, 1050), extra=()):
    """Search Console rows by page: the changed room page, three unchanged room pages, one offer page."""
    cd = date.fromisoformat(change_day)
    calls = []

    def fetch(s, e):
        calls.append((s, e))
        before = e < cd
        rows = [_row('/rooms/deluxe/', *(page_before if before else page_after))]
        for p in ('/rooms/studio/', '/rooms/suite/', '/rooms/family/'):
            rows.append(_row(p, *(ctrl_before if before else ctrl_after)))
        rows.append(_row('/offers/summer/', *((10, 100) if before else (90, 900))))   # other type: ignored
        rows += list(extra)
        return rows
    fetch.calls = calls
    return fetch


CH = [{'page': f'https://{HOST}/rooms/deluxe/', 'date': '2026-09-01', 'what': ['SEO titles updated'],
       'sources': ['execute']}]
AS_OF = date(2026, 10, 15)          # 28 days after are in, 56 are not


def test_readback_gain_beyond_similar_pages_is_promote():
    it = mp.readback(CH, _fetch('2026-09-01', (50, 1000), (80, 1200)), AS_OF, HOST)[0]
    assert it['label'] == 'promote' and it['label_text'] == 'Promote'
    w = it['windows']['28']
    assert w['metric'] == 'clicks' and w['page_change_pct'] == 60.0 and w['control_change_pct'] == 5.0
    assert w['gap_points'] == 55.0 and w['control']['pages'] == 3 and w['control_type'] == 'unchanged rooms pages'
    assert 'moved ahead of similar pages' in it['why']
    assert w['page']['before']['ctr_pct'] == 5.0 and w['page']['after']['position'] == 8.0
    assert '56' not in it['windows']


def test_readback_moving_with_similar_pages_is_unproven():
    it = mp.readback(CH, _fetch('2026-09-01', (50, 1000), (55, 1100), (100, 1000), (110, 1100)), AS_OF, HOST)[0]
    assert it['label'] == 'unproven' and 'moved with similar pages' in it['why']


def test_readback_drop_against_similar_pages_is_rollback_candidate():
    it = mp.readback(CH, _fetch('2026-09-01', (50, 1000), (30, 900)), AS_OF, HOST)[0]
    assert it['label'] == 'rollback' and it['label_text'] == 'Rollback candidate'
    assert 'moved against similar pages' in it['why']
    assert 'caus' not in it['why']


def test_readback_too_few_impressions_keeps_testing():
    it = mp.readback(CH, _fetch('2026-09-01', (2, mp.MIN_IMPRESSIONS - 1), (9, 400)), AS_OF, HOST)[0]
    assert it['label'] == 'keep_testing' and 'too little data' in it['why']


def test_readback_low_clicks_compares_google_views():
    it = mp.readback(CH, _fetch('2026-09-01', (5, 500), (6, 800)), AS_OF, HOST)[0]
    w = it['windows']['28']
    assert w['metric'] == 'impressions' and w['page_change_pct'] == 60.0 and it['label'] == 'promote'


def test_readback_too_early_does_not_query():
    f = _fetch('2026-09-01', (50, 1000), (80, 1200))
    it = mp.readback(CH, f, date(2026, 9, 20), HOST)[0]
    assert it['label'] == 'keep_testing' and 'too early' in it['why']
    assert f.calls == []


def test_readback_uses_56_days_when_available():
    f = _fetch('2026-09-01', (50, 1000), (80, 1200))
    it = mp.readback(CH, f, date(2026, 11, 5), HOST)[0]
    assert set(it['windows']) == {'28', '56'} and it['used_days'] == 56
    assert it['windows']['56']['before'] == ['2026-07-07', '2026-08-31']


def test_readback_falls_back_to_all_pages_then_unproven():
    ch = [{'page': f'https://{HOST}/blog/guide/', 'date': '2026-09-01', 'what': ['Page text updated'],
           'sources': ['work log']}]
    extra = [_row('/blog/guide/', *(50, 1000))]
    it = mp.readback(ch, _fetch('2026-09-01', (50, 1000), (80, 1200), extra=extra), AS_OF, HOST)[0]
    assert it['windows']['28']['control_type'] == 'all unchanged pages of the hotel'
    lone = mp.readback(ch, lambda s, e: [_row('/blog/guide/', 50, 1000)], AS_OF, HOST)[0]
    assert lone['label'] == 'unproven' and 'not enough unchanged pages' in lone['why']


def test_changed_pages_are_never_their_own_control():
    ch = CH + [{'page': f'https://{HOST}/rooms/studio/', 'date': '2026-09-01', 'what': ['x'], 'sources': ['execute']}]
    it = mp.readback(ch, _fetch('2026-09-01', (50, 1000), (80, 1200)), AS_OF, HOST)[0]
    w = it['windows']['28']        # two unchanged room pages are too few: all unchanged pages, still not /rooms/studio/
    assert w['control_type'] == 'all unchanged pages of the hotel' and w['control']['pages'] == 3


def test_group_changes_same_page_same_day():
    raw = [{'page': f'https://{HOST}/rooms/deluxe/', 'date': '2026-09-01', 'what': 'SEO titles updated',
            'source': 'execute'},
           {'page': f'https://www.{HOST}/rooms/deluxe', 'date': '2026-09-01', 'what': 'Meta descriptions updated',
            'source': 'execute'},
           {'page': '/rooms/deluxe/', 'date': '2026-09-01', 'what': 'SEO titles updated', 'source': 'work log'},
           {'page': f'https://{HOST}/rooms/deluxe/', 'date': '2026-09-20', 'what': 'Page text updated',
            'source': 'execute'},
           {'page': f'https://{HOST}/old/', 'date': '2026-01-01', 'what': 'old', 'source': 'execute'},
           {'page': f'https://{HOST}/bad/', 'date': '', 'what': 'no date', 'source': 'work log'}]
    g = mp.group_changes(raw, date(2026, 6, 1), date(2026, 9, 30), f'https://{HOST}/')
    assert len(g) == 2
    assert g[0]['what'] == ['SEO titles updated', 'Meta descriptions updated']
    assert g[0]['sources'] == ['execute', 'work log'] and g[1]['date'] == '2026-09-20'


def test_changed_pages_reads_execute_and_work_log(hotel):
    hd = hotel / HOST
    (hd / 'execute-2026-09-01').mkdir()
    (hd / 'execute-2026-09-01' / 'changes.json').write_text(json.dumps([
        {'id': 'a', 'page': f'https://{HOST}/rooms/deluxe/', 'field': 'title', 'at': '2026-09-01 10:00:00'},
        {'id': 'b', 'page': f'https://{HOST}/rooms/deluxe/', 'field': 'description', 'at': '2026-09-01 10:05:00'},
        {'id': 'c', 'page': '', 'field': 'menu', 'at': '2026-09-01 10:05:00'}]), encoding='utf-8')
    monthly.add_work_log(HOST, 'park', '2026-09-10', 'Offer page rewritten', f'https://{HOST}/offers/summer/')
    monthly.add_work_log(HOST, 'park', '2026-09-11', 'Business Profile photos')          # no URL: not read back
    g = mp.changed_pages(_ctx(), '2026-09')
    assert [(x['date'], x['what']) for x in g] == [
        ('2026-09-01', ['SEO titles updated', 'Meta descriptions updated']), ('2026-09-10', ['Offer page rewritten'])]


def test_collect_readback_queries_search_console_once_per_window(hotel, monkeypatch):
    hd = hotel / HOST
    (hd / 'execute-2026-09-01').mkdir()
    (hd / 'execute-2026-09-01' / 'changes.json').write_text(json.dumps([
        {'page': f'https://{HOST}/rooms/deluxe/', 'field': 'title', 'at': '2026-09-01 10:00:00'}]), encoding='utf-8')
    f = _fetch('2026-09-01', (50, 1000), (80, 1200))
    from hotel_seo_tools import keyword_map
    monkeypatch.setattr(keyword_map, '_gsc_rows', lambda prop, s, e, dims, prefixes: f(s, e))
    out = mp.collect_readback(_ctx(), '2026-09', today=date(2026, 10, 18))
    assert out['status'] == 'ok' and out['as_of'] == '2026-10-15'
    assert out['constants']['min_impressions'] == mp.MIN_IMPRESSIONS
    assert out['items'][0]['label'] == 'promote'
    assert len(f.calls) == len(set(f.calls)) == 2


def test_readback_in_work_done_page(hotel):
    md = hotel / HOST / 'monthly-2026-09'
    data = json.loads((md / 'data.json').read_text(encoding='utf-8'))
    items = mp.readback(CH, _fetch('2026-09-01', (50, 1000), (80, 1200)), AS_OF, HOST)
    data['readback'] = {'status': 'ok', 'as_of': str(AS_OF), 'constants': {}, 'items': items}
    (md / 'data.json').write_text(json.dumps(data), encoding='utf-8')
    monthly.build(HOST, 'park', '2026-09')
    doc = json.loads((md / 'monthly-report.json').read_text(encoding='utf-8'))
    comp = next(c for c in _page(doc, '04')['components'] if c.get('title') == 'Did each change move its page?')
    row = comp['table']['rows'][0]
    assert row[0] == '/rooms/deluxe/' and row[1] == '1 Sep' and row[3] == '50 → 80 clicks'
    assert row[4] == '+5% (3 pages)' and row[5] == {'text': 'Promote', 'pill': 'green'}
    assert 'does not prove' in _page(doc, '04')['components'][-1]['note'] or any(
        'does not prove' in c.get('note', '') for c in _page(doc, '04')['components'])
    # the Word / Google Doc sections carry it too, and the PDF page renders it with the result pill
    assert any('Did each change move its page?' in json.dumps(s) for s in doc['sections'])
    from hotel_seo_tools import pdf
    html = pdf.build_html(doc)
    assert 'Did each change move its page?' in html and '<span class="pill pill-green">Promote</span>' in html
    assert 'What AI answers say when guests ask' in html
