"""Questions for the hotel: one spreadsheet per hotel per audit, and reading the filled-in copy back.

build(group_dir, slug)           collects everything only the hotel can answer and writes
                                   <hotel dir>/audit-<date>/hotel-questions.json   (the master list, with where each
                                                                                    question is used: "refs")
                                   <hotel dir>/Reports/NN - <Hotel> Questions for the Hotel (<date>).xlsx
                                 Sheets and where each reads from:
                                 Questions (Q1..)  every [CONFIRM] in audit-<date>/audit-report.json, build-plan.json,
                                                   web-team.json and every held finding; wrong facts AI assistants gave
                                                   (the latest monthly-<YYYY-MM>/manual.json "ai_panel": results[].errors,
                                                   one question per fact across engines, skipped when the fact is
                                                   already confirmed); area facts in new copy that are neither sourced
                                                   nor confirmed (copy/claims-<date>.json from save_claims), other than
                                                   distances / travel times
                                 Rooms (R1..)      size, guests, beds per room type: the latest booking_engine.json
                                                   (site vs engine) and Booking.com facts
                                 Distances (D1..)  distances the site states (crawl site_text.json), Booking.com's nearby
                                                   list, the keyword map's landmarks, and distance / travel-time claims
                                                   from copy/claims-*.json (merged into the same place's row)
                                 Facts (F1..)      basic facts not yet confirmed (hotel-facts.json); name, address, phone
                                                   and website with every source's value where they disagree: the website
                                                   (audit-<date>/code/consistency.json "nap", else the crawl's
                                                   findings.json schema and tel: links), the Business Profile
                                                   (gbp/gbp-<date>.json listing) and Booking.com facts (the booking
                                                   engine gives no name / address / phone)
                                 Business Profile (B1..)  the latest gbp/amenities-<date>.json (gbp_amenities), compared
                                                   again with today's facts: values Google shows that no fact backs,
                                                   gaps and mismatches whose fact isn't the hotel's own, conflicting
                                                   facts. A field the Facts sheet already asks (check-in / out,
                                                   rooms, parking, breakfast, pets, airport transfer, Wi-Fi) goes into
                                                   that Facts row instead.
                                 The reports' markers become "[CONFIRM Q7]" so each gap points at its question. Ids stay
                                 the same across rebuilds (matched by room / place / fact / field / question key), and
                                 imported answers are kept, so it can be re-run after a monthly AI check or a write session.
edit(group_dir, slug, edits)     Claude's wording pass (Questions and Business Profile sheets).
import_answers(group_dir, slug, xlsx)
                                 reads the returned spreadsheet: answers into hotel-questions.json, confirmed facts into
                                 hotel-facts.json (source "hotel questionnaire, <date>, <who>"), which the [CONFIRM]
                                 guard, execute and gbp_amenities accept (Business Profile answers as kind "lodging",
                                 subject = the field). "Don't know" on an area fact means: take it out of the copy.
corrections(group_dir, slug)     where an answer contradicts the live site (room size / guests, distances, phone,
                                 address, name): text_replace actions for execute, each with the exact phrase found on
                                 the page.
save_claims(group_dir, slug, claims)
                                 write mode's claim ledger -> <hotel dir>/copy/claims-<date>.json.
"""
import json
import re
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from . import group as grp, paths

MARK = re.compile(r'\[CONFIRM(?P<rest>[^\]]*)\]')
NUMBERED = re.compile(r'^\s*(Q\d+)\b[:\s]*(.*)$')
YES = re.compile(r'^\s*(yes|y|correct|confirmed?|ok|okay|right|go ahead|approved?|agree[ds]?|✓|true)\b[\s.!]*$', re.I)
NO = re.compile(r'^\s*(no|n|not|none|wrong|don\'?t|do not|remove|false)\b', re.I)
FACTS = [('checkin_time', 'Check-in time'), ('checkout_time', 'Check-out time'),
         ('room_count', 'Number of rooms / apartments'), ('stars', 'Star rating'),
         ('phone', 'Reservations phone (with country code)'), ('email', 'Reservations email'),
         ('address', 'Address exactly as it should appear on Google'), ('parking', 'Parking (free / paid / none)'),
         ('breakfast', 'Breakfast (included / extra charge / not offered)'), ('pets', 'Pets allowed?'),
         ('children', 'Children: ages, extra beds, cots'), ('cancellation', 'Standard cancellation policy'),
         ('airport_transfer', 'Airport transfer (yes / no, paid / free)'), ('wifi', 'Wi-Fi (free / paid)')]
PLACE_WORDS = re.compile(r'airport|metro|station|mall|beach|expo|marina|tower|centre|center|souk|museum|stadium|'
                         r'hospital|university|park|creek|frame|burj|palm|global village|downtown|festival|port', re.I)
SIZE = re.compile(r'(\d+(?:[.,]\d+)?)(?:\s*[-–]\s*\d+(?:[.,]\d+)?)?\s*(m²|m2|sqm|sq\.?\s?m|square met(?:er|re)s?)', re.I)
GUESTS = re.compile(r'(?:up to|max(?:imum)?\.?|sleeps|accommodates?)\s*(\d+)\s*(?:guests?|people|persons|adults)', re.I)
DONT_KNOW = re.compile(r"^\s*(?:i\s+)?(?:don'?t|do not|dont)\s+know\b|^\s*(?:not sure|unsure|no idea|unknown|n/a)\b|"
                       r"^\s*\?+\s*$", re.I)
# Asked on the Facts sheet only when the sources disagree (phone and address are always on it until confirmed).
NAP_FACTS = {'name': 'Hotel name exactly as it should appear everywhere', 'website': 'Official website address'}
NAP_KINDS = ('name', 'address', 'phone', 'website')
NEW_TYPES = {'ai_error', 'area_claim'}          # rebuilt from their sources each time; unanswered stale ones are dropped
CLAIM_KINDS = {'distance', 'travel_time', 'opening_hours', 'visa', 'event_date', 'other'}
PHONE_RUN = re.compile(r'(?:\+|\b00)?\d[\d\s().-]{6,}\d')
# Topic of a wrong fact in an AI answer: the Facts-sheet kind it is about (so a confirmed fact or an open Facts row is
# found), or a lodging field. First match wins.
AI_TOPICS = [('checkin_time', r'check[- ]?in'), ('checkout_time', r'check[- ]?out'),
             ('phone', r'phone|telephone|\+\d{3}|\bcall\b'), ('email', r'e-?mail'),
             ('address', r'address|located (?:in|on|at)|\blocation\b'), ('name', r'\bname[ds]?\b|called'),
             ('room_count', r'\b\d+\s+(?:rooms|apartments|keys|units)\b|number of rooms'), ('stars', r'\bstars?\b'),
             ('parking', r'parking'), ('breakfast', r'breakfast'), ('pets', r'\bpets?\b'),
             ('wifi', r'wi-?fi|internet'), ('airport_transfer', r'airport (?:transfer|shuttle)|shuttle'),
             ('cancellation', r'cancel'), ('children', r'child|kids'), ('website', r'website|\burl\b'),
             ('lodging:pools.pool', r'\bpool'), ('lodging:wellness.fitnessCenter', r'\bgym\b|fitness'),
             ('lodging:wellness.spa', r'\bspa\b'), ('lodging:foodAndDrink.restaurant', r'restaurant')]


def _today():
    d = date.today()
    return d, f'{d.day} {d.strftime("%b %Y")}'


def _run_dir(group_dir, slug, run_date=None):
    hdir = grp.hotel_dir(group_dir, slug)
    runs = sorted(p for p in hdir.glob('audit-*') if p.is_dir())
    if run_date:
        return hdir, hdir / f'audit-{run_date}'
    if not runs:
        raise FileNotFoundError(f'no audit-<date> folder for {slug}: build the audit report first')
    return hdir, runs[-1]


def _sentence(text, pos):
    """The sentence around position pos, without markdown."""
    start = max(text.rfind('. ', 0, pos), text.rfind('\n', 0, pos), text.rfind('? ', 0, pos)) + 1
    ends = [i for i in (text.find('. ', pos), text.find('\n', pos)) if i != -1]
    end = min(ends) + 1 if ends else len(text)
    s = MARK.sub('', text[start:end])
    s = re.sub(r'[*_`#>]+', '', s)
    return re.sub(r'\s+', ' ', s).strip(' .;:-') + '.'


def _norm(s):
    return re.sub(r'\s+', ' ', re.sub(r'[^\w\s]', ' ', str(s or '').lower())).strip()


# ---------------------------------------------------------------- build

NUM_WORDS = {'one': '1', 'two': '2', 'three': '3', 'four': '4', 'five': '5', 'six': '6'}
GENERIC_ROOM = {'apartment', 'apartments', 'room', 'rooms', 'suite', 'suites', 'hotel', 'the', 'and', 'with', 'view'}
FACT_HINTS = {'checkin_time': r'check[- ]?in', 'checkout_time': r'check[- ]?out', 'phone': r'phone|call\b|\+971',
              'email': r'e-?mail|@', 'room_count': r'\b\d+\s+(?:rooms|apartments|keys|units)\b',
              'parking': r'parking', 'breakfast': r'breakfast', 'pets': r'\bpets?\b', 'wifi': r'wi-?fi',
              'airport_transfer': r'transfer|shuttle', 'cancellation': r'cancel', 'stars': r'\bstar\b',
              'children': r'child|kids|cot\b', 'address': r'address'}


