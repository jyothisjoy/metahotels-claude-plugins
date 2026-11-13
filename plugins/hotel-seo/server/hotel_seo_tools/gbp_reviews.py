"""Google review replies for a hotel's Business Profile, drafted by Claude and sent only after the user approves.

  pending(group_dir, slug, location, since_days)   reviews that need a reply, written as a drafts file
                                                   (<hotel dir>/gbp/review-replies-<date>.json / .md) for Claude to
                                                   fill: one "reply" per review, in the review's language
  check_drafts(file)                               lint every reply (problems block sending) and, when clean, the
                                                   `changes` dict for gbp_propose ({"review_replies": [...]})
  lint_reply(reply, review, ...)                   the checks for one reply

Needs a reply: no reply yet, or the guest edited the review after the hotel replied. since_days > 0 keeps only reviews
written or edited in the last since_days days. Sending is gbp_write's two steps: propose (change id) -> the user
approves that id -> apply. Nothing here sends anything.
"""
import json
import re
from datetime import date, timedelta

from . import copylint, gbp, group as grp, paths
from .gbp_write import DEAL

REPLY_MAX_CHARS = 600            # Google allows 4096; a reply guests read is 2-4 sentences (content-writing.md)
COMPLAINT_MAX_STARS = 2          # 1-2 stars: apology + offline contact required, shown to the user first
MIXED_STARS = 3                  # 3 stars: apology / contact recommended (warning)
NAME_MAX_USES = 1                # the hotel name at most once (keyword stuffing)
ANON_NAMES = {'a google user', 'google user', 'anonymous', ''}

LATIN = re.compile(r'[A-Za-zÀ-ɏ]')
LETTER = re.compile(r'[^\W\d_]')
EMAIL = re.compile(r'[\w.+-]+@[\w-]+(?:\.[\w-]+)+')
PHONE = re.compile(r'(?<![\w/])\+?\d[\d\s().-]{6,}\d(?![\w/])')
URL = re.compile(r'https?://|\bwww\.|(?<![@\w.-])[\w-]+\.(?:com|ae|net|org|info|hotel)\b', re.I)
# gbp_write.DEAL (Google's hotel posts policy) catches offers and deals; this adds codes, vouchers and upgrades
OFFER = re.compile(r'\b(?:coupon|voucher|discount\w*|promo\w*|(?<!dress )code|free (?:night|stay)|'
                   r'(?:free|complimentary|room) upgrades?|upgrade you|special (?:rate|price)|best (?:rate|price))\b|'
                   r'كوبون|قسيمة|رمز|ترقية مجانية', re.I)
MONTH = (r'(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|'
         r'oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)')
BOOKING_DETAIL = re.compile(
    r'\b(?:booking|reservation|confirmation|folio|invoice|res)\s*(?:no\.?|number|#|id|ref(?:erence)?)\s*[:#]?\s*'
    r'[A-Z0-9-]*\d[A-Z0-9-]*|\broom\s*(?:no\.?|number|#)?\s*\d{2,5}\b|\b(?:credit card|card ending|passport|'
    r'emirates id|visa number)\b|\b\d{1,2}(?:st|nd|rd|th)?\s+' + MONTH + r'\b|\b' + MONTH + r'\s+\d{1,2}(?:st|nd|rd|th)?\b|'
    r'رقم الحجز|رقم الغرفة|بطاقة الائتمان|جواز السفر', re.I)
ARGUE = re.compile(r"\b(?:not true|untrue|you are wrong|you're wrong|false (?:claim|review)|you failed to|you should "
                   r"have|you did not (?:read|follow)|contrary to (?:what you|your)|as you were (?:told|informed)|"
                   r"that is incorrect|your claim|fake review|our records show|our records indicate)\b|"
                   r'غير صحيح|ادعاء', re.I)
APOLOGY = re.compile(r'\b(?:sorry|apolog\w*|regret)\b|نعتذر|نأسف|آسف|اعتذار|عذرا|عذراً', re.I)
REPLY_TELLS = re.compile(r'\bdear (?:valued )?guest\b|\bvalued guest\b|\bwe are (?:thrilled|delighted|elated)\b|'
                         r'\brest assured\b|\byour feedback is (?:invaluable|greatly appreciated|important to us)\b|'
                         r'\bwe strive\b|\bthank you for choosing\b|\bwe take (?:your )?feedback seriously\b|'
                         r'\bplease do not hesitate\b|\bdon\'t hesitate\b|\bat your earliest convenience\b|'
                         r'\bwe pride ourselves\b|\bwonderful (?:experience|stay) with us\b', re.I)
