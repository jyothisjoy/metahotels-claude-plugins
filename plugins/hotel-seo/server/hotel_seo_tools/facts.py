"""[CONFIRM] guard: every hotel fact in a list must be backed by evidence or marked [CONFIRM].

Two kinds of fact (playbook ground rules 5 and 6):
  site-checkable   sizes, star rating, beds, floors, restaurants, pools...: OK if the live site says it
  hotel-confirmed  room service / 24-hour, loyalty tiers and benefits, room count, occupancy, distances
                   and travel times, check-in/out times, prices, discounts: OK only if it is in
                   hotel-facts.json, because hotel sites contradict themselves on exactly these

A phrase also counts as marked when another item in the same section mentions it together with
[CONFIRM] (schema in a code block can't carry the tag itself).

"Why" lines, the summary table, the subtitle, the lead box and the "already working" table are
skipped: they carry our own data (impressions, revenue, what the booking engine shows), not hotel facts.
"[CONFIRM with hotel which]" counts as [CONFIRM].

Evidence:
  <crawl>/site_text.json        visible text of every page (written by audit_site)
  <domain>/hotel-facts.json     {"facts": [{"fact": "Check-in 15:00", "source": "hotel contact, 15 Oct 2026"}]}
"""
import json
import re
from collections import defaultdict

from . import paths

NUM = r'\d[\d,.]*'
FACT_PATTERNS = {
    'size': rf'{NUM}\s*(?:m²|m2|sqm|sq\.?\s?m|square met(?:er|re)s?)',
    'distance_time': rf'{NUM}\s*(?:km|kilomet(?:er|re)s?|miles?|minutes?|mins?|hours?|hrs?)\b',
    # up to two words between the number and the noun: "3 loyalty tiers", "13 luxury suites"
    'count_confirm': rf'{NUM}\s+(?:[a-z-]+\s+){{0,2}}?(?:rooms?|suites?|keys|guests?|people|persons|adults|'
                     rf'children|tiers?|levels?)\b',
    'count_site': rf'{NUM}\s+(?:[a-z-]+\s+){{0,2}}?(?:floors?|beds?|bedrooms?|restaurants?|pools?|seats?|'
                  rf'apartments?)\b',
    'round_the_clock': r'\b24[- ]?hours?\b|\bround[- ]the[- ]clock\b|\b24/7\b',
    'price': rf'(?:AED|USD|EUR|\$|€)\s?{NUM}|{NUM}\s?(?:AED|USD|EUR|dirhams?)\b',
    'percent': rf'{NUM}\s?%',
    'time': r'\b\d{1,2}:\d{2}\b',
    'stars': rf'\b{NUM}[- ]?stars?\b',
}
HOTEL_CONFIRMED = {'distance_time', 'count_confirm', 'round_the_clock', 'price', 'percent', 'time'}
MARK = re.compile(r'\[CONFIRM[^\]]*\]')
FACT_RE = re.compile('|'.join(f'(?P<{k}>{v})' for k, v in FACT_PATTERNS.items()), re.I)


def norm(s):
    s = (s or '').lower().replace('²', '2').replace('–', '-').replace('—', '-')
    s = re.sub(r'(\d),(\d{3})', r'\1\2', s)
    s = re.sub(r'\s*(?:sq\.?\s?m|sqm|square met(?:er|re)s?|m 2)\b', ' m2', s)
    s = re.sub(r'(\d)\s*([a-z%])', r'\1 \2', s)          # "830m2" == "830 m2"
    s = re.sub(r'\bhrs?\b', 'hour', s)
    s = re.sub(r'\bhours\b', 'hour', s)
    s = re.sub(r'\bmins?\b|\bminutes\b', 'minute', s)
    s = re.sub(r'24\s*-?\s*hour', '24 hour', s)
    s = re.sub(r'\s+', ' ', s)
    return s.strip()


