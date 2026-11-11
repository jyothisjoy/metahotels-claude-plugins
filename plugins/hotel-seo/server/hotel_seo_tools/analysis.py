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
                         'disallow': re.findall(r'(?im)^\s*disallow:\s*(\S+)', robots)}
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


def _gsc_query(s, prop, start, end, dims, row_limit=25000, search_type='web', max_rows=200000, filters=None):
    """Search Analytics rows, paged with startRow (one call returns at most 25,000 rows; a group domain's
    query x page report is bigger than that)."""
    url = ('https://www.googleapis.com/webmasters/v3/sites/' + requests.utils.quote(prop, safe='')
           + '/searchAnalytics/query')
    want = max_rows if row_limit >= 25000 else row_limit   # 25000 (the default) means "all rows"
    rows, page = [], min(row_limit, 25000)
    while True:
        body = {'startDate': str(start), 'endDate': str(end), 'dimensions': dims, 'rowLimit': page,
                'startRow': len(rows), 'type': search_type}
        if filters:
            body['dimensionFilterGroups'] = [{'filters': filters}]
        r = s.post(url, json=body, timeout=90)
        if r.status_code != 200:
            raise RuntimeError(f'Search Console API {r.status_code}: {r.text[:200]}')
        got = r.json().get('rows', [])
        rows += got
        if len(got) < page or len(rows) >= want:
            return rows[:want]


def _gsc_site_totals(s, prop, start, end, scope=''):
    """Clicks and impressions for the whole property (or the hotel's section) with no dimension: this
    includes the anonymised searches that query rows leave out, often a large share on small hotel sites."""
    filters = [{'dimension': 'page', 'operator': 'contains', 'expression': scope}] if scope else None
    rows = _gsc_query(s, prop, start, end, [], row_limit=1, filters=filters)
    return {'clicks': rows[0]['clicks'], 'impressions': rows[0]['impressions']} if rows else \
        {'clicks': 0, 'impressions': 0}


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


# Google's logging error: Search Console over-reported impressions from 13 May 2025 to 27 Apr 2026 and the
# history won't be corrected (clicks were not affected). Impressions, CTR and average position compared
# across that window are not like for like.
GSC_IMPRESSIONS_ANOMALY = (date(2025, 5, 13), date(2026, 4, 27))


def gsc_anomaly_note(*windows):
    """A warning when any (start, end) window overlaps the inflated-impressions period, else ''."""
    a0, a1 = GSC_IMPRESSIONS_ANOMALY
    hit = [f'{s}..{e}' for s, e in windows if s <= a1 and e >= a0]
    if not hit:
        return ''
    return (f"window {', '.join(hit)} overlaps Google's impressions logging error ({a0}..{a1}): impressions were "
            'over-reported and not corrected, so compare clicks only; impressions, CTR and position changes '
            'across it are not real')


