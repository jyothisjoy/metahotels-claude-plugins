"""Mirai reservations through the Mirai XML API (webservice_getreservations, R.1.0.36).

Credentials (first found wins):
  1. MIRAI_USER / MIRAI_PASS in the environment
  2. MIRAI_USER / MIRAI_PASS in the .env file of the work folder (where Claude was started; desktop
     chat: ~/Documents/MetaHotels SEO)
  3. ~/.metahotels-seo/mirai.json written by `hotel-seo-mirai-login`
Claude never reads or prints them; they only go into the Basic auth header.

What the API gives (and what the spec gets wrong, checked against live responses, Oct 2026):
  - One call per 3 minutes and at most 31 days per call. The last call time is kept on disk, so the
    limit holds across MCP server restarts and the scheduled monitor.
  - One login covers a whole chain: each response has a <bookings hotelId=...> group for every hotel
    the login can see (empty ones too), so one window serves every hotel and tells us whether a
    Mirai ID is covered at all.
  - Amounts use a dot (1306.96) although the spec shows a comma (727,74); both are parsed.
  - modified_reservations=true is needed to see modifications; a booking can appear in several
    windows, so the latest revision (by @date) wins.
  - Cancelled = action "Cancel" or revisionStatus 2 / 4; 6 = no-show; 7 = duplicate (dropped).
  - Room and offer names are only in <distributor> comments ("Room id #561842", "Offer id #574228").

Personal data (names, email, phone, card, documents, comments) is never parsed or stored: windows are
cached as reduced JSON in ~/.metahotels-seo/mirai-cache, one file per window for all hotels.
"""
import argparse
import base64
import getpass
import hashlib
import html
import json
import os
import re
import statistics
import threading
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

import defusedxml.ElementTree as ET
import requests

from . import paths

CREDS = paths.HOME / 'mirai.json'
CACHE = paths.HOME / 'mirai-cache'
LAST_CALL = CACHE / 'last-call'
URL = 'https://channel.mirai.com/XMLIntegrationx/webservice_getreservations_Auth.apro'
MIN_GAP = 185            # seconds between calls (limit: one per 3 minutes)
WINDOW_DAYS = 31         # per call
TODAY_CACHE_MIN = 60     # a window that includes today is reused for this long
CACHE_VERSION = 2
BOARDS = {'0': 'Room only', '1': 'Breakfast', '2': 'Half board', '3': 'Full board', '4': 'All inclusive',
          '5': 'Half board plus', '6': 'Full board plus', '7': 'All inclusive plus'}
_lock = threading.Lock()


# ---------------------------------------------------------------- credentials

def _dotenv(path):
    vals = {}
    try:
        lines = path.read_text(encoding='utf-8-sig').splitlines()
    except OSError:
        return vals
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        k = re.sub(r'^export\s+', '', k.strip())
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in '"\'':
            v = v[1:-1]
        else:
            v = re.sub(r'\s+#.*$', '', v)
        vals[k] = v
    return vals


def credentials():
    """(user, password, where) or (None, None, why not)."""
    user, pw = os.environ.get('MIRAI_USER'), os.environ.get('MIRAI_PASS') or os.environ.get('MiRAI_PASS')
    if user and pw:
        return user, pw, 'environment'
    env_file = paths.work_dir() / '.env'
    env = _dotenv(env_file)
    user, pw = env.get('MIRAI_USER'), env.get('MIRAI_PASS') or env.get('MiRAI_PASS')
    if user and pw:
        return user, pw, str(env_file)
    if CREDS.exists():
        c = json.loads(CREDS.read_text(encoding='utf-8'))
        if c.get('login') and c.get('password'):
            return c['login'], c['password'], str(CREDS)
    return None, None, (f'no MIRAI_USER / MIRAI_PASS in {env_file} (or the environment, or {CREDS})')


def configured():
    user, _, where = credentials()
    return (True, where) if user else (False, where)


def _headers():
    user, pw, _ = credentials()
    token = base64.b64encode(f'{user}:{pw}'.encode()).decode()
    return {'Authorization': f'Basic {token}', 'Accept-Encoding': 'gzip, deflate, br', 'Content-Type': 'text/xml'}


def _user_key():
    return hashlib.sha1((credentials()[0] or '').encode()).hexdigest()[:8]


# ---------------------------------------------------------------- parsing

