"""Site checks run in code on every page, from the crawl's link graph and the HTML audit_site already scans
(registry 1.7):

  orphan_key_page / orphan_page   L01  a page with no internal links to it (rooms, offers, dining, spa and meetings: High)
  key_page_too_deep               L02  a key page more than MAX_CLICK_DEPTH clicks from its hotel's main page
  hreflang_incomplete             T15  extends analysis.hreflang_report: missing EN/AR version, self-reference, x-default
  boilerplate_shared              O20  the same sentence on > BOILERPLATE_SHARE of one hotel's room / offer / area pages
  link_preview_missing            O21  og:title / og:image missing or the image doesn't load (WhatsApp shares)
  heading_level_skipped / _empty  O04  H2 -> H4 jumps and heading tags with no text (Elementor)
  generic_anchor_text             L05  "Read more" / "Click here" share of a page's internal links
  url_variant_duplicate           T08  a case or trailing-slash variant answering 200 with no redirect or canonical

run() takes what audit_site has (scanned pages, crawl.json, the site registry) and returns the report section and the
issues; each issue carries its own re-check. The LIVE functions at the bottom are those re-check types:
checks.run_check dispatches to them, so /hotel-seo recheck proves each fix on the live site.
"""
import json
import math
import re
from collections import Counter, defaultdict, deque
from urllib.parse import urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup

# ---------------------------------------------------------------- thresholds (registry section 3)

MAX_CLICK_DEPTH = 3              # clicks from the hotel's main page (group sites: the hotel's section page)
BOILERPLATE_MIN_WORDS = 8        # shorter sentences ("Book now and save") are UI, not copy
BOILERPLATE_SHARE = 0.30         # on more than this share of one hotel's pages of one kind
BOILERPLATE_MIN_PAGES = 3        # and on at least this many pages
BOILERPLATE_MIN_GROUP = 4        # kinds with fewer pages are not compared
BOILERPLATE_MAX_PER_PAGE = 5     # sentences listed per page
GENERIC_ANCHOR_SHARE = 0.25      # share of a page's in-content internal links
GENERIC_ANCHOR_MIN = 3           # and at least this many generic links
HEADINGS_MAX = 120               # headings stored per page
VARIANT_PROBES = 40              # key pages whose case / slash variants are requested live
LIVE_BFS_CAP = 300               # pages a live click-depth re-check may fetch

# ---------------------------------------------------------------- page kinds

KEY_KINDS = {'rooms', 'offers', 'dining', 'spa', 'meetings'}          # orphan_key_page (High)
DEPTH_KINDS = KEY_KINDS | {'contact'}
PREVIEW_KINDS = {'home', 'rooms', 'offers', 'dining', 'spa', 'meetings', 'contact', 'location'}
BOILERPLATE_KINDS = {'rooms', 'offers', 'location'}
SECTION = [('dining', re.compile(r'/(dining|restaurants?|bars?|cafes?|lounges?)(/|-|$)')),
           ('spa', re.compile(r'/(spa|wellness|fitness|gym)(/|-|$)')),
           ('meetings', re.compile(r'/(meetings?|events?|weddings?|conferences?|mice|venues?)(/|-|$)')),
           ('location', re.compile(r'/(location|getting-here|directions|area|neighbou?rhood|surroundings|nearby|'
                                   r'attractions?|things-to-do|explore)(/|-|$)'))]
# booking engine, legal and thank-you pages are left out of the orphan and depth checks
EXCLUDED_PATH = re.compile(r'/(privacy|terms|cookies?|legal|disclaimer|imprint|gdpr|sitemap|thank|thanks|thank-you|'
                           r'success|confirmation|my-account|account|login|register|cart|checkout|search|'
                           r'page/\d+|tag|category|author|feed)(/|-|$)', re.I)
GENERIC_ANCHOR = re.compile(
    r'^(read more|more|click here|here|learn more|view more|see more|discover more|find out more|more info|'
    r'more details|view details|continue reading|اقرأ المزيد|المزيد|انقر هنا|اضغط هنا|اكتشف المزيد|عرض المزيد)'
    r'[\s.…»›>→!]*$', re.I)
SENTENCE_END = re.compile(r'(?<=[.!?؟])\s+')
CHROME = re.compile('header|footer|popup')


