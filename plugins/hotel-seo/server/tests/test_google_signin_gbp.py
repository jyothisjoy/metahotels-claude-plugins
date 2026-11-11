"""Google sign-in asks for every permission by default; Business Profile API check and hotel linking."""
import json

import pytest

from hotel_seo_tools import gbp, google_auth, paths


def test_signin_asks_for_everything_by_default():
    s = google_auth.scopes()
    assert gbp.GBP_SCOPE in s and google_auth.ADS_SCOPE in s and paths.GSC_SCOPE in s
    assert gbp.GBP_SCOPE not in google_auth.scopes(no_gbp=True)
    assert google_auth.ADS_SCOPE not in google_auth.scopes(no_ads=True)


def test_unticked_permissions_are_named():
    asked = google_auth.scopes()
    granted = [x for x in asked if x != gbp.GBP_SCOPE]
    assert google_auth.missing(asked, granted) == ['Google Business Profile']
    assert google_auth.missing(asked, asked) == []


def test_api_check_names_a_disabled_api(monkeypatch):
    monkeypatch.setattr(gbp, 'configured', lambda: (True, ''))
    monkeypatch.setattr(gbp, '_accounts', lambda: [{'name': 'accounts/1'}])

    def fake_get(url, params=None):
        if 'mybusinesslodging' in url:
            raise gbp.GbpError('403 from mybusinesslodging.googleapis.com: SERVICE_DISABLED Enable the My Business '
                               'Lodging API: https://console.cloud.google.com/apis/library/mybusinesslodging.googleapis.com')
        if url.endswith('/locations'):
            return {'locations': [{'name': 'locations/42', 'title': 'Royal M'}]}
        return {}
    monkeypatch.setattr(gbp, '_get', fake_get)
    r = gbp.api_check()
    assert r['checked'] and not r['all_ok'] and r['tried_on'] == 'locations/42'
    assert r['apis']['My Business Lodging API'].startswith('not working: 403')
    assert r['apis']['Business Profile Performance API'] == 'ok'
    assert r['apis']['My Business Business Information API'] == 'ok'


def test_api_check_404_counts_as_working(monkeypatch):
    monkeypatch.setattr(gbp, 'configured', lambda: (True, ''))
    monkeypatch.setattr(gbp, '_accounts', lambda: [{'name': 'accounts/1'}])

    def fake_get(url, params=None):
        if 'mybusinesslodging' in url:
            raise gbp.GbpError('404 from mybusinesslodging.googleapis.com: not found')
        return {'locations': [{'name': 'locations/42'}]} if url.endswith('/locations') else {}
    monkeypatch.setattr(gbp, '_get', fake_get)
    assert gbp.api_check()['all_ok']


def test_link_hotel_saves_and_resolves(tmp_path, monkeypatch):
    hdir = tmp_path / 'royalm.com'
    hdir.mkdir()
    (hdir / 'hotel.json').write_text(json.dumps({'preferences': {'units': 'sqm'}}), encoding='utf-8')
    from hotel_seo_tools import group as grp
    monkeypatch.setattr(grp, 'hotel_dir', lambda group_dir, slug, reg=None: hdir)
    monkeypatch.setattr(gbp, '_find', lambda loc: ('accounts/1', {'name': 'locations/42', 'title': 'Royal M',
                                                                 'websiteUri': 'https://royalm.com/'}))
    r = gbp.link_hotel('royalm.com', 'royal-m', 'royalm.com')
    assert r['location'] == 'locations/42' and r['account'] == 'accounts/1'
    saved = json.loads((hdir / 'hotel.json').read_text(encoding='utf-8'))
    assert saved['preferences'] == {'units': 'sqm'} and saved['gbp']['title'] == 'Royal M'
    assert gbp.resolve_hotel('royalm.com', 'royal-m') == 'locations/42'
    assert gbp.resolve_hotel('royalm.com', 'royal-m', 'locations/7') == 'locations/7'


def test_unlinked_hotel_says_how_to_link(tmp_path, monkeypatch):
    from hotel_seo_tools import group as grp
    monkeypatch.setattr(grp, 'hotel_dir', lambda group_dir, slug, reg=None: tmp_path)
    with pytest.raises(gbp.GbpError, match='gbp_link'):
        gbp.resolve_hotel('x.com', 'x')
