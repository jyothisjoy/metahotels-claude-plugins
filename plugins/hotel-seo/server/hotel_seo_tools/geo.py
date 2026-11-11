"""Free map data for seo-maps and the keyword candidates: geocoding and places near a hotel.

- Nominatim (OpenStreetMap) geocoding: 1 request per second, named User-Agent (their usage policy).
- Overpass (OpenStreetMap) for places in a radius: hotels (competitors), airports, metro / rail stations, malls,
  beaches, attractions, convention / exhibition centres, stadiums, hospitals, universities.
- Geoapify Places (free tier) adds named points of interest when its key is set (apikeys 'geoapify'). The key is
  added here, server-side, and is never returned.
Results are cached in ~/.metahotels-seo/cache/geo for 30 days, so repeated runs don't hit the services again.
"""
import hashlib
import json
import math
import time

import requests

from . import apikeys, paths

UA = 'hotel-seo/0.9 (MetaHotels SEO audits; contact: metahotels.m@gmail.com)'
CACHE = paths.HOME / 'cache' / 'geo'
CACHE_DAYS = 30
OVERPASS = ['https://overpass-api.de/api/interpreter', 'https://overpass.kumi.systems/api/interpreter',
            'https://overpass.private.coffee/api/interpreter']
_last_nominatim = [0.0]

# kind -> Overpass filters (node/way/relation with these tags)
KINDS = {
    'hotel': ['["tourism"="hotel"]', '["tourism"="apartment"]', '["tourism"="guest_house"]', '["tourism"="hostel"]'],
    'airport': ['["aeroway"="aerodrome"]["iata"]'],
    'metro_station': ['["railway"="station"]["station"="subway"]', '["public_transport"="station"]["subway"="yes"]',
                      '["railway"="station"]'],
    'mall': ['["shop"="mall"]'],
    'beach': ['["natural"="beach"]'],
    'attraction': ['["tourism"="attraction"]', '["tourism"="theme_park"]', '["tourism"="museum"]',
                   '["tourism"="zoo"]', '["leisure"="water_park"]'],
    'venue': ['["amenity"="conference_centre"]', '["amenity"="exhibition_centre"]', '["building"="convention_centre"]',
              '["leisure"="stadium"]'],
    'hospital': ['["amenity"="hospital"]'],
    'university': ['["amenity"="university"]'],
    'marina': ['["leisure"="marina"]'],
}
GEOAPIFY_CATEGORIES = {
    'hotel': 'accommodation.hotel,accommodation.apartment',
    'airport': 'airport',
    'metro_station': 'public_transport.subway,public_transport.train',
    'mall': 'commercial.shopping_mall',
    'beach': 'beach',
    'attraction': 'tourism.attraction,tourism.sights,entertainment.theme_park,entertainment.museum,entertainment.zoo',
    'venue': 'building.public_and_civil,sport.stadium',
    'hospital': 'healthcare.hospital',
    'university': 'education.university',
    'marina': 'leisure.park',
}


def _cache(key):
    CACHE.mkdir(parents=True, exist_ok=True)
    return CACHE / (hashlib.sha1(key.encode()).hexdigest() + '.json')


def _cached(key):
    f = _cache(key)
    if f.exists() and time.time() - f.stat().st_mtime < CACHE_DAYS * 86400:
        try:
            return json.loads(f.read_text(encoding='utf-8'))
        except ValueError:
            return None
    return None


def _store(key, value):
    _cache(key).write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    return value


def distance_m(lat1, lon1, lat2, lon2):
    r = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return round(2 * r * math.asin(math.sqrt(a)))


def geocode(query):
    """Address or place name -> best match {lat, lon, display_name, type, address{...}}; {} if nothing found."""
    q = (query or '').strip()
    if not q:
        return {'found': False, 'reason': 'empty query'}
    key = 'geocode:en:' + q.lower()
    hit = _cached(key)
    if hit is not None:
        return hit
    wait = 1.1 - (time.time() - _last_nominatim[0])
    if wait > 0:
        time.sleep(wait)
    r = requests.get('https://nominatim.openstreetmap.org/search',
                     params={'q': q, 'format': 'jsonv2', 'addressdetails': 1, 'limit': 1, 'accept-language': 'en'},
                     headers={'User-Agent': UA}, timeout=30)
    _last_nominatim[0] = time.time()
    r.raise_for_status()
    rows = r.json()
    if not rows:
        return _store(key, {'found': False, 'query': q})
    x = rows[0]
    return _store(key, {'found': True, 'query': q, 'lat': float(x['lat']), 'lon': float(x['lon']),
                        'display_name': x.get('display_name'), 'type': x.get('type'),
                        'address': x.get('address', {}), 'source': 'OpenStreetMap Nominatim'})


FILTER_PART = __import__('re').compile(r'\["([^"]+)"(?:="([^"]+)")?\]')


