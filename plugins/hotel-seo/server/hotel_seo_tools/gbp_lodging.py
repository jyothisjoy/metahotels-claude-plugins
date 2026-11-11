"""Hotel amenities and policies on the Business Profile (Google's Lodging API), compared with the hotel's facts.

Reads (GET only):
  getLodging        GET  https://mybusinesslodging.googleapis.com/v1/{name=locations/*/lodging}?readMask=*
                    https://developers.google.com/my-business/reference/lodging/rest/v1/locations/getLodging
  getGoogleUpdated  GET  https://mybusinesslodging.googleapis.com/v1/{name=locations/*/lodging}:getGoogleUpdated?readMask=*
                    -> {"lodging": Lodging, "diffMask": "<fields Google changed itself>"}
                    https://developers.google.com/my-business/reference/lodging/rest/v1/locations.lodging/getGoogleUpdated
The write (updateLodging, PATCH with a required updateMask) is built here by lodging_op() and sent only through
gbp_write (propose -> approved apply):
                    https://developers.google.com/my-business/reference/lodging/rest/v1/locations/updateLodging
Field names: https://developers.google.com/my-business/reference/lodging/rest/v1/Lodging
  Every amenity is a value plus a "<field>Exception" sibling (EXCEPTION_UNSPECIFIED, UNDER_CONSTRUCTION,
  DEPENDENT_ON_SEASON, DEPENDENT_ON_DAY_OF_WEEK) for when the fact can't be given as a value.
  sustainability.sustainabilityCertifications is deprecated (no longer populated; Google gets it from BeCause): skipped.

Values in the table: "yes" / "no" / a number / "15:00", "exception: <reason>" when the profile gives a reason instead
of a value, and "not set" when Google holds nothing. Only confirmed facts (hotel-facts.json, never Booking.com alone)
become proposed changes; GBP values no fact backs are left alone and marked "unconfirmed".
"""
import json
import re

from . import facts as fx, paths
from .gbp import LODGING, GbpError, _find, _get, _safe

EXCEPTIONS = {'EXCEPTION_UNSPECIFIED', 'UNDER_CONSTRUCTION', 'DEPENDENT_ON_SEASON', 'DEPENDENT_ON_DAY_OF_WEEK'}
SKIP = {'name', 'metadata', 'allUnits', 'someUnits'}          # allUnits / someUnits are output only
DEPRECATED = {'sustainability.sustainabilityCertifications'}
TIME_FIELDS = {'checkinTime', 'checkoutTime'}

