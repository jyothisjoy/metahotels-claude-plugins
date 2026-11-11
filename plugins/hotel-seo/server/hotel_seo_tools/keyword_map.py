"""Non-brand keyword map for one hotel (Search Console for hotels is almost all brand searches).

Steps, all in code (playbook 0c-3):
  A. Candidates from what the hotel is and where it is: places (city, district), property type, star tier, nearby
     landmarks (geo.nearby: airport, metro, malls, beaches, attractions, venues), facilities, room types and
     audiences (from hotel-facts.json: Booking.com, booking engine, sheet). Only facts the hotel has are used.
  B. Expansion: Keyword Planner ideas from the strongest seeds and from competitor hotel URLs; extra keywords
     Claude passes in (seo-flow Find, Arabic versions).
  C. Volumes for every candidate (Keyword Planner, hotel's city + country + feeder markets), brand filter
     (this hotel, group, sister hotels, competitors), relevance gate, score = volume x intent x fit.
  D. Clusters: close variants + shared head modifier; one target page per cluster (existing page by URL / title /
     H1 match, or "missing page"); Search Console (16 months, this hotel's pages) gives the status:
     ranks / shows but low / invisible / no page.
  E. Google page 1 (serp_enrich): earlier checks reused free, then Serper for at most SERP_CLUSTERS "no page" /
     "shows but low" clusters (1 credit each): rival hotels, booking-site share, People Also Ask (c['serp']);
     build_order puts clusters rival hotels rank for ahead of the rest. Seasonal peak from the 12 monthly volumes
     (c['peak']): "publish or refresh by" = peak - LEAD_WEEKS.
Output: <hotel dir>/keywords/keyword-map.json (+ keyword-map-keywords.csv of every keyword kept and
keyword-map-excluded.csv of every search left out, with the reason). Each cluster carries "why": the reasons it
was chosen, in plain words (explain()), used by the Audit Report's keyword chapter.
"""
import calendar
import csv
import json
import re
from collections import defaultdict
from datetime import date, timedelta

from . import geo, group as grp, keywords, paths

TYPE_WORDS = {
    'hotel': ['hotel', 'hotels'],
    'resort': ['resort', 'beach resort'],
    'hotel apartments': ['hotel apartments', 'serviced apartments', 'apartments'],
    'suites': ['suites hotel'],
}
FACILITY_TERMS = {   # Booking.com / site facility text -> search wording
    r'\bprivate beach|beachfront\b': 'with private beach', r'\boutdoor (?:swimming )?pool|\bpool\b': 'with pool',
    r'\bspa\b': 'with spa', r'\bfitness|\bgym\b': 'with gym', r'\bkitchen(?:ette)?\b': 'with kitchen',
    r'\bfree parking|\bparking\b': 'with parking', r'\bairport shuttle|\bairport transfer': 'with airport shuttle',
    r'\bsea view|\bocean view': 'sea view', r'\bfamily rooms?\b': 'family rooms', r'\bkids?\b.*\bclub\b': 'kids club',
    r'\brooftop\b': 'rooftop', r'\bbalcony\b': 'with balcony', r'\bpet[- ]friendly|\bpets allowed': 'pet friendly',
}
ROOM_TERMS = {r'family (?:room|suite)': 'family room', r'suite': 'suite', r'(?:two|2)[- ]bed': '2 bedroom apartment',
              r'(?:three|3)[- ]bed': '3 bedroom apartment', r'(?:one|1)[- ]bed': '1 bedroom apartment',
              r'studio': 'studio apartment', r'connect': 'connecting rooms', r'sea view': 'sea view room'}
AUDIENCES = ['family', 'business', 'luxury', 'cheap', 'budget', 'romantic', 'long stay', 'monthly']
LANDMARK_KINDS = {'airport': 30000, 'metro_station': 1500, 'mall': 3000, 'beach': 3000, 'attraction': 3000,
                  'venue': 4000, 'hospital': 2500, 'university': 3000, 'marina': 3000}
INFO_WORDS = re.compile(r'\b(things to do|what to do|how to|how far|distance|weather|best time|guide|map|history|'
                        r'opening hours|tickets?|entry fee|near me|restaurants? in|places to visit|attractions)\b')
BOOK_WORDS = re.compile(r'\b(hotels?|resorts?|apartments?|suites?|stay|book|booking|deals?|offers?|rooms?|'
                        r'accommodation|inn|lodging|staycation)\b')


GENERIC = set("""hotel hotels resort resorts apartment apartments hotel-apartments serviced suite suites stay stays
booking book booked deals deal offers offer cheap cheapest affordable budget best top rated luxury luxurious premium
near nearby close to in at on with and the a an for of by from me star stars room rooms family families kids children
business couples couple honeymoon romantic long term short monthly weekly daily week month night nights weekend holiday
holidays vacation staycation trip price prices rate rates online official website site new open rent rental furnished
pool pools swimming private beach spa gym fitness parking free breakfast shuttle transfer airport metro station view
sea city centre center kitchen kitchenette balcony rooftop pet friendly dog dogs bedroom bedrooms bed beds studio one two
three 1 2 3 4 5 connecting large big small good great accommodation accommodations lodging inn guest guests house
apart reviews review all inclusive half board things thing do what where how far distance map weather guide visit
visiting places place attractions attraction restaurants restaurant shopping mall malls activities activity
around walking walk minutes km""".split())


def _toks(s):
    return set(re.findall(r'[a-z0-9]+', _norm(s)))


def local_terms(places, nearby, city):
    """Phrases that make a search about THIS hotel's area: its district names and the landmarks near it."""
    terms = {}
    for p in places:
        if p and _norm(p) != _norm(city):
            terms[_norm(p)] = ('place', p)
    for kind, maxd in LANDMARK_KINDS.items():
        for pl in (nearby.get('places', {}).get(kind) or []):
            n = _norm(pl['name'])
            looks_like_hotel = re.search(r'\b(hotel|hotels|resort|suites|apartments|inn|hostel|residence)\b', n)
            if pl['distance_m'] <= maxd and len(n) >= 5 and not _toks(n) <= GENERIC and not looks_like_hotel:
                terms.setdefault(n, ('landmark', pl['name']))
    return terms


