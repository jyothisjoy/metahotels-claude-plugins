"""Booking.com facts for one hotel, cross-checked with the hotel's own booking engine.

Booking.com blocks plain fetching, so Claude opens the hotel's Booking.com page with Claude in Chrome, runs
EXTRACT_JS there (javascript_tool) and passes the JSON it returns to import_page(). That keeps:
  - the page's JSON-LD (name, address, rating, description),
  - the text of the facilities, house rules, surroundings, review and room sections,
  - the availability table rows (room names, sleeps, beds),
and turns them into typed facts: {"fact", "source": "Booking.com, <date>", "kind", "subject", "value"}.

Rule agreed with the user: a Booking.com fact is CONFIRMED for the [CONFIRM] guard only where the hotel's own booking
engine (booking_engine_snapshot) shows the same thing; then it is saved again with source
"Booking.com + booking engine, <date>". Booking.com-only facts stay unconfirmed. Disagreements (room size, occupancy,
cancellation wording) are written to facts-conflicts.json and become "Booking path & facts" findings.
Prices and discounts are never confirmed from Booking.com.
"""
import json
import re
from datetime import date

from . import paths

EXTRACT_JS = r"""
(() => {
  // hotel-seo Booking.com extractor: reads the page in the browser and keeps only the facts hotel-seo uses.
  const txt = el => (el ? el.innerText.replace(/\s+\n/g, '\n').replace(/[ \t]+/g, ' ').trim() : '');
  const one = sel => txt(document.querySelector(sel));
  const all = sel => [...document.querySelectorAll(sel)].map(txt).filter(Boolean).join('\n');
  const lines = s => s.split('\n').map(x => x.trim()).filter(Boolean);
  const out = {v: 2, url: location.origin + location.pathname};
  let ld = {};
  document.querySelectorAll('script[type="application/ld+json"]').forEach(s => {
    try { const j = JSON.parse(s.textContent); if (/Hotel|Lodging|Apartment|Resort|Hostel/.test(JSON.stringify(j['@type']))) ld = j; } catch (e) {}
  });
  const a = ld.address || {};
  out.name = ld.name || one('h2.pp-header__title, [data-testid="title"]');
  out.address = a.streetAddress || one('[data-testid="PropertyHeaderAddressDesktop-wrapper"]').split('\n')[0];
  out.country = a.addressCountry || '';
  out.rating = (ld.aggregateRating || {}).ratingValue || null;
  out.reviews = (ld.aggregateRating || {}).reviewCount || null;
  const starEl = document.querySelector('[data-testid="rating-stars"], [data-testid="rating-squares"]');
  out.stars = starEl ? (starEl.querySelectorAll('span, svg').length || null) : null;
  const rules = all('[data-testid="HouseRules-wrapper"], #hp_policies_box');
  const m = (re) => { const x = rules.match(re); return x ? x[1].trim() : ''; };
  out.checkin = m(/Check-in\s*\n\s*(?:From\s*)?([0-9]{1,2}:[0-9]{2}(?:\s*(?:to|-)\s*[0-9]{1,2}:[0-9]{2})?)/i);
  out.checkout = m(/Check-out\s*\n\s*(?:From\s*[0-9:]+\s*)?(?:until|to|Until)?\s*([0-9]{1,2}:[0-9]{2})/i);
  out.children = m(/Child policies\s*\n([^\n]+)/i);
  out.pets = m(/\nPets\s*\n([^\n]+)/i);
  out.min_age = m(/minimum age for check-in is (\d+)/i);
  out.cancellation = m(/Cancellation\/? ?prepayment\s*\n([^\n]+)/i);
  const fac = lines(all('[data-testid="property-most-popular-facilities-wrapper"], .hp_desc_important_facilities'))
    .filter(x => !/^most popular facilities$/i.test(x));
  out.facilities = [...new Set(fac)].slice(0, 40);
  const sur = lines(all('[data-testid="property-section--surroundings"], [data-testid="poi-block-list"], #hotel_surroundings'));
  out.nearby = [];
  for (let i = 0; i + 1 < sur.length; i++) {
    if (/^\d+(?:[.,]\d+)?\s*(?:km|m|mi)$/i.test(sur[i + 1]) && !/^\d/.test(sur[i])) { out.nearby.push([sur[i].slice(0, 60), sur[i + 1]]); i++; }
  }
  out.nearby = out.nearby.slice(0, 30);
  out.rooms = [];
  document.querySelectorAll('#hprt-table tbody tr').forEach(tr => {
    const name = txt(tr.querySelector('.hprt-roomtype-icon-link, .hprt-roomtype-link'));
    if (!name) return;
    const occEl = tr.querySelector('.hprt-occupancy-occupancy-info');
    const occ = occEl ? ((occEl.getAttribute('aria-label') || txt(occEl)).match(/\d+/) || [''])[0] : '';
    const size = (txt(tr).match(/(\d+(?:\.\d+)?)\s*(?:m²|m2|square met)/i) || [])[1] || '';
    out.rooms.push({name: name.slice(0, 80), sleeps: occ, beds: txt(tr.querySelector('.hprt-roomtype-bed')).slice(0, 80), size_m2: size});
  });
  // room sizes from the room pop-ups when the table has none
  document.querySelectorAll('.hprt-lightbox, [data-testid="roomPage"]').forEach(p => {
    const t = txt(p); const n = (t.split('\n')[0] || '').slice(0, 80); const s = (t.match(/(\d+(?:\.\d+)?)\s*(?:m²|m2)/i) || [])[1];
    const r = out.rooms.find(r => r.name === n);
    if (r && s && !r.size_m2) r.size_m2 = s;
    else if (!r && n && s) out.rooms.push({name: n, sleeps: '', beds: '', size_m2: s});
  });
  window.__hotelseo_json = JSON.stringify(out).replace(/(https?:\/\/[^\s"?#]+)[?#][^\s"]*/g, '$1');
  const size = 900;
  return JSON.stringify({length: window.__hotelseo_json.length, chunk_size: size,
                         chunks: Math.ceil(window.__hotelseo_json.length / size),
                         found: {name: !!out.name, stars: out.stars, checkin: out.checkin, facilities: out.facilities.length,
                                 nearby: out.nearby.length, rooms: out.rooms.length}});
})()
"""