# Fields that can be changed through gbp_propose's "lodging" key: path -> (type, label). Each one has a verified
# "<field>Exception" sibling in the Lodging reference, which goes into the updateMask with it.
WRITABLE = {
    'policies.checkinTime': ('time', 'Check-in time'),
    'policies.checkoutTime': ('time', 'Check-out time'),
    'policies.smokeFreeProperty': ('bool', 'Smoke-free property'),
    'policies.kidsStayFree': ('bool', 'Kids stay free'),
    'policies.allInclusiveAvailable': ('bool', 'All-inclusive available'),
    'policies.paymentOptions.cash': ('bool', 'Pay by cash'),
    'policies.paymentOptions.creditCard': ('bool', 'Pay by credit card'),
    'policies.paymentOptions.debitCard': ('bool', 'Pay by debit card'),
    'policies.paymentOptions.mobileNfc': ('bool', 'Pay by phone (NFC)'),
    'property.roomsCount': ('int', 'Number of rooms'),
    'property.floorsCount': ('int', 'Number of floors'),
    'property.builtYear': ('int', 'Year built'),
    'property.lastRenovatedYear': ('int', 'Year last renovated'),
    'services.frontDesk': ('bool', 'Front desk'),
    'services.twentyFourHourFrontDesk': ('bool', '24-hour front desk'),
    'services.concierge': ('bool', 'Concierge'),
    'services.elevator': ('bool', 'Lift'),
    'services.baggageStorage': ('bool', 'Luggage storage'),
    'services.fullServiceLaundry': ('bool', 'Laundry service'),
    'services.currencyExchange': ('bool', 'Currency exchange'),
    'foodAndDrink.restaurant': ('bool', 'Restaurant'),
    'foodAndDrink.restaurantsCount': ('int', 'Number of restaurants'),
    'foodAndDrink.bar': ('bool', 'Bar'),
    'foodAndDrink.roomService': ('bool', 'Room service'),
    'foodAndDrink.twentyFourHourRoomService': ('bool', '24-hour room service'),
    'foodAndDrink.breakfastAvailable': ('bool', 'Breakfast available'),
    'foodAndDrink.freeBreakfast': ('bool', 'Free breakfast'),
    'foodAndDrink.breakfastBuffet': ('bool', 'Breakfast buffet'),
    'pools.pool': ('bool', 'Pool'),
    'pools.indoorPool': ('bool', 'Indoor pool'),
    'pools.outdoorPool': ('bool', 'Outdoor pool'),
    'pools.poolsCount': ('int', 'Number of pools'),
    'wellness.fitnessCenter': ('bool', 'Gym'),
    'wellness.spa': ('bool', 'Spa'),
    'wellness.sauna': ('bool', 'Sauna'),
    'wellness.massage': ('bool', 'Massage'),
    'transportation.airportShuttle': ('bool', 'Airport shuttle'),
    'transportation.freeAirportShuttle': ('bool', 'Free airport shuttle'),
    'transportation.carRentalOnProperty': ('bool', 'Car hire on site'),
    'families.kidsFriendly': ('bool', 'Kid-friendly'),
    'families.kidsClub': ('bool', 'Kids club'),
    'families.babysitting': ('bool', 'Babysitting'),
    'connectivity.wifiAvailable': ('bool', 'Wi-Fi'),
    'connectivity.freeWifi': ('bool', 'Free Wi-Fi'),
    'connectivity.publicAreaWifiAvailable': ('bool', 'Wi-Fi in public areas'),
    'parking.parkingAvailable': ('bool', 'Parking'),
    'parking.freeParking': ('bool', 'Free parking'),
    'parking.valetParkingAvailable': ('bool', 'Valet parking'),
    'parking.electricCarChargingStations': ('bool', 'EV charging'),
    'accessibility.mobilityAccessible': ('bool', 'Wheelchair accessible'),
    'accessibility.mobilityAccessibleElevator': ('bool', 'Accessible lift'),
    'accessibility.mobilityAccessibleParking': ('bool', 'Accessible parking'),
    'pets.petsAllowed': ('bool', 'Pets allowed'),
    'pets.petsAllowedFree': ('bool', 'Pets stay free'),
    'housekeeping.housekeepingAvailable': ('bool', 'Housekeeping'),
    'housekeeping.dailyHousekeeping': ('bool', 'Daily housekeeping'),
    'activities.beachAccess': ('bool', 'Beach access'),
    'activities.privateBeach': ('bool', 'Private beach'),
    'activities.beachFront': ('bool', 'Beachfront'),
    'business.businessCenter': ('bool', 'Business centre'),
    'business.meetingRooms': ('bool', 'Meeting rooms'),
}
# What a guest looks for first: shown as "not set" when Google has nothing for them.
KEY_FIELDS = ['policies.checkinTime', 'policies.checkoutTime', 'property.roomsCount', 'policies.paymentOptions.creditCard',
              'services.twentyFourHourFrontDesk', 'foodAndDrink.restaurant', 'foodAndDrink.breakfastAvailable',
              'foodAndDrink.freeBreakfast', 'foodAndDrink.roomService', 'pools.pool', 'wellness.fitnessCenter',
              'transportation.airportShuttle', 'families.kidsFriendly', 'connectivity.wifiAvailable',
              'connectivity.freeWifi', 'parking.parkingAvailable', 'parking.freeParking',
              'accessibility.mobilityAccessible', 'pets.petsAllowed', 'housekeeping.dailyHousekeeping']

