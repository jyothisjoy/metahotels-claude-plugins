"""Proof for the Monthly Report: what AI answers say about the hotel, and whether each change moved its page.

1. AI-answer panel. A fixed set of about ten guest questions per hotel (<hotel dir>/ai-prompts.json, built once from
   the keyword map and hotel facts, editable), asked every month in ChatGPT, Perplexity and Google (AI Mode / AI
   Overview) through Claude in Chrome in the user's own browser. Per question and engine: hotel named, link to the
   hotel site cited, position among the hotels named, other hotels / OTAs named, description correct (errors listed).
   Saved as the "ai_panel" block of monthly-<month>/manual.json (import_monthly_manual). It is a sample of answers on
   the day it was run (answers vary), never a ranking; a month without a run shows "not run", never zeros.

2. Change readback. Every page changed through execute (execute-*/changes.json) or logged with a URL in work-log.csv:
   Search Console clicks, Google views (impressions), CTR and position for the 28 days before and after the change
   (and 56 when that much time has passed), against unchanged pages of the same type over the same days (a
   difference-in-differences: the page's change minus the similar pages' change). Labels: Promote, Keep testing,
   Rollback candidate, Unproven. Wording is "moved with / against similar pages": this never proves cause.
"""
import csv
import json
import re
from datetime import date, timedelta
from urllib.parse import urlparse

# ---------------------------------------------------------------- constants

PROMPTS_FILE = 'ai-prompts.json'
PROMPT_TARGET = 10
ENGINES = {'chatgpt': 'ChatGPT', 'perplexity': 'Perplexity', 'google_ai': 'Google AI Mode / AI Overview'}
ENGINE_ALIASES = {'chatgpt': 'chatgpt', 'chat gpt': 'chatgpt', 'openai': 'chatgpt', 'perplexity': 'perplexity',
                  'google_ai': 'google_ai', 'google': 'google_ai', 'google ai': 'google_ai',
                  'google ai mode': 'google_ai', 'ai mode': 'google_ai', 'ai overview': 'google_ai',
                  'google ai overview': 'google_ai', 'gemini': 'google_ai'}
RESULT_FIELDS = ('prompt', 'engine', 'named', 'cited', 'position', 'hotels_named', 'competitors',
                 'description_correct', 'errors', 'note')
PANEL_FIELDS = ('checked', 'results', 'not_run', 'note', 'source')

WINDOW_DAYS = 28                 # days before / after a change compared
LONG_WINDOW_DAYS = 56            # used instead when that much time has passed since the change
MIN_IMPRESSIONS = 100            # Google views the page needs in the window before AND after; fewer -> Keep testing
MIN_CLICKS_FOR_CLICK_METRIC = 20  # below this many clicks before, compare Google views instead of clicks
MIN_CONTROL_PAGES = 3            # unchanged similar pages needed for a comparison
GAP_POINTS = 20                  # percentage points ahead of / behind similar pages for Promote / Rollback candidate
READBACK_LOOKBACK_DAYS = 120     # changes made this many days before the month's end are read back
GSC_LAG_DAYS = 3

_MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
LABELS = {'promote': ('Promote', 'green'), 'keep_testing': ('Keep testing', 'grey'),
          'rollback': ('Rollback candidate', 'red'), 'unproven': ('Unproven', 'amber')}


# ---------------------------------------------------------------- 1. AI-answer prompts

def prompts_file(ctx):
    return ctx['hotel_dir'] / PROMPTS_FILE


def load_prompts(ctx):
    f = prompts_file(ctx)
    return json.loads(f.read_text(encoding='utf-8')) if f.exists() else None


def _hotel_facts(ctx):
    f = ctx['hotel_dir'] / 'hotel-facts.json'
    if not f.exists():
        return []
    try:
        return json.loads(f.read_text(encoding='utf-8')).get('facts', [])
    except ValueError:
        return []


def _fact_lines(facts, limit=40):
    out = []
    for x in facts:
        if x.get('fact'):
            out.append(str(x['fact']))
        elif x.get('kind') and x.get('value') not in (None, '', []):
            v = x['value']
            out.append(f"{x['kind']}: {', '.join(map(str, v)) if isinstance(v, list) else v}")
    return out[:limit]