def is_relevant(kw, city, terms, brands):
    """Keep a search only when it is about this hotel's area / landmarks, or is a plain stay search in its city that
    names nothing else (no other district, no other hotel brand)."""
    k = _norm(kw)
    if is_brand(k, brands):
        return False
    hit = [t for t in terms if t in k]
    if hit:
        # nothing unexplained may remain: "grand excelsior hotel al barsha" names another hotel
        rest = _toks(k) - GENERIC - _toks(city) - set().union(*(_toks(t) for t in hit))
        return not rest
    rest = _toks(k) - GENERIC - _toks(city)
    return bool(BOOK_WORDS.search(k)) and not rest and bool(_toks(k) & _toks(city))


def classify(kw, terms):
    """(kind, head) for a search: the landmark / area / facility / room / audience / stars it is about."""
    k = _norm(kw)
    for t in sorted(terms, key=len, reverse=True):
        if t in k:
            return terms[t][0], terms[t][1]
    for rx, term in FACILITY_TERMS.items():
        if re.search(rx, k, re.I):
            return 'facility', term
    for rx, term in ROOM_TERMS.items():
        if re.search(rx, k, re.I):
            return 'room', term
    m = re.search(r'\b([1-5])[ -]?star', k)
    if m:
        return 'stars', f'{m.group(1)} star'
    for a in AUDIENCES:
        if re.search(rf'\b{a}\b', k):
            return 'audience', a
    if INFO_WORDS.search(k):
        return 'guide', ' '.join(sorted(_toks(k) - GENERIC))[:40] or 'city guide'
    return 'type', 'hotels in the city'


def _norm(s):
    return re.sub(r'\s+', ' ', re.sub(r'[^\w\s&-]', ' ', str(s or '').lower())).strip()


def _facts(hotel_dir):
    f = paths.resolve(hotel_dir) / 'hotel-facts.json'
    return json.loads(f.read_text(encoding='utf-8')).get('facts', []) if f.exists() else []


def _fact(facts, kind):
    for x in facts:
        if x.get('kind') == kind:
            return x.get('value')
    return None


def brand_terms(hotel, reg, competitor_names=(), exclude=()):
    """Words that make a search a brand search: hotel, group, sister hotels and competitors. Words that are part of
    the hotel's own area or landmark names are never brand words ("Kempinski Hotel Mall of the Emirates" must not
    turn "mall" and "emirates" into a brand)."""
    exclude = set(exclude) | GENERIC
    names = [hotel.get('name', ''), (reg or {}).get('group', {}).get('name', '')]
    names += [h.get('name', '') for h in (reg or {}).get('hotels', [])]
    names += list(competitor_names)
    generic = {'hotel', 'hotels', 'resort', 'resorts', 'apartments', 'apartment', 'suites', 'suite', 'the', 'and',
               'group', 'by', 'dubai', 'sharjah', 'abu', 'dhabi', 'fujairah', 'ajman', 'al', 'el', 'city', 'plaza',
               'park', 'garden', 'grand', 'tower', 'palace', 'beach', 'inn', 'residence', 'residences', 'stay',
               'executive', 'deira', 'barsha', 'bur', 'marina', 'downtown', 'jumeirah', 'cairo', 'luxury', 'royal'}
    out = set()
    for n in names:
        words = [w for w in re.findall(r'[a-z0-9]+', _norm(n)) if len(w) >= 3 and w not in generic and w not in exclude]
        out.update(words)
        joined = ' '.join(re.findall(r'[a-z0-9]+', _norm(n)))
        if joined and len(joined) > 6 and set(joined.split()) - exclude - generic:
            out.add(joined)
        # a hotel name made only of ordinary words ("Studio One Hotel") is still a brand as a whole phrase
        if joined and len(joined.split()) >= 2 and re.search(r'\b(hotel|resort|suites|apartments|inn)\b', joined):
            out.add(re.sub(r'\b(dubai|sharjah|abu dhabi|fujairah|ajman|cairo)\b', '', joined).strip())
    return sorted(out)


def is_brand(q, terms):
    flat = ' ' + _norm(q) + ' '
    return any(f' {t} ' in flat or (len(t) > 6 and t.replace(' ', '') in flat.replace(' ', '')) for t in terms)


def property_types(hotel, facts):
    text = ' '.join([hotel.get('name', ''), str(_fact(facts, 'description') or '')]).lower()
    types = ['hotel']
    if 'resort' in text:
        types.append('resort')
    if re.search(r'apartment|residence|suites', text):
        types.append('hotel apartments')
    return types


def hotel_facilities(facts):
    fac_text = ' '.join(_fact(facts, 'facilities') or []) + ' ' + str(_fact(facts, 'description') or '')
    return sorted({term for rx, term in FACILITY_TERMS.items() if re.search(rx, fac_text, re.I)})


def serves(kw, kind, head, stars, facilities):
    """False when the search asks for something the hotel isn't: another star rating, luxury for a hotel under 5
    stars, budget for a 5-star, or a facility it doesn't have."""
    k = _norm(kw)
    m = re.search(r'\b([1-5])[ -]?star', k)
    if stars and m and int(m.group(1)) != int(stars):
        return False
    if stars and int(stars) < 5 and re.search(r'\bluxury\b', k):
        return False
    if stars and int(stars) >= 5 and re.search(r'\b(cheap|budget|cheapest)\b', k):
        return False
    if kind == 'facility' and facilities and head not in facilities:
        return False
    return True