def kind(url, ptype):
    """audit.page_type plus dining / spa / meetings / location from the path."""
    if ptype in ('home', 'rooms', 'offers', 'contact', 'booking', 'external'):
        return ptype
    path = urlparse(url).path.lower()
    for name, rx in SECTION:
        if rx.search(path):
            return name
    return ptype or 'other'


def excluded(url, k):
    from .audit import is_booking_href
    return k in ('booking', 'external') or bool(EXCLUDED_PATH.search(urlparse(url).path)) or is_booking_href(url)


def _host(u):
    return urlparse(u).netloc.lower().removeprefix('www.')


def norm(u):
    """Link-graph key: host without www, path without trailing slash, no query or fragment (path case kept)."""
    p = urlparse((u or '').split('#')[0])
    return _host(u) + ((p.path or '/').rstrip('/') or '/')


def same_url(a, b):
    """Exact address match (trailing slash and case count), host without www."""
    pa, pb = urlparse(a or ''), urlparse(b or '')
    return _host(a) == _host(b) and (pa.path or '/') == (pb.path or '/')


# ---------------------------------------------------------------- per-page extraction (audit.scan_pages, live checks)

def strip_chrome(soup):
    """A copy of the page without header, footer, nav and Elementor header / footer / popup templates."""
    s = BeautifulSoup(str(soup), 'html.parser')
    for t in s(['script', 'style', 'noscript', 'svg']):
        t.decompose()
    for t in s.find_all(['header', 'footer', 'nav']) + s.find_all(attrs={'data-elementor-type': CHROME}):
        t.decompose()
    return s


def og(soup):
    def prop(name):
        m = soup.find('meta', attrs={'property': name}) or soup.find('meta', attrs={'name': name})
        return (m.get('content') or '').strip() if m else ''
    return {'og_title': prop('og:title'), 'og_image': prop('og:image')}


def headings(main_soup):
    out = []
    for h in main_soup.find_all(re.compile(r'^h[1-6]$')):
        text = re.sub(r'\s+', ' ', h.get_text(' ')).strip() or \
            ' '.join((i.get('alt') or '').strip() for i in h.find_all('img')).strip()
        out.append([int(h.name[1]), text[:80]])
    return out[:HEADINGS_MAX]


def heading_problems(hs):
    """[[level, text], ...] in page order -> skipped levels (going down more than one step) and empty headings."""
    skipped, empty, prev = [], [], None
    for lvl, text in hs:
        if not text:
            empty.append(f'empty H{lvl}')
        if prev is not None and lvl > prev + 1:
            skipped.append(f'H{prev} → H{lvl}' + (f' ("{text[:40]}")' if text else ''))
        prev = lvl
    return {'skipped': skipped, 'empty': empty}


def anchor_stats(main_soup, page_url, home_host):
    """In-content internal links with text, and how many of them are generic ("Read more", "Click here")."""
    total, generic, links = 0, Counter(), []
    for a in main_soup.find_all('a', href=True):
        if a['href'].startswith('#'):
            continue
        href = urljoin(page_url, a['href'])
        if not href.startswith('http') or _host(href) != home_host:
            continue
        text = re.sub(r'\s+', ' ', a.get_text(' ')).strip()
        if not text:
            continue
        total += 1
        if GENERIC_ANCHOR.match(text):
            generic[text.lower()] += 1
            if [text, href] not in links:
                links.append([text, href])
    # each generic link with where it goes: execute renames it after the page it opens (report.core_findings)
    return {'body_links': total, 'generic_anchor_count': sum(generic.values()),
            'generic_anchors': dict(generic.most_common(5)), 'generic_links': links[:30]}


def generic_over(stats):
    n, g = stats.get('body_links', 0), stats.get('generic_anchor_count', 0)
    return g >= GENERIC_ANCHOR_MIN and n and g / n > GENERIC_ANCHOR_SHARE


def sentences(text):
    """Sentences of >= BOILERPLATE_MIN_WORDS words; a line break (end of a block element) also ends one."""
    out = []
    for line in (text or '').split('\n'):
        for s in SENTENCE_END.split(re.sub(r'\s+', ' ', line)):
            s = s.strip()
            if len(s.split()) >= BOILERPLATE_MIN_WORDS and s not in out:
                out.append(s[:300])
    return out[:80]