HOW_TO = ('1. Open the hotel\'s Booking.com page in a NEW Claude in Chrome tab with dates, so the room table shows: '
          '<booking.com hotel URL>?checkin=<yyyy-mm-dd, ~30 days ahead>&checkout=<next day>&group_adults=2&no_rooms=1. '
          'Never sign in or type anything on Booking.com. '
          '2. Wait for the page, then run `window.scrollTo(0, document.body.scrollHeight)` and wait 2 s. '
          '3. Run the javascript below with javascript_tool. It returns {length, chunk_size, chunks, found}. '
          '4. For k = 0 .. chunks-1 run `window.__hotelseo_json.slice(k*900, (k+1)*900)` and keep each result exactly '
          '(the browser tool returns ~1,000 characters per call). '
          '5. Call import_bookingcom(hotel_dir, chunks=[...all chunk strings in order...]).')

TIME = re.compile(r'(\d{1,2}[:.]\d{2})')


def _norm_time(t):
    t = t.replace('.', ':')
    h, m = t.split(':')
    return f'{int(h):02d}:{m}'


def _ld_nodes(blocks):
    for b in blocks or []:
        nodes = b.get('@graph', [b]) if isinstance(b, dict) else b if isinstance(b, list) else []
        for n in nodes:
            if isinstance(n, dict):
                yield n


POI_PREFIX = re.compile(r'^(?:Restaurant|Cafe/bar|Train|Metro|Bus|Airport|Beach|Mountain|Lake|River|Sea/ocean|'
                        r'Natural beauty|Top attractions)(?=[A-Z0-9])')