def gsc_report(prop, site_name, home_host, days=90, hotel_names=(), hotel_path='', other_sites=None):
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

    def totals(rows, w_start, w_end):
        c = sum(r['clicks'] for r in rows)
        i = sum(r['impressions'] for r in rows)
        bc = sum(r['clicks'] for r in rows if is_brand(r['keys'][0]))
        try:
            site = _gsc_site_totals(s, prop, w_start, w_end, scope)
        except RuntimeError:
            site = {'clicks': None, 'impressions': None}
        # Query rows leave out anonymised (rare) searches: the site total is the real one. Brand share is a
        # share of the clicks Google attributes to a query, and says so.
        return {'clicks': site['clicks'] if site['clicks'] is not None else c,
                'impressions': site['impressions'] if site['impressions'] is not None else i,
                'query_attributed_clicks': c,
                'anonymised_clicks_pct': round(100 * (site['clicks'] - c) / site['clicks'], 1)
                if site['clicks'] else None,
                'brand_clicks': bc,
                'brand_click_share_pct': round(100 * bc / c, 1) if c else None,
                'brand_share_note': 'share of clicks Google attributes to a query (anonymised searches excluded)'}
    def other_site(q):
        """Searches that belong to the hotel's other websites (Abar, Nov 2026: restaurant and iftar searches are
        gulcafe.com's, the in-house restaurant's own site: link there, don't compete with it)."""
        for o in other_sites or []:
            if any(t.lower() in q.lower() for t in o.get('terms', [])):
                return o.get('domain', '')
        return ''

    def page_lang(u):
        m = re.match(r'^/([a-z]{2})(?:-[a-z]{2})?/', urlparse(u or '').path.lower())
        return m.group(1) if m else 'en'

    candidates = [r for r in q_now if not is_brand(r['keys'][0]) and 4 <= r['position'] <= 20
                  and r['impressions'] >= 30]
    left_out = [{'query': r['keys'][0], 'impressions': r['impressions'], 'belongs_to': other_site(r['keys'][0])}
                for r in candidates if other_site(r['keys'][0])]
    money = []
    for r in sorted(candidates, key=lambda r: -r['impressions']):
        q = r['keys'][0]
        if other_site(q):
            continue
        tp = top_page.get(q, '')
        q_lang = 'ar' if ARABIC.search(q) else 'en'
        # Rose, Nov 2026: English searches were aimed at the /ar/ homepage, which had no impressions. A search
        # is only matched with a page in its own language.
        money.append({'query': q, 'impressions': r['impressions'], 'clicks': r['clicks'],
                      'position': round(r['position'], 1), 'top_page': tp,
                      'language_mismatch': bool(tp) and (q_lang == 'ar') != (page_lang(tp) == 'ar')})
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
        'brand_terms': terms, 'brand_terms_source': terms_source, 'now': totals(q_now, start, end), 'before': totals(q_prev, p_start, p_end),
        'money_queries_pos_4_20': money,
        'left_out_other_sites': left_out[:20],
        'arabic_queries': {'count': len(arabic), 'impressions': sum(r['impressions'] for r in arabic),
                           'clicks': sum(r['clicks'] for r in arabic),
                           'top': [{'query': r['keys'][0], 'impressions': r['impressions'],
                                    'position': round(r['position'], 1)}
                                   for r in sorted(arabic, key=lambda r: -r['impressions'])]},
        'pages_by_impressions': [{'page': r['keys'][0], 'clicks': r['clicks'], 'impressions': r['impressions'],
                                  'position': round(r['position'], 1)}
                                 for r in sorted(pages_now, key=lambda r: -r['impressions'])],
        'host_variant_pages': sorted(variants, key=lambda x: -x['clicks']),
        'booking_and_account_pages': sorted(account, key=lambda x: -x['impressions']),
        'impressions_anomaly': gsc_anomaly_note((start, end), (p_start, p_end)),
        'pages_with_impressions_16m': _pages_16m(s, prop, end, scope),
        'image_search': gsc_image_search(s, prop, start, end, scope),
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


def _pages_16m(s, prop, end, scope=''):
    """Every page with at least one impression in the last 16 months (Search Console's whole history). A page a list
    targets that isn't here has had no search impressions at all (Rose, Nov 2026: English searches were aimed at the
    /ar/ homepage, 0 impressions)."""
    try:
        rows = _gsc_query(s, prop, end - timedelta(days=480), end, ['page'])
    except RuntimeError:
        return None
    return sorted(r['keys'][0] for r in rows if not scope or (urlparse(r['keys'][0]).path + '/').startswith(scope))


def key_pages_without_impressions(pages, gsc):
    """Indexable home / room / offer / contact pages with no impressions in 16 months."""
    seen = gsc.get('pages_with_impressions_16m')
    if seen is None:
        return None
    have = {u.rstrip('/').replace('://www.', '://') for u in seen}
    return sorted(u for u, p in pages.items() if p.get('type') in ('home', 'rooms', 'offers', 'contact')
                  and 'noindex' not in (p.get('robots', '') + ' ' + p.get('x_robots_tag', '')).lower()
                  and u.rstrip('/').replace('://www.', '://') not in have)