def candidates(hotel, facts, places, nearby, rooms):
    """Candidate searches with their modifiers. Only what the hotel actually has or where it is."""
    types = property_types(hotel, facts)
    stars = _fact(facts, 'stars')
    fac_text = ' '.join(_fact(facts, 'facilities') or []) + ' ' + str(_fact(facts, 'description') or '')
    facilities = sorted({term for rx, term in FACILITY_TERMS.items() if re.search(rx, fac_text, re.I)})
    room_terms = sorted({term for r in rooms for rx, term in ROOM_TERMS.items() if re.search(rx, r, re.I)})
    out = {}

    def add(phrase, head_kind, head, fit=1.0, page_type='home', **extra):
        p = _norm(phrase)
        if p and p not in out:
            out[p] = {'keyword': p, 'head_kind': head_kind, 'head': head, 'fit': fit, 'page_type': page_type,
                      'source': "built from the hotel's facts and location", **extra}
    for place in places:
        for t in types:
            for w in TYPE_WORDS[t]:
                add(f'{w} in {place}', 'place', place)
                add(f'{place} {w}', 'place', place)
                add(f'best {w} in {place}', 'place', place)
                if stars:
                    add(f'{stars} star {w} {place}', 'stars', f'{stars} star')
                    add(f'{stars} star {w} in {place}', 'stars', f'{stars} star')
                for f in facilities:
                    add(f'{w} {f} {place}' if f.startswith('with') else f'{f} {w} {place}', 'facility', f,
                        page_type='facility')
                for a in AUDIENCES:
                    if a in ('luxury',) and stars and int(stars) < 5:
                        continue
                    if a in ('cheap', 'budget') and stars and int(stars) >= 5:
                        continue
                    add(f'{a} {w} {place}', 'audience', a, page_type='offer' if a in ('monthly', 'long stay') else 'home')
                add(f'{w} deals {place}', 'intent', 'deals', page_type='offer')
        for r in room_terms:
            add(f'{r} {place}', 'room', r, page_type='room')
            add(f'hotel with {r} {place}', 'room', r, page_type='room')
    for kind, maxd in LANDMARK_KINDS.items():
        for pl in (nearby.get('places', {}).get(kind) or []):
            if pl['distance_m'] > maxd:
                continue
            name = _norm(pl['name'])
            if not name or len(name) < 4:
                continue
            fit = round(max(0.3, 1 - pl['distance_m'] / maxd), 2)
            for t in types[:2]:
                for w in TYPE_WORDS[t][:2]:
                    add(f'{w} near {name}', 'landmark', pl['name'], fit, 'location', distance_m=pl['distance_m'],
                        landmark_kind=kind)
                    add(f'{w} close to {name}', 'landmark', pl['name'], fit, 'location', distance_m=pl['distance_m'],
                        landmark_kind=kind)
            add(f'things to do near {name}', 'landmark-info', pl['name'], fit * 0.5, 'blog',
                distance_m=pl['distance_m'], landmark_kind=kind)
    return list(out.values())


def _gsc_rows(prop, start, end, dims, prefixes):
    """Search Console rows (all pages of results) filtered to the hotel's path prefixes."""
    from .analysis import _gsc
    s = _gsc()
    if s is None:
        return None
    import requests
    url = ('https://www.googleapis.com/webmasters/v3/sites/' + requests.utils.quote(prop, safe='') +
           '/searchAnalytics/query')
    rows = []
    # The API only ANDs filters within a group, so each path prefix is its own query (results merged).
    filters = [None] if not prefixes or prefixes == ['/'] else list(prefixes)
    for prefix in filters:
        start_row = 0
        while True:
            body = {'startDate': str(start), 'endDate': str(end), 'dimensions': dims, 'rowLimit': 25000,
                    'startRow': start_row, 'dataState': 'final'}
            if prefix:
                body['dimensionFilterGroups'] = [{'groupType': 'and', 'filters': [
                    {'dimension': 'page', 'operator': 'contains', 'expression': prefix}]}]
            r = s.post(url, json=body, timeout=120)
            if r.status_code != 200:
                raise RuntimeError(f'Search Console {r.status_code}: {r.text[:200]}')
            got = r.json().get('rows', [])
            rows += got
            if len(got) < 25000:
                break
            start_row += 25000
    return rows


def _page_index(crawl_dir, urls):
    """{url: tokens of url path + title + H1} for matching clusters to existing pages."""
    data = json.loads((paths.resolve(crawl_dir) / 'crawl.json').read_text(encoding='utf-8'))
    by = {u['url']: u for u in data.get('urls', [])}
    out = {}
    for u in urls:
        x = by.get(u, {})
        text = ' '.join([re.sub(r'[/_-]+', ' ', u.split('//', 1)[-1].split('/', 1)[-1]), str(x.get('title') or ''),
                         str(x.get('h1') or '')])
        out[u] = set(re.findall(r'[a-z0-9]+', text.lower()))
    return out


def _best_page(cluster_words, page_index, page_type):
    if not cluster_words:
        cluster_words = {'__none__'}
    type_hint = {'room': ('room', 'suite', 'apartment'), 'offer': ('offer', 'deal', 'package', 'stay'),
                 'location': ('location', 'contact', 'getting', 'map', 'about'), 'facility': ('facilit', 'pool',
                 'spa', 'gym', 'amenit'), 'blog': ('blog', 'guide', 'news'), 'home': ()}.get(page_type, ())
    best, best_s = None, 0.0
    for u, toks in page_index.items():
        s = len(cluster_words & toks) / max(1, len(cluster_words))
        if type_hint and any(any(t.startswith(h) for t in toks) for h in type_hint):
            s += 0.25
        if s > best_s:
            best, best_s = u, s
    return (best, round(best_s, 2)) if best_s >= 0.5 else (None, round(best_s, 2))


