"""Site audit: every count and finding is computed here, not by the model.

Reads the crawl (crawl.json), fetches every 200 page's HTML once, and adds the WordPress
REST API, booking-link checks and Search Console spam queries. Writes to the crawl folder:

  findings.json   counts, per-URL issues with page type and severity, WordPress and security data
  findings.md     the same as a readable summary with full counts (never samples)
  site_text.json  visible text per page (the [CONFIRM] guard checks facts against it)

Severity rule (playbook section 4): issues on the homepage, room pages, offers, contact and the
booking path are always Priority.
"""
import json
import re
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from . import analysis, consistency, paths
from .librecrawl import UA, is_page

CRITICAL_TYPES = {'home', 'rooms', 'offers', 'contact', 'booking'}
SPAM_QUERY = re.compile(
    r'casino|slot|gacor|togel|judi|\bbet\b|betting|poker|\btoto\b|viagra|cialis|porn|\bsex\b|xxx|'
    r'escort|loan|crypto|bitcoin|[a-z]{3,}\d{2,}\b', re.I)
SEO_PLUGINS = {'rankmath/v1': 'Rank Math', 'yoast/v1': 'Yoast SEO', 'aioseo/v1': 'All in One SEO',
               'seopress/v1': 'SEOPress'}
RISKY_NAMESPACE = re.compile(r'mcp|abilit|wp-content-server|elementor-mcp', re.I)
BOOK_TEXT = re.compile(r'\bbook\b|book now|reserve|check availability|availability', re.I)
# what the SEO plugin prints into the page (the REST namespace only says it is installed and active)
SEO_HTML = {'Rank Math': re.compile(r'rank-math|rankmath', re.I), 'Yoast SEO': re.compile(r'yoast', re.I),
            'All in One SEO': re.compile(r'aioseo', re.I), 'SEOPress': re.compile(r'seopress', re.I)}
# browser-side translation: Google can't index the translated text
TRANSLATE_HTML = {'GTranslate': re.compile(r'gtranslate', re.I), 'Weglot': re.compile(r'weglot', re.I),
                  'ConveyThis': re.compile(r'conveythis', re.I),
                  'Google Translate widget': re.compile(r'translate\.google\.com/translate_a', re.I)}


def page_type(url, home_host):
    p = urlparse(url)
    path = p.path.lower()
    if p.netloc.replace('www.', '') != home_host:
        return 'external'
    if path in ('', '/'):
        return 'home'
    if re.search(r'/(rooms?|suites?|accommodation|apartments?)(/|-|$)', path):
        return 'rooms'
    if re.search(r'offer|package|deal|promo|staycation', path):
        return 'offers'
    if 'contact' in path:
        return 'contact'
    if re.search(r'book|reserv', path):
        return 'booking'
    if re.search(r'/(blog|blogs|news|tag|category|author)/', path):
        return 'blog'
    return 'other'


def severity(ptype):
    return 'Priority' if ptype in CRITICAL_TYPES else 'Secondary'


def _get(session, url, **kw):
    try:
        return session.get(url, timeout=25, **kw)
    except requests.RequestException:
        return None


# ---------------------------------------------------------------- pages

def is_booking_href(href):
    p = urlparse(href)
    return bool('idtokenprovider' in href or 'mirai' in p.netloc or 'bookingstep' in p.path.lower()
                or re.search(r'/search/?$', p.path) and p.query or re.search(r'reserv|booking-engine', p.netloc))


def booking_link_problems(href, today=None, main_currency='AED'):
    """Old booking-engine addresses and stale parameters (a 2023 check-in date, a foreign currency)."""
    probs = []
    q = parse_qs(urlparse(href).query)
    if 'bookingstep' in urlparse(href).path.lower():
        probs.append('old booking-step address')
    for key in ('checkin', 'checkIn', 'arrival'):
        for v in q.get(key, []):
            m = re.match(r'(\d{1,2})/(\d{1,2})/(\d{4})', v) or re.match(r'(\d{4})-(\d{2})-(\d{2})', v)
            if m:
                g = m.groups()
                try:
                    d = date(int(g[2]), int(g[1]), int(g[0])) if len(g[0]) <= 2 else date(int(g[0]), int(g[1]), int(g[2]))
                except ValueError:
                    continue
                if d < (today or date.today()):
                    probs.append(f'check-in date in the past ({v})')
    cur = (q.get('currency') or [''])[0]
    if cur and main_currency and cur.upper() != main_currency.upper():
        probs.append(f'currency {cur} (the site mostly uses {main_currency})')
    return probs


def scan_pages(urls, home_host, delay=0.3, progress=None):
    s = requests.Session()
    s.headers['User-Agent'] = UA
    pages, texts, links = {}, {}, []
    for n, url in enumerate(urls, 1):
        r = _get(s, url)
        if r is None or r.status_code != 200:
            pages[url] = {'fetch_status': r.status_code if r is not None else 0}
            continue
        html = r.text
        soup = BeautifulSoup(html, 'html.parser')
        jsonld_types, jsonld_errors, nodes_summary = [], [], []
        for tag in soup.find_all('script', type='application/ld+json'):
            raw = tag.string or tag.get_text() or ''
            try:
                data = json.loads(raw)
            except (ValueError, TypeError) as e:
                guess = re.search(r'"@type"\s*:\s*\[?\s*"([^"]+)"', raw)
                jsonld_errors.append(f"{guess.group(1) if guess else 'unknown'} block: {str(e)[:90]}")
                continue
            nodes_summary.extend(analysis.jsonld_nodes(data))
            nodes = data.get('@graph', [data]) if isinstance(data, dict) else data if isinstance(data, list) else []
            for node in nodes:
                if isinstance(node, dict):
                    t = node.get('@type')
                    jsonld_types.extend(t if isinstance(t, list) else [t] if t else [])
        meta = soup.find('meta', attrs={'name': re.compile('^description$', re.I)})
        robots = soup.find('meta', attrs={'name': re.compile('^robots$', re.I)})
        canon = soup.find('link', rel=lambda v: v and 'canonical' in v)
        h1s = [re.sub(r'\s+', ' ', h.get_text(' ')).strip() for h in soup.find_all('h1')]
        pages[url] = {
            'type': page_type(url, home_host),
            'title': re.sub(r'\s+', ' ', soup.title.get_text()).strip() if soup.title else '',
            'meta_description': (meta.get('content') or '').strip() if meta else '',
            'h1': h1s,
            'canonical': canon.get('href', '') if canon else '',
            'robots': robots.get('content', '') if robots else '',
            'jsonld_types': jsonld_types,
            'jsonld_errors': jsonld_errors,
            'gtm_ids': sorted(set(re.findall(r'GTM-[A-Z0-9]{4,}', html))),
            'gtag_ids': sorted(set(re.findall(r'\bG-[A-Z0-9]{6,}\b', html))),
            'x_robots_tag': r.headers.get('X-Robots-Tag', ''),
            'jsonld_nodes': nodes_summary,
            'seo_plugin_html': [name for name, rx in SEO_HTML.items() if rx.search(html[:200000])],
            'translation_plugin': [name for name, rx in TRANSLATE_HTML.items() if rx.search(html)],
            'hreflang_count': len(soup.find_all('link', rel=lambda v: v and 'alternate' in v, hreflang=True)),
            'hreflang': {(l.get('hreflang') or '').strip(): urljoin(url, l.get('href') or '')
                         for l in soup.find_all('link', rel=lambda v: v and 'alternate' in v, hreflang=True)},
            'html_lang': (soup.html.get('lang') or '').strip() if soup.html else '',
            'offer_valid_through': sorted(set(re.findall(
                r'"(?:validThrough|priceValidUntil)"\s*:\s*"(\d{4}-\d{2}-\d{2})', html))),
            'links_rooms': False, 'links_booking': False,
        }
        phones = set()
        for a in soup.find_all('a', href=True):
            href = urljoin(url, a['href'])
            text = re.sub(r'\s+', ' ', a.get_text(' ')).strip()
            if a['href'].lower().startswith('tel:'):
                d = re.sub(r'\D', '', a['href'])
                phones.add((d[2:] if d.startswith('00') else d)[-13:])
                continue
            if not href.startswith('http'):
                continue
            if is_booking_href(href) or BOOK_TEXT.search(text):
                links.append({'source': url, 'href': href.split('#')[0], 'text': text[:80]})
                pages[url]['links_booking'] = True
            elif urlparse(href).netloc.replace('www.', '') == home_host and page_type(href, home_host) == 'rooms':
                pages[url]['links_rooms'] = True
        for t in soup(['script', 'style', 'noscript', 'svg']):
            t.decompose()
        texts[url] = re.sub(r'\s+', ' ', soup.get_text(' ')).strip()
        text_phones = set()
        for m in analysis.PHONE.finditer(texts[url]):
            digits = re.sub(r'\D', '', m.group(0))
            digits = digits[2:] if digits.startswith('00') else digits
            if 9 <= len(digits) <= 13:
                text_phones.add(digits)
        pages[url]['phones'] = sorted(phones)                       # tel: links
        pages[url]['phones_text'] = sorted(text_phones - phones)
        for t in soup.find_all(['header', 'footer', 'nav']) + soup.find_all(
                attrs={'data-elementor-type': re.compile('header|footer|popup')}):
            t.decompose()
        main = re.sub(r'\s+', ' ', soup.get_text(' ')).strip()
        pages[url]['content_words'] = len(main.split())
        pages[url]['main_text_start'] = main[:400]
        if progress and n % 20 == 0:
            progress(f'scanned {n}/{len(urls)} pages')
        time.sleep(delay)
    return pages, texts, links