def _num(v):
    """Mirai amounts: '1306.96' in live responses, '727,74' in the spec; '1.234,56' tolerated."""
    s = str(v or '').strip()
    if not s:
        return 0.0
    if ',' in s and '.' in s:
        s = s.replace('.', '').replace(',', '.') if s.rfind(',') > s.rfind('.') else s.replace(',', '')
    elif ',' in s:
        s = s.replace(',', '.')
    try:
        return float(s)
    except ValueError:
        return 0.0


def _int(v, default=0):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return default


def _text(el):
    return html.unescape(html.unescape((el.text or '').strip())) if el is not None else ''


def _failure(root):
    f = root.find('failure')
    if f is None:
        return ''
    comment = _text(f.find('comment'))
    first = next((ln.strip() for ln in comment.splitlines() if ln.strip()), '')
    message = re.sub(r'^[\w.]+Exception:\s*', '', first)[:200]
    return f"{f.get('type', 'failure')}: {message}"


def _booking(b, hotel_id):
    """One booking without personal data."""
    comments = {}
    for c in b.iter('comment'):
        m = re.match(r'\s*(Room|Offer|PriceModifier)\s+id\s*#?\s*(\d+)', c.get('name') or '', re.I)
        if m:
            comments[(m.group(1).lower(), m.group(2))] = _text(c)
    club = b.find('club')
    club_status = next((_text(c) for c in b.iter('comment') if (c.get('name') or '') == 'ClubStatus'), '')
    joins = (club.get('joinsclub') if club is not None else '') or \
        (re.search(r'joinsclub:\s*(\w+)', club_status, re.I) or [None, ''])[1]
    rooms, stays, adults, children = [], [], 0, 0
    for r in b.iter('room'):
        segs = (r.get('id') or '').split('-')
        label = next((comments[('room', s)] for s in segs if ('room', s) in comments), '')
        name, _, rate = label.partition(' : ')
        rate = re.sub(r'\s+\d+\s+(adults?|guests?|persons?)\b.*$', '', rate).strip()
        adults += _int(r.get('numAdults'))
        children += _int(r.get('numChildren')) + _int(r.get('numBabies'))
        offer = r.get('idOffer') or ''
        rooms.append({'room': name.strip() or f"room type {r.get('idRoomType', '?')}", 'rate': rate,
                      'offer_id': offer, 'offer': comments.get(('offer', offer), '') if offer else ''})
        for s in r.iter('stay'):
            q = _int(s.get('quantity'), 1) or 1
            stays.append({'date': s.get('date', ''), 'board': BOARDS.get(s.get('idBoard', ''), s.get('idBoard', '')),
                          'quantity': q, 'revenue': round(_num(s.get('unitPrice')) * q, 2)})
    dates = sorted({s['date'] for s in stays if s['date']})
    checkin = dates[0] if dates else ''
    checkout = (date.fromisoformat(dates[-1]) + timedelta(days=1)).isoformat() if dates else ''
    extras = b.find('extras')
    return {
        'id': b.get('id'), 'hotel_id': hotel_id, 'action': b.get('action', ''),
        'revision_status': b.get('revisionStatus', ''), 'event_date': b.get('date', ''),
        'reservation_date': (b.get('reservationDate') or b.get('date') or '')[:10],
        'cancellation_date': (b.get('cancellationDate') or '')[:10],
        'checkin': checkin, 'checkout': checkout,
        'nights': (date.fromisoformat(checkout) - date.fromisoformat(checkin)).days if checkin else 0,
        'room_nights': sum(s['quantity'] for s in stays), 'rooms': rooms, 'stays': stays,
        'adults': adults, 'children': children,
        'total': _num(b.get('totalAmount')), 'total_without_taxes': _num(b.get('amountWithoutTaxes')),
        'currency': b.get('currency', ''), 'commission_pct': _int(b.get('commission')) / 100,
        'channel': b.get('channelSource', ''), 'hsri': b.get('hsri', ''), 'promo': b.get('promo', ''),
        'non_refundable': (b.get('nonRefundable') or '').lower() == 'true',
        'payment_type': b.get('paymentType', ''), 'language': b.get('language', ''),
        'country': (b.find('customer').get('countryCode', '') if b.find('customer') is not None else ''),
        'club_member': club.get('member', '') if club is not None else '',
        'club_joins': (joins or '').lower(), 'club_level': club.get('level', '') if club is not None else '',
        'club_program': club.get('programId', '') if club is not None else '',
        'price_modifiers': sorted({v for (k, _), v in comments.items() if k == 'pricemodifier'}),
        'extras': [{'name': e.get('name', ''), 'total': _num(e.get('total_price'))} for e in extras]
        if extras is not None else [],
    }


