"""[CONFIRM] guard: every hotel fact in a list must be backed by evidence or marked [CONFIRM].

Two kinds of fact (playbook ground rules 5 and 6):
  site-checkable   sizes, star rating, beds, floors, restaurants, pools...: OK if the live site says it
  site-checkable   services and inclusions (in-room dining, airport transfer, private beach, free
                   breakfast / parking / Wi-Fi...): OK if the live site or the facts file says it
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
    # m² and sq ft (Abar's sizes are in sq ft), single figures and ranges ("700–807 sq ft")
    'size': rf'{NUM}(?:\s?[–-]\s?{NUM})?\s*(?:m²|m2|sqm|sq\.?\s?m\b|square met(?:er|re)s?|sq\.?\s?ft|ft²|'
            rf'square f(?:ee|oo)t)',
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
    # services and inclusions guests hold the hotel to (schema amenityFeature, FAQ answers)
    'service': r'\b(?:room service|in-room dining|airport (?:transfers?|shuttle|pick-?up)|valet parking|'
               r'private beach|all[- ]inclusive|butler|babysitting|kids? club|'
               r'(?:free|complimentary) (?:wi-?fi|parking|breakfast|cancellation|shuttle|transfers?|upgrades?|'
               r'late check-?out|early check-?in|access|minibar))\b',
    'loyalty': r'\b(?:loyalty|membership|member|rewards?) (?:tiers?|levels?)\b|\b(?:silver|gold|platinum) (?:tier|level|member)s?\b',
}
HOTEL_CONFIRMED = {'distance_time', 'count_confirm', 'round_the_clock', 'price', 'percent', 'time', 'loyalty'}
MARK = re.compile(r'\[CONFIRM[^\]]*\]')
URL_LIKE = re.compile(r'(?:https?://|www\.)\S+|(?<![\w])/[\w\-./]*[?#][^\s`)\]]*|`[^`]*(?:/|\?|=)[^`]*`')
FACT_RE = re.compile('|'.join(f'(?P<{k}>{v})' for k, v in FACT_PATTERNS.items()), re.I)


def norm(s):
    s = (s or '').lower().replace('²', '2').replace('–', '-').replace('—', '-')
    s = re.sub(r'(\d),(\d{3})', r'\1\2', s)
    s = re.sub(r'\s*(?:sq\.?\s?ft|ft2|square f(?:ee|oo)t)\b', ' sqft', s)
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


def _items(doc, with_context=False):
    """(section, text) for every text the guard reads; with_context adds the sentence or table row
    the text sits in (a value in a table cell is to be deleted when its row says Delete)."""
    def out(where, text, ctx=None):
        return (where, text, text if ctx is None else ctx) if with_context else (where, text)
    for w in doc.get('warnings_top', []) + doc.get('warnings_end', []):
        yield out('warning', w)
    for p in doc.get('intro', []):
        yield out('intro', p)
    for s in doc.get('sections', []):
        if s.get('code_data'):
            continue            # our own data tables (keyword volumes, OpenStreetMap distances), not hotel claims
        where = f"{s.get('number', '')} {s.get('title', '')}".strip()
        prev = ''
        for b in s.get('blocks', []):
            (kind, val), = b.items()
            if kind == 'code':
                yield out(where, val, f'\x00code {prev} {val}')     # "Delete these lines:" then the code block
            elif kind in ('p', 'warning', 'note', 'paste', 'h3'):
                yield out(where, val)
            elif kind in ('ol', 'ul'):
                for li in val:
                    yield out(where, li)
            elif kind == 'table':
                for row in val.get('rows', []):
                    joined = ' | '.join(str(c) for c in row)
                    for c in row:
                        yield out(where, f'{c}' + (' [CONFIRM]' if MARK.search(joined) else ''), joined)
            prev = str(val) if kind in ('p', 'ol', 'ul', 'h3', 'note') else ''


def is_confirmed_source(source):
    """Which hotel-facts.json sources count as confirmation for the [CONFIRM] guard. Booking.com alone never does;
    "Booking.com + booking engine, <date>" (the engine agreed, bookingcom.crosscheck) does."""
    s = str(source or '').strip().lower()
    return bool(s) and not s.startswith('booking.com,')


def is_hotel_source(source):
    """The hotel's own answer (questionnaire, information sheet, email, WhatsApp, the hotel contact)."""
    return str(source or '').strip().lower().startswith(('hotel', 'the hotel'))


def is_sheet_source(source):
    """An answer the hotel wrote in the Questions for the Hotel sheet (import_hotel_answers)."""
    return str(source or '').strip().lower().startswith('hotel questionnaire')


def is_engine_source(source):
    return str(source or '').strip().lower().startswith('booking engine')