def booking_link_hotels(links, mirai_id='', hotel_path=''):
    """Which hotel each booking link opens: its Mirai ID (idtokenprovider) against the hotel's own.
    Names come from the parity feed's hotel roster when it is set up. A link to another hotel's
    booking engine sends the guest to the wrong hotel (e.g. a Cairo "Rooms & Suites" button that
    opened Gewan Palace, New Alamein)."""
    ids = Counter()
    by_id = defaultdict(list)
    for l in links:
        q = parse_qs(urlparse(l['href']).query)
        for v in q.get('idtokenprovider', []) + q.get('idTokenProvider', []):
            ids[v] += 1
            by_id[v].append(l)
    scope = '/' + hotel_path.strip('/') + '/' if hotel_path and hotel_path.strip('/') else ''

    def in_scope(u):
        return not scope or (urlparse(u).path + '/').startswith(scope)
    # Without mirai_id, the hotel's own ID is the one its room pages use: on a shared domain the most
    # common ID can belong to a sister hotel, and a hotel's ID was once reported "not found".
    room_ids = Counter(v for v, ls in by_id.items() for l in ls if in_scope(l['source'])
                       and page_type(l['source'], urlparse(l['source']).netloc.replace('www.', '')) == 'rooms')
    scoped = Counter(v for v, ls in by_id.items() for l in ls if in_scope(l['source']))
    if mirai_id:
        own, own_from = str(mirai_id), 'given (mirai_id)'
    elif room_ids:
        own, own_from = room_ids.most_common(1)[0][0], 'the ID most used on room pages' + (f' under {scope}' if scope else '')
    elif scoped:
        own, own_from = scoped.most_common(1)[0][0], 'the most common ID' + (f' under {scope}' if scope else '')
    else:
        own, own_from = '', 'no booking links with an ID'
    try:
        from . import parity
        roster = parity.hotel_roster()
    except Exception:
        roster = {}
    other = []
    for v, ls in by_id.items():
        if v != own:
            for l in ls:
                if in_scope(l['source']):
                    other.append(dict(l, mirai_id=v, opens=roster.get(v, 'unknown hotel (not in the roster)')))
    pages_by_id = {v: sorted({l['source'] for l in ls})[:15] for v, ls in by_id.items()}
    return {'own_mirai_id': own, 'own_id_from': own_from, 'own_name': roster.get(own, ''), 'ids_seen': dict(ids),
            'pages_by_id': pages_by_id,
            'roster_used': bool(roster), 'links_to_other_hotels': other}


def check_booking_links(links, delay=0.3):
    s = requests.Session()
    s.headers['User-Agent'] = UA
    status = {}
    for href in sorted({l['href'] for l in links}):
        r = _get(s, href, allow_redirects=True)
        status[href] = r.status_code if r is not None else 0
        time.sleep(delay)
    dead = [dict(l, status=status[l['href']]) for l in links
            if status.get(l['href'], 0) == 0 or status[l['href']] >= 400]
    curs = Counter(c.upper() for l in links for c in parse_qs(urlparse(l['href']).query).get('currency', []))
    main = curs.most_common(1)[0][0] if curs else ''
    outdated = [dict(l, status=status[l['href']], problems=booking_link_problems(l['href'], main_currency=main))
                for l in links if booking_link_problems(l['href'], main_currency=main)]
    return {'unique_links_checked': len(status), 'dead': dead,
            'dead_unique': sorted({d['href'] for d in dead}),
            'outdated': outdated,
            'formats': dict(Counter(re.sub(r'\?.*', '', l['href']) for l in links).most_common(10))}


# ---------------------------------------------------------------- WordPress

def _paged(s, url, params, max_pages=30):
    items, page = [], 1
    while page <= max_pages:
        r = _get(s, url, params={**params, 'page': page, 'per_page': 100})
        if r is None or r.status_code != 200:
            break
        try:
            batch = r.json()
        except ValueError:
            break
        if not isinstance(batch, list) or not batch:
            break
        items.extend(batch)
        if page >= int(r.headers.get('X-WP-TotalPages', page)):
            break
        page += 1
    return items


