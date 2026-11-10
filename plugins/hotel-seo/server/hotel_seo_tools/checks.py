"""Re-check: run the machine-checkable `checks` stored on each list section against the live site.

Every section of a Priority / Secondary / Web Team list can carry checks, written when the list is
generated (see lists.schema.json). /hotel-seo recheck runs them all and marks each section
Done (every automatic check passes), Partly (some pass), Open (none pass) or Manual (only checks
that need a person). Re-checks of the same list are numbered (round 1, 2, ...), counted from the
earlier recheck-*/ folders next to out_dir. It then writes, e.g. for the second Priority re-check:

  priority-recheck-2-results.json         every check with expected vs actual
  priority-recheck-2.json                 a Re-check list (status table + a lettered section per unfinished item)
  priority-open-items-after-recheck-2.json  the original list re-issued with only the unfinished items

Pages are fetched fresh (Cache-Control: no-cache) as raw HTML.
"""
import copy
import json
import re
import string
import time
import unicodedata
from datetime import date
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from . import paths
from .librecrawl import UA, is_page

AUTO = {'title', 'meta', 'h1', 'h1_count', 'redirect', 'status', 'canonical', 'noindex', 'text_absent',
        'text_present', 'alt', 'schema_count', 'link_absent', 'link_present', 'schema_block_equals'}


def _clean(s):
    """Text for comparison only. Invisible format characters (zero-width space, soft hyphen, BOM, word
    joiner, bidi marks, tag characters: Unicode category Cf) are dropped, so a pasted title that looks right
    passes and an old phone number with a hidden character in it is still found. Never used to rewrite
    copy: on Arabic pages bidi marks are meaningful."""
    s = re.sub(r'`', '', str(s or ''))
    s = ''.join(ch for ch in s if unicodedata.category(ch) != 'Cf')
    s = s.replace(' ', ' ').replace(' ', ' ')
    return re.sub(r'\s+', ' ', s).strip().lower()


def _jsonld_nodes(soup):
    out = []
    for tag in soup.find_all('script', type='application/ld+json'):
        try:
            data = json.loads(tag.string or tag.get_text() or '')
        except (ValueError, TypeError):
            continue
        nodes = data.get('@graph', [data]) if isinstance(data, dict) else data if isinstance(data, list) else []
        out.extend(n for n in nodes if isinstance(n, dict))
    return out


def _haystack(soup, scope):
    """Where a text check looks. 'visible' = the page text a guest sees; 'schema' = the JSON-LD only
    (a schema-only item must not fail on a visible testimonial widget, and a schema phone is not in
    the visible text); 'html' = the raw HTML."""
    if scope == 'schema':
        return ' '.join(json.dumps(n, ensure_ascii=False) for n in _jsonld_nodes(soup))
    if scope == 'html':
        return str(soup)
    return soup.get_text(' ')


def _bad_href(href):
    """A link that looks right but won't work: whitespace or %20 in it (a pasted "/search/? idtokenprovider=…"
    stops the engine resolving the hotel)."""
    h = href or ''
    if re.search(r'\s', h.strip()) or (h != h.strip()):
        return 'whitespace in the address'
    if '%20' in h.split('#')[0]:
        return '%20 (an encoded space) in the address'
    return ''


def _norm_value(v):
    if isinstance(v, dict):
        return {k: _norm_value(x) for k, x in v.items() if k != '@context'}
    if isinstance(v, list):
        return [_norm_value(x) for x in v]
    return re.sub(r'\s+', ' ', str(v)).strip() if isinstance(v, str) else v


def _block_diff(live, expected):
    live, expected = _norm_value(live), _norm_value(expected)
    missing = sorted(k for k in expected if k not in live)
    extra = sorted(k for k in live if k not in expected)
    differ = sorted(k for k in expected if k in live and live[k] != expected[k])
    return missing, extra, differ


class Fetcher:
    def __init__(self, site, delay=0.3):
        self.site = site.rstrip('/') + '/'
        self.s = requests.Session()
        self.s.headers.update({'User-Agent': UA, 'Cache-Control': 'no-cache', 'Pragma': 'no-cache'})
        self.cache = {}
        self.delay = delay

    def url(self, u):
        return urljoin(self.site, u)

    def get(self, u):
        u = self.url(u)
        if u not in self.cache:
            try:
                r = self.s.get(u, timeout=25, allow_redirects=True)
                soup = BeautifulSoup(r.text, 'html.parser') if 'html' in r.headers.get('content-type', '') else None
                self.cache[u] = (r, soup)
            except requests.RequestException as e:
                self.cache[u] = (e, None)
            time.sleep(self.delay)
        return self.cache[u]