BLOCKS = ['p', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'div', 'td', 'th', 'dd', 'dt', 'blockquote', 'section',
          'article', 'figcaption', 'br']


def block_text(main_soup):
    """The body's text with a line break after every block element (headings and widgets never run into copy)."""
    body = BeautifulSoup(str(main_soup.body or main_soup), 'html.parser')
    for t in body.find_all(BLOCKS):
        t.append('\n')
    return body.get_text(' ')


def norm_sentence(s, name=''):
    """Compare form: lower case, the page's own name -> {name}, numbers -> #, no punctuation. Two room pages saying
    "The Deluxe Room offers 32 sqm..." and "The Superior Room offers 28 sqm..." become the same sentence."""
    t = ' ' + s.lower() + ' '
    name = (name or '').strip().lower()
    if len(name) >= 4:
        t = t.replace(name, ' {name} ')
    t = re.sub(r'\d+(?:[.,]\d+)?', '#', t)
    t = re.sub(r'[^\w{}#\s]', ' ', t)
    return re.sub(r'\s+', ' ', t).strip()


def page_extras(soup, main_soup, url, ptype, home_host):
    """Fields audit.scan_pages adds to each page for these checks (main_soup: header, footer, nav removed)."""
    out = og(soup)
    out['headings'] = headings(main_soup)
    out.update(anchor_stats(main_soup, url, home_host))
    if kind(url, ptype) in BOILERPLATE_KINDS:
        out['main_sentences'] = sentences(block_text(main_soup))
    return out


# ---------------------------------------------------------------- link graph

def link_graph(data, home_host):
    """Internal link graph from crawl.json: norm(source) -> {norm(target)}, redirects followed to the final page."""
    redirect = {norm(u['url']): norm(u['redirected_to']) for u in data.get('urls', [])
                if u.get('redirects') and u.get('redirected_to')}

    def final(u):
        k, seen = norm(u), set()
        while k in redirect and k not in seen:
            seen.add(k)
            k = redirect[k]
        return k
    graph = defaultdict(set)
    for l in data.get('links', []):
        t = l.get('target_url') or ''
        if _host(t) != home_host:
            continue
        s, t = final(l.get('source_url') or ''), final(t)
        if s != t:
            graph[s].add(t)
    for u in data.get('urls', []):
        t = final(u['url'])
        for src in u.get('linked_from') or []:
            s = final(src)
            if s != t and _host(src) == home_host:
                graph[s].add(t)
    return graph


def inlinks(graph):
    c = Counter()
    for s, ts in graph.items():
        for t in ts:
            c[t] += 1
    return c


def bfs(graph, starts):
    dist, q = {}, deque()
    for s in starts:
        dist[s] = 0
        q.append(s)
    while q:
        u = q.popleft()
        for v in graph.get(u, ()):
            if v not in dist:
                dist[v] = dist[u] + 1
                q.append(v)
    return dist


def hotel_mains(site, reg):
    """slug -> the hotel's main URLs (group: its section paths; single hotel: the homepage)."""
    root = site.rstrip('/')
    if not reg or len(reg.get('hotels', [])) <= 1:
        return {'site': [root + '/']}
    out = {h['slug']: [root + p for p in h.get('paths') or ['/']] for h in reg['hotels']}
    out['group'] = [root + '/']
    return out


def owner(url, reg):
    if not reg or len(reg.get('hotels', [])) <= 1:
        return 'site'
    from . import group as grp
    return grp.hotel_for(url, reg)


def _indexable_self(p, url):
    if 'noindex' in (p.get('robots', '') + ' ' + p.get('x_robots_tag', '')).lower():
        return False
    c = p.get('canonical') or ''
    return not c or norm(urljoin(url, c)) == norm(url)


# ---------------------------------------------------------------- the checks

def orphans(pages, graph, mains, extra=()):
    inl, main_keys, extra = inlinks(graph), {norm(u) for us in mains.values() for u in us}, set(extra)
    out = []
    for u, p in pages.items():
        k = kind(u, p.get('type'))
        if norm(u) in main_keys or k == 'home' or excluded(u, k) or not _indexable_self(p, u):
            continue
        if inl.get(norm(u), 0) == 0:
            out.append({'url': u, 'kind': k, 'key': k in KEY_KINDS,
                        'found_in': 'sitemap / WordPress only' if u in extra else 'crawl (no page links to it)'})
    return out


