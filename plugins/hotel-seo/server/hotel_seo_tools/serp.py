"""Exact Google positions for the monthly report's tracked keywords, through Serper (google.serper.dev).

Key: SERPER_API in the work folder's .env (apikeys 'serper'); never returned by any tool.
Search Console gives average positions for searches where the hotel already appeared; this adds the position on
one fixed day from the hotel's city, the page that ranks, who ranks above, and the map pack.
Each results page (10 results) costs one Serper credit; positions are checked to the top 30 (3 pages) and the
search stops as soon as the hotel's page is found.

Page 1 of every check is also kept whole, at no extra credit, as `composition`: People Also Ask questions, related
searches, the answer box, the knowledge graph, and a label for each top-10 result (classify_result: booking site,
own hotel, own group, rival hotel, guide, other) with a one-line verdict (mix_verdict). Files saved before
composition existed simply lack the key; readers use .get('composition').
"""
import json
import re
import time
from collections import Counter
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


# ---------------------------------------------------------------- what page 1 is made of

# Booking sites / OTAs and metasearch, by their name before the country ending (expedia.ae, tripadvisor.co.uk).
OTA_NAMES = ('booking', 'expedia', 'agoda', 'trip', 'hotels', 'tripadvisor', 'kayak', 'trivago', 'priceline',
             'hotelscombined', 'momondo', 'skyscanner', 'makemytrip', 'goibibo', 'almosafer', 'tajawal', 'wego',
             'rehlat', 'cleartrip', 'airbnb', 'vrbo', 'hostelworld', 'travelocity', 'orbitz', 'ebookers',
             'lastminute', 'opodo', 'hrs', 'yatra', 'travelstay', 'hotwire', 'ostrovok', 'easemytrip', 'musafir')
# Guides, magazines, news, encyclopedias, forums and social sites.
GUIDE_NAMES = ('timeout', 'timeoutdubai', 'visitdubai', 'visitabudhabi', 'visitsharjah', 'visitrasalkhaimah',
               'lonelyplanet', 'wikipedia', 'wikitravel', 'wikivoyage', 'cntraveler', 'theculturetrip', 'culturetrip',
               'gulfnews', 'khaleejtimes', 'thenationalnews', 'thenational', 'whatson', 'reddit', 'quora', 'youtube',
               'tiktok', 'instagram', 'facebook', 'medium', 'travelandleisure', 'forbes', 'nytimes', 'theguardian',
               'bbc', 'cnn', 'dubaitravelblog', 'condenast', 'telegraph', 'independent', 'fodors', 'frommers',
               'arabianbusiness', 'gulfbusiness', 'zawya', 'emirates247', 'mydubai', 'dubaiofw', 'pinterest')
# Hotel brands and chains that are hotels themselves (their own sites).
HOTEL_BRANDS = ('marriott', 'hilton', 'ihg', 'accor', 'hyatt', 'radissonhotels', 'radisson', 'rotana', 'jumeirah',
                'millenniumhotels', 'wyndhamhotels', 'fourseasons', 'shangri-la', 'kempinski', 'movenpick', 'novotel',
                'ibis', 'sofitel', 'fairmont', 'rovehotels', 'citymaxhotels', 'premierinn', 'addresshotels',
                'vidahotels', 'ramada', 'holidayinn', 'crowneplaza', 'sheraton', 'westin', 'ritzcarlton',
                'mandarinoriental', 'anantara', 'swissotel', 'pullman', 'mercure', 'atlantis', 'oneandonly',
                'fortunegroupofhotels', 'florahospitality', 'bestwestern', 'centarahotelsresorts', 'melia',
                'barcelo', 'nh-hotels', 'raffles', 'banyantree', 'avanihotels', 'hotelindigo', 'staybridge',
                'intercontinental', 'goldentulip', 'louvrehotels', 'hamptoninn', 'doubletree', 'conrad', 'waldorf')
HOTEL_WORDS = re.compile(r'\b(hotels?|resorts?|suites|inn|hostel|motel|residences?|hotel apartments|'
                         r'serviced apartments)\b', re.I)
GUIDE_PATH = re.compile(r'/(blog|blogs|news|guide|guides|article|articles|magazine|things-to-do|travel-guide|'
                        r'stories|story|wiki)(/|$|-)', re.I)
GUIDE_TITLE = re.compile(r'\b(top \d+|\d+ best|best \d+|things to do|guide|where to stay|review of)\b', re.I)
LABELS = ('booking site', 'own hotel', 'own group', 'rival hotel', 'guide', 'other')
BOOKING_HEAVY = 6          # booking sites in the top 10 for "mostly booking sites"
HOTEL_CAN_WIN = 2          # hotel sites (ours or rivals) in the top 10 for "hotel sites can win"
GUIDE_HEAVY = 5            # guides in the top 10 for "mostly guides and articles"


