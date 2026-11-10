"""Live consistency check: one fact must read the same on every page before a run, a re-check or an agency's
"done" is accepted.

From the Abar and Rose runs (handoff, Nov 2026). A reviewer found these on abarhotels.com within an hour of the site
being marked done: guest numbers fixed in a room page's body but not its meta description; one apartment with a
different size in the title, meta and body; one landmark at 0.9 / 1 / 1.6 km on different pages; metas over 155
characters; WordPress default "Page - Site" titles; an old year in a blog title; room pages with no room schema;
internal links marked nofollow. A second reviewer's lists (9 Nov) then flagged four distance "conflicts" that were
different places ("The Market Mall in Green Community 1.6 km", "Dubai Exhibition Centre, Expo City 11.7 km", "The Els
Club, Dubai Sports City 12.9 km", and Dubai Marina / Global Village / Mall of the Emirates read as one "Emirates").
So a distance belongs to the longest known place name it follows, stops at the end of the clause, a qualified name is
reported under its full name, and figures are compared with hotel-facts.json.

run(site, out_dir, facts_file, landmarks) reads every sitemap page, writes nothing to the site, and returns one row
per problem. Every DISTANCE row is checked by hand against its quoted text.
"""
import html
import json
import re
from collections import defaultdict
from datetime import date
from urllib.parse import urljoin, urlparse

import requests

from . import paths
from .librecrawl import UA

# Place names that are always worth matching. The run adds the names in hotel-facts.json and the place names the
# site itself puts next to a distance, so hotels outside Dubai work too.
DEFAULT_LANDMARKS = ['Airport', 'Metro Station', 'Beach', 'City Centre', 'Downtown', 'Old Town', 'Marina', 'Mall',
                     'Expo City', 'Al Maktoum', 'Global Village', 'Mall of the Emirates', 'Dubai Mall', 'Burj Khalifa',
                     'Dubai Marina', 'Palm Jumeirah', 'DXB', 'Gold Souk']
FACT_DIST = re.compile(r'^\s*(?P<place>[^:]{3,80}?):\s*(?:about\s+|approx(?:imately)?\.?\s+)?'
                       r'(?P<km>\d{1,3}(?:\.\d)?)\s?km', re.I)
NUM_KM = re.compile(r'(\d{1,3}(?:\.\d)?) ?km\b', re.I)
SIZE = r'(\d{2,4}(?:[,.]\d{3})?(?:\s?[–-]\s?\d{2,4}(?:[,.]\d{3})?)?) ?(?:sqm|m²|m2|sq\.? ?ft|square (?:metres|meters|feet))'
SITE_PLACE = re.compile(r"((?:the\s+)?[A-Z][\w'’&.-]*(?:\s+(?:of|al|Al|el|bin|the|de|&)?\s*[A-Z][\w'’&.-]*){0,4})"
                        r"\s*(?:[:(–-]|is|is about|is only|at)?\s*\(?\s*\d{1,3}(?:\.\d)?\s?km\b")
STOP = {'the', 'from', 'in', 'at', 'to', 'and', 'by', 'is', 'of', 'a', 'an', 'near', 'about', 'hotel', 'apartments',
        'yes', 'how', 'far', 'it', 'its', 'our', 'area', 'place', 'road', 'car', 'just', 'only', 'approx'}
CLAUSE_END = re.compile(r'[.?!;]\s|\)|\b(?:and|to|for|from|while)\b', re.I)
BEFORE = re.compile(r'(?:\d|\bkm\b|\bmin(?:utes)?\b|[.?!:;()])', re.I)


def _get(s, url):
    r = s.get(url, timeout=40)
    r.raise_for_status()
    return r.text


def _sitemap_urls(s, site):
    try:
        idx = _get(s, site + '/sitemap_index.xml')
        maps = re.findall(r'<loc>([^<]*sitemap[^<]*\.xml)</loc>', idx)
    except requests.RequestException:
        maps = []
    maps = maps or [site + '/sitemap.xml']
    urls, warn = set(), []
    for sm in maps:
        try:
            urls.update(u for u in re.findall(r'<loc>([^<]+)</loc>', _get(s, sm))
                        if not re.search(r'\.(jpe?g|png|webp|gif|pdf|xml)$', u, re.I))
        except requests.RequestException as e:
            warn.append(f'sitemap {sm}: {e}')
    return sorted(urls), warn


def _text(h):
    h = re.sub(r'<script.*?</script>|<style.*?</style>', ' ', h, flags=re.S | re.I)
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', h)))


def internal_nofollow(h, page_url, host):
    """Links to the site's own pages marked rel=nofollow: they tell Google not to pass value to the hotel's pages."""
    out = []
    for m in re.finditer(r'<a\b[^>]*>', h, re.I):
        tag = m.group(0)
        rel = re.search(r'rel=["\']([^"\']*)["\']', tag, re.I)
        href = re.search(r'href=["\']([^"\']+)["\']', tag, re.I)
        if not rel or 'nofollow' not in rel.group(1).lower() or not href:
            continue
        u = urljoin(page_url, href.group(1))
        if urlparse(u).netloc.replace('www.', '') == host and not href.group(1).startswith('#'):
            out.append(u)
    return sorted(set(out))