def build_prompts(hotel, kmap=None, facts=None):
    """About ten questions a guest would type, from the keyword map (area, landmarks, audiences, facilities, rooms)
    and the hotel's name. Discovery questions test whether the hotel is recommended; brand questions test whether
    the description is right."""
    kmap, facts = kmap or {}, facts or []
    name = hotel.get('name') or ''
    city = hotel.get('city') or kmap.get('city') or 'Dubai'
    tw = 'hotel apartment' if re.search(r'apartment', name, re.I) else 'hotel'
    cl = sorted(kmap.get('clusters', []), key=lambda c: -(c.get('score') or 0))

    def heads(kind, n):
        return [str(c.get('head') or c.get('primary_keyword')) for c in cl if c.get('kind') == kind][:n]
    places = [p for p in heads('place', 2) if p.lower() != city.lower()]
    if not places:
        places = [str(p.get('name') if isinstance(p, dict) else p) for p in (kmap.get('places') or [])][:1]
    area = places[0] if places else city
    where = area if area.lower() == city.lower() else f'{area}, {city}'
    landmarks = heads('landmark', 2)
    audiences = heads('audience', 3)
    facilities = [f for f in heads('facility', 3)]
    rooms = heads('room', 2)
    out = []

    def add(text, kind, why):
        t = re.sub(r'\s+', ' ', text).strip()
        if t.lower() not in [p['prompt'].lower() for p in out] and len(out) < PROMPT_TARGET:
            out.append({'id': f'p{len(out) + 1}', 'prompt': t, 'kind': kind, 'why': why})

    add(f'What is the best {tw} in {where}?', 'discovery', f'area: {area}')
    for lm in landmarks:
        add(f'Recommend a {tw} near {lm}', 'discovery', f'landmark: {lm}')
    def with_(f):
        return f if f.startswith('with') else f'with {f}'
    extra = with_(facilities[0]) if facilities else (f'with a {rooms[0]}' if rooms else '')
    used = set()
    for a in audiences[:2]:
        if a in ('monthly', 'long stay'):
            add(f'{tw.capitalize()} in {area} for a monthly stay', 'discovery', f'audience: {a}')
        elif a in ('cheap', 'budget'):
            add(f'Good value {tw} in {area}', 'discovery', f'audience: {a}')
        else:
            add(f'{a.capitalize()} {tw} in {area} {extra}', 'discovery', f'audience: {a}')
            used.add(extra)
    for f in facilities[:3]:
        if with_(f) not in used:
            add(f'{tw.capitalize()} in {area} {with_(f)}', 'discovery', f'facility: {f}')
    for r in rooms[:1]:
        add(f'Where can I book a {r} in {area}?', 'discovery', f'room: {r}')
    add(f'Tell me about {name} in {city}: location, rooms and facilities', 'brand', 'description check')
    add(f'Is {name} a good place to stay? What is nearby?', 'brand', 'description check')
    for t, why in ((f'Where should I stay in {where}?', f'area: {area}'),
                   (f'{tw.capitalize()} in {city} near the metro', 'location'),
                   (f'Best {tw}s in {city} for a short stay', 'city'),
                   (f'Quiet {tw} in {area} for a business trip', 'audience: business'),
                   (f'Family {tw} in {area}', 'audience: family')):
        add(t, 'discovery', why)
    return out


def propose_prompts(ctx):
    km = ctx['hotel_dir'] / 'keywords' / 'keyword-map.json'
    kmap = json.loads(km.read_text(encoding='utf-8')) if km.exists() else {}
    data = {'confirmed': False, 'proposed': str(date.today()),
            'prompts': build_prompts(ctx['hotel'], kmap, _hotel_facts(ctx)),
            'source': 'keyword map' if kmap else 'hotel name and city only (no keyword map yet)',
            'note': 'Proposed from the keyword map. Show them to the user, edit, then save with ai_prompts(prompts=...). '
                    'The same questions run every month so months compare.'}
    prompts_file(ctx).write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding='utf-8')
    return data