def wordpress(site):
    s = requests.Session()
    s.headers['User-Agent'] = UA
    r = _get(s, urljoin(site, '/wp-json/'))
    if r is None or r.status_code != 200:
        return {'is_wordpress_api': False}
    try:
        root = r.json()
    except ValueError:
        return {'is_wordpress_api': False}
    namespaces = root.get('namespaces', [])
    out = {
        'is_wordpress_api': True,
        'site_name': root.get('name', ''),
        'namespaces': namespaces,
        'seo_plugin': [v for k, v in SEO_PLUGINS.items() if k in namespaces] or ['none detected'],
        'redirection_plugin': 'redirection/v1' in namespaces,
        'risky_namespaces': [n for n in namespaces if RISKY_NAMESPACE.search(n)],
    }
    users = _get(s, urljoin(site, '/wp-json/wp/v2/users'), params={'per_page': 100, '_fields': 'id,slug,name'})
    try:
        user_list = users.json() if users is not None and users.status_code == 200 else []
    except ValueError:
        user_list = []
    out['users_public'] = bool(user_list) and isinstance(user_list, list)
    out['users'] = [u.get('slug') for u in user_list] if out['users_public'] else []

    posts = _paged(s, urljoin(site, '/wp-json/wp/v2/posts'),
                   {'_fields': 'id,date,modified,slug,link,title,content,author'})
    names = {u.get('id'): u.get('name') or u.get('slug') for u in user_list} if out['users_public'] else {}
    # the byline guests see on blog posts: a company login here reads as the author of the hotel's articles
    out['post_authors'] = [{'author': names.get(a, f'user {a}'), 'posts': n}
                           for a, n in Counter(p.get('author') for p in posts).most_common()]
    out['posts'] = suspicious_posts(posts)
    pages = _paged(s, urljoin(site, '/wp-json/wp/v2/pages'), {'_fields': 'id,link'}, max_pages=10)
    out['content_links'] = sorted({p.get('link') for p in posts + pages if p.get('link')})
    out['mcp_endpoints'] = probe_risky_routes(s, site, root, out['risky_namespaces'])

    media = _paged(s, urljoin(site, '/wp-json/wp/v2/media'), {'_fields': 'id,source_url,alt_text,media_type'},
                   max_pages=20)
    images = [m for m in media if m.get('media_type') == 'image']
    out['media'] = {'images': len(images),
                    'missing_alt_text': sum(1 for m in images if not (m.get('alt_text') or '').strip())}
    return out


def _dt(v):
    try:
        return datetime.fromisoformat(v)
    except (TypeError, ValueError):
        return None