def room_pattern(name):
    """Regex for a room type's name as sites write it: "One Bedroom" / "1-Bedroom" / "1 BR"."""
    words = [w for w in re.findall(r'[a-z0-9]+', name.lower()) if w not in GENERIC_ROOM]
    if not words:
        return None
    parts = []
    for w in words:
        alt = {w} | ({NUM_WORDS[w]} if w in NUM_WORDS else set()) | \
            ({k for k, v in NUM_WORDS.items() if v == w})
        if w.startswith('bedroom'):
            alt |= {'bedroom', 'bed', 'br', 'bhk'}
        parts.append('(?:' + '|'.join(sorted(alt, key=len, reverse=True)) + ')')
    # the name may run on into "Apartment" / "Room" / "Suite": that is still this room's name
    return re.compile(r'\b' + r'[\s-]*'.join(parts) + r'\b(?:[\s-]+(?:apartments?|rooms?|suites?)\b)?', re.I)


def _target(sentence, rooms, dists, basics):
    """Which sheet row a [CONFIRM] belongs to: a room (size / guests / beds), a distance, a basic fact; else None."""
    from . import facts as fx
    kinds = {m.lastgroup for m in fx.FACT_RE.finditer(sentence)}
    if kinds & {'size', 'count_confirm', 'count_site'} or re.search(r'\bbeds?\b|sleeps|guests?', sentence, re.I):
        hits = [r for r in rooms if r.get('_rx') and r['_rx'].search(sentence)]
        if len(hits) == 1:
            return hits[0]['id']
    if 'distance_time' in kinds:
        s = _norm(sentence)
        hits = [d for d in dists if _norm(d['place']) and _norm(d['place']) in s]
        if hits:
            return max(hits, key=lambda d: len(d['place']))['id']
    for b in basics:
        if re.search(FACT_HINTS.get(b.get('kind'), r'^\b$'), sentence, re.I):
            return b['id']
    return None


def _collect_markers(docs, items, by_key, next_id, rooms=(), dists=(), basics=()):
    """Number every [CONFIRM] in the documents (rewriting them in place). A gap about a room, a distance or a basic
    fact points at that row of its sheet ("[CONFIRM R2]"); everything else is grouped into one question per finding
    (or Build Plan page), listing every detail to confirm."""
    sheet_rows = {r['id']: r for r in list(rooms) + list(dists) + list(basics)}

    def walk(obj, where):
        if isinstance(obj, dict):
            w = dict(where)
            if obj.get('title') and isinstance(obj.get('title'), str):
                w['section'] = obj['title']
            if obj.get('finding_id'):
                w['finding_id'] = obj['finding_id']
            if obj.get('url') and isinstance(obj.get('url'), str):
                w['page'] = obj['url']
            return {k: walk(v, w) for k, v in obj.items()}
        if isinstance(obj, list):
            if obj and all(isinstance(v, (str, int, float)) or v is None for v in obj) and len(obj) <= 12:
                # a table row: the other cells (room name, page) tell what a [CONFIRM] in one cell is about
                where = dict(where, row=' | '.join(MARK.sub('', str(v)) for v in obj if v not in (None, '')))
            return [walk(v, where) for v in obj]
        if not isinstance(obj, str) or '[CONFIRM' not in obj:
            return obj

        def number(m):
            rest = m.group('rest').strip()
            hit = NUMBERED.match(rest) or re.match(r'^\s*([RDFB]\d+)\b', rest)
            if hit:                                      # already numbered on an earlier build
                qid = hit.group(1)
                if qid in items:
                    items[qid]['refs'].append(dict(where))
                elif qid in sheet_rows:
                    sheet_rows[qid].setdefault('refs', []).append(dict(where))
                return m.group(0)
            detail = rest.lstrip(':').strip()
            detail = re.sub(r'^(with (the )?hotel( which| what)?)\s*', '', detail, flags=re.I)
            context = _sentence(obj, m.start())
            context = re.sub(r'^(Fix|Where|Check|Why)\s*:\s*', '', context)
            if where.get('row') and context.rstrip('.') in where['row']:
                context = re.sub(r'\s+', ' ', where['row']).strip() + '.'
            tid = _target(context + ' ' + detail, rooms, dists, basics)
            if tid:
                sheet_rows[tid].setdefault('refs', []).append(dict(where, context=context))
                return f'[CONFIRM {tid}]'
            key = 'section:' + _norm(where.get('section') or where.get('page') or where.get('doc'))
            qid = by_key.get(key)
            if not qid:
                qid = f'Q{next_id[0]}'
                next_id[0] += 1
                by_key[key] = qid
                items[qid] = {'id': qid, 'sheet': 'Questions', 'type': 'confirm', 'key': key,
                              'topic': where.get('section', ''), 'page': where.get('page', ''),
                              'question': 'Are these details correct? Reply "Yes" if all are right, or write the '
                                          'correct version of any that are not.',
                              'details': [], 'now': '', 'why': f"Used in the {where.get('doc', '').replace('.json', '')}"
                                                                .replace('-', ' '), 'refs': [], 'answer': None}
            it = items[qid]
            line = (detail[:1].upper() + detail[1:] + ': ' if detail else '') + context
            if line not in it['details']:
                it['details'].append(line)
                it['now'] = '\n'.join(f'{n}. {d}' for n, d in enumerate(it['details'], 1))
            it['refs'].append(dict(where))
            return f'[CONFIRM {qid}]'
        return MARK.sub(number, obj)
    out = {}
    for name, doc in docs.items():
        out[name] = walk(doc, {'doc': name})
    return out


def _holds(report, items, next_id):
    skip = {'room_size_mismatch', 'facts_conflict'}          # asked in the Rooms sheet
    for s in report.get('sections', []):
        if not s.get('hold') or s.get('finding_id', '').replace('booking-', '').replace('facts-bookingcom-', '') in skip:
            continue
        if any(it.get('finding_id') == s.get('finding_id') for it in items.values()):
            continue
        rows = []
        for b in s.get('blocks', []):
            if 'table' in b:
                rows += ['; '.join(str(c) for c in r) for r in b['table'].get('rows', [])]
        qid = f'Q{next_id[0]}'
        next_id[0] += 1
        items[qid] = {'id': qid, 'sheet': 'Questions', 'type': 'hold', 'topic': s.get('title', ''),
                      'finding_id': s.get('finding_id'), 'page': ', '.join((s.get('pages_all') or [])[:3]),
                      'question': f"{s.get('title', '')}: is this right? Reply \"Yes\" to go ahead, \"No\" to leave it, "
                                  'or tell us what is correct.',
                      'now': ' | '.join(rows) or s.get('why', ''), 'why': f"On hold: {s['hold']}", 'refs': [
                          {'doc': 'audit-report.json', 'finding_id': s.get('finding_id'), 'section': s.get('title')}],
                      'answer': None}


def _facts(hdir):
    f = hdir / 'hotel-facts.json'
    return json.loads(f.read_text(encoding='utf-8')).get('facts', []) if f.exists() else []


def _rooms(hdir, facts):
    from . import facts as fx
    snaps = sorted(hdir.rglob('booking_engine.json'), key=lambda p: p.stat().st_mtime)
    engine = json.loads(snaps[-1].read_text(encoding='utf-8')) if snaps else {}
    rooms = (engine.get('website_vs_engine') or {}).get('rooms') or []
    conf = hdir / 'facts-conflicts.json'
    pairs = {}
    if conf.exists():
        for c in json.loads(conf.read_text(encoding='utf-8')).get('conflicts', []):
            if c.get('room_engine') and c.get('room_bookingcom'):
                pairs[_norm(c['room_engine'])] = c['room_bookingcom']

    def bc(room, kind):
        names = {_norm(room), _norm(pairs.get(_norm(room), ''))}
        for x in facts:
            if x.get('kind') == kind and _norm(x.get('subject')) in names and not fx.is_confirmed_source(x.get('source')):
                return str(x.get('value', ''))
        return ''
    out = []
    for n, r in enumerate(rooms, 1):
        out.append({'id': f'R{n}', 'sheet': 'Rooms', 'room': r.get('room', ''), 'page': r.get('site_page') or '',
                    'site_size': ', '.join(f'{s} m²' for s in r.get('sizes_on_page') or []),
                    'engine_size': r.get('engine_size') or '', 'bookingcom_size': bc(r.get('room', ''), 'room_size'),
                    'site_guests': ', '.join(str(x) for x in r.get('occupancy_on_page') or []),
                    'engine_guests': str(r.get('engine_max_occupancy') or ''),
                    'bookingcom_beds': bc(r.get('room', ''), 'room_beds'), 'answer': None})
    return out