def save_prompts(ctx, prompts):
    """Confirm the question set. Items: "text" or {"prompt", "kind": "discovery" | "brand", "why"}. Questions kept
    from the old set keep their id."""
    old = {p['prompt'].lower(): p for p in (load_prompts(ctx) or {}).get('prompts', [])}
    used = {p['id'] for p in old.values()}
    clean = []
    for p in prompts or []:
        p = {'prompt': p} if isinstance(p, str) else dict(p)
        text = re.sub(r'\s+', ' ', str(p.get('prompt') or '')).strip()
        if not text or text.lower() in [c['prompt'].lower() for c in clean]:
            continue
        kind = p.get('kind') or (old.get(text.lower()) or {}).get('kind') or 'discovery'
        if kind not in ('discovery', 'brand'):
            raise ValueError(f'kind must be "discovery" or "brand" (got {kind!r})')
        pid = (old.get(text.lower()) or {}).get('id')
        if not pid:
            n = 1
            while f'p{n}' in used:
                n += 1
            pid = f'p{n}'
            used.add(pid)
        clean.append({'id': pid, 'prompt': text, 'kind': kind, 'why': p.get('why') or
                      (old.get(text.lower()) or {}).get('why', '')})
    if not clean:
        raise ValueError('no questions given')
    if len(clean) > 20:
        raise ValueError(f'{len(clean)} questions: keep the set to about ten (20 at most) so a monthly run stays short')
    data = {'confirmed': True, 'confirmed_on': str(date.today()), 'prompts': clean}
    prompts_file(ctx).write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding='utf-8')
    return data


def prompts_tool(ctx, propose=False, prompts=None):
    """Read, propose or save the hotel's AI-answer questions; the read includes the hotel facts to check against."""
    if prompts:
        data = save_prompts(ctx, prompts)
    elif propose or not load_prompts(ctx):
        data = propose_prompts(ctx)
    else:
        data = load_prompts(ctx)
    return {**data, 'file': str(prompts_file(ctx)), 'engines': ENGINES,
            'facts_to_check': _fact_lines(_hotel_facts(ctx)),
            'facts_file': str(ctx['hotel_dir'] / 'hotel-facts.json')}


# ---------------------------------------------------------------- 1. AI-answer panel: import and validation

def _bool(v, field):
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in ('yes', 'y', 'true', '1'):
        return True
    if s in ('no', 'n', 'false', '0'):
        return False
    raise ValueError(f'{field} must be yes / no (got {v!r})')


def _list(v):
    if v in (None, ''):
        return []
    if isinstance(v, str):
        v = re.split(r'\s*[;\n]\s*', v)
    return [re.sub(r'\s+', ' ', str(x)).strip() for x in v if str(x).strip()]


def engine_key(e):
    k = ENGINE_ALIASES.get(re.sub(r'[\s_-]+', ' ', str(e or '')).strip().lower())
    if not k:
        k = ENGINE_ALIASES.get(str(e or '').strip().lower())
    if not k:
        raise ValueError(f'engine {e!r} unknown; use one of: {", ".join(ENGINES)}')
    return k