def _jsonld_type_count(soup, wanted):
    n = 0
    for tag in soup.find_all('script', type='application/ld+json'):
        try:
            data = json.loads(tag.string or '')
        except (ValueError, TypeError):
            continue
        nodes = data.get('@graph', [data]) if isinstance(data, dict) else data if isinstance(data, list) else []
        for node in nodes:
            if isinstance(node, dict):
                t = node.get('@type')
                if wanted in (t if isinstance(t, list) else [t]):
                    n += 1
    return n


def run_check(c, f, sitewide_urls):
    t = c.get('type')
    if t not in AUTO:
        return {'result': 'manual', 'actual': 'check by hand'}
    if t == 'redirect':
        try:
            r = f.s.get(f.url(c['source']), timeout=25, allow_redirects=True)
        except requests.RequestException as e:
            return {'result': 'fail', 'actual': f'error: {e}'}
        first = r.history[0].status_code if r.history else r.status_code
        ok = first == 301 and r.status_code == 200 and r.url.rstrip('/') == f.url(c['expected']).rstrip('/')
        return {'result': 'pass' if ok else 'fail',
                'actual': f'{first} → {r.url} ({r.status_code}), {len(r.history)} hop(s)'}

    targets = sitewide_urls if c.get('url') == 'sitewide' else [c.get('url', '/')]
    targets = list(dict.fromkeys(f.url(u).split('#')[0] for u in targets))   # one entry per page
    if t in ('text_absent', 'link_absent'):
        hits = []
        for u in targets:
            r, soup = f.get(u)
            if soup is None:
                continue
            if t == 'text_absent':
                scope = c.get('scope') or ('visible' if c.get('visible_only', True) else 'html')
                if _clean(c['text']) in _clean(_haystack(soup, scope)):
                    hits.append(f.url(u))
            else:
                if any(c['href'] in (a.get('href') or '') for a in soup.find_all('a')):
                    hits.append(f.url(u))
        return {'result': 'pass' if not hits else 'fail',
                'actual': f'still on {len(hits)} page(s): ' + ', '.join(hits[:5]) if hits else 'gone'}

    r, soup = f.get(c.get('url', '/'))
    if isinstance(r, Exception):
        return {'result': 'fail', 'actual': f'error: {r}'}
    if t == 'status':
        return {'result': 'pass' if r.status_code == int(c['expected']) else 'fail', 'actual': str(r.status_code)}
    if soup is None:
        return {'result': 'fail', 'actual': f'not HTML (status {r.status_code})'}
    if t == 'title':
        actual = soup.title.get_text() if soup.title else ''
        return {'result': 'pass' if _clean(actual) == _clean(c['expected']) else 'fail', 'actual': actual.strip()}
    if t == 'meta':
        m = soup.find('meta', attrs={'name': re.compile('^description$', re.I)})
        actual = (m.get('content') or '') if m else ''
        return {'result': 'pass' if _clean(actual) == _clean(c['expected']) else 'fail', 'actual': actual.strip()}
    if t == 'h1':
        h1s = [re.sub(r'\s+', ' ', h.get_text(' ')).strip() for h in soup.find_all('h1')]
        ok = len(h1s) == 1 and _clean(h1s[0]) == _clean(c['expected'])
        return {'result': 'pass' if ok else 'fail', 'actual': ' | '.join(h1s) or '(no H1)'}
    if t == 'h1_count':
        n = len(soup.find_all('h1'))
        return {'result': 'pass' if n == int(c.get('expected', 1)) else 'fail', 'actual': f'{n} H1(s)'}
    if t == 'link_present':
        want = c['href'].strip()
        found = [a.get('href') or '' for a in soup.find_all('a')
                 if want in (a.get('href') or '') or want in re.sub(r'\s|%20', '', a.get('href') or '')]
        if not found:
            return {'result': 'fail', 'actual': 'no such link'}
        bad = [(h, _bad_href(h)) for h in found if _bad_href(h)]
        if bad:
            return {'result': 'fail', 'actual': f'linked, but the address is malformed ({bad[0][1]}): "{bad[0][0]}"'}
        if c.get('exact') and not any(f.url(h).rstrip('/') == f.url(want).rstrip('/') for h in found):
            return {'result': 'fail', 'actual': f'links to "{found[0]}", not exactly "{want}"'}
        return {'result': 'pass', 'actual': 'linked'}
    if t == 'schema_block_equals':
        # "Replace with this block": the live block must equal the paste block, not merely contain one
        # value of it (a paste merged into the old block kept six old fields and dropped sameAs).
        want = c['expected'] if isinstance(c['expected'], dict) else json.loads(c['expected'])
        wtype = c.get('schema_type') or want.get('@type')
        nodes = [n for n in _jsonld_nodes(soup)
                 if wtype in (n.get('@type') if isinstance(n.get('@type'), list) else [n.get('@type')])]
        if not nodes:
            return {'result': 'fail', 'actual': f'no {wtype} block on the page'}
        best = min((_block_diff(n, want) for n in nodes), key=lambda d: sum(map(len, d)))
        missing, extra, differ = best
        if not any(best) and len(nodes) == 1:
            return {'result': 'pass', 'actual': 'matches the paste block'}
        parts = ([f'{len(nodes)} {wtype} blocks (expected 1)'] if len(nodes) > 1 else []) + \
                ([f'missing {missing}'] if missing else []) + ([f'extra (old) fields {extra}'] if extra else []) + \
                ([f'different values {differ}'] if differ else [])
        return {'result': 'fail', 'actual': '; '.join(parts)}
    if t == 'canonical':
        link = soup.find('link', rel=lambda v: v and 'canonical' in v)
        actual = link.get('href', '') if link else ''
        ok = actual.rstrip('/') == f.url(c['expected']).rstrip('/')
        return {'result': 'pass' if ok else 'fail', 'actual': actual or '(none)'}
    if t == 'noindex':
        m = soup.find('meta', attrs={'name': re.compile('^robots$', re.I)})
        robots = ((m.get('content') or '') if m else '') + ' ' + r.headers.get('X-Robots-Tag', '')
        has = 'noindex' in robots.lower()
        return {'result': 'pass' if has == bool(c.get('expected', True)) else 'fail', 'actual': robots.strip() or '(index)'}
    if t == 'text_present':
        scope = c.get('scope', 'visible')
        hit = _clean(c['text']) in _clean(_haystack(soup, scope))
        return {'result': 'pass' if hit else 'fail', 'actual': ('found' if hit else 'not found') + f' ({scope})'}
    if t == 'alt':
        imgs = [i for i in soup.find_all('img') if c['image'] in (i.get('src') or '') + (i.get('data-src') or '')]
        if not imgs:
            return {'result': 'fail', 'actual': 'image not on the page'}
        alts = [i.get('alt') or '' for i in imgs]
        ok = all(_clean(a) == _clean(c['expected']) for a in alts)
        return {'result': 'pass' if ok else 'fail', 'actual': ' | '.join(sorted(set(alts))) or '(empty)'}
    if t == 'schema_count':
        n = _jsonld_type_count(soup, c['schema_type'])
        return {'result': 'pass' if n == int(c['expected']) else 'fail', 'actual': f'{n} {c["schema_type"]} node(s)'}
    return {'result': 'manual', 'actual': 'unknown check type'}


