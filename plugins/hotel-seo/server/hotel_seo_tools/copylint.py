"""Copy lint: the text MetaHotels hands over to be pasted word for word (references/content-writing.md).

Detection only: nothing is rewritten automatically. `copy_report` splits the results into
  problems   fix before the copy goes out (over-long titles / metas, a title wider than Google shows,
             prices in FAQ answers, banned button text, "image of" alt text, stock openings, em dashes,
             unsourced superlatives, invisible characters, a cluster of AI tells)
  warnings   look and decide (a single AI tell, a section opening on a bare pronoun, a first sentence
             that repeats its heading, alt text issues, time-sensitive words, mixed or wrong size units,
             the main phrase missing from a prominent place or repeated in the intro)
  lengths    every title / meta / alt with its count ("58/60 chars, 512/580 px") for the hand-over.
`lint_copy(doc)` keeps the old flat list (problems, then warnings marked "(warning)").
"""
import re
import unicodedata

# ---------------------------------------------------------------- patterns (existing)

# Stock openings (content-writing.md section 4): checked at the start of each paste block
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

# ---------------------------------------------------------------- AI tells, by category

# Hotel-copy AI tells (content-writing.md section 4). One hit is a warning; a cluster in one section is a problem.
_SENTENCE_START = r'(?:^|(?<=[.!?]\s)|(?<=[.!?]\*\*\s)|(?<=\|\s))'
AI_TELL_CATEGORIES = {
    'transition': re.compile(_SENTENCE_START + r'(?:moreover|furthermore|additionally|that said|'
                             r'notably|importantly)\b', re.I | re.M),
    'filler': re.compile(r"\bit(?: is|'s) (?:worth noting|important to note|worth mentioning)\b|\blet'?s dive\b|"
                         r"\bdive into\b|\bin conclusion\b|\bto summari[sz]e\b|\bin summary\b|\bthis (?:article|post|"
                         r"guide) will\b|\bi hope this helps\b|\bneedless to say\b|\bat the end of the day\b|"
                         r"\bthis matters\b", re.I),
    'inflated_verb': re.compile(r'\butili[sz](?:e[sd]?|ing)\b|\bfacilitat\w*|\bleverag\w*|\belevate[sd]?\b|'
                                r'\benhanc\w*|\bembark\b|\bindulge\b|\bdelve\b|\bunlock\w*|\bfoster\w*|'
                                r'\bempower\w*|\bstreamlin\w*|\bshowcas\w*|\bunderscor\w*', re.I),
    'inflated_adjective': re.compile(r'\bcomprehensive\b|\bpivotal\b|\bseamless(?:ly)?\b|\bnestled\b|\bboasts?\b|'
                                     r'\bvibrant\b|\bunparalleled\b|\bunforgettable\b|\bgame-changing\b|'
                                     r'\binnovative\b|\bholistic\b|\brobust\b|\bbustling\b|\bbreathtaking\b|'
                                     r'\bmeticulous(?:ly)?\b|\bever-evolving\b', re.I),
    'cliche': re.compile(r'\bin the heart of\b|\boasis\b|\bhaven\b|\btapestry\b|\btestament\b|\bcurated\b|'
                         r'\bluxurious retreat\b|\bperfect blend\b|\bsecond to none\b|\bhidden gem\b|'
                         r'\bunique blend\b|\bthe perfect (?:base|choice|getaway)\b', re.I),
    'construction': re.compile(r"\bwhether you'?re\b|\bnot just\b[^.]{1,60}\bbut\b|"
                               r"\brather than (?:simply|merely|just)\b|\b(?:serves|stands) as\b", re.I),
}
AI_TELLS = re.compile('|'.join(f'(?:{rx.pattern})' for rx in AI_TELL_CATEGORIES.values()), re.I | re.M)
AI_TELL_PROBLEM_CATEGORIES = 3      # this many different categories in one section -> problem
AI_TELL_PROBLEM_HITS = 6            # or this many hits in one section -> problem