# Confirmed-fact topics -> how to read them. kinds: the typed "kind" in hotel-facts.json (questionnaire, Booking.com,
# booking engine); label: the start of a free-text fact ("Check-in time: 15:00", "Parking: free").
TOPICS = {
    'checkin': {'kinds': {'checkin_time'}, 'label': r'check[- ]?in(?:\s*time)?(?:\s*from)?'},
    'checkout': {'kinds': {'checkout_time'}, 'label': r'check[- ]?out(?:\s*time)?(?:\s*(?:until|by))?'},
    'rooms': {'kinds': {'room_count'}, 'label': r'(?:number of (?:rooms|keys)(?:\s*/\s*apartments)?|room count|total rooms)'},
    'breakfast': {'kinds': {'breakfast'}, 'label': r'breakfast'},
    'parking': {'kinds': {'parking'}, 'label': r'(?:car\s*)?parking'},
    'pets': {'kinds': {'pets'}, 'label': r'pets?(?:\s*allowed\??)?'},
    'airport': {'kinds': {'airport_transfer'}, 'label': r'airport (?:transfer|shuttle)s?'},
    'wifi': {'kinds': {'wifi'}, 'label': r'wi-?fi|internet'},
}
TIME_RE = re.compile(r'\b(\d{1,2})(?:[:.](\d{2}))?\s*(a\.?m\.?|p\.?m\.?)?(?![\d%])', re.I)
NO_RE = re.compile(r'^\s*(?:no\b(?!\s*(?:charge|extra|fee|cost))|none|not (?:offered|available|allowed|provided|possible)|unavailable|n/?a)\b'
                   r'|\b(?:not allowed|not offered|not available|no pets)\b', re.I)
NOT_FREE_RE = re.compile(r'\b(?:not (?:included|free|complimentary)|paid|extra charge|(?<!no )(?<!of )charged?|surcharge|fee|'
                         r'aed|usd|dirhams?)\b|\$\s?\d', re.I)
FREE_RE = re.compile(r'\b(?:free|included|complimentary|inclusive|no charge)\b', re.I)
YES_RE = re.compile(r'^\s*(?:yes|y|available|allowed|offered|on request|provided)\b', re.I)
# The lodging fields each topic fills (see _values), and the hotel-facts.json kind the questionnaire's Facts sheet asks
# for them under: a Business Profile question on one of these fields goes to that Facts row, never a second row.
TOPIC_FIELDS = {'checkin': ['policies.checkinTime'], 'checkout': ['policies.checkoutTime'], 'rooms': ['property.roomsCount'],
                'breakfast': ['foodAndDrink.breakfastAvailable', 'foodAndDrink.freeBreakfast'],
                'parking': ['parking.parkingAvailable', 'parking.freeParking'],
                'pets': ['pets.petsAllowed', 'pets.petsAllowedFree'],
                'airport': ['transportation.airportShuttle', 'transportation.freeAirportShuttle'],
                'wifi': ['connectivity.wifiAvailable', 'connectivity.freeWifi']}
FIELD_KIND = {p: next(iter(TOPICS[t]['kinds'])) for t, ps in TOPIC_FIELDS.items() for p in ps}
# How a facility reads on Booking.com or on the website -> the lodging field it means ("yes" when it is mentioned).
AMENITY_WORDS = {
    'pools.pool': r'swimming pool|\bpool\b', 'wellness.fitnessCenter': r'fitness (?:centre|center|room)|\bgym\b',
    'wellness.spa': r'\bspa\b', 'wellness.sauna': r'\bsauna\b', 'foodAndDrink.restaurant': r'\brestaurant\b',
    'foodAndDrink.bar': r'\bbar\b(?!\s*code)', 'foodAndDrink.roomService': r'room service|in-room dining',
    'services.twentyFourHourFrontDesk': r'24[- ]hour front desk|24/7 reception|24-hour reception',
    'services.elevator': r'\belevator\b|\blift\b', 'services.fullServiceLaundry': r'laundry',
    'services.baggageStorage': r'luggage storage|baggage storage', 'connectivity.freeWifi': r'free wi-?fi',
    'parking.freeParking': r'free (?:private |public |on-site )?parking', 'parking.valetParkingAvailable': r'valet',
    'transportation.airportShuttle': r'airport (?:shuttle|transfer)', 'families.kidsClub': r'kids\'? club',
    'activities.privateBeach': r'private beach', 'activities.beachFront': r'beachfront|beach front',
    'business.meetingRooms': r'meeting rooms?|conference', 'business.businessCenter': r'business cent(?:re|er)',
    'accessibility.mobilityAccessible': r'wheelchair|accessible rooms?',
}


def mentions(text):
    """{lodging field: "yes"} for every facility AMENITY_WORDS finds in a text (a Booking.com facility, a page)."""
    return {p: 'yes' for p, rx in AMENITY_WORDS.items() if re.search(rx, str(text or ''), re.I)}