STUFF = re.compile(r'\b(?:best|top|cheap|luxury|affordable|budget)\s+(?:\w+\s+)?hotels?\s+(?:in|near)\b|'
                   r'\bhotels?\s+(?:in|near)\s+\w+', re.I)
RULES = [
    f'One reply per review, in the review\'s language: an Arabic review gets an Arabic reply written in Arabic '
    f'(not a translation of an English draft); other languages: English unless the user says otherwise.',
    'Hotel voice (references/content-writing.md, <hotel dir>/voice.md): 2-4 plain sentences, no stock openings, '
    'no AI tells ("valued guest", "rest assured", "we strive").',
    'Thank the guest by first name only, and only when the review shows one (first_name); never the surname.',
    'Answer the specific point the guest made (what they liked, what went wrong).',
    'No prices, offers, discounts, upgrades or codes; no links; no personal data or booking details (booking or '
    'room numbers, stay dates, payment).',
    'Never argue or correct the guest. A complaint (1-2 stars) gets an apology and an offline contact: only the '
    'hotel email / phone listed under "contacts" (confirmed facts), nothing else.',
    f'At most {REPLY_MAX_CHARS} characters; the hotel name at most once; no "hotel in <city>" phrases.',
    'Facts only from the site, hotel-facts.json or the booking engine; no [CONFIRM] left in a reply.',
    'Set "skip": true on a review the user doesn\'t want answered now.',
]


# ---------------------------------------------------------------- reading reviews

def _split_comment(c):
    """(original, google_translation). Google writes "(Translated by Google) ... (Original) ..." or the reverse."""
    c = (c or '').strip()
    if '(Original)' in c:
        before, after = c.split('(Original)', 1)
        return after.strip(), before.replace('(Translated by Google)', '').strip()
    if '(Translated by Google)' in c:
        before, after = c.split('(Translated by Google)', 1)
        return before.strip(), after.strip()
    return c, ''


def language(text):
    """'ar', 'en' (Latin script; also the default for a stars-only review) or 'other'."""
    letters = LETTER.findall(text or '')
    if not letters:
        return 'en'
    ar = len(copylint.ARABIC.findall(text))
    if ar / len(letters) >= 0.4:
        return 'ar'
    return 'en' if len(LATIN.findall(text)) / len(letters) >= 0.6 else 'other'


def _first_name(reviewer):
    name = str((reviewer or {}).get('displayName') or '').strip()
    if (reviewer or {}).get('isAnonymous') or name.lower() in ANON_NAMES:
        return '', name
    first = name.split()[0] if name.split() else ''
    # initials ("J.") or a handle with digits is not a name to thank someone by
    return ('' if len(first.rstrip('.')) < 2 or re.search(r'\d', first) else first.title()), name


def _row(r):
    reply = r.get('reviewReply') or {}
    original, translated = _split_comment(r.get('comment'))
    first, display = _first_name(r.get('reviewer'))
    stars = gbp.STARS.get(r.get('starRating'))
    return {'review_id': r.get('reviewId', ''), 'stars': stars, 'date': (r.get('createTime') or '')[:10],
            'updated': (r.get('updateTime') or '')[:10], 'reviewer': display, 'first_name': first,
            'language': language(original), 'comment': original[:2000], 'comment_translated': translated[:2000],
            'existing_reply': (reply.get('comment') or '')[:2000], 'existing_reply_date': (reply.get('updateTime') or '')[:10],
            'check_with_user_first': bool(stars and stars <= COMPLAINT_MAX_STARS), 'reply': ''}