# ---------------------------------------------------------------- new rules

TITLE_TARGET_CHARS = 60             # the write standard (content-writing.md section 3); problem above LIMITS (62)
TITLE_MAX_PX = 580                  # Google's desktop title width, Arial ~20px; Latin script only
META_MAX_CHARS = 155
ALT_MAX_CHARS = 125                 # screen readers stop around here
HEADING_ECHO_RATIO = 0.7            # share of the first sentence's content words that are in its heading
MAIN_PHRASE_MAX_IN_INTRO = 2        # 3+ uses of the main phrase in the intro -> warning

BANNED_BUTTONS = {'read more', 'click here', 'view more', 'learn more', 'submit', 'see more', 'more', 'click',
                  'here', 'more info', 'details'}
ALT_GENERIC_START = re.compile(r'^\s*(?:an? )?(?:image|photo|picture|photograph|pic|graphic) (?:of|showing)\b', re.I)
PRICE = re.compile(r'\b(?:AED|USD|EUR|GBP|SAR|QAR|OMR|INR|Dhs?|dirhams?)\b|درهم|[$€£₹]\s?\d|'
                   # a percentage only when it is a discount ("20% off", "save 15%"), not "100% non-smoking"
                   r'(?:\bsave\s+(?:up\s+to\s+)?|\bup\s+to\s+)\d+\s?%|\d+\s?%\s*(?:off|discount|savings?|cheaper|less)\b|'
                   r'\bfrom\s+\d[\d,]*(?![\d,])(?!\s*(?:[:.]\d|a\.?m\b|p\.?m\b|hours?|hrs?\b|h\b|minutes?|mins?\b|'
                   r'km\b|kilomet|met(?:re|er)s?\b|m\b|miles?\b|years?\b|yrs?\b|months?\b|weeks?\b|days?\b|'
                   r'nights?\b|guests?\b|people\b|persons?\b|adults?\b|child|kids?\b|floors?\b|rooms?\b|beds?\b|'
                   r'sq|m²|st\b|nd\b|rd\b|th\b|to\s+\d|-\s*\d|–\s*\d|'
                   r'(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b))', re.I)
TIME_SENSITIVE = re.compile(r'\b(?:currently|this (?:year|season|summer|winter|month)|next year|last year|'
                            r'newly (?:opened|renovated|launched)|recently|brand[- ]new|just opened|now open|'
                            r'coming soon)\b|\b20\d{2}\b(?!\s*(?:sq|m²|m2|aed|dhs?|km))', re.I)
SIZE_SQM = re.compile(r'\d[\d,.]*\s*(?:m²|m2\b|sqm\b|sq\.?\s?m\b|sq\.? met(?:re|er)s?|square met(?:re|er)s?)|متر مربع|م²',
                      re.I)
SIZE_SQFT = re.compile(r'\d[\d,.]*\s*(?:sq\.?\s?ft\b|sqft\b|ft²|square f(?:ee|oo)t)|قدم مربع', re.I)
BARE_PRONOUN = re.compile(r"^(?:it|its|it's|they|their|they're|them)\b|"
                          r"^(?:this|these|those|that)(?=\s*[,.;:!?]|\s*$|\s+(?:is|are|was|were|has|have|had|"
                          r"offers?|includes?|makes?|means|can|will|lets|gives|provides?|features?|sits|puts|"
                          r"comes?|keeps?|brings?)\b)", re.I)
ARABIC = re.compile('[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]')
STOPWORDS = set('''a an the and or but of in on at to for from with by as is are was were be been being it its this
that these those our your their we you they there here into onto over under near than then so such very
can will would should may might must has have had do does did not no all any each every more most some
also just only about after before during per via up out off what which who whom whose when where why how
your yours ours'''.split())

