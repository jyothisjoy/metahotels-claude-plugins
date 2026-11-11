"""Exact Google positions for the monthly report's tracked keywords, through Serper (google.serper.dev).

Key: SERPER_API in the work folder's .env (apikeys 'serper'); never returned by any tool.
Search Console gives average positions for searches where the hotel already appeared; this adds the position on
one fixed day from the hotel's city, the page that ranks, who ranks above, and the map pack.
Each results page (10 results) costs one Serper credit; positions are checked to the top 30 (3 pages) and the
search stops as soon as the hotel's page is found.
"""
import json
import re
import time
from datetime import date
from urllib.parse import urlparse

import requests

from . import apikeys, paths

BASE = 'https://google.serper.dev/'
PAGES = 3                   # top 30
COUNTRY = {'united arab emirates': 'ae', 'uae': 'ae', 'egypt': 'eg', 'saudi arabia': 'sa', 'qatar': 'qa',
           'oman': 'om', 'bahrain': 'bh', 'kuwait': 'kw', 'jordan': 'jo', 'lebanon': 'lb'}
EMIRATES = {'dubai': 'Dubai', 'abu dhabi': 'Abu Dhabi', 'sharjah': 'Sharjah', 'ajman': 'Ajman',
            'fujairah': 'Fujairah', 'ras al khaimah': 'Ras Al Khaimah', 'umm al quwain': 'Umm Al Quwain',
            'al ain': 'Abu Dhabi'}


def _post(endpoint, body):
    key = apikeys.get('serper')
    if not key:
        raise RuntimeError('no Serper key: add SERPER_API=... to the work folder .env')
    for attempt in range(3):
        r = requests.post(BASE + endpoint, headers={'X-API-KEY': key, 'Content-Type': 'application/json'},
                          data=json.dumps(body), timeout=60)
        if r.status_code == 429 and attempt < 2:
            time.sleep(3 * (attempt + 1))
            continue
        if r.status_code != 200:
            raise RuntimeError(f'Serper {r.status_code}: {r.text[:200]}')
        return r.json()


def location(city, country='United Arab Emirates'):
    """Serper's location string, e.g. "Dubai,Dubai,United Arab Emirates"."""
    c = (city or '').strip()
    if not c:
        return country
    region = EMIRATES.get(c.lower(), c) if (country or '').lower() in ('united arab emirates', 'uae') else c
    return f'{c},{region},{country}'


def gl_for(country):
    return COUNTRY.get((country or '').lower(), 'ae')


def _host(u):
    return urlparse(u or '').netloc.lower().replace('www.', '')


def _ours(link, host, prefixes):
    if _host(link) != host:
        return False
    if not prefixes or prefixes == ['/']:
        return True
    path = urlparse(link).path or '/'
    return any(path.startswith(p) for p in prefixes)


def _name_match(title, hotel_name):
    words = [w for w in re.findall(r'[a-z0-9]+', (hotel_name or '').lower())
             if w not in {'hotel', 'hotels', 'the', 'and', 'by', 'apartments', 'apartment', 'resort', 'suites'}]
    t = (title or '').lower()
    return bool(words) and all(w in t for w in words)


def rank(keyword, site, prefixes, hotel_name, city, country='United Arab Emirates', hl='en', pages=PAGES):
    """One keyword: position of the hotel's page (or None in the top `pages`*10), the URL, results above it,
    another page of the same site that ranks instead (group sites), and the map pack."""
    host = _host(site)
    loc, gl = location(city, country), gl_for(country)
    seen, credits, map_pack, other_page = [], 0, None, None
    hit = None
    for page in range(1, pages + 1):
        data = _post('search', {'q': keyword, 'gl': gl, 'hl': hl, 'location': loc, 'page': page})
        credits += 1
        if page == 1:
            places = data.get('places') or []
            if places:
                pos = next((i for i, p in enumerate(places, 1) if _name_match(p.get('title'), hotel_name)), None)
                map_pack = {'shown': True, 'hotel_position': pos, 'hotels': [p.get('title') for p in places]}
            else:
                map_pack = {'shown': False}
        organic = data.get('organic') or []
        for i, o in enumerate(organic, 1):
            absolute = len(seen) + 1
            link = o.get('link', '')
            seen.append({'position': absolute, 'title': o.get('title', ''), 'link': link})
            if _ours(link, host, prefixes):
                hit = {'position': absolute, 'url': link}
                break
            if other_page is None and _host(link) == host:
                other_page = {'position': absolute, 'url': link}
        if hit or len(organic) < 8:
            break
    above = [s for s in seen if hit and s['position'] < hit['position']][:3] if hit else seen[:3]
    return {'keyword': keyword, 'checked': str(date.today()), 'location': loc, 'gl': gl, 'hl': hl,
            'position': hit['position'] if hit else None, 'url': hit['url'] if hit else '',
            'checked_to': len(seen), 'above': [{'position': a['position'], 'title': a['title'],
                                                'domain': _host(a['link'])} for a in above],
            'other_site_page': other_page if not hit else None, 'map_pack': map_pack, 'credits': credits}


def maps_rank(keyword, lat, lng, hotel_name, hl='en', zoom=14):
    """Position of the hotel in Google Maps results for the keyword, searched from the hotel's own area."""
    data = _post('maps', {'q': keyword, 'll': f'@{lat},{lng},{zoom}z', 'hl': hl})
    places = data.get('places') or []
    pos = next((i for i, p in enumerate(places, 1) if _name_match(p.get('title'), hotel_name)), None)
    return {'keyword': keyword, 'from': f'{lat},{lng} (hotel area)', 'position': pos, 'results': len(places),
            'top': [{'position': i, 'title': p.get('title'), 'rating': p.get('rating'),
                     'reviews': p.get('ratingCount')} for i, p in enumerate(places[:5], 1)], 'credits': 1}


def estimate(keywords, maps_keywords=()):
    """Most credits a run can use (stops early when the hotel is found)."""
    return len(keywords) * PAGES + len(maps_keywords)


def run(out_file, keywords, site, prefixes, hotel_name, city, country='United Arab Emirates', latlng=None,
        maps_keywords=(), progress=None):
    """Check every tracked keyword (cached in out_file: a re-run only checks what is missing)."""
    out_file = paths.resolve(out_file)
    done = json.loads(out_file.read_text(encoding='utf-8')) if out_file.exists() else {'search': {}, 'maps': {}}
    errors = []
    for n, kw in enumerate(keywords, 1):
        if kw in done['search']:
            continue
        try:
            done['search'][kw] = rank(kw, site, prefixes, hotel_name, city, country)
        except RuntimeError as e:
            errors.append(f'{kw}: {e}')
            if 'no Serper key' in str(e) or ' 401' in str(e) or ' 403' in str(e):
                break
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(json.dumps(done, indent=1, ensure_ascii=False), encoding='utf-8')
        if progress:
            progress(f'{n}/{len(keywords)} keywords')
    if latlng:
        for kw in maps_keywords:
            if kw in done['maps'] or errors:
                continue
            try:
                done['maps'][kw] = maps_rank(kw, latlng[0], latlng[1], hotel_name)
            except RuntimeError as e:
                errors.append(f'maps {kw}: {e}')
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(done, indent=1, ensure_ascii=False), encoding='utf-8')
    used = sum(v.get('credits', 0) for v in done['search'].values()) + sum(v.get('credits', 0)
                                                                           for v in done['maps'].values())
    return {'file': str(out_file), 'checked': len(done['search']), 'maps_checked': len(done['maps']),
            'credits_used_total': used, 'errors': errors[:10]}
