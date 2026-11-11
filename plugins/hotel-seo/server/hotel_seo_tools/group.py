"""Sites: a single hotel on its own domain, or a hotel group (many hotels as sections of one site, e.g.
/hotels-apartments/rose-park-albarsha/).

site.json (in <domain>/) is the registry every other step reads (older runs: group.json, still read):
{
  "type": "single" | "group",
  "group": {"name", "site", "gsc_property", "ga4_property"},
  "hotels": [{"slug", "name", "paths": ["/hotels-apartments/rose-park-albarsha/"], "city", "country",
              "mirai_id", "booking_com_url", "gsc_property", "ga4_property", "confirmed": true}],
  "confirmed_on": "yyyy-mm-dd"
}
Single hotel (one hotel covering the whole domain, paths ["/"]): everything sits directly in <domain>/ (no group/,
no hotels/, no Group Summary, no group batch). Group: site-wide work in <domain>/group/, each hotel in
<domain>/hotels/<slug>/. hotel_dir() and site_dir() give the right folder for either kind.

detect() proposes the hotels from a crawl; Claude shows the list to the user, who confirms it and adds the
Booking.com URLs; save() writes it. partition() assigns every crawled page to a hotel (longest path prefix wins)
or to "group" (shared pages: group home, about, careers, blog).
"""
import json
import re
from collections import Counter, defaultdict
from datetime import date
from urllib.parse import urlparse

from . import paths
from .librecrawl import is_page

HOTEL_TYPES = {'Hotel', 'LodgingBusiness', 'Resort', 'Motel', 'Hostel', 'BedAndBreakfast', 'Apartment',
               'ApartmentComplex', 'Accommodation', 'Suite', 'HotelRoom'}
GROUP_PARENT_HINTS = re.compile(r'hotel|resort|propert|apartment|destination|our-|stay|location', re.I)
SKIP_SEGMENTS = {'wp-content', 'wp-json', 'wp-admin', 'feed', 'tag', 'category', 'author', 'page', 'blog', 'blogs',
                 'news', 'search', 'ar', 'en', 'ru', 'de', 'fr', 'zh', 'it', 'es'}
MIRAI_ID = re.compile(r'idtokenprovider=(\d+)')


def _path(u):
    p = urlparse(u).path or '/'
    return p if p.endswith('/') else p + '/'


def _host(u):
    return urlparse(u if '//' in u else 'https://' + u).netloc.lower().removeprefix('www.')


def _types(block):
    nodes = block.get('@graph', [block]) if isinstance(block, dict) else block if isinstance(block, list) else []
    for n in nodes:
        if isinstance(n, dict):
            t = n.get('@type')
            for x in (t if isinstance(t, list) else [t]):
                if x:
                    yield x, n


def _load_crawl(crawl_dir):
    data = json.loads((paths.resolve(crawl_dir) / 'crawl.json').read_text(encoding='utf-8'))
    start = data.get('stats', {}).get('baseUrl') or (data['urls'][0]['url'] if data.get('urls') else '')
    host = _host(start)
    pages = [u for u in data.get('urls', []) if is_page(u) and _host(u['url']) == host]
    return data, host, pages


def _clean_name(t):
    """'Rose Park Al Barsha | Hotel In Sheikh Zayed Rd - Official Site' -> 'Rose Park Al Barsha'."""
    t = re.sub(r'\s+', ' ', str(t or '')).strip()
    t = re.split(r'\s[|–—]\s|\s-\s(?=official)', t, flags=re.I)[0]
    return re.sub(r'\s*[-|]?\s*official (web)?site\s*$', '', t, flags=re.I).strip()