def _parse_v2(p):
    """The compact v2 extractor output -> typed facts."""
    facts = []

    def add(kind, subject, value, text):
        if value not in (None, '', [], {}):
            facts.append({'kind': kind, 'subject': subject, 'value': value, 'fact': text})
    add('name', 'property', p.get('name'), f"Property name: {p.get('name')}")
    add('address', 'property', p.get('address'), f"Address: {p.get('address')}")
    if p.get('stars'):
        add('stars', 'property', int(p['stars']), f"{int(p['stars'])}-star")
    if p.get('rating'):
        add('review_score', 'property', f"{p['rating']}/10 from {p.get('reviews')} reviews",
            f"Booking.com guest rating {p['rating']}/10 ({p.get('reviews')} reviews)")
    if p.get('checkin'):
        add('checkin_time', 'property', p['checkin'], f"Check-in from {p['checkin']}")
    if p.get('checkout'):
        add('checkout_time', 'property', p['checkout'], f"Check-out until {p['checkout']}")
    for k, label in (('children', 'Children'), ('pets', 'Pets'), ('cancellation', 'Cancellation')):
        add(k, 'property', p.get(k), f"{label}: {p.get(k)}")
    if p.get('min_age'):
        add('age_restriction', 'property', p['min_age'], f"Minimum check-in age {p['min_age']}")
    if p.get('facilities'):
        add('facilities', 'property', p['facilities'], 'Facilities on Booking.com: ' + ', '.join(p['facilities']))
    near = [[POI_PREFIX.sub('', n).strip(), d] for n, d in p.get('nearby') or []]
    if near:
        add('nearby', 'property', [{'place': n, 'distance': d} for n, d in near],
            'Nearby on Booking.com: ' + '; '.join(f'{n} {d}' for n, d in near))
    for r in p.get('rooms') or []:
        name = re.sub(r'\s+-\s+Late check-out.*$', '', r.get('name', '')).strip()
        if not name:
            continue
        if r.get('size_m2'):
            add('room_size', name, f"{r['size_m2']} m²", f"{name}: {r['size_m2']} m²")
        if r.get('sleeps'):
            add('room_occupancy', name, int(r['sleeps']), f"{name}: up to {r['sleeps']} guests")
        if r.get('beds'):
            add('room_beds', name, r['beds'], f"{name}: {r['beds']}")
    return facts


def parse(page):
    """Typed facts from the extractor's JSON (a dict or the JSON string)."""
    if isinstance(page, str):
        page = json.loads(page)
    facts = []
    if page.get('v') == 2:
        return _parse_v2(page)

    def add(kind, subject, value, text):
        if value not in (None, '', [], {}):
            facts.append({'kind': kind, 'subject': subject, 'value': value, 'fact': text})
    for n in _ld_nodes(page.get('jsonld')):
        t = n.get('@type')
        types = t if isinstance(t, list) else [t]
        if not any(x in ('Hotel', 'LodgingBusiness', 'Apartment', 'Resort', 'Hostel') for x in types):
            continue
        add('name', 'property', n.get('name'), f"Property name: {n.get('name')}")
        addr = n.get('address') if isinstance(n.get('address'), dict) else {}
        street = ', '.join(str(addr.get(k)) for k in ('streetAddress', 'addressLocality', 'addressRegion',
                                                      'postalCode', 'addressCountry') if addr.get(k))
        add('address', 'property', street, f'Address: {street}')
        if addr.get('addressLocality'):
            add('city', 'property', addr['addressLocality'], f"City: {addr['addressLocality']}")
        ar = n.get('aggregateRating') or {}
        if ar.get('ratingValue'):
            add('review_score', 'property', f"{ar.get('ratingValue')}/{ar.get('bestRating', 10)} from "
                f"{ar.get('reviewCount') or ar.get('ratingCount', '?')} reviews",
                f"Booking.com guest rating {ar.get('ratingValue')}/{ar.get('bestRating', 10)} "
                f"({ar.get('reviewCount') or ar.get('ratingCount', '?')} reviews)")
        if n.get('description'):
            add('description', 'property', str(n['description'])[:600], 'Description: ' + str(n['description'])[:600])
    if page.get('stars'):
        add('stars', 'property', int(page['stars']), f"{int(page['stars'])}-star")
    rules = page.get('sections', {}).get('house_rules', '')
    for label, kind in (('check-in', 'checkin_time'), ('check-out', 'checkout_time')):
        m = re.search(label + r'[^\n]*?\n?[^\n]*?' + TIME.pattern, rules, re.I)
        if m:
            add(kind, 'property', _norm_time(m.group(1)), f'{label.capitalize()} from {_norm_time(m.group(1))}'
                if kind == 'checkin_time' else f'Check-out until {_norm_time(m.group(1))}')
    for label, kind in (('pets', 'pets'), ('children', 'children'), ('cancellation', 'cancellation'),
                        ('age restriction', 'age_restriction'), ('smoking', 'smoking'), ('parties', 'parties')):
        m = re.search(rf'(?im)^\s*{label}[^\n]*\n([^\n]+(?:\n(?!\s*[A-Z][a-z]+(?:\s[a-z/-]+){{0,2}}\s*$)[^\n]+){{0,3}})',
                      rules)
        if m:
            add(kind, 'property', m.group(1).strip()[:300], f'{label.capitalize()}: {m.group(1).strip()[:300]}')
    fac = page.get('sections', {}).get('popular_facilities', '') + '\n' + page.get('sections', {}).get('facilities', '')
    items = sorted({x.strip() for x in re.split(r'\n+', fac) if 2 < len(x.strip()) < 60})
    if items:
        add('facilities', 'property', items, 'Facilities on Booking.com: ' + ', '.join(items[:80]))
    for r in page.get('rooms', []):
        name = re.sub(r'\s+', ' ', r.get('name', '')).strip()
        if not name:
            continue
        if r.get('size_m2'):
            add('room_size', name, f"{r['size_m2']} m²", f"{name}: {r['size_m2']} m²")
        occ = re.search(r'(\d+)', r.get('occupancy') or '')
        if occ:
            add('room_occupancy', name, int(occ.group(1)), f'{name}: up to {occ.group(1)} guests')
        if r.get('beds'):
            add('room_beds', name, r['beds'], f"{name}: {r['beds']}")
    det = page.get('sections', {}).get('room_details', '')
    for m in re.finditer(r'([A-Z][^\n]{3,60})\n[^\n]*?(\d+(?:\.\d+)?)\s*(?:m²|m2)', det):
        if not any(f['kind'] == 'room_size' and f['subject'] == m.group(1).strip() for f in facts):
            add('room_size', m.group(1).strip(), f'{m.group(2)} m²', f'{m.group(1).strip()}: {m.group(2)} m²')
    sur = page.get('sections', {}).get('surroundings', '')
    near = []
    for m in re.finditer(r'([^\n]{3,70})\n?\s*(\d+(?:[.,]\d+)?)\s*(km|m)\b', sur):
        near.append({'place': m.group(1).strip(), 'distance': f'{m.group(2)} {m.group(3)}'})
    if near:
        add('nearby', 'property', near, 'Nearby on Booking.com: ' + '; '.join(f"{x['place']} {x['distance']}"
                                                                               for x in near[:40]))
    return facts


