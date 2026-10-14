"""Mirai reservations through the Mirai XML API (getreservations, by reservation date).

Credentials are per machine in ~/.metahotels-seo/mirai.json: {"login": "...", "password": "..."}
(from integrations@mirai.com). Without them the tool says so and the skill falls back to the
Reservations Excel export.

API limits (Mirai XML API R.1.0.36): Basic auth, HTTPS GET, at most 31 days per request and one
request every 3 minutes. Each window's XML is cached in ~/.metahotels-seo/mirai-cache so re-runs
don't wait again; windows that end today are always refetched.
"""
import base64
import json
import time
import defusedxml.ElementTree as ET
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

import requests

from . import paths

CREDS = paths.HOME / 'mirai.json'
CACHE = paths.HOME / 'mirai-cache'
URL = 'https://channel.mirai.com/XMLIntegrationx/webservice_getreservations_Auth.apro'
MIN_GAP = 185  # seconds between calls (limit: one per 3 minutes)
_last_call = 0.0


def configured():
    return CREDS.exists()


def _auth():
    c = json.loads(CREDS.read_text(encoding='utf-8'))
    token = base64.b64encode(f"{c['login']}:{c['password']}".encode()).decode()
    return {'Authorization': f'Basic {token}', 'Accept-Encoding': 'gzip, deflate'}


def _num(v):
    """Mirai decimals use a comma: '727,74'."""
    try:
        return float(str(v).replace('.', '').replace(',', '.')) if v not in (None, '') else 0.0
    except ValueError:
        return 0.0


def _windows(start, end):
    cur = start
    while cur <= end:
        stop = min(cur + timedelta(days=30), end)
        yield cur, stop
        cur = stop + timedelta(days=1)


def _fetch(frm, to, progress=None):
    global _last_call
    CACHE.mkdir(parents=True, exist_ok=True)
    cached = CACHE / f'{frm}_{to}.xml'
    if cached.exists() and to < date.today():
        return cached.read_text(encoding='utf-8')
    wait = MIN_GAP - (time.time() - _last_call)
    if wait > 0:
        if progress:
            progress(f'waiting {int(wait)}s for the Mirai rate limit')
        time.sleep(wait)
    r = requests.get(URL, params={'from': f'{frm}T00:00:00', 'to': f'{to}T23:59:59'},
                     headers=_auth(), timeout=120)
    _last_call = time.time()
    if r.status_code == 401:
        raise RuntimeError('Mirai rejected the login (401). Check ~/.metahotels-seo/mirai.json.')
    r.raise_for_status()
    text = r.text
    if '<success' not in text:
        raise RuntimeError(f'Mirai returned an error for {frm}..{to}: {text[:300]}')
    if to < date.today():
        cached.write_text(text, encoding='utf-8')
    return text


def _parse(xml_text, hotel_id):
    root = ET.fromstring(xml_text)
    out = []
    for group in root.iter('bookings'):
        if hotel_id and group.get('hotelId') != str(hotel_id):
            continue
        for b in group.findall('booking'):
            stays = [s.get('date') for s in b.iter('stay') if s.get('date')]
            offers = sorted({r.get('idOffer') for r in b.iter('room') if r.get('idOffer')})
            cust = b.find('customer')
            out.append({
                'id': b.get('id'),
                'action': b.get('action'),
                'reservation_date': (b.get('reservationDate') or '')[:10],
                'checkin': min(stays) if stays else '',
                'nights': len(set(stays)),
                'total': _num(b.get('totalAmount')),
                'currency': b.get('currency'),
                'channel': b.get('channelSource') or '',
                'promo': b.get('promo') or '',
                'non_refundable': b.get('nonRefundable') == 'true',
                'country': cust.get('countryCode') if cust is not None else '',
                'offers': offers,
            })
    return out


def reservations(hotel_id, date_from='', date_to='', progress=None):
    """Bookings made between date_from and date_to (yyyy-mm-dd), summarised for the playbook."""
    if not configured():
        return {'configured': False,
                'message': 'Mirai API credentials are not set up on this machine. Use the Reservations '
                           'Excel export instead (inputs checklist: Mirai reservations export).'}
    start = date.fromisoformat(date_from) if date_from else date(date.today().year, 3, 1)
    end = date.fromisoformat(date_to) if date_to else date.today()
    latest = {}
    for frm, to in _windows(start, end):
        if progress:
            progress(f'fetching {frm}..{to}')
        for b in _parse(_fetch(frm, to, progress), hotel_id):
            latest[b['id']] = b      # later revisions (Modify / Cancel) replace earlier ones
    bookings = list(latest.values())
    live = [b for b in bookings if (b['action'] or '').lower() != 'cancel']

    by_month = defaultdict(lambda: {'bookings': 0, 'revenue': 0.0, 'nights': 0})
    for b in live:
        m = by_month[b['reservation_date'][:7]]
        m['bookings'] += 1
        m['revenue'] += b['total']
        m['nights'] += b['nights']
    stay_month = Counter(b['checkin'][:7] for b in live if b['checkin'])
    windows = []
    for b in live:
        if b['checkin'] and b['reservation_date']:
            windows.append((datetime.fromisoformat(b['checkin']) - datetime.fromisoformat(b['reservation_date'])).days)
    nights = sum(b['nights'] for b in live)
    revenue = sum(b['total'] for b in live)

    out_dir = paths.HOME / 'mirai-cache'
    detail = out_dir / f'bookings-{hotel_id}-{start}-{end}.json'
    detail.write_text(json.dumps(bookings, indent=1), encoding='utf-8')
    return {
        'configured': True,
        'hotel_id': str(hotel_id), 'from': str(start), 'to': str(end),
        'bookings': len(live), 'cancelled': len(bookings) - len(live),
        'revenue': round(revenue, 2), 'currency': next((b['currency'] for b in live if b['currency']), ''),
        'adr': round(revenue / nights, 2) if nights else 0,
        'avg_length_of_stay': round(nights / len(live), 2) if live else 0,
        'median_booking_window_days': sorted(windows)[len(windows) // 2] if windows else None,
        'by_booking_month': {k: {**v, 'revenue': round(v['revenue'], 2)} for k, v in sorted(by_month.items())},
        'by_stay_month': dict(sorted(stay_month.items())),
        'channel_source': dict(Counter(b['channel'] for b in live).most_common()),
        'promo_codes': dict(Counter(b['promo'] for b in live if b['promo']).most_common(15)),
        'offer_ids': dict(Counter(o for b in live for o in b['offers']).most_common(15)),
        'guest_country': dict(Counter(b['country'] for b in live if b['country']).most_common(15)),
        'non_refundable_share': round(sum(b['non_refundable'] for b in live) / len(live), 3) if live else 0,
        'detail_file': str(detail),
    }


def login():
    """hotel-seo-mirai-login: store Mirai XML API credentials for this machine (typed, not echoed)."""
    import getpass
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