def depth_report(pages, graph, mains, reg, orphan_urls=()):
    dist = {slug: bfs(graph, [norm(u) for u in us]) for slug, us in mains.items()}
    site_main = mains.get('group') or mains.get('site')
    out = []
    for u, p in pages.items():
        k = kind(u, p.get('type'))
        if k not in DEPTH_KINDS or excluded(u, k) or u in orphan_urls or not _indexable_self(p, u):
            continue
        slug = owner(u, reg)
        start = mains.get(slug) or site_main
        d = dist.get(slug if slug in mains else ('group' if 'group' in mains else 'site'), {}).get(norm(u))
        if d is None or d > MAX_CLICK_DEPTH:
            out.append({'url': u, 'kind': k, 'hotel': slug, 'start': start[0], 'clicks': d})
    return out


def hreflang_sets(pages, mains):
    """Completes analysis.hreflang_report for EN/AR (Polylang) sites: every key page has each site language linked,
    each set lists the page itself, and the home / hotel main pages carry x-default."""
    langs = {c.split('-')[0].lower() for p in pages.values() for c in (p.get('hreflang') or {}) if c != 'x-default'}
    if len(langs) < 2:
        return {'languages': sorted(langs), 'incomplete': []}
    main_keys = {norm(u) for us in mains.values() for u in us}
    out = []
    for u, p in pages.items():
        if not _indexable_self(p, u):
            continue
        k = kind(u, p.get('type'))
        alts = p.get('hreflang') or {}
        probs = []
        if not alts:
            if k in PREVIEW_KINDS - {'location'} and not excluded(u, k):
                probs.append('no hreflang tags (no linked translation)')
        else:
            have = {c.split('-')[0].lower() for c in alts if c != 'x-default'}
            probs += [f'no {lang} version linked' for lang in sorted(langs - have)]
            if norm(u) not in {norm(v) for v in alts.values()}:
                probs.append('the set does not list the page itself')
            if (norm(u) in main_keys or k == 'home') and 'x-default' not in alts:
                probs.append('no x-default')
        if probs:
            out.append({'url': u, 'kind': k, 'problems': probs, 'x_default': norm(u) in main_keys or k == 'home',
                        'languages': sorted(langs)})
    return {'languages': sorted(langs), 'incomplete': out}


def boilerplate(pages, reg):
    """Sentences shared by > BOILERPLATE_SHARE of one hotel's room / offer / area pages (name-swapped copy)."""
    groups = defaultdict(list)
    for u, p in pages.items():
        k = kind(u, p.get('type'))
        if k in BOILERPLATE_KINDS and p.get('main_sentences'):
            groups[(owner(u, reg), k)].append(u)
    rows, per_page = [], defaultdict(list)
    for (slug, k), urls in sorted(groups.items()):
        n = len(urls)
        if n < BOILERPLATE_MIN_GROUP:
            continue
        seen = defaultdict(dict)                     # normalised sentence -> {url: the page's own wording}
        for u in urls:
            p = pages[u]
            name = (p.get('h1') or [''])[0]
            for s in p['main_sentences']:
                seen[norm_sentence(s, name)].setdefault(u, s)
        need = max(BOILERPLATE_MIN_PAGES, math.floor(BOILERPLATE_SHARE * n) + 1)
        for key, by_url in seen.items():
            if len(by_url) >= need and len(by_url) / n > BOILERPLATE_SHARE:
                example = next(iter(by_url.values()))
                rows.append({'hotel': slug, 'kind': k, 'sentence': example, 'pages': len(by_url), 'of': n,
                             'urls': sorted(by_url)})
                for u, s in by_url.items():
                    per_page[u].append((s, len(by_url), n, k))
    return {'shared': sorted(rows, key=lambda r: -r['pages']), 'per_page': per_page}


def link_previews(pages, mains, image_status):
    main_keys = {norm(u) for us in mains.values() for u in us}
    out = []
    for u, p in pages.items():
        k = kind(u, p.get('type'))
        if k not in PREVIEW_KINDS and norm(u) not in main_keys:
            continue
        probs = []
        if not p.get('og_title'):
            probs.append('no og:title')
        img = p.get('og_image') or ''
        if not img:
            probs.append('no og:image')
        else:
            st = image_status(urljoin(u, img))
            if st != 200:
                probs.append(f'og:image {img} returns {st or "no answer"}')
        if probs:
            out.append({'url': u, 'kind': k, 'problems': probs})
    return out


