"""Site-wide analyses for audit_site, each one computed in code (playbook rule 10).

Added after comparing the plugin's output with the manual Al Bahar and Atana lists of 14 Oct 2026:
every check here is something a manual list found that the first audit did not count.
"""
import csv
import json
import re
import statistics
from collections import Counter, defaultdict
from datetime import date, timedelta
from urllib.parse import urljoin, urlparse, parse_qs

import warnings

import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

warnings.filterwarnings('ignore', category=XMLParsedAsHTMLWarning)

from . import paths

ACCOUNT_PATHS = ['/search/', '/checkout/', '/my-booking/', '/my-bookings/', '/sign-in/', '/signin/', '/sign-up/',
                 '/signup/', '/login/', '/register/', '/profile/', '/account/', '/my-account/', '/thank-you/',
                 '/thankyou/', '/cart/']
BUSINESS_TYPES = {'Hotel', 'Resort', 'LodgingBusiness', 'LocalBusiness', 'BedAndBreakfast', 'Motel', 'Hostel',
                  'Product', 'Restaurant', 'TouristAccommodation'}
OTA_DOMAINS = ('booking.com', 'agoda.', 'expedia.', 'hotels.com', 'trip.com', 'makemytrip.', 'goibibo.',
               'trivago.', 'kayak.', 'hotelscombined.', 'priceline.', 'travelocity.', 'orbitz.')
CITIES = ['Dubai', 'Abu Dhabi', 'Sharjah', 'Ajman', 'Fujairah', 'Ras Al Khaimah', 'Umm Al Quwain', 'Al Ain',
          'Doha', 'Riyadh', 'Jeddah', 'Muscat', 'Manama', 'Kuwait', 'Beirut',
          'Cairo', 'Giza', 'Alexandria', 'New Alamein', 'El Alamein', 'Hurghada', 'Sharm El Sheikh', 'El Gouna',
          'Marsa Matrouh', 'Luxor', 'Aswan', 'Sahl Hasheesh', 'Ain Sokhna']
SEASON = re.compile(r'\b(summer|winter|spring|autumn|ramadan|eid|iftar|christmas|xmas|festive|new year|nye|'
                    r'valentine|diwali|easter|national day)\b', re.I)
SEASON_MONTHS = {'summer': {6, 7, 8, 9}, 'winter': {11, 12, 1, 2, 3}, 'spring': {3, 4, 5}, 'autumn': {9, 10, 11},
                 'christmas': {11, 12}, 'xmas': {11, 12}, 'festive': {11, 12, 1}, 'new year': {12, 1}, 'nye': {12},
                 'valentine': {1, 2}, 'easter': {3, 4}, 'national day': {11, 12}, 'diwali': {10, 11}}
JUNK_SLUG = re.compile(r'^(img|image|images|test|testing|sample-page|hello-world|untitled|draft|copy|new-page|'
                       r'page|\d+|[a-f0-9]{8,}(-htm)?|[a-z0-9]{12,}-htm)$', re.I)
ARCHIVE = re.compile(r'/(19|20)\d{2}/(\d{2}/)?(\d{2}/)?$|/author/|/tag/|/category/|/page/\d+/?$|/feed/?$')
HACKED = re.compile(r'hacked by|defaced by|h[a4]ck[e3]d by|owned by .{0,20}team|was here', re.I)
EMPTY_TEXT = re.compile(r'no content available|nothing found|page not found|coming soon|lorem ipsum', re.I)
GENERIC_WORDS = {'hotel', 'hotels', 'resort', 'resorts', 'suites', 'suite', 'apartments', 'apartment', 'beach',
                 'the', 'and', 'group', 'city', 'tower', 'towers', 'inn', 'spa', 'official', 'site', 'by',
                 # location and descriptor words that sit in hotel names and titles but aren't the brand
                 # (Pearl Marina: "marina" made "hotel apartments in dubai marina" a brand search)
                 'marina', 'heights', 'star', 'stars', 'bay', 'creek', 'downtown', 'barsha', 'jumeirah', 'deira',
                 'palm', 'airport', 'centre', 'center', 'boutique', 'luxury', 'residence', 'residences', 'villa',
                 'villas', 'plaza', 'view', 'sea', 'gate', 'park', 'tecom', 'internet', 'media', 'business',
                 'hurghada', 'sahl', 'hasheesh', 'gouna', 'makadi', 'sokhna', 'corniche', 'island', 'oasis'} | {
                     c.lower().replace(' ', '') for c in CITIES} | {w for c in CITIES for w in c.lower().split()
                                                                     if len(w) > 3}
PRICE = re.compile(r'(?:AED|USD|EUR|SAR|QAR|OMR|INR|\$|€|£)\s?\d[\d,]*(?:\.\d+)?(?:\s?[-–]\s?\d[\d,]*)?'
                   r'|\d[\d,]*(?:\s?[-–]\s?\d[\d,]*)?\s?(?:AED|dirhams?|USD)\b', re.I)