def describe(c):
    t = c.get('type')
    if t == 'redirect':
        return f"301 {c['source']} → {c['expected']}"
    if t in ('title', 'meta', 'h1', 'canonical'):
        return f"{t} on {c.get('url')}: {c.get('expected')}"
    if t == 'noindex':
        return f"{'noindex' if c.get('expected', True) else 'indexable'}: {c.get('url')}"
    if t == 'status':
        return f"{c.get('url')} returns {c.get('expected')}"
    if t == 'text_absent':
        return f"text gone ({c.get('url')}): \"{c.get('text')}\""
    if t == 'text_present':
        return f"text present on {c.get('url')}: \"{c.get('text')}\""
    if t == 'link_absent':
        return f"no link to {c.get('href')} ({c.get('url')})"
    if t == 'link_present':
        return f"{c.get('url')} links to {c.get('href')}"
    if t == 'h1_count':
        return f"{c.get('expected', 1)} H1 on {c.get('url')}"
    if t == 'alt':
        return f"alt for {c.get('image')} on {c.get('url')}: \"{c.get('expected')}\""
    if t == 'schema_count':
        return f"{c.get('expected')} × {c.get('schema_type')} on {c.get('url')}"
    if t == 'schema_block_equals':
        exp = c.get('expected')
        typ = c.get('schema_type') or (exp.get('@type') if isinstance(exp, dict) else '')
        return f"{typ} block on {c.get('url')} equals the paste block"
    return c.get('description', t or '')


PATH_RE = re.compile(r'\[→\s*([^\]\s]+)\s*\]|`(/[^`\s]*)`|(?<![\w/])(/[a-z0-9][\w\-./%?=&]*)|https?://[^\s`)\]|"\']+', re.I)
ASSET = re.compile(r'\.(?:jpe?g|png|webp|gif|svg|css|js|xml|pdf|ico)(?:\?|$)', re.I)


def _path_of(u, host):
    from urllib.parse import urlparse
    pu = urlparse(u if '://' in u else 'https://' + host + ('' if u.startswith('/') else '/') + u)
    if host and pu.netloc.replace('www.', '') not in (host, ''):
        return None
    p = pu.path or '/'
    return p if p.endswith('/') or '.' in p.rsplit('/', 1)[-1] else p + '/'


