"""Monthly report: periods, change lines, brand matching, Serper parsing, narrative number check."""
import json
from datetime import date

import pytest

from hotel_seo_tools import group, monthly, serp


def test_periods_regular_and_january():
    p = monthly.periods('2026-10')
    assert p['current'] == (date(2026, 10, 1), date(2026, 10, 31))
    assert p['previous'] == (date(2026, 9, 1), date(2026, 9, 30))
    assert p['last_year'] == (date(2025, 10, 1), date(2025, 10, 31))
    j = monthly.periods('2026-01')
    assert j['previous'] == (date(2025, 12, 1), date(2025, 12, 31))
    assert monthly.periods('2028-02')['current'][1] == date(2028, 2, 29)


def test_periods_rejects_bad_month():
    for bad in ('2026-13', '2026-1', 'oct'):
        with pytest.raises(ValueError):
            monthly.periods(bad)


def test_default_month_and_provisional():
    assert monthly.default_month(date(2026, 11, 2)) == '2026-10'
    assert monthly.default_month(date(2026, 1, 15)) == '2025-12'
    assert monthly.provisional('2026-10', date(2026, 11, 2)) is True
    assert monthly.provisional('2026-10', date(2026, 11, 4)) is False


def test_next_month_wraps():
    assert monthly._next_month('2026-12') == '2027-01'
    assert monthly._next_month('2026-09') == '2026-10'


def test_change_percent_only_with_a_real_base():
    assert monthly.change(832, 320)['text'] == '▲ +160% (from 320)'
    assert monthly.change(12, 3)['text'] == '▲ +9 (from 3)'          # not +300%
    assert monthly.change(78, 103)['dir'] == 'down'
    assert monthly.change(5, None)['text'] == 'no earlier data'
    assert monthly.change(4, 4)['dir'] == 'flat'


def test_position_and_points():
    assert monthly._chg_pos(6.4, 8.1) == {'change': '▲ up from 8.1', 'dir': 'up'}
    assert monthly._chg_pos(9.0, 6.4)['dir'] == 'down'
    assert monthly._chg_points(60.9, 72.3)['change'] == '▼ −11.4 points (from 72.3%)'


def test_brand_includes_one_letter_misspellings():
    terms = ['abar', 'abar hotel apartments']
    assert monthly.is_brand('abar hotel', terms)
    assert monthly.is_brand('abrar hotel apartments', terms)
    assert not monthly.is_brand('hotel apartments in dip', terms)
    assert not monthly.is_brand('aarp family apartments', terms)


def _fake_serp(pages):
    def post(endpoint, body):
        return pages[body.get('page', 1) - 1] if endpoint == 'search' else {'places': []}
    return post


def test_serp_rank_finds_hotel_page_and_map_pack(monkeypatch):
    p1 = {'organic': [{'title': f'Other {i}', 'link': f'https://other{i}.com/'} for i in range(1, 11)],
          'places': [{'title': 'Some Hotel'}, {'title': 'Rose Park Hotel Al Barsha'}]}
    p2 = {'organic': [{'title': 'Group home', 'link': 'https://rosehotelsgroup.com/'},
                      {'title': 'Rose Park', 'link': 'https://rosehotelsgroup.com/hotels-apartments/rose-park-albarsha/'}]
          + [{'title': 'x', 'link': f'https://x{i}.com/'} for i in range(8)]}
    monkeypatch.setattr(serp, '_post', _fake_serp([p1, p2]))
    r = serp.rank('hotel near mall of the emirates', 'https://rosehotelsgroup.com/',
                  ['/hotels-apartments/rose-park-albarsha/'], 'Rose Park Al Barsha', 'Dubai')
    assert r['position'] == 12
    assert r['url'].endswith('/rose-park-albarsha/')
    assert r['map_pack'] == {'shown': True, 'hotel_position': 2, 'hotels': ['Some Hotel', 'Rose Park Hotel Al Barsha']}
    assert r['credits'] == 2
    assert r['location'] == 'Dubai,Dubai,United Arab Emirates' and r['gl'] == 'ae'