def _site_text(group_dir, slug, reg):
    crawls = sorted(p for p in paths.resolve(group_dir).glob('crawl-*') if p.is_dir())
    if not crawls or not (crawls[-1] / 'site_text.json').exists():
        return {}
    texts = json.loads((crawls[-1] / 'site_text.json').read_text(encoding='utf-8'))
    if grp.is_single(reg):
        return texts
    return {u: t for u, t in texts.items() if grp.hotel_for(u, reg) == slug}


def _distances(hdir, facts, texts):
    from .analysis import DIST_A, DIST_B
    places = {}
    for url, text in texts.items():
        for rx, pi, vi, ui in ((DIST_A, 3, 1, 2), (DIST_B, 1, 2, 3)):
            for m in rx.finditer(text or ''):
                raw = m.group(pi).strip()
                place = re.split(r'[.!?;:,]\s|\.$', re.sub(r'^the\s+', '', raw, flags=re.I))[0].strip()
                if len(place) < 4 or not PLACE_WORDS.search(place):
                    continue
                phrase = m.group(0)
                if len(place) < len(raw):                       # cut the phrase where the place name ends
                    phrase = phrase[:phrase.find(raw) + len(raw)] if raw in phrase else phrase
                    phrase = phrase.replace(raw, place) if raw in phrase else phrase
                k = _norm(place)
                hit = next((kk for kk in places if kk.startswith(k) or k.startswith(kk)), None)
                p = places.setdefault(hit or k, {'place': place, 'site': [], 'pages': set(), 'phrases': []})
                if len(place) > len(p['place']):
                    p['place'] = place
                p['site'].append(f'{m.group(vi)} {m.group(ui)}')
                p['pages'].add(url)
                p['phrases'].append({'url': url, 'phrase': phrase})
    for x in facts:
        if x.get('kind') == 'nearby' and isinstance(x.get('value'), list):
            for v in x['value']:
                if PLACE_WORDS.search(v.get('place', '')):
                    k = _norm(v['place'])
                    hit = next((kk for kk in places if kk in k or k in kk), None)
                    p = places.setdefault(hit or k, {'place': v['place'], 'site': [], 'pages': set(), 'phrases': []})
                    p['bookingcom'] = v.get('distance', '')
    km_f = hdir / 'keywords' / 'keyword-map.json'
    if km_f.exists():
        for c in json.loads(km_f.read_text(encoding='utf-8')).get('clusters', []):
            if c.get('kind') == 'landmark' and c.get('distance_m') is not None:
                k = _norm(c['head'])
                hit = next((kk for kk in places if kk in k or k in kk), None)
                p = places.setdefault(hit or k, {'place': c['head'], 'site': [], 'pages': set(), 'phrases': []})
                p['map'] = f"{round(c['distance_m'] / 1000, 1)} km"
    out = []
    for n, p in enumerate(sorted(places.values(), key=lambda p: (not p['site'], p['place'].lower())), 1):
        out.append({'id': f'D{n}', 'sheet': 'Distances', 'place': p['place'],
                    'site_says': ', '.join(dict.fromkeys(p['site'])), 'bookingcom_says': p.get('bookingcom', ''),
                    'map_says': p.get('map', ''), 'pages': sorted(p['pages']), 'phrases': p['phrases'], 'answer': None})
    return out


def _confirmed(facts, kind, subject=None):
    """A confirmed (hotel-facts.json, never Booking.com alone), current fact of this kind (and subject)."""
    from . import facts as fx
    return any(x.get('kind') == kind and fx.is_confirmed_source(x.get('source')) and not x.get('superseded')
               and (subject is None or _norm(x.get('subject')) == _norm(subject)) for x in facts)


def _basic_facts(facts, extra=()):
    """Facts-sheet rows for the basic facts no confirmed fact covers; extra: more kinds to ask (name / website when
    the sources disagree on them)."""
    from . import facts as fx
    out = []
    for kind, label in FACTS + [(k, NAP_FACTS[k]) for k in extra]:
        have = [x for x in facts if x.get('kind') == kind]
        if any(fx.is_confirmed_source(x.get('source')) for x in have):
            continue
        we_have = '; '.join(f"{x.get('value')} ({x.get('source')})" for x in have) or 'not found'
        out.append({'id': f'F{len(out) + 1}', 'sheet': 'Facts', 'kind': kind, 'label': label, 'we_have': we_have,
                    'answer': None})
    return out


def _rel(hdir, f):
    try:
        return Path(f).relative_to(hdir).as_posix()
    except ValueError:
        return Path(f).name


# ---------------------------------------------------------------- name / address / phone

def _digits9(s):
    d = re.sub(r'\D', '', str(s or ''))
    return (d[2:] if d.startswith('00') else d)[-9:]


def _host(u):
    u = str(u or '').strip().lower()
    return re.sub(r'^www\.', '', urlparse(u if '//' in u else '//' + u).netloc)


def _nap_key(field, v):
    if field == 'phone':
        return _digits9(v)
    if field == 'website':
        return _host(v)
    return _norm(v)


def _nap_same(field, a, b):
    ka, kb = _nap_key(field, a), _nap_key(field, b)
    if field == 'address':          # "Street 5, Al Barsha" and "Street 5, Al Barsha, Dubai, AE" are one address
        sa, sb = set(ka.split()), set(kb.split())
        return sa <= sb or sb <= sa
    return ka == kb


def _nap_values(group_dir, slug, reg, hdir, facts):
    """{field: [{"source", "value", "pages"}]} for name / address / phone / website, and the files they came from."""
    mine = (lambda u: True) if grp.is_single(reg) else (lambda u: grp.hotel_for(u, reg) == slug)
    vals, files = {k: [] for k in NAP_KINDS}, []

    def add(field, source, value, pages=()):
        value = re.sub(r'\s+', ' ', str(value or '')).strip()
        if not value or not _nap_key(field, value):
            return
        for v in vals[field]:
            if v['source'] == source and _nap_key(field, v['value']) == _nap_key(field, value):
                v['pages'] = sorted(set(v['pages']) | set(pages))
                return
        vals[field].append({'source': source, 'value': value, 'pages': sorted(set(pages))})
    cons = sorted(hdir.glob('audit-*/code/consistency.json'))
    nap = json.loads(cons[-1].read_text(encoding='utf-8')).get('nap') if cons else None
    if nap:
        files.append(cons[-1])
        for field, key in (('name', 'name'), ('address', 'address'), ('phone', 'phone'), ('phone', 'schema_phone')):
            for v, urls in (nap.get(key) or {}).items():
                urls = [u for u in urls if mine(u)]
                if urls:
                    add(field, 'Website', v, urls)
    else:                                           # no consistency check with "nap" yet: the crawl's own findings
        crawls = sorted(p for p in paths.resolve(group_dir).glob('crawl-*') if (p / 'findings.json').exists())
        if crawls:
            rep = json.loads((crawls[-1] / 'findings.json').read_text(encoding='utf-8')).get('report', {})
            from .analysis import BUSINESS_TYPES
            for b in rep.get('schema', {}).get('blocks', []):
                urls = [u for u in b.get('urls') or [] if mine(u)]
                if b.get('type') not in BUSINESS_TYPES or not urls:
                    continue
                files.append(crawls[-1] / 'findings.json')
                add('name', 'Website', b.get('name'), urls)
                add('phone', 'Website', b.get('telephone'), urls)
                add('address', 'Website', ', '.join(x for x in (b.get('street'), b.get('locality')) if x), urls)
            for p in rep.get('phones', {}).get('numbers', []):
                urls = [u for u in p.get('urls') or [] if mine(u)]
                if p.get('in_tel_links') and urls:
                    add('phone', 'Website', p['number'], urls)
    g = sorted(hdir.glob('gbp/gbp-*.json'))
    if g:
        lst = json.loads(g[-1].read_text(encoding='utf-8')).get('listing') or {}
        if lst:
            files.append(g[-1])
            for field, key in (('name', 'title'), ('address', 'address'), ('phone', 'phone'), ('website', 'website')):
                add(field, 'Google Business Profile', lst.get(key))
    for x in facts:
        if x.get('kind') in NAP_KINDS and not x.get('superseded') and isinstance(x.get('value'), str):
            src = str(x.get('source') or '')
            add(x['kind'], 'Booking.com' if src.lower().startswith('booking.com') else src.split(',')[0] or 'our records',
                x['value'])
    if vals['website']:                              # the profile's link against the site we audit
        add('website', 'Website', reg['group'].get('site'))
    return vals, files


def _nap_differs(field, values):
    return any(not _nap_same(field, a['value'], b['value']) for a in values for b in values)


def _nap_text(values):
    return '; '.join(f"{v['source']}: “{v['value']}”" + (f" ({len(v['pages'])} page(s))" if v['pages'] else '')
                     for v in values)