def build(group_dir, slug, crawl_dir, countries=None, languages=('en',), extra_keywords=(), competitor_urls=(),
          radius_m=5000, gsc_property='', progress=None, serp_clusters=None):
    serp_clusters = SERP_CLUSTERS if serp_clusters is None else serp_clusters
    def say(m):
        if progress:
            progress(m)
    reg = grp.load(group_dir)
    if not reg:
        raise FileNotFoundError('no site.json: run detect_hotels + save_group first')
    hotel = next((h for h in reg['hotels'] if h['slug'] == slug), None)
    if not hotel:
        raise LookupError(f'no hotel {slug} in site.json')
    hdir = grp.hotel_dir(group_dir, slug, reg)
    out_dir = hdir / 'keywords'
    out_dir.mkdir(parents=True, exist_ok=True)
    facts = _facts(hdir)
    city = hotel.get('city') or _fact(facts, 'city') or ''
    country = hotel.get('country') or ''
    cc = {'united arab emirates': 'AE', 'uae': 'AE', 'egypt': 'EG', 'saudi arabia': 'SA', 'ksa': 'SA',
          'oman': 'OM', 'qatar': 'QA', 'bahrain': 'BH', 'kuwait': 'KW'}.get(country.lower(), country.upper()[:2])
    # where it is
    say('geocoding the hotel and finding nearby places')
    addr = _fact(facts, 'address') or f"{hotel['name']}, {city}"
    loc = geo.geocode(addr)
    if not loc.get('found'):
        loc = geo.geocode(f"{hotel['name']}, {city}")
    nearby = geo.nearby(loc['lat'], loc['lon'], radius_m) if loc.get('found') else {'places': {}}
    a = loc.get('address', {}) if loc.get('found') else {}
    raw_places = [_norm(x) for x in (a.get('suburb'), a.get('neighbourhood'), a.get('city_district'),
                                     a.get('quarter'), city) if x]
    # "al barsha 1" -> also "al barsha" (people search the area, not the sub-district number)
    raw_places += [re.sub(r'\s+\d+$', '', p) for p in raw_places]
    places = [p for p in dict.fromkeys(raw_places) if p]
    rooms = [r.get('name', '') for r in _engine_rooms(hdir)] + [x.get('subject', '') for x in facts
                                                               if x.get('kind', '').startswith('room_')]
    cands = candidates(hotel, facts, places, nearby, rooms)
    competitor_names = [p['name'] for p in nearby.get('places', {}).get('hotel', [])]
    own_words = set().union(*(_toks(t) for t in local_terms(places, nearby, city))) | _toks(city) if places else set()
    brands = brand_terms(hotel, reg, competitor_names, exclude=own_words)
    # expansion: Keyword Planner ideas
    markets = [m for m in dict.fromkeys([city] + list(countries or []) + ([cc] if cc else [])) if m]
    ideas = []
    seeds = [c['keyword'] for c in cands if c['head_kind'] in ('place', 'landmark')][:20]
    say(f'Keyword Planner ideas ({len(seeds)} seeds, {len(competitor_urls)} competitor URLs)')
    for lang in languages:
        r = keywords.ideas(seeds=seeds, out_dir=str(out_dir), countries=markets[:1] or ['AE'], language=lang,
                           country_code=cc)
        if r.get('checked'):
            ideas += [(x['keyword'], "Keyword Planner idea from searches about the hotel's area")
                      for x in json.loads(open(r['files'][1], encoding='utf-8').read())['rows']]
        for cu in competitor_urls:
            r = keywords.ideas(url=cu, out_dir=str(out_dir), countries=markets[:1] or ['AE'], language=lang,
                               country_code=cc)
            if r.get('checked'):
                ideas += [(x['keyword'], f'Keyword Planner idea from competitor site {cu}')
                          for x in json.loads(open(r['files'][1], encoding='utf-8').read())['rows']]
    terms = local_terms(places, nearby, city)
    stars = _fact(facts, 'stars')
    facilities = hotel_facilities(facts)
    have = {c['keyword'] for c in cands}
    own_brand = brand_terms(hotel, reg, exclude=own_words)
    excluded = []

    def leave_out(k, why, src):
        excluded.append({'keyword': k, 'reason': why, 'source': src})

    def brand_reason(k):
        return (BRAND_OWN if is_brand(k, own_brand) else BRAND_OTHER)
    dropped = 0
    for k, src in list(ideas) + [(e, 'suggested in the FLOW Find stage') for e in extra_keywords]:
        nk = _norm(k)
        if not nk or nk in have:
            continue
        have.add(nk)
        if is_brand(nk, brands):
            dropped += 1
            leave_out(nk, brand_reason(nk), src)
            continue
        if not is_relevant(nk, city, terms, brands):
            dropped += 1
            leave_out(nk, OFF_AREA, src)
            continue
        kind, head = classify(nk, terms)
        if not serves(nk, kind, head, stars, facilities):
            dropped += 1
            leave_out(nk, NOT_SERVED, src)
            continue
        cands.append({'keyword': nk, 'head_kind': kind, 'head': head, 'fit': 0.8, 'source': src,
                      'page_type': {'landmark': 'location', 'guide': 'blog', 'room': 'room', 'facility': 'facility'}
                      .get(kind, 'home')})
    for c in cands:
        if is_brand(c['keyword'], brands):
            leave_out(c['keyword'], brand_reason(c['keyword']), c.get('source', ''))
    cands = [c for c in cands if not is_brand(c['keyword'], brands)]
    say(f'{len(cands)} relevant candidates ({dropped} Keyword Planner ideas dropped as off-topic: other districts, '
        'other hotels, unrelated searches)')
    # volumes per market (first market = the hotel's city; then country; then feeder markets)
    say(f'Keyword Planner volumes for {len(cands)} candidates in {markets}')
    vol = defaultdict(dict)
    for lang in languages:
        for m in markets:
            cache = out_dir / f'.volumes-{re.sub(r"[^A-Za-z0-9]+", "_", m)}-{lang}-{date.today().isoformat()}.json'
            cached = json.loads(cache.read_text(encoding='utf-8')) if cache.exists() else {'rows': []}
            have_kw = {_norm(x['keyword']) for x in cached['rows']} | set(cached.get('asked', []))
            todo = [c['keyword'] for c in cands if c['keyword'] not in have_kw]
            if todo:
                r = keywords.volumes(todo, str(out_dir), countries=[m], language=lang, country_code=cc, save=False)
                if not r.get('checked'):
                    raise RuntimeError('Keyword Planner: ' + r.get('reason', 'failed'))
                cached['rows'] += r['rows']
                cached['asked'] = sorted(set(cached.get('asked', [])) | set(todo))
                cache.write_text(json.dumps(cached, ensure_ascii=False), encoding='utf-8')
            r = {'rows': cached['rows']}
            for x in r['rows']:
                vol[_norm(x['keyword'])][f'{m}/{lang}'] = x
                for v in x.get('close_variants') or []:
                    vol[_norm(v)].setdefault('_variant_of', x['keyword'])
    # Search Console: 16 months, this hotel's pages only
    prop = gsc_property or hotel.get('gsc_property') or reg['group'].get('gsc_property')
    gsc = {}
    if prop:
        say('Search Console, 16 months, this hotel\'s pages')
        end = date.today() - timedelta(days=3)
        rows = _gsc_rows(prop, end - timedelta(days=486), end, ['query', 'page'], hotel['paths'])
        for r in rows or []:
            q, page = r['keys']
            g = gsc.setdefault(_norm(q), {'impressions': 0, 'clicks': 0, 'pos_x_impr': 0.0, 'pages': defaultdict(int)})
            g['impressions'] += r['impressions']
            g['clicks'] += r['clicks']
            g['pos_x_impr'] += r['position'] * r['impressions']
            g['pages'][page] += r['impressions']
        # non-brand searches the hotel already gets impressions for become keywords too
        have = {c['keyword'] for c in cands}
        src = 'Search Console: the hotel already shows for it'
        for q, g in gsc.items():
            if q in have:
                continue
            if is_brand(q, brands):
                leave_out(q, brand_reason(q), src)
                continue
            if g['clicks'] > 0 or is_relevant(q, city, terms, brands):
                kind, head = classify(q, terms)
                if g['clicks'] == 0 and not serves(q, kind, head, stars, facilities):
                    leave_out(q, NOT_SERVED, src)
                    continue
                cands.append({'keyword': q, 'head_kind': kind, 'head': head, 'fit': 0.9, 'page_type': 'home',
                              'source': src})
            else:
                leave_out(q, OFF_AREA, src)
    # score
    rows = []
    for c in cands:
        v = vol.get(c['keyword'], {})
        local = next((v[k] for k in v if not k.startswith('_') and k.startswith(f'{markets[0]}/')), None) if markets else None
        best = max((v[k] for k in v if not k.startswith('_')), key=lambda x: x['avg_monthly_searches'] or 0,
                   default=None)
        g = gsc.get(c['keyword'])
        volume = (local or best or {}).get('avg_monthly_searches') or 0
        if not volume and not g:
            leave_out(c['keyword'], NO_VOLUME, c.get('source', ''))
            continue
        info = bool(INFO_WORDS.search(c['keyword']))
        bid = (best or {}).get('high_top_bid') or 0
        intent = 0.4 if info else (1.0 if BOOK_WORDS.search(c['keyword']) else 0.6)
        if bid and not info:
            intent += min(0.5, bid / 10)
        row = dict(c, volume=volume, volume_by_market={k: x['avg_monthly_searches'] for k, x in v.items()
                                                       if not k.startswith('_')},
                   monthly=(local or best or {}).get('monthly', []), competition=(best or {}).get('competition', ''),
                   high_top_bid=bid, intent='informational' if info else 'booking',
                   score=round(volume * intent * c['fit'], 1))
        if info:
            row['page_type'] = 'blog'
        if g:
            row.update(gsc_impressions=g['impressions'], gsc_clicks=g['clicks'],
                       gsc_position=round(g['pos_x_impr'] / g['impressions'], 1) if g['impressions'] else None,
                       gsc_top_page=max(g['pages'], key=g['pages'].get))
        rows.append(row)
    rows.sort(key=lambda r: -r['score'])
    # cluster
    say('clustering and matching pages')
    clusters = defaultdict(list)
    for r in rows:
        clusters[(r['head_kind'], _norm(r['head']) or 'hotels in the city')].append(r)
    page_urls = grp.pages_of(crawl_dir, slug) or []
    hotel_home = next((u for u in page_urls if u.rstrip('/').endswith(hotel['paths'][0].rstrip('/'))), None) \
        if hotel['paths'] != ['/'] else next((u for u in page_urls if u.rstrip('/').count('/') == 2), None)
    index = _page_index(crawl_dir, page_urls) if page_urls else {}
    out_clusters = []
    for (kind, head), items in clusters.items():
        items.sort(key=lambda r: -r['score'])
        primary = items[0]
        words = (_toks(head) | _toks(primary['keyword'])) - GENERIC - _toks(city)
        target, match = _best_page(words, index, primary['page_type'])
        if not target and kind in ('type', 'place', 'stars', 'audience') and hotel_home in index:
            target, match = hotel_home, 1.0          # general stay searches belong on the hotel's main page
        gsc_items = [r for r in items if r.get('gsc_impressions')]
        if gsc_items:
            impr = sum(r['gsc_impressions'] for r in gsc_items)
            pos = sum(r['gsc_position'] * r['gsc_impressions'] for r in gsc_items) / impr if impr else None
            target = target or max(gsc_items, key=lambda r: r['gsc_impressions']).get('gsc_top_page')
            status = 'ranks' if pos is not None and pos <= 10 else 'shows but low'
        else:
            impr, pos = 0, None
            status = 'invisible' if target else 'no page'
        dist = [r['distance_m'] for r in items if r.get('distance_m') is not None]
        peak = seasonal_peak(_sum_monthly(items))
        cl = {
            'id': re.sub(r'[^a-z0-9]+', '-', f'{kind}-{head}').strip('-')[:60], 'kind': kind, 'head': head,
            'primary_keyword': primary['keyword'], 'page_type': primary['page_type'],
            'intent': primary['intent'], 'volume': sum(r['volume'] for r in items),
            'score': round(sum(r['score'] for r in items), 1), 'keywords': [r['keyword'] for r in items],
            'target_page': target, 'match': match, 'status': status, 'gsc_impressions': impr,
            'gsc_position': round(pos, 1) if pos else None,
            'monthly': primary.get('monthly', []),
            'sources': sorted({r.get('source') or "built from the hotel's facts and location" for r in items}),
            'distance_m': min(dist) if dist else None}
        if peak:
            cl['peak'] = peak
        out_clusters.append(cl)
    out_clusters.sort(key=lambda c: -c['score'])
    # who holds page 1: free from earlier checks, then Serper for the top "no page" / "shows but low" clusters
    serp_note = serp_enrich(out_clusters, hdir, reg['group'].get('site') or '', hotel, city, country,
                            rival_names=competitor_names, limit=serp_clusters, say=say)
    order = build_order(out_clusters)
    rank_of = {cid: i for i, cid in enumerate(order, 1)}
    for cl in out_clusters:
        cl['build_rank'] = rank_of.get(cl['id'])
        cl['why'] = explain(cl, city=city, stars=stars, market=markets[0] if markets else '', slug=slug)
    ex_summary = defaultdict(lambda: {'count': 0, 'examples': []})
    for e in excluded:
        b = ex_summary[e['reason']]
        b['count'] += 1
        if len(b['examples']) < 8:
            b['examples'].append(e['keyword'])
    result = {'hotel': hotel['name'], 'slug': slug, 'city': city, 'country': country, 'markets': markets,
              'languages': list(languages), 'generated': date.today().isoformat(),
              'location': {k: loc.get(k) for k in ('lat', 'lon', 'display_name')} if loc.get('found') else None,
              'places': places, 'brand_terms_filtered': brands, 'candidates': len(cands), 'keywords': len(rows),
              'excluded_summary': dict(sorted(ex_summary.items(), key=lambda kv: -kv[1]['count'])),
              'excluded_file': str(out_dir / 'keyword-map-excluded.csv'),
              'clusters': out_clusters, 'build_order': order, 'serp': serp_note,
              'status_counts': {s: sum(1 for c in out_clusters if c['status'] == s)
                                for s in ('ranks', 'shows but low', 'invisible', 'no page')},
              'sources': ['Google Ads Keyword Planner'] + (['Search Console (16 months, hotel pages)'] if gsc else []) +
                         ['OpenStreetMap' + (' + Geoapify' if 'Geoapify' in nearby.get('sources', []) else '')]}
    f = out_dir / 'keyword-map.json'
    f.write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding='utf-8')
    with open(out_dir / 'keyword-map-keywords.csv', 'w', newline='', encoding='utf-8-sig') as fh:
        w = csv.writer(fh)
        w.writerow(['keyword', 'volume', 'intent', 'score', 'head_kind', 'head', 'page_type', 'competition',
                    'high_top_bid', 'gsc_impressions', 'gsc_position'])
        for r in rows:
            w.writerow([r['keyword'], r['volume'], r['intent'], r['score'], r['head_kind'], r['head'], r['page_type'],
                        r['competition'], r['high_top_bid'], r.get('gsc_impressions', ''), r.get('gsc_position', '')])
    with open(out_dir / 'keyword-map-excluded.csv', 'w', newline='', encoding='utf-8-sig') as fh:
        w = csv.writer(fh)
        w.writerow(['keyword', 'why it was left out', 'where it came from'])
        for e in excluded:
            w.writerow([e['keyword'], e['reason'], e['source']])
    return {'file': str(f), 'csv': str(out_dir / 'keyword-map-keywords.csv'), 'keywords': len(rows),
            'excluded': len(excluded),
            'clusters': len(out_clusters), 'status_counts': result['status_counts'],
            'top_clusters': [{k: c[k] for k in ('primary_keyword', 'volume', 'status', 'target_page')}
                             for c in out_clusters[:15]], 'serp': serp_note}