def heading_report(pages):
    out = []
    for u, p in pages.items():
        if 'headings' not in p:
            continue
        pr = heading_problems(p['headings'])
        if pr['skipped'] or pr['empty']:
            out.append({'url': u, **pr})
    return out


def generic_anchor_report(pages):
    return [{'url': u, 'generic': p['generic_anchor_count'], 'links': p['body_links'],
             'anchors': p.get('generic_anchors', {})} for u, p in pages.items() if generic_over(p)]


def variants(url):
    """The trailing-slash twin and a case variant of a URL ('/rooms/' -> '/rooms', '/Rooms/')."""
    p = urlparse(url)
    path = p.path or '/'
    if path == '/':
        return []
    out = [path[:-1] if path.endswith('/') else path + '/']
    if path != path.lower():
        out.append(path.lower())
    else:
        m = re.search(r'[a-z]', path)
        if m:
            out.append(path[:m.start()] + path[m.start()].upper() + path[m.start() + 1:])
    return [urlunparse(p._replace(path=v, query='', fragment='')) for v in out]


def variant_ok(page_url, variant, res):
    """A variant is handled when it redirects, is gone, or answers 200 with a canonical to the page."""
    st = res.get('status') or 0
    if 300 <= st < 400 or 400 <= st < 500:
        return True
    if st != 200:
        return True                                   # unreachable / 5xx: not a duplicate (other checks report errors)
    c = res.get('canonical') or ''
    return bool(c) and same_url(urljoin(variant, c), page_url)


def url_duplicates(pages, data, mains, probe, probes=VARIANT_PROBES):
    """Case / trailing-slash variants that both answer 200: from the crawl (two crawled addresses of one page) and by
    requesting the variants of the key pages live."""
    from .librecrawl import is_page
    out, seen = [], set()
    groups = defaultdict(list)
    for u in data.get('urls', []):
        if is_page(u):
            p = urlparse(u['url'])
            groups[_host(u['url']) + (p.path or '/').lower().rstrip('/')].append(u)
    inl = Counter(l.get('target_url') for l in data.get('links', []))
    for members in groups.values():
        addrs = {m['url']: m for m in members}
        if len(addrs) < 2:
            continue
        canons = [m.get('canonical_url') or (pages.get(a) or {}).get('canonical') or '' for a, m in addrs.items()]
        canons = [urljoin(a, c) for a, c in zip(addrs, canons) if c]
        if len(canons) == len(addrs) and all(same_url(c, canons[0]) for c in canons):
            continue                                  # every variant names the same canonical
        main = max(addrs, key=lambda a: (a in pages, urlparse(a).path == urlparse(a).path.lower(), inl.get(a, 0)))
        for a in addrs:
            if a != main and (main, a) not in seen:
                seen.add((main, a))
                out.append({'url': main, 'variant': a, 'status': 200, 'source': 'crawl'})
    main_keys = {norm(u) for us in mains.values() for u in us}
    key = [u for u, p in pages.items() if kind(u, p.get('type')) in PREVIEW_KINDS or norm(u) in main_keys]
    for u in key[:probes]:
        for v in variants(u):
            if any(same_url(v, x['variant']) for x in out):
                continue
            res = probe(v)
            if not variant_ok(u, v, res):
                out.append({'url': u, 'variant': v, 'status': res.get('status'), 'source': 'live request'})
    return out


# ---------------------------------------------------------------- live helpers (audit) and run()

def _session():
    import requests
    from .librecrawl import UA
    s = requests.Session()
    s.headers['User-Agent'] = UA
    return s


def live_image_status(session=None):
    s, cache = session or _session(), {}

    def status(url):
        if url not in cache:
            try:
                r = s.head(url, allow_redirects=True, timeout=15)
                if r.status_code >= 400:
                    r = s.get(url, allow_redirects=True, timeout=20, stream=True)
                    r.close()
                cache[url] = r.status_code
            except Exception:
                cache[url] = 0
        return cache[url]
    return status