# Hotel-copy AI tells (references/content-writing.md section 4). Detection only: we never rewrite automatically.
AI_TELLS = re.compile(
    r'\bnestled\b|\bin the heart of\b|\bboasts?\b|\bvibrant\b|\boasis\b|\bhaven\b|\bunparalleled\b|\bseamless(?:ly)?\b|'
    r'\belevate[sd]?\b|\bunforgettable\b|\btapestry\b|\btestament\b|\bcurated\b|\bdelve\b|\bwhether you\'?re\b|'
    r'\bnot just\b[^.]{1,60}\bbut\b|\brather than (?:simply|merely|just)\b|\bthis matters\b|\b(?:serves|stands) as\b|'
    r'\bembark\b|\bindulge\b|\bluxurious retreat\b|\bperfect blend\b|\bsecond to none\b|\bleverag\w*|\benhanc\w*|'
    r'\bgame-changing\b|\binnovative\b|\bholistic\b|\brobust\b|\bunlock\w*', re.I)
# Stock openings (content-writing.md section 4): checked at the start of each paste block and paragraph
STOCK_OPENING = re.compile(r"^\s*(welcome to|discover|experience|looking for|have you ever|in today'?s|"
                           r"when it comes to|whether you'?re|are you (?:looking|planning))\b", re.I)
# Honesty gate (content-writing.md section 4): superlatives need a source; urgency must be real
SUPERLATIVE = re.compile(r"(?<![\w-])(?:the )?(?:best|largest|biggest|first|only|finest|leading|number one|no\. ?1)"
                         r"(?= (?:hotel|resort|apartments?|property|pool|beach|rooftop|spa|in|on|of|choice|place|"
                         r"value|rate|price))|#1\b|"
                         r"\baward[- ]winning\b|\bonly \d+ rooms? left\b|\bselling fast\b", re.I)
HIDDEN = re.compile('[​-‍⁠﻿­‪-‮⁦-⁩\U000e0000-\U000e007f]')
QUOTED_COLUMNS = re.compile(r'^(now|current|currently|old|was|before|live now|on the site)\b', re.I)
LIMITS = ((re.compile(r'title', re.I), 62, 'title'), (re.compile(r'meta', re.I), 155, 'meta description'))


def _plain(cell):
    return re.sub(r'\[CONFIRM[^\]]*\]|`|\*\*|\*', '', str(cell)).strip()


def lint_copy(doc):
    """Copy the agency will paste word for word: AI tells and stock openings, em dashes in paste blocks,
    titles over 62 and metas over 155 characters in copy tables, and invisible characters (zero-width,
    soft hyphen, BOM, bidi overrides, tag characters) that break titles and fail re-checks. Columns that
    quote the live site ("Now", "Current") are skipped. Bidi marks U+200E/U+200F are allowed: Arabic and
    mixed-direction text needs them."""
    out = []
    for s in doc.get('sections', []):
        name = f"{s.get('number', '')} {s.get('title', '')}".strip()
        texts = []
        for b in s.get('blocks', []):
            (kind, val), = b.items()
            if kind in ('paste', 'p'):
                texts.append(str(val))
                if kind == 'paste':
                    if STOCK_OPENING.search(str(val)):
                        out.append(f'{name}: stock opening "{str(val)[:50]}" (start with the answer or a fact)')
                    if '—' in str(val):
                        out.append(f'{name}: em dash in paste copy "{str(val)[:50]}" (use a colon, comma or full stop)')
            elif kind == 'table':
                cols = [str(c) for c in val.get('columns', [])]
                keep = [i for i, c in enumerate(cols) if not QUOTED_COLUMNS.search(c)] or list(range(len(cols)))
                for row in val.get('rows', []):
                    texts.append(' | '.join(str(row[i]) for i in keep if i < len(row)))
                    for i in keep:
                        if i >= len(row) or i >= len(cols):
                            continue
                        cell = _plain(row[i])
                        if not cell or cell.lower().startswith('keep'):
                            continue
                        for rx, limit, label in LIMITS:
                            if rx.search(cols[i]) and len(cell) > limit:
                                out.append(f'{name}: {label} is {len(cell)} characters (max {limit}): "{cell[:70]}"')
                                break
        for t in texts:
            for m in SUPERLATIVE.finditer(t):
                out.append(f'{name}: superlative "{m.group(0)}" needs a source on file, or cut it: '
                           f'"{t[max(0, m.start() - 30):m.end() + 30].strip()}"')
            for m in AI_TELLS.finditer(t):
                out.append(f'{name}: AI tell "{m.group(0)}" in "{t[max(0, m.start() - 30):m.end() + 30].strip()}"')
            h = HIDDEN.search(t)
            if h:
                out.append(f'{name}: invisible character U+{ord(h.group(0)):04X} in "{t[:60]}"')
    return out[:60]