def answer_value(path, text):
    """A hotel's written answer for one lodging field -> its lodging value ("yes" / "no" / "15:00" / "12"), or None
    when the answer doesn't give one ("don't know", a comment)."""
    t = str(text if text is not None else '').strip()
    if not t or re.match(r"^\s*(?:don'?t|do not|not sure|unsure|no idea|unknown|n/?a\b|\?)", t, re.I):
        return None
    typ = WRITABLE.get(path, ('',))[0] or ('time' if path.endswith('Time') else
                                         'int' if re.search(r'(?:Count|Year)$', path) else 'bool')
    if typ == 'time':
        return _time(t) or (_time(t + ':00') if re.fullmatch(r'\d{1,2}', t) else None)
    if typ == 'int':
        m = re.search(r'\d+', t)
        return str(int(m.group(0))) if m else None
    if re.match(r'^\s*(?:yes|y|true|available|offered|allowed|provided|included|free)\b', t, re.I):
        return 'yes'
    if re.match(r'^\s*(?:no|n|false|not|none)\b', t, re.I):
        return 'no'
    return None


# ---------- reading ----------

def _loc_name(location):
    """locations/<id> for an id, a "locations/<id>" or anything _find accepts (website, name)."""
    s = str(location).strip()
    if re.fullmatch(r'(locations/)?\d+', s):
        return f"locations/{s.split('/')[-1]}"
    return _find(s)[1]['name']


def fetch(loc_name):
    """The lodging record, or {} when the profile has none yet (Google answers 404)."""
    try:
        return _get(f'{LODGING}/{loc_name}/lodging', {'readMask': '*'})
    except GbpError as e:
        if str(e).startswith('404 '):
            return {}
        raise


def fetch_google_updated(loc_name):
    try:
        return _get(f'{LODGING}/{loc_name}/lodging:getGoogleUpdated', {'readMask': '*'})
    except GbpError as e:
        if str(e).startswith('404 '):
            return {}
        raise


def _hhmm(t):
    t = t or {}
    return f"{int(t.get('hours', 0)):02d}:{int(t.get('minutes', 0)):02d}"   # proto3 drops zeros: {} is midnight


def _show(v):
    if isinstance(v, bool):
        return 'yes' if v else 'no'
    return str(v)


def _label(path):
    if path in WRITABLE:
        return WRITABLE[path][1]
    leaf = path.split('.')[-1]
    return re.sub(r'(?<!^)(?=[A-Z])', ' ', leaf).capitalize()


def _walk(obj, prefix, out):
    for k, v in obj.items():
        path = f'{prefix}.{k}' if prefix else k
        if (not prefix and k in SKIP) or path in DEPRECATED:
            continue
        if k.endswith('Exception'):
            base = path[:-len('Exception')]
            out.setdefault(base, {})['exception'] = v
            continue
        if k in TIME_FIELDS and isinstance(v, dict):
            out.setdefault(path, {})['value'] = _hhmm(v)
        elif isinstance(v, dict):
            _walk(v, path, out)
        elif isinstance(v, list):
            for i, item in enumerate(v):
                if not isinstance(item, dict):
                    out.setdefault(f'{path}[{i}]', {})['value'] = _show(item)
                    continue
                key = item.get('languageCode') or item.get('label') or str(i)
                _walk({x: y for x, y in item.items() if x not in ('languageCode', 'label')}, f'{path}[{key}]', out)
        else:
            out.setdefault(path, {})['value'] = _show(v)


def flat(lodging):
    """{path: {"value": "yes" | "15:00" | "12", "exception": "DEPENDENT_ON_SEASON"}} for every field Google holds."""
    out = {}
    _walk(lodging or {}, '', out)
    return out


def state(entry):
    """The readable value: the value, "exception: <reason>", or "not set"."""
    if not entry:
        return 'not set'
    if 'value' in entry:
        return entry['value']
    reason = str(entry.get('exception', 'EXCEPTION_UNSPECIFIED'))
    return 'exception: ' + ('unspecified' if reason == 'EXCEPTION_UNSPECIFIED' else reason.lower().replace('_', ' '))


def table(lodging):
    """One row per field Google holds, plus "not set" rows for the key hotel fields. Sorted by section."""
    f = flat(lodging)
    rows = [{'field': p, 'label': _label(p), 'value': state(e)} for p, e in f.items()]
    rows += [{'field': p, 'label': _label(p), 'value': 'not set'} for p in KEY_FIELDS if p not in f]
    return sorted(rows, key=lambda r: r['field'])


# ---------- facts -> lodging values ----------