def live_probe(session=None):
    s = session or _session()

    def probe(url):
        try:
            r = s.get(url, allow_redirects=False, timeout=20)
        except Exception:
            return {'status': 0}
        out = {'status': r.status_code, 'location': r.headers.get('Location', '')}
        if r.status_code == 200 and 'html' in r.headers.get('content-type', 'text/html'):
            link = BeautifulSoup(r.text, 'html.parser').find('link', rel=lambda v: v and 'canonical' in v)
            out['canonical'] = link.get('href', '') if link else ''
        return out
    return probe


def run(pages, data, home_host, site, reg=None, extra=(), image_status=None, probe=None):
    """All checks above. Returns {'report': ..., 'issues': [{check, url, detail, sev, recheck}]}."""
    mains = hotel_mains(site, reg)
    graph = link_graph(data, home_host)
    has_links = bool(graph)
    orph = orphans(pages, graph, mains, extra) if has_links else []
    deep = depth_report(pages, graph, mains, reg, {o['url'] for o in orph}) if has_links else []
    hl = hreflang_sets(pages, mains)
    bp = boilerplate(pages, reg)
    prev = link_previews(pages, mains, image_status or live_image_status())
    heads = heading_report(pages)
    gen = generic_anchor_report(pages)
    dups = url_duplicates(pages, data, mains, probe or live_probe())
    issues = []

    def add(check, url, detail, recheck, sev=None):
        issues.append({'check': check, 'url': url, 'detail': detail, 'sev': sev, 'recheck': recheck})

    for o in orph:
        add('orphan_key_page' if o['key'] else 'orphan_page', o['url'],
            f"0 internal links; {o['kind']} page found in the {o['found_in']}",
            {'type': 'inlinked', 'url': o['url']}, 'Priority' if o['key'] else None)
    for d in deep:
        add('key_page_too_deep', d['url'],
            (f"{d['clicks']} clicks" if d['clicks'] is not None else 'no link path') + f" from {d['start']}",
            {'type': 'click_depth', 'url': d['url'], 'source': d['start'], 'expected': MAX_CLICK_DEPTH})
    for h in hl['incomplete']:
        add('hreflang_incomplete', h['url'], '; '.join(h['problems']),
            {'type': 'hreflang_ok', 'url': h['url'], 'languages': h['languages'], 'x_default': h['x_default']})
    for u, items in bp['per_page'].items():
        for s, k, n, kd in sorted(items, key=lambda x: -x[1])[:BOILERPLATE_MAX_PER_PAGE]:
            add('boilerplate_shared', u, f'"{s}" (on {k} of {n} {kd} pages)',
                {'type': 'text_absent', 'url': u, 'text': s})
    for x in prev:
        add('link_preview_missing', x['url'], '; '.join(x['problems']), {'type': 'og_present', 'url': x['url']})
    for x in heads:
        if x['skipped']:
            add('heading_level_skipped', x['url'], ', '.join(x['skipped'][:8]),
                {'type': 'heading_levels', 'url': x['url'], 'what': 'skipped'})
        if x['empty']:
            add('heading_empty', x['url'], f"{len(x['empty'])} empty heading(s): " + ', '.join(sorted(set(x['empty']))),
                {'type': 'heading_levels', 'url': x['url'], 'what': 'empty'})
    for x in gen:
        add('generic_anchor_text', x['url'], f"{x['generic']} of {x['links']} in-content links: "
            + ', '.join(f'"{a}" ×{n}' for a, n in x['anchors'].items()),
            {'type': 'generic_anchors_max', 'url': x['url'], 'expected': GENERIC_ANCHOR_SHARE})
    for x in dups:
        add('url_variant_duplicate', x['url'], f"{x['variant']} answers {x['status']} with no redirect or canonical "
            f"to this page ({x['source']})", {'type': 'variant_resolved', 'url': x['url'], 'source': x['variant']})
    report = {
        'thresholds': {'max_click_depth': MAX_CLICK_DEPTH, 'boilerplate_share': BOILERPLATE_SHARE,
                       'boilerplate_min_words': BOILERPLATE_MIN_WORDS, 'generic_anchor_share': GENERIC_ANCHOR_SHARE,
                       'generic_anchor_min': GENERIC_ANCHOR_MIN},
        'link_data': has_links, 'orphans': orph, 'too_deep': deep, 'hreflang': hl, 'boilerplate': bp['shared'][:100],
        'link_previews': prev, 'headings': heads[:300], 'generic_anchors': gen, 'url_duplicates': dups,
        'counts': {'orphan_key_pages': sum(o['key'] for o in orph), 'orphan_pages': sum(not o['key'] for o in orph),
                   'too_deep': len(deep), 'hreflang_incomplete': len(hl['incomplete']),
                   'boilerplate_sentences': len(bp['shared']), 'link_previews_missing': len(prev),
                   'heading_skips': sum(1 for x in heads if x['skipped']),
                   'heading_empty': sum(1 for x in heads if x['empty']), 'generic_anchor_pages': len(gen),
                   'url_duplicates': len(dups)}}
    return {'report': report, 'issues': issues}