def select_pending(raw, since_days=0, today=None):
    """Reviews (raw v4 review objects) that need a reply, newest first."""
    today = today or date.today()
    cutoff = (today - timedelta(days=int(since_days))).isoformat() if since_days else ''
    out = []
    for r in raw:
        reply = r.get('reviewReply') or {}
        if not (reply.get('comment') or '').strip():
            why = 'no reply'
        elif (r.get('updateTime') or '')[:10] > (reply.get('updateTime') or '~')[:10]:   # a later day, not the reply's own bump
            why = 'the guest edited the review after the reply'
        else:
            continue
        if cutoff and max((r.get('createTime') or '')[:10], (r.get('updateTime') or '')[:10]) < cutoff:
            continue
        out.append(dict(_row(r), reason=why))
    out.sort(key=lambda x: max(x['date'], x['updated']), reverse=True)
    return out


def _fetch(account, location, limit=200):
    """Raw reviews from the Google My Business API (v4), newest first."""
    url = f'{gbp.V4}/{account}/{location}/reviews'
    params, out = {'pageSize': 50, 'orderBy': 'updateTime desc'}, []
    while len(out) < limit:
        data = gbp._get(url, params)
        out += data.get('reviews', [])
        if not data.get('nextPageToken'):
            break
        params['pageToken'] = data['nextPageToken']
    return out[:limit]


# ---------------------------------------------------------------- hotel context

def contacts(facts_file):
    """Email addresses and phone numbers in confirmed facts (hotel-facts.json): the only contacts a reply may give."""
    f = paths.resolve(facts_file) if facts_file else None
    if not f or not f.exists():
        return {'email': [], 'phone': []}
    from .facts import is_confirmed_source
    try:
        rows = json.loads(f.read_text(encoding='utf-8')).get('facts', [])
    except ValueError:
        rows = []
    emails, phones = [], []
    for x in rows:
        if x.get('superseded') or not is_confirmed_source(x.get('source', '')):
            continue
        text = str(x.get('fact', ''))
        emails += [e for e in EMAIL.findall(text) if e not in emails]
        if re.search(r'phone|tel\b|telephone|call|whatsapp|mobile|هاتف|واتساب', text, re.I):
            phones += [p.strip() for p in PHONE.findall(text) if p.strip() not in phones]
    return {'email': emails, 'phone': phones}


def _digits(s):
    d = re.sub(r'\D', '', s or '')
    return d[-9:]


def _hotel(group_dir, slug):
    reg = grp.load(group_dir)
    if not reg:
        raise FileNotFoundError(f'no site.json in {group_dir}')
    h = next((x for x in reg['hotels'] if x['slug'] == slug), None)
    if not h:
        raise LookupError(f'no hotel "{slug}" in {group_dir}')
    return reg, h, grp.hotel_dir(group_dir, slug, reg)


# ---------------------------------------------------------------- lint