def _time(text):
    for m in TIME_RE.finditer(text or ''):
        h, mi, ap = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or '').lower().replace('.', '')
        if not m.group(2) and not ap:
            continue                         # a bare number ("2") is not a time
        if ap == 'pm' and h < 12:
            h += 12
        elif ap == 'am' and h == 12:
            h = 0
        if h <= 23 and mi <= 59:
            return f'{h:02d}:{mi:02d}'
    return None


def _avail_free(text):
    """(available, free) from "free", "paid", "included", "no", "yes" ...; None where the text doesn't say."""
    t = str(text or '')
    if NO_RE.search(t):
        return False, None
    paid, free = bool(NOT_FREE_RE.search(t)), bool(FREE_RE.search(t))
    if paid and free and not re.search(r'\bnot (?:included|free|complimentary)\b', t, re.I):
        return True, None                    # "free valet, paid public parking": available, free unclear
    if paid:
        return True, False
    if free:
        return True, True
    if YES_RE.search(t):
        return True, None
    return None, None


def _values(topic, value):
    """{lodging path: value} a fact on this topic states. Empty when the wording is unclear."""
    v = str(value if not isinstance(value, (list, dict)) else '').strip()
    if topic in ('checkin', 'checkout'):
        t = _time(v)
        return {f'policies.{topic}Time': t} if t else {}
    if topic == 'rooms':
        m = re.search(r'\d+', v)
        return {'property.roomsCount': str(int(m.group(0)))} if m else {}
    avail, free = _avail_free(v)
    paths_ = {'breakfast': ('foodAndDrink.breakfastAvailable', 'foodAndDrink.freeBreakfast'),
              'parking': ('parking.parkingAvailable', 'parking.freeParking'),
              'pets': ('pets.petsAllowed', 'pets.petsAllowedFree'),
              'airport': ('transportation.airportShuttle', 'transportation.freeAirportShuttle'),
              'wifi': ('connectivity.wifiAvailable', 'connectivity.freeWifi')}[topic]
    out = {}
    if avail is not None:
        out[paths_[0]] = _show(avail)
    if free is not None and topic != 'pets':          # "pets: free" is too rare to read reliably
        out[paths_[1]] = _show(free)
    if topic == 'breakfast' and avail is False:
        out[paths_[1]] = 'no'
    return out


def _topic_of(fact):
    """(topic, value text) for a hotel-facts.json row, or (None, None)."""
    kind = fact.get('kind')
    for topic, spec in TOPICS.items():
        if kind in spec['kinds']:
            return topic, str(fact.get('value') if fact.get('value') not in (None, '') else fact.get('fact', ''))
    text = str(fact.get('fact') or '')
    text = re.sub(r'^[^:–]{0,40}\s–\s', '', text)       # info sheet "Policies – Check-in time: 15:00"
    for topic, spec in TOPICS.items():
        m = re.match(rf"\s*(?:{spec['label']})\s*(?::|-|\s)\s*(.+)$", text, re.I)
        if m:
            return topic, m.group(1)
    return None, None


def confirmed_values(facts_file):
    """{path: {"value", "fact", "source"}} from confirmed facts. A hotel answer beats the booking engine; two
    confirmed facts of the same weight that disagree go to "conflicts" and propose nothing."""
    f = paths.resolve(facts_file) if facts_file else None
    rows = json.loads(f.read_text(encoding='utf-8')).get('facts', []) if f and f.exists() else []
    best, conflicts = {}, {}
    for x in rows:
        if x.get('superseded') or not fx.is_confirmed_source(x.get('source')):
            continue
        weight = 1 if fx.is_hotel_source(x.get('source')) else 0
        if x.get('kind') == 'lodging' and x.get('subject'):
            # the questionnaire's Business Profile sheet: one field, answered directly
            v = answer_value(x['subject'], x.get('value'))
            vals = {x['subject']: v} if v is not None else {}
        else:
            topic, text = _topic_of(x)
            if not topic:
                continue
            vals = _values(topic, text)
        for p, v in vals.items():
            rec = {'value': v, 'fact': x.get('fact', ''), 'source': x.get('source', ''), 'weight': weight}
            have = best.get(p)
            if have is None or weight > have['weight']:
                best[p] = rec
                conflicts.pop(p, None)
            elif weight == have['weight'] and v != have['value']:
                conflicts.setdefault(p, [have]).append(rec)
    for p in conflicts:
        best.pop(p, None)
    return best, conflicts