# Only runs that start a number (+ or 00 not glued to other digits/letters) and end at a non-digit:
# joined digit strings (prices, IDs, dates) gave +212 / +220 / +420 on 109 Pearl Marina pages.
PHONE = re.compile(r'(?<![\w+])(?:\+|00)\s?\d{1,3}[\s\-.()]*\d{1,4}[\s\-.()]*\d{2,4}[\s\-.]*\d{3,4}(?!\d)')
SHORT_CODES = {'1', '7', '20', '27', '30', '31', '32', '33', '34', '36', '39', '40', '41', '43', '44', '45', '46',
               '47', '48', '49', '51', '52', '54', '55', '60', '61', '62', '63', '64', '65', '66', '81', '82', '84',
               '86', '90', '91', '92', '93', '94', '95', '98'}
LANDMARK = r"((?:the\s+)?[A-Z][\w'’&.-]*(?:\s+(?:of|al|Al|el|bin|the|de|&)?\s*[A-Z][\w'’&.-]*){0,4})"
DIST_VALUE = r'(\d+(?:\.\d+)?)\s?(km|kms|kilomet(?:er|re)s?|minutes?|mins?|miles?)\b'
DIST_A = re.compile(DIST_VALUE + r'[^.\n]{0,25}?\b(?:from|to|of|away from)\s+' + LANDMARK)
DIST_B = re.compile(LANDMARK + r'\s*(?:[:(–-]|is|is about|is only|at)?\s*\(?\s*' + DIST_VALUE)


def _host(u):
    return urlparse(u).netloc.lower().replace('www.', '')


def _path(u):
    p = urlparse(u).path or '/'
    return p if p.endswith('/') or '.' in p.rsplit('/', 1)[-1] else p + '/'


# ---------------------------------------------------------------- HTTP helpers

def _session(ua):
    s = requests.Session()
    s.headers['User-Agent'] = ua
    return s


def _get(s, url, **kw):
    try:
        return s.get(url, timeout=25, **kw)
    except requests.RequestException:
        return None


# ---------------------------------------------------------------- sitemaps and robots.txt

def _sitemap_entries(text):
    soup = BeautifulSoup(text or '', 'html.parser')
    return [l.get_text().strip() for l in soup.find_all('loc')]


def sitemaps(site, ua):
    """robots.txt Sitemap lines, the usual sitemap URLs, what each lists, and post types they include."""
    s = _session(ua)
    out = {'robots_txt': {}, 'sitemaps': {}}
    r = _get(s, urljoin(site, '/robots.txt'))
    robots = r.text if r is not None and r.status_code == 200 else ''
    out['robots_txt'] = {'status': r.status_code if r is not None else 0,
                         'sitemap_lines': re.findall(r'(?im)^\s*sitemap:\s*(\S+)', robots),
                         'disallow': re.findall(r'(?im)^\s*disallow:\s*(\S+)', robots)[:30]}
    candidates = list(dict.fromkeys(out['robots_txt']['sitemap_lines'] + [
        urljoin(site, p) for p in ('/sitemap_index.xml', '/sitemap.xml', '/wp-sitemap.xml')]))
    for url in candidates:
        r = _get(s, url, allow_redirects=True)
        info = {'status': r.status_code if r is not None else 0, 'final_url': r.url if r is not None else ''}
        if r is not None and r.status_code == 200 and '<' in r.text[:200]:
            children = _sitemap_entries(r.text)
            info['entries'] = len(children)
            if '<sitemapindex' in r.text[:2000]:
                info['child_sitemaps'] = children
                info['includes'] = sorted({m.group(1) for c in children
                                           for m in [re.search(r'(post_tag|tag|category|author|users|date|'
                                                               r'facility|facilities|nearby|attachment|'
                                                               r'offer[_-]?cat\w*|hotel[_-]?cat\w*)', c)] if m})
        out['sitemaps'][url] = info
    return out


# ---------------------------------------------------------------- Search Console

def _gsc():
    if not paths.GSC_TOKEN.exists():
        return None
    from google.auth.transport.requests import AuthorizedSession
    from google.oauth2.credentials import Credentials
    creds = Credentials.from_authorized_user_info(json.loads(paths.GSC_TOKEN.read_text()), paths.gsc_scopes())
    return AuthorizedSession(creds)


def _gsc_query(s, prop, start, end, dims, row_limit=25000):
    url = ('https://www.googleapis.com/webmasters/v3/sites/' + requests.utils.quote(prop, safe='')
           + '/searchAnalytics/query')
    r = s.post(url, json={'startDate': str(start), 'endDate': str(end), 'dimensions': dims,
                          'rowLimit': row_limit}, timeout=90)
    if r.status_code != 200:
        raise RuntimeError(f'Search Console API {r.status_code}: {r.text[:200]}')
    return r.json().get('rows', [])


def _strip_generic(stem):
    """'pearlmarinahotel' -> 'pearl', 'atanahotel' -> 'atana': drop generic and location words from the
    ends of a domain label (only the ends, so a name that merely contains one stays whole)."""
    changed = True
    while changed and stem:
        changed = False
        for w in sorted(GENERIC_WORDS, key=len, reverse=True):
            if len(w) >= 3 and len(stem) > len(w) + 2:
                if stem.endswith(w):
                    stem, changed = stem[:-len(w)], True
                elif stem.startswith(w) and w not in ('al', 'el'):
                    stem, changed = stem[len(w):], True
    return stem