def _merge_nap(basics, vals, files, hdir):
    """Put every source's name / address / phone / website on its Facts row (rows for name / website exist only when
    the sources disagree)."""
    for b in basics:
        if b['kind'] not in NAP_KINDS or not vals.get(b['kind']):
            continue
        values = vals[b['kind']]
        differs = _nap_differs(b['kind'], values)
        # the row's own facts (Booking.com, never confirmed) are among these values already
        b['we_have'] = ('These differ: ' if differs else '') + _nap_text(values)
        b['nap_values'] = values
        b['differs'] = differs
        b.setdefault('refs', []).extend({'doc': _rel(hdir, f), 'section': 'Name, address and phone'} for f in files)


# ---------------------------------------------------------------- Business Profile amenities and policies

def _lodging_by_source(facts, texts):
    """{lodging field: {"site_says", "engine_says", "bookingcom_says"}} from the facts and the site's pages."""
    from . import gbp_lodging as gl
    out = {}
    for x in facts:
        if x.get('superseded'):
            continue
        src = str(x.get('source') or '').lower()
        col = 'engine_says' if src.startswith('booking engine') else 'bookingcom_says' if src.startswith('booking.com') \
            else 'site_says' if src.startswith(('website', 'site', 'live site')) else None
        if not col:
            continue
        if x.get('kind') == 'facilities' and isinstance(x.get('value'), list):
            got = {}
            for f in x['value']:
                got.update(gl.mentions(f))
        elif x.get('kind') == 'lodging':
            v = gl.answer_value(x.get('subject', ''), x.get('value'))
            got = {x['subject']: v} if v else {}
        else:
            topic, text = gl._topic_of(x)
            got = gl._values(topic, text) if topic else {}
        for p, v in got.items():
            out.setdefault(p, {})[col] = v
    pages = {}
    for text in texts.values():
        for p in gl.mentions(text):
            pages[p] = pages.get(p, 0) + 1
    for p, n in pages.items():
        out.setdefault(p, {}).setdefault('site_says', f'mentioned on {n} page(s)')
    return out


def _gbp_rows(hdir, facts, texts, basics, dropped):
    """Business Profile sheet rows from the latest gbp/amenities-<date>.json; fields the Facts sheet asks go into that
    row instead."""
    from . import facts as fx, gbp_lodging as gl
    found = sorted(hdir.glob('gbp/amenities-*.json'))
    if not found:
        return []
    saved = json.loads(found[-1].read_text(encoding='utf-8'))
    if isinstance(saved.get('lodging'), dict):        # compare again: answers imported since then count
        cmp_ = gl.compare(saved['lodging'], str(hdir / 'hotel-facts.json'))
    else:
        cmp_ = saved
    ref = {'doc': _rel(hdir, found[-1]), 'section': 'Business Profile: hotel details (gbp_amenities, '
                                                    f"{saved.get('saved') or found[-1].stem[10:]})"}
    by_src = _lodging_by_source(facts, texts)
    f_rows = {b['kind']: b for b in basics}
    rows, seen = [], set()

    def add(path, label, gbp_val, why):
        if path in seen:
            return
        seen.add(path)
        kind = gl.FIELD_KIND.get(path)
        if kind in f_rows:                             # the Facts sheet already asks this: one row, its id
            b = f_rows[kind]
            b['gbp_says'] = (b.get('gbp_says') or []) + [f'{label}: {gbp_val}']
            b['refs'] = (b.get('refs') or []) + [dict(ref, field=path)]
            return
        if 'gbp:' + path in dropped:
            return
        typ = gl.WRITABLE.get(path, ('',))[0] or ('time' if path.endswith('Time') else
                                                  'int' if re.search(r'(?:Count|Year)$', path) else 'bool')
        ask = {'time': f'{label}: write the correct time (e.g. 15:00).',
               'int': f'{label}: write the correct number.'}.get(typ, f'{label}: yes or no?')
        rows.append({'id': '', 'sheet': 'Business Profile', 'field': path, 'label': label, 'gbp': gbp_val,
                     'site_says': '', 'engine_says': '', 'bookingcom_says': '', **by_src.get(path, {}),
                     'question': ask + ' Write "Don\'t know" if you are not sure.', 'why': why,
                     'key': 'gbp:' + path, 'refs': [dict(ref, field=path)], 'answer': None})
    for u in cmp_.get('unconfirmed') or []:
        add(u['field'], u['label'], u['gbp'], 'Google shows this on your listing; we have nothing from you to check it.')
    for kind in ('mismatches', 'gaps'):
        for m in cmp_.get(kind) or []:
            if fx.is_hotel_source(m.get('source')):
                continue                               # the hotel's own answer: a change to propose, not a question
            google = 'Google has nothing' if kind == 'gaps' else f"Google shows {m['gbp']}"
            add(m['field'], m['label'], m['gbp'], f"{google}; {m.get('source') or 'our records'} says "
                                                  f"{m['confirmed']} (“{m.get('fact', '')}”). Which is right?")
    for c in cmp_.get('conflicting_facts') or []:
        add(c['field'], c['label'], c['gbp'], 'Our sources disagree: ' + '; '.join(c.get('facts') or []))
    for b in basics:
        if b.get('gbp_says'):
            b['we_have'] = f"{b['we_have']}; Google Business Profile shows: " + ', '.join(b['gbp_says'])
    return rows


# ---------------------------------------------------------------- wrong facts in AI answers

def _ai_topic(text):
    from .facts import FACT_RE
    kinds = {m.lastgroup for m in FACT_RE.finditer(text)}
    if 'distance_time' in kinds:
        m = PLACE_WORDS.search(text)
        if m:
            return 'distance:' + m.group(0).lower()
    for kind, rx in AI_TOPICS:
        if re.search(rx, text, re.I):
            return kind
    return None


def _topic_confirmed(facts, topic):
    from . import facts as fx, gbp_lodging as gl
    if topic.startswith('distance:'):
        place = topic.split(':', 1)[1]
        return any(x.get('kind') == 'distance' and place in _norm(x.get('subject')) and fx.is_confirmed_source(
            x.get('source')) and not x.get('superseded') for x in facts)
    if topic.startswith('lodging:'):
        return _confirmed(facts, 'lodging', topic.split(':', 1)[1])
    if _confirmed(facts, topic):
        return True
    for x in facts:                                  # free-text facts ("Check-in time: 15:00", info sheet)
        if fx.is_confirmed_source(x.get('source')) and not x.get('superseded') and not x.get('kind'):
            t, _ = gl._topic_of(x)
            if t and topic in gl.TOPICS[t]['kinds']:
                return True
    return False


def _ai_items(hdir, facts, basics, items, by_key, next_id, dropped, seen):
    """Wrong facts from the latest month's AI-answer panel: into the open Facts row when there is one, else one
    Questions item per fact across engines. Already confirmed facts are fixes elsewhere, not questions."""
    from .monthly_proof import ENGINES, _day
    panel, src = None, None
    for f in sorted(hdir.glob('monthly-*/manual.json'), reverse=True):
        try:
            p = json.loads(f.read_text(encoding='utf-8')).get('ai_panel')
        except ValueError:
            continue
        if p and p.get('results'):
            panel, src = p, f
            break
    if not panel:
        return
    day = _day(panel.get('checked') or '')
    groups = {}
    for r in panel['results']:
        for e in r.get('errors') or []:
            topic = _ai_topic(e)
            key = 'ai:' + (topic or _norm(e)[:100])
            g = groups.setdefault(key, {'topic': topic, 'errors': [], 'engines': [], 'refs': []})
            eng = ENGINES.get(r.get('engine'), str(r.get('engine') or ''))
            if e not in g['errors']:
                g['errors'].append(e)
            if eng not in g['engines']:
                g['engines'].append(eng)
            g['refs'].append({'doc': _rel(hdir, src), 'section': f'AI answer check, {day}', 'engine': eng,
                              'prompt': r.get('prompt', ''), 'error': e})
    f_rows = {b['kind']: b for b in basics}
    for key, g in groups.items():
        topic = g['topic']
        if topic and _topic_confirmed(facts, topic):
            continue                                   # the right fact is known: fix the site / profile instead
        said = ' / '.join('“' + re.sub(r'^\s*(?:says|said|states?|claims?|gives)\s+(?:that\s+)?', '', e, flags=re.I)
                          + '”' for e in g['errors'])
        if topic in f_rows:
            b = f_rows[topic]
            b['we_have'] = f"{b['we_have']}; {', '.join(g['engines'])} ({day}) said: {said}"
            b['refs'] = (b.get('refs') or []) + g['refs']
            continue
        if key in dropped:
            continue
        seen.add(key)
        engines = ' and '.join(g['engines']) if len(g['engines']) < 3 else ', '.join(g['engines'][:-1]) + \
            ' and ' + g['engines'][-1]
        q = (f'{engines} {"says" if len(g["engines"]) == 1 else "say"}: {said}. What is correct? Write the correct '
             'fact, or "Yes" if this is in fact right.')
        now = '\n'.join(f"{x['engine']}, {day}, asked “{x['prompt']}”: {x['error']}" for x in g['refs'])
        qid = by_key.get(key)
        if qid and qid in items:
            items[qid].update(question=items[qid].get('question') if items[qid].get('edited') else q, now=now)
            items[qid]['refs'] = g['refs']
            continue
        qid = f'Q{next_id[0]}'
        next_id[0] += 1
        by_key[key] = qid
        items[qid] = {'id': qid, 'sheet': 'Questions', 'type': 'ai_error', 'key': key,
                      'topic': 'What AI assistants say about the hotel', 'page': '', 'question': q, 'now': now,
                      'why': f'A wrong fact AI assistants gave guests (AI answer check, {day}). The right fact goes on '
                             'the website and the Business Profile so the answers can change.',
                      'refs': g['refs'], 'answer': None}