def fact_places(facts_file):
    """{place name: km} from hotel-facts.json lines like "Expo City Dubai: 11.9 km by road" (superseded facts are
    ignored). "Dubai Marina (Marina Mall)" also gives "Dubai Marina" and "Marina Mall"."""
    if not facts_file or not paths.resolve(facts_file).exists():
        return {}
    out = {}
    for x in json.loads(paths.resolve(facts_file).read_text(encoding='utf-8')).get('facts', []):
        m = FACT_DIST.match(str(x.get('fact') or '')) if not x.get('superseded') else None
        if not m:
            continue
        name = m.group('place').strip()
        for n in {name, re.sub(r'\s*\(.*?\)', '', name).strip(), *re.findall(r'\(([^)]+)\)', name)}:
            if len(n) > 3 and not re.search(r'\d{4}', n):
                out.setdefault(n, m.group('km'))
    return out


def site_places(texts):
    """Place names the site itself writes right before a distance in km."""
    names = set()
    for t in texts:
        for m in SITE_PLACE.finditer(t):
            n = re.sub(r'^the\s+', '', m.group(1).strip(), flags=re.I).strip(' .,:;')
            if len(n) >= 4 and n.lower() not in STOP:
                names.add(n)
    return names


def distances(txt, names, brand=''):
    """(place, km, snippet) for each "<place> ... N km" in the text. The longest known name wins where names overlap
    ("Mall of the Emirates" over "Emirates"); a figure after another place name, or past the end of the clause,
    belongs to something else; a name with its own qualifier in front ("The Market Mall in Green Community", "The
    Els Club, Dubai Sports City", "Pavilion Al Furjan") is reported under that full name."""
    spans = []
    for n in sorted(names, key=len, reverse=True):
        for m in re.finditer(rf'(?<!\w){re.escape(n)}(?!\w)', txt, re.I):
            if not any(a <= m.start() < b or a < m.end() <= b for a, b, _ in spans):
                spans.append((m.start(), m.end(), n))
    spans.sort()
    brand_words = {w.lower() for w in re.findall(r'\w+', brand)}
    out = []
    for i, (a, b, n) in enumerate(spans):
        nxt = spans[i + 1][0] if i + 1 < len(spans) else len(txt)
        window = txt[b:min(b + 45, nxt)]
        cut = CLAUSE_END.search(window)
        window = window[:cut.start()] if cut else window
        m = NUM_KM.search(window)
        if not m:
            continue
        head = txt[max(0, a - 40):a]
        stops = list(BEFORE.finditer(head))
        prefix = head[stops[-1].end():] if stops else head
        prev_end = spans[i - 1][1] if i else -1
        if prev_end > a - len(prefix):
            prefix = txt[spans[i - 1][0]:a]
        quals = [w for w in re.findall(r"[A-Z][\w']*", prefix) if w.lower() not in STOP | brand_words]
        place = (prefix.strip(' ,') + ' ' + n).strip() if quals else n
        out.append((place, m.group(1), txt[max(0, a - 30):b + m.end() + 5].strip()))
    return out


def distance_rows(texts_by_url, facts_file='', brand='', landmarks=None):
    """Distances that disagree across pages, or with hotel-facts.json. texts_by_url: {url: visible text}.
    The hotel's own name is never a landmark ("Abar Hotel Apartments ... 0.9 km" is the hotel, not a place)."""
    facts = fact_places(facts_file)
    from .analysis import _strip_generic
    own = _strip_generic(re.sub(r'[^a-z0-9]', '', brand.lower())) if brand else ''
    found = {n for n in site_places(texts_by_url.values()) if not (own and own in n.lower().replace(' ', ''))}
    names = set(landmarks or DEFAULT_LANDMARKS) | set(facts) | found
    dist, snip = defaultdict(lambda: defaultdict(set)), {}
    for url, txt in texts_by_url.items():
        for lm, km, s in distances(txt, names, brand):
            dist[lm][km].add(url)
            snip.setdefault((lm, km), f'{urlparse(url).path}: "…{s}…"')
    rows = []
    for lm, figs in dist.items():
        want = facts.get(lm)
        if want:
            for k, v in sorted(figs.items()):
                if float(k) != float(want):
                    rows.append({'landmark': lm, 'facts_says': want, 'values': {k: sorted(v)[:5]},
                                 'detail': f'{k} km on {len(v)} page(s), hotel-facts.json says {want} km. '
                                           f'{snip[(lm, k)]}'})
        elif len(figs) > 1:
            rows.append({'landmark': lm, 'facts_says': None, 'values': {k: sorted(v)[:5] for k, v in figs.items()},
                         'detail': '; '.join(f'{k} km on {len(v)} page(s) e.g. {snip[(lm, k)]}'
                                             for k, v in sorted(figs.items()))})
    return rows