def _time_variants(t):
    h, m = (int(x) for x in t.split(':'))
    h12 = h % 12 or 12
    suffix = 'pm' if h >= 12 else 'am'
    mm = '' if m == 0 else f':{m:02d}'
    return [f'{h:02d}:{m:02d}', f'{h}:{m:02d}', f'{h12}{mm} {suffix}', f'{h12}{mm}{suffix}',
            f'{h12}{mm} {suffix[0]}.m', f'{h12}:{m:02d} {suffix}']


def _verified(phrase, corpus):
    if not corpus:
        return False
    p = norm(phrase)
    if p in corpus:
        return True
    if re.fullmatch(r'\d{1,2}:\d{2}', p):
        return any(v in corpus for v in _time_variants(p))
    nums = re.findall(r'\d+(?:\.\d+)?', p)
    unit = re.sub(r'[\d.,%$€\s-]+', ' ', p).strip().split(' ')[0] if re.search(r'[a-z]', p) else ''
    if nums and unit:
        stem = re.escape(unit[:4])
        return all(re.search(rf'\b{re.escape(n)}\b.{{0,25}}{stem}|{stem}.{{0,25}}\b{re.escape(n)}\b', corpus)
                   for n in nums)
    return False


def _items(doc):
    for w in doc.get('warnings_top', []) + doc.get('warnings_end', []):
        yield 'warning', w
    for p in doc.get('intro', []):
        yield 'intro', p
    for s in doc.get('sections', []):
        where = f"{s.get('number', '')} {s.get('title', '')}".strip()
        for b in s.get('blocks', []):
            (kind, val), = b.items()
            if kind in ('p', 'code', 'warning', 'note', 'paste', 'h3'):
                yield where, val
            elif kind in ('ol', 'ul'):
                for li in val:
                    yield where, li
            elif kind == 'table':
                for row in val.get('rows', []):
                    joined = ' | '.join(str(c) for c in row)
                    for c in row:
                        yield where, f'{c}' + (' [CONFIRM]' if MARK.search(joined) else '')


def load_corpus(crawl_dir='', facts_file=''):
    site, confirmed, sources = [], [], []
    if crawl_dir:
        f = paths.resolve(crawl_dir) / 'site_text.json'
        if f.exists():
            site.extend(json.loads(f.read_text(encoding='utf-8')).values())
            sources.append(str(f))
    if facts_file and paths.resolve(facts_file).exists():
        facts = json.loads(paths.resolve(facts_file).read_text(encoding='utf-8')).get('facts', [])
        confirmed.extend(x.get('fact', '') for x in facts)
        sources.append(str(paths.resolve(facts_file)))
    confirmed_text = norm(' \n '.join(confirmed))
    return norm(' \n '.join(site)) + ' \n ' + confirmed_text, confirmed_text, sources


def check(doc, crawl_dir='', facts_file=''):
    corpus, confirmed, sources = load_corpus(crawl_dir, facts_file)
    if not sources:
        return {'checked': False, 'reason': 'no site_text.json (run audit_site) and no hotel-facts.json'}
    items = list(_items(doc))
    marked = defaultdict(str)          # section -> normalised text of its [CONFIRM] items
    for where, text in items:
        if MARK.search(str(text)):
            marked[where] += ' ' + norm(str(text))
    unverified, checked = [], 0
    for where, text in items:
        text = str(text)
        if MARK.search(text):
            continue
        for m in FACT_RE.finditer(text):
            checked += 1
            phrase, kind = m.group(0), m.lastgroup
            if norm(phrase) in marked[where]:
                continue
            evidence = confirmed if kind in HOTEL_CONFIRMED else corpus
            if not _verified(phrase, evidence):
                start = max(0, m.start() - 60)
                unverified.append({'section': where, 'phrase': phrase, 'kind': kind,
                                   'needs': 'hotel confirmation' if kind in HOTEL_CONFIRMED else 'the live site',
                                   'context': text[start:m.end() + 60].replace('\n', ' ')})
    return {'checked': True, 'facts_checked': checked, 'unverified': unverified, 'evidence': sources}