def brand_terms(site_name, home_host, hotel_names=()):
    """Words that make a search a brand search, and where they came from.

    Seeded from the most stable identifiers first: the domain label (atanahotel.com -> "atana"), then
    the hotel's own schema / hotel.json name. The WordPress site title comes last because owners stuff
    it with keywords ("Hotels in Barsha Heights, 4-star hotel..." gave barsha/heights/star and a 3%
    brand share where "atana" queries were 71% of clicks)."""
    terms, source = set(), []
    stem = _strip_generic(re.sub(r'[^a-z0-9]', '', home_host.split('.')[0].lower()))
    if len(stem) >= 4 and stem not in GENERIC_WORDS:
        terms.add(stem)
        source.append(f'domain ({home_host.split(".")[0]})')
    for name in hotel_names:
        words = {w for w in re.findall(r'[a-z0-9]+', (name or '').lower()) if len(w) >= 4 and w not in GENERIC_WORDS}
        # a word already inside the domain stem adds nothing; one that isn't is a real second name token
        new = {w for w in words if not any(w in t for t in terms)}
        if new:
            terms |= new
            source.append(f'hotel name ("{name}")')
    if not terms:
        words = {w for w in re.findall(r'[a-z0-9]+', (site_name or '').lower())
                 if len(w) >= 4 and w not in GENERIC_WORDS}
        if words:
            terms |= words
            source.append(f'site title ("{site_name}"): check these, titles are often keyword-stuffed')
    if not terms and stem:
        terms.add(stem)
        source.append('domain')
    return sorted(t for t in terms if t), '; '.join(source)


def gsc_report(prop, site_name, home_host, days=90, hotel_names=(), hotel_path=''):
    """Brand share, money searches near page one, pages by impressions, host variants, booking pages,
    Arabic searches and submitted sitemaps. Last 90 days vs the 90 before."""
    if not prop:
        return {'checked': False, 'reason': 'no Search Console property given'}
    s = _gsc()
    if s is None:
        return {'checked': False, 'reason': 'no Search Console token (run hotel-seo-auth)'}
    end = date.today() - timedelta(days=2)
    start = end - timedelta(days=days - 1)
    p_end = start - timedelta(days=1)
    p_start = p_end - timedelta(days=days - 1)
    try:
        q_now = _gsc_query(s, prop, start, end, ['query'])
        q_prev = _gsc_query(s, prop, p_start, p_end, ['query'])
        pages_now = _gsc_query(s, prop, start, end, ['page'])
        q_page = _gsc_query(s, prop, start, end, ['query', 'page'])
    except RuntimeError as e:
        return {'checked': False, 'reason': str(e)}
    # The page Google shows for each search. On a domain with several hotels a query-only view hands
    # one hotel's searches to another (a sister's exact brand query listed as this hotel's opportunity).
    top_page = {}
    for r in sorted(q_page, key=lambda r: (r['clicks'], r['impressions'])):
        top_page[r['keys'][0]] = r['keys'][1]
    scope = '/' + hotel_path.strip('/') + '/' if hotel_path and hotel_path.strip('/') else ''

    def sister(q):
        return bool(scope) and q in top_page and not (urlparse(top_page[q]).path + '/').startswith(scope)
    sister_queries = [r for r in q_now if sister(r['keys'][0])]
    if scope:
        q_now = [r for r in q_now if not sister(r['keys'][0])]
        q_prev = [r for r in q_prev if not sister(r['keys'][0])]
        pages_now = [r for r in pages_now if (urlparse(r['keys'][0]).path + '/').startswith(scope)]
    terms, terms_source = brand_terms(site_name, home_host, hotel_names)

    def is_brand(q):
        flat = q.lower().replace(' ', '')
        return any(t in flat for t in terms)

    def totals(rows):
        c = sum(r['clicks'] for r in rows)
        i = sum(r['impressions'] for r in rows)
        bc = sum(r['clicks'] for r in rows if is_brand(r['keys'][0]))
        return {'clicks': c, 'impressions': i, 'brand_clicks': bc,
                'brand_click_share_pct': round(100 * bc / c, 1) if c else None}
    money = sorted(({'query': r['keys'][0], 'impressions': r['impressions'], 'clicks': r['clicks'],
                     'position': round(r['position'], 1), 'top_page': top_page.get(r['keys'][0], '')}
                    for r in q_now if not is_brand(r['keys'][0]) and 4 <= r['position'] <= 20
                    and r['impressions'] >= 30), key=lambda x: -x['impressions'])[:40]
    arabic = [r for r in q_now if re.search(r'[؀-ۿ]', r['keys'][0])]
    variants = [{'page': r['keys'][0], 'clicks': r['clicks'], 'impressions': r['impressions']}
                for r in pages_now if urlparse(r['keys'][0]).scheme == 'http'
                or urlparse(r['keys'][0]).netloc.startswith('www.')]
    account = [{'page': r['keys'][0], 'clicks': r['clicks'], 'impressions': r['impressions']}
               for r in pages_now if any(p.rstrip('/') in urlparse(r['keys'][0]).path for p in ACCOUNT_PATHS)
               or 'idtokenprovider' in r['keys'][0] or 'bookingstep' in r['keys'][0]]
    out = {
        'checked': True, 'property': prop, 'window': f'{start}..{end}', 'previous': f'{p_start}..{p_end}',
        'hotel_path': scope or None,
        'sister_hotel_queries_dropped': {'count': len(sister_queries), 'top': [
            {'query': r['keys'][0], 'clicks': r['clicks'], 'impressions': r['impressions'],
             'top_page': top_page.get(r['keys'][0], '')}
            for r in sorted(sister_queries, key=lambda r: -r['clicks'])[:10]]},
        'brand_terms': terms, 'brand_terms_source': terms_source, 'now': totals(q_now), 'before': totals(q_prev),
        'money_queries_pos_4_20': money,
        'arabic_queries': {'count': len(arabic), 'impressions': sum(r['impressions'] for r in arabic),
                           'clicks': sum(r['clicks'] for r in arabic),
                           'top': [{'query': r['keys'][0], 'impressions': r['impressions'],
                                    'position': round(r['position'], 1)}
                                   for r in sorted(arabic, key=lambda r: -r['impressions'])[:8]]},
        'pages_by_impressions': [{'page': r['keys'][0], 'clicks': r['clicks'], 'impressions': r['impressions'],
                                  'position': round(r['position'], 1)}
                                 for r in sorted(pages_now, key=lambda r: -r['impressions'])[:60]],
        'host_variant_pages': sorted(variants, key=lambda x: -x['clicks'])[:20],
        'booking_and_account_pages': sorted(account, key=lambda x: -x['impressions'])[:20],
    }
    url = 'https://www.googleapis.com/webmasters/v3/sites/' + requests.utils.quote(prop, safe='') + '/sitemaps'
    r = s.get(url, timeout=60)
    if r.status_code == 200:
        out['submitted_sitemaps'] = [{'path': x.get('path'), 'last_downloaded': x.get('lastDownloaded', ''),
                                      'errors': int(x.get('errors', 0)), 'warnings': int(x.get('warnings', 0)),
                                      'pending': x.get('isPending', False),
                                      'submitted': sum(int(c.get('submitted', 0)) for c in x.get('contents', []))}
                                     for x in r.json().get('sitemap', [])]
        live = _session('Mozilla/5.0')
        for x in out['submitted_sitemaps']:
            lr = _get(live, x['path'], allow_redirects=True)
            x['live_status'] = lr.status_code if lr is not None else 0
    return out