def lint_reply(reply, review, hotel_name='', city='', contact=None):
    """{'problems': [...], 'warnings': [...]} for one reply. Problems block sending."""
    contact = contact or {'email': [], 'phone': []}
    rid = review.get('review_id', '?')
    who = f"review {rid} ({review.get('stars') or '?'}★)"
    text = (reply or '').strip()
    probs, warns = [], []
    if not text:
        return {'problems': [f'{who}: no reply written (write one, or set "skip": true)'], 'warnings': []}
    if len(text) > REPLY_MAX_CHARS:
        probs.append(f'{who}: reply is {len(text)} characters (max {REPLY_MAX_CHARS}): cut it to 2-4 sentences')
    if '[CONFIRM' in text:
        probs.append(f'{who}: [CONFIRM] left in the reply: only confirmed facts go to Google')
    # language
    want = review.get('language') or 'en'
    got = language(text)
    if want == 'ar' and got != 'ar':
        probs.append(f'{who}: the review is in Arabic; write the reply in Arabic (natively, not a translation)')
    elif want == 'en' and got == 'ar':
        probs.append(f'{who}: the review is in English; the reply is in Arabic')
    elif want == 'other':
        warns.append(f'{who}: the review is in another language; the reply is in '
                     f'{"Arabic" if got == "ar" else "English"}: check with the user')
    # prices, offers, links
    for rx, what in ((copylint.PRICE, 'a price'), (DEAL, 'an offer / deal'), (OFFER, 'a discount / code / upgrade'),
                     (URL, 'a link')):
        m = rx.search(text)
        if m:
            probs.append(f'{who}: {what} in the reply "{m.group(0).strip()}": replies never carry prices, offers or '
                         'links')
    # personal data and booking details
    m = BOOKING_DETAIL.search(text)
    if m:
        probs.append(f'{who}: booking or personal detail "{m.group(0).strip()}" in the reply (no booking / room '
                     'numbers, stay dates or payment details in public)')
    first = (review.get('first_name') or '').strip()
    display = (review.get('reviewer') or '').strip()
    for tok in display.split()[1:]:
        tok = tok.strip('.,')
        if len(tok) >= 2 and re.search(r'(?<![\w])' + re.escape(tok) + r'(?![\w])', text, re.I):
            probs.append(f'{who}: the guest\'s surname "{tok}" in the reply: first name only')
    if not first and display and display.split() and display.lower() not in ANON_NAMES:
        tok = display.split()[0]
        if len(tok) >= 2 and re.search(r'(?<![\w])' + re.escape(tok) + r'(?![\w])', text, re.I) and \
                tok.lower() not in (hotel_name or '').lower():
            warns.append(f'{who}: "{tok}" is not a usable first name (initials / handle): thank without a name')
    allowed_emails = {e.lower() for e in contact.get('email', [])}
    allowed_phones = {_digits(p) for p in contact.get('phone', [])}
    used_contact = False
    for e in EMAIL.findall(text):
        if e.lower() in allowed_emails:
            used_contact = True
        else:
            probs.append(f'{who}: email "{e}" is not a confirmed hotel contact (hotel-facts.json): use a confirmed '
                         'one or none')
    for p in PHONE.findall(text):
        if _digits(p) in allowed_phones:
            used_contact = True
        else:
            probs.append(f'{who}: phone "{p.strip()}" is not a confirmed hotel contact (hotel-facts.json)')
    # tone
    m = ARGUE.search(text)
    if m:
        probs.append(f'{who}: "{m.group(0)}" argues with the guest: acknowledge, apologise, take it offline')
    stars = review.get('stars') or 5
    if stars <= COMPLAINT_MAX_STARS:
        if not APOLOGY.search(text):
            probs.append(f'{who}: a complaint needs an apology')
        if not (contact.get('email') or contact.get('phone')):
            probs.append(f'{who}: a complaint needs an offline contact, and hotel-facts.json has no confirmed hotel '
                         'email or phone: add one (add_facts) first')
        elif not used_contact:
            probs.append(f'{who}: a complaint needs an offline contact: give the confirmed '
                         + ' or '.join((contact.get('email') or [])[:1] + (contact.get('phone') or [])[:1]))
    elif stars == MIXED_STARS and not (APOLOGY.search(text) or used_contact):
        warns.append(f'{who}: a 3-star review usually names a problem: apologise for it or offer a contact')
    # keyword stuffing
    if hotel_name and len(hotel_name) > 3:
        uses = len(re.findall(re.escape(hotel_name), text, re.I))
        if uses > NAME_MAX_USES:
            probs.append(f'{who}: the hotel name is used {uses} times (once at most: keyword stuffing)')
    m = STUFF.search(text)
    if m:
        probs.append(f'{who}: "{m.group(0)}" reads as keyword stuffing: write to the guest, not to Google')
    if city and len(city) > 2 and len(re.findall(r'(?<![\w])' + re.escape(city) + r'(?![\w])', text, re.I)) > 1:
        probs.append(f'{who}: "{city}" is used more than once (keyword stuffing)')
    # house style: our copy lint (stock openings, em dashes, superlatives, AI tells, invisible characters)
    rep = copylint.report_units([{'kind': 'copy', 'text': text, 'where': who}], hotel_name)
    probs += rep['problems']
    warns += [w for w in rep['warnings'] if 'will date' not in w]
    for m in REPLY_TELLS.finditer(text):
        probs.append(f'{who}: canned phrase "{m.group(0)}" (an AI / template tell): say it the way the hotel would')
    if first and not re.search(re.escape(first), text, re.I) and stars > COMPLAINT_MAX_STARS:
        warns.append(f'{who}: the guest signed as {first}: thank them by first name')
    return {'problems': probs, 'warnings': warns}


# ---------------------------------------------------------------- the two calls