def _facts_doc(facts_file):
    f = paths.resolve(facts_file)
    return f, (json.loads(f.read_text(encoding='utf-8')) if f.exists() else {'facts': []})


def import_page(page, hotel_dir, facts_file='', on=None):
    """Save the extractor JSON in hotel_dir, add its facts (source "Booking.com, <date>") to hotel-facts.json and
    cross-check them with the latest booking-engine snapshot. Returns counts, conflicts and the confirmed facts."""
    on = on or date.today()
    d = paths.resolve(hotel_dir)
    d.mkdir(parents=True, exist_ok=True)
    if isinstance(page, str) and not page.lstrip().startswith('{'):
        page = paths.resolve(page).read_text(encoding='utf-8')
    if isinstance(page, str):
        page = json.loads(page)
    raw = d / f'bookingcom-{on.isoformat()}.json'
    raw.write_text(json.dumps(page, indent=1, ensure_ascii=False), encoding='utf-8')
    facts = parse(page)
    facts_file = facts_file or str(d / 'hotel-facts.json')
    f, doc = _facts_doc(facts_file)
    src = f'Booking.com, {on:%d %b %Y}'
    doc['facts'] = [x for x in doc.get('facts', []) if not str(x.get('source', '')).startswith('Booking.com, ')]
    doc['facts'].extend(dict(x, source=src) for x in facts)
    doc['bookingcom_url'] = page.get('url', '')
    f.write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding='utf-8')
    engine = latest_engine_snapshot(d)
    cross = crosscheck(facts_file, engine) if engine else {'checked': False,
                                                          'reason': 'no booking_engine.json for this hotel yet: run '
                                                                    'booking_engine_snapshot, then crosscheck_facts'}
    return {'saved': str(raw), 'facts_added': len(facts), 'by_kind': _count(facts), 'facts_file': str(f),
            'crosscheck': cross,
            'sections_found': sorted(page.get('sections', {})), 'rooms_found': len(page.get('rooms', [])),
            'next': 'Read the sections Booking.com returned (raw file) for anything the parser missed; add those with '
                    'add_facts and source "Booking.com, <date>". They stay unconfirmed unless the engine agrees.'}