# Arial advance widths (1/1000 em); x 20px / 1000 = SERP pixels. Unknown glyphs count as 556 (a digit).
_W = {' ': 278, '!': 278, '"': 355, '#': 556, '$': 556, '%': 889, '&': 667, "'": 191, '(': 333, ')': 333,
      '*': 389, '+': 584, ',': 278, '-': 333, '.': 278, '/': 278, ':': 278, ';': 278, '<': 584, '=': 584,
      '>': 584, '?': 556, '@': 1015, '[': 278, '\\': 278, ']': 278, '^': 469, '_': 556, '`': 333, '{': 334,
      '|': 260, '}': 334, '~': 584, '–': 556, '—': 1000, '‘': 222, '’': 222, '“': 333, '”': 333, '·': 278,
      '•': 350, '…': 1000, '²': 333, '€': 556, '£': 556, '®': 737, '©': 737, '™': 1000}
_W.update({d: 556 for d in '0123456789'})
_W.update(dict(zip('ABCDEFGHIJKLMNOPQRSTUVWXYZ',
                   (667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778, 667, 778, 722, 667,
                    611, 722, 667, 944, 667, 667, 611))))
_W.update(dict(zip('abcdefghijklmnopqrstuvwxyz',
                   (556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556, 556, 556, 333, 500,
                    278, 556, 500, 722, 500, 500, 500))))
TITLE_FONT_PX = 20


def title_px(text):
    """Width of a title in Google's results (Arial ~20px), rounded. Accented letters count as their base letter."""
    total = 0
    for ch in str(text):
        w = _W.get(ch)
        if w is None:
            base = unicodedata.normalize('NFKD', ch)[:1]
            w = _W.get(base, 556)
        total += w
    return round(total * TITLE_FONT_PX / 1000)


def _plain(cell):
    return re.sub(r'\[CONFIRM[^\]]*\]|`|\*\*|\*', '', str(cell)).strip()


def _strip_md(line):
    return re.sub(r'^\s*(?:#{1,6}\s+|[-*+]\s+|\d+[.)]\s+|>\s*)', '', _plain(line)).strip()


def _sentences(text):
    text = re.sub(r'\s+', ' ', _plain(text)).strip()
    return [x for x in re.split(r'(?<=[.!?])\s+(?=["“(\'A-Z0-9؀-ۿ])', text) if x]


def _content_words(text):
    out = set()
    for w in re.findall(r"[a-z0-9؀-ۿ]+", text.lower()):
        if w in STOPWORDS or (len(w) < 3 and not w.isdigit()):
            continue
        out.add(w[:-1] if len(w) > 3 and w.endswith('s') and not w.endswith('ss') else w)
    return out


def _snip(t, m, pad=30):
    return t[max(0, m.start() - pad):m.end() + pad].strip()


# ---------------------------------------------------------------- units

KINDS = (('title', re.compile(r'title', re.I)), ('meta', re.compile(r'meta', re.I)),
         ('h1', re.compile(r'\bh1\b', re.I)), ('heading', re.compile(r'\bh[2-6]\b|heading', re.I)),
         ('alt', re.compile(r'\balt\b', re.I)), ('button', re.compile(r'button|\bcta\b|link text', re.I)),
         ('faq_answer', re.compile(r'\banswer\b', re.I)), ('faq_question', re.compile(r'\bquestion\b', re.I)))
COPY_KINDS = {'title', 'meta', 'h1', 'heading', 'alt', 'button', 'faq_answer', 'copy'}
_BUTTON_NOTE = re.compile(r'^\s*\*\*\s*(?:booking )?(?:button|cta)\s*:?\s*\*\*\s*:?\s*(.+)$', re.I | re.S)
_FAQ_CONTEXT = re.compile(r'\bfaqs?\b|frequently asked|guest questions', re.I)


def _kind(label):
    label = _plain(label)
    if not label or len(label) > 40:
        return None
    for k, rx in KINDS:
        if rx.search(label):
            return k
    return None