def gsc_image_search(s, prop, start, end, scope=''):
    """Google Images: totals, the site's own image CTR, and pages with many image impressions but a CTR
    below the site's median (hotel photos are searched; this tab is rarely looked at)."""
    try:
        pages = _gsc_query(s, prop, start, end, ['page'], search_type='image')
        queries = _gsc_query(s, prop, start, end, ['query'], row_limit=1000, search_type='image')
    except RuntimeError as e:
        return {'checked': False, 'reason': str(e)}
    if scope:
        pages = [r for r in pages if (urlparse(r['keys'][0]).path + '/').startswith(scope)]
    clicks = sum(r['clicks'] for r in pages)
    impr = sum(r['impressions'] for r in pages)
    ctrs = [r['clicks'] / r['impressions'] for r in pages if r['impressions'] >= 100]
    med = statistics.median(ctrs) if ctrs else None
    med_impr = statistics.median([r['impressions'] for r in pages]) if pages else 0
    low = [{'page': r['keys'][0], 'impressions': r['impressions'], 'clicks': r['clicks'],
            'ctr_pct': round(100 * r['clicks'] / r['impressions'], 2)}
           for r in pages if med is not None and r['impressions'] >= max(100, med_impr)
           and r['clicks'] / r['impressions'] < med]
    return {'checked': True, 'clicks': clicks, 'impressions': impr,
            'ctr_pct': round(100 * clicks / impr, 2) if impr else None,
            'median_page_ctr_pct': round(100 * med, 2) if med is not None else None,
            'top_pages': [{'page': r['keys'][0], 'impressions': r['impressions'], 'clicks': r['clicks']}
                          for r in sorted(pages, key=lambda r: -r['impressions'])[:15]],
            'high_impressions_low_ctr': sorted(low, key=lambda x: -x['impressions'])[:15],
            'top_queries': [{'query': r['keys'][0], 'impressions': r['impressions'], 'clicks': r['clicks']}
                            for r in sorted(queries, key=lambda r: -r['impressions'])[:15]]}


# ---------------------------------------------------------------- AI search crawlers

# Search crawlers that decide whether the site can be shown (and linked) in AI answers.
AI_SEARCH_BOTS = {
    'OAI-SearchBot': 'Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; OAI-SearchBot/1.0; '
                     '+https://openai.com/searchbot',
    'PerplexityBot': 'Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; PerplexityBot/1.0; '
                     '+https://perplexity.ai/perplexitybot)',
    'Claude-SearchBot': 'Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; Claude-SearchBot/1.0; '
                        '+https://www.anthropic.com)',
    'Googlebot': 'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)',
    'Bingbot': 'Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)',
}
# Training-only crawlers: blocking them is the owner's choice and doesn't remove search visibility.
AI_TRAINING_BOTS = ('GPTBot', 'ClaudeBot', 'Google-Extended', 'Applebot-Extended', 'CCBot')
# Agents that fetch a page because a guest asked them to ("check this hotel and book me a room"). They
# generally don't follow robots.txt, so only the firewall can stop them: firewall test only.
AI_USER_AGENTS = {
    'ChatGPT-User': 'Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; ChatGPT-User/1.0; '
                    '+https://openai.com/bot',
    'Claude-User': 'Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; Claude-User/1.0; '
                   '+Claude-User@anthropic.com)',
    'Perplexity-User': 'Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; Perplexity-User/1.0; '
                       '+https://perplexity.ai/perplexity-user)',
}
# Vendor challenge pages only. A bare "captcha" is NOT a block: reCAPTCHA on a contact form is on most
# hotel homepages.
CHALLENGE = re.compile(r'challenge-platform|cf-chl-|<title>\s*Just a moment\.\.\.|Attention Required! \| Cloudflare|'
                       r'px-captcha|captcha-delivery\.com|datadome|sgcaptcha|/\.well-known/sgcaptcha', re.I)


def _robots_groups(text):
    """robots.txt as Google reads it (RFC 9309): groups of user-agent lines with their allow/disallow rules."""
    groups, cur, last_ua = [], None, False
    for raw in text.splitlines():
        line = raw.split('#', 1)[0].strip()
        if ':' not in line:
            continue
        key, val = (x.strip() for x in line.split(':', 1))
        key = key.lower()
        if key == 'user-agent':
            if not last_ua:
                cur = {'agents': [], 'rules': []}
                groups.append(cur)
            cur['agents'].append(val.lower())
            last_ua = True
        elif key in ('allow', 'disallow') and cur is not None:
            cur['rules'].append((key, val))
            last_ua = False
        else:
            last_ua = False
    return groups


def _robots_rule_rx(path):
    rx = re.escape(path).replace(r'\*', '.*')
    return re.compile('^' + (rx[:-2] + '$' if rx.endswith(r'\$') else rx))