def _count(facts):
    out = {}
    for x in facts:
        out[x['kind']] = out.get(x['kind'], 0) + 1
    return out


def latest_engine_snapshot(hotel_dir):
    found = sorted(paths.resolve(hotel_dir).rglob('booking_engine.json'), key=lambda p: p.stat().st_mtime)
    return str(found[-1]) if found else ''


def _num(s):
    m = re.search(r'(\d+(?:\.\d+)?)', str(s or ''))
    return float(m.group(1)) if m else None


def crosscheck(facts_file, engine_json, on=None):
    """Compare Booking.com facts with the booking-engine snapshot. Agreeing facts are saved again with source
    "Booking.com + booking engine, <date>"; disagreements go to facts-conflicts.json next to the facts file."""
    from .booking_engine import _match
    on = on or date.today()
    f, doc = _facts_doc(facts_file)
    eng = json.loads(paths.resolve(engine_json).read_text(encoding='utf-8'))
    rooms = (eng.get('summary') or {}).get('rooms') or eng.get('rooms') or []
    eng_rooms = {r['name']: r for r in rooms if r.get('name')}
    bc = [x for x in doc.get('facts', []) if str(x.get('source', '')).startswith('Booking.com, ')]
    confirmed, conflicts, unmatched = [], [], []
    for x in bc:
        if x.get('kind') not in ('room_size', 'room_occupancy'):
            continue
        name, score = _match(x['subject'], eng_rooms)
        if not name:
            unmatched.append(x['subject'])
            continue
        er = eng_rooms[name]
        if x['kind'] == 'room_size':
            a, b = _num(x['value']), _num(er.get('size'))
            if a is None or b is None:
                continue
            if abs(a - b) <= 1:
                confirmed.append({'fact': f"{name}: {int(b) if b == int(b) else b} m²", 'kind': 'room_size',
                                  'subject': name, 'value': f'{b} m²'})
            else:
                conflicts.append({'kind': 'room_size', 'room_engine': name, 'room_bookingcom': x['subject'],
                                  'engine': er.get('size'), 'bookingcom': x['value']})
        else:
            a, b = _num(x['value']), _num(er.get('max_occupancy'))
            if a is None or b is None:
                continue
            if a == b:
                confirmed.append({'fact': f'{name}: up to {int(b)} guests', 'kind': 'room_occupancy',
                                  'subject': name, 'value': int(b)})
            else:
                conflicts.append({'kind': 'room_occupancy', 'room_engine': name, 'room_bookingcom': x['subject'],
                                  'engine': er.get('max_occupancy'), 'bookingcom': x['value']})
    canc_bc = next((x['value'] for x in bc if x.get('kind') == 'cancellation'), '')
    canc_eng = (eng.get('summary') or {}).get('cancellation_options') or []
    if canc_bc and canc_eng:
        conflicts.append({'kind': 'cancellation_wording', 'engine': canc_eng, 'bookingcom': canc_bc,
                          'note': 'Compare by hand: wording differs between systems; a real mismatch is a finding.'})
    src = f'Booking.com + booking engine, {on:%d %b %Y}'
    doc['facts'] = [x for x in doc['facts'] if not str(x.get('source', '')).startswith('Booking.com + booking engine')]
    doc['facts'].extend(dict(x, source=src) for x in confirmed)
    f.write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding='utf-8')
    cf = f.with_name('facts-conflicts.json')
    cf.write_text(json.dumps({'checked_on': on.isoformat(), 'engine_snapshot': str(engine_json),
                              'conflicts': conflicts, 'bookingcom_rooms_not_on_engine': sorted(set(unmatched))},
                             indent=1, ensure_ascii=False), encoding='utf-8')
    return {'checked': True, 'confirmed': len(confirmed), 'conflicts': len(conflicts),
            'bookingcom_rooms_not_on_engine': sorted(set(unmatched)), 'conflicts_file': str(cf)}


def add_facts(facts_file, facts, source):
    """Add facts by hand (e.g. read from a PDF sheet or the Booking.com sections the parser missed). One value per
    fact (facts.add_facts): a hotel answer marks the booking-engine facts it contradicts superseded."""
    if not source or not re.search(r'\d{4}', source):
        raise ValueError('source must name where the fact came from and the date, e.g. "hotel contact, 24 Oct 2026"')
    from . import facts as fx
    return fx.add_facts(facts_file, facts, source)