def lint_checks(doc):
    """Checks that can't prove the section done (a recheck marked Done while one of the 12 blog posts its
    own text named still had the old link; 2 of 6 title changes and 2 of 14 link replacements checked):
      - a URL in a section's tables or code blocks with no check on it
      - a schema table row that says Delete / Remove with no schema_count / schema_block_equals check
      - a "Replace with this block" section with no schema_block_equals check
    Returns one line per gap; empty when every section can be proven."""
    from urllib.parse import urlparse
    host = urlparse(doc.get('site') or '').netloc.replace('www.', '')
    out = []
    for s in doc.get('sections', []):
        if s.get('hold'):
            continue
        name = f"{s.get('number', '')} {s.get('title', '')}".strip()
        checks = s.get('checks', [])
        covered = set()
        for c in checks:
            for k in ('url', 'source', 'expected', 'href', 'image'):
                v = c.get(k)
                if isinstance(v, str) and v and v != 'sitewide':
                    p = _path_of(v, host)
                    if p:
                        covered.add(p)
        named, delete_rows, replace_block = [], 0, False
        for b in s.get('blocks', []):
            (kind, val), = b.items()
            texts = []
            if kind == 'table':
                texts = [' | '.join(str(x) for x in row) for row in val.get('rows', [])]
                delete_rows += sum(1 for t in texts if re.search(r'\b(delete|remove)\b', t, re.I)
                                   and re.search(r'schema|json|"@type"|"\w+"\s*:', t + ' ' + str(val.get('columns')), re.I))
            elif kind == 'code':
                texts = [str(val)]
                if str(val).lstrip().startswith('{') and '@type' in str(val):
                    replace_block = replace_block or bool(re.search(r'replace', json.dumps(s.get('blocks'), ensure_ascii=False), re.I))
            for t in texts:
                for m in PATH_RE.finditer(t):
                    u = next(g for g in m.groups() if g) if any(m.groups()) else m.group(0)
                    if ASSET.search(u) or 'idtokenprovider' in u or u.startswith('/wp-json'):
                        continue
                    p = _path_of(u, host)
                    if p and p not in named:
                        named.append(p)
        missing = [p for p in named if p not in covered]
        if missing:
            out.append(f"{name}: no check for {len(missing)} of {len(named)} URLs it names: {', '.join(missing[:8])}")
        types = {c.get('type') for c in checks}
        if delete_rows and not types & {'schema_count', 'schema_block_equals'}:
            out.append(f"{name}: {delete_rows} schema line(s) to delete but no schema_count / schema_block_equals check")
        if replace_block and 'schema_block_equals' not in types:
            out.append(f"{name}: a block to paste as a replacement but no schema_block_equals check "
                       '(a merged paste passes a presence check)')
    return out


def list_coverage(doc, crawl_dir, list_dir=None):
    """Audit findings that reached no list: Priority-severity URLs and security items from findings.json
    against the text and checks of every list in the same folder with the same date (or the list
    alone). Omissions then become decisions instead of accidents (an indexable registration page,
    11 spam queries and a rooms archive with no H1 once reached no list)."""
    from urllib.parse import urlparse
    if not crawl_dir:
        return {'checked': False, 'reason': 'no crawl_dir'}
    fj = paths.resolve(crawl_dir) / 'findings.json'
    if not fj.exists():
        return {'checked': False, 'reason': 'no findings.json in crawl_dir (run audit_site)'}
    fnd = json.loads(fj.read_text(encoding='utf-8'))
    host = urlparse(fnd.get('site') or doc.get('site') or '').netloc.replace('www.', '')
    docs = [doc]
    if list_dir:
        for f in paths.resolve(list_dir).glob('*.json'):
            if re.search(r'-(presend|results)\.json$|recheck', f.name):
                continue
            try:
                d = json.loads(f.read_text(encoding='utf-8'))
            except (ValueError, OSError):
                continue
            if isinstance(d, dict) and d.get('date') == doc.get('date') and d.get('title') != doc.get('title'):
                docs.append(d)
    blob = ' '.join(json.dumps(d, ensure_ascii=False) for d in docs)
    on_lists = {_path_of(m.group(0) if not any(m.groups()) else next(g for g in m.groups() if g), host)
                for m in PATH_RE.finditer(blob)}
    pri = {}
    for i in fnd.get('issues', []):
        if i.get('severity') == 'Priority':
            p = _path_of(i['url'], host)
            if p and p not in on_lists:
                pri.setdefault(p, set()).add(i['check'])
    sec = fnd.get('security', [])
    sec_listed = bool(re.search(r'security|suspicious|spam|malware', blob, re.I))
    return {'checked': True, 'lists_compared': [d.get('title') for d in docs],
            'priority_urls_on_no_list': [{'path': p, 'checks': sorted(c)} for p, c in sorted(pri.items())],
            'security_items_on_no_list': [] if sec_listed else sec}


