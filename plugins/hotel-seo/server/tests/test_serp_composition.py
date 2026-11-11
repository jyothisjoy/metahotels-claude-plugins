"""Whole Google page 1 from Serper (composition), its use in the keyword map (rivals, People Also Ask, build order,
seasonal timing) and the monthly report's "Google last month" column. No live API calls."""
import json
from datetime import date

import pytest

from hotel_seo_tools import apikeys, group, keyword_map as km, monthly, serp

SITE = 'https://rosehotelsgroup.com/'
PREFIX = ['/hotels-apartments/rose-park-albarsha/']

PAGE1 = {
    'organic': [
        {'title': 'THE 10 BEST Hotels in Al Barsha 2026 - Tripadvisor', 'link': 'https://www.tripadvisor.com/Hotels-g1'},
        {'title': 'Hotels in Al Barsha, Dubai', 'link': 'https://www.booking.com/district/ae/dubai/albarsha.html'},
        {'title': 'Rose Park Hotel Al Barsha', 'link': 'https://rosehotelsgroup.com/hotels-apartments/rose-park-albarsha/'},
        {'title': 'Rose Plaza Al Barsha', 'link': 'https://rosehotelsgroup.com/hotels-apartments/rose-plaza/'},
        {'title': 'Grand Barsha Hotel | Official site', 'link': 'https://www.grandbarsha.com/'},
        {'title': 'Novotel Dubai Al Barsha', 'link': 'https://all.accor.com/hotel/6532/index.en.shtml'},
        {'title': 'Where to stay in Al Barsha', 'link': 'https://www.timeoutdubai.com/travel/where-to-stay'},
        {'title': 'Al Barsha travel tips', 'link': 'https://someblog.net/blog/al-barsha-tips'},
        {'title': 'Al Barsha hotels', 'link': 'https://www.expedia.ae/Al-Barsha-Hotels.d1.Travel-Guide-Hotels'},
        {'title': 'Al Barsha - property listings', 'link': 'https://www.bayut.com/al-barsha/'},
    ],
    'peopleAlsoAsk': [{'question': 'Is Al Barsha a good area to stay in Dubai?', 'snippet': '...'},
                      {'question': 'How far is Al Barsha from the airport?'}, {'snippet': 'no question'}],
    'relatedSearches': [{'query': 'al barsha hotels near metro'}, {'query': 'cheap hotels al barsha'}],
    'answerBox': {'title': 'Al Barsha', 'snippet': 'A district of Dubai', 'link': 'https://en.wikipedia.org/wiki/Al_Barsha'},
    'knowledgeGraph': {'title': 'Al Barsha', 'type': 'Neighbourhood', 'website': 'https://www.dubai.ae/'},
    'places': [{'title': 'Some Hotel'}],
}


# ---------------------------------------------------------------- classification

@pytest.mark.parametrize('link,title,label', [
    ('https://www.booking.com/hotel/ae/x.html', 'X', 'booking site'),
    ('https://www.expedia.co.uk/Dubai-Hotels', 'Dubai hotels', 'booking site'),
    ('https://ar.hotels.com/de123', 'Hotel X', 'booking site'),
    ('https://www.agoda.com/x', 'x', 'booking site'),
    ('https://www.trip.com/hotels/x', 'x', 'booking site'),
    ('https://www.tripadvisor.ae/Hotel_Review', 'Hotel X', 'booking site'),
    ('https://www.google.com/travel/hotels/x', 'x', 'booking site'),
    ('https://rosehotelsgroup.com/hotels-apartments/rose-park-albarsha/rooms/', 'Rooms', 'own hotel'),
    ('https://www.rosehotelsgroup.com/offers/', 'Offers', 'own group'),
    ('https://www.timeoutdubai.com/hotels/best', 'Best hotels', 'guide'),
    ('https://example.net/blog/dubai-areas', 'Dubai areas', 'guide'),
    ('https://news.example.com/x', '10 best hotels in Dubai', 'guide'),
    ('https://www.marriott.com/en-us/hotels/dxbmc', 'Marriott Al Barsha', 'rival hotel'),
    ('https://www.grandbarsha.com/', 'Grand Barsha | Official', 'rival hotel'),       # rival_names match
    ('https://www.someresort.ae/', 'Welcome', 'rival hotel'),                          # hotel word in the domain
    ('https://www.bayut.com/al-barsha/', 'Al Barsha listings', 'other'),
    ('https://rosehotels.com/', 'Welcome', 'rival hotel'),                             # not hotels.com
])
def test_classify_result(link, title, label):
    assert serp.classify_result(link, title, 'rosehotelsgroup.com', PREFIX, rival_names=['Grand Barsha Hotel']) == label


