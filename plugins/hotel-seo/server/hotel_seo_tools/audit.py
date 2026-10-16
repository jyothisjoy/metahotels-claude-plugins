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
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from . import analysis, paths
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
            'links_rooms': False, 'links_booking': False,
        }
        phones = set()
        for a in soup.find_all('a', href=True):
            href = urljoin(url, a['href'])
            text = re.sub(r'\s+', ' ', a.get_text(' ')).strip()
            if a['href'].lower().startswith('tel:'):
                phones.add(re.sub(r'\D', '', a['href'])[-12:])
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
        for m in analysis.PHONE.finditer(texts[url]):
            digits = re.sub(r'\D', '', m.group(0))
            digits = digits[2:] if digits.startswith('00') else digits
            if 9 <= len(digits) <= 13:
                phones.add(digits)
        pages[url]['phones'] = sorted(phones)
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


def booking_link_hotels(links, mirai_id=''):
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
    own = str(mirai_id) if mirai_id else (ids.most_common(1)[0][0] if ids else '')
    try:
        from . import parity
        roster = parity.hotel_roster()
    except Exception:
        roster = {}
    other = []
    for v, ls in by_id.items():
        if v != own:
            for l in ls:
                other.append(dict(l, mirai_id=v, opens=roster.get(v, 'unknown hotel (not in the roster)')))
    return {'own_mirai_id': own, 'own_name': roster.get(own, ''), 'ids_seen': dict(ids),
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
    groups = Counter(re.sub(r'-\d+$', '', p.get('slug', '')) for p in posts)
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
        try:
            if (datetime.fromisoformat(modified) - datetime.fromisoformat(published)).days > 365:
                reasons.append('published date more than a year before last change (backdated?)')
        except ValueError:
            pass
        base = re.sub(r'-\d+$', '', p.get('slug', ''))
        if groups[base] >= 3 and len(body) < 200:
            reasons.append(f'one of {groups[base]} posts with slug "{base}"')
        if len(reasons) >= 2:
            suspicious.append({'id': p.get('id'), 'title': title, 'slug': p.get('slug'), 'link': p.get('link'),
                               'published': published, 'modified': modified, 'author': p.get('author'),
                               'reasons': reasons})
    trend = Counter((x['modified'] or '')[:7] for x in suspicious)
    out['posts'] = {'total': len(posts), 'suspicious_count': len(suspicious),
                    'suspicious_by_month_modified': dict(sorted(trend.items())),
                    'latest_suspicious_change': max((x['modified'] for x in suspicious), default=''),
                    'suspicious': suspicious}

    media = _paged(s, urljoin(site, '/wp-json/wp/v2/media'), {'_fields': 'id,source_url,alt_text,media_type'},
                   max_pages=20)
    images = [m for m in media if m.get('media_type') == 'image']
    out['media'] = {'images': len(images),
                    'missing_alt_text': sum(1 for m in images if not (m.get('alt_text') or '').strip())}
    return out


# ---------------------------------------------------------------- Search Console spam terms

def gsc_spam_queries(site_property, days=90):
    if not site_property or not paths.GSC_TOKEN.exists():
        return {'checked': False, 'reason': 'no Search Console property or token'}
    from google.auth.transport.requests import AuthorizedSession
    from google.oauth2.credentials import Credentials
    creds = Credentials.from_authorized_user_info(json.loads(paths.GSC_TOKEN.read_text()), [paths.GSC_SCOPE])
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

def audit(crawl_dir, site_property='', progress=None, hotel_city='', mirai_id=''):
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

    step(f'scanning {len(urls)} pages')
    pages, texts, links = scan_pages(urls, home_host, progress=progress)
    step('checking booking links')
    booking = check_booking_links(links)
    booking['hotels'] = booking_link_hotels(links, mirai_id)
    step('WordPress REST API')
    wp = wordpress(site)
    spam = gsc_spam_queries(site_property)
    step('sitemaps, canonicals, links, schema, Search Console')
    ok = {u: p for u, p in pages.items() if 'title' in p}
    words = {u: p.get('content_words', 0) for u, p in ok.items()}
    city = hotel_city or analysis.hotel_city(ok)
    gsc = analysis.gsc_report(site_property, wp.get('site_name', ''), home_host)
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
        'distance_conflicts': analysis.distance_conflicts(texts),
        'prices_in_text': analysis.price_mentions(texts, ok),
        'out_of_season': analysis.season_report(ok, texts),
        'other_city': analysis.city_report(ok, city),
        'hacked_text': analysis.hacked_text(texts),
        'blog_booking_links': analysis.blog_booking_links(ok, gsc.get('pages_by_impressions')),
        'seo_plugin_output_pages': dict(Counter(n for p in ok.values() for n in p.get('seo_plugin_html', []))),
        'translation': {'client_side_plugin': sorted({n for p in ok.values() for n in p.get('translation_plugin', [])}),
                        'pages_with_hreflang': sum(1 for p in ok.values() if p.get('hreflang_count'))},
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
        security.append(f"{wp['posts']['suspicious_count']} suspicious posts (latest change "
                        f"{wp['posts']['latest_suspicious_change'][:10]}); by month: {wp['posts']['suspicious_by_month_modified']}")
    if wp.get('risky_namespaces'):
        security.append('REST namespaces that expose site control (check they require authentication): '
                        + ', '.join(wp['risky_namespaces']))
    if wp.get('users_public'):
        security.append(f"/wp-json/wp/v2/users lists {len(wp['users'])} usernames publicly")
    for h in report['hacked_text']:
        security.append(f"Defacement text \"{h['text']}\" on {h['pages']} pages: " + ', '.join(h['urls'][:8]))
    if spam.get('spam_hits'):
        security.append(f"{len(spam['spam_hits'])} spam-looking search queries in Search Console: "
                        + ', '.join(sorted({h['query'] for h in spam['spam_hits']})[:10]))

    counts = Counter(i['check'] for i in issues)
    findings = {
        'site': site, 'generated': datetime.now().isoformat(timespec='seconds'),
        'pages_scanned': len(ok), 'pages_failed': len(pages) - len(ok),
        'counts': dict(counts),
        'priority_issue_count': sum(1 for i in issues if i['severity'] == 'Priority'),
        'jsonld_sitewide_types': sitewide,
        'jsonld_type_pages': dict(type_pages),
        'tags_in_raw_html': {'gtm': sorted({g for p in ok.values() for g in p['gtm_ids']}),
                             'gtag': sorted({g for p in ok.values() for g in p['gtag_ids']})},
        'booking_links': booking, 'wordpress': wp, 'gsc_spam': spam, 'gsc': gsc, 'security': security,
        'report': report,
        'issues': issues,
        'pages': ok,
    }
    md = findings_md(findings)
    (crawl_dir / 'findings.json').write_text(json.dumps(findings, indent=1, ensure_ascii=False), encoding='utf-8')
    (crawl_dir / 'site_text.json').write_text(json.dumps(texts, ensure_ascii=False), encoding='utf-8')
    (crawl_dir / 'findings.md').write_text(md, encoding='utf-8')
    return {k: findings[k] for k in ('site', 'pages_scanned', 'counts', 'priority_issue_count', 'security',
                                     'jsonld_sitewide_types', 'tags_in_raw_html')} | {
        'booking_links_dead': booking['dead_unique'],
        'files': ['findings.json', 'findings.md', 'site_text.json', 'replace_pairs.csv'],
        'findings_md': md[:8000]}


def findings_md(f):
    """Readable summary with full counts. Per-URL detail stays in findings.json."""
    r, wp, b, g = f['report'], f['wordpress'], f['booking_links'], f['gsc']
    L = [f"# Findings: {f['site']}", '',
         f"Generated {f['generated']} from {f['pages_scanned']} pages. All counts are complete (every page), "
         'not samples. Detail per URL is in findings.json.', '']
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
    for x in lk['broken_targets'][:25]:
        L.append(f"- Broken: {x['target']} ({x.get('status')}) from {x['pages_linking']} pages"
                 + (' [sitewide]' if x['sitewide'] else '') + f", anchor {x['anchors'][:2]}")
    for x in lk['redirected_targets']:
        if x['sitewide']:
            L.append(f"- Sitewide link through a redirect: {x['target']} → {x.get('final')} ({x['pages_linking']} pages)")
    L.append('- Old → final address pairs for a bulk search-and-replace: replace_pairs.csv')
    bh = b.get('hotels', {})
    L.append(f"- Booking links by hotel (Mirai ID): {bh.get('ids_seen')}; own {bh.get('own_mirai_id')} "
             f"{bh.get('own_name', '')}; links opening another hotel: {len(bh.get('links_to_other_hotels', []))}"
             + ('' if bh.get('roster_used') else ' (names need the parity feed: hotel-seo-parity-login)'))
    L.append(f"- Booking links: {b['unique_links_checked']} checked, {len(b['dead_unique'])} dead, "
             f"{len(b['outdated'])} outdated (old booking-step address, past dates, other currency); formats: {b['formats']}")
    L.append('')

    L += ['## Copy consistency', '']
    ph = r['phones']
    L.append(f"- Phone numbers: {[(x['number'], x['pages']) for x in ph['numbers'][:8]]}; odd country codes: "
             f"{[x['number'] for x in ph['odd_country_codes']] or 'none'}")
    for d in r['distance_conflicts']:
        L.append(f"- {d['landmark']}: {list(d['values'])} (different figures for the same place)")
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
          f"pages with hreflang: {tr['pages_with_hreflang']}"]
    if g.get('checked'):
        a = g['arabic_queries']
        L.append(f"- Arabic searches: {a['count']} queries, {a['impressions']} impressions, {a['clicks']} clicks")
    L.append('')

    if g.get('checked'):
        L += ['## Search Console (' + g['window'] + ' vs ' + g['previous'] + ')', '',
              f"- Now: {g['now']}", f"- Before: {g['before']}", f"- Brand terms used: {g['brand_terms']}",
              '- Non-brand searches at positions 4–20: ' + '; '.join(
                  f"{q['query']} ({q['impressions']} impr, pos {q['position']})" for q in g['money_queries_pos_4_20'][:12]),
              '- Old host versions still getting clicks: ' + ('; '.join(
                  f"{x['page']} ({x['clicks']} clicks)" for x in g['host_variant_pages'][:5]) or 'none'),
              '- Booking / account pages in search: ' + ('; '.join(
                  f"{x['page']} ({x['impressions']} impr)" for x in g['booking_and_account_pages'][:5]) or 'none'), '']
    else:
        L += [f"## Search Console: not checked ({g.get('reason')})", '']

    L += [f"- Tags in raw HTML: GTM {f['tags_in_raw_html']['gtm'] or 'none'}, gtag {f['tags_in_raw_html']['gtag'] or 'none'} "
          '(tags injected at runtime only show in inspect_pages)',
          f"- Media Library images: {wp.get('media', {}).get('images', 'n/a')}, missing alt text: "
          f"{wp.get('media', {}).get('missing_alt_text', 'n/a')}"]
    return '\n'.join(L) + '\n'