# ---------------------------------------------------------------- links

def link_report(data, page_urls, home_host, out_dir):
    """Broken and redirected link targets grouped by target, with how many pages link to them.
    Writes replace_pairs.csv (old address -> final address) for a bulk search-and-replace."""
    by_url = {u['url']: u for u in data.get('urls', [])}
    n_pages = max(1, len(page_urls))
    broken, redirected = defaultdict(lambda: {'sources': set(), 'anchors': Counter()}), \
        defaultdict(lambda: {'sources': set(), 'anchors': Counter()})
    for l in data.get('links', []):
        t = by_url.get(l['target_url'])
        status = l.get('target_status')
        if status in (None, '') and t:
            status = t.get('status_code')
        try:
            status = int(status)
        except (TypeError, ValueError):
            status = None
        anchor = re.sub(r'\s+', ' ', l.get('anchor_text') or '').strip()[:60]
        if status is not None and (status == 0 or status >= 400):
            g = broken[l['target_url']]
            g['status'] = status
            g['internal'] = _host(l['target_url']) == home_host
            g['sources'].add(l['source_url'])
            g['anchors'][anchor] += 1
        if t and t.get('redirects') and _host(l['target_url']) == home_host:
            g = redirected[l['target_url']]
            g['final'] = t.get('redirected_to', '')
            g['hops'] = len(t['redirects'])
            g['sources'].add(l['source_url'])
            g['anchors'][anchor] += 1

    def rows(groups):
        out = []
        for target, g in sorted(groups.items(), key=lambda kv: -len(kv[1]['sources'])):
            n = len(g['sources'])
            row = {'target': target, 'pages_linking': n, 'sitewide': n >= 0.8 * n_pages and n >= 5,
                   'anchors': [a for a, _ in g['anchors'].most_common(3)],
                   'sources': sorted(g['sources'])}
            row.update({k: g[k] for k in ('status', 'internal', 'final', 'hops') if k in g})
            out.append(row)
        return out
    b, r = rows(broken), rows(redirected)
    pairs = {}
    for g in r:
        if g.get('final') and g['final'].rstrip('/') != g['target'].rstrip('/'):
            pairs[g['target']] = (g['final'], g['pages_linking'])
    with open(out_dir / 'replace_pairs.csv', 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['search', 'replace', 'pages_linking'])
        for src, (dst, n) in sorted(pairs.items(), key=lambda kv: -kv[1][1]):
            w.writerow([src, dst, n])
    return {'broken_targets': b, 'redirected_targets': r,
            'counts': {'broken_internal_targets': sum(1 for x in b if x.get('internal')),
                       'broken_external_targets': sum(1 for x in b if not x.get('internal')),
                       'sitewide_broken': sum(1 for x in b if x['sitewide']),
                       'redirected_targets': len(r), 'sitewide_redirected': sum(1 for x in r if x['sitewide']),
                       'redirect_chains': sum(1 for x in r if x.get('hops', 1) > 1),
                       'pages_with_redirected_links': len({s for x in r for s in x['sources']}),
                       'replace_pairs': len(pairs)}}