def test_mix_verdict():
    assert serp.mix_verdict({'booking site': 7, 'rival hotel': 1}) == 'mostly booking sites'
    assert serp.mix_verdict({'booking site': 7, 'rival hotel': 1, 'own hotel': 1}) == 'hotel sites can win'
    assert serp.mix_verdict({'guide': 6}) == 'mostly guides and articles'
    assert serp.mix_verdict({'booking site': 3, 'guide': 3, 'other': 4}) == 'mixed'


# ---------------------------------------------------------------- composition

def test_composition_parses_page_one():
    c = serp.composition(PAGE1, 'rosehotelsgroup.com', PREFIX, rival_names=['Grand Barsha Hotel'])
    labels = [t['label'] for t in c['top10']]
    assert labels == ['booking site', 'booking site', 'own hotel', 'own group', 'rival hotel', 'rival hotel', 'guide',
                      'guide', 'booking site', 'other']
    assert c['mix'] == {'booking site': 3, 'own hotel': 1, 'own group': 1, 'rival hotel': 2, 'guide': 2, 'other': 1}
    assert c['verdict'] == 'hotel sites can win'
    assert c['rival_domains'] == ['grandbarsha.com', 'all.accor.com']
    assert c['paa'] == ['Is Al Barsha a good area to stay in Dubai?', 'How far is Al Barsha from the airport?']
    assert c['related'] == ['al barsha hotels near metro', 'cheap hotels al barsha']
    assert c['answer_box'] == {'title': 'Al Barsha', 'text': 'A district of Dubai', 'domain': 'en.wikipedia.org'}
    assert c['knowledge_graph'] == {'title': 'Al Barsha', 'type': 'Neighbourhood', 'domain': 'dubai.ae'}


def test_composition_missing_fields():
    c = serp.composition({}, 'rosehotelsgroup.com', PREFIX)
    assert c['top10'] == [] and c['verdict'] is None and c['paa'] == [] and c['related'] == []
    assert c['answer_box'] is None and c['knowledge_graph'] is None and c['rival_domains'] == []
    assert serp.composition(None)['mix'] == dict.fromkeys(serp.LABELS, 0)


def _fake_post(pages):
    calls = []

    def post(endpoint, body):
        calls.append(body)
        return pages[body.get('page', 1) - 1] if endpoint == 'search' else {'places': []}
    post.calls = calls
    return post


def test_rank_keeps_composition_at_no_extra_credit(monkeypatch):
    fake = _fake_post([PAGE1])
    monkeypatch.setattr(serp, '_post', fake)
    r = serp.rank('hotels in al barsha', SITE, PREFIX, 'Rose Park Al Barsha', 'Dubai')
    assert r['position'] == 3 and r['credits'] == 1 and len(fake.calls) == 1
    assert r['composition']['paa'][0].startswith('Is Al Barsha')
    assert r['composition']['mix']['own hotel'] == 1
    assert r['map_pack'] == {'shown': True, 'hotel_position': None, 'hotels': ['Some Hotel']}   # unchanged shape


# ---------------------------------------------------------------- seasonal peak

def _months(values, year=2025):
    return [{'month': f'{year}-{i:02d}', 'searches': v} for i, v in enumerate(values, 1)]