def faq_sets(h):
    sets = []
    for b in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', h, re.S | re.I):
        try:
            d = json.loads(b)
        except ValueError:
            continue
        stack = [d]
        while stack:
            o = stack.pop()
            if isinstance(o, dict):
                if o.get('@type') == 'FAQPage':
                    sets.append(tuple(sorted(str(q.get('name', '')).strip().lower() for q in o.get('mainEntity') or []
                                             if isinstance(q, dict))))
                stack.extend(o.values())
            elif isinstance(o, list):
                stack.extend(o)
    return sets


def run(site, out_dir='', facts_file='', landmarks=None, room_path='', progress=None):
    site = ('https://' + site if '//' not in site else site).rstrip('/')
    host = urlparse(site).netloc.replace('www.', '')
    from .audit import page_type
    old_years = '|'.join(str(y) for y in range(2015, date.today().year))
    s = requests.Session()
    s.headers['User-Agent'] = UA
    urls, warn = _sitemap_urls(s, site)
    problems, texts, faq_pages = [], {}, defaultdict(list)

    def add(kind, page, detail):
        problems.append({'type': kind, 'page': page, 'detail': detail})
    for i, url in enumerate(urls):
        if progress and i % 20 == 0:
            progress(f'{i}/{len(urls)} pages')
        try:
            h = _get(s, url)
        except requests.RequestException as e:
            add('FETCH', url, str(e)[:200])
            continue
        path = urlparse(url).path or '/'
        title = html.unescape((re.search(r'<title[^>]*>(.*?)</title>', h, re.S | re.I) or [None, ''])[1]).strip()
        m = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']*)["\']', h, re.I) or \
            re.search(r'<meta[^>]+content=["\']([^"\']*)["\'][^>]+name=["\']description["\']', h, re.I)
        meta = html.unescape(m.group(1)) if m else ''
        txt = texts[url] = _text(h)
        if re.search(r' [-–] [^|]+$', title) and '|' not in title:
            add('TITLE-DEFAULT', path, f"'{title}' (WordPress default; use the site's title format)")
        if re.search(rf'\b({old_years})\b', title):
            add('TITLE-OLD-YEAR', path, f"'{title}'")
        if len(title) > 60:
            add('TITLE-LONG', path, f"{len(title)} chars, Google may cut it (fix if cheap): '{title}'")
        faqs = faq_sets(h)
        if len(faqs) > 1:
            add('FAQ-MULTI', path, f'{len(faqs)} FAQPage blocks: keep one per page')
        for f in faqs:
            if f:
                faq_pages[f].append(path)
        if not meta:
            add('META-MISSING', path, '')
        elif len(meta) > 155:
            add('META-LONG', path, f'{len(meta)} chars')
        nf = internal_nofollow(h, url, host)
        if nf:
            add('INTERNAL-NOFOLLOW', path, f'{len(nf)} internal link(s) marked nofollow: ' + ', '.join(nf[:5]))
        is_room = (room_path and room_path in path) or (not room_path and page_type(url, host) == 'rooms'
                                                        and path.rstrip('/').count('/') >= 2)
        if is_room:
            g_body = set(re.findall(r'[Uu]p to (\d+) [Gg]uests', txt))
            g_meta = set(re.findall(r'(?:up to|for) (\d+)', meta))
            if g_meta and g_body and not g_meta & g_body:
                add('ROOM-GUESTS', path, f'body says {sorted(g_body)}, meta says {sorted(g_meta)}')
            if len(g_body) > 1:
                add('ROOM-GUESTS', path, f"body has several 'up to N guests' figures {sorted(g_body)}")
            own = set(re.findall(SIZE, title, re.I)) | set(re.findall(SIZE, meta, re.I))
            body = set(re.findall(SIZE, txt, re.I))
            if own and body and not own <= body:
                add('ROOM-SIZE', path, f'title/meta {sorted(own)} vs body {sorted(body)}')
            if not re.search(r'"@type"\s*:\s*"(HotelRoom|Suite|Accommodation|Apartment|Product)"', h):
                add('ROOM-SCHEMA', path, 'no room-level schema (HotelRoom / Suite with occupancy and bed)')
    for f, ps in faq_pages.items():
        if len(ps) > 1:
            add('FAQ-DUPLICATE', ', '.join(ps[:10]), f'the same {len(f)} FAQ questions on {len(ps)} pages: keep them '
                                                     'only where they belong')
    for row in distance_rows(texts, facts_file, host.split('.')[0], landmarks):
        add('DISTANCE', row['landmark'], row['detail'])
    out = {'site': site, 'checked_on': date.today().isoformat(), 'pages': len(urls), 'warnings': warn,
           'problems': problems,
           'counts': {k: sum(p['type'] == k for p in problems) for k in sorted({p['type'] for p in problems})},
           'facts_file': facts_file or None, 'known_distances': len(fact_places(facts_file)),
           'note': 'Check every DISTANCE row by hand against its quoted text: two figures can be two different places '
                   '(a gate vs a building). TITLE-LONG is fix-if-cheap. Work is not done while any other row is open.'}
    if out_dir:
        d = paths.resolve(out_dir)
        d.mkdir(parents=True, exist_ok=True)
        (d / 'consistency.json').write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding='utf-8')
        out['file'] = str(d / 'consistency.json')
    return out