def units_from_doc(doc):
    """(section name, section, units, generic texts) per section. A unit is {kind, text}; kinds are title, meta,
    h1, heading, alt, button, faq_answer, faq_question (table columns or row labels, a "Booking button" note) and
    copy (a paste block). Generic texts are every paragraph, paste block and table row the old lint read."""
    for s in doc.get('sections', []):
        if s.get('chapter') or s.get('generated') or s.get('code_data'):
            continue                     # chapter headings, generated scores and our own data tables
        name = f"{s.get('number', '')} {s.get('title', '')}".strip()
        units, texts, h3 = [], [], ''
        faq_section = bool(_FAQ_CONTEXT.search(str(s.get('title', ''))))
        for b in s.get('blocks', []):
            (kind, val), = b.items()
            if kind == 'h3':
                h3 = str(val)
            elif kind in ('paste', 'p'):
                texts.append(str(val))
                if kind == 'paste':
                    units.append({'kind': 'copy', 'text': str(val),
                                  'faq': faq_section or bool(_FAQ_CONTEXT.search(h3))})
            elif kind == 'note':
                m = _BUTTON_NOTE.match(str(val))
                if m:
                    units.append({'kind': 'button', 'text': _plain(m.group(1))})
            elif kind == 'table':
                cols = [str(c) for c in val.get('columns', [])]
                keep = [i for i, c in enumerate(cols) if not QUOTED_COLUMNS.search(c)] or list(range(len(cols)))
                col_kind = {i: _kind(cols[i]) for i in keep if i < len(cols)}
                label_col = 0 in keep and 0 < len(cols) and not col_kind.get(0)
                for row in val.get('rows', []):
                    texts.append(' | '.join(str(row[i]) for i in keep if i < len(row)))
                    row_kind = _kind(row[0]) if label_col and row else None
                    for i in keep:
                        if i >= len(row) or i >= len(cols):
                            continue
                        k = col_kind.get(i) or (row_kind if i != 0 else None)
                        cell = _plain(row[i])
                        if not k or not cell or cell.lower().startswith('keep'):
                            continue
                        units.append({'kind': k, 'text': cell, 'label': cols[i] if col_kind.get(i) else row[0]})
        yield name, s, units, texts


def _parse_copy(text, faq):
    """A paste block as items: ('heading'|'question'|'answer'|'para', text)."""
    items, in_faq = [], faq
    for raw in re.split(r'\n\s*\n|\n(?=\s*(?:#{1,6}\s|\*\*[^*]+\*\*\s*$|Q:|A:|Question:|Answer:))', str(text), flags=re.M):
        lines = [x for x in raw.split('\n') if x.strip()]
        if not lines:
            continue
        first = lines[0].strip()
        rest = ' '.join(x.strip() for x in lines[1:])
        is_heading = bool(re.match(r'#{1,6}\s', first)) or bool(re.fullmatch(r'\*\*[^*]+\*\*', first))
        q = re.match(r'(?:Q|Question)\s*[:.]\s*(.+)', _plain(first), re.I)
        a = re.match(r'(?:A|Answer)\s*[:.]\s*(.+)', _plain(first), re.I)
        if is_heading and _FAQ_CONTEXT.search(first) and not first.rstrip('*').endswith('?'):
            in_faq = True
        if q or (in_faq and _strip_md(first).endswith('?')):
            items.append(('question', q.group(1) if q else _strip_md(first)))
            if rest:
                items.append(('answer', rest))
        elif a:
            items.append(('answer', (a.group(1) + ' ' + rest).strip()))
        elif is_heading:
            items.append(('heading', _strip_md(first)))
            if rest:
                items.append(('para', rest))
        else:
            items.append(('answer' if items and items[-1][0] == 'question' else 'para',
                          _strip_md(first) + (' ' + rest if rest else '')))
    return items


def _intro(items):
    out = []
    for k, t in items:
        if k in ('heading', 'question'):
            break
        out.append(t)
    return ' '.join(out)