def parse(xml_text):
    """{'hotels': [every hotel ID the login covers], 'bookings': [...]} from one response."""
    root = ET.fromstring(xml_text)
    why = _failure(root)
    if why:
        raise RuntimeError(f'Mirai returned {why}')
    hotels, bookings = [], []
    for g in root.findall('bookings'):
        hid = g.get('hotelId', '')
        hotels.append(hid)
        bookings.extend(_booking(b, hid) for b in g.findall('booking'))
    return {'hotels': hotels, 'bookings': bookings}


# ---------------------------------------------------------------- fetching

def _windows(start, end):
    cur = start
    while cur <= end:
        stop = min(cur + timedelta(days=WINDOW_DAYS - 1), end)
        yield cur, stop
        cur = stop + timedelta(days=1)


def _wait_turn(progress=None):
    CACHE.mkdir(parents=True, exist_ok=True)
    try:
        last = float(LAST_CALL.read_text())
    except (OSError, ValueError):
        last = 0.0
    wait = MIN_GAP - (time.time() - last)
    if wait > 0:
        if progress:
            progress(f'waiting {int(wait)}s for the Mirai limit (one call per 3 minutes)')
        time.sleep(wait)


def _call(params, progress=None):
    with _lock:
        _wait_turn(progress)
        try:
            r = requests.get(URL, params={**params, 'modified_reservations': 'true'}, headers=_headers(),
                             timeout=180)
        finally:
            LAST_CALL.write_text(str(time.time()))
    if r.status_code == 401:
        raise RuntimeError('Mirai rejected the login (401): check MIRAI_USER / MIRAI_PASS.')
    if r.status_code >= 400 and '<failure' not in r.text:
        raise RuntimeError(f'Mirai answered HTTP {r.status_code}.')
    return parse(r.text)


def _window(by, frm, to, progress=None):
    """One window for every hotel the login covers, from the cache when it can be."""
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / f'{by}-{frm}-{to}-{_user_key()}.json'
    today = date.today()
    if f.exists():
        data = json.loads(f.read_text(encoding='utf-8'))
        age_min = (time.time() - data.get('fetched', 0)) / 60
        # a closed window no longer changes (arrivals: allow 3 days for late cancellations / no-shows)
        closed = to < today if by == 'booking' else to < today - timedelta(days=3)
        if data.get('v') == CACHE_VERSION and (closed or age_min < TODAY_CACHE_MIN):
            return data
    if progress:
        progress(f'fetching {by} dates {frm}..{to}')
    keys = ('from', 'to') if by == 'booking' else ('checkinFrom', 'checkinTo')
    data = _call({keys[0]: f'{frm}T00:00:00', keys[1]: f'{to}T23:59:59'}, progress)
    data.update(v=CACHE_VERSION, fetched=time.time(), window=f'{frm}..{to}', by=by)
    f.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    return data


# ---------------------------------------------------------------- summary

def _status(b):
    if b['revision_status'] == '7':
        return 'duplicate'
    if b['action'].lower() == 'cancel' or b['revision_status'] in ('2', '4'):
        return 'cancelled'
    if b['revision_status'] == '6':
        return 'no_show'
    return 'live'


def _top(counter, n=15, ndigits=None):
    return {k: (round(v, ndigits) if ndigits is not None else v) for k, v in counter.most_common(n) if k}