# ---------------------------------------------------------------- canonicals

def canonical_targets(pages, data, ua):
    """Canonicals that point somewhere other than the page itself: where do they lead?
    A canonical to a redirect or a 404 means Google can index neither address."""
    by_url = {u['url'].rstrip('/'): u for u in data.get('urls', [])}
    s = _session(ua)
    cache, out = {}, []
    for url, p in pages.items():
        c = p.get('canonical') or ''
        if not c or c.rstrip('/') == url.rstrip('/'):
            continue
        c_abs = urljoin(url, c)
        if c_abs not in cache:
            u = by_url.get(c_abs.rstrip('/'))
            if u is not None and u.get('redirects'):
                cache[c_abs] = (int(u['redirects'][0].get('status_code') or 301), u.get('redirected_to', ''))
            else:
                r = _get(s, c_abs, allow_redirects=False)
                cache[c_abs] = (r.status_code if r is not None else 0,
                                r.headers.get('Location', '') if r is not None else '')
        status, loc = cache[c_abs]
        kind = 'ok_other_page' if status == 200 else 'to_redirect' if 300 <= status < 400 else 'to_error'
        loops_back = bool(loc) and urljoin(c_abs, loc).rstrip('/') == url.rstrip('/')
        out.append({'url': url, 'canonical': c, 'canonical_status': status, 'redirects_to': loc,
                    'kind': kind, 'redirects_back_to_page': loops_back})
    return out


# ---------------------------------------------------------------- titles

SEP = re.compile(r'\s+[|–—-]\s+|\s*\|\s*')


def title_report(pages, site_name):
    titles = {u: p['title'] for u, p in pages.items() if p.get('title')}
    suffixes = Counter()
    for t in titles.values():
        parts = SEP.split(t)
        if len(parts) > 1:
            suffixes[parts[-1].strip()] += 1
    n = max(1, len(titles))
    common = [{'suffix': s, 'pages': c, 'chars': len(s), 'stuffed': s.count(',') >= 1 or len(s) > 40}
              for s, c in suffixes.most_common(5) if c >= max(3, 0.3 * n)]
    default_wp = []
    if site_name:
        pat = re.compile(r'^(.+?)\s+[–-]\s+' + re.escape(site_name) + r'$')
        default_wp = [u for u, t in titles.items() if pat.match(t)]
    dupes = defaultdict(list)
    for u, t in titles.items():
        dupes[t].append(u)
    return {'common_suffixes': common, 'default_wordpress_titles': default_wp,
            'duplicate_titles': {t: us for t, us in dupes.items() if len(us) > 1},
            'meta_description_coverage': f"{sum(1 for p in pages.values() if p.get('meta_description'))} of {len(pages)}"}


def old_years(pages, today=None):
    year = (today or date.today()).year
    old = re.compile(r'\b(20[12]\d)\b')
    out = []
    for u, p in pages.items():
        hay = ' '.join([p.get('title', '')] + p.get('h1', []))
        ys = sorted({int(y) for y in old.findall(hay) if int(y) < year})
        slug_years = sorted({int(y) for y in old.findall(urlparse(u).path) if int(y) < year})
        if ys or slug_years:
            out.append({'url': u, 'years_in_title_or_h1': ys, 'years_in_url': slug_years,
                        'title': p.get('title', '')})
    return out


# ---------------------------------------------------------------- page groups

def archive_pages(data, home_host):
    kinds = {'date': re.compile(r'/(19|20)\d{2}/(\d{2}/)?(\d{2}/)?$'), 'author': re.compile(r'/author/'),
             'tag': re.compile(r'/tag/'), 'category': re.compile(r'/(category|blogs?/category)/'),
             'feed': re.compile(r'/feed/?$'), 'pagination': re.compile(r'/page/\d+/?$'),
             'attachment': re.compile(r'[?&]attachment_id=|/attachment/')}
    out = defaultdict(list)
    for u in data.get('urls', []):
        if _host(u['url']) != home_host or u.get('redirects') or str(u.get('status_code')) != '200':
            continue
        if 'noindex' in (u.get('robots') or '').lower():
            continue
        for k, rx in kinds.items():
            if rx.search(u['url']):
                out[k].append(u['url'])
                break
    return {k: {'count': len(v), 'urls': v} for k, v in out.items()}


def page_groups(pages, texts_words):
    """Thin page groups by first path segment (e.g. /facility/, /nearby/), empty and junk pages."""
    groups = defaultdict(list)
    for u in pages:
        seg = [x for x in urlparse(u).path.split('/') if x]
        if len(seg) >= 2:
            groups[seg[0]].append(u)
    thin = []
    for g, us in groups.items():
        words = [texts_words.get(u, 0) for u in us]
        if len(us) >= 3 and statistics.median(words) < 150:
            thin.append({'group': f'/{g}/', 'pages': len(us), 'median_content_words': int(statistics.median(words)),
                         'urls': sorted(us)})
    empty, junk = [], []
    in_thin = {u for g in thin for u in g['urls']}
    for u, p in pages.items():
        last = [x for x in urlparse(u).path.split('/') if x]
        if last and JUNK_SLUG.match(last[-1]) and not re.fullmatch(r'\d+', last[-1]):
            junk.append(u)
        if urlparse(u).query or ARCHIVE.search(urlparse(u).path):
            continue                       # booking-engine URLs and archives are reported elsewhere
        w = texts_words.get(u, 0)
        if EMPTY_TEXT.search(p.get('main_text_start', '')) or (w < 15 and u not in in_thin
                                                               and not re.search(r'galler|photo', u)):
            empty.append({'url': u, 'content_words': w, 'title': p.get('title', ''),
                          'says': (EMPTY_TEXT.search(p.get('main_text_start', '')) or [''])[0]})
    return {'thin_groups': sorted(thin, key=lambda x: -x['pages']), 'empty_pages': empty, 'junk_slugs': junk}