# ---------------------------------------------------------------- re-check types (checks.run_check -> LIVE)

def _fetch(f, u):
    r, soup = f.get(u)
    return (None, None) if isinstance(r, Exception) else (r, soup)


def _links_of(r, soup):
    base = getattr(r, 'url', '') or ''
    return {norm(urljoin(base, a['href'])) for a in soup.find_all('a', href=True) if not a['href'].startswith('#')}


def live_inlinked(c, f, sitewide):
    target = norm(f.url(c['url']))
    pages = [u for u in dict.fromkeys(f.url(x) for x in (sitewide or ['/'])) if norm(u) != target]
    for u in pages:
        r, soup = _fetch(f, u)
        if soup is not None and target in _links_of(r, soup):
            return {'result': 'pass', 'actual': f'linked from {u}'}
    return {'result': 'fail', 'actual': f'no link to it on the {len(pages)} page(s) checked'}


def live_click_depth(c, f, sitewide):
    target, limit = norm(f.url(c['url'])), int(c.get('expected', MAX_CLICK_DEPTH))
    start = f.url(c.get('source') or '/')
    host = _host(start)
    frontier, seen, fetched = [start], {norm(start)}, 0
    for depth in range(limit + 1):
        if target in {norm(u) for u in frontier}:
            return {'result': 'pass', 'actual': f'{depth} click(s) from {start}'}
        if depth == limit:
            break
        nxt = []
        for u in frontier:
            if fetched >= LIVE_BFS_CAP:
                return {'result': 'fail', 'actual': f'not found in the first {LIVE_BFS_CAP} pages within {limit} clicks'}
            r, soup = _fetch(f, u)
            fetched += 1
            if soup is None:
                continue
            for a in soup.find_all('a', href=True):
                v = urljoin(getattr(r, 'url', '') or u, a['href']).split('#')[0]
                if v.startswith('http') and _host(v) == host and norm(v) not in seen:
                    seen.add(norm(v))
                    nxt.append(v)
        frontier = nxt
    return {'result': 'fail', 'actual': f'more than {limit} clicks from {start}'}


def live_hreflang_ok(c, f, sitewide):
    from .analysis import _hreflang_code_ok
    r, soup = _fetch(f, c['url'])
    if soup is None:
        return {'result': 'fail', 'actual': 'page did not load'}
    base = getattr(r, 'url', '') or f.url(c['url'])
    alts = {(l.get('hreflang') or '').strip(): urljoin(base, l.get('href') or '')
            for l in soup.find_all('link', rel=lambda v: v and 'alternate' in v, hreflang=True)}
    if not alts:
        return {'result': 'fail', 'actual': 'no hreflang tags'}
    me = norm(base)
    probs = [f'invalid code "{k}"' for k in alts if not _hreflang_code_ok(k)]
    if me not in {norm(v) for v in alts.values()}:
        probs.append('no self-reference')
    if c.get('x_default') and 'x-default' not in alts:
        probs.append('no x-default')
    have = {k.split('-')[0].lower() for k in alts if k != 'x-default'}
    probs += [f'no {lang} version' for lang in c.get('languages', []) if lang not in have]
    for code, t in alts.items():
        if code == 'x-default' or norm(t) == me:
            continue
        tr, ts = _fetch(f, t)
        if tr is None or ts is None:
            probs.append(f'{code} → {t} did not load')
            continue
        if tr.history or tr.status_code != 200:
            probs.append(f'{code} → {t} returns {tr.history[0].status_code if tr.history else tr.status_code}')
            continue
        rob = ts.find('meta', attrs={'name': re.compile('^robots$', re.I)})
        if rob and 'noindex' in (rob.get('content') or '').lower():
            probs.append(f'{code} → {t} is noindex')
        can = ts.find('link', rel=lambda v: v and 'canonical' in v)
        if can and can.get('href') and norm(urljoin(t, can['href'])) != norm(t):
            probs.append(f'{code} → {t} canonical points elsewhere')
        back = {norm(urljoin(t, l.get('href') or ''))
                for l in ts.find_all('link', rel=lambda v: v and 'alternate' in v, hreflang=True)}
        if me not in back:
            probs.append(f'{code} → {t} does not link back')
    return {'result': 'fail' if probs else 'pass', 'actual': '; '.join(probs) or f'{len(alts)} alternates, all correct'}