def test_seasonal_peak_found_with_publish_by():
    p = km.seasonal_peak(_months([100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 300]), today=date(2026, 3, 1))
    assert p['month'] == 12 and p['name'] == 'December'
    assert p['publish_by'] == '2026-10-06'               # 1 Dec 2026 - 8 weeks
    assert p['lift_pct'] == round((300 / (1400 / 12) - 1) * 100)


def test_seasonal_peak_none_when_flat_or_missing():
    assert km.seasonal_peak(_months([100] * 12)) is None
    assert km.seasonal_peak(_months([100, 105, 110, 100, 95, 100, 100, 110, 100, 100, 100, 120])) is None   # < 30% lift
    assert km.seasonal_peak(_months([100] * 11)) is None                    # not 12 months
    assert km.seasonal_peak([]) is None and km.seasonal_peak(None) is None
    assert km.seasonal_peak(_months([0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 40])) is None   # too few searches
    assert km.seasonal_peak([{'month': '2025-?', 'searches': 10}]) is None


def test_timing_line_in_why_and_now_when_close():
    c = {'kind': 'place', 'head': 'al barsha', 'status': 'no page', 'monthly': _months([50] * 6 + [200] + [50] * 5)}
    why = km.explain(c, city='dubai', today=date(2026, 1, 10))
    assert any('peak in July' in w and 'by 6 May 2026' in w for w in why)
    why = km.explain(c, city='dubai', today=date(2026, 6, 20))
    assert any('peak in July' in w and 'now' in w for w in why)
    flat = dict(c, monthly=_months([50] * 12))
    assert not any('peak' in w for w in km.explain(flat, city='dubai'))


def test_sum_monthly_adds_cluster_searches():
    items = [{'monthly': _months([10] * 12)}, {'monthly': _months([5] * 12)}, {'monthly': [{'month': '2025-?',
                                                                                        'searches': 99}]}]
    s = km._sum_monthly(items)
    assert len(s) == 12 and all(x['searches'] == 15 for x in s)


# ---------------------------------------------------------------- keyword map: page 1, rivals, build order

def _clusters():
    return [
        {'id': 'type-hotels', 'primary_keyword': 'hotels in dubai', 'status': 'ranks', 'score': 900},
        {'id': 'place-barsha', 'primary_keyword': 'hotels in al barsha', 'status': 'no page', 'score': 500},
        {'id': 'landmark-moe', 'primary_keyword': 'hotel near mall of the emirates', 'status': 'shows but low',
         'score': 300},
        {'id': 'room-family', 'primary_keyword': 'family room al barsha', 'status': 'no page', 'score': 100},
    ]


NOBODY = {'organic': [{'title': f'Deal {i}', 'link': f'https://www.booking.com/x{i}'} for i in range(7)]
          + [{'title': 'Guide', 'link': 'https://www.timeoutdubai.com/x'}]}
RIVALS = {'organic': [{'title': 'Mall Hotel Dubai', 'link': 'https://www.mallhotel.ae/'},
                      {'title': 'x', 'link': 'https://www.booking.com/x'}],
          'peopleAlsoAsk': [{'question': 'Which hotel is connected to Mall of the Emirates?'}]}