def validate_panel(panel, prompt_set):
    """Check what Claude read in the AI answers. Raises ValueError on anything not in the format."""
    if not isinstance(panel, dict):
        raise ValueError('ai_panel must be an object {"checked", "results": [...], "not_run": {...}}')
    unknown = [k for k in panel if k not in PANEL_FIELDS]
    if unknown:
        raise ValueError(f'ai_panel.{unknown[0]} is not a known field; allowed: {", ".join(PANEL_FIELDS)}')
    prompts = (prompt_set or {}).get('prompts') or []
    if not prompts:
        raise ValueError('no AI-answer questions for this hotel: create them with ai_prompts first')
    by_id = {p['id']: p for p in prompts}
    by_text = {p['prompt'].lower(): p for p in prompts}
    checked = str(panel.get('checked') or date.today())
    try:
        date.fromisoformat(checked)
    except ValueError:
        raise ValueError(f'ai_panel.checked must be YYYY-MM-DD (got {checked!r})') from None
    results, seen = [], set()
    for i, r in enumerate(panel.get('results') or []):
        where = f'ai_panel.results[{i}]'
        if not isinstance(r, dict):
            raise ValueError(f'{where} must be an object')
        bad = [k for k in r if k not in RESULT_FIELDS]
        if bad:
            raise ValueError(f'{where}.{bad[0]} is not a known field; allowed: {", ".join(RESULT_FIELDS)}')
        q = str(r.get('prompt') or '').strip()
        p = by_id.get(q) or by_text.get(re.sub(r'\s+', ' ', q).lower())
        if not p:
            raise ValueError(f'{where}.prompt {q!r} is not one of the saved questions (ids or exact text from '
                             'ai_prompts)')
        eng = engine_key(r.get('engine'))
        if (p['id'], eng) in seen:
            raise ValueError(f'{where}: {p["id"]} × {eng} given twice')
        seen.add((p['id'], eng))
        if 'named' not in r or 'cited' not in r:
            raise ValueError(f'{where}: "named" and "cited" are required (yes / no)')
        named, cited = _bool(r['named'], f'{where}.named'), _bool(r['cited'], f'{where}.cited')
        pos = r.get('position')
        if pos in ('', None):
            pos = None
        else:
            try:
                pos = int(pos)
            except (TypeError, ValueError):
                raise ValueError(f'{where}.position must be a whole number (got {pos!r})') from None
            if pos < 1:
                raise ValueError(f'{where}.position must be 1 or more')
        if not named and pos is not None:
            raise ValueError(f'{where}: a position is given but the hotel was not named')
        hn = r.get('hotels_named')
        hn = None if hn in ('', None) else int(hn)
        if pos is not None and hn is not None and pos > hn:
            raise ValueError(f'{where}: position {pos} is beyond the {hn} hotels named')
        dc = r.get('description_correct')
        dc = None if dc in ('', None) else _bool(dc, f'{where}.description_correct')
        errors = _list(r.get('errors'))
        if not named and (dc is not None or errors):
            raise ValueError(f'{where}: the hotel was not named, so there is no description to check')
        if dc is False and not errors:
            raise ValueError(f'{where}: description_correct is no: list the errors (what the answer said vs the fact)')
        if dc is True and errors:
            raise ValueError(f'{where}: errors listed but description_correct is yes')
        results.append({'id': p['id'], 'prompt': p['prompt'], 'kind': p.get('kind', 'discovery'), 'engine': eng,
                        'named': named, 'cited': cited, 'position': pos, 'hotels_named': hn,
                        'competitors': _list(r.get('competitors')), 'description_correct': dc, 'errors': errors,
                        'note': str(r.get('note') or '')})
    not_run = {}
    for e, why in (panel.get('not_run') or {}).items():
        not_run[engine_key(e)] = str(why or 'not run')
    clash = sorted({r['engine'] for r in results} & set(not_run))
    if clash:
        raise ValueError(f'{", ".join(clash)} has results and is also listed as not run')
    if not results and not not_run:
        raise ValueError('ai_panel has no results: leave it out when the panel was not run this month')
    return {'checked': checked, 'results': results, 'not_run': not_run,
            'prompts_in_set': len(prompts), 'note': str(panel.get('note') or ''),
            'source': str(panel.get('source') or 'Claude in Chrome (answers read in the user\'s browser)')}


# ---------------------------------------------------------------- 1. AI-answer panel: summary and report