BRAND_OWN = "brand search: people already looking for the hotel by name (it ranks for these; no work needed)"
BRAND_OTHER = "another hotel's or brand's name"
OFF_AREA = "about another area, or not a search for a place to stay"
NOT_SERVED = "asks for something the hotel isn't or doesn't have (star rating, facility, price level)"
NO_VOLUME = "no monthly searches (Keyword Planner) and the hotel never showed for it in Search Console"
KIND_REASON = {
    'place': "The hotel is in {head}: guests search for a place to stay there.",
    'type': "General searches for a place to stay in {city}: the hotel's main page should be in them.",
    'stars': "The hotel is {head}.",
    'facility': "The hotel has it: guests search for hotels {head}.",
    'room': "The hotel sells this room type ({head}).",
    'audience': "{Head} stays in the hotel's area.",
    'intent': "Searches from people ready to book ({head}).",
    'guide': "Questions guests ask before the trip: a guide page can answer them and link to booking.",
    'landmark-info': "Questions about {head}: a guide page can answer them and link to booking.",
}
STATUS_REASON = {
    'ranks': "Already on page 1 of Google (average position {pos}): keep it there.",
    'shows but low': "Google shows the hotel at position {pos} ({impr} views in 16 months): the page needs work to "
                     "reach page 1.",
    'invisible': "A page exists but Google does not show it for these searches yet.",
    'no page': "No page answers it yet: the Build Plan adds one.",
}