# ---------------------------------------------------------------- the report

def _hotel_tokens(name):
    words = _content_words(name or '') - {'hotel', 'resort', 'apartment', 'suite', 'tower', 'spa', 'dubai',
                                          'sharjah', 'fujairah', 'ajman', 'abu', 'dhabi', 'group'}
    return words


def check_units(sections, hotel_name='', main_phrase='', units_pref=''):
    """sections: [(name, units, texts, main_phrase)] -> {'problems', 'warnings', 'lengths'}."""
    problems, warnings, lengths = [], [], []
    alts_seen = {}
    hotel_tok = _hotel_tokens(hotel_name) if hotel_name and not str(hotel_name).strip().lower().endswith('group') \
        else set()
    pref = ''
    if units_pref:
        pref = 'sqft' if re.search(r'ft|feet|foot', str(units_pref), re.I) else 'sqm'

    for name, units, texts, phrase in sections:
        phrase = phrase or main_phrase
        copy_texts = []
        h1s = [u['text'] for u in units if u['kind'] == 'h1']
        first_copy = True
        for u in units:
            k, t = u['kind'], str(u['text'])
            if k in COPY_KINDS:
                copy_texts.append(t)
            cell = _plain(t)
            arabic = bool(ARABIC.search(cell))
            if k == 'title':
                n, px = len(cell), (None if arabic else title_px(cell))
                lengths.append({'where': name, 'unit': 'title', 'text': cell, 'chars': n,
                                'max_chars': TITLE_TARGET_CHARS, 'px': px, 'max_px': None if arabic else TITLE_MAX_PX,
                                'count': f'{n}/{TITLE_TARGET_CHARS}' + ('' if arabic else f', {px}/{TITLE_MAX_PX} px')})
                if n > LIMITS[0][1]:
                    problems.append(f'{name}: title is {n} characters (max {LIMITS[0][1]}): "{cell[:70]}"')
                elif px is not None and px > TITLE_MAX_PX:
                    problems.append(f'{name}: title is {px}px wide (Google shows about {TITLE_MAX_PX}px; '
                                    f'{n} characters but wide letters): "{cell[:70]}"')
            elif k == 'meta':
                n = len(cell)
                lengths.append({'where': name, 'unit': 'meta', 'text': cell, 'chars': n, 'max_chars': META_MAX_CHARS,
                                'count': f'{n}/{META_MAX_CHARS}'})
                if n > LIMITS[1][1]:
                    problems.append(f'{name}: meta description is {n} characters (max {LIMITS[1][1]}): "{cell[:70]}"')
            elif k == 'alt':
                n = len(cell)
                lengths.append({'where': name, 'unit': 'alt', 'text': cell, 'chars': n, 'max_chars': ALT_MAX_CHARS,
                                'count': f'{n}/{ALT_MAX_CHARS}'})
                if ALT_GENERIC_START.search(cell):
                    problems.append(f'{name}: alt text starts "{ALT_GENERIC_START.search(cell).group(0).strip()}" '
                                    f'(say what is in the photo): "{cell[:70]}"')
                if n > ALT_MAX_CHARS:
                    warnings.append(f'{name}: alt text is {n} characters (keep it under {ALT_MAX_CHARS}): "{cell[:70]}"')
                key = re.sub(r'\W+', ' ', cell.lower()).strip()
                if key in alts_seen:
                    warnings.append(f'{name}: same alt text as {alts_seen[key]} (each image needs its own): '
                                    f'"{cell[:70]}"')
                else:
                    alts_seen[key] = name
                if hotel_tok and not arabic and not hotel_tok <= _content_words(cell):
                    warnings.append(f'{name}: alt text without the hotel name ({hotel_name}): "{cell[:70]}"')
            elif k == 'button':
                if re.sub(r'[^a-z ]+', '', cell.lower()).strip() in BANNED_BUTTONS:
                    problems.append(f'{name}: button text "{cell}" says nothing about where it goes '
                                    '(e.g. "View Deluxe King Room", "Check availability")')
            elif k == 'faq_answer':
                m = PRICE.search(cell)
                if m:
                    problems.append(f'{name}: FAQ answer with a price "{m.group(0).strip()}" (prices change: link to '
                                    f'the offer or booking page instead): "{_snip(cell, m)}"')
                first = (_sentences(cell) or [''])[0]
                if BARE_PRONOUN.search(first):
                    warnings.append(f'{name}: FAQ answer starts with "{first.split()[0]}" (name the hotel or room '
                                    f'so it reads alone): "{first[:70]}"')
            elif k == 'copy':
                if STOCK_OPENING.search(t):
                    problems.append(f'{name}: stock opening "{t[:50]}" (start with the answer or a fact)')
                if '—' in t:
                    problems.append(f'{name}: em dash in paste copy "{t[:50]}" (use a colon, comma or full stop)')
                items = _parse_copy(t, u.get('faq'))
                prev = ('heading', h1s[0]) if first_copy and len(h1s) == 1 else None
                for i, (ik, it) in enumerate(items):
                    if ik == 'answer':
                        m = PRICE.search(it)
                        if m:
                            problems.append(f'{name}: FAQ answer with a price "{m.group(0).strip()}" (prices change: '
                                            f'link to the offer or booking page instead): "{_snip(it, m)}"')
                    if ik in ('para', 'answer') and (i == 0 or items[i - 1][0] in ('heading', 'question')):
                        first = (_sentences(it) or [''])[0]
                        if BARE_PRONOUN.search(first):
                            warnings.append(f'{name}: section starts with "{first.split()[0]}" (name the hotel or '
                                            f'room so it reads alone when quoted): "{first[:70]}"')
                        head = items[i - 1][1] if i and items[i - 1][0] == 'heading' else (
                            prev[1] if i == 0 and prev else '')
                        if head and not ARABIC.search(first):
                            sw, hw = _content_words(first), _content_words(head)
                            if len(sw) >= 2 and len(hw) >= 2 and len(sw & hw) / len(sw) > HEADING_ECHO_RATIO:
                                warnings.append(f'{name}: first sentence repeats its heading "{_plain(head)[:50]}" '
                                                f'(open with a fact instead): "{first[:70]}"')
                first_copy = False

        # time-sensitive words and size units, in the copy only (not our notes to the agency)
        for t in copy_texts:
            for m in TIME_SENSITIVE.finditer(_plain(t)):
                warnings.append(f'{name}: "{m.group(0)}" will date (state the fact without the time word, or '
                                f'give the date): "{_snip(_plain(t), m)}"')
        joined = ' '.join(_plain(t) for t in copy_texts)
        sqm, sqft = SIZE_SQM.search(joined), SIZE_SQFT.search(joined)
        if sqm and sqft:
            warnings.append(f'{name}: room sizes in both m² and sq ft ("{sqm.group(0)}", "{sqft.group(0)}"): '
                            'use one unit everywhere')
        elif pref and (sqft if pref == 'sqm' else sqm):
            m = sqft if pref == 'sqm' else sqm
            warnings.append(f'{name}: size "{m.group(0)}" is not in this hotel\'s unit ({units_pref}, hotel.json '
                            'preferences.units)')

        # main phrase: once in the title, H1 and first two sentences; never stuffed into the intro
        if phrase:
            want = _content_words(phrase)
            titles = [u['text'] for u in units if u['kind'] == 'title']
            copies = [u for u in units if u['kind'] == 'copy']
            intro = _intro(_parse_copy(copies[0]['text'], copies[0].get('faq'))) if copies else ''
            places = (('title', titles), ('H1', h1s), ('first two sentences', [' '.join(_sentences(intro)[:2])]
                                                      if intro else []))
            for label, vals in places:
                if vals and not any(want <= _content_words(v) for v in vals):
                    warnings.append(f'{name}: main phrase "{phrase}" is not in the {label}')
            uses = len(re.findall(r'\b' + r'\s+'.join(map(re.escape, phrase.lower().split())) + r'\b',
                                  _plain(intro).lower()))
            if uses > MAIN_PHRASE_MAX_IN_INTRO:
                warnings.append(f'{name}: main phrase "{phrase}" is used {uses} times in the intro (once reads '
                                'naturally)')

        # superlatives, AI tells (by category), invisible characters: every text, as before
        tell_hits = {}
        for t in texts + [u['text'] for u in units if u.get('from_tool')]:
            for m in SUPERLATIVE.finditer(t):
                problems.append(f'{name}: superlative "{m.group(0)}" needs a source on file, or cut it: '
                                f'"{_snip(t, m)}"')
            for cat, rx in AI_TELL_CATEGORIES.items():
                for m in rx.finditer(t):
                    tell_hits.setdefault(cat, []).append(m.group(0))
                    warnings.append(f'{name}: AI tell "{m.group(0)}" in "{_snip(t, m)}"')
            h = HIDDEN.search(t)
            if h:
                problems.append(f'{name}: invisible character U+{ord(h.group(0)):04X} in "{t[:60]}"')
        total = sum(len(v) for v in tell_hits.values())
        if len(tell_hits) >= AI_TELL_PROBLEM_CATEGORIES or total >= AI_TELL_PROBLEM_HITS:
            problems.append(f'{name}: reads as AI-written ({total} tells in {len(tell_hits)} kinds: '
                            + '; '.join(f"{c.replace('_', ' ')}: {', '.join(sorted(set(v)))}"
                                        for c, v in sorted(tell_hits.items()))
                            + '): rewrite the section plainly with facts')
    return {'problems': problems, 'warnings': warnings, 'lengths': lengths}