def summarise(bookings, currency_hint=''):
    live = [b for b in bookings if _status(b) == 'live']
    cancelled = [b for b in bookings if _status(b) == 'cancelled']
    no_shows = [b for b in bookings if _status(b) == 'no_show']
    currencies = Counter(b['currency'] for b in live if b['currency'])
    cur = currencies.most_common(1)[0][0] if currencies else currency_hint
    revenue = sum(b['total'] for b in live)
    room_nights = sum(b['room_nights'] for b in live)
    lead = [(date.fromisoformat(b['checkin']) - date.fromisoformat(b['reservation_date'])).days
            for b in live if b['checkin'] and b['reservation_date']]
    buckets = Counter('0-1 days' if d <= 1 else '2-7 days' if d <= 7 else '8-30 days' if d <= 30
                      else '31-90 days' if d <= 90 else '91+ days' for d in lead)

    by_month = defaultdict(lambda: {'bookings': 0, 'revenue': 0.0, 'room_nights': 0, 'cancelled': 0})
    for b in live:
        m = by_month[b['reservation_date'][:7]]
        m['bookings'] += 1
        m['revenue'] += b['total']
        m['room_nights'] += b['room_nights']
    for b in cancelled:
        by_month[b['reservation_date'][:7]]['cancelled'] += 1
    by_stay = defaultdict(lambda: {'room_nights': 0, 'revenue': 0.0})
    for b in live:
        for s in b['stays']:
            m = by_stay[s['date'][:7]]
            m['room_nights'] += s['quantity']
            m['revenue'] += s['revenue']

    offers = defaultdict(lambda: {'bookings': 0, 'room_nights': 0, 'revenue': 0.0, 'offer_id': ''})
    room_types = defaultdict(lambda: {'bookings': 0, 'room_nights': 0, 'revenue': 0.0})
    for b in live:
        share = b['total'] / max(1, len(b['rooms']))
        nights_per_room = b['room_nights'] / max(1, len(b['rooms']))
        for r in b['rooms']:
            o = offers[r['offer'] or ('(no offer)' if not r['offer_id'] else f"offer {r['offer_id']}")]
            o['bookings'] += 1
            o['room_nights'] += nights_per_room
            o['revenue'] += share
            o['offer_id'] = r['offer_id']
            t = room_types[r['room']]
            t['bookings'] += 1
            t['room_nights'] += nights_per_room
            t['revenue'] += share

    def rows(d):
        return [{'name': k, **{kk: round(vv, 2) if isinstance(vv, float) else vv for kk, vv in v.items()}}
                for k, v in sorted(d.items(), key=lambda kv: -kv[1]['revenue'])]

    n = len(live) or 1
    return {
        'bookings': len(live), 'cancelled': len(cancelled), 'no_shows': len(no_shows),
        'cancellation_rate_pct': round(100 * len(cancelled) / (len(live) + len(cancelled)), 1)
        if live or cancelled else 0,
        'currency': cur, 'other_currencies': {k: v for k, v in currencies.items() if k != cur},
        'revenue': round(revenue, 2), 'cancelled_revenue': round(sum(b['total'] for b in cancelled), 2),
        'room_nights': room_nights,
        'adr': round(revenue / room_nights, 2) if room_nights else 0,
        'avg_length_of_stay': round(sum(b['nights'] for b in live) / n, 2) if live else 0,
        'median_booking_window_days': statistics.median(lead) if lead else None,
        'booking_window': dict(sorted(buckets.items(), key=lambda kv: int(re.match(r'\d+', kv[0]).group(0)))),
        'checkin_weekday': dict(Counter(date.fromisoformat(b['checkin']).strftime('%a')
                                        for b in live if b['checkin']).most_common()),
        'by_booking_month': {k: {kk: round(vv, 2) for kk, vv in v.items()} for k, v in sorted(by_month.items())},
        'by_stay_month': {k: {kk: round(vv, 2) for kk, vv in v.items()} for k, v in sorted(by_stay.items())},
        'offers': rows(offers), 'room_types': rows(room_types),
        'boards': _top(Counter(s['board'] for b in live for s in b['stays'] for _ in range(s['quantity']))),
        'channel_source': _top(Counter(b['channel'] for b in live)),
        'promo_codes': _top(Counter(b['promo'] for b in live)),
        'price_modifiers': _top(Counter(p for b in live for p in b['price_modifiers'])),
        'club': {'program': _top(Counter(b['club_program'] for b in live), 3),
                 'joined_with_this_booking': sum(b['club_joins'] in ('new', 'yes') for b in live),
                 'existing_members': sum(b['club_joins'] == 'existing' for b in live),
                 'levels': _top(Counter(b['club_level'] for b in live))},
        'guest_country': _top(Counter(b['country'] for b in live)),
        'language': _top(Counter(b['language'] for b in live)),
        'with_children_pct': round(100 * sum(b['children'] > 0 for b in live) / n, 1) if live else 0,
        'avg_adults': round(sum(b['adults'] for b in live) / n, 2) if live else 0,
        'non_refundable_pct': round(100 * sum(b['non_refundable'] for b in live) / n, 1) if live else 0,
        'payment_type': _top(Counter(b['payment_type'] for b in live)),
        'extras': _top(Counter(e['name'] for b in live for e in b['extras'])),
    }