def robots_allowed(text, bot, path):
    """Google's matching: the group whose user-agent is the bot's product token (else '*'); within it the
    longest matching rule wins, and Allow wins a tie. Several groups for the same agent are merged."""
    token = bot.lower()
    groups = _robots_groups(text)
    rules = [r for g in groups if token in g['agents'] for r in g['rules']]
    if not any(token in g['agents'] for g in groups):
        rules = [r for g in groups if '*' in g['agents'] for r in g['rules']]
    best = None
    for kind, val in rules:
        if not val:
            continue  # "Disallow:" with no path allows everything
        if _robots_rule_rx(val).match(path):
            key = (len(val), kind == 'allow')
            if best is None or key > best[0]:
                best = (key, kind)
    return best is None or best[1] == 'allow'


def ai_access(site, ua, extra_urls=()):
    """Can AI search crawlers and guest-triggered AI agents reach the site? robots.txt per crawler, read the
    way Google reads it, for the homepage and key pages; plus a user-agent test against the firewall,
    judged against a normal browser fetch of the same page. A spoofed user agent is a signal, not proof:
    CDNs that verify crawlers by IP block a fake Googlebot/Bingbot on purpose, so those aren't judged."""
    s = _session(ua)
    home = site.rstrip('/') + '/'
    test_urls = [home] + [u for u in extra_urls if u and u.rstrip('/') != home.rstrip('/')][:2]
    r = _get(s, urljoin(site, '/robots.txt'))
    text = r.text if r is not None and r.status_code == 200 else ''
    named = {a for g in _robots_groups(text) for a in g['agents']}
    robots = {}
    for bot in list(AI_SEARCH_BOTS) + list(AI_TRAINING_BOTS):
        blocked = [u for u in test_urls
                   if not robots_allowed(text, bot, urlparse(u).path or '/')]
        robots[bot] = {'allowed': not blocked, 'blocked_urls': blocked, 'named_in_robots': bot.lower() in named}
    base = _get(s, home, allow_redirects=True)
    headers = dict(base.headers) if base is not None else {}
    cdn = [n for n, hit in (('Cloudflare', 'cf-ray' in {k.lower() for k in headers}),
                            ('LiteSpeed', 'litespeed' in headers.get('Server', '').lower()),
                            ('QUIC.cloud', any(k.lower().startswith('x-qc-') for k in headers)),
                            ('SiteGround', 'sg-' in ' '.join(headers).lower())) if hit]
    base_code = base.status_code if base is not None else 0
    base_challenged = base is not None and bool(CHALLENGE.search(base.text[:50000]))

    def probe(bua):
        b = _get(_session(bua), home, allow_redirects=True)
        code = b.status_code if b is not None else 0
        challenged = b is not None and bool(CHALLENGE.search(b.text[:50000]) or b.headers.get('cf-mitigated'))
        size = len(b.content) if b is not None else 0
        return {'status': code, 'challenge_page': challenged and not base_challenged, 'bytes': size}

    firewall = {bot: probe(bua) for bot, bua in {**AI_SEARCH_BOTS, **AI_USER_AGENTS}.items()}
    base_size = len(base.content) if base is not None else 0

    def blocked(bot):
        f = firewall[bot]
        if base_code != 200:
            return False
        # a different answer from the browser's: error status, a vendor challenge, or a near-empty page
        return (f['status'] in (401, 403, 406, 429, 503) or f['challenge_page']
                or (f['status'] == 200 and base_size > 20000 and f['bytes'] < base_size * 0.2))
    judged = [b for b in AI_SEARCH_BOTS if b not in ('Googlebot', 'Bingbot')]
    blocked_robots = [b for b in AI_SEARCH_BOTS if not robots[b]['allowed']]
    blocked_firewall = [b for b in judged if blocked(b)]
    blocked_agents = [b for b in AI_USER_AGENTS if blocked(b)]
    rstatus = r.status_code if r is not None else 0
    if rstatus != 200 and not 400 <= rstatus < 500:
        # unreachable or 5xx: not a pass (Google treats a 5xx robots.txt as "disallow everything")
        blocked_robots = []
    return {'robots_txt_status': rstatus, 'robots_checked': rstatus == 200 or 400 <= rstatus < 500,
            'firewall_checked': base_code == 200, 'robots': robots,
            'browser_status': base_code, 'cdn': cdn, 'firewall': firewall,
            'search_bots_blocked_in_robots': blocked_robots,
            'search_bots_blocked_by_firewall_signal': blocked_firewall,
            'guest_agents_blocked_by_firewall_signal': blocked_agents, 'urls_tested': test_urls,
            'training_bots_blocked': [b for b in AI_TRAINING_BOTS if not robots[b]['allowed']]}