def copy_report(doc, hotel_name=None, main_phrase='', units_pref=''):
    """The report for a list / Build Plan JSON. hotel_name defaults to doc["hotel"]; a section's own
    "main_phrase" (or the doc's) wins over main_phrase."""
    secs = [(name, units, texts, s.get('main_phrase') or doc.get('main_phrase') or '')
            for name, s, units, texts in units_from_doc(doc)]
    return check_units(secs, doc.get('hotel', '') if hotel_name is None else hotel_name, main_phrase, units_pref)


def report_units(units, hotel_name='', main_phrase='', units_pref=''):
    """The report for loose units (write mode): [{"kind": "title"|"meta"|"h1"|"heading"|"alt"|"button"|
    "faq_answer"|"copy", "text": "...", "where": "<page>"}]. Units with the same "where" are one section."""
    groups = {}
    for u in units or []:
        k = str(u.get('kind', 'copy')).lower().replace(' ', '_')
        k = {'intro': 'copy', 'body': 'copy', 'paste': 'copy', 'description': 'meta', 'meta_description': 'meta',
             'seo_title': 'title', 'h2': 'heading', 'h3': 'heading', 'alt_text': 'alt', 'faq': 'faq_answer',
             'answer': 'faq_answer', 'cta': 'button'}.get(k, k)
        groups.setdefault(str(u.get('where') or ''), []).append(
            {'kind': k, 'text': str(u.get('text', '')), 'from_tool': True, 'faq': k == 'copy' and bool(u.get('faq'))})
    secs = [(where or 'copy', us, [], '') for where, us in groups.items()]
    return check_units(secs, hotel_name, main_phrase, units_pref)


def lint_copy(doc, hotel_name=None, main_phrase='', units_pref=''):
    """Flat list, as before: problems first, then warnings marked "(warning)". Capped at 60 lines."""
    r = copy_report(doc, hotel_name, main_phrase, units_pref)
    return (r['problems'] + ['(warning) ' + w for w in r['warnings']])[:60]