def detect(crawl_dir):
    """Propose the hotels of a group site from its crawl: sections that sit under one parent path and carry Hotel
    schema, booking-engine links or their own sub-pages. Returns {'site', 'hotels': [...], 'evidence'}."""
    data, host, pages = _load_crawl(crawl_dir)
    by_path = {_path(u['url']): u for u in pages}
    # 1. parent folders with several child sections
    children = defaultdict(set)
    for p in by_path:
        segs = [s for s in p.strip('/').split('/') if s]
        if len(segs) >= 2 and segs[0] not in SKIP_SEGMENTS:
            children['/' + segs[0] + '/'].add(segs[1])
    # 2. per-section evidence: hotel schema, booking links (Mirai IDs), page counts
    links_by_source = defaultdict(list)
    for l in data.get('links', []):
        links_by_source[l.get('source_url')].append(l.get('target_url') or '')
    candidates = []
    for parent, kids in children.items():
        if len(kids) < 2:
            continue
        for kid in sorted(kids):
            prefix = f'{parent}{kid}/'
            sect = [u for p, u in by_path.items() if p.startswith(prefix)]
            names, cities, countries, ids = Counter(), Counter(), Counter(), Counter()
            hotel_schema = 0
            for u in sect:
                for block in u.get('json_ld') or []:
                    for t, n in _types(block):
                        if t in HOTEL_TYPES or t == 'LocalBusiness':
                            hotel_schema += 1
                            if n.get('name'):
                                names[str(n['name']).strip()] += 1
                            addr = n.get('address') if isinstance(n.get('address'), dict) else {}
                            if addr.get('addressLocality'):
                                cities[str(addr['addressLocality']).strip()] += 1
                            if addr.get('addressCountry'):
                                c = addr['addressCountry']
                                countries[str(c.get('name') if isinstance(c, dict) else c).strip()] += 1
                for target in links_by_source.get(u['url'], []):
                    for m in MIRAI_ID.findall(target):
                        ids[m] += 1
            score = (3 if hotel_schema else 0) + (2 if ids else 0) + (1 if len(sect) > 1 else 0) + \
                    (1 if GROUP_PARENT_HINTS.search(parent) else 0)
            if score < 3:
                continue
            title = _clean_name((by_path.get(prefix) or {}).get('h1') or (by_path.get(prefix) or {}).get('title')
                                or kid.replace('-', ' ').title())
            candidates.append({
                'slug': kid, 'name': names.most_common(1)[0][0] if names else re.sub(r'\s+', ' ', str(title)).strip(),
                'paths': [prefix], 'city': cities.most_common(1)[0][0] if cities else '',
                'country': countries.most_common(1)[0][0] if countries else '',
                'mirai_id': ids.most_common(1)[0][0] if ids else '', 'mirai_ids_seen': dict(ids),
                'booking_com_url': '', 'pages': len(sect), 'hotel_schema_blocks': hotel_schema,
                'parent': parent, 'confidence': 'high' if score >= 5 else 'medium'})
    # Keep the parent with the most hotel-like sections (avoid e.g. /blog/<post>/ false positives).
    best_parent = Counter(c['parent'] for c in candidates if c['confidence'] == 'high').most_common(1)
    if best_parent:
        candidates = [c for c in candidates if c['parent'] == best_parent[0][0] or c['confidence'] == 'high']
    if not candidates:
        # A single-hotel site: one hotel covering the whole site.
        ids = Counter(m for l in data.get('links', []) for m in MIRAI_ID.findall(l.get('target_url') or ''))
        names = Counter()
        for u in pages:
            for block in u.get('json_ld') or []:
                for t, n in _types(block):
                    if t in HOTEL_TYPES and n.get('name'):
                        names[str(n['name']).strip()] += 1
        candidates = [{'slug': re.sub(r'[^a-z0-9]+', '-', host.split('.')[0]).strip('-'),
                       'name': names.most_common(1)[0][0] if names else host, 'paths': ['/'], 'city': '',
                       'country': '', 'mirai_id': ids.most_common(1)[0][0] if ids else '',
                       'mirai_ids_seen': dict(ids), 'booking_com_url': '', 'pages': len(pages),
                       'hotel_schema_blocks': sum(names.values()), 'parent': '/', 'confidence': 'high'}]
    return {'site': f'https://{host}', 'pages': len(pages), 'hotels': candidates,
            'note': 'Proposed from the crawl. Show it to the user, confirm names / paths / cities, ask for each '
                    "hotel's Booking.com URL, then call save_group."}


REGISTRY, LEGACY = 'site.json', 'group.json'


def file_for(group_dir):
    """site.json, or an older run's group.json when only that exists."""
    d = paths.resolve(group_dir)
    return d / LEGACY if not (d / REGISTRY).exists() and (d / LEGACY).exists() else d / REGISTRY


def is_single(reg):
    """One hotel covering the whole domain (no group sections)."""
    if not reg:
        return False
    if reg.get('type') in ('single', 'group'):
        return reg['type'] == 'single'
    hs = reg.get('hotels') or []
    return len(hs) == 1 and (hs[0].get('paths') or ['/']) == ['/']


def load(group_dir):
    f = file_for(group_dir)
    if not f.exists():
        return None
    reg = json.loads(f.read_text(encoding='utf-8'))
    reg.setdefault('type', 'single' if is_single(reg) else 'group')
    return reg


def hotel_dir(group_dir, slug, reg=None):
    """Where a hotel's files live: <domain>/ for a single hotel, <domain>/hotels/<slug>/ in a group."""
    reg = reg if reg is not None else load(group_dir)
    d = paths.resolve(group_dir)
    return d if is_single(reg) else d / 'hotels' / slug


def site_dir(group_dir, reg=None):
    """Where site-wide work lives: <domain>/ for a single hotel, <domain>/group/ for a group."""
    reg = reg if reg is not None else load(group_dir)
    d = paths.resolve(group_dir)
    return d if is_single(reg) else d / 'group'