def _named(host, names):
    """True when host is <name>.<country ending> or a sub-domain of it (ae.hotels.com, www.expedia.co.uk)."""
    return any(re.search(rf'(^|\.){re.escape(n)}\.(com|net|org|[a-z]{{2}}|co\.[a-z]{{2}}|com\.[a-z]{{2}})$', host)
               for n in names)


def classify_result(link, title='', host='', prefixes=None, rival_names=()):
    """Label of one search result: 'own hotel' (this hotel's pages), 'own group' (another page of the same site),
    'booking site' (OTA / metasearch, Google Hotels), 'guide' (guide, blog, news, social), 'rival hotel' (another
    hotel's own site: a hotel brand, hotel words in the title or domain, or one of rival_names), else 'other'."""
    h = _host(link)
    path = urlparse(link or '').path or '/'
    t = str(title or '')
    if host and h == host:
        return 'own hotel' if _ours(link, host, prefixes or []) else 'own group'
    if _named(h, OTA_NAMES) or (re.search(r'(^|\.)google\.', h) and path.startswith('/travel')):
        return 'booking site'
    if _named(h, GUIDE_NAMES) or GUIDE_PATH.search(path) or GUIDE_TITLE.search(t):
        return 'guide'
    first = h.split('.')[0] if h else ''
    if (_named(h, HOTEL_BRANDS) or HOTEL_WORDS.search(t) or re.search(r'hotel|resort|suites|inn$', first)
            or any(_name_match(t, n) for n in rival_names if n)):
        return 'rival hotel'
    return 'other'


def mix_verdict(mix):
    """One line on who holds page 1: hotel sites can win / mostly booking sites / mostly guides and articles / mixed."""
    hotels = mix.get('own hotel', 0) + mix.get('own group', 0) + mix.get('rival hotel', 0)
    if hotels >= HOTEL_CAN_WIN:
        return 'hotel sites can win'
    if mix.get('booking site', 0) >= BOOKING_HEAVY:
        return 'mostly booking sites'
    if mix.get('guide', 0) >= GUIDE_HEAVY:
        return 'mostly guides and articles'
    return 'mixed'


def composition(data, host='', prefixes=None, rival_names=()):
    """Page 1 of one Serper search response, whole: top-10 labels and mix, People Also Ask, related searches, answer
    box and knowledge graph. Missing parts are empty / None (Serper only sends what Google showed)."""
    data = data or {}
    top = []
    for i, o in enumerate((data.get('organic') or [])[:10], 1):
        link = o.get('link', '')
        top.append({'position': o.get('position') or i, 'domain': _host(link), 'title': o.get('title', ''),
                    'label': classify_result(link, o.get('title', ''), host, prefixes, rival_names)})
    counts = Counter(t['label'] for t in top)
    mix = {k: counts.get(k, 0) for k in LABELS}
    ab = data.get('answerBox') or None
    kg = data.get('knowledgeGraph') or None
    return {
        'top10': top, 'mix': mix, 'verdict': mix_verdict(mix) if top else None,
        'rival_domains': list(dict.fromkeys(t['domain'] for t in top if t['label'] == 'rival hotel')),
        'paa': [q['question'] for q in data.get('peopleAlsoAsk') or [] if isinstance(q, dict) and q.get('question')],
        'related': [r['query'] for r in data.get('relatedSearches') or [] if isinstance(r, dict) and r.get('query')],
        'answer_box': {'title': ab.get('title', ''), 'text': ab.get('answer') or ab.get('snippet') or '',
                       'domain': _host(ab.get('link'))} if isinstance(ab, dict) else None,
        'knowledge_graph': {'title': kg.get('title', ''), 'type': kg.get('type', ''),
                            'domain': _host(kg.get('website'))} if isinstance(kg, dict) else None,
    }


def _map_pack(data, hotel_name):
    places = data.get('places') or []
    if not places:
        return {'shown': False}
    pos = next((i for i, p in enumerate(places, 1) if _name_match(p.get('title'), hotel_name)), None)
    return {'shown': True, 'hotel_position': pos, 'hotels': [p.get('title') for p in places]}


def rank(keyword, site, prefixes, hotel_name, city, country='United Arab Emirates', hl='en', pages=PAGES,
         rival_names=()):
    """One keyword: position of the hotel's page (or None in the top `pages`*10), the URL, results above it,
    another page of the same site that ranks instead (group sites), the map pack, and page 1's composition."""
    host = _host(site)
    loc, gl = location(city, country), gl_for(country)
    seen, credits, map_pack, other_page, comp = [], 0, None, None, None
    hit = None
    for page in range(1, pages + 1):
        data = _post('search', {'q': keyword, 'gl': gl, 'hl': hl, 'location': loc, 'page': page})
        credits += 1
        if page == 1:
            map_pack = _map_pack(data, hotel_name)
            comp = composition(data, host, prefixes, rival_names)
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
            'other_site_page': other_page if not hit else None, 'map_pack': map_pack, 'composition': comp,
            'credits': credits}


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