# ---------------------------------------------------------------- area facts in written copy (claim ledger)

def _claim_key(text):
    return 'claim:' + _norm(text)[:120]


def save_claims(group_dir, slug, claims):
    """Write mode's claim ledger: [{"claim": "<as written>", "kind": "distance" | "travel_time" | "opening_hours" |
    "visa" | "event_date" | "other", "place": "<for distances>", "source": "<link, or empty>", "checked":
    "YYYY-MM-DD", "where": "<page URL or content file>"}] -> <hotel dir>/copy/claims-<today>.json (merged with today's
    file by claim text). Unsourced ones go to the hotel with the next hotel_questions."""
    reg = grp.load(group_dir)
    if not reg:
        raise FileNotFoundError('no site.json')
    next(h for h in reg['hotels'] if h['slug'] == slug)
    d = grp.hotel_dir(group_dir, slug) / 'copy'
    d.mkdir(parents=True, exist_ok=True)
    f = d / f'claims-{date.today().isoformat()}.json'
    doc = json.loads(f.read_text(encoding='utf-8')) if f.exists() else {'claims': []}
    by = {_claim_key(c['claim']): c for c in doc['claims']}
    problems = []
    for n, c in enumerate(claims or []):
        if not isinstance(c, dict) or not str(c.get('claim') or '').strip():
            problems.append(f'claims[{n}]: needs "claim" (the sentence as written)')
            continue
        kind = str(c.get('kind') or 'other').strip().lower().replace(' ', '_').replace('-', '_')
        if kind not in CLAIM_KINDS:
            problems.append(f'claims[{n}]: kind {kind!r} unknown, saved as "other" (use {", ".join(sorted(CLAIM_KINDS))})')
            kind = 'other'
        rec = {'claim': re.sub(r'\s+', ' ', str(c['claim'])).strip(), 'kind': kind,
               'place': str(c.get('place') or '').strip(), 'source': str(c.get('source') or '').strip(),
               'checked': str(c.get('checked') or '').strip(), 'where': str(c.get('where') or '').strip()}
        old = by.get(_claim_key(rec['claim']))
        if old and old.get('status'):
            rec['status'] = old['status']
        by[_claim_key(rec['claim'])] = rec
    doc['claims'] = list(by.values())
    f.write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding='utf-8')
    open_ = [c['claim'] for c in doc['claims'] if not c['source'] and not c.get('status')]
    return {'file': str(f), 'claims': len(doc['claims']), 'unsourced': open_, 'problems': problems,
            'next': ('Mark each unsourced claim [CONFIRM] in the copy (or remove it), and run hotel_questions to add '
                     'them to the Questions for the Hotel spreadsheet.') if open_ else 'Every claim has a source.'}


def _claims(hdir):
    """Every claim in copy/claims-*.json, the latest file's version of each, with the file it came from."""
    out = {}
    for f in sorted(hdir.glob('copy/claims-*.json')):
        try:
            for c in json.loads(f.read_text(encoding='utf-8')).get('claims', []):
                if c.get('claim'):
                    out[_claim_key(c['claim'])] = dict(c, _file=f)
        except ValueError:
            continue
    return out


def _claim_place(c):
    if c.get('place'):
        return c['place']
    m = re.search(r'(?:to|from|of|near)\s+(?:the\s+)?([A-Z][\w\'’&.-]*(?:\s+(?:of|al|Al|the|de)?\s*[A-Z][\w\'’&.-]*){0,4})',
                  c['claim'])
    return m.group(1) if m else c['claim']


def _claim_items(hdir, facts, dists, items, by_key, next_id, dropped, seen, stage):
    """Unsourced, unconfirmed area claims: distances and travel times on the Distances sheet (into the same place's
    row when there is one; stage "distances", before the ids are given), the rest on the Questions sheet (stage
    "questions", after the reports' markers). "Don't know" is a valid answer: the claim then leaves the copy."""
    for key, c in _claims(hdir).items():
        if c.get('source') or c.get('status') or key in dropped or _confirmed(facts, 'area_claim', key):
            continue
        ref = {'doc': _rel(hdir, c['_file']), 'section': 'Area facts in new copy (claim ledger)',
               'page': c.get('where', ''), 'claim': c['claim']}
        claim = {k: c.get(k, '') for k in ('claim', 'kind', 'where')} | {'key': key}
        is_distance = c.get('kind') in ('distance', 'travel_time')
        if is_distance != (stage == 'distances'):
            continue
        if is_distance:
            place = _claim_place(c)
            if any(x.get('kind') == 'distance' and fx_ok(x) and (_norm(place) in _norm(x.get('subject')) or
                                                                _norm(x.get('subject')) in _norm(place)) for x in facts):
                continue                               # the hotel already gave this distance
            k = _norm(place)
            row = next((d for d in dists if _norm(d['place']) and (_norm(d['place']) in k or k in _norm(d['place']))),
                       None)
            if row is None:
                row = {'id': '', 'sheet': 'Distances', 'place': place, 'site_says': '', 'bookingcom_says': '',
                       'map_says': '', 'pages': [], 'phrases': [], 'answer': None}
                dists.append(row)
            row.setdefault('claims', [])
            if all(x['key'] != key for x in row['claims']):
                row['claims'].append(claim)
                row['site_says'] = '; '.join(x for x in [row['site_says'], f"new copy: “{c['claim']}”"] if x)
            if c.get('where') and c['where'] not in row['pages']:
                row['pages'] = row['pages'] + [c['where']]
            row['refs'] = (row.get('refs') or []) + [ref]
            continue
        seen.add(key)
        q = (f"Our new text says: “{c['claim']}”. Is this right? Write \"Yes\", the correct version, or \"Don't know\" "
             '(then we take it out of the text; you don\'t need to look it up).')
        qid = by_key.get(key)
        if qid and qid in items:
            items[qid]['refs'] = [ref]
            continue
        qid = f'Q{next_id[0]}'
        next_id[0] += 1
        by_key[key] = qid
        items[qid] = {'id': qid, 'sheet': 'Questions', 'type': 'area_claim', 'key': key, 'claim': claim,
                      'topic': 'Area facts in new copy', 'page': c.get('where', ''), 'question': q,
                      'now': c['claim'] + (f" ({c['kind'].replace('_', ' ')})" if c.get('kind') else ''),
                      'why': 'A fact about the area in copy written for the website, with no source yet.',
                      'refs': [ref], 'answer': None}


def fx_ok(x):
    from . import facts as fx
    return fx.is_confirmed_source(x.get('source')) and not x.get('superseded')


# ---------------------------------------------------------------- stable ids

def _ident(i):
    return i['sheet'], _norm(i.get('room') or i.get('place') or i.get('kind') or i.get('field') or '')


def _assign_ids(rows, prefix, old_items, hwm):
    """Each row keeps the id (and the answer) it had on the last build; new rows get the next free number."""
    old = {_ident(i): i for i in old_items if i.get('id', '').startswith(prefix) and i['sheet'] != 'Questions'}
    used = set()
    for r in rows:
        o = old.get(_ident(r))
        r['id'] = ''
        if o and o['id'] not in used:
            r['id'] = o['id']
            used.add(o['id'])
            if o.get('answer'):
                r.update(answer=o['answer'], answered_on=o.get('answered_on'), answered_by=o.get('answered_by'))
    for r in rows:
        if not r['id']:
            hwm[prefix] = hwm.get(prefix, 0) + 1
            r['id'] = f'{prefix}{hwm[prefix]}'
    rows.sort(key=lambda r: int(r['id'][len(prefix):]))


def _high_water(old):
    hwm = dict(old.get('max_ids') or {})
    for i in old.get('items', []):
        m = re.match(r'^([A-Z])(\d+)$', i.get('id', ''))
        if m:
            hwm[m.group(1)] = max(hwm.get(m.group(1), 0), int(m.group(2)))
    return hwm