def _run_all(doc, crawl_dir, progress):
    site = doc.get('site')
    if not site:
        raise ValueError('The list has no "site" (e.g. "https://hotel.com"); add it and run again.')
    sitewide = ['/']
    if crawl_dir:
        data = json.loads((paths.resolve(crawl_dir) / 'crawl.json').read_text(encoding='utf-8'))
        sitewide = [u['url'] for u in data['urls'] if is_page(u)]
    f = Fetcher(site)
    results = []
    for i, s in enumerate(doc['sections']):
        rows = [{'check': describe(c), **run_check(c, f, sitewide)} for c in s.get('checks', [])]
        auto = [r for r in rows if r['result'] != 'manual']
        passed = sum(r['result'] == 'pass' for r in auto)
        status = ('Manual' if not auto else 'Done' if passed == len(auto) else 'Partly' if passed else 'Open')
        results.append({'index': i, 'number': s.get('number', i + 1), 'title': s['title'], 'status': status,
                        'passed': passed, 'automatic': len(auto), 'checks': rows})
        if progress:
            progress(f"checked {i + 1}/{len(doc['sections'])} items")
    return results


def presend(list_json, crawl_dir='', progress=None):
    """Live diff before sending: run a draft list's checks against the live site now. Items whose
    checks all pass are already fixed (the agency may have done them since the crawl): they are
    dropped. Partly-fixed items stay, titled "(partly done)" with a note of what is already live.
    Writes <list>-presend.json next to the draft; render that one."""
    src = paths.resolve(list_json)
    doc = json.loads(src.read_text(encoding='utf-8'))
    results = _run_all(doc, crawl_dir, progress)
    out = copy.deepcopy(doc)
    out['sections'], dropped, partly = [], [], []
    for r in results:
        sec = copy.deepcopy(doc['sections'][r['index']])
        if r['status'] == 'Done' and not sec.get('hold'):
            dropped.append(f"{r['number']} {r['title']}")
            continue
        if r['status'] == 'Partly':
            live = [c['check'] for c in r['checks'] if c['result'] == 'pass']
            sec['title'] = f"{STATUS_SUFFIX.sub('', sec['title'])} (partly done)"
            sec.setdefault('blocks', []).insert(0, {'note': 'Already live: ' + '; '.join(live) + '. Only the rest below.'})
            partly.append(f"{r['number']} {r['title']}")
        out['sections'].append(sec)
    if out.get('summary') and dropped:
        gone = {d.split(' ', 1)[0] for d in dropped}
        out['summary']['rows'] = [row for row in doc['summary']['rows'] if str(row[0]) not in gone]
    dest = src.with_name(src.stem + '-presend.json')
    dest.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding='utf-8')
    lint = lint_checks(doc)
    coverage = list_coverage(doc, crawl_dir, src.parent)
    copy_lint = lint_copy(doc)
    return {'checks_missing': lint, 'not_on_any_list': coverage, 'copy_problems': copy_lint,
            'items': len(results), 'already_fixed_dropped': dropped, 'partly_done': partly,
            'no_automatic_checks': [f"{r['number']} {r['title']}" for r in results if r['status'] == 'Manual'],
            'file': str(dest),
            'next': ('Render this file instead of the draft.' if dropped or partly else
                     'Nothing is fixed yet: render the draft (or this identical copy).')
            + (' Items were dropped: re-letter the sections and check the summary and lead still read right.'
               if dropped else '')
            + (' checks_missing: add the missing checks to the draft (one per URL / row) and run again.'
               if lint else '')
            + (' copy_problems: rewrite those phrases plainly (playbook 4) and remove invisible characters.'
               if copy_lint else '')
            + (' not_on_any_list: put each on a list, or note in run-notes why it is left out.'
               if coverage.get('priority_urls_on_no_list') or coverage.get('security_items_on_no_list') else '')}


STATUS_SUFFIX = re.compile(r'(\s\((Done|Partly|Open|Manual|Waiting|partly done)\))+$')


def _slug(text):
    return re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')


def recheck_round(doc, out):
    """Which re-check of this list this is: 1 + the rounds already done (earlier recheck-*/ folders
    next to out_dir, and the round an open-items list was issued after)."""
    from .pdf import short_list
    base = doc.get('against') if doc.get('title') == 'Re-check' else doc.get('title')
    rounds, files = [int(doc.get('open_items_after') or 0)], 0
    for f in out.parent.glob('recheck-*/*.json'):
        if f.parent.resolve() == out.resolve():
            continue                     # re-running the same re-check keeps its number
        try:
            d = json.loads(f.read_text(encoding='utf-8'))
        except (ValueError, OSError):
            continue
        if not isinstance(d, dict) or d.get('title') != 'Re-check':
            continue
        if d.get('against') == base or (not d.get('against') and str(d.get('subtitle', '')).startswith(f'Against the {base} ')):
            files += 1
            rounds.append(int(d.get('recheck_round') or 0))
    return max(max(rounds), files) + 1, base, short_list(base)


DIFF_FIELDS = ('title', 'meta_description', 'h1', 'canonical', 'robots', 'jsonld_types')