def test_serp_enrich_checks_capped_clusters_and_orders_rivals_first(tmp_path, monkeypatch):
    by_kw = {'hotels in al barsha': NOBODY, 'hotel near mall of the emirates': RIVALS}
    calls = []

    def post(endpoint, body):
        calls.append(body['q'])
        return by_kw.get(body['q'], {})
    monkeypatch.setattr(serp, '_post', post)
    monkeypatch.setattr(apikeys, 'get', lambda name: 'k' if name == 'serper' else None)
    cl = _clusters()
    note = km.serp_enrich(cl, tmp_path, SITE, {'name': 'Rose Park Al Barsha', 'paths': PREFIX}, 'Dubai',
                          'United Arab Emirates', limit=2)
    assert calls == ['hotels in al barsha', 'hotel near mall of the emirates']      # 'ranks' skipped; cap 2
    assert note['checked'] == 2 and note['credits'] == 2
    assert 'serp' not in cl[0] and 'serp' not in cl[3]
    assert cl[1]['serp']['verdict'] == 'mostly booking sites' and cl[1]['serp']['rival_domains'] == []
    assert cl[2]['serp']['rival_domains'] == ['mallhotel.ae']
    assert cl[2]['serp']['paa'] == ['Which hotel is connected to Mall of the Emirates?']
    # rivals rank + we're low -> ahead of the higher-score cluster nobody's hotel page serves
    assert km.build_order(cl) == ['landmark-moe', 'type-hotels', 'place-barsha', 'room-family']
    why = km.explain(cl[2], city='dubai')
    assert any(w.startswith('Rival hotels are on page 1') and 'mallhotel.ae' in w for w in why)
    assert any('Which hotel is connected' in w for w in why)
    assert any('mostly booking sites' in w for w in km.explain(cl[1], city='dubai'))
    # second run: reused from the cache, no credits
    calls.clear()
    cl2 = _clusters()
    note2 = km.serp_enrich(cl2, tmp_path, SITE, {'name': 'Rose Park Al Barsha', 'paths': PREFIX}, 'Dubai',
                           'United Arab Emirates', limit=2)
    assert calls == [] and note2['reused'] == 2 and note2['credits'] == 0
    assert cl2[2]['serp']['source'] == 'earlier check'


def test_serp_enrich_without_key_or_old_files(tmp_path, monkeypatch):
    monkeypatch.setattr(apikeys, 'get', lambda name: None)
    md = tmp_path / 'monthly-2026-10'
    md.mkdir()
    old = {'search': {'hotels in al barsha': {'keyword': 'hotels in al barsha', 'checked': str(date.today()),
                                              'position': 14, 'map_pack': {'shown': False}}}, 'maps': {}}
    (md / 'serp.json').write_text(json.dumps(old), encoding='utf-8')      # saved before composition existed
    cl = _clusters()
    note = km.serp_enrich(cl, tmp_path, SITE, {'name': 'X', 'paths': PREFIX}, 'Dubai', 'United Arab Emirates')
    assert note['reused'] == 0 and note['checked'] == 0 and 'no Serper key' in note['skipped']
    assert not any('serp' in c for c in cl)
    assert km.build_order(cl) == ['type-hotels', 'place-barsha', 'landmark-moe', 'room-family']   # by score


def test_serp_enrich_reuses_monthly_check_with_composition(tmp_path, monkeypatch):
    monkeypatch.setattr(apikeys, 'get', lambda name: (_ for _ in ()).throw(AssertionError('no key lookup needed')))
    r = {'keyword': 'hotels in al barsha', 'checked': str(date.today()), 'position': None,
         'map_pack': {'shown': True, 'hotel_position': 2, 'hotels': []},
         'composition': serp.composition(RIVALS, 'rosehotelsgroup.com', PREFIX)}
    md = tmp_path / 'monthly-2026-10'
    md.mkdir()
    (md / 'serp.json').write_text(json.dumps({'search': {'hotels in al barsha': r}}), encoding='utf-8')
    cl = [c for c in _clusters() if c['id'] in ('type-hotels', 'place-barsha')]
    note = km.serp_enrich(cl, tmp_path, SITE, {'name': 'X', 'paths': PREFIX}, 'Dubai', 'United Arab Emirates')
    assert note['reused'] == 1 and cl[1]['serp']['map_pack'] == {'shown': True, 'hotel_position': 2}
    assert km.build_order(cl) == ['place-barsha', 'type-hotels']


# ---------------------------------------------------------------- monthly: Google last month

def _serp_entry(pos, loc='Dubai,Dubai,United Arab Emirates', gl='ae', hl='en'):
    return {'position': pos, 'location': loc, 'gl': gl, 'hl': hl, 'checked': '2026-10-02',
            'map_pack': {'shown': False}}