def summarize(panel):
    """Per engine and overall: answers read, hotel named, link cited, average position when named, descriptions
    right / wrong, other hotels and OTAs named most."""
    if not panel or not panel.get('results') and not panel.get('not_run'):
        return None
    out = {'checked': panel.get('checked'), 'engines': {}, 'not_run': dict(panel.get('not_run') or {})}

    def agg(rs):
        named = [r for r in rs if r['named']]
        pos = [r['position'] for r in named if r.get('position')]
        judged = [r for r in named if r.get('description_correct') is not None]
        return {'answers': len(rs), 'named': len(named), 'cited': sum(1 for r in rs if r['cited']),
                'avg_position': round(sum(pos) / len(pos), 1) if pos else None,
                'described': len(judged), 'correct': sum(1 for r in judged if r['description_correct']),
                'named_pct': round(100 * len(named) / len(rs)) if rs else None}
    res = panel.get('results') or []
    for e in ENGINES:
        rs = [r for r in res if r['engine'] == e]
        if rs:
            out['engines'][e] = agg(rs)
    out['all'] = agg(res) if res else None
    comp = {}
    for r in res:
        for c in r.get('competitors') or []:
            comp[c] = comp.get(c, 0) + 1
    out['competitors'] = sorted(comp.items(), key=lambda kv: (-kv[1], kv[0]))[:8]
    out['errors'] = [{'engine': ENGINES[r['engine']], 'prompt': r['prompt'], 'error': e}
                     for r in res for e in r.get('errors') or []]
    return out


def _of(n, d):
    return '–' if d is None else f'{n} of {d}'


def _trend(cur, prev, key):
    """'▲ from 4 of 10' style line for a count out of answers, compared as a share."""
    if not prev or not prev.get('answers'):
        return {'text': 'not run last month', 'pill': 'grey'}
    c, p = cur[key] / cur['answers'], prev[key] / prev['answers']
    if abs(c - p) < 0.005:
        return {'text': f"same as last month ({_of(prev[key], prev['answers'])})", 'pill': 'grey'}
    up = c > p
    return {'text': f"{'▲' if up else '▼'} from {_of(prev[key], prev['answers'])}", 'pill': 'green' if up else 'red'}


def panel_components(cur_panel, prev_panel, mlabel):
    """Report components for page 03: a small table per engine with last month alongside, other names, errors."""
    cur, prev = summarize(cur_panel), summarize(prev_panel)
    title = 'What AI answers say when guests ask'
    if not cur:
        return [{'title': title, 'text': f'AI answer check: **not run** in {mlabel}. (The questions are asked in '
                                         'ChatGPT, Perplexity and Google in a browser; no numbers are shown for a '
                                         'month without a check.)'}], ['AI answer check not run this month']
    n_q = cur_panel.get('prompts_in_set') or len({r['id'] for r in cur_panel.get('results') or []})
    rows = []
    for e, lab in ENGINES.items():
        a = cur['engines'].get(e)
        if not a:
            why = cur['not_run'].get(e, 'not run')
            rows.append([lab, {'text': 'not run', 'pill': 'grey'}, '–', '–', '–', why])
            continue
        p = (prev or {}).get('engines', {}).get(e)
        rows.append([lab, _of(a['named'], a['answers']), _of(a['cited'], a['answers']),
                     '–' if a['avg_position'] is None else f"#{a['avg_position']:g}",
                     _of(a['correct'], a['described']) if a['described'] else '–',
                     _trend(a, p, 'named')])
    comps = [{'title': title,
              'text': f"The same {n_q} guest questions asked in each AI engine on {_day(cur['checked'])}: is the "
                      'hotel named, is its website linked, where it comes among the hotels named, and is the '
                      'description right.',
              'table': {'columns': ['AI engine', 'Hotel named', 'Website linked', 'Place among hotels named',
                                    'Description right', 'Named vs last month'],
                        'align': ['l', 'r', 'r', 'r', 'r', 'r'], 'rows': rows}}]
    if cur['competitors']:
        comps.append({'title': 'Also named in the answers',
                      'list': [f'{n} ({c} answer{"s" if c != 1 else ""})' for n, c in cur['competitors']]})
    if cur['errors']:
        comps.append({'title': 'Wrong facts about the hotel in the answers',
                      'list': [f"{x['engine']}, “{x['prompt']}”: {x['error']}" for x in cur['errors'][:8]]})
    comps.append({'note': f"A sample of answers on {_day(cur['checked'])}, not a ranking: AI answers change from one "
                          'person, day and wording to the next. The same questions are asked every month so the trend '
                          'means more than any single answer.'})
    return comps, []