SERP_CLUSTERS = 12        # most Serper credits a keyword map spends: page 1 (1 credit) of this many clusters
SERP_STATUSES = ('no page', 'shows but low')   # the clusters checked, top score first
SERP_MAX_AGE_DAYS = 30    # an earlier page-1 check (keyword map or monthly report) is reused this long
SERP_CACHE = 'serp-page1.json'                 # <hotel dir>/keywords/: the keyword map's own checks
LEAD_WEEKS = 8            # publish or refresh a page this long before its searches peak
PEAK_MIN_RATIO = 1.3      # the peak month must be 30% above the monthly average, else demand is flat
PEAK_MIN_AVG = 10         # below this many searches a month the seasonal shape is noise
VERDICT_REASON = {
    'hotel sites can win': "Hotel websites hold places on page 1 of Google (checked {d}): a strong hotel page can "
                           "rank.",
    'mostly booking sites': "Page 1 of Google is mostly booking sites ({n} of the top 10, checked {d}): hard for a "
                            "hotel page to reach the top.",
    'mostly guides and articles': "Page 1 of Google is mostly guides and articles ({n} of the top 10, checked {d}): "
                                  "a guide page fits it better than a booking page.",
    'mixed': "Page 1 of Google is a mix of booking sites, guides and other sites (checked {d}).",
}