SNIPPET_BLOCK = re.compile(r'nosnippet|max-snippet\s*:\s*(0|[1-4]?\d)\b', re.I)


def snippet_blocks(pages):
    """Pages whose robots meta / X-Robots-Tag stop Google showing a snippet: that also keeps them out of
    AI Overviews and AI Mode (max-snippet under 50 characters counts as blocked)."""
    return [{'url': u, 'robots': (p.get('robots', '') + ' ' + p.get('x_robots_tag', '')).strip()}
            for u, p in pages.items()
            if SNIPPET_BLOCK.search(p.get('robots', '') + ' ' + p.get('x_robots_tag', ''))]


# ---------------------------------------------------------------- languages

LANG_CODE = re.compile(r'^(x-default|[a-z]{2,3}(-[a-z]{4})?(-([a-z]{2}|\d{3}))?)$', re.I)   # case doesn't matter
# Common wrong codes: a country used as a language, or a non-ISO region
WRONG_LANG = {'jp': 'ja', 'cn': 'zh', 'gr': 'el', 'dk': 'da', 'se': 'sv', 'kr': 'ko', 'cz': 'cs', 'ua': 'uk',
              'il': 'he', 'ir': 'fa', 'in': 'hi'}
WRONG_REGION = {'uk': 'gb', 'eu': None, 'uae': 'ae', 'ksa': 'sa'}


def _hreflang_code_ok(code):
    if not LANG_CODE.match(code):
        return False
    parts = code.lower().split('-')
    return parts[0] not in WRONG_LANG and not (len(parts) > 1 and parts[-1] in WRONG_REGION)
ARABIC = re.compile(r'[؀-ۿ]')


def hreflang_report(pages, data):
    """hreflang as Google uses it: every alternate points back (else that pair is ignored), targets answer
    200, are indexable and canonical, codes are valid (en-GB, not en-uk), and Arabic pages really are
    Arabic in their title / meta / H1 (Rank Math fields are often left in English on Polylang /ar/ pages)."""
    from .librecrawl import page_status
    status = {u['url'].rstrip('/'): page_status(u) for u in data.get('urls', [])}
    norm = {u.rstrip('/'): p for u, p in pages.items()}
    with_tags = {u: p for u, p in pages.items() if p.get('hreflang')}
    out = {'pages_with_hreflang': len(with_tags), 'no_return_link': [], 'bad_targets': [], 'invalid_codes': [],
           'no_self_reference': [], 'x_default_missing': 0, 'arabic_pages_not_arabic': [], 'lang_mismatch': []}
    for u, p in with_tags.items():
        alts = p['hreflang']
        for code in alts:
            if not _hreflang_code_ok(code):
                out['invalid_codes'].append({'url': u, 'code': code})
        if u.rstrip('/') not in {v.rstrip('/') for v in alts.values()}:
            out['no_self_reference'].append(u)
        if 'x-default' not in alts:
            out['x_default_missing'] += 1
        for code, target in alts.items():
            t = target.rstrip('/')
            if t == u.rstrip('/'):
                continue
            tp = norm.get(t)
            if tp is None:
                st = status.get(t)
                if st and st != 200:
                    out['bad_targets'].append({'url': u, 'code': code, 'target': target, 'problem': f'returns {st}'})
                continue
            if 'noindex' in (tp.get('robots', '') + ' ' + tp.get('x_robots_tag', '')).lower():
                out['bad_targets'].append({'url': u, 'code': code, 'target': target, 'problem': 'noindex'})
            elif tp.get('canonical') and tp['canonical'].rstrip('/') != t:
                out['bad_targets'].append({'url': u, 'code': code, 'target': target,
                                           'problem': f"canonical points to {tp['canonical']}"})
            elif tp.get('hreflang') and u.rstrip('/') not in {v.rstrip('/') for v in tp['hreflang'].values()}:
                out['no_return_link'].append({'url': u, 'code': code, 'target': target})
    for u, p in pages.items():
        lang = (p.get('html_lang') or '').lower()
        visible = ' '.join([p.get('title', ''), p.get('meta_description', '')] + p.get('h1', []))
        if lang.startswith('ar') and visible.strip() and not ARABIC.search(visible):
            out['arabic_pages_not_arabic'].append({'url': u, 'title': p.get('title', '')})
        elif lang and not lang.startswith('ar') and ARABIC.search(p.get('title', '')) and '/ar' not in u \
                and len(ARABIC.findall(p.get('title', ''))) > len(p.get('title', '')) / 2:
            out['lang_mismatch'].append({'url': u, 'html_lang': lang, 'title': p.get('title', '')})
    for k in ('no_return_link', 'bad_targets', 'invalid_codes', 'no_self_reference', 'arabic_pages_not_arabic',
              'lang_mismatch'):
        out[k] = out[k][:200]
    return out


