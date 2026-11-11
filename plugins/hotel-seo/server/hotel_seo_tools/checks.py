"""Re-check: run the machine-checkable `checks` stored on each finding against the live site.

Every finding of an Audit Report / Web Team List carries checks, written by the agents and the report builder
(see templates/report.schema.json). /hotel-seo recheck runs them all and marks each section
Done (every automatic check passes), Partly (some pass), Open (none pass) or Manual (only checks
that need a person). Re-checks of the same list are numbered (round 1, 2, ...), counted from the
earlier recheck-*/ folders next to out_dir. It then writes, e.g. for the second re-check of an Audit Report:

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
from datetime import date
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from . import paths
from .librecrawl import UA, is_page

AUTO = {'title', 'meta', 'h1', 'h1_count', 'redirect', 'status', 'canonical', 'noindex', 'text_absent',
        'text_present', 'alt', 'schema_count', 'link_absent', 'link_present', 'title_present', 'meta_present',
        'title_max', 'meta_max', 'canonical_self', 'jsonld_valid', 'alt_present'}


def _clean(s):
    s = re.sub(r'`', '', str(s or ''))
    return re.sub(r'\s+', ' ', s).strip().lower()


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
                hay = soup.get_text(' ') if c.get('visible_only', True) else str(soup)
                if _clean(c['text']) in _clean(hay):
                    hits.append(f.url(u))
            else:
                if any(c['href'] in (a.get('href') or '') for a in soup.find_all('a')):
                    hits.append(f.url(u))
        return {'result': 'pass' if not hits else 'fail',
                'actual': f'still on {len(hits)} page(s): ' + ', '.join(hits) if hits else 'gone'}

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
        ok = any(c['href'] in (a.get('href') or '') for a in soup.find_all('a'))
        return {'result': 'pass' if ok else 'fail', 'actual': 'linked' if ok else 'no such link'}
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
        return {'result': 'pass' if _clean(c['text']) in _clean(soup.get_text(' ')) else 'fail',
                'actual': 'found' if _clean(c['text']) in _clean(soup.get_text(' ')) else 'not found'}
    if t == 'alt':
        imgs = [i for i in soup.find_all('img') if c['image'] in (i.get('src') or '') + (i.get('data-src') or '')]
        if not imgs:
            return {'result': 'fail', 'actual': 'image not on the page'}
        alts = [i.get('alt') or '' for i in imgs]
        ok = all(_clean(a) == _clean(c['expected']) for a in alts)
        return {'result': 'pass' if ok else 'fail', 'actual': ' | '.join(sorted(set(alts))) or '(empty)'}
    if t in ('title_present', 'title_max'):
        actual = re.sub(r'\s+', ' ', soup.title.get_text()).strip() if soup.title else ''
        ok = bool(actual) if t == 'title_present' else (bool(actual) and len(actual) <= int(c.get('expected', 62)))
        return {'result': 'pass' if ok else 'fail', 'actual': f'{len(actual)} chars: {actual[:90]}' if actual else '(no title)'}
    if t in ('meta_present', 'meta_max'):
        m = soup.find('meta', attrs={'name': re.compile('^description$', re.I)})
        actual = ((m.get('content') or '') if m else '').strip()
        ok = bool(actual) if t == 'meta_present' else (bool(actual) and len(actual) <= int(c.get('expected', 155)))
        return {'result': 'pass' if ok else 'fail', 'actual': f'{len(actual)} chars' if actual else '(no meta description)'}
    if t == 'canonical_self':
        link = soup.find('link', rel=lambda v: v and 'canonical' in v)
        actual = link.get('href', '') if link else ''
        ok = actual.rstrip('/') == f.url(c.get('url', '/')).rstrip('/')
        return {'result': 'pass' if ok else 'fail', 'actual': actual or '(none)'}
    if t == 'alt_present':
        imgs = [i for i in soup.find_all('img') if c['image'] in (i.get('src') or '') + (i.get('data-src') or '')]
        if not imgs:
            return {'result': 'pass', 'actual': 'image no longer on the page'}
        alts = [(i.get('alt') or '').strip() for i in imgs]
        return {'result': 'pass' if all(alts) else 'fail', 'actual': ' | '.join(sorted(set(alts))) or '(empty)'}
    if t == 'jsonld_valid':
        bad = 0
        for tag in soup.find_all('script', type='application/ld+json'):
            try:
                json.loads(tag.string or tag.get_text() or '')
            except (ValueError, TypeError):
                bad += 1
        return {'result': 'pass' if not bad else 'fail', 'actual': f'{bad} invalid JSON-LD block(s)'}
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
    if t == 'title_present':
        return f"title present on {c.get('url')}"
    if t == 'meta_present':
        return f"meta description present on {c.get('url')}"
    if t == 'title_max':
        return f"title on {c.get('url')} at most {c.get('expected', 62)} chars"
    if t == 'meta_max':
        return f"meta description on {c.get('url')} at most {c.get('expected', 155)} chars"
    if t == 'canonical_self':
        return f"{c.get('url')} canonical to itself"
    if t == 'jsonld_valid':
        return f"every JSON-LD block on {c.get('url')} parses"
    if t == 'alt_present':
        return f"{c.get('image')} on {c.get('url')} has alt text"
    return c.get('description', t or '')


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
        if s.get('chapter') or s.get('generated'):
            continue                     # chapter headings and generated score sections are not findings
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
    return {'items': len(results), 'already_fixed_dropped': dropped, 'partly_done': partly,
            'no_automatic_checks': [f"{r['number']} {r['title']}" for r in results if r['status'] == 'Manual'],
            'file': str(dest),
            'next': ('Render this file instead of the draft.' if dropped or partly else
                     'Nothing is fixed yet: render the draft (or this identical copy).')
            + (' Items were dropped: re-letter the sections and check the summary and lead still read right.'
               if dropped else '')}


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


def recheck(list_json, out_dir, crawl_dir='', progress=None):
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
        if s.get('chapter') or s.get('generated'):
            continue                     # chapter headings and generated score sections are not findings
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

    return {'items': len(results), 'done': done,
            'partly': sum(r['status'] == 'Partly' for r in results),
            'open': sum(r['status'] == 'Open' for r in results),
            'manual': sum(r['status'] == 'Manual' for r in results),
            'waiting': sum(r['status'] == 'Waiting' for r in results),
            'by_item': [{k: r[k] for k in ('number', 'title', 'status', 'passed', 'automatic')} for r in results],
            'recheck_round': n,
            'files': {k: str(v) for k, v in files.items()}}
