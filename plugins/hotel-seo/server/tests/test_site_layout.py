"""Single-hotel sites keep everything in <domain>/; groups use group/ and hotels/<slug>/."""
import json

import pytest

from hotel_seo_tools import group, monthly, report


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv('HOTEL_SEO_HOME', str(tmp_path))
    return tmp_path


def test_single_hotel_is_flat(home):
    reg = group.save('abarhotels.com', {'name': 'Abar Hotel Apartments', 'site': 'https://abarhotels.com/'},
                     [{'slug': 'abar', 'name': 'Abar Hotel Apartments', 'paths': ['/']}])
    d = home / 'abarhotels.com'
    assert reg['type'] == 'single'
    assert (d / 'site.json').exists()
    assert not (d / 'hotels').exists() and not (d / 'group').exists()
    assert group.hotel_dir('abarhotels.com', 'abar') == d
    assert group.site_dir('abarhotels.com') == d
    assert report.build_group('abarhotels.com')['skipped'] is True
    assert monthly.build_group('abarhotels.com', '2026-09')['skipped'] is True


def test_group_gets_hotel_and_group_folders(home):
    reg = group.save('rosehotelsgroup.com', {'name': 'Rose Hotels Group', 'site': 'https://rosehotelsgroup.com/'},
                     [{'slug': 'rose-park', 'name': 'Rose Park', 'paths': ['/hotels/rose-park/']},
                      {'slug': 'rose-plaza', 'name': 'Rose Plaza', 'paths': ['/hotels/rose-plaza/']}])
    d = home / 'rosehotelsgroup.com'
    assert reg['type'] == 'group'
    assert (d / 'hotels' / 'rose-park').is_dir() and (d / 'hotels' / 'rose-plaza').is_dir()
    assert group.hotel_dir('rosehotelsgroup.com', 'rose-park') == d / 'hotels' / 'rose-park'
    assert group.site_dir('rosehotelsgroup.com') == d / 'group'


def test_group_hotel_cannot_cover_the_whole_site(home):
    with pytest.raises(ValueError):
        group.save('x.com', {'site': 'https://x.com/'}, [{'slug': 'a', 'paths': ['/']}, {'slug': 'b', 'paths': ['/b/']}])


def test_old_group_json_is_still_read(home):
    d = home / 'abarhotels.com'
    d.mkdir()
    (d / 'group.json').write_text(json.dumps({'group': {'site': 'https://abarhotels.com'},
                                              'hotels': [{'slug': 'abarhotels', 'name': 'Abar', 'paths': ['/']}]}))
    reg = group.load('abarhotels.com')
    assert reg['type'] == 'single'
    assert group.hotel_dir('abarhotels.com', 'abarhotels') == d