def expired_offer_schema(pages, today=None):
    """Offer markup whose validThrough / priceValidUntil is already past: an expired offer still in schema."""
    today = (today or date.today()).isoformat()
    return [{'url': u, 'dates': [d for d in p.get('offer_valid_through', []) if d < today]}
            for u, p in pages.items() if any(d < today for d in p.get('offer_valid_through', []))]


def meta_template_report(pages):
    """Meta descriptions built from a template: identical to the title, starting with the whole title, or
    the same text with only the page name changed (a Rank Math pattern applied site-wide)."""
    same, starts, skeletons = [], [], defaultdict(list)
    for u, p in pages.items():
        t, m = (p.get('title') or '').strip(), (p.get('meta_description') or '').strip()
        if not m or not t:
            continue
        if m.lower() == t.lower():
            same.append(u)
        elif len(t) > 15 and m.lower().startswith(t.lower()):
            starts.append(u)
        name = (p.get('h1') or [''])[0] or t.split('|')[0]
        sk = m.replace(name.strip(), '{name}') if name.strip() and name.strip() in m else ''
        if sk and '{name}' in sk:
            skeletons[sk].append(u)
    tmpl = [{'pattern': k, 'pages': len(v), 'examples': v[:5]} for k, v in skeletons.items() if len(v) >= 3]
    return {'meta_equals_title': same, 'meta_starts_with_title': starts,
            'templated': sorted(tmpl, key=lambda x: -x['pages'])[:10]}


# ---------------------------------------------------------------- links

def _live_status(url):
    """Live status of a link target fetched like a browser, or None if it can't be reached at all."""
    h = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
                       'Chrome/140.0.0.0 Safari/537.36'}
    try:
        r = requests.get(url, headers=h, timeout=20, allow_redirects=True, stream=True)
        r.close()
        return r.status_code
    except requests.RequestException:
        return None


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
    # Re-test before reporting: status 0 (timeout), 403 and 429 at crawl time are often the crawler being
    # blocked or slowed, not a broken link (Rose, Nov 2026: a sitewide sister-domain link with status 0 reached a
    # plan as a Critical "broken link"; it loads fine). Only what still fails live is a finding.
    false_alarms = []
    for g in list(b):
        if g.get('status') in (0, 403, 429, 503):
            live = _live_status(g['target'])
            if live and live < 400:
                b.remove(g)
                false_alarms.append(dict(g, live_status=live))
    pairs = {}
    for g in r:
        if g.get('final') and g['final'].rstrip('/') != g['target'].rstrip('/'):
            pairs[g['target']] = (g['final'], g['pages_linking'])
    with open(out_dir / 'replace_pairs.csv', 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['search', 'replace', 'pages_linking'])
        for src, (dst, n) in sorted(pairs.items(), key=lambda kv: -kv[1][1]):
            w.writerow([src, dst, n])
    return {'broken_targets': b, 'redirected_targets': r, 'false_alarms': false_alarms,
            'counts': {'false_alarms_retested_ok': len(false_alarms),'broken_internal_targets': sum(1 for x in b if x.get('internal')),
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
    rows = [{'number': '+' + n, 'pages': len(where[n]), 'in_tel_links': tel[n], 'urls': sorted(where[n])}
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
            out.append({'landmark': lm, 'values': {v: sorted(us) for v, us in vals.items()}})
    return out


def price_mentions(texts, pages):
    out = []
    for u, t in texts.items():
        hits = sorted({m.group(0).strip() for m in PRICE.finditer(t)})
        if hits:
            out.append({'url': u, 'page_type': pages.get(u, {}).get('type', ''), 'prices': hits})
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
        warning = (f'schema names several cities {dict(loc)}: pass hotel_city (on a group site each hotel\'s city '
                   'is in site.json)')
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