def save(group_dir, group, hotels):
    """Validate and write site.json. One hotel covering the whole domain (paths ["/"]) is a single-hotel site:
    no hotels/ folders. A group gets hotels/<slug>/ per hotel. Returns the saved registry."""
    seen, clean = set(), []
    for h in hotels:
        slug = re.sub(r'[^a-z0-9-]+', '-', str(h.get('slug', '')).lower()).strip('-')
        if not slug or slug in seen:
            raise ValueError(f'every hotel needs a unique slug (got {h.get("slug")!r})')
        seen.add(slug)
        ps = [p if p.startswith('/') else '/' + p for p in (h.get('paths') or [])]
        ps = [p if p.endswith('/') else p + '/' for p in ps]
        if not ps:
            raise ValueError(f'hotel {slug} has no paths')
        bc = (h.get('booking_com_url') or '').strip()
        if bc and 'booking.com/hotel/' not in bc:
            raise ValueError(f'hotel {slug}: {bc} is not a Booking.com hotel page URL (…booking.com/hotel/…)')
        clean.append({'slug': slug, 'name': h.get('name', slug), 'paths': ps, 'city': h.get('city', ''),
                      'country': h.get('country', ''), 'mirai_id': str(h.get('mirai_id') or ''),
                      'booking_com_url': bc, 'gsc_property': h.get('gsc_property', ''),
                      'ga4_property': h.get('ga4_property', ''), 'confirmed': bool(h.get('confirmed', True))})
    single = len(clean) == 1 and clean[0]['paths'] == ['/']
    if not single and any(h['paths'] == ['/'] for h in clean):
        raise ValueError('a group needs each hotel\'s own path (e.g. /hotels/<hotel>/); "/" is only for a single-hotel '
                         'site')
    reg = {'type': 'single' if single else 'group',
           'group': {'name': group.get('name', ''), 'site': group.get('site', ''),
                     'gsc_property': group.get('gsc_property', ''), 'ga4_property': group.get('ga4_property', '')},
           'hotels': clean, 'confirmed_on': date.today().isoformat()}
    d = paths.resolve(group_dir)
    d.mkdir(parents=True, exist_ok=True)
    (d / REGISTRY).write_text(json.dumps(reg, indent=1, ensure_ascii=False), encoding='utf-8')
    if not single:
        for h in clean:
            (d / 'hotels' / h['slug']).mkdir(parents=True, exist_ok=True)
    return reg


def hotel_for(url, reg):
    """The slug of the hotel that owns a URL (longest matching path prefix), or 'group'."""
    p = _path(url)
    best, best_len = 'group', -1
    for h in reg['hotels']:
        for prefix in h['paths']:
            if p.startswith(prefix) and len(prefix) > best_len:
                best, best_len = h['slug'], len(prefix)
    return best


def partition(crawl_dir, group_dir):
    """Assign every crawled page to a hotel or 'group'. Writes <crawl>/partition.json {slug: [urls]}."""
    reg = load(group_dir)
    if not reg:
        raise FileNotFoundError(f'no group.json in {paths.resolve(group_dir)}: run detect_hotels + save_group first')
    data, _, pages = _load_crawl(crawl_dir)
    owner = {u['url']: hotel_for(u['url'], reg) for u in pages}
    # Shared post types (e.g. /room/<name>/, /offer/<name>/) sit outside every hotel's path. A page like that belongs to
    # a hotel when the only hotel pages linking to it are that hotel's (group pages and menus linking everywhere don't
    # count); otherwise it stays with the group.
    linked_from = defaultdict(set)
    for l in data.get('links', []):
        src, dst = l.get('source_url'), l.get('target_url')
        if dst in owner and owner[dst] == 'group' and src in owner and owner[src] != 'group':
            linked_from[dst].add(owner[src])
    moved = {}
    for u, hotels in linked_from.items():
        if len(hotels) == 1:
            owner[u] = moved[u] = next(iter(hotels))
    out = defaultdict(list)
    for u, h in owner.items():
        out[h].append(u)
    out = {k: sorted(v) for k, v in out.items()}
    (paths.resolve(crawl_dir) / 'partition-shared-pages.json').write_text(
        json.dumps(moved, indent=1), encoding='utf-8')
    (paths.resolve(crawl_dir) / 'partition.json').write_text(json.dumps(out, indent=1), encoding='utf-8')
    return {'file': str(paths.resolve(crawl_dir) / 'partition.json'), 'pages': {k: len(v) for k, v in out.items()}}


def pages_of(crawl_dir, slug):
    """URLs of one hotel (or 'group') from partition.json."""
    f = paths.resolve(crawl_dir) / 'partition.json'
    return json.loads(f.read_text(encoding='utf-8')).get(slug, []) if f.exists() else []