def suspicious_posts(posts):
    """Junk or injected posts: very short titles, empty bodies, many look-alike slugs, and backdating.
    Backdating shows two ways: the published date is long before the last change, or the post ID is
    newer than posts published long after it (WordPress hands out IDs in creation order, so a high ID
    with a 2020 date was created recently and dated back)."""
    groups = Counter(re.sub(r'-\d+$', '', p.get('slug', '')) for p in posts)
    # compare each post's date with the median date of the posts created just before it: one oddly
    # dated post must not make every later post look backdated
    dated = [(p.get('id') or 0, _dt(p.get('date'))) for p in posts]
    dated = sorted((i, d.replace(tzinfo=None)) for i, d in dated if d)
    created_after, normal = set(), []          # normal: dates of the unflagged posts so far, in ID order
    for pid, d in dated:
        before = sorted(normal[-9:])
        if len(before) >= 3 and (before[len(before) // 2] - d).days > 180:
            created_after.add(pid)              # a run of injected posts can't become the baseline
        else:
            normal.append(d)
    suspicious = []
    for p in posts:
        title = BeautifulSoup((p.get('title') or {}).get('rendered', ''), 'html.parser').get_text().strip()
        body = BeautifulSoup((p.get('content') or {}).get('rendered', ''), 'html.parser').get_text(' ').strip()
        published, modified = p.get('date', ''), p.get('modified', '')
        reasons = []
        if len(title) <= 5:
            reasons.append('very short title')
        if len(body) < 40:
            reasons.append('empty or near-empty content')
        pd, md = _dt(published), _dt(modified)
        if pd and md and (md - pd).days > 365:
            reasons.append('published date more than a year before last change (backdated?)')
        if p.get('id') in created_after:
            reasons.append('created after posts dated much later (ID order): backdated')
        base = re.sub(r'-\d+$', '', p.get('slug', ''))
        if groups[base] >= 3 and len(body) < 200:
            reasons.append(f'one of {groups[base]} posts with slug "{base}"')
        if len(reasons) >= 2:
            suspicious.append({'id': p.get('id'), 'title': title, 'slug': p.get('slug'), 'link': p.get('link'),
                               'published': published, 'modified': modified, 'author': p.get('author'),
                               'reasons': reasons})
    trend = Counter((x['modified'] or '')[:7] for x in suspicious)
    recent = (datetime.now() - timedelta(days=30)).isoformat()
    return {'total': len(posts), 'suspicious_count': len(suspicious),
            'suspicious_by_month_modified': dict(sorted(trend.items())),
            'latest_suspicious_change': max((x['modified'] for x in suspicious), default=''),
            'suspicious_changed_last_30_days': sum(1 for x in suspicious if (x['modified'] or '') >= recent),
            'slug_groups': {k: n for k, n in groups.items()
                            if n >= 3 and any(x['slug'].startswith(k) for x in suspicious)},
            'suspicious': suspicious}


def probe_risky_routes(s, site, root, namespaces):
    """Do the MCP / site-control routes answer without logging in? Read-only probes: a GET on each
    plain route, and an MCP "tools/list" request (lists tools, changes nothing) on MCP routes."""
    out = []
    routes = root.get('routes') or {}
    for ns in namespaces:
        rows = []
        for route, info in routes.items():
            if not route.startswith(f'/{ns}') or '(?P<' in route or route.rstrip('/') == f'/{ns}':
                continue
            methods = set(info.get('methods') or [])
            url = urljoin(site, '/wp-json' + route)
            if 'GET' in methods:
                r = _get(s, url)
                code = r.status_code if r is not None else 0
                rows.append({'route': route, 'method': 'GET', 'status': code,
                             'open': code == 200 and len(r.content) > 2})
            if 'POST' in methods and 'mcp' in route.lower():
                try:
                    r = s.post(url, json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}, timeout=25,
                               headers={'Accept': 'application/json, text/event-stream'})
                    code, body = r.status_code, r.text[:20000]
                except requests.RequestException:
                    code, body = 0, ''
                rows.append({'route': route, 'method': 'POST tools/list', 'status': code,
                             'open': code == 200 and '"tools"' in body,
                             'tools_listed': len(re.findall(r'"name"\s*:', body)) if code == 200 else 0})
            if len(rows) >= 12:
                break
        open_rows = [r for r in rows if r['open']]
        out.append({'namespace': ns, 'routes_probed': len(rows), 'open_without_login': len(open_rows),
                    'verdict': ('OPEN: answers without logging in' if open_rows else
                                'requires login' if rows and all(r['status'] in (401, 403) for r in rows) else
                                'no plain routes to probe' if not rows else 'did not answer openly'),
                    'routes': rows})
    return out


def llms_txt(site, active_seo):
    """A leftover llms.txt from an SEO plugin that is no longer the active one (e.g. Yoast's after a
    switch to Rank Math) keeps describing the site with stale pages."""
    s = requests.Session()
    s.headers['User-Agent'] = UA
    r = _get(s, urljoin(site, '/llms.txt'), allow_redirects=True)
    if r is None or r.status_code != 200 or 'html' in r.headers.get('content-type', ''):
        return {'exists': False}
    named = [name for name, rx in SEO_HTML.items() if rx.search(r.text[:5000])]
    return {'exists': True, 'generated_by': named, 'lines': r.text.count('\n') + 1,
            'leftover': bool(named) and not any(n in active_seo for n in named)}


# ---------------------------------------------------------------- Search Console spam terms

def gsc_spam_queries(site_property, days=90):
    if not site_property or not paths.GSC_TOKEN.exists():
        return {'checked': False, 'reason': 'no Search Console property or token'}
    from google.auth.transport.requests import AuthorizedSession
    from google.oauth2.credentials import Credentials
    creds = Credentials.from_authorized_user_info(json.loads(paths.GSC_TOKEN.read_text()), paths.gsc_scopes())
    s = AuthorizedSession(creds)
    end = date.today() - timedelta(days=2)
    start = end - timedelta(days=days)
    url = ('https://www.googleapis.com/webmasters/v3/sites/'
           + requests.utils.quote(site_property, safe='') + '/searchAnalytics/query')
    r = s.post(url, json={'startDate': str(start), 'endDate': str(end), 'dimensions': ['query', 'page'],
                          'rowLimit': 25000}, timeout=60)
    if r.status_code != 200:
        return {'checked': False, 'reason': f'Search Console API {r.status_code}: {r.text[:200]}'}
    rows = r.json().get('rows', [])
    hits = [{'query': x['keys'][0], 'page': x['keys'][1], 'impressions': x['impressions'], 'clicks': x['clicks']}
            for x in rows if SPAM_QUERY.search(x['keys'][0])]
    return {'checked': True, 'window': f'{start}..{end}', 'queries_scanned': len(rows), 'spam_hits': hits}


# ---------------------------------------------------------------- main

def hotel_names(crawl_dir, pages, hotel_path=''):
    """The hotel's own name(s) for brand terms: <domain>/hotel.json, then the business schema name on
    the hotel's pages (under hotel_path on a shared domain)."""
    names = []
    hj = Path(crawl_dir).parent / 'hotel.json'
    if hj.exists():
        try:
            h = json.loads(hj.read_text(encoding='utf-8'))
            for k in ('name', 'hotel', 'names'):
                v = h.get(k)
                names += v if isinstance(v, list) else [v] if isinstance(v, str) and v else []
        except (ValueError, OSError, AttributeError):
            pass
    scope = '/' + hotel_path.strip('/') + '/' if hotel_path and hotel_path.strip('/') else ''
    c = Counter(n['name'] for u, p in pages.items() if not scope or (urlparse(u).path + '/').startswith(scope)
                for n in p.get('jsonld_nodes', []) if n['type'] in analysis.BUSINESS_TYPES and n.get('name'))
    names += [n for n, _ in c.most_common(2)]
    return [n for n in dict.fromkeys(names) if isinstance(n, str)]


def audit(crawl_dir, site_property='', progress=None, hotel_city='', mirai_id='', hotel_path=''):
    crawl_dir = paths.resolve(crawl_dir)
    data = json.loads((crawl_dir / 'crawl.json').read_text(encoding='utf-8'))
    start = (data.get('stats') or {}).get('baseUrl') or data['urls'][0]['url']
    home_host = urlparse(start).netloc.replace('www.', '')
    site = f'{urlparse(start).scheme}://{urlparse(start).netloc}'
    urls = [u['url'] for u in data['urls']
            if is_page(u) and urlparse(u['url']).netloc.replace('www.', '') == home_host]

    def step(msg):
        if progress:
            progress(msg)

    step('WordPress REST API')
    wp = wordpress(site)
    # Full counts: pages the crawler didn't reach (orphan posts, sitemap-only URLs) are scanned too.
    from .indexing import _sitemap_urls
    seen = {u.rstrip('/') for u in urls}
    extra = []
    for u in wp.get('content_links', []) + _sitemap_urls(site, limit=3000):
        u = u.split('#')[0]
        if urlparse(u).netloc.replace('www.', '') == home_host and not urlparse(u).query \
                and u.rstrip('/') not in seen and not re.search(r'\.(xml|jpe?g|png|webp|gif|pdf|svg)$', u, re.I):
            seen.add(u.rstrip('/'))
            extra.append(u)
    extra = extra[:1500]
    coverage = {'crawled_pages': len(urls), 'added_from_sitemaps_and_wordpress': len(extra),
                'added_examples': extra[:20]}
    step(f'scanning {len(urls) + len(extra)} pages ({len(extra)} not reached by the crawl)')
    pages, texts, links = scan_pages(urls + extra, home_host, progress=progress)
    step('checking booking links')
    booking = check_booking_links(links)
    booking['hotels'] = booking_link_hotels(links, mirai_id, hotel_path)
    spam = gsc_spam_queries(site_property)
    step('rendering the homepage for the tags that actually fire')
    tracking = rendered_tags(site, crawl_dir)
    step('sitemaps, canonicals, links, schema, Search Console')
    ok = {u: p for u, p in pages.items() if 'title' in p}
    words = {u: p.get('content_words', 0) for u, p in ok.items()}
    city_info = ({'city': hotel_city, 'source': 'given (hotel_city)', 'given': True, 'warning': ''} if hotel_city
                 else analysis.hotel_city_with_source(ok, home_host, hotel_path))
    city = city_info['city']
    hj = crawl_dir.parent / 'hotel.json'
    try:
        hotel_info = json.loads(hj.read_text(encoding='utf-8')) if hj.exists() else {}
    except ValueError:
        hotel_info = {}
    gsc = analysis.gsc_report(site_property, wp.get('site_name', ''), home_host,
                              hotel_names=hotel_names(crawl_dir, ok, hotel_path), hotel_path=hotel_path,
                              other_sites=hotel_info.get('other_sites'))
    report = {
        'sitemaps': analysis.sitemaps(site, UA),
        'canonical_targets': analysis.canonical_targets(ok, data, UA),
        'titles': analysis.title_report(ok, wp.get('site_name', '')),
        'old_years': analysis.old_years(ok),
        'archives_indexable': analysis.archive_pages(data, home_host),
        'page_groups': analysis.page_groups(ok, words),
        'account_pages': analysis.account_pages(site, UA, ok),
        'schema': analysis.schema_report(ok),
        'links': analysis.link_report(data, list(ok), home_host, crawl_dir),
        'phones': analysis.phone_report(ok),
        # one landmark, one distance: the stricter matcher from the Abar handoff (figures belong to the longest
        # place name before them, within the clause) and compared with hotel-facts.json
        'distance_conflicts': consistency.distance_rows(texts, str(crawl_dir.parent / 'hotel-facts.json'),
                                                        home_host.split('.')[0]),
        'prices_in_text': analysis.price_mentions(texts, ok),
        'out_of_season': analysis.season_report(ok, texts),
        'other_city': analysis.city_report(ok, city),
        'hacked_text': analysis.hacked_text(texts),
        'blog_booking_links': analysis.blog_booking_links(ok, gsc.get('pages_by_impressions')),
        'seo_plugin_output_pages': dict(Counter(n for p in ok.values() for n in p.get('seo_plugin_html', []))),
        'translation': {'client_side_plugin': sorted({n for p in ok.values() for n in p.get('translation_plugin', [])}),
                        'pages_with_hreflang': sum(1 for p in ok.values() if p.get('hreflang_count'))},
        'llms_txt': llms_txt(site, wp.get('seo_plugin', [])),
        'ai_access': analysis.ai_access(site, UA, [next((u for u, p in ok.items() if p.get('type') == t), '')
                                                   for t in ('rooms', 'offers')]),
        'snippet_blocked_pages': analysis.snippet_blocks(ok),
        'hreflang': analysis.hreflang_report(ok, data),
        'expired_offer_schema': analysis.expired_offer_schema(ok),
        'meta_templates': analysis.meta_template_report(ok),
        'key_pages_no_impressions_16m': analysis.key_pages_without_impressions(ok, gsc) if gsc.get('checked') else None,
        'coverage': coverage,
    }

    issues = []

    def add(check, url, detail, sev=None):
        t = pages.get(url, {}).get('type') or page_type(url, home_host)
        issues.append({'check': check, 'url': url, 'page_type': t, 'severity': sev or severity(t), 'detail': detail})

    for u, p in ok.items():
        if not p['h1']:
            add('h1_missing', u, 'no H1')
        elif len(p['h1']) > 1:
            add('h1_multiple', u, f"{len(p['h1'])} H1s: " + ' | '.join(p['h1'][:4]))
        if not p['title']:
            add('title_missing', u, 'no title')
        elif len(p['title']) > 62:
            add('title_too_long', u, f"{len(p['title'])} chars")
        if not p['meta_description']:
            add('meta_missing', u, 'no meta description')
        elif len(p['meta_description']) > 155:
            add('meta_too_long', u, f"{len(p['meta_description'])} chars")
        if 'noindex' in (p['robots'] + ' ' + p['x_robots_tag']).lower() and p['type'] in CRITICAL_TYPES:
            add('noindex_on_key_page', u, p['robots'] or p['x_robots_tag'])
        if not p['canonical']:
            add('canonical_missing', u, '')
        for err in p['jsonld_errors']:
            add('jsonld_invalid', u, err + ' (Google ignores the whole block)')
    for c in report['canonical_targets']:
        if c['kind'] == 'ok_other_page':
            add('canonical_other', c['url'], c['canonical'])
        else:
            # Google can index neither address: Priority whatever the page type
            add('canonical_broken', c['url'], f"canonical {c['canonical']} returns {c['canonical_status']}"
                + (' and redirects back to this page' if c['redirects_back_to_page'] else ''), 'Priority')
    for d in booking['dead']:
        add('booking_link_dead', d['source'], f"{d['text'] or 'link'} -> {d['href']} ({d['status']})", 'Priority')
    for d in booking['outdated']:
        add('booking_link_outdated', d['source'], f"{d['text'] or 'link'} -> {d['href']}: "
            + '; '.join(d['problems']), 'Priority')
    for d in booking['hotels']['links_to_other_hotels']:
        add('booking_link_other_hotel', d['source'], f"{d['text'] or 'link'} opens {d['opens']} (Mirai "
            f"{d['mirai_id']}), not this hotel ({booking['hotels']['own_mirai_id']})", 'Priority')
    for a in report['account_pages']:
        if not a['noindex']:
            add('booking_page_indexable', a['url'], 'booking-engine or account page without noindex', 'Priority')
    for x in report['old_years']:
        add('old_year_in_title', x['url'], f"{x['years_in_title_or_h1'] or x['years_in_url']}: {x['title']}")
    for x in report['out_of_season']:
        add('out_of_season_wording', x['url'], f"{', '.join(x['out_of_season_words'])}: {x['title']}")
    for x in report['other_city']['pages']:
        add('other_city_in_heading', x['url'], f"{x['field']} names {x['city']} (hotel is in "
            f"{report['other_city']['hotel_city']}): {x['text']}")
    for x in report['page_groups']['empty_pages']:
        add('page_empty', x['url'], f"{x['content_words']} words of content" + (f", says \"{x['says']}\"" if x['says'] else ''))
    for u in report['page_groups']['junk_slugs']:
        add('junk_page', u, 'odd slug (created by mistake?)')
    for x in report['phones']['odd_country_codes']:
        for u in x['urls']:
            add('phone_country_code', u, f"{x['number']} (main code {report['phones']['main_country_code']})")
    ai = report['ai_access']
    for bot in ai['search_bots_blocked_in_robots']:
        # robots.txt is read, not guessed: a blocked search crawler hides the whole site from that search
        add('ai_search_bot_blocked', site.rstrip('/') + '/', f"robots.txt blocks {bot} from the homepage", 'Priority')
    for x in report['snippet_blocked_pages']:
        add('snippet_blocked', x['url'], x['robots'])
    hl = report['hreflang']
    for x in hl['no_return_link']:
        add('hreflang_no_return', x['url'], f"{x['code']} → {x['target']} doesn't link back (Google ignores the pair)")
    for x in hl['bad_targets']:
        add('hreflang_bad_target', x['url'], f"{x['code']} → {x['target']}: {x['problem']}")
    for x in hl['invalid_codes']:
        add('hreflang_invalid_code', x['url'], f"\"{x['code']}\" is not a valid language(-region) code")
    for x in hl['arabic_pages_not_arabic']:
        add('arabic_page_untranslated', x['url'], f"lang=ar but title/meta/H1 have no Arabic: {x['title']}")
    for x in report['expired_offer_schema']:
        add('offer_schema_expired', x['url'], f"Offer markup valid until {', '.join(x['dates'])}")
    for u in report['meta_templates']['meta_equals_title']:
        add('meta_equals_title', u, 'meta description is the title again')
    for g in report['links']['broken_targets']:
        if g.get('internal') or g['sitewide']:
            for u in g['sources']:
                add('link_broken', u, f"{g['anchors'][0] if g['anchors'] else 'link'} -> {g['target']} "
                    f"({g.get('status')})" + (' [sitewide]' if g['sitewide'] else ''))

    type_pages = defaultdict(int)
    for p in ok.values():
        for t in set(p['jsonld_types']):
            type_pages[t] += 1
    sitewide = {t: n for t, n in type_pages.items() if n >= max(3, int(0.8 * len(ok)))}

    security = []
    if wp.get('posts', {}).get('suspicious_count'):
        ps = wp['posts']
        security.append(f"{ps['suspicious_count']} suspicious posts of {ps['total']} (latest change "
                        f"{ps['latest_suspicious_change'][:10]}, {ps['suspicious_changed_last_30_days']} in the last "
                        f"30 days: {'STILL BEING CREATED' if ps['suspicious_changed_last_30_days'] else 'not recent'}); "
                        f"slug groups {ps['slug_groups'] or '-'}; by month: {ps['suspicious_by_month_modified']}")
    for m in wp.get('mcp_endpoints', []):
        if m['open_without_login']:
            security.append(f"/wp-json/{m['namespace']} answers without logging in ({m['open_without_login']} of "
                            f"{m['routes_probed']} routes probed): require authentication or remove the plugin")
    others = [m['namespace'] for m in wp.get('mcp_endpoints', []) if not m['open_without_login']]
    if others:
        security.append('REST namespaces that expose site control (probed: did not answer without login; '
                        'confirm they require authentication): ' + ', '.join(others))
    if report['llms_txt'].get('leftover'):
        security.append(f"/llms.txt was written by {', '.join(report['llms_txt']['generated_by'])}, which is not "
                        f"the active SEO plugin ({', '.join(wp.get('seo_plugin', []))}): delete the leftover file")
    if wp.get('users_public'):
        security.append(f"/wp-json/wp/v2/users lists {len(wp['users'])} usernames publicly")
    if tracking.get('history_entries_added'):
        security.append(f"Back-button hijacking signal: the homepage added {tracking['history_entries_added']} browser "
                        f"history entries with no click ({tracking.get('push_states_without_click')}). Google's spam "
                        'policy (since 15 Jun 2026): find the script (chat, popup, ad or booking widget) and remove it')
    for h in report['hacked_text']:
        security.append(f"Defacement text \"{h['text']}\" on {h['pages']} pages: " + ', '.join(h['urls'][:8]))
    if spam.get('spam_hits'):
        security.append(f"{len(spam['spam_hits'])} spam-looking search queries in Search Console: "
                        + ', '.join(sorted({h['query'] for h in spam['spam_hits']})[:10]))

    counts = Counter(i['check'] for i in issues)
    findings = {
        'site': site, 'generated': datetime.now().isoformat(timespec='seconds'),
        'hotel_city': city_info, 'hotel_path': hotel_path or None,
        'pages_scanned': len(ok), 'pages_failed': len(pages) - len(ok),
        'counts': dict(counts),
        'priority_issue_count': sum(1 for i in issues if i['severity'] == 'Priority'),
        'jsonld_sitewide_types': sitewide,
        'jsonld_type_pages': dict(type_pages),
        'tags_in_raw_html': {'gtm': sorted({g for p in ok.values() for g in p['gtm_ids']}),
                             'gtag': sorted({g for p in ok.values() for g in p['gtag_ids']})},
        'tags_rendered': tracking,
        'booking_links': booking, 'wordpress': wp, 'gsc_spam': spam, 'gsc': gsc, 'security': security,
        'report': report,
        'issues': issues,
        'pages': ok,
    }
    md = findings_md(findings)
    (crawl_dir / 'findings.json').write_text(json.dumps(findings, indent=1, ensure_ascii=False), encoding='utf-8')
    (crawl_dir / 'site_text.json').write_text(json.dumps(texts, ensure_ascii=False), encoding='utf-8')
    (crawl_dir / 'findings.md').write_text(md, encoding='utf-8')
    return {k: findings[k] for k in ('site', 'hotel_city', 'pages_scanned', 'counts', 'priority_issue_count', 'security',
                                     'jsonld_sitewide_types', 'tags_rendered')} | {
        'coverage': {k: v for k, v in coverage.items() if k != 'added_examples'},
        'booking_links_dead': booking['dead_unique'],
        'files': ['findings.json', 'findings.md', 'site_text.json', 'replace_pairs.csv'],
        'findings_md': md[:8000]}


def findings_md(f):
    """Readable summary with full counts. Per-URL detail stays in findings.json."""
    r, wp, b, g = f['report'], f['wordpress'], f['booking_links'], f['gsc']
    L = [f"# Findings: {f['site']}", '',
         f"Generated {f['generated']} from {f['pages_scanned']} pages. All counts are complete (every page), "
         'not samples. Detail per URL is in findings.json.', '']
    hc = f.get('hotel_city') or {}
    L += [f"**Hotel city: {hc.get('city') or 'unknown'}** (source: {hc.get('source', 'n/a')})"
          + (f" · pages scoped to {f['hotel_path']}" if f.get('hotel_path') else ''), '']
    if hc.get('warning'):
        L += [f"> WARNING: {hc['warning']}. The other-city check below used this city.", '']
    if f['security']:
        L += ['## Security (top of the Web Team list)', ''] + [f'- {s}' for s in f['security']] + ['']

    L += ['## SEO plugin and sitemaps', '',
          f"- SEO plugin (REST API): {', '.join(wp.get('seo_plugin', ['n/a']))}; its output is in the HTML of: "
          f"{r['seo_plugin_output_pages'] or 'no pages'} (of {f['pages_scanned']}). Redirection plugin: "
          f"{wp.get('redirection_plugin', 'n/a')}",
          f"- Meta descriptions: {r['titles']['meta_description_coverage']} pages have one",
          f"- robots.txt sitemap lines: {r['sitemaps']['robots_txt']['sitemap_lines'] or 'none'}"]
    for url, s in r['sitemaps']['sitemaps'].items():
        L.append(f"- {url}: {s['status']}" + (f", {s['entries']} entries" if 'entries' in s else '')
                 + (f", includes {s['includes']}" if s.get('includes') else '')
                 + (f" (ends at {s['final_url']})" if s.get('final_url') and s['final_url'] != url else ''))
    for s in g.get('submitted_sitemaps', []):
        L.append(f"- Search Console sitemap {s['path']}: live {s['live_status']}, errors {s['errors']}, "
                 f"last read {s['last_downloaded'][:10] or 'never'}, {s['submitted']} submitted")
    L.append('')

    L += ['## Counts per check', '']
    for check, n in Counter(i['check'] for i in f['issues']).most_common():
        pri = sum(1 for i in f['issues'] if i['check'] == check and i['severity'] == 'Priority')
        L.append(f'- {check}: {n} ({pri} Priority)')
    L.append('')

    bad = [c for c in r['canonical_targets'] if c['kind'] != 'ok_other_page']
    if bad:
        L += [f"## Canonicals that block indexing ({len(bad)} pages)", '']
        L += [f"- {c['url']} → {c['canonical']} ({c['canonical_status']}"
              + (', redirects back' if c['redirects_back_to_page'] else '') + ')' for c in bad] + ['']

    t = r['titles']
    L += ['## Titles', '']
    L += [f"- Suffix \"{s['suffix']}\" on {s['pages']} pages ({s['chars']} chars"
          + (', keyword-stuffed' if s['stuffed'] else '') + ')' for s in t['common_suffixes']]
    L.append(f"- WordPress default titles (\"Page – Site name\"): {len(t['default_wordpress_titles'])} pages")
    L.append(f"- Duplicate titles: {len(t['duplicate_titles'])}")
    mt = r.get('meta_templates') or {}
    if mt:
        L.append(f"- Meta descriptions identical to the title: {len(mt['meta_equals_title'])}; starting with the "
                 f"whole title: {len(mt['meta_starts_with_title'])}; one template with only the page name changed: "
                 + ('; '.join(f"\"{x['pattern'][:90]}\" on {x['pages']} pages" for x in mt['templated'][:3]) or 'none'))
    if r.get('expired_offer_schema'):
        L.append(f"- Offer schema past its validThrough / priceValidUntil date: {len(r['expired_offer_schema'])} pages")
    L.append('')

    L += ['## Indexing', '']
    for a in r['account_pages']:
        L.append(f"- {a['url']}: {'noindex' if a['noindex'] else 'INDEXABLE'}")
    for k, v in r['archives_indexable'].items():
        L.append(f"- Indexable {k} archive pages: {v['count']}")
    for x in r['page_groups']['thin_groups']:
        L.append(f"- Thin group {x['group']}: {x['pages']} pages, median {x['median_content_words']} words of content")
    L.append(f"- Near-empty pages: {len(r['page_groups']['empty_pages'])}; odd slugs: {r['page_groups']['junk_slugs'] or 'none'}")
    L.append('')

    s = r['schema']
    L += ['## Schema (every distinct block)', '']
    for blk in s['blocks']:
        if blk['flags'] or blk['type'] in analysis.BUSINESS_TYPES:
            L.append(f"- {blk['type']} \"{blk.get('name', '')}\" on {blk['pages']} pages"
                     + (f"; geo {blk['geo']}" if blk.get('geo') else '')
                     + (f"; reviews by {blk['reviews']}" if blk.get('reviews') else '')
                     + (': ' + '; '.join(blk['flags']) if blk['flags'] else ''))
    L += [f'- Conflict: {c}' for c in s['conflicts']]
    bad_blocks = Counter(e for p in f['pages'].values() for e in p['jsonld_errors'])
    L += [f'- Invalid (Google ignores it): {e}: {n} pages' for e, n in bad_blocks.most_common()]
    L.append(f"- Types on (nearly) every page: {f['jsonld_sitewide_types'] or 'none'}")
    L.append('')

    lk = r['links']
    L += ['## Links', '', f"- {lk['counts']}"]
    if lk.get('false_alarms'):
        L.append('- Failed at crawl time but load fine now (not findings): ' + ', '.join(
            f"{x['target']} ({x.get('status')} → {x['live_status']})" for x in lk['false_alarms'][:8]))
    for x in lk['broken_targets'][:25]:
        L.append(f"- Broken: {x['target']} ({x.get('status')}) from {x['pages_linking']} pages"
                 + (' [sitewide]' if x['sitewide'] else '') + f", anchor {x['anchors'][:2]}")
    for x in lk['redirected_targets']:
        if x['sitewide']:
            L.append(f"- Sitewide link through a redirect: {x['target']} → {x.get('final')} ({x['pages_linking']} pages)")
    L.append('- Old → final address pairs for a bulk search-and-replace: replace_pairs.csv')
    bh = b.get('hotels', {})
    L.append(f"- Booking links by hotel (Mirai ID): {bh.get('ids_seen')}; own {bh.get('own_mirai_id')} "
             f"(from {bh.get('own_id_from', 'n/a')}) "
             f"{bh.get('own_name', '')}; links opening another hotel: {len(bh.get('links_to_other_hotels', []))}"
             + ('' if bh.get('roster_used') else ' (names need the parity feed: hotel-seo-parity-login)'))
    L.append(f"- Booking links: {b['unique_links_checked']} checked, {len(b['dead_unique'])} dead, "
             f"{len(b['outdated'])} outdated (old booking-step address, past dates, other currency); formats: {b['formats']}")
    L.append('')

    L += ['## Copy consistency', '']
    ph = r['phones']
    L.append(f"- Phone numbers: {[(x['number'], x['pages']) for x in ph['numbers'][:8]]}; main code "
             f"{ph.get('main_country_code', 'n/a')} (from {ph.get('main_code_from', 'n/a')}); odd country codes in "
             f"tel: links: {[x['number'] for x in ph['odd_country_codes']] or 'none'}")
    if ph.get('odd_country_codes_text_only'):
        L.append("- Odd codes in page text only (check by eye before listing; not counted as issues): "
                 f"{[(x['number'], x['pages']) for x in ph['odd_country_codes_text_only'][:6]]}")
    for d in r['distance_conflicts']:
        L.append(f"- DISTANCE {d['landmark']}: {d['detail']} (check by hand: two figures can be two places)")
    L.append(f"- Pages naming another city in a title/H1/meta (hotel city {r['other_city']['hotel_city'] or 'unknown'}): "
             f"{len(r['other_city']['pages'])}")
    L.append(f"- Out-of-season wording: {len(r['out_of_season'])} pages; old years in titles/H1s/URLs: {len(r['old_years'])}")
    L.append(f"- Pages with prices in the text (compare with the booking engine): {len(r['prices_in_text'])}")
    L.append(f"- Blog post authors shown: {wp.get('post_authors', 'n/a')}")
    L.append('')

    bl = r['blog_booking_links']
    if bl:
        no = [x for x in bl if not (x['links_to_rooms'] or x['links_to_booking'])]
        L += ['## Blog → booking', '', f"- {len(no)} of {len(bl)} posts link to neither a room page nor the booking "
              'engine. Busiest without a link: ' + ', '.join(f"{x['url']} ({x['impressions']})" for x in no[:6]), '']

    tr = r['translation']
    L += ['## Languages', '', f"- Browser-side translation plugin: {tr['client_side_plugin'] or 'none'}; "
          f"pages with hreflang: {tr['pages_with_hreflang']}"
          + (' (hreflang present: the plugin serves real language pages, not browser-side only)'
             if tr['client_side_plugin'] and tr['pages_with_hreflang'] else '')]
    hl = r.get('hreflang') or {}
    if hl.get('pages_with_hreflang'):
        L.append(f"- hreflang: pairs that don't link back {len(hl['no_return_link'])}; alternates that redirect, "
                 f"404, are noindex or not canonical {len(hl['bad_targets'])}; invalid codes "
                 f"{sorted({x['code'] for x in hl['invalid_codes']}) or 'none'}; pages not listing themselves "
                 f"{len(hl['no_self_reference'])}; without x-default {hl['x_default_missing']}")
    if hl.get('arabic_pages_not_arabic'):
        L.append(f"- Arabic pages (lang=ar) whose title, meta and H1 have no Arabic: {len(hl['arabic_pages_not_arabic'])}"
                 ', e.g. ' + ', '.join(urlparse(x['url']).path for x in hl['arabic_pages_not_arabic'][:5]))
    if g.get('checked'):
        a = g['arabic_queries']
        L.append(f"- Arabic searches: {a['count']} queries, {a['impressions']} impressions, {a['clicks']} clicks")
    L.append('')

    ai = r.get('ai_access') or {}
    if ai:
        L += ['## AI search access (ChatGPT, Perplexity, Claude, Copilot, Google AI features)', '']
        if not ai.get('robots_checked') or not ai.get('firewall_checked'):
            L += [f"> NOT CHECKED: robots.txt answered {ai['robots_txt_status']}, homepage {ai['browser_status']}. "
                  'AI checks AI01–AI02 are insufficient_data, not a pass.', '']
        L += [f"- robots.txt ({ai['robots_txt_status']}): search crawlers blocked: "
              f"{ai['search_bots_blocked_in_robots'] or 'none'}; training-only crawlers blocked (owner's choice, "
              f"not an issue): {ai['training_bots_blocked'] or 'none'}",
              f"- Firewall signal (spoofed user agent, homepage {ai['browser_status']} for a browser; CDN "
              f"{ai['cdn'] or 'none seen'}): " + ', '.join(
                  f"{b} {v['status']}" + (' CHALLENGE' if v['challenge_page'] else '') for b, v in ai['firewall'].items()),
              f"- Pages tested: {', '.join(urlparse(u).path for u in ai.get('urls_tested', []))}",
              f"- AI search bots that look blocked by the firewall (confirm in the host / Cloudflare bot settings "
              f"before listing): {ai['search_bots_blocked_by_firewall_signal'] or 'none'}. Googlebot/Bingbot "
              'results are not judged here (CDNs block fake ones on purpose): use index_status.',
              f"- AI agents acting for a guest (ChatGPT-User, Claude-User, Perplexity-User; they don't follow "
              f"robots.txt, only a firewall stops them) that look blocked: "
              f"{ai.get('guest_agents_blocked_by_firewall_signal') or 'none'}",
              f"- Pages blocking snippets (nosnippet / max-snippet under 50, which also keeps them out of AI "
              f"Overviews and AI Mode): {len(r.get('snippet_blocked_pages') or [])}", '']

    if g.get('checked'):
        L += ['## Search Console (' + g['window'] + ' vs ' + g['previous'] + ')', '']
        if g.get('impressions_anomaly'):
            L += [f"> WARNING: {g['impressions_anomaly']}.", '']
        im = g.get('image_search') or {}
        if im.get('checked'):
            L += [f"- Google Images: {im['clicks']} clicks, {im['impressions']} impressions, CTR {im['ctr_pct']}% "
                  f"(median page {im['median_page_ctr_pct']}%). High impressions, below-median CTR: " + ('; '.join(
                      f"{urlparse(x['page']).path} ({x['impressions']} impr, {x['ctr_pct']}%)"
                      for x in im['high_impressions_low_ctr'][:6]) or 'none')]
        L += [f"- Now: {g['now']}", f"- Before: {g['before']}",
              f"- Brand terms used: {g['brand_terms']} (from {g.get('brand_terms_source', 'n/a')}); check them "
              'before quoting the brand share',
              (f"- Searches whose top page belongs to a sister hotel (left out, hotel_path {g['hotel_path']}): "
               f"{g['sister_hotel_queries_dropped']['count']}") if g.get('hotel_path') else
              '- Whole-domain view (no hotel_path): on a domain with several hotels pass hotel_path',
              '- Non-brand searches at positions 4–20: ' + '; '.join(
                  f"{q['query']} ({q['impressions']} impr, pos {q['position']}, page "
                  f"{urlparse(q.get('top_page') or '').path or '?'})" for q in g['money_queries_pos_4_20'][:12]),
              '- Key pages (home, rooms, offers, contact) with no impressions in 16 months (never target a search '
              'at these without fixing why first): ' + (', '.join(urlparse(u).path for u in
                                                     (r.get('key_pages_no_impressions_16m') or [])[:10]) or 'none'),
              "- Left out, they belong to the hotel's other websites (link there instead): " + ('; '.join(
                  f"{x['query']} → {x['belongs_to']}" for x in g.get('left_out_other_sites', [])[:6]) or 'none'),
              "- Searches whose top page is in another language (target a page in the search's language): " + (
                  '; '.join(f"{q['query']} → {urlparse(q['top_page']).path}"
                            for q in [x for x in g['money_queries_pos_4_20'] if x.get('language_mismatch')][:6])
                  or 'none'),
              '- Old host versions still getting clicks: ' + ('; '.join(
                  f"{x['page']} ({x['clicks']} clicks)" for x in g['host_variant_pages'][:5]) or 'none'),
              '- Booking / account pages in search: ' + ('; '.join(
                  f"{x['page']} ({x['impressions']} impr)" for x in g['booking_and_account_pages'][:5]) or 'none'), '']
    else:
        L += [f"## Search Console: not checked ({g.get('reason')})", '']

    tr = f.get('tags_rendered') or {}
    L += ['## Tracking', '']
    if tr.get('checked'):
        t = tr['tags_fired']
        L.append(f"- Tags that FIRE on the rendered homepage (use these, not raw HTML, for any tracking statement): "
                 f"GTM {t['gtm'] or 'none'}, GA4 {t['ga4'] or 'none'} ({t['ga4_hits']} hits), Google Ads "
                 f"{t['google_ads'] or 'none'}, Meta pixel {'yes' if t['meta_pixel'] else 'no'}")
        cm = tr.get('consent_mode') or []
        L.append(f"- Consent Mode: {'; '.join(c['command'] + ' ' + json.dumps(c['params']) for c in cm) or 'no gtag consent call seen'}"
                 f"; consent state on GA4 hits (gcs): {tr.get('ga4_consent_states') or 'none seen'}; cookie banner: "
                 f"{'yes' if tr.get('consent_banner') else 'no'}. EEA guests under basic consent mode are not counted "
                 'in GA4: read A11 (GA4 vs Mirai) with this in mind')
    else:
        L.append(f"- Rendered check failed ({tr.get('reason')}): run inspect_pages before saying anything about tags")
    L += [f"- Tags in raw HTML: GTM {f['tags_in_raw_html']['gtm'] or 'none'}, gtag {f['tags_in_raw_html']['gtag'] or 'none'} "
          '(cache plugins often delay tags, so raw HTML alone can show none)',
          f"- Media Library images: {wp.get('media', {}).get('images', 'n/a')}, missing alt text: "
          f"{wp.get('media', {}).get('missing_alt_text', 'n/a')}"]
    cv = r.get('coverage') or {}
    if cv:
        L.append(f"- Coverage: {cv['crawled_pages']} crawled pages + {cv['added_from_sitemaps_and_wordpress']} pages "
                 'the crawl did not reach (from sitemaps and the WordPress API) were all scanned')
    lt = r.get('llms_txt') or {}
    if lt.get('exists'):
        L.append(f"- /llms.txt: {lt['lines']} lines, written by {lt['generated_by'] or 'unknown'}"
                 + (' (LEFTOVER: not the active SEO plugin)' if lt.get('leftover') else ''))
    for m in wp.get('mcp_endpoints', []):
        L.append(f"- /wp-json/{m['namespace']}: {m['verdict']} ({m['routes_probed']} routes probed)")
    return '\n'.join(L) + '\n'


def rendered_tags(site, crawl_dir):
    """Render the homepage like a visitor (pagecheck) and keep the tags that actually fire."""
    try:
        from . import pagecheck
        res = pagecheck.inspect([site.rstrip('/') + '/'], crawl_dir / 'inspect-home', viewports=('desktop',))
        row = res['results'][0]
        if row.get('error'):
            return {'checked': False, 'reason': row['error']}
        return {'checked': True, 'url': row['url'], 'tags_fired': row['tags_fired'],
                'consent_banner': row.get('consent_banner'), 'consent_mode': row.get('consent_mode'),
                'ga4_consent_states': row.get('ga4_consent_states'),
                'history_entries_added': row.get('history_entries_added', 0),
                'push_states_without_click': row.get('push_states_without_click', []),
                'screenshot': row.get('screenshot')}
    except Exception as e:  # noqa: BLE001 - no Chromium etc.: say so, the audit carries on
        return {'checked': False, 'reason': f'{type(e).__name__}: {str(e)[:200]}'}