def build(group_dir, slug, run_date=None):
    reg = grp.load(group_dir)
    if not reg:
        raise FileNotFoundError('no site.json')
    hotel = next(h for h in reg['hotels'] if h['slug'] == slug)
    hdir, run = _run_dir(group_dir, slug, run_date)
    qf = run / 'hotel-questions.json'
    old = json.loads(qf.read_text(encoding='utf-8')) if qf.exists() else {}
    hwm = _high_water(old)
    dropped = set(old.get('dropped_keys') or [])
    items = {i['id']: dict(i, refs=[]) for i in old.get('items', []) if i['sheet'] == 'Questions'}
    by_key = {i['key']: i['id'] for i in items.values() if i.get('key')}
    next_id = [max([int(i[1:]) for i in items] + [hwm.get('Q', 0)]) + 1]
    facts = _facts(hdir)
    texts = _site_text(group_dir, slug, reg)
    rooms = _rooms(hdir, facts)
    dists = _distances(hdir, facts, texts)
    nap, nap_files = _nap_values(group_dir, slug, reg, hdir, facts)
    extra = [k for k in NAP_FACTS if not _confirmed(facts, k) and len(nap[k]) > 1 and _nap_differs(k, nap[k])]
    basics = _basic_facts(facts, extra)
    _merge_nap(basics, nap, nap_files, hdir)
    gbp_rows = _gbp_rows(hdir, facts, texts, basics, dropped)
    seen = set()
    _claim_items(hdir, facts, dists, items, by_key, next_id, dropped, seen, 'distances')
    old_items = old.get('items', [])
    for rows, prefix in ((rooms, 'R'), (dists, 'D'), (basics, 'F'), (gbp_rows, 'B')):
        _assign_ids(rows, prefix, old_items, hwm)
    for r in rooms:
        r['_rx'] = room_pattern(r['room'])
    names = ['audit-report.json', 'build-plan.json', 'web-team.json']
    docs = {n: json.loads((run / n).read_text(encoding='utf-8')) for n in names if (run / n).exists()}
    rewritten = _collect_markers(docs, items, by_key, next_id, rooms, dists, basics + gbp_rows)
    for n, d in rewritten.items():
        (run / n).write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding='utf-8')
    if 'audit-report.json' in rewritten:
        _holds(rewritten['audit-report.json'], items, next_id)
    _ai_items(hdir, facts, basics, items, by_key, next_id, dropped, seen)
    _claim_items(hdir, facts, dists, items, by_key, next_id, dropped, seen, 'questions')
    for r in rooms:
        r.pop('_rx', None)
    for qid in [k for k, i in items.items() if i.get('type') in NEW_TYPES and i.get('key') not in seen
                and not i.get('answer')]:
        del items[qid]                               # its source has gone (now confirmed, sourced, or fixed)
    qs = sorted(items.values(), key=lambda i: int(i['id'][1:]))
    hwm['Q'] = max([hwm.get('Q', 0), next_id[0] - 1])
    data = {'hotel': hotel['name'], 'slug': slug, 'site': reg['group']['site'], 'built': str(date.today()),
            'run': run.name, 'items': qs + rooms + dists + basics + gbp_rows, 'max_ids': hwm,
            'dropped_keys': sorted(dropped)}
    if old.get('imported'):
        data['imported'] = old['imported']
    qf.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding='utf-8')
    xlsx = _write_xlsx(data, hdir / 'Reports', hotel)
    return {'file': str(qf), 'xlsx': str(xlsx), 'questions': len(qs), 'rooms': len(rooms), 'distances': len(dists),
            'facts': len(basics), 'business_profile': len(gbp_rows),
            'ai_answer_errors': sum(1 for i in qs if i.get('type') == 'ai_error'),
            'area_claims': sum(1 for i in qs if i.get('type') == 'area_claim') +
            sum(len(d.get('claims') or []) for d in dists),
            'markers_numbered': sum(1 for i in data['items'] for r in i.get('refs') or [] if r.get('doc') in names),
            'next': 'Render the reports now (their [CONFIRM] markers carry the question numbers). Send the xlsx to '
                    'the hotel; when it comes back, import_hotel_answers.'}


def edit(group_dir, slug, edits):
    """Claude's wording pass over the Questions sheet. edits: [{"id": "Q4", "question": "...", "now": "...",
    "drop": true, "merge_into": "Q2"}]. drop: not a question for the hotel (its markers are removed from the
    reports); merge_into: the same ask as another question (its markers are renumbered). Rewrites the xlsx."""
    reg = grp.load(group_dir)
    hotel = next(h for h in reg['hotels'] if h['slug'] == slug)
    hdir, run = _run_dir(group_dir, slug)
    qf = run / 'hotel-questions.json'
    data = json.loads(qf.read_text(encoding='utf-8'))
    items = {i['id']: i for i in data['items']}
    renumber, problems = {}, []
    dropped = set(data.get('dropped_keys') or [])
    for e in edits:
        qid = e.get('id')
        if qid not in items or items[qid]['sheet'] not in ('Questions', 'Business Profile'):
            problems.append(f'{qid}: not a question id')
            continue
        if items[qid]['sheet'] == 'Business Profile' and e.get('merge_into'):
            problems.append(f'{qid}: Business Profile rows can be reworded or dropped, not merged')
            continue
        if e.get('drop'):
            renumber[qid] = None
            if items[qid].get('key'):
                dropped.add(items[qid]['key'])        # not asked again on the next build
        elif e.get('merge_into'):
            if e['merge_into'] not in items:
                problems.append(f"{qid}: merge_into {e['merge_into']} unknown")
                continue
            renumber[qid] = e['merge_into']
            tgt = items[e['merge_into']]
            tgt['refs'] = (tgt.get('refs') or []) + (items[qid].get('refs') or [])
        for k in ('question', 'now', 'why', 'topic'):
            if e.get(k):
                items[qid][k] = e[k]
                items[qid]['edited'] = True           # a rebuild keeps this wording
    if renumber:
        def fix(m):
            rest = m.group('rest').strip()
            hit = NUMBERED.match(rest)
            if not hit or hit.group(1) not in renumber:
                return m.group(0)
            new = renumber[hit.group(1)]
            return '' if new is None else f'[CONFIRM {new}]'

        def walk(o):
            if isinstance(o, dict):
                return {k: walk(v) for k, v in o.items()}
            if isinstance(o, list):
                return [walk(v) for v in o]
            return re.sub(r'\s{2,}', ' ', MARK.sub(fix, o)) if isinstance(o, str) and '[CONFIRM' in o else o
        for n in ('audit-report.json', 'build-plan.json', 'web-team.json'):
            if (run / n).exists():
                d = json.loads((run / n).read_text(encoding='utf-8'))
                (run / n).write_text(json.dumps(walk(d), indent=1, ensure_ascii=False), encoding='utf-8')
    data['items'] = [i for i in items.values() if i['id'] not in renumber]
    data['dropped_keys'] = sorted(dropped)
    qf.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding='utf-8')
    xlsx = _write_xlsx(data, hdir / 'Reports', hotel)
    return {'questions': sum(1 for i in data['items'] if i['sheet'] == 'Questions'), 'dropped': [k for k, v in
            renumber.items() if v is None], 'merged': {k: v for k, v in renumber.items() if v}, 'problems': problems,
            'xlsx': str(xlsx)}


# ---------------------------------------------------------------- spreadsheet

SHEETS = {
    'Questions': (['#', 'Topic', 'Question', 'What we see now', 'Why we ask', 'Page', 'Hotel answer',
                   'Answered by (name, role)'],
                  ['id', 'topic', 'question', 'now', 'why', 'page'], ['answer', 'answered_by'],
                  [7, 28, 45, 50, 30, 30, 40, 22]),
    'Rooms': (['#', 'Room type', 'Room page', 'Website says (size)', 'Booking engine (size)', 'Booking.com (size)',
               'Website (max guests)', 'Booking engine (max guests)', 'Booking.com (beds)', 'Size (m²)',
               'Max adults', 'Max children', 'Beds (e.g. 1 king + sofa bed)'],
              ['id', 'room', 'page', 'site_size', 'engine_size', 'bookingcom_size', 'site_guests', 'engine_guests',
               'bookingcom_beds'], ['size_m2', 'max_adults', 'max_children', 'beds'],
              [6, 26, 34, 16, 16, 16, 14, 14, 22, 12, 11, 11, 28]),
    'Distances': (['#', 'Place', 'Website says', 'Booking.com says', 'Map distance (straight line)',
                   'Distance by road (km)', 'Drive time (minutes)', 'Walk / Metro tip (optional)'],
                  ['id', 'place', 'site_says', 'bookingcom_says', 'map_says'], ['road_km', 'drive_min', 'tip'],
                  [6, 36, 22, 18, 18, 16, 16, 36]),
    'Facts': (['#', 'Fact', 'What we have now (source)', 'Correct answer'],
              ['id', 'label', 'we_have'], ['value'], [6, 40, 60, 40]),
    'Business Profile': (['#', 'Business Profile field', 'Google shows', 'Website says', 'Booking engine says',
                          'Booking.com says', 'Why we ask', 'Question', 'Correct answer'],
                         ['id', 'label', 'gbp', 'site_says', 'engine_says', 'bookingcom_says', 'why', 'question'],
                         ['value'], [6, 28, 16, 18, 18, 18, 40, 40, 30]),
}