def account_pages(site, ua, crawled):
    """Booking-engine and account pages that Google may index: status and robots for the usual paths."""
    s = _session(ua)
    out = []
    crawled_paths = {_path(u): u for u in crawled}
    for p in ACCOUNT_PATHS:
        r = _get(s, urljoin(site, p), allow_redirects=True)
        if r is None or r.status_code != 200 or _path(r.url) != p:
            continue
        soup = BeautifulSoup(r.text, 'html.parser')
        m = soup.find('meta', attrs={'name': re.compile('^robots$', re.I)})
        robots = ((m.get('content') or '') if m else '') + ' ' + r.headers.get('X-Robots-Tag', '')
        out.append({'url': r.url, 'noindex': 'noindex' in robots.lower(), 'robots': robots.strip(),
                    'in_crawl': p in crawled_paths})
    return out


# ---------------------------------------------------------------- schema

def _first(v):
    return v[0] if isinstance(v, list) and v else v


def schema_report(pages):
    """Every distinct JSON-LD business/review block with the pages it is on and what is wrong with it."""
    blocks = {}
    for u, p in pages.items():
        for n in p.get('jsonld_nodes', []):
            key = (n['type'], n.get('name', ''), n.get('street', ''), n.get('geo', ''))
            b = blocks.setdefault(key, dict(n, pages=0, urls=[]))
            b['pages'] += 1
            if len(b['urls']) < 3:
                b['urls'].append(u)
    n_pages = max(1, len(pages))
    out = []
    for b in blocks.values():
        flags = []
        if b.get('reviews') or b.get('rating'):
            flags.append('review or rating markup about the hotel itself (self-serving reviews: against Google rules)')
        if b['type'] == 'Review':
            flags.append('standalone Review block')
        if b.get('ota_sameas'):
            flags.append('sameAs points to OTA pages: ' + ', '.join(b['ota_sameas']))
        if b.get('price_range'):
            flags.append(f"priceRange \"{b['price_range']}\" ([CONFIRM] or delete)")
        if b['type'] == 'FAQPage' and b['pages'] > 3:
            flags.append(f"FAQPage on {b['pages']} pages (homepage only)")
        if b['type'] in BUSINESS_TYPES and b['pages'] >= 0.8 * n_pages and n_pages > 5:
            flags.append(f"on {b['pages']} of {n_pages} pages (sitewide)")
        b['flags'] = flags
        out.append(b)
    business = [b for b in out if b['type'] in BUSINESS_TYPES]
    names = {b.get('name') for b in business if b.get('name')}
    geos = {b.get('geo') for b in business if b.get('geo')}
    conflicts = []
    if len(names) > 1:
        conflicts.append('business blocks use different names: ' + ' / '.join(sorted(names)))
    if len(geos) > 1:
        conflicts.append('business blocks use different coordinates: ' + ' / '.join(sorted(geos)))
    return {'blocks': sorted(out, key=lambda b: (-b['pages'], b['type'])), 'conflicts': conflicts}


def jsonld_nodes(data):
    """Compact summary of each JSON-LD node on a page (used by schema_report)."""
    nodes = data.get('@graph', [data]) if isinstance(data, dict) else data if isinstance(data, list) else []
    out = []
    for n in nodes:
        if not isinstance(n, dict):
            continue
        t = n.get('@type')
        t = '/'.join(t) if isinstance(t, list) else str(t or '')
        if not any(x in t for x in BUSINESS_TYPES | {'Review', 'FAQPage', 'Organization', 'AggregateRating'}):
            continue
        addr = _first(n.get('address')) or {}
        geo = n.get('geo') or {}
        same = n.get('sameAs') or []
        same = same if isinstance(same, list) else [same]
        reviews = n.get('review') or []
        reviews = reviews if isinstance(reviews, list) else [reviews]
        rating = n.get('aggregateRating') or (n.get('reviewRating') if 'Review' in t else None)
        out.append({
            'type': t.split('/')[0] if t.split('/')[0] in BUSINESS_TYPES else t,
            'name': str(n.get('name', ''))[:80],
            'street': str(addr.get('streetAddress', '') if isinstance(addr, dict) else addr)[:80],
            'locality': str(addr.get('addressLocality', '') if isinstance(addr, dict) else '')[:40],
            'geo': f"{geo.get('latitude', '')},{geo.get('longitude', '')}" if isinstance(geo, dict) and geo else '',
            'price_range': str(n.get('priceRange', '') or ''),
            'ota_sameas': [x for x in same if isinstance(x, str) and any(d in x for d in OTA_DOMAINS)],
            'rating': json.dumps(rating, ensure_ascii=False)[:120] if rating else '',
            'reviews': [str((_first(r.get('author')) or {}).get('name', '') if isinstance(_first(r.get('author')), dict)
                            else _first(r.get('author')) or '')[:40] for r in reviews if isinstance(r, dict)],
            'rooms': str(n.get('numberOfRooms', '') or ''),
            'telephone': str(_first(n.get('telephone')) or '')[:40],
            'maps_sameas': [x for x in same + [n.get('hasMap') or '']
                            if isinstance(x, str) and re.search(r'google\.[a-z.]+/maps|maps\.app\.goo\.gl|g\.page|[?&]cid=', x)],
        })
    return out