def write_drafts(hdir, hotel, location, account, rows, facts_file, since_days=0, today=None):
    today = today or date.today()
    out = hdir / 'gbp'
    out.mkdir(parents=True, exist_ok=True)
    f = out / f'review-replies-{today.isoformat()}.json'
    voice = hdir / 'voice.md'
    doc = {'hotel': hotel.get('name', ''), 'slug': hotel.get('slug', ''), 'city': hotel.get('city', ''),
           'location': location, 'account': account, 'created': today.isoformat(), 'since_days': since_days,
           'facts_file': str(facts_file), 'voice_file': str(voice) if voice.exists() else '',
           'contacts': contacts(facts_file), 'max_chars': REPLY_MAX_CHARS, 'rules': RULES,
           'how_to_fill': 'Write each "reply" (or set "skip": true), then gbp_review_drafts_check(<this file>).',
           'replies': rows}
    f.write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding='utf-8')
    L = [f"# Review replies to write: {doc['hotel']} ({today.isoformat()})", '',
         f"{len(rows)} review(s) need a reply. Write each reply in the JSON file ({f.name}); this page is for reading.",
         '', f"Confirmed contacts for complaints: {', '.join(doc['contacts']['email'] + doc['contacts']['phone']) or 'none (add one with add_facts)'}",
         '', '## Rules', *[f'- {r}' for r in RULES], '']
    for r in rows:
        L += [f"## {r['stars'] or '?'}★ · {r['date']} · {r['reviewer'] or 'anonymous'} · {r['language'].upper()}"
              + (' · SHOW THE USER FIRST' if r['check_with_user_first'] else ''), '',
              f"Review {r['review_id']} ({r['reason']})", '', f"> {r['comment'] or '(stars only, no text)'}"]
        if r['comment_translated']:
            L += ['', f"Google's translation: {r['comment_translated']}"]
        if r['existing_reply']:
            L += ['', f"Current reply ({r['existing_reply_date']}): {r['existing_reply']}"]
        L.append('')
    f.with_suffix('.md').write_text('\n'.join(L), encoding='utf-8')
    return f


def pending(group_dir, slug, location='', since_days=0, limit=200):
    """Reviews that need a reply, as a drafts file for Claude to fill. Read-only on Google's side."""
    ok, why = gbp.configured()
    if not ok:
        return {'checked': False, 'reason': why}
    try:
        reg, hotel, hdir = _hotel(group_dir, slug)
        loc = gbp.resolve_hotel(group_dir, slug, location)
        linked = gbp.hotel_location(group_dir, slug)
        account = linked.get('account') if linked.get('location') == loc and linked.get('account') else ''
        if not account:
            account, found = gbp._find(loc)
            loc = found['name'] if found['name'].startswith('locations/') else loc
        raw = _fetch(account, loc, limit)
    except (gbp.GbpError, FileNotFoundError, LookupError) as e:
        return {'checked': False, 'reason': str(e)}
    except Exception as e:  # noqa: BLE001 - sign-in failures etc. as a readable reason
        return {'checked': False, 'reason': f'{type(e).__name__}: {str(e)[:400]}'}
    rows = select_pending(raw, since_days)
    facts_file = hdir / 'hotel-facts.json'
    f = write_drafts(hdir, hotel, loc, account, rows, facts_file, since_days)
    low = [r for r in rows if r['check_with_user_first']]
    return {'checked': True, 'location': loc, 'fetched': len(raw), 'pending': len(rows), 'low_star': len(low),
            'by_language': {k: sum(r['language'] == k for r in rows) for k in ('en', 'ar', 'other')},
            'drafts_file': str(f), 'md_file': str(f.with_suffix('.md')),
            'contacts': contacts(facts_file),
            'reviews': [{k: (v[:200] if isinstance(v, str) else v) for k, v in r.items()
                         if k in ('review_id', 'stars', 'date', 'first_name', 'language', 'comment', 'reason',
                                  'check_with_user_first')} for r in rows[:40]],
            'next': ('Show the user the 1-2 star reviews first (check_with_user_first) and ask how the hotel wants to '
                     'answer them. Write each "reply" in the drafts file (Arabic reviews: write the reply in Arabic), '
                     'then gbp_review_drafts_check(drafts_file).') if rows else 'No review needs a reply.'}