def _write_xlsx(data, out_dir, hotel):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from . import pdf
    out_dir.mkdir(parents=True, exist_ok=True)
    navy, yellow, grey = PatternFill('solid', fgColor='12355B'), PatternFill('solid', fgColor='FFF4C2'), \
        PatternFill('solid', fgColor='F2F4F7')
    thin = Side(style='thin', color='D6DBE1')
    box = Border(left=thin, right=thin, top=thin, bottom=thin)
    wrap = Alignment(wrap_text=True, vertical='top')
    wb = Workbook()
    ws = wb.active
    ws.title = 'How to fill'
    counts = {s: sum(1 for i in data['items'] if i['sheet'] == s) for s in SHEETS}
    lines = [(f"{hotel['name']}: questions for the hotel", Font(bold=True, size=14, color='12355B')),
             (f"From the website audit of {data['built']} ({data['site']}).", None),
             ('', None),
             ('Please fill in the yellow cells only. Grey cells show what we found; leave them as they are.', None),
             ('Your answers are used exactly as written on the website, so please be precise (numbers, units, times).',
              None),
             ('If something we show is already correct, write "Yes". If you would rather not publish it, write "No".',
              None),
             ('Distances and facts about the area: if you don\'t know, write "Don\'t know". We then take it out of the '
              'text; you don\'t need to look it up.', None),
             ('', None),
             *[(f'{s}: {n} item(s)', Font(bold=True)) for s, n in counts.items() if n],
             ('', None),
             ('Answered by (name, role):', Font(bold=True)),
             ('Date:', Font(bold=True))]
    for r, (text, font) in enumerate(lines, 1):
        ws.cell(row=r, column=1, value=text)
        if font:
            ws.cell(row=r, column=1).font = font
    who_row = len(lines) - 1
    for r in (who_row, who_row + 1):
        ws.cell(row=r, column=2).fill = yellow
        ws.cell(row=r, column=2).border = box
    ws.column_dimensions['A'].width = 34
    ws.column_dimensions['B'].width = 40
    for name, (headers, info, answers, widths) in SHEETS.items():
        rows = [i for i in data['items'] if i['sheet'] == name]
        if not rows:
            continue
        s = wb.create_sheet(name)
        s.append(headers)
        for c in s[1]:
            c.fill, c.font, c.alignment, c.border = navy, Font(bold=True, color='FFFFFF'), wrap, box
        for i in rows:
            vals = [i.get(k, '') if not isinstance(i.get(k), list) else ', '.join(i.get(k)) for k in info]
            ans = i.get('answer') or {}
            s.append(vals + [ans.get(k, '') for k in answers])
            r = s.max_row
            for col in range(1, len(headers) + 1):
                cell = s.cell(row=r, column=col)
                cell.alignment, cell.border = wrap, box
                cell.fill = yellow if col > len(info) else grey
        for n, w in enumerate(widths, 1):
            s.column_dimensions[chr(64 + n)].width = w
        s.freeze_panes = 'C2'
    name = re.sub(r'[<>:"/\\|?*]', '-', f"{hotel['name']} Questions for the Hotel ({date.today().day} "
                                        f"{date.today().strftime('%b')}).xlsx")
    same = [f for f in out_dir.glob(f'* - {name}')]
    num = re.match(r'(\d+) - ', same[0].name).group(1) if same else pdf.next_file_number()
    f = out_dir / f'{num} - {name}'
    wb.save(f)
    return f


# ---------------------------------------------------------------- answers

def _latest_questions(hdir):
    found = sorted(hdir.glob('audit-*/hotel-questions.json'))
    return found[-1] if found else None


def load(group_dir, slug):
    f = _latest_questions(grp.hotel_dir(group_dir, slug))
    return json.loads(f.read_text(encoding='utf-8')) if f else None


def classify(answer_text):
    t = str(answer_text or '').strip()
    if not t:
        return 'unanswered'
    if YES.match(t):
        return 'yes'
    if NO.match(t):
        return 'no'
    return 'value'


def import_answers(group_dir, slug, xlsx_path):
    from openpyxl import load_workbook
    hdir = grp.hotel_dir(group_dir, slug)
    qf = _latest_questions(hdir)
    if not qf:
        raise FileNotFoundError('no hotel-questions.json: run hotel_questions first')
    data = json.loads(qf.read_text(encoding='utf-8'))
    items = {i['id']: i for i in data['items']}
    wb = load_workbook(paths.resolve(xlsx_path), data_only=True)
    who = ''
    if 'How to fill' in wb.sheetnames:
        for row in wb['How to fill'].iter_rows(values_only=True):
            if row and str(row[0] or '').startswith('Answered by') and len(row) > 1 and row[1]:
                who = str(row[1]).strip()
    unknown, answered = [], {}
    for name, (headers, info, answers, _) in SHEETS.items():
        if name not in wb.sheetnames:
            continue
        ws = wb[name]
        head = [str(c.value or '').strip() for c in ws[1]]
        cols = {h: n for n, h in enumerate(head)}
        for row in ws.iter_rows(min_row=2, values_only=True):
            qid = str(row[0] or '').strip()
            if not qid:
                continue
            if qid not in items:
                unknown.append(qid)
                continue
            vals = {}
            for key, h in zip(answers, headers[len(info):]):
                v = row[cols[h]] if h in cols and cols[h] < len(row) else None
                if v not in (None, ''):
                    vals[key] = str(v).strip() if not isinstance(v, (int, float)) else v
            if vals:
                items[qid]['answer'] = vals
                answered[qid] = vals
    d, today = _today()
    source = f'hotel questionnaire, {today}' + (f', {who}' if who else '')
    for i in items.values():
        if i['id'] in answered:
            i['answered_on'] = str(d)
            i['answered_by'] = (i.get('answer') or {}).get('answered_by') or who
    data['items'] = list(items.values())
    data['imported'] = {'on': str(d), 'file': str(xlsx_path), 'by': who}
    qf.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding='utf-8')
    added = _to_facts(hdir, [items[k] for k in answered], source)
    remove = _claim_outcomes(hdir, [items[k] for k in answered], today)
    open_ = [i['id'] for i in items.values() if not i.get('answer')]
    gbp_answered = [k for k in answered if items[k]['sheet'] == 'Business Profile'] + \
        [k for k in answered if items[k]['sheet'] == 'Facts' and any(r.get('field') for r in items[k].get('refs') or [])]
    return {'answered': len(answered), 'not_answered': open_, 'unknown_ids_in_file': unknown, 'facts_added': added,
            'source': source, 'corrections': len(corrections(group_dir, slug)),
            'remove_from_copy': remove,
            **({'business_profile': f'{len(gbp_answered)} answer(s) about the Business Profile: run gbp_amenities '
                                    '(domain, slug) for the changes they give, and offer them (Business Profile '
                                    'changes).'} if gbp_answered else {}),
            'next': 'Run execute_plan: answered [CONFIRM] / held items are now included, and the corrections (site text '
                    'that contradicts the hotel) are in the "hotel-answers" batch.'}


def _to_facts(hdir, answered, source):
    f = hdir / 'hotel-facts.json'
    doc = json.loads(f.read_text(encoding='utf-8')) if f.exists() else {'facts': []}
    new = []
    for i in answered:
        a = i['answer']
        if i['sheet'] == 'Rooms':
            if a.get('size_m2') not in (None, ''):
                new.append({'kind': 'room_size', 'subject': i['room'], 'value': f"{a['size_m2']} m²",
                            'fact': f"{i['room']}: {a['size_m2']} m²"})
            if a.get('max_adults') not in (None, ''):
                ch = a.get('max_children')
                new.append({'kind': 'room_occupancy', 'subject': i['room'], 'value': a['max_adults'],
                            'fact': f"{i['room']}: up to {a['max_adults']} adults" + (f' and {ch} children' if ch else '')})
            if a.get('beds'):
                new.append({'kind': 'room_beds', 'subject': i['room'], 'value': a['beds'],
                            'fact': f"{i['room']}: {a['beds']}"})
        elif i['sheet'] == 'Distances':
            if a.get('road_km') not in (None, '') and not DONT_KNOW.match(str(a['road_km'])):
                t = f" ({a['drive_min']} minutes' drive)" if a.get('drive_min') not in (None, '') else ''
                new.append({'kind': 'distance', 'subject': i['place'], 'value': f"{a['road_km']} km",
                            'fact': f"{i['place']}: {a['road_km']} km by road{t}"})
            if a.get('tip') and not DONT_KNOW.match(str(a['tip'])):
                new.append({'kind': 'distance_tip', 'subject': i['place'], 'value': a['tip'],
                            'fact': f"{i['place']}: {a['tip']}"})
        elif i['sheet'] == 'Facts' and a.get('value') not in (None, '') and not DONT_KNOW.match(str(a['value'])):
            new.append({'kind': i['kind'], 'subject': 'property', 'value': a['value'], 'fact': f"{i['label']}: {a['value']}"})
        elif i['sheet'] == 'Business Profile' and a.get('value') not in (None, '') \
                and not DONT_KNOW.match(str(a['value'])):
            # read by gbp_amenities as this field's confirmed value (gbp_lodging.confirmed_values)
            new.append({'kind': 'lodging', 'subject': i['field'], 'value': a['value'],
                        'fact': f"{i['label']}: {a['value']}"})
        elif i['sheet'] == 'Questions' and i.get('type') == 'area_claim':
            t = str(a.get('answer') or '')
            c = 'dont_know' if DONT_KNOW.match(t) else classify(t)
            if c == 'yes':
                new.append({'kind': 'area_claim', 'subject': i['key'], 'value': i['claim']['claim'],
                            'fact': i['claim']['claim']})
            elif c == 'value':
                new.append({'kind': 'area_claim', 'subject': i['key'], 'value': t, 'fact': t})
        elif i['sheet'] == 'Questions':
            if DONT_KNOW.match(str(a.get('answer') or '')):
                continue
            c = classify(a.get('answer'))
            if c == 'yes':
                new.append({'kind': 'confirmed', 'subject': i['id'], 'value': i['now'], 'fact': i['now']})
            elif c == 'value':
                new.append({'kind': 'answer', 'subject': i['id'], 'value': a['answer'],
                            'fact': f"{i['question']} {a['answer']}"})
    have = {(x.get('kind'), x.get('subject'), str(x.get('value')), x.get('source')) for x in doc.get('facts', [])}
    added = 0
    for x in new:
        x['source'] = source
        if (x['kind'], x['subject'], str(x['value']), source) not in have:
            doc.setdefault('facts', []).append(x)
            added += 1
    f.write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding='utf-8')
    return added