def _sum_monthly(items):
    """The 12-month series of a whole cluster (sum of its searches' Keyword Planner months)."""
    tot = defaultdict(int)
    for r in items:
        for m in r.get('monthly') or []:
            if m.get('searches') is not None and re.match(r'^\d{4}-\d{2}$', str(m.get('month', ''))):
                tot[m['month']] += m['searches']
    return [{'month': k, 'searches': v} for k, v in sorted(tot.items())]


def _next_start(month, today):
    d = date(today.year, month, 1)
    return d if d > today else date(today.year + 1, month, 1)


def seasonal_peak(monthly, today=None):
    """The calendar month searches peak in: {'month': 7, 'name': 'July', 'lift_pct': 45, 'publish_by': date str}
    (publish_by = the next start of that month minus LEAD_WEEKS). None when there are not 12 months, too few
    searches (PEAK_MIN_AVG) or no month stands out (PEAK_MIN_RATIO): flat or missing data."""
    by = defaultdict(list)
    for m in monthly or []:
        mt = re.match(r'^(\d{4})-(\d{2})$', str(m.get('month', '')))
        if mt and isinstance(m.get('searches'), (int, float)) and 1 <= int(mt.group(2)) <= 12:
            by[int(mt.group(2))].append(m['searches'])
    if len(by) < 12:
        return None
    avg_by = {k: sum(v) / len(v) for k, v in by.items()}
    avg = sum(avg_by.values()) / 12
    top = max(avg_by.values())
    if avg < PEAK_MIN_AVG or top < avg * PEAK_MIN_RATIO:
        return None
    today = today or date.today()
    month = min((m for m, v in avg_by.items() if v == top), key=lambda m: _next_start(m, today))
    return {'month': month, 'name': calendar.month_name[month], 'lift_pct': round((top / avg - 1) * 100),
            'publish_by': str(_next_start(month, today) - timedelta(weeks=LEAD_WEEKS))}


def _timing_line(peak, today=None):
    today = today or date.today()
    by = _next_start(peak['month'], today) - timedelta(weeks=LEAD_WEEKS)
    head = f"Searches peak in {peak['name']} ({peak['lift_pct']}% above the monthly average)"
    if by <= today:
        return head + f": publish or refresh the page now (the peak is under {LEAD_WEEKS} weeks away)."
    return head + f": publish or refresh the page by {by.day} {calendar.month_name[by.month]} {by.year}."


def _earlier_checks(hdir, today):
    """{keyword: Serper rank result with composition} from the keyword map's cache and the monthly reports'
    serp.json, checked within SERP_MAX_AGE_DAYS; the newest check wins. Files without composition add nothing."""
    hdir = paths.resolve(hdir)
    out = {}
    for f in sorted(hdir.glob('monthly-*/serp.json')) + [hdir / 'keywords' / SERP_CACHE]:
        if not f.exists():
            continue
        try:
            d = json.loads(f.read_text(encoding='utf-8'))
        except ValueError:
            continue
        for kw, r in (d.get('search') or {}).items():
            if not isinstance(r, dict) or not r.get('composition'):
                continue
            try:
                age = (today - date.fromisoformat(str(r.get('checked', '')))).days
            except ValueError:
                continue
            k = _norm(kw)
            if 0 <= age <= SERP_MAX_AGE_DAYS and (k not in out or r['checked'] >= out[k]['checked']):
                out[k] = r
    return out


def _serp_summary(r, source):
    comp = r.get('composition') or {}
    mp = r.get('map_pack') or {}
    return {'checked': r.get('checked'), 'source': source, 'position': r.get('position'),
            'verdict': comp.get('verdict'), 'mix': comp.get('mix') or {},
            'rival_domains': comp.get('rival_domains') or [], 'paa': comp.get('paa') or [],
            'related': comp.get('related') or [], 'answer_box': comp.get('answer_box'),
            'map_pack': {'shown': bool(mp.get('shown')), 'hotel_position': mp.get('hotel_position')}}


def serp_enrich(clusters, hdir, site, hotel, city, country, rival_names=(), limit=SERP_CLUSTERS, say=None,
                today=None):
    """Page 1 of Google for the clusters (c['serp']: verdict, mix, rival hotel domains, People Also Ask, related
    searches, map pack). Earlier checks are reused free; then Serper (1 credit each) for the top `limit` clusters
    by score whose status is in SERP_STATUSES. No Serper key: skipped, nothing else changes."""
    today = today or date.today()
    found = _earlier_checks(hdir, today)
    note = {'reused': 0, 'checked': 0, 'credits': 0, 'limit': limit}
    for c in clusters:
        r = found.get(_norm(c.get('primary_keyword')))
        if r:
            c['serp'] = _serp_summary(r, 'earlier check')
            note['reused'] += 1
    # the cap counts reused checks too, so a rebuild within SERP_MAX_AGE_DAYS spends nothing new
    todo = [c for c in clusters if c.get('status') in SERP_STATUSES][:max(0, limit or 0)]
    todo = [c for c in todo if not c.get('serp')]
    if not todo:
        return note
    from . import apikeys, serp
    if not apikeys.get('serper'):
        note['skipped'] = 'no Serper key: page 1 (rival hotels, People Also Ask) not checked'
        return note
    cache_f = paths.resolve(hdir) / 'keywords' / SERP_CACHE
    try:
        cache = json.loads(cache_f.read_text(encoding='utf-8')) if cache_f.exists() else {}
    except ValueError:
        cache = {}
    cache.setdefault('search', {})
    if say:
        say(f'Google page 1 for {len(todo)} clusters (Serper, {len(todo)} credits at most)')
    for c in todo:
        try:
            r = serp.rank(c['primary_keyword'], site, hotel.get('paths') or ['/'], hotel.get('name', ''),
                          city or 'Dubai', country or 'United Arab Emirates', pages=1, rival_names=rival_names)
        except RuntimeError as e:
            note['error'] = str(e)[:200]
            break
        cache['search'][c['primary_keyword']] = r
        c['serp'] = _serp_summary(r, 'keyword map check')
        note['checked'] += 1
        note['credits'] += r.get('credits', 1)
    cache_f.parent.mkdir(parents=True, exist_ok=True)
    cache_f.write_text(json.dumps(cache, indent=1, ensure_ascii=False), encoding='utf-8')
    return note