def compare(lodging, facts_file):
    """Mismatches, gaps (a confirmed fact the profile leaves unset or answers with an exception), matches, GBP values
    with no confirmed fact ("unconfirmed"), and the ready `changes` dict for gbp_propose (confirmed facts only)."""
    f = flat(lodging)
    want, conflicts = confirmed_values(facts_file)
    out = {'mismatches': [], 'gaps': [], 'matches': [], 'unconfirmed': [], 'conflicting_facts': [], 'changes': {}}
    for p, rec in sorted(want.items()):
        now = state(f.get(p))
        row = {'field': p, 'label': _label(p), 'gbp': now, 'confirmed': rec['value'], 'fact': rec['fact'],
               'source': rec['source']}
        if now == rec['value']:
            out['matches'].append(row)
            continue
        out['gaps' if 'value' not in (f.get(p) or {}) else 'mismatches'].append(row)
        if p not in WRITABLE:
            row['manual'] = True             # not changeable through the API: change it in the profile itself
            continue
        typ = WRITABLE[p][0]
        out['changes'][p] = (rec['value'] == 'yes') if typ == 'bool' else int(rec['value']) if typ == 'int' else rec['value']
    for p, recs in sorted(conflicts.items()):
        out['conflicting_facts'].append({'field': p, 'label': _label(p), 'gbp': state(f.get(p)),
                                         'facts': [f"{r['fact']} ({r['source']})" for r in recs]})
    for p, e in sorted(f.items()):
        if p not in want and p not in conflicts and 'value' in e:
            out['unconfirmed'].append({'field': p, 'label': _label(p), 'gbp': e['value']})
    return out


def _facts_file(group_dir, slug):
    from . import group as grp
    return str(grp.hotel_dir(group_dir, slug) / 'hotel-facts.json')


@_safe
def amenities(location, facts_file='', out_dir=''):
    """The lodging table, what Google changed itself, the comparison with confirmed facts and a ready `changes`.
    out_dir (the hotel's gbp folder): also saved as amenities-<date>.json, with the raw lodging record, for
    hotel_questions (it compares that record with the facts again at each build)."""
    out = _amenities(location, facts_file)
    if out_dir:
        from datetime import date
        d = paths.resolve(out_dir)
        d.mkdir(parents=True, exist_ok=True)
        f = d / f'amenities-{date.today().isoformat()}.json'
        f.write_text(json.dumps(dict(out, saved=date.today().isoformat()), indent=1, ensure_ascii=False),
                     encoding='utf-8')
        out['file'] = str(f)
    out.pop('lodging', None)                 # the raw record is in the file; the reply keeps the table
    return out


def _amenities(location, facts_file=''):
    name = _loc_name(location)
    lodging = fetch(name)
    try:
        gu = fetch_google_updated(name)
    except GbpError as e:
        gu = {'error': str(e)[:300]}
    rows = table(lodging)
    cmp_ = compare(lodging, facts_file)
    google_changed = []
    if gu.get('diffMask'):
        gf = flat(gu.get('lodging') or {})
        for p in [m.strip() for m in gu['diffMask'].split(',') if m.strip()]:
            base = p[:-len('Exception')] if p.endswith('Exception') else p
            google_changed.append({'field': base, 'label': _label(base), 'google_value': state(gf.get(base)),
                                   'profile_value': state(flat(lodging).get(base))})
    changes = {'lodging': cmp_['changes']} if cmp_['changes'] else {}
    return {
        'checked': True, 'location': name, 'has_lodging_data': bool(lodging),
        'updated': ((lodging.get('metadata') or {}).get('updateTime') or ''),
        'fields_set': sum(1 for r in rows if r['value'] != 'not set' and not r['value'].startswith('exception')),
        'key_fields_not_set': [r['label'] for r in rows if r['value'] == 'not set'],
        'table': rows,
        'google_changed': google_changed,
        'google_updated_error': gu.get('error', ''),
        **{k: cmp_[k] for k in ('mismatches', 'gaps', 'matches', 'conflicting_facts', 'unconfirmed')},
        'facts_file': facts_file,
        'changes': changes,
        'lodging': lodging,
        'next': ('Show the mismatches and gaps; with the user\'s go-ahead, gbp_propose(location, changes, '
                 '"<hotel dir>/gbp/changes"). Unconfirmed values stay as they are; ask the hotel about them if they '
                 'look wrong (add the answer with add_facts).') if changes else
                'Nothing to propose from confirmed facts.',
    }