def _matches(tags, flt):
    for k, v in FILTER_PART.findall(flt):
        if k not in tags or (v and tags.get(k) != v):
            return False
    return True


def _overpass_all(lat, lon, radius_m, kinds):
    """One Overpass request for every kind (airports within max(radius, 40 km)); classified by tags afterwards."""
    parts = []
    for kind in kinds:
        rad = max(radius_m, 40000) if kind == 'airport' else radius_m
        for f in KINDS[kind]:
            for el in ('node', 'way', 'relation'):
                parts.append(f'{el}{f}(around:{int(rad)},{lat},{lon});')
    q = f'[out:json][timeout:90];({"".join(parts)});out center tags;'
    last = None
    for attempt in range(len(OVERPASS) * 2):
        url = OVERPASS[attempt % len(OVERPASS)]
        try:
            r = requests.post(url, data={'data': q}, headers={'User-Agent': UA}, timeout=120)
        except requests.RequestException as e:
            last = e
            continue
        if r.status_code in (429, 502, 503, 504):
            last = requests.HTTPError(f'{r.status_code} from {url}')
            time.sleep(5)
            continue
        r.raise_for_status()
        out = {k: [] for k in kinds}
        for e in r.json().get('elements', []):
            t = e.get('tags', {})
            name = t.get('name:en') or t.get('name')
            la = e.get('lat') or (e.get('center') or {}).get('lat')
            lo = e.get('lon') or (e.get('center') or {}).get('lon')
            if not name or la is None:
                continue
            kind = next((k for k in kinds if any(_matches(t, f) for f in KINDS[k])), None)
            if not kind:
                continue
            d = distance_m(lat, lon, la, lo)
            if kind != 'airport' and d > radius_m:
                continue
            out[kind].append({'name': name, 'name_local': t.get('name') if t.get('name') != name else '',
                              'kind': kind, 'lat': la, 'lon': lo, 'distance_m': d, 'stars': t.get('stars', ''),
                              'website': t.get('website') or t.get('contact:website') or '',
                              'iata': t.get('iata', ''), 'source': 'OpenStreetMap'})
        return out
    raise last or requests.HTTPError('Overpass unavailable')


def _geoapify(lat, lon, radius_m, kind, key):
    r = requests.get('https://api.geoapify.com/v2/places',
                     params={'categories': GEOAPIFY_CATEGORIES[kind], 'filter': f'circle:{lon},{lat},{int(radius_m)}',
                             'bias': f'proximity:{lon},{lat}', 'limit': 500, 'apiKey': key}, timeout=60)
    if r.status_code != 200:
        return []
    out = []
    for f in r.json().get('features', []):
        pr = f.get('properties', {})
        if not pr.get('name'):
            continue
        out.append({'name': pr['name'], 'name_local': '', 'kind': kind, 'lat': pr.get('lat'), 'lon': pr.get('lon'),
                    'distance_m': pr.get('distance') or distance_m(lat, lon, pr.get('lat'), pr.get('lon')),
                    'stars': '', 'website': pr.get('website', ''), 'iata': '', 'source': 'Geoapify'})
    return out


def nearby(lat, lon, radius_m=5000, kinds=None):
    """Places of each kind within radius_m of (lat, lon), nearest first, de-duplicated by name.
    The airport search always uses at least 40 km, since airports are rarely within 5 km."""
    kinds = [k for k in (kinds or list(KINDS)) if k in KINDS]
    key = f'nearby:{round(lat, 4)}:{round(lon, 4)}:{int(radius_m)}:{",".join(sorted(kinds))}'
    hit = _cached(key)
    if hit is not None:
        return hit
    gkey = apikeys.get('geoapify')
    result, errors = {k: [] for k in kinds}, {}
    try:
        osm = _overpass_all(lat, lon, radius_m, kinds)
    except requests.RequestException as e:
        osm = {}
        errors['overpass'] = f'{type(e).__name__}: {str(e)[:150]}'
    for kind in kinds:
        rows = list(osm.get(kind, []))
        if gkey:
            rad = max(radius_m, 40000) if kind == 'airport' else radius_m
            try:
                rows += _geoapify(lat, lon, rad, kind, gkey)
            except requests.RequestException as e:
                errors[f'geoapify:{kind}'] = f'{type(e).__name__}: {str(e)[:150]}'
        seen, uniq = set(), []
        for x in sorted(rows, key=lambda x: x['distance_m']):
            k = x['name'].strip().lower()
            if k in seen:
                continue
            seen.add(k)
            uniq.append(x)
        result[kind] = uniq
    out = {'center': {'lat': lat, 'lon': lon}, 'radius_m': radius_m, 'sources': ['OpenStreetMap Overpass'] +
           (['Geoapify'] if gkey else []), 'counts': {k: len(v) for k, v in result.items()}, 'places': result}
    if errors:
        out['errors'] = errors
        return out                          # don't cache partial results
    return _store(key, out)