def source_rank(source):
    """Which fact wins a conflict. What the hotel's own booking engine (/search) shows is always right (the user's
    rule, Nov 2026): booking engine 3 > the hotel's Questions sheet answer 2 > other hotel messages (email,
    WhatsApp) 1 > everything else (site, Booking.com, AI answers) 0. A hotel answer that contradicts the engine is kept
    as a note for whoever manages Mirai; the site follows the engine."""
    if is_engine_source(source):
        return 3
    if is_sheet_source(source):
        return 2
    return 1 if is_hotel_source(source) else 0


ROOM_FACT = re.compile(r'^\s*(?P<room>[^:]{3,80}?):\s*(?P<val>.+)$')
GUESTS = re.compile(r'(?:up to|sleeps|max(?:imum)?|for)\s*(\d+)\s*(?:guests?|people|persons|adults)?|(\d+)\s*guests', re.I)
ADULTS_KIDS = re.compile(r'(\d+)\s*adults?\s*(?:\+|and|&)\s*(\d+)\s*(?:children|kids|child)', re.I)
SIZE_VAL = re.compile(r'(\d[\d,.]*(?:\s?[–-]\s?\d[\d,.]*)?)\s*(m²|m2|sqm|sq\.?\s?m\b|sq\.?\s?ft|ft²|square f(?:ee|oo)t|'
                      r'square met(?:er|re)s?)', re.I)


def _room_key(name):
    return re.sub(r'[^a-z0-9]+', ' ', name.lower().replace('one', '1').replace('two', '2').replace('three', '3')
                  .replace('four', '4')).strip()


def room_fact(text):
    """("2 bedroom apartment", "guests" | "size", value) for facts like "Two Bedroom Apartment: up to 8 guests
    (4 adults + 4 children)" or "Two Bedroom Apartment: 1,012–1,184 sq ft"; None otherwise."""
    m = ROOM_FACT.match(str(text or ''))
    if not m or not re.search(r'room|suite|apartment|studio|villa|chalet|penthouse|bedroom', m.group('room'), re.I):
        return None
    val = m.group('val')
    ak = ADULTS_KIDS.search(val)
    g = GUESTS.search(val)
    if ak or g:
        n = int(ak.group(1)) + int(ak.group(2)) if ak else int(g.group(1) or g.group(2))
        return _room_key(m.group('room')), 'guests', n
    sz = SIZE_VAL.search(val)
    if sz:
        return _room_key(m.group('room')), 'size', norm(sz.group(0))
    return None


def add_facts(facts_file, facts, source):
    """Add facts with their source. One value per fact (same room, same kind): the higher source_rank wins and the
    other is marked "superseded" (the booking engine beats everything, the hotel's answers included). Returns what
    was added, what was superseded, and engine_corrections: hotel answers the engine overrules (the site follows the
    engine; if the hotel is right, the engine setting must change first)."""
    f = paths.resolve(facts_file)
    doc = json.loads(f.read_text(encoding='utf-8')) if f.exists() else {'facts': []}
    rows = doc.setdefault('facts', [])
    have = {x.get('fact') for x in rows}
    rank_new = source_rank(source)
    added, superseded, overruled = [], [], []
    for text in facts:
        text = str(text if isinstance(text, str) else (text or {}).get('fact', '')).strip()
        if not text or text in have:
            continue
        rf = room_fact(text)
        rec = {'fact': text, 'source': source}
        for x in rows:
            xf = room_fact(x.get('fact'))
            if not (rf and xf and xf[:2] == rf[:2] and xf[2] != rf[2]) or x.get('superseded'):
                continue
            rank_old = source_rank(x.get('source'))
            if rank_new > rank_old:
                x['superseded'] = True
                x['superseded_by'] = f'{text} ({source})'
                superseded.append(x['fact'])
                if is_engine_source(source) and is_hotel_source(x.get('source')):
                    overruled.append({'hotel_said': f"{x['fact']} ({x['source']})", 'engine_sells': text})
            elif rank_old > rank_new:
                rec['superseded'] = True
                rec['superseded_by'] = f"{x['fact']} ({x['source']})"
                if is_hotel_source(source) and is_engine_source(x.get('source')):
                    overruled.append({'hotel_said': f'{text} ({source})', 'engine_sells': x['fact']})
        rows.append(rec)
        have.add(text)
        added.append(text)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding='utf-8')
    out = {'added': added, 'superseded': superseded, 'engine_corrections': engine_corrections(facts_file),
           'facts_file': str(f)}
    if overruled:
        out['engine_overrides'] = {'rows': overruled, 'note': 'The booking engine is always right: the site follows '
                                   'it. If the hotel is right, whoever manages Mirai changes the engine first; the '
                                   'site follows on the next run.'}
    return out