# ---------------------------------------------------------------- the review sheet (Excel)
#
# The replies the plugin wrote, in a sheet the user or the hotel can read and edit before anything is posted:
# <hotel dir>/Reports/<date>/NN - <Hotel> Review Replies (<d Mon>).xlsx. Grey cells are the review; yellow cells
# ("Final reply", "Send?", "Notes") are theirs. read_sheet() / import_sheet() take the rows marked "Yes", lint the
# final reply again and give the gbp_propose changes; that is what gets posted (after the user approves the change id).

SHEET_TITLE = 'Review Replies'
COLS = [('review_id', 'Review ID', 14), ('date', 'Date', 11), ('stars', 'Stars', 7), ('reviewer', 'Reviewer', 18),
        ('language', 'Language', 9), ('comment', 'Review', 60), ('comment_translated', "Google's translation", 40),
        ('existing_reply', 'Current reply', 36), ('reason', 'Why it needs a reply', 22),
        ('reply', 'Reply written by the plugin', 55), ('final', 'Final reply (edit here)', 55),
        ('send', 'Send? (Yes / No)', 11), ('notes', 'Notes', 28), ('status', 'Status', 22)]
EDITABLE = {'final', 'send', 'notes'}
YES_RX = re.compile(r'^\s*(?:y|yes|ok|send|نعم)\s*\.?\s*$', re.I)


def _sheet_name(hotel_name, today):
    name = f"{hotel_name} {SHEET_TITLE} ({today.day} {today.strftime('%b')}).xlsx"
    return re.sub(r'[<>:"/\\|?*]', '-', name)