def test_last_month_position_only_when_location_matches(tmp_path):
    prev = tmp_path / 'monthly-2026-09'
    prev.mkdir()
    (prev / 'serp.json').write_text(json.dumps({'search': {
        'hotels in al barsha': _serp_entry(8),
        'hotel near moe': _serp_entry(12, loc='Abu Dhabi,Abu Dhabi,United Arab Emirates'),
        'family hotel dubai': dict(_serp_entry(5), device='mobile')}}), encoding='utf-8')
    sq = {'hotels in al barsha': _serp_entry(6), 'hotel near moe': _serp_entry(9), 'family hotel dubai': _serp_entry(4),
          'new keyword': _serp_entry(3)}
    got = monthly._serp_last_month({'hotel_dir': tmp_path}, '2026-10', sq)
    assert set(got) == {'hotels in al barsha'} and got['hotels in al barsha']['position'] == 8
    assert monthly._serp_last_month({'hotel_dir': tmp_path}, '2026-12', sq) == {}       # no file


def test_last_month_wraps_january(tmp_path):
    prev = tmp_path / 'monthly-2025-12'
    prev.mkdir()
    (prev / 'serp.json').write_text(json.dumps({'search': {'k': _serp_entry(2)}}), encoding='utf-8')
    assert monthly._serp_last_month({'hotel_dir': tmp_path}, '2026-01', {'k': _serp_entry(3)})['k']['position'] == 2


def test_monthly_table_has_google_last_month_column(tmp_path, monkeypatch):
    monkeypatch.setenv('HOTEL_SEO_HOME', str(tmp_path))
    group.save('example-hotels.com', {'name': 'Example Group', 'site': 'https://example-hotels.com/'},
               [{'slug': 'park', 'name': 'Example Park Hotel', 'paths': ['/'], 'city': 'Dubai',
                 'gsc_property': 'sc-domain:example-hotels.com', 'ga4_property': 'properties/1'}])
    root = tmp_path / 'example-hotels.com'
    md = root / 'monthly-2026-10'
    md.mkdir(parents=True)
    q = {'hotels in al barsha': [3, 120, 14.2], 'hotel near moe': [1, 40, 22.0]}
    data = {'hotel': 'Example Park Hotel', 'month': '2026-10', 'brand_terms': ['example park'],
            'periods': {'current': ['2026-10-01', '2026-10-31'], 'previous': ['2026-09-01', '2026-09-30'],
                        'last_year': ['2025-10-01', '2025-10-31']},
            'gsc': {'status': 'ok', 'current': {'queries': q}, 'previous': {'queries': q}, 'last_year': {}},
            'ga4': {'status': 'not available'}, 'mirai': {'status': 'not available'},
            'parity': {'status': 'not available'}, 'index': {'status': 'not available'},
            'work': {'items': [], 'build_plan_steps': []},
            'tracked': {'confirmed': True, 'keywords': [{'keyword': 'hotels in al barsha', 'type': 'discovery'},
                                                        {'keyword': 'hotel near moe', 'type': 'discovery'}]}}
    (md / 'data.json').write_text(json.dumps(data), encoding='utf-8')
    (md / 'serp.json').write_text(json.dumps({'search': {'hotels in al barsha': _serp_entry(6),
                                                         'hotel near moe': _serp_entry(9)}}), encoding='utf-8')
    prev = root / 'monthly-2026-09'
    prev.mkdir()
    (prev / 'serp.json').write_text(json.dumps({'search': {
        'hotels in al barsha': _serp_entry(8),
        'hotel near moe': _serp_entry(12, loc='Sharjah,Sharjah,United Arab Emirates')}}), encoding='utf-8')
    monthly.build('example-hotels.com', 'park', '2026-10')
    doc = json.loads((md / 'monthly-report.json').read_text(encoding='utf-8'))
    tables = [c['table'] for p in doc['monthly']['pages'] for c in p['components']
              if isinstance(c, dict) and 'table' in c and 'Google last month' in c['table']['columns']]
    assert len(tables) == 1
    t = tables[0]
    i = t['columns'].index('Google last month')
    assert len(t['align']) == len(t['columns'])
    rows = {r[0]: r for r in t['rows']}
    assert rows['hotels in al barsha'][i]['text'] == '8'
    assert rows['hotel near moe'][i]['text'] == '–'                 # other location: not compared