# ---------------------------------------------------------------- copy consistency

def country_code(n):
    for k in (1, 2):
        if n[:k] in SHORT_CODES:
            return n[:k]
    return n[:3]


def phone_report(pages):
    """Phone numbers from tel: links (reliable) and from visible text runs that start with + or 00.
    Odd country codes are judged against the tel: links; a text-only odd number is listed to check by
    eye, not raised as an issue."""
    tel, text = Counter(), Counter()
    where = defaultdict(set)
    for u, p in pages.items():
        for ph in p.get('phones', []):
            tel[ph] += 1
            where[ph].add(u)
        for ph in p.get('phones_text', []):
            text[ph] += 1
            where[ph].add(u)
    if not tel and not text:
        return {'numbers': [], 'odd_country_codes': [], 'odd_country_codes_text_only': []}
    main_cc = Counter(country_code(n) for n in (tel or text).elements()).most_common(1)[0][0]
    rows = [{'number': '+' + n, 'pages': len(where[n]), 'in_tel_links': tel[n], 'urls': sorted(where[n])[:10]}
            for n in sorted(set(tel) | set(text), key=lambda n: -len(where[n]))]
    odd = [r for r in rows if country_code(r['number'][1:]) != main_cc]
    return {'numbers': rows, 'main_country_code': '+' + main_cc,
            'main_code_from': 'tel: links' if tel else 'page text (no tel: links)',
            'odd_country_codes': [r for r in odd if r['in_tel_links']],
            'odd_country_codes_text_only': [r for r in odd if not r['in_tel_links']]}


def distance_conflicts(texts):
    found = defaultdict(lambda: defaultdict(set))
    for u, t in texts.items():
        for rx, (vi, ui, li) in ((DIST_A, (1, 2, 3)), (DIST_B, (2, 3, 1))):
            for m in rx.finditer(t):
                lm = re.sub(r'^the\s+', '', m.group(li).strip(), flags=re.I).strip(' .,:;')
                if len(lm) < 4 or lm.lower() in {'from', 'about', 'only', 'just'}:
                    continue
                unit = m.group(ui).lower()
                unit = 'km' if unit.startswith('k') else 'min' if unit.startswith('min') else unit
                found[lm.lower()][f'{float(m.group(vi)):g} {unit}'].add(u)
    out = []
    for lm, vals in found.items():
        by_unit = defaultdict(set)
        for v in vals:
            by_unit[v.split()[1]].add(v)
        if any(len(v) > 1 for v in by_unit.values()):
            out.append({'landmark': lm, 'values': {v: sorted(us)[:5] for v, us in vals.items()}})
    return out


def price_mentions(texts, pages):
    out = []
    for u, t in texts.items():
        hits = sorted({m.group(0).strip() for m in PRICE.finditer(t)})
        if hits:
            out.append({'url': u, 'page_type': pages.get(u, {}).get('type', ''), 'prices': hits[:10]})
    return out


def season_report(pages, texts, today=None):
    month = (today or date.today()).month
    out = []
    for u, p in pages.items():
        hay_head = ' '.join([p.get('title', ''), urlparse(u).path.replace('-', ' ')] + p.get('h1', []))
        words = {m.group(1).lower() for m in SEASON.finditer(hay_head)}
        if p.get('type') == 'offers':
            words |= {m.group(1).lower() for m in SEASON.finditer(texts.get(u, '')[:3000])}
        off = [w for w in words if w in SEASON_MONTHS and month not in SEASON_MONTHS[w]]
        if off:
            out.append({'url': u, 'page_type': p.get('type'), 'out_of_season_words': sorted(off),
                        'title': p.get('title', '')})
    return out


def city_report(pages, hotel_city):
    if not hotel_city:
        return {'hotel_city': '', 'pages': []}
    others = [c for c in CITIES if c.lower() != hotel_city.lower()]
    rx = re.compile(r'\b(' + '|'.join(map(re.escape, others)) + r')\b', re.I)
    out = []
    for u, p in pages.items():
        if p.get('type') == 'blog' or ARCHIVE.search(urlparse(u).path):
            continue
        for field, vals in (('title', [p.get('title', '')]), ('h1', p.get('h1', [])),
                            ('meta', [p.get('meta_description', '')])):
            for v in vals:
                m = rx.search(v or '')
                if m and hotel_city.lower() not in (v or '').lower()[:m.start()][-30:]:
                    out.append({'url': u, 'field': field, 'text': v, 'city': m.group(1)})
    return {'hotel_city': hotel_city, 'pages': out}