def _day(d):
    try:
        dd = date.fromisoformat(str(d))
        return f'{dd.day} {_MON[dd.month - 1]} {dd.year}'
    except ValueError:
        return str(d)


def prev_month(month):
    y, m = map(int, month.split('-'))
    return f'{y - (m == 1)}-{12 if m == 1 else m - 1:02d}'


def load_panel(hotel_dir, month):
    f = hotel_dir / f'monthly-{month}' / 'manual.json'
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text(encoding='utf-8')).get('ai_panel')
    except ValueError:
        return None


# ---------------------------------------------------------------- 2. change readback

def page_type(url, host):
    from .audit import page_type as pt
    return pt(url if '//' in url else f'https://{host}{url if url.startswith("/") else "/" + url}', host)


def _key(url):
    p = urlparse(url).path if '//' in str(url) else str(url)
    p = (p or '/').split('#')[0].split('?')[0]
    return p.rstrip('/').lower() or '/'


def changed_pages(ctx, month):
    """[{page, date, what: [...], sources: [...]}]: execute changes and work-log rows with a URL, made in the
    READBACK_LOOKBACK_DAYS before the month's end; changes on one page on one day are one entry."""
    from . import group as grp
    from .monthly import _field_label, periods
    end = periods(month)['current'][1]
    start = end - timedelta(days=READBACK_LOOKBACK_DAYS)
    raw = []
    runs = list(ctx['hotel_dir'].glob('execute-*/changes.json'))
    if not ctx.get('single'):
        runs += list((ctx['group_dir'] / 'group').glob('execute-*/changes.json'))
    for f in runs:
        try:
            ch = json.loads(f.read_text(encoding='utf-8'))
        except ValueError:
            continue
        for c in ch if isinstance(ch, list) else []:
            page = c.get('page') or ''
            if not page:
                continue
            if f.parent.parent.name == 'group' and grp.hotel_for(page, ctx['reg']) != ctx['hotel']['slug']:
                continue
            raw.append({'page': page, 'date': (c.get('at') or '')[:10], 'what': _field_label(c.get('field')),
                        'source': 'execute'})
    log = ctx['hotel_dir'] / 'work-log.csv'
    if log.exists():
        with open(log, encoding='utf-8-sig', newline='') as fh:
            for r in csv.DictReader(fh):
                if (r.get('page') or '').strip():
                    raw.append({'page': r['page'].strip(), 'date': (r.get('date') or '')[:10],
                                'what': r.get('what') or 'Change logged by hand', 'source': 'work log'})
    return group_changes(raw, start, end, ctx['site'])


def group_changes(raw, start, end, site=''):
    out = {}
    for r in raw:
        try:
            d = date.fromisoformat(r['date'])
        except ValueError:
            continue
        if not (start <= d <= end):
            continue
        url = r['page'] if '//' in r['page'] else site.rstrip('/') + '/' + r['page'].lstrip('/')
        g = out.setdefault((_key(url), r['date']), {'page': url, 'date': r['date'], 'what': [], 'sources': []})
        if r['what'] not in g['what']:
            g['what'].append(r['what'])
        if r['source'] not in g['sources']:
            g['sources'].append(r['source'])
    return sorted(out.values(), key=lambda g: (g['date'], g['page']))


def _sum(rows):
    c = sum(r['clicks'] for r in rows)
    i = sum(r['impressions'] for r in rows)
    pos = sum(r['position'] * r['impressions'] for r in rows) / i if i else None
    return {'clicks': c, 'impressions': i, 'ctr_pct': round(100 * c / i, 2) if i else None,
            'position': round(pos, 1) if pos else None}


def _by_page(rows):
    out = {}
    for r in rows or []:
        out.setdefault(_key(r['keys'][0]), []).append(r)
    return out


def _pct(before, after):
    if not before:
        return None
    return round(100 * (after - before) / before, 1)


def windows(change_day, days):
    d = date.fromisoformat(change_day) if isinstance(change_day, str) else change_day
    return (d - timedelta(days=days), d - timedelta(days=1)), (d + timedelta(days=1), d + timedelta(days=days))