def reservations(hotel_id, date_from='', date_to='', by='booking', out_dir='', progress=None):
    """Bookings of one hotel from the Mirai XML API, summarised for the playbook.

    by="booking": bookings MADE between the dates (default 1 Mar this year -> today).
    by="checkin": bookings ARRIVING between the dates (default today -> +90 days: what is on the books).
    """
    ok, where = configured()
    if not ok:
        return {'configured': False,
                'message': f'Mirai API credentials are not set up: {where}. Add MIRAI_USER and MIRAI_PASS to '
                           'the .env file in the work folder, or use the Reservations Excel export '
                           '(inputs checklist: Mirai reservations export).'}
    if by not in ('booking', 'checkin'):
        raise ValueError('by must be "booking" or "checkin"')
    today = date.today()
    if by == 'booking':
        start = date.fromisoformat(date_from) if date_from else date(today.year, 3, 1)
        end = date.fromisoformat(date_to) if date_to else today
    else:
        start = date.fromisoformat(date_from) if date_from else today
        end = date.fromisoformat(date_to) if date_to else today + timedelta(days=90)
    if end < start:
        raise ValueError('date_to is before date_from')
    hid = str(hotel_id).strip()

    windows = list(_windows(start, end))
    latest, hotels_seen, fetched, cached = {}, set(), 0, 0
    for i, (frm, to) in enumerate(windows, 1):
        before = time.time()
        data = _window(by, frm, to, progress)
        if data.get('fetched', 0) >= before:
            fetched += 1
        else:
            cached += 1
        hotels_seen.update(data['hotels'])
        for b in data['bookings']:
            if b['hotel_id'] == hid and (b['id'] not in latest or b['event_date'] >= latest[b['id']]['event_date']):
                latest[b['id']] = b
        if progress:
            progress(f'window {i}/{len(windows)} done ({len(latest)} bookings for {hid} so far)')

    key = 'reservation_date' if by == 'booking' else 'checkin'
    bookings = [b for b in latest.values() if b[key] and start.isoformat() <= b[key] <= end.isoformat()
                and _status(b) != 'duplicate']
    out = {'configured': True, 'credentials_from': where, 'hotel_id': hid, 'by': by,
           'from': str(start), 'to': str(end), 'windows': len(windows), 'fetched_now': fetched,
           'from_cache': cached, 'login_covers_hotels': len(hotels_seen)}
    if hid not in hotels_seen:
        # Mirai only lists hotels with some activity in the window, so a quiet hotel over a short range
        # looks the same as a hotel this login doesn't cover.
        out['warning'] = (f'Mirai returned nothing at all for hotel {hid} in this range ({len(hotels_seen)} other '
                          'hotels had activity). Either the Mirai ID is wrong (check team.md or idtokenprovider in '
                          'the site\'s booking links), this login does not cover the hotel, or it had no bookings, '
                          'changes or cancellations in the range.')
    out.update(summarise(bookings))

    dest = paths.resolve(out_dir) if out_dir else CACHE
    dest.mkdir(parents=True, exist_ok=True)
    detail = dest / f'mirai-{by}-{hid}-{start}-{end}.json'
    detail.write_text(json.dumps(sorted(bookings, key=lambda b: b['reservation_date']), indent=1,
                                 ensure_ascii=False), encoding='utf-8')
    out['detail_file'] = str(detail)
    out['note'] = ('Revenue is totalAmount (taxes included) of bookings not cancelled; ADR = revenue / room '
                   'nights. Offers and room types split a multi-room booking evenly. No guest names, '
                   'emails or phones are kept.')
    return out


# ---------------------------------------------------------------- login (fallback to .env)

def login():
    """hotel-seo-mirai-login: store Mirai XML API credentials for this machine (typed, not echoed).
    Usually not needed: MIRAI_USER / MIRAI_PASS in the work folder's .env are read first."""
    argparse.ArgumentParser(description='Save Mirai XML API credentials (fallback to MIRAI_USER / MIRAI_PASS '
                                        'in the work folder .env).').parse_args()
    print('Mirai XML API credentials (from integrations@mirai.com). Stored in', CREDS)
    user = input('Login: ').strip()
    pw = getpass.getpass('Password: ')
    if not user or not pw:
        raise SystemExit('Nothing saved.')
    paths.HOME.mkdir(parents=True, exist_ok=True)
    CREDS.write_text(json.dumps({'login': user, 'password': pw}), encoding='utf-8')
    try:
        CREDS.chmod(0o600)
    except OSError:
        pass
    print('Saved. Test with a short range: mirai_reservations(hotel_id, date_from=<7 days ago>).')