def engine_corrections(facts_file):
    """Rooms where the hotel says something other than what the booking engine sells (Questions sheet, email,
    WhatsApp). The engine is always right for the site, so the page follows the engine; if the hotel is right, this
    is the engine setting to change in Mirai (Abar, Nov 2026: the engine sold the Two-Bedroom for 5; the hotel said 4
    adults + 4 children). Never a [CONFIRM] question and never a page edit."""
    f = paths.resolve(facts_file)
    if not f.exists():
        return []
    rows = json.loads(f.read_text(encoding='utf-8')).get('facts', [])
    hotel = {}
    for x in rows:
        rf = room_fact(x.get('fact'))
        if rf and is_hotel_source(x.get('source')):
            hotel[rf[:2]] = (x['fact'], x['source'], rf[2])
    out = []
    for x in rows:
        rf = room_fact(x.get('fact'))
        if rf and str(x.get('source', '')).lower().startswith('booking engine') and rf[:2] in hotel \
                and hotel[rf[:2]][2] != rf[2]:
            h = hotel[rf[:2]]
            out.append({'room': x['fact'].split(':')[0].strip(), 'kind': rf[1], 'engine_sells': x['fact'],
                        'hotel_says': f'{h[0]} ({h[1]})',
                        'fix': f"The site follows the engine ({x['fact']}). If the hotel is right, change "
                               f"{rf[1]} for {x['fact'].split(':')[0].strip()} in the Mirai extranet first; the site "
                               'follows on the next run.'})
    seen, uniq = set(), []
    for c in out:
        k = (c['room'], c['kind'], c['engine_sells'])
        if k not in seen:
            seen.add(k)
            uniq.append(c)
    return uniq


def load_corpus(crawl_dir='', facts_file=''):
    site, confirmed, sources = [], [], []
    if crawl_dir:
        f = paths.resolve(crawl_dir) / 'site_text.json'
        if f.exists():
            site.extend(json.loads(f.read_text(encoding='utf-8')).values())
            sources.append(str(f))
    if facts_file and paths.resolve(facts_file).exists():
        facts = json.loads(paths.resolve(facts_file).read_text(encoding='utf-8')).get('facts', [])
        # A fact the hotel has corrected is kept for the record with "superseded": true and no longer counts
        # (Abar, Nov 2026: the engine sold the Two-Bedroom for 5; the hotel said 4 adults + 4 children).
        # Booking.com alone is never confirmation.
        confirmed.extend(x.get('fact', '') for x in facts
                         if is_confirmed_source(x.get('source', '')) and not x.get('superseded'))
        sources.append(str(paths.resolve(facts_file)))
    confirmed_text = norm(' \n '.join(confirmed))
    return norm(' \n '.join(site)) + ' \n ' + confirmed_text, confirmed_text, sources


DELETE_WORDS = re.compile(r'\b(?:delete|remove|drop|take out|get rid of)\b', re.I)
CODE_SPAN = re.compile(r'`[^`]*`')
REGEX_BACKREF = re.compile(r'^\$\d$')


def _to_delete(text, ctx, m, kind_is_code):
    """A value the list tells the reader to delete is not a claim the list makes: skip it when it sits
    in a code span (or a code block) and the sentence, row or lead-in says delete / remove."""
    if not DELETE_WORDS.search(ctx or ''):
        return False
    if kind_is_code:
        return True
    return any(c.start() <= m.start() and m.end() <= c.end() for c in CODE_SPAN.finditer(text))


def check(doc, crawl_dir='', facts_file=''):
    corpus, confirmed, sources = load_corpus(crawl_dir, facts_file)
    if not sources:
        return {'checked': False, 'reason': 'no site_text.json (run audit_site) and no hotel-facts.json'}
    items = list(_items(doc, with_context=True))
    marked = defaultdict(str)          # section -> normalised text of its [CONFIRM] items
    for where, text, _ in items:
        if MARK.search(str(text)):
            marked[where] += ' ' + norm(str(text))
    unverified, checked, skipped = [], 0, 0
    for where, text, ctx in items:
        text, ctx = str(text), str(ctx)
        if MARK.search(text):
            continue
        is_code_block = ctx.startswith('\x00code ')
        # URLs and paths are addresses, not hotel facts ("%2C", "checkin=20%2F03" in booking links)
        text = URL_LIKE.sub(lambda m: ' ' * len(m.group(0)), text)
        for m in FACT_RE.finditer(text):
            checked += 1
            phrase, kind = m.group(0), m.lastgroup
            if norm(phrase) in marked[where]:
                continue
            if kind == 'price' and REGEX_BACKREF.match(phrase.strip()):
                skipped += 1           # "$1" in a redirect rule is a regex backreference, not a price
                continue
            if _to_delete(text, ctx, m, is_code_block):
                skipped += 1
                continue
            evidence = confirmed if kind in HOTEL_CONFIRMED else corpus
            if not _verified(phrase, evidence):
                start = max(0, m.start() - 60)
                unverified.append({'section': where, 'phrase': phrase, 'kind': kind,
                                   'needs': 'hotel confirmation' if kind in HOTEL_CONFIRMED else 'the live site',
                                   'context': text[start:m.end() + 60].replace('\n', ' ')})
    return {'checked': True, 'facts_checked': checked, 'skipped_as_deletions_or_regex': skipped,
            'unverified': unverified, 'evidence': sources}