def judge(change, fetch, as_of, host, changed_keys, days=WINDOW_DAYS):
    """One change, one window length. fetch(start, end) -> Search Console rows by page."""
    (b0, b1), (a0, a1) = windows(change['date'], days)
    out = {'days': days, 'before': [str(b0), str(b1)], 'after': [str(a0), str(a1)]}
    if a1 > as_of:
        out.update(label='keep_testing', why=f'too early: the {days} days after the change end on {a1}, Search '
                                             f'Console has data to {as_of}')
        return out
    before, after = _by_page(fetch(b0, b1)), _by_page(fetch(a0, a1))
    k = _key(change['page'])
    pb, pa = _sum(before.get(k, [])), _sum(after.get(k, []))
    out['page'] = {'before': pb, 'after': pa}
    ptype = page_type(change['page'], host)
    out['page_type'] = ptype

    def ctrl(same_type):
        keys = {x for x in set(before) | set(after) if x not in changed_keys and
                (not same_type or page_type(x, host) == ptype)}
        return keys, _sum([r for x in keys for r in before.get(x, [])]), _sum([r for x in keys for r in after.get(x, [])])
    keys, cb, ca = ctrl(True)
    out['control_type'] = f'unchanged {ptype} pages'
    if len(keys) < MIN_CONTROL_PAGES or not cb['impressions']:
        keys, cb, ca = ctrl(False)
        out['control_type'] = 'all unchanged pages of the hotel'
    out['control'] = {'pages': len(keys), 'before': cb, 'after': ca}
    if pb['impressions'] < MIN_IMPRESSIONS or pa['impressions'] < MIN_IMPRESSIONS:
        out.update(label='keep_testing', why=f'too little data: fewer than {MIN_IMPRESSIONS} Google views before or '
                                             f'after ({pb["impressions"]} → {pa["impressions"]})')
        return out
    if len(keys) < MIN_CONTROL_PAGES or not cb['impressions']:
        out.update(label='unproven', why=f'not enough unchanged pages to compare with ({len(keys)})')
        return out
    metric = 'clicks' if pb['clicks'] >= MIN_CLICKS_FOR_CLICK_METRIC and cb['clicks'] else 'impressions'
    pp, cp = _pct(pb[metric], pa[metric]), _pct(cb[metric], ca[metric])
    gap = round(pp - cp, 1)
    word = 'clicks' if metric == 'clicks' else 'Google views'
    out.update(metric=metric, page_change_pct=pp, control_change_pct=cp, gap_points=gap)
    sign = (lambda v: f"{'+' if v > 0 else '−' if v < 0 else '±'}{abs(v):g}%")
    if gap >= GAP_POINTS:
        out.update(label='promote', why=f'{word} {sign(pp)} vs {sign(cp)} on similar pages: moved ahead of similar pages')
    elif gap <= -GAP_POINTS:
        out.update(label='rollback', why=f'{word} {sign(pp)} vs {sign(cp)} on similar pages: moved against similar '
                                         'pages')
    else:
        out.update(label='unproven', why=f'{word} {sign(pp)} vs {sign(cp)} on similar pages: moved with similar pages')
    return out


def readback(changes, fetch, as_of, host):
    """Every grouped change judged on 28 days, and on 56 when that much time has passed (the 56-day verdict is used
    then: more data)."""
    changed_keys = {_key(c['page']) for c in changes}
    items = []
    for c in changes:
        short = judge(c, fetch, as_of, host, changed_keys, WINDOW_DAYS)
        long_ = None
        if date.fromisoformat(c['date']) + timedelta(days=LONG_WINDOW_DAYS) <= as_of:
            long_ = judge(c, fetch, as_of, host, changed_keys, LONG_WINDOW_DAYS)
        use = long_ if long_ and long_['label'] != 'keep_testing' else short
        items.append({**c, 'path': urlparse(c['page']).path or c['page'], 'label': use['label'],
                      'label_text': LABELS[use['label']][0], 'why': use['why'], 'used_days': use['days'],
                      'windows': {str(WINDOW_DAYS): short, **({str(LONG_WINDOW_DAYS): long_} if long_ else {})}})
    return items