def baseline_diff(doc, baseline_crawl_dir, crawl_dir):
    """What changed between the crawl the list was built from and the re-check crawl, per page, that no
    item on the list asked for (a duplicate H1 on two posts and a CTA added to three were found only
    this way). Both crawls need audit_site (findings.json)."""
    from urllib.parse import urlparse
    try:
        old = json.loads((paths.resolve(baseline_crawl_dir) / 'findings.json').read_text(encoding='utf-8'))['pages']
        new = json.loads((paths.resolve(crawl_dir) / 'findings.json').read_text(encoding='utf-8'))['pages']
    except (OSError, ValueError, KeyError) as e:
        return {'checked': False, 'reason': f'needs findings.json in both crawls (run audit_site): {e}'}
    host = urlparse(doc.get('site') or '').netloc.replace('www.', '')
    blob = json.dumps(doc.get('sections', []), ensure_ascii=False)
    on_list = {_path_of(m.group(0) if not any(m.groups()) else next(g for g in m.groups() if g), host)
               for m in PATH_RE.finditer(blob)}
    by_path_old = {_path_of(u, host): p for u, p in old.items()}
    by_path_new = {_path_of(u, host): p for u, p in new.items()}
    changed, unasked = [], []
    for path in sorted(set(by_path_old) & set(by_path_new)):
        a, b = by_path_old[path], by_path_new[path]
        diffs = []
        for k in DIFF_FIELDS:
            va, vb = a.get(k), b.get(k)
            if k == 'jsonld_types':
                va, vb = sorted(va or []), sorted(vb or [])
            if va != vb:
                diffs.append({'field': k, 'before': va, 'after': vb})
        if diffs:
            row = {'path': path, 'changes': diffs}
            changed.append(row)
            if path not in on_list:
                unasked.append(row)
    return {'checked': True, 'pages_compared': len(set(by_path_old) & set(by_path_new)),
            'pages_changed': len(changed),
            'gone_since_baseline': sorted(set(by_path_old) - set(by_path_new))[:30],
            'new_since_baseline': sorted(set(by_path_new) - set(by_path_old))[:30],
            'changes_not_on_any_item': unasked[:60]}