def _claim_outcomes(hdir, answered, today):
    """What the hotel's answers mean for the area claims in new copy: "Don't know" (or "No") takes the claim out of
    the copy; a value or "Yes" confirms it. The outcome is written into copy/claims-*.json (so the claim isn't asked
    again) and the claims to remove are returned."""
    outcome = {}                                       # claim key -> (status, claim dict, question id)
    for i in answered:
        a = i.get('answer') or {}
        if i['sheet'] == 'Questions' and i.get('type') == 'area_claim':
            t = str(a.get('answer') or '')
            c = 'dont_know' if DONT_KNOW.match(t) else classify(t)
            st = {'dont_know': f"remove: the hotel doesn't know ({today})", 'no': f'remove: the hotel says it is wrong '
                  f'({today})', 'yes': f'confirmed by the hotel ({today})',
                  'value': f'corrected by the hotel ({today}): {t}'}.get(c)
            if st:
                outcome[i['key']] = (st, i['claim'], i['id'])
        elif i['sheet'] == 'Distances' and i.get('claims'):
            km = a.get('road_km')
            if km not in (None, '') and _num(km) is not None:
                st = f"corrected by the hotel ({today}): {km} km by road"
            elif any(DONT_KNOW.match(str(v)) for v in a.values() if v not in (None, '')):
                st = f"remove: the hotel doesn't know ({today})"
            else:
                continue
            for c in i['claims']:
                outcome[c['key']] = (st, c, i['id'])
    if not outcome:
        return []
    for f in sorted(hdir.glob('copy/claims-*.json')):
        try:
            doc = json.loads(f.read_text(encoding='utf-8'))
        except ValueError:
            continue
        hit = False
        for c in doc.get('claims', []):
            o = outcome.get(_claim_key(c.get('claim', '')))
            if o:
                c['status'] = o[0]
                hit = True
        if hit:
            f.write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding='utf-8')
    return [{'question': qid, 'claim': c.get('claim'), 'where': c.get('where', ''), 'why': st}
            for st, c, qid in outcome.values() if st.startswith('remove')]


def _num(v):
    try:
        return float(str(v).replace(',', '.').split()[0])
    except (ValueError, IndexError):
        return None


def _owner(text, pos, rooms_rx, window=160):
    """The room whose name is mentioned last before pos (within window characters), or None."""
    best, best_at, best_end = None, -1, -1
    for rid, rx in rooms_rx:
        if not rx:
            continue
        for m in rx.finditer(text, max(0, pos - window), pos):
            if m.start() > best_at:
                best, best_at, best_end = rid, m.start(), m.end()
    if best and re.search(r'\b(apartments?|rooms?|suites?|villas?|penthouses?)\b', text[best_end:pos], re.I):
        return None              # another room type is named in between: not sure whose size this is, leave it
    return best


def _nap_corrections(i, want, texts):
    """The hotel's phone / address / name against the page text: each other value a source gave (website, Business
    Profile, Booking.com) is replaced where that exact text is on a page. A phone is matched by its digits, whatever the
    spacing on the page; a name or address only verbatim, and never when it is part of the answer itself (replacing
    "Abar Hotel" inside "Abar Hotel Apartments" would double words)."""
    out, kind = [], i['kind']
    why = f"Hotel answer {i['id']}: the {'phone number' if kind == 'phone' else kind} is {want}"
    olds = [v['value'] for v in i['nap_values'] if not _nap_same(kind, v['value'], want)]
    if kind == 'phone':
        # a site can carry other numbers (restaurant, WhatsApp): a website number counts as the hotel's phone only
        # when it is the site's one number, or another source (Business Profile, Booking.com) gives it too
        site = {_digits9(v['value']) for v in i['nap_values'] if v['source'] == 'Website'}
        other = {_digits9(v['value']) for v in i['nap_values'] if v['source'] != 'Website'}
        wrong = (other | (site if len(site) == 1 else site & other)) - {_digits9(want), ''}
        for url, text in texts.items():
            for m in PHONE_RUN.finditer(text or ''):
                run = m.group(0).strip(' .-()')
                if _digits9(run) in wrong:
                    out.append({'type': 'text_replace', 'url': url, 'find': run, 'replace': want,
                                'question': i['id'], 'why': why})
        return out
    for o in olds:
        if len(o) < 6 or o.lower() in want.lower():
            continue
        for url, text in texts.items():
            if o in (text or ''):
                out.append({'type': 'text_replace', 'url': url, 'find': o, 'replace': want, 'question': i['id'],
                            'why': why})
    return out


def corrections(group_dir, slug):
    """text_replace actions where the hotel's answer contradicts the live site, with the exact phrase on the page."""
    reg = grp.load(group_dir)
    data = load(group_dir, slug)
    if not data:
        return []
    texts = _site_text(group_dir, slug, reg)
    rooms_rx = [(i['id'], room_pattern(i['room'])) for i in data['items'] if i['sheet'] == 'Rooms']
    out = []
    for i in data['items']:
        a = i.get('answer') or {}
        if i['sheet'] == 'Rooms' and i.get('page') and _num(a.get('size_m2')) is not None:
            want = _num(a['size_m2'])
            text = texts.get(i['page'], '')
            for m in SIZE.finditer(text):
                if _owner(text, m.start(), rooms_rx) != i['id']:
                    continue                       # a size of another room (cards, "other rooms"), not this one
                if _num(m.group(1)) != want or '–' in m.group(0) or '-' in m.group(0):
                    new = f"{a['size_m2']} {m.group(2)}"
                    out.append({'type': 'text_replace', 'url': i['page'], 'find': m.group(0), 'replace': new,
                                'question': i['id'], 'why': f"Hotel answer {i['id']}: {i['room']} is {a['size_m2']} m²"})
        if i['sheet'] == 'Rooms' and i.get('page') and _num(a.get('max_adults')) is not None:
            want = int(_num(a['max_adults']) + (_num(a.get('max_children')) or 0))
            text = texts.get(i['page'], '')
            for m in GUESTS.finditer(text):
                if _owner(text, m.start(), rooms_rx) != i['id']:
                    continue
                if int(m.group(1)) != want:
                    out.append({'type': 'text_replace', 'url': i['page'], 'find': m.group(0),
                                'replace': m.group(0).replace(m.group(1), str(want), 1), 'question': i['id'],
                                'why': f"Hotel answer {i['id']}: {i['room']} sleeps up to {want}"})
        if i['sheet'] == 'Distances' and _num(a.get('road_km')) is not None:
            want = _num(a['road_km'])
            for p in i.get('phrases') or []:
                m = re.search(r'(\d+(?:\.\d+)?)\s?(km|kms|kilomet(?:er|re)s?)', p['phrase'], re.I)
                if m and _num(m.group(1)) != want:
                    out.append({'type': 'text_replace', 'url': p['url'], 'find': p['phrase'],
                                'replace': p['phrase'].replace(m.group(0), f"{a['road_km']} {m.group(2)}", 1),
                                'question': i['id'], 'why': f"Hotel answer {i['id']}: {i['place']} is {a['road_km']} km"})
        if i['sheet'] == 'Facts' and i.get('kind') in ('phone', 'address', 'name') and i.get('nap_values') \
                and a.get('value') not in (None, '') and not DONT_KNOW.match(str(a['value'])):
            out += _nap_corrections(i, str(a['value']).strip(), texts)
    seen, uniq = set(), []
    for c in out:
        k = (c['url'], c['find'])
        if k not in seen:
            seen.add(k)
            uniq.append(c)
    return uniq