def build_order(clusters):
    """Cluster ids in Build Plan order: clusters with no page or shown low where rival hotels rank on page 1 come
    first (guests go to rivals for it, and a hotel page can win it), then all others by score, so clusters nobody's
    hotel page serves come after them."""
    def key(c):
        rivals = bool((c.get('serp') or {}).get('rival_domains')) and c.get('status') in SERP_STATUSES
        return 0 if rivals else 1, -(c.get('score') or 0)
    return [c['id'] for c in sorted(clusters, key=key)]


def _title(s):
    small = {'of', 'the', 'and', 'in', 'at', 'al', 'el', 'bin', 'de'}
    words = str(s or '').split()
    return ' '.join(w if (w in small and i) else w[:1].upper() + w[1:] for i, w in enumerate(words))


def explain(c, city='', stars=None, market='', slug='', today=None):
    """Plain-language reasons a cluster was chosen (also for keyword maps built before reasons were recorded)."""
    kind, head = c.get('kind', 'type'), str(c.get('head') or '')
    if kind in ('place', 'landmark', 'landmark-info'):
        head = _title(head)
    city = _title(city)
    why = []
    if kind == 'landmark':
        d = c.get('distance_m')
        why.append(f"{head} is {round(d / 1000, 1)} km from the hotel (OpenStreetMap): guests look for a stay near it."
                   if d is not None else f"{head} is near the hotel: guests look for a stay near it.")
    elif kind in KIND_REASON:
        why.append(KIND_REASON[kind].format(head=head, Head=head[:1].upper() + head[1:], city=city or 'the city'))
    n = len(c.get('keywords') or [])
    if c.get('volume'):
        why.append(f"{c['volume']:,} searches a month across {n} search{'es' if n != 1 else ''} in this group "
                   f"(Keyword Planner{', ' + market if market else ''}).")
    if c.get('intent') == 'booking':
        why.append('Booking intent: people searching it are choosing where to stay.')
    st = STATUS_REASON.get(c.get('status'))
    if st:
        if c.get('status') == 'shows but low' and (c.get('gsc_position') or 0) > 50:
            st = 'Google barely shows the hotel for it (position {pos}, {impr} views in 16 months): it needs a page ' \
                 'built for it.'
        why.append(st.format(pos=round(c.get('gsc_position') or 0), impr=f"{c.get('gsc_impressions') or 0:,}")
                   if c.get('status') == 'shows but low' and (c.get('gsc_position') or 0) > 50
                   else st.format(pos=c.get('gsc_position'), impr=f"{c.get('gsc_impressions') or 0:,}"))
    s = c.get('serp') or {}
    if s.get('rival_domains') and c.get('status') in SERP_STATUSES:
        why.append(f"Rival hotels are on page 1 of Google for it ({', '.join(s['rival_domains'][:3])}) and the hotel "
                   + ('has no page for it' if c.get('status') == 'no page' else 'is not on page 1')
                   + ': build it first.')
    elif s.get('verdict') in VERDICT_REASON:
        mix = s.get('mix') or {}
        n = mix.get('booking site', 0) if s['verdict'] == 'mostly booking sites' else mix.get('guide', 0)
        why.append(VERDICT_REASON[s['verdict']].format(n=n, d=s.get('checked') or 'recently'))
    if s.get('paa'):
        why.append('People also ask on Google: ' + ' '.join(f'"{q}"' for q in s['paa'][:3])
                   + ' Answer them on the page (FAQ and copy).')
    peak = c.get('peak') or seasonal_peak(c.get('monthly'), today)
    if peak:
        why.append(_timing_line(peak, today))
    if slug and c.get('owned_by') and c.get('owned_by') != slug:
        why.append('In this city another hotel of the group targets it first (see the Group Summary).')
    src = [x for x in c.get('sources') or [] if not x.startswith('built from')]
    if src:
        why.append('Found through: ' + '; '.join(src) + '.')
    return why


def _engine_rooms(hotel_dir):
    found = sorted(paths.resolve(hotel_dir).rglob('booking_engine.json'), key=lambda p: p.stat().st_mtime)
    if not found:
        return []
    d = json.loads(found[-1].read_text(encoding='utf-8'))
    return (d.get('summary') or {}).get('rooms') or []


def assign_group(group_dir):
    """Across hotels of one group: a cluster head that several hotels in the same city share is owned by one hotel
    (the best score), the others get it as 'owned_by' so they don't compete. Writes each keyword-map.json back."""
    reg = grp.load(group_dir)
    maps = {}
    for h in reg['hotels']:
        f = grp.hotel_dir(group_dir, h['slug'], reg) / 'keywords' / 'keyword-map.json'
        if f.exists():
            maps[h['slug']] = (f, json.loads(f.read_text(encoding='utf-8')))
    owners = {}
    for slug, (_, m) in maps.items():
        for c in m['clusters']:
            key = (_norm(m.get('city')), c['kind'], c['head'] or c['primary_keyword'])
            if key not in owners or c['score'] > owners[key][1]:
                owners[key] = (slug, c['score'])
    shared = 0
    for slug, (f, m) in maps.items():
        for c in m['clusters']:
            key = (_norm(m.get('city')), c['kind'], c['head'] or c['primary_keyword'])
            owner = owners[key][0]
            c['owned_by'] = owner
            if owner != slug:
                shared += 1
        f.write_text(json.dumps(m, indent=1, ensure_ascii=False), encoding='utf-8')
    return {'hotels': len(maps), 'clusters_owned_by_another_hotel': shared}