def live_og_present(c, f, sitewide):
    r, soup = _fetch(f, c['url'])
    if soup is None:
        return {'result': 'fail', 'actual': 'page did not load'}
    o, probs = og(soup), []
    if not o['og_title']:
        probs.append('no og:title')
    if not o['og_image']:
        probs.append('no og:image')
    else:
        st = live_image_status(f.s)(urljoin(getattr(r, 'url', '') or f.url(c['url']), o['og_image']))
        if st != 200:
            probs.append(f'og:image returns {st or "no answer"}')
    return {'result': 'fail' if probs else 'pass', 'actual': '; '.join(probs) or 'og:title and og:image present'}


def live_heading_levels(c, f, sitewide):
    r, soup = _fetch(f, c['url'])
    if soup is None:
        return {'result': 'fail', 'actual': 'page did not load'}
    pr = heading_problems(headings(strip_chrome(soup)))
    bad = pr['empty'] if c.get('what') == 'empty' else pr['skipped'] if c.get('what') == 'skipped' \
        else pr['skipped'] + pr['empty']
    return {'result': 'fail' if bad else 'pass', 'actual': ', '.join(bad[:8]) or 'heading levels fine'}


def live_generic_anchors(c, f, sitewide):
    r, soup = _fetch(f, c['url'])
    if soup is None:
        return {'result': 'fail', 'actual': 'page did not load'}
    base = getattr(r, 'url', '') or f.url(c['url'])
    st = anchor_stats(strip_chrome(soup), base, _host(base))
    over = generic_over(st)
    return {'result': 'fail' if over else 'pass',
            'actual': f"{st['generic_anchor_count']} of {st['body_links']} in-content links generic"}


def live_variant_resolved(c, f, sitewide):
    page, variant = f.url(c['url']), f.url(c['source'])
    res = live_probe(f.s)(variant)
    ok = variant_ok(page, variant, res)
    return {'result': 'pass' if ok else 'fail',
            'actual': f"{variant} answers {res.get('status')}" + (f" → {res['location']}" if res.get('location') else '')
            + (f", canonical {res['canonical']}" if res.get('canonical') else '')}


LIVE = {'inlinked': live_inlinked, 'click_depth': live_click_depth, 'hreflang_ok': live_hreflang_ok,
        'og_present': live_og_present, 'heading_levels': live_heading_levels,
        'generic_anchors_max': live_generic_anchors, 'variant_resolved': live_variant_resolved}
DESCRIBE = {
    'inlinked': lambda c: f"a page on the site links to {c.get('url')}",
    'click_depth': lambda c: f"{c.get('url')} at most {c.get('expected', MAX_CLICK_DEPTH)} clicks from {c.get('source')}",
    'hreflang_ok': lambda c: f"hreflang set on {c.get('url')} complete and linked back",
    'og_present': lambda c: f"og:title and a loading og:image on {c.get('url')}",
    'heading_levels': lambda c: f"no {'empty headings' if c.get('what') == 'empty' else 'skipped heading levels'} "
                                f"on {c.get('url')}",
    'generic_anchors_max': lambda c: f"generic anchors at most {int(float(c.get('expected', GENERIC_ANCHOR_SHARE)) * 100)}% "
                                     f"of in-content links on {c.get('url')}",
    'variant_resolved': lambda c: f"{c.get('source')} redirects or is canonical to {c.get('url')}",
}