def write_sheet(drafts_file, today=None):
    """The review sheet for a drafts file (after check_drafts): one row per review, the plugin's reply copied into
    "Final reply". 1-2 star reviews start as "Send? = No" (the user sees them first); a skipped review is "No"."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from . import pdf
    today = today or date.today()
    f = paths.resolve(drafts_file)
    d = json.loads(f.read_text(encoding='utf-8'))
    hdir = f.parent.parent
    out = paths.reports_dir(hdir, today.isoformat())
    out.mkdir(parents=True, exist_ok=True)
    navy, yellow, grey, red = (PatternFill('solid', fgColor=c) for c in ('12355B', 'FFF4C2', 'F2F4F7', 'FDE2E1'))
    thin = Side(style='thin', color='D6DBE1')
    box = Border(left=thin, right=thin, top=thin, bottom=thin)
    wrap, rtl = Alignment(wrap_text=True, vertical='top'), Alignment(wrap_text=True, vertical='top',
                                                                      horizontal='right', readingOrder=2)
    wb = Workbook()
    ws = wb.active
    ws.title = 'How to use'
    lines = [(f"{d.get('hotel', '')}: Google review replies", Font(bold=True, size=14, color='12355B')),
             (f"{len(d.get('replies', []))} review(s) that need a reply, read on {d.get('created', '')}.", None), ('', None),
             ('Edit only the yellow cells. "Final reply" is what is posted on Google, exactly as written.', None),
             ('"Send?": Yes to post the reply, No to leave the review unanswered for now.', None),
             ('1-2 star reviews start as No: read them first and say how the hotel wants to answer.', None),
             ('Arabic reviews get an Arabic reply. Keep it to 2-4 sentences; no prices, offers, booking numbers or '
              'room numbers.', None), ('', None),
             ('Nothing is posted until MetaHotels has checked the sheet and you approve the change on screen.',
              Font(bold=True))]
    for r, (text, font) in enumerate(lines, 1):
        ws.cell(row=r, column=1, value=text).font = font or Font()
    ws.column_dimensions['A'].width = 110
    s = wb.create_sheet('Replies')
    s.append([c[1] for c in COLS])
    for c in s[1]:
        c.fill, c.font, c.alignment, c.border = navy, Font(bold=True, color='FFFFFF'), wrap, box
    for r in d.get('replies', []):
        low = bool(r.get('check_with_user_first'))
        reply = '' if r.get('skip') else (r.get('reply') or '').strip()
        row = dict(r, final=reply, send='No' if (low or r.get('skip') or not reply) else 'Yes',
                   notes='Complaint: show the user first' if low else ('skipped by the plugin' if r.get('skip') else ''),
                   status='')
        s.append([row.get(k, '') if not isinstance(row.get(k), list) else ', '.join(row[k]) for k, _, _ in COLS])
        n = s.max_row
        for col, (k, _, _) in enumerate(COLS, 1):
            cell = s.cell(row=n, column=col)
            cell.border = box
            cell.fill = yellow if k in EDITABLE else (red if low and k == 'stars' else grey)
            cell.alignment = rtl if r.get('language') == 'ar' and k in ('comment', 'reply', 'final') else wrap
    for col, (_, _, w) in enumerate(COLS, 1):
        s.column_dimensions[chr(64 + col)].width = w
    s.freeze_panes = 'C2'
    info = wb.create_sheet('Info')
    for k, v in (('drafts_file', str(f)), ('location', d.get('location', '')), ('hotel', d.get('hotel', '')),
                 ('created', today.isoformat())):
        info.append([k, v])
    info.sheet_state = 'hidden'
    name = _sheet_name(d.get('hotel', ''), today)
    same = list(out.glob(f'* - {name}'))
    num = re.match(r'(\d+) - ', same[0].name).group(1) if same else pdf.next_file_number()
    x = out / f'{num} - {name}'
    wb.save(x)
    d['review_sheet'] = str(x)
    f.write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding='utf-8')
    return x


def latest_sheet(hdir):
    """The newest review sheet of a hotel (any dated report folder), or None."""
    found = sorted(paths.resolve(hdir).joinpath('Reports').rglob(f'* {SHEET_TITLE} (*).xlsx'),
                   key=lambda p: p.stat().st_mtime)
    return found[-1] if found else None


def read_sheet(xlsx):
    """The rows marked "Send? = Yes" that are not posted or proposed yet, linted again with their final reply.
    Returns {"replies": [{review_id, reply}], "problems", "warnings", "location", "drafts_file", "show_user_first"}."""
    from openpyxl import load_workbook
    x = paths.resolve(xlsx)
    wb = load_workbook(x, data_only=True)
    info = {str(r[0]): r[1] for r in wb['Info'].iter_rows(values_only=True) if r and r[0]} if 'Info' in wb.sheetnames \
        else {}
    d = {}
    if info.get('drafts_file') and paths.resolve(info['drafts_file']).exists():
        d = json.loads(paths.resolve(info['drafts_file']).read_text(encoding='utf-8'))
    by_id = {r.get('review_id'): r for r in d.get('replies', [])}
    contact = contacts(d['facts_file']) if d.get('facts_file') else d.get('contacts') or {}
    ws = wb['Replies']
    head = [c.value for c in ws[1]]
    idx = {k: head.index(label) for k, label, _ in COLS if label in head}
    replies, problems, warnings, flagged, rows = [], [], [], [], {}
    for n, row in enumerate(ws.iter_rows(min_row=2, values_only=True), 2):
        get = (lambda k: row[idx[k]] if k in idx and idx[k] < len(row) else None)
        rid = str(get('review_id') or '').strip()
        if not rid:
            continue
        status = str(get('status') or '').lower()
        if not YES_RX.match(str(get('send') or '')) or status.startswith(('posted', 'proposed')):
            continue
        final = str(get('final') or '').strip()
        review = by_id.get(rid) or {'review_id': rid, 'stars': get('stars'), 'language': get('language') or '',
                                    'comment': get('comment') or '', 'first_name': ''}
        if not final:
            problems.append(f'row {n} ({rid}): "Send?" is Yes but "Final reply" is empty')
            continue
        res = lint_reply(final, review, d.get('hotel', info.get('hotel', '')), d.get('city', ''), contact)
        problems += [f'row {n}: {p}' for p in res['problems']]
        warnings += [f'row {n}: {w}' for w in res['warnings']]
        if review.get('check_with_user_first'):
            flagged.append({'review_id': rid, 'stars': review.get('stars'), 'comment': str(review.get('comment'))[:400],
                            'reply': final})
        replies.append({'review_id': rid, 'reply': final})
        rows[rid] = n
    return {'xlsx': str(x), 'replies': replies, 'problems': problems, 'warnings': warnings,
            'show_user_first': flagged, 'location': info.get('location') or d.get('location', ''),
            'drafts_file': info.get('drafts_file', ''), 'rows': rows}


def mark_sheet(xlsx, review_ids, status):
    """Write a status ("Proposed, change <id>", "Posted <date>") on the rows of these reviews."""
    from openpyxl import load_workbook
    x = paths.resolve(xlsx)
    wb = load_workbook(x)
    ws = wb['Replies']
    head = [c.value for c in ws[1]]
    ci, si = head.index('Review ID') + 1, head.index('Status') + 1
    want = set(review_ids)
    for r in range(2, ws.max_row + 1):
        if str(ws.cell(row=r, column=ci).value or '') in want:
            ws.cell(row=r, column=si, value=status)
    wb.save(x)


def import_sheet(xlsx):
    """The edited review sheet -> one gbp_write proposal of the rows marked Yes (sends nothing). Problems block it."""
    r = read_sheet(xlsx)
    out = {k: r[k] for k in ('xlsx', 'problems', 'warnings', 'show_user_first', 'location')}
    out['replies'] = len(r['replies'])
    if r['problems'] or not r['replies']:
        out['next'] = ('Fix the problems in the sheet (or set "Send?" to No) and import it again; nothing was proposed.'
                       if r['problems'] else 'No row is marked "Send? = Yes" (or every one was already proposed).')
        return out
    if not r['location']:
        out['problems'] = ['the sheet has no Business Profile location (Info sheet): link the hotel with gbp_link']
        return out
    from . import gbp_write
    hdir = paths.resolve(r['drafts_file']).parent.parent if r['drafts_file'] else paths.owner_dir(paths.resolve(xlsx).parent)
    res = gbp_write.propose(r['location'], {'review_replies': r['replies']}, out_dir=str(hdir / 'gbp' / 'changes'))
    if not res.get('checked'):
        out['problems'] = [res.get('reason') or 'the proposal failed']
        return out
    mark_sheet(xlsx, [x['review_id'] for x in r['replies']], f"Proposed, change {res['change_id']}")
    out.update(change_id=res['change_id'], change_file=res['change_file'], preview=res.get('preview', ''),
               next='Show the user every reply (the 1-2 star ones first) and the preview word for word; '
                    'gbp_apply(change_file, confirm=change_id) only after they approve that id in a later message.')
    return out


def check_drafts(file):
    """Lint every reply of a drafts file. Returns the ready `changes` for gbp_propose only when nothing blocks."""
    f = paths.resolve(file)
    d = json.loads(f.read_text(encoding='utf-8'))
    contact = contacts(d['facts_file']) if d.get('facts_file') else d.get('contacts') or {}   # re-read: facts change
    problems, warnings, ready, skipped, flagged = [], [], [], [], []
    for r in d.get('replies', []):
        if r.get('skip'):
            skipped.append(r.get('review_id'))
            continue
        res = lint_reply(r.get('reply', ''), r, d.get('hotel', ''), d.get('city', ''), contact)
        problems += res['problems']
        warnings += res['warnings']
        if (r.get('reply') or '').strip():
            ready.append({'review_id': r['review_id'], 'reply': r['reply'].strip()})
        if r.get('check_with_user_first'):
            flagged.append({'review_id': r.get('review_id'), 'stars': r.get('stars'),
                            'comment': (r.get('comment') or '')[:400], 'reply': r.get('reply', '')})
    ok = not problems and bool(ready)
    hdir = f.parent.parent
    sheet = str(write_sheet(f)) if ok else ''
    return {'ready': ok, 'replies': len(ready), 'skipped': skipped, 'problems': problems, 'warnings': warnings,
            'show_user_first': flagged, 'location': d.get('location', ''),
            'review_sheet': sheet, 'out_dir': str(hdir / 'gbp' / 'changes'),
            'next': ('Fix every problem in the drafts file and check again; nothing can be sent yet.' if problems else
                     'Nothing to send.' if not ready else
                     f'The review sheet is ready: {sheet}. Give it to the user (and the hotel, for the 1-2 star '
                     'ones) to read and edit: "Final reply" is what gets posted, "Send?" Yes / No. When it comes '
                     'back, gbp_review_sheet_import(<sheet>) checks it again and proposes the Yes rows (or the '
                     'execute business-profile batch picks them up); gbp_apply only after the user approves the '
                     'change id in a later message.')}