def summary(loc_name):
    """Short lodging summary for gbp.report: fields set, key fields not set, what Google changed itself."""
    lodging = fetch(loc_name)
    rows = table(lodging)
    out = {'has_lodging_data': bool(lodging),
           'fields_set': sum(1 for r in rows if r['value'] != 'not set' and not r['value'].startswith('exception')),
           'key_fields_not_set': [r['label'] for r in rows if r['value'] == 'not set']}
    try:
        gu = fetch_google_updated(loc_name)
        out['google_changed'] = gu.get('diffMask', '')
    except GbpError:
        pass
    return out


# ---------- the write (gbp_write's "lodging" key) ----------

def _flatten_changes(ch, prefix=''):
    out = {}
    for k, v in ch.items():
        p = f'{prefix}.{k}' if prefix else str(k)
        if isinstance(v, dict) and p not in WRITABLE:
            out.update(_flatten_changes(v, p))
        else:
            out[p] = v
    return out


def _value(path, v):
    """(body value or None, exception or None, readable after) for one change, validated."""
    typ, label = WRITABLE[path]
    if v is None:
        return None, None, 'not set'
    if isinstance(v, str) and v.strip().upper() in EXCEPTIONS:
        e = v.strip().upper()
        return None, e, state({'exception': e})
    if typ == 'time':
        t = _time(str(v)) if isinstance(v, str) and re.fullmatch(r'\s*\d{1,2}[:.]\d{2}\s*(?:[ap]\.?m\.?)?\s*', v, re.I) else None
        if not t:
            raise GbpError(f'{label} ({path}) takes a time like "15:00"')
        h, m = (int(x) for x in t.split(':'))
        return {'hours': h, 'minutes': m}, None, t
    if typ == 'int':
        if isinstance(v, bool) or not isinstance(v, int) and not re.fullmatch(r'\d+', str(v).strip()):
            raise GbpError(f'{label} ({path}) takes a whole number')
        n = int(v)
        if n < 0 or n > 100000:
            raise GbpError(f'{label} ({path}) = {n} is out of range')
        return n, None, str(n)
    if not isinstance(v, bool):
        raise GbpError(f'{label} ({path}) takes true or false')
    return v, None, _show(v)


def _set(body, path, value):
    parts = path.split('.')
    d = body
    for p in parts[:-1]:
        d = d.setdefault(p, {})
    d[parts[-1]] = value


def live_values(lodging, fields):
    """{path: readable value} for the stale check and read-back (same shape at proposal and at apply)."""
    f = flat(lodging)
    return {p: state(f.get(p)) for p in fields}


def lodging_op(name, changes):
    """The updateLodging op for gbp_write.propose: validated, with updateMask = each field and its Exception sibling
    (a field in the mask but not in the body is cleared, so setting a value clears an old exception and vice versa)."""
    if not isinstance(changes, dict) or not changes:
        raise GbpError('lodging takes {"policies.checkinTime": "15:00", "parking.freeParking": true, ...}')
    ch = _flatten_changes(changes)
    unknown = [p for p in ch if p not in WRITABLE]
    if unknown:
        raise GbpError(f'lodging fields {unknown} are not changeable here; changeable: {sorted(WRITABLE)}')
    current = fetch(name)
    before = live_values(current, ch)
    body, mask, rows = {'name': f'{name}/lodging'}, [], []
    afters = {}
    for p, v in ch.items():
        val, exc, after = _value(p, v)
        if before[p] == after:
            continue                         # already on the profile: left out of the mask
        if val is not None:
            _set(body, p, val)
        if exc is not None:
            _set(body, p + 'Exception', exc)
        mask += [p, p + 'Exception']
        afters[p] = after
        rows.append((f'Hotel details: {WRITABLE[p][1]}', before[p], after))
    if not rows:
        raise GbpError('the profile already shows these lodging values; nothing to change')
    return {'kind': 'lodging', 'rows': rows, 'method': 'PATCH', 'url': f'{LODGING}/{name}/lodging',
            'params': {'updateMask': ','.join(mask)}, 'body': body,
            'before': {p: before[p] for p in afters}, 'after': afters, 'google_validated': False}