def recheck(list_json, out_dir, crawl_dir='', progress=None, baseline_crawl_dir=''):
    src = paths.resolve(list_json)
    doc = json.loads(src.read_text(encoding='utf-8'))
    site = doc.get('site')
    if not site:
        raise ValueError('The list has no "site" (e.g. "https://hotel.com"); add it and run again.')
    sitewide = ['/']
    if crawl_dir:
        data = json.loads((paths.resolve(crawl_dir) / 'crawl.json').read_text(encoding='utf-8'))
        sitewide = [u['url'] for u in data['urls'] if is_page(u)]
    f = Fetcher(site)

    results, today = [], date.today()
    for i, s in enumerate(doc['sections']):
        checks = s.get('checks', [])
        rows = []
        for c in checks:
            res = run_check(c, f, sitewide)
            rows.append({'check': describe(c), **res})
        auto = [r for r in rows if r['result'] != 'manual']
        passed = sum(r['result'] == 'pass' for r in auto)
        if not rows:
            status = 'Manual'
        elif not auto:
            status = 'Manual'
        elif passed == len(auto):
            status = 'Done'
        elif passed:
            status = 'Partly'
        else:
            status = 'Open'
        if s.get('hold') and status != 'Done':
            status = 'Waiting'           # waiting for the hotel: not the agency's to finish yet
        results.append({'index': i, 'number': s.get('number', i + 1), 'title': STATUS_SUFFIX.sub('', s['title']),
                        'status': status, 'passed': passed, 'automatic': len(auto), 'checks': rows})
        if progress:
            progress(f"checked {i + 1}/{len(doc['sections'])} items")

    out = paths.resolve(out_dir)
    first_date = doc.get('original_date') or doc['date']      # the date of the list as first sent
    out.mkdir(parents=True, exist_ok=True)
    n, base, short = recheck_round(doc, out)
    stem = f'{_slug(short)}-recheck-{n}'
    files = {'results': out / f'{stem}-results.json', 'recheck_list': out / f'{stem}.json',
             'open_items_list': out / f'{_slug(short)}-open-items-after-recheck-{n}.json'}
    files['results'].write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding='utf-8')

    # Re-check list: status table + one lettered section per unfinished item.
    letters = iter(string.ascii_uppercase)
    sections = []
    for r in results:
        if r['status'] in ('Done', 'Waiting'):
            continue
        failing = [c for c in r['checks'] if c['result'] != 'pass']
        sections.append({
            'number': next(letters, '*'), 'title': f"{r['title']} ({r['status']})",
            'blocks': [{'table': {'columns': ['Check', 'Now on the live site', 'Result'],
                                  'rows': [[c['check'], c['actual'], c['result'].upper()] for c in failing]}}],
        })
    done = sum(r['status'] == 'Done' for r in results)
    recheck_doc = {
        'hotel': doc['hotel'], 'short_name': doc.get('short_name', doc['hotel']), 'site': site,
        'title': 'Re-check', 'against': base, 'recheck_round': n, 'file_number': 'auto', 'date': today.strftime('%d %b').lstrip('0'),
        'subtitle': f"Re-check {n} against the {base} of {first_date} · {done} of {len(results)} items done",
        'summary': {'columns': ['#', 'Item', 'Status', 'Note'],
                    'rows': [[r['number'], r['title'], r['status'],
                              f"{r['passed']}/{r['automatic']} checks pass" if r['automatic'] else 'check by hand']
                             for r in results]},
        'intro': ['Thank you. Everything marked Done is confirmed on the live site. The lettered sections '
                  'below list exactly what is still missing on each open item.'],
        'sections': sections,
        'footer': '**When done:** LiteSpeed → Purge All → send MetaHotels the change list. We will re-check again.',
    }
    files['recheck_list'].write_text(json.dumps(recheck_doc, indent=1, ensure_ascii=False), encoding='utf-8')

    # The original list with only unfinished items, status in each title.
    open_doc = copy.deepcopy(doc)
    open_doc['sections'] = []
    for r in results:
        if r['status'] == 'Done':
            continue
        sec = copy.deepcopy(doc['sections'][r['index']])
        sec['title'] = f"{r['title']} ({r['status']})"
        open_doc['sections'].append(sec)
    if open_doc.get('summary'):
        keep = {str(r['number']) for r in results if r['status'] != 'Done'}
        open_doc['summary']['rows'] = [row for row in doc['summary']['rows'] if str(row[0]) in keep]
    open_doc['date'] = recheck_doc['date']
    open_doc['open_items_after'] = n
    open_doc['original_date'] = first_date
    open_doc['file_number'] = 'auto'     # a new file: next running number when rendered
    open_doc['subtitle'] = (f"Still open after re-check {n} of the {base} of {first_date} · "
                            f"{len(open_doc['sections'])} items")
    files['open_items_list'].write_text(json.dumps(open_doc, indent=1, ensure_ascii=False), encoding='utf-8')

    # Pages the agency changed and the re-check confirmed: one Search Console inspect link each. Google's API
    # can't request indexing, so it's a click per URL (handoff, Nov 2026: this list was being built by hand).
    from urllib.parse import quote, urlparse as _up
    changed = []
    for r in results:
        if r['status'] != 'Done':
            continue
        for c in doc['sections'][r['index']].get('checks', []):
            u = c.get('url') or c.get('source')
            if u and u != 'sitewide' and c.get('type') != 'manual':
                full = urljoin(site.rstrip('/') + '/', u)
                if full not in changed:
                    changed.append(full)
    if changed:
        prop = 'sc-domain:' + _up(site).netloc.replace('www.', '')
        lines = [f'# Request indexing: {doc["hotel"]} · re-check {n} · {today.isoformat()}', '',
                 f'{len(changed)} pages changed and confirmed live. Open each link (signed in to Search Console), '
                 'then **Request indexing**. Once per page is enough; asking again doesn\'t speed it up. If the '
                 f'property isn\'t `{prop}`, change resource_id in the links.', '']
        lines += [f'- [ ] {u}  \n  https://search.google.com/search-console/inspect?resource_id={quote(prop, safe="")}'
                  f'&id={quote(u, safe="")}' for u in changed]
        files['indexing_requests'] = out / f'{stem}-indexing-requests.md'
        files['indexing_requests'].write_text('\n'.join(lines) + '\n', encoding='utf-8')

    diff = (baseline_diff(doc, baseline_crawl_dir, crawl_dir) if baseline_crawl_dir and crawl_dir else
            {'checked': False, 'reason': 'give baseline_crawl_dir (the crawl the list was built from) and crawl_dir'})
    if diff.get('checked'):
        files['baseline_diff'] = out / f'{stem}-baseline-diff.json'
        files['baseline_diff'].write_text(json.dumps(diff, indent=1, ensure_ascii=False), encoding='utf-8')
    return {'items': len(results), 'done': done,
            'checks_missing': lint_checks(doc),
            'changes_not_on_any_item': {k: v for k, v in diff.items() if k != 'changes_not_on_any_item'}
            | {'count': len(diff.get('changes_not_on_any_item', [])),
               'first': diff.get('changes_not_on_any_item', [])[:8]},
            'partly': sum(r['status'] == 'Partly' for r in results),
            'open': sum(r['status'] == 'Open' for r in results),
            'manual': sum(r['status'] == 'Manual' for r in results),
            'waiting': sum(r['status'] == 'Waiting' for r in results),
            'by_item': [{k: r[k] for k in ('number', 'title', 'status', 'passed', 'automatic')} for r in results],
            'recheck_round': n,
            'files': {k: str(v) for k, v in files.items()}}
