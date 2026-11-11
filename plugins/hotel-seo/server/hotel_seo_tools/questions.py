"""Questions for the hotel: one spreadsheet per hotel per audit, and reading the filled-in copy back.

build(group_dir, slug)           collects everything only the hotel can answer and writes
                                   <hotel dir>/audit-<date>/hotel-questions.json   (the master list, with where each
                                                                                    question is used)
                                   <hotel dir>/Reports/NN - <Hotel> Questions for the Hotel (<date>).xlsx
                                 Sheets: Questions (Q1..: every [CONFIRM] in the Audit Report / Build Plan / Web Team
                                 List and every item on hold), Rooms (R1..: size, guests, beds per room type, with what
                                 the site, the booking engine and Booking.com say), Distances (D1..), Facts (F1..: basic
                                 facts not yet confirmed). The reports' markers become "[CONFIRM Q7]" so each gap points
                                 at its question.
import_answers(group_dir, slug, xlsx)
                                 reads the returned spreadsheet: answers into hotel-questions.json, confirmed facts into
                                 hotel-facts.json (source "hotel questionnaire, <date>, <who>"), which the [CONFIRM]
                                 guard and execute accept.
corrections(group_dir, slug)     where an answer contradicts the live site (room size / guests, distances): text_replace
                                 actions for execute, each with the exact phrase found on the page.
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
        if re.search(FACT_HINTS.get(b['kind'], r'^\b$'), sentence, re.I):
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
            hit = NUMBERED.match(rest) or re.match(r'^\s*([RDF]\d+)\b', rest)
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


def _basic_facts(facts):
    from . import facts as fx
    out = []
    for n, (kind, label) in enumerate(FACTS, 1):
        have = [x for x in facts if x.get('kind') == kind]
        if any(fx.is_confirmed_source(x.get('source')) for x in have):
            continue
        we_have = '; '.join(f"{x.get('value')} ({x.get('source')})" for x in have) or 'not found'
        out.append({'id': f'F{len(out) + 1}', 'sheet': 'Facts', 'kind': kind, 'label': label, 'we_have': we_have,
                    'answer': None})
    return out


def build(group_dir, slug, run_date=None):
    reg = grp.load(group_dir)
    if not reg:
        raise FileNotFoundError('no site.json')
    hotel = next(h for h in reg['hotels'] if h['slug'] == slug)
    hdir, run = _run_dir(group_dir, slug, run_date)
    qf = run / 'hotel-questions.json'
    old = json.loads(qf.read_text(encoding='utf-8')) if qf.exists() else {}
    items = {i['id']: dict(i, refs=[]) for i in old.get('items', []) if i['sheet'] == 'Questions'}
    by_key = {i['key']: i['id'] for i in items.values() if i.get('key')}
    next_id = [max([int(i[1:]) for i in items] or [0]) + 1]
    facts = _facts(hdir)
    rooms = _rooms(hdir, facts)
    for r in rooms:
        r['_rx'] = room_pattern(r['room'])
    dists = _distances(hdir, facts, _site_text(group_dir, slug, reg))
    basics = _basic_facts(facts)
    names = ['audit-report.json', 'build-plan.json', 'web-team.json']
    docs = {n: json.loads((run / n).read_text(encoding='utf-8')) for n in names if (run / n).exists()}
    rewritten = _collect_markers(docs, items, by_key, next_id, rooms, dists, basics)
    for n, d in rewritten.items():
        (run / n).write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding='utf-8')
    if 'audit-report.json' in rewritten:
        _holds(rewritten['audit-report.json'], items, next_id)
    for r in rooms:
        r.pop('_rx', None)
    # keep answers already imported when the list is rebuilt
    ident = (lambda i: (i['sheet'], _norm(i.get('room') or i.get('place') or i.get('kind') or '')))
    old_answers = {ident(i): i for i in old.get('items', []) if i['sheet'] != 'Questions' and i.get('answer')}
    for i in rooms + dists + basics:
        o = old_answers.get(ident(i))
        if o:
            i.update(answer=o['answer'], answered_on=o.get('answered_on'), answered_by=o.get('answered_by'))
    qs = sorted(items.values(), key=lambda i: int(i['id'][1:]))
    _, today = _today()
    data = {'hotel': hotel['name'], 'slug': slug, 'site': reg['group']['site'], 'built': str(date.today()),
            'run': run.name, 'items': qs + rooms + dists + basics}
    qf.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding='utf-8')
    xlsx = _write_xlsx(data, hdir / 'Reports', hotel)
    return {'file': str(qf), 'xlsx': str(xlsx), 'questions': len(qs), 'rooms': len(rooms), 'distances': len(dists),
            'facts': len(basics),
            'markers_numbered': sum(len(i.get('refs') or []) for i in data['items']),
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
    for e in edits:
        qid = e.get('id')
        if qid not in items or items[qid]['sheet'] != 'Questions':
            problems.append(f'{qid}: not a question id')
            continue
        if e.get('drop'):
            renumber[qid] = None
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
    open_ = [i['id'] for i in items.values() if not i.get('answer')]
    return {'answered': len(answered), 'not_answered': open_, 'unknown_ids_in_file': unknown, 'facts_added': added,
            'source': source, 'corrections': len(corrections(group_dir, slug)),
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
            if a.get('road_km') not in (None, ''):
                t = f" ({a['drive_min']} minutes' drive)" if a.get('drive_min') not in (None, '') else ''
                new.append({'kind': 'distance', 'subject': i['place'], 'value': f"{a['road_km']} km",
                            'fact': f"{i['place']}: {a['road_km']} km by road{t}"})
            if a.get('tip'):
                new.append({'kind': 'distance_tip', 'subject': i['place'], 'value': a['tip'],
                            'fact': f"{i['place']}: {a['tip']}"})
        elif i['sheet'] == 'Facts' and a.get('value') not in (None, ''):
            new.append({'kind': i['kind'], 'subject': 'property', 'value': a['value'], 'fact': f"{i['label']}: {a['value']}"})
        elif i['sheet'] == 'Questions':
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
    seen, uniq = set(), []
    for c in out:
        k = (c['url'], c['find'])
        if k not in seen:
            seen.add(k)
            uniq.append(c)
    return uniq