def collect_readback(ctx, month, today=None):
    """The readback block of data.json, from Search Console page rows under the hotel's paths."""
    prop = ctx['settings'].get('gsc_property')
    if not prop:
        return {'status': 'not available: no Search Console property'}
    changes = changed_pages(ctx, month)
    as_of = (today or date.today()) - timedelta(days=GSC_LAG_DAYS)
    base = {'as_of': str(as_of), 'constants': {
        'window_days': WINDOW_DAYS, 'long_window_days': LONG_WINDOW_DAYS, 'min_impressions': MIN_IMPRESSIONS,
        'min_clicks_for_click_metric': MIN_CLICKS_FOR_CLICK_METRIC, 'min_control_pages': MIN_CONTROL_PAGES,
        'gap_points': GAP_POINTS, 'lookback_days': READBACK_LOOKBACK_DAYS}}
    if not changes:
        return {'status': 'ok', **base, 'items': []}
    from .keyword_map import _gsc_rows
    cache = {}

    def fetch(s, e):
        if (s, e) not in cache:
            cache[(s, e)] = _gsc_rows(prop, s, e, ['page'], ctx['prefixes']) or []
        return cache[(s, e)]
    return {'status': 'ok', **base, 'items': readback(changes, fetch, as_of, ctx['host'])}


def readback_components(block):
    """Report components for page 04 (Work done)."""
    if not isinstance(block, dict) or block.get('status') != 'ok':
        reason = (block or {}).get('status', 'not collected') if isinstance(block, dict) else 'not collected'
        return [], [f'change readback {reason}']
    items = block.get('items') or []
    if not items:
        return [], []
    rows = []
    for it in sorted(items, key=lambda i: i['date'], reverse=True)[:15]:
        w = it['windows'][str(it['used_days'])]
        m = w.get('metric') or 'clicks'
        pg = w.get('page') or {}

        def ba(x):
            return '–' if not x else f"{x['before'][m]:,} → {x['after'][m]:,}"
        lab, pill = LABELS[it['label']]
        rows.append([it['path'], _short(it['date']), '; '.join(it['what']),
                     ba(pg) + ('' if not pg else f" {'clicks' if m == 'clicks' else 'views'}"),
                     '–' if w.get('control_change_pct') is None else
                     f"{'+' if w['control_change_pct'] > 0 else '−' if w['control_change_pct'] < 0 else '±'}"
                     f"{abs(w['control_change_pct']):g}% ({w['control']['pages']} pages)",
                     {'text': lab, 'pill': pill}])
    c = block.get('constants') or {}
    counts = {}
    for it in items:
        counts[it['label_text']] = counts.get(it['label_text'], 0) + 1
    return [{'title': 'Did each change move its page?',
             'text': 'Each changed page in Google search for the '
                     f"{c.get('window_days', WINDOW_DAYS)} days before and after the change "
                     f"({c.get('long_window_days', LONG_WINDOW_DAYS)} when that much time has passed), next to "
                     'unchanged pages of the same kind over the same days. ' +
                     ', '.join(f'{v} {k}' for k, v in sorted(counts.items())) + '.',
             'table': {'columns': ['Page', 'Changed', 'What', 'Before → after', 'Similar pages', 'Result'],
                       'align': ['l', 'l', 'l', 'r', 'r', 'l'], 'rows': rows}},
            {'note': f"Promote: moved ahead of similar pages by {c.get('gap_points', GAP_POINTS)}+ points. Rollback "
                     'candidate: moved against similar pages by as much. Unproven: moved with similar pages. Keep '
                     f"testing: too early, or under {c.get('min_impressions', MIN_IMPRESSIONS)} Google views. Season, "
                     'demand and Google updates move all pages; the comparison takes out part of that, but it does not '
                     f"prove the change caused the difference. Search Console data to {_short(block.get('as_of', ''))}."}], []


def _short(d):
    try:
        dd = date.fromisoformat(d)
        return f'{dd.day} {_MON[dd.month - 1]}'
    except ValueError:
        return d