def test_serp_rank_not_found_reports_other_group_page(monkeypatch):
    page = {'organic': [{'title': 'Group', 'link': 'https://rosehotelsgroup.com/offers/'}] +
            [{'title': 'x', 'link': f'https://x{i}.com/'} for i in range(9)]}
    monkeypatch.setattr(serp, '_post', _fake_serp([page, page, page]))
    r = serp.rank('hotels in barsha', 'https://rosehotelsgroup.com/', ['/hotels-apartments/rose-park-albarsha/'],
                  'Rose Park Al Barsha', 'Dubai')
    assert r['position'] is None and r['checked_to'] == 30 and r['credits'] == 3
    assert r['other_site_page']['url'] == 'https://rosehotelsgroup.com/offers/'


@pytest.fixture
def hotel(tmp_path, monkeypatch):
    monkeypatch.setenv('HOTEL_SEO_HOME', str(tmp_path))
    group.save('example-hotels.com', {'name': 'Example Group', 'site': 'https://example-hotels.com/'},
               [{'slug': 'park', 'name': 'Example Park Hotel', 'paths': ['/'], 'city': 'Dubai',
                 'gsc_property': 'sc-domain:example-hotels.com', 'ga4_property': 'properties/1'}])
    md = tmp_path / 'example-hotels.com' / 'monthly-2026-09'          # single hotel: flat layout
    md.mkdir(parents=True)
    data = {'hotel': 'Example Park Hotel', 'month': '2026-09', 'brand_terms': ['example park'],
            'periods': {'current': ['2026-09-01', '2026-09-30'], 'previous': ['2026-08-01', '2026-08-31'],
                        'last_year': ['2025-09-01', '2025-09-30']},
            'gsc': {'status': 'not available: test'},
            'ga4': {'status': 'ok', 'current': {'organic': {'sessions': 832}, 'all': {'sessions': 3500},
                                                'ai': {'sessions': 46, 'by_assistant': []}},
                    'previous': {'organic': {'sessions': 320}, 'all': {'sessions': 1200},
                                 'ai': {'sessions': 16, 'by_assistant': []}},
                    'last_year': {'organic': {'sessions': None}, 'all': {'sessions': None}, 'ai': {'sessions': None}}},
            'mirai': {'status': 'not available'}, 'parity': {'status': 'not available'},
            'index': {'status': 'not available'}, 'work': {'items': [], 'build_plan_steps': []},
            'tracked': {'keywords': []}}
    (md / 'data.json').write_text(json.dumps(data), encoding='utf-8')
    return tmp_path


def test_narrative_numbers_must_come_from_data(hotel):
    ok = monkey_save({'headline': 'Google visits rose to 832 from 320, +160%.'})
    assert ok['saved'] is True, ok
    bad = monkey_save({'headline': 'Google visits rose to 950.'})
    assert bad['saved'] is False
    assert bad['numbers_not_in_data'][0]['number'] == '950'
    assert monkey_save({'unknown': 'x'})['saved'] is False


def monkey_save(n):
    return monthly.save_narrative('example-hotels.com', 'park', '2026-09', n)


def test_build_shows_dashes_not_zeros_without_data(hotel):
    r = monthly.build('example-hotels.com', 'park', '2026-09')
    doc = json.loads(open(r['file'], encoding='utf-8').read())
    yoy = next(c for p in doc['monthly']['pages'] for c in p['components']
               if c.get('title', '').startswith('This month'))
    visits = next(row for row in yoy['table']['rows'] if row[0] == 'Visits from Google')
    assert visits == ['Visits from Google', '832', '320', '–']
    assert doc['title'] == 'Monthly Report' and doc['date'] == 'Sep 2026'
    assert any('not checked' in m for m in r['not_available'])