CITY_COUNTRY = {**{c: 'UAE' for c in ('Dubai', 'Abu Dhabi', 'Sharjah', 'Ajman', 'Fujairah', 'Ras Al Khaimah',
                                       'Umm Al Quwain', 'Al Ain')},
                'Doha': 'Qatar', 'Riyadh': 'Saudi Arabia', 'Jeddah': 'Saudi Arabia', 'Muscat': 'Oman',
                'Manama': 'Bahrain', 'Kuwait': 'Kuwait', 'Beirut': 'Lebanon',
                **{c: 'Egypt' for c in ('Cairo', 'Giza', 'Alexandria', 'New Alamein', 'El Alamein', 'Hurghada',
                                        'Sharm El Sheikh', 'El Gouna', 'Marsa Matrouh', 'Luxor', 'Aswan',
                                        'Sahl Hasheesh', 'Ain Sokhna')}}
TLD_COUNTRY = {'ae': 'UAE', 'eg': 'Egypt', 'qa': 'Qatar', 'sa': 'Saudi Arabia', 'om': 'Oman', 'bh': 'Bahrain',
               'kw': 'Kuwait', 'lb': 'Lebanon'}


def hotel_city(pages):
    return hotel_city_with_source(pages)['city']


def hotel_city_with_source(pages, home_host='', hotel_path=''):
    """The hotel's city when the operator didn't give one, with where it came from, so a wrong guess is
    visible. On a domain with several hotels the sitewide schema can be another property's block (two
    Egyptian hotels were audited as Fujairah), so pages under hotel_path are read first."""
    scope = '/' + hotel_path.strip('/') + '/' if hotel_path and hotel_path.strip('/') else ''
    own = {u: p for u, p in pages.items() if scope and (urlparse(u).path + '/').startswith(scope)} or pages
    rest = [p for u, p in pages.items() if u not in own]
    # a block that also sits on most pages outside the hotel's section is the sitewide (sister) block
    sitewide = Counter((n.get('name'), n.get('locality')) for p in rest for n in p.get('jsonld_nodes', [])
                       if n['type'] in BUSINESS_TYPES)
    shared = {k for k, c in sitewide.items() if rest and c >= 0.5 * len(rest)}
    loc, names = Counter(), Counter()
    for p in own.values():
        for n in p.get('jsonld_nodes', []):
            if own is not pages and (n.get('name'), n.get('locality')) in shared:
                continue
            if n['type'] in BUSINESS_TYPES and n.get('locality'):
                for c in CITIES:
                    if c.lower() in n['locality'].lower():
                        loc[c] += 1
                        names[(c, n.get('name', ''))] += 1
    city, source = '', 'not found: pass hotel_city'
    if loc:
        city = loc.most_common(1)[0][0]
        blocks = ', '.join(f'"{nm}"' for (c, nm), _ in names.most_common() if c == city and nm)[:120]
        source = (f'schema addressLocality on {loc[city]} pages' + (f' ({blocks})' if blocks else '')
                  + (f'; other cities in schema: {dict(loc)}' if len(loc) > 1 else ''))
    else:
        home = next((p for p in own.values() if p.get('type') == 'home'), {})
        hay = ' '.join([home.get('title', '')] + home.get('h1', []))
        for c in CITIES:
            if c.lower() in hay.lower():
                city, source = c, 'homepage title / H1'
                break
    warning = ''
    tld_country = TLD_COUNTRY.get(home_host.rsplit('.', 1)[-1]) if home_host else None
    if city and tld_country and CITY_COUNTRY.get(city) != tld_country:
        warning = (f'inferred city {city} ({CITY_COUNTRY.get(city)}) is not in the country of the domain '
                   f'(.{home_host.rsplit(".", 1)[-1]} = {tld_country}): pass hotel_city and run again')
    elif city and len(loc) > 1:
        warning = f'schema names several cities {dict(loc)}: pass hotel_city (and hotel_path on a multi-hotel domain)'
    return {'city': city, 'source': source, 'given': False, 'warning': warning}


def hacked_text(texts):
    """Defacement signatures ("Hacked by ...") in the visible text of any page."""
    out = defaultdict(list)
    for u, t in texts.items():
        for m in HACKED.finditer(t):
            out[' '.join(t[m.start():m.start() + 60].split()[:3])].append(u)   # "Hacked by CoupDeGrace"
    return [{'text': k, 'pages': len(set(v)), 'urls': sorted(set(v))} for k, v in out.items()]


def blog_booking_links(pages, gsc_pages=None):
    """Blog posts and whether they link on to the rooms or the booking engine, busiest first."""
    imp = {}
    for r in gsc_pages or []:
        imp[r['page'].rstrip('/')] = r['impressions']
    out = []
    for u, p in pages.items():
        if p.get('type') != 'blog' or not re.search(r'/blogs?/[^/]+/', urlparse(u).path):
            continue
        out.append({'url': u, 'links_to_rooms': p.get('links_rooms', False),
                    'links_to_booking': p.get('links_booking', False),
                    'impressions': imp.get(u.rstrip('/'), 0)})
    return sorted(out, key=lambda x: -x['impressions'])
