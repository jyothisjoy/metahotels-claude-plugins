"""Booking engine snapshot: what the hotel actually sells, read from the live Mirai engine.

A Playwright session opens the hotel's own booking page (<site>/search/?idtokenprovider=<id>&checkin=...)
for a few sample stays and keeps the JSON the engine loads itself:

  reservation.mirai.com/.../booking/rates   rooms, rates, offers, member (club) discount, boards,
                                            cancellation terms, prices, taxes, availability
  index-price.mirai.com/<id>/<MMYYYY>.json  lowest price per night for each month shown
  engine.mirai.com/HOTEL/<id>.json          engine settings (booking window, club, tracking)

It then renders the website's room, offer and loyalty pages in the same session and compares:
room sizes and occupancy on the site vs the engine, offers sold with no page, offer pages with no
matching rate, and the member discount the site claims.

Writes booking_engine.json (everything), booking_engine.md (summary) and a screenshot per stay.
Reading only: never selects a room or starts a booking.
"""
import json
import re
import time
from collections import Counter, defaultdict
from datetime import date, timedelta
from urllib.parse import urlparse

from . import paths

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
      'Chrome/140.0.0.0 Safari/537.36')
STOP = {'room', 'rooms', 'suite', 'the', 'and', 'with', 'view', 'offer', 'package', 'stay', 'deal', 'at', 'a',
        'for', 'of', 'in', '&', '-', '–', 'hotel', 'resort', 'special'}


# ---------------------------------------------------------------- sample stays

def default_stays(today=None, peak_month=12, max_days=100):
    """Next weekend, about 30 days out, and mid peak month: 1 night, 2 adults."""
    today = today or date.today()
    fri = today + timedelta(days=(4 - today.weekday()) % 7 or 7)
    if (fri - today).days < 3:
        fri += timedelta(days=7)
    out = [('next weekend', fri), ('in about 30 days', today + timedelta(days=30))]
    year = today.year if peak_month >= today.month else today.year + 1
    peak = date(year, peak_month, 15)
    if peak > today + timedelta(days=max_days - 1):
        peak = today + timedelta(days=max_days - 1)
    if all(abs((peak - d).days) > 7 for _, d in out):
        out.append((f'peak month ({peak:%b})', peak))
    return [{'label': l, 'checkin': d.isoformat(), 'nights': 1, 'adults': 2} for l, d in out]


# ---------------------------------------------------------------- parsing

def _f(v):
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


def parse_rates(data):
    """Rooms and their rates from the booking/rates response."""
    items = ((data or {}).get('data') or {}).get('items') or []
    rooms = []
    for it in items:
        canc = {c.get('id'): c.get('name') for c in it.get('cancellations') or []}
        rate_names = {r.get('id'): r for r in it.get('rates') or []}
        offers = []
        for b in it.get('boards') or []:
            r = rate_names.get(b.get('rateId'), {})
            club = [x for x in ((b.get('discount') or {}).get('breakdown') or [])]
            offers.append({
                'rate': r.get('name', ''), 'offer': bool(r.get('offer')), 'club_rate': bool(r.get('isClub')),
                'rate_discount_pct': r.get('discountPercentage'),
                'board': b.get('name', ''), 'cancellation': canc.get(b.get('cancellationId'), ''),
                'payment': b.get('paymentConditions', ''),
                'price': _f(b.get('price')), 'before_discount': _f(b.get('originalPrice') or b.get('basePrice')),
                'taxes': _f(b.get('taxes')),
                'total_discount_pct': (b.get('discount') or {}).get('percentage'),
                'discount_breakdown': [{'pct': x.get('percentage'), 'value': _f(x.get('value')), 'type': x.get('type')}
                                       for x in club],
            })
        rooms.append({
            'name': it.get('name', ''), 'size': it.get('size', ''), 'max_occupancy': it.get('maxOccupation'),
            'available': it.get('availability'), 'sold_out': bool(it.get('soldOut')),
            'beds': [b.get('name') or b.get('type') if isinstance(b, dict) else b for b in it.get('bedTypes') or []],
            'amenities': [a.get('text') for a in it.get('amenities') or [] if a.get('text')],
            'description': (it.get('description') or '')[:400],
            'rates': offers,
        })
    return rooms


def summarise(stays):
    """Mirai's discount breakdown: type 0 is the member (club) discount, type 1 the offer's own."""
    offers, boards, cancels, club = defaultdict(list), Counter(), Counter(), Counter()
    rooms = {}
    for s in stays:
        for r in s.get('rooms', []):
            rooms.setdefault(r['name'], {k: r[k] for k in ('name', 'size', 'max_occupancy', 'beds', 'amenities')})
            for x in r['rates']:
                own = [d['pct'] for d in x['discount_breakdown'] if d['type'] == 1 and d['pct']]
                if x['offer'] or own:
                    offers[x['rate']].extend(own or [x['rate_discount_pct'] or 0])
                boards[x['board']] += 1
                cancels[x['cancellation']] += 1
                for d in x['discount_breakdown']:
                    if d['type'] == 0 and d['pct']:
                        club[d['pct']] += 1
    return {
        'rooms': list(rooms.values()),
        'offers': [{'rate': n, 'discount_pct': round(max(p)) if p else None,
                    'discount_range': f'{round(min(p))}–{round(max(p))}%' if p and min(p) != max(p) else
                    (f'{round(max(p))}%' if p else ''), 'seen': len(p)}
                   for n, p in sorted(offers.items(), key=lambda kv: -len(kv[1]))],
        'member_discount_pct': [p for p, _ in club.most_common()],
        'boards': [b for b, _ in boards.most_common()],
        'cancellation_options': [c for c, _ in cancels.most_common() if c],
        'lowest_price_per_stay': {s['label']: min((x['price'] for r in s.get('rooms', []) for x in r['rates']
                                                   if x['price']), default=None) for s in stays},
    }


def calendar_summary(cal):
    by_month, by_dow = {}, defaultdict(list)
    for month, data in sorted(cal.items(), key=lambda kv: (kv[0][-4:], kv[0][:-4].zfill(2))):
        prices = {d: p for d, p in (data.get('prices') or {}).items() if p}
        if not prices:
            continue
        vals = list(prices.values())
        by_month[month] = {'nights_priced': len(vals), 'min': min(vals), 'max': max(vals),
                           'avg': round(sum(vals) / len(vals), 2),
                           'highest_dates': sorted(prices, key=lambda d: -prices[d])[:5]}
        for d, p in prices.items():
            dd, mm, yy = (int(x) for x in d.split('/'))
            by_dow[date(yy, mm, dd).strftime('%a')].append(p)
    return {'by_month': by_month,
            'avg_by_weekday': {k: round(sum(v) / len(v), 2) for k, v in by_dow.items()},
            'currency': next((c.get('currency') for c in cal.values() if c.get('currency')), '')}


# ---------------------------------------------------------------- website comparison

def _tokens(s):
    return {w for w in re.findall(r'[a-z0-9]+', (s or '').lower()) if w not in STOP and len(w) > 1}


def _match(name, candidates, need=0.6):
    """Best candidate by shared words, ignoring words on most candidates (the hotel name)."""
    candidates = list(candidates)
    df = Counter(w for c in candidates for w in _tokens(c))
    common = {w for w, n in df.items() if len(candidates) >= 3 and n > len(candidates) / 2}
    t = _tokens(name) - common
    best, score = None, 0
    for c in candidates:
        ct = _tokens(c) - common
        if not t or not ct:
            continue
        s = len(t & ct) / len(t)
        if s > score:
            best, score = c, s
    return (best, round(score, 2)) if score >= need else (None, round(score, 2))


def compare(summary, site_pages):
    """site_pages: {url: {'title', 'h1', 'text', 'type'}} rendered in the same session."""
    out = {'rooms': [], 'offers_without_page': [], 'offer_pages_without_rate': [], 'member_discount_on_site': []}
    room_pages = {u: p for u, p in site_pages.items() if p['type'] == 'rooms'
                  and urlparse(u).path.strip('/').count('/') >= 1}       # /room/<name>/, not the listing page
    offer_pages = {u: p for u, p in site_pages.items() if p['type'] == 'offers'}
    heads = {u: f"{p['h1']} {p['title']}" for u, p in room_pages.items()}
    for r in summary['rooms']:
        url, score = _match(r['name'], heads.values())
        url = next((u for u, h in heads.items() if h == url), None)
        row = {'room': r['name'], 'engine_size': r['size'], 'engine_max_occupancy': r['max_occupancy'],
               'site_page': url, 'match': score}
        if url:
            text = room_pages[url]['text']
            num = re.search(r'\d+', r['size'] or '')
            row['size_on_page'] = bool(num and re.search(rf'\b{num.group(0)}\s?(m²|m2|sqm|sq\.? ?m|square)', text, re.I))
            sizes = sorted({m.group(1) for m in re.finditer(r'(\d{2,4})\s?(?:m²|m2|sqm|sq\.? ?m)', text, re.I)})
            row['sizes_on_page'] = sizes
            occ = re.findall(r'(?:up to|max(?:imum)?|sleeps)\s*(\d+)\s*(?:adults|guests|people|persons)', text, re.I)
            row['occupancy_on_page'] = sorted(set(occ))
        out['rooms'].append(row)
    offer_heads = {u: f"{p['h1']} {p['title']} {urlparse(u).path.replace('-', ' ')}" for u, p in offer_pages.items()
                   if urlparse(u).path.strip('/').count('/') >= 1}
    matched_pages = set()
    for o in summary['offers']:
        best, score = _match(o['rate'], offer_heads.values(), need=0.5)
        if best is None:
            out['offers_without_page'].append(o)
        else:
            matched_pages.add(next(u for u, h in offer_heads.items() if h == best))
    out['offer_pages_without_rate'] = sorted(set(offer_heads) - matched_pages)
    for u, p in site_pages.items():
        for m in re.finditer(r'(\d{1,2})\s?%[^.]{0,60}?(member|club|rewards|loyalty|direct)', p['text'], re.I):
            out['member_discount_on_site'].append({'url': u, 'pct': int(m.group(1)),
                                                   'context': p['text'][max(0, m.start() - 40):m.end() + 20]})
    return out


# ---------------------------------------------------------------- session

def _page_type(url):
    path = urlparse(url).path.lower()
    if re.search(r'/(blog|blogs|news)/', path):
        return 'other'
    if re.search(r'/(rooms?|suites?|accommodation|apartments?)(/|-|$)', path):
        return 'rooms'
    if re.search(r'offer|package|deal|promo', path):
        return 'offers'
    if re.search(r'loyal|reward|club|member', path):
        return 'loyalty'
    return 'other'


def _site_urls(crawl_dir, site, limit=60):
    """Room, offer and loyalty pages from the crawl (or just the homepage without one)."""
    if not crawl_dir:
        return [site.rstrip('/') + '/']
    from .librecrawl import is_page
    data = json.loads((paths.resolve(crawl_dir) / 'crawl.json').read_text(encoding='utf-8'))
    host = urlparse(site).netloc.replace('www.', '')
    urls = [u['url'] for u in data['urls'] if is_page(u) and urlparse(u['url']).netloc.replace('www.', '') == host
            and not urlparse(u['url']).query]
    keep = [u for u in urls if _page_type(u) != 'other']
    return [site.rstrip('/') + '/'] + keep[:limit]


def snapshot(site, hotel_id, out_dir, stays=None, crawl_dir='', facts_file='', peak_month=12,
             currency='', lang='en', progress=None):
    from playwright.sync_api import sync_playwright
    site = site if site.startswith('http') else 'https://' + site
    out = paths.resolve(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stays = stays or default_stays(peak_month=peak_month)
    results, calendar, engine_cfg, errors = [], {}, {}, []

    def say(m):
        if progress:
            progress(m)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(user_agent=UA, viewport={'width': 1366, 'height': 900}, locale='en-GB')
        page = ctx.new_page()

        def keep(resp):
            u = resp.url
            try:
                if 'index-price.mirai.com' in u:
                    calendar[u.rsplit('/', 1)[-1].replace('.json', '')] = resp.json()
                elif 'engine.mirai.com/HOTEL/' in u and not engine_cfg:
                    engine_cfg.update(resp.json())
            except Exception:
                pass
        page.on('response', keep)

        for i, s in enumerate(stays, 1):
            d = date.fromisoformat(s['checkin'])
            url = (f"{site.rstrip('/')}/search/?idtokenprovider={hotel_id}&checkin={d:%d/%m/%Y}"
                   f"&nights={s['nights']}&lang={lang}" + (f'&currency={currency}' if currency else ''))
            say(f"booking engine {i}/{len(stays)}: {s['label']} ({d:%d %b})")
            rec = dict(s, url=url)
            try:
                with page.expect_response(lambda r: 'booking/rates' in r.url, timeout=60000) as resp_info:
                    page.goto(url, wait_until='domcontentloaded', timeout=60000)
                data = resp_info.value.json()
                rec['status'] = (data or {}).get('status')
                rec['rooms'] = parse_rates(data)
                rec['user_location'] = (((data.get('data') or {}).get('tracking') or {}).get('country'))
                page.wait_for_timeout(3000)
                shot = out / f"booking-engine-{i}-{d:%Y-%m-%d}.png"
                page.screenshot(path=str(shot), full_page=True)
                rec['screenshot'] = str(shot)
            except Exception as e:
                rec['error'] = f'{type(e).__name__}: {str(e)[:200]}'
                errors.append(rec['error'])
            results.append(rec)
            time.sleep(2)

        site_pages = {}
        urls = _site_urls(crawl_dir, site)
        for n, u in enumerate(urls, 1):
            try:
                page.goto(u, wait_until='domcontentloaded', timeout=45000)
                page.wait_for_timeout(1500)
                site_pages[u] = {'type': _page_type(u), 'title': page.title(),
                                 'h1': ' | '.join(page.locator('h1').all_inner_texts())[:200],
                                 'text': re.sub(r'\s+', ' ', page.inner_text('body'))[:20000]}
            except Exception as e:
                site_pages[u] = {'type': _page_type(u), 'title': '', 'h1': '', 'text': '', 'error': str(e)[:150]}
            if n % 10 == 0:
                say(f'website pages rendered {n}/{len(urls)}')
        browser.close()

    summary = summarise(results)
    cal = calendar_summary(calendar)
    comparison = compare(summary, site_pages)
    today = date.today()
    facts = []
    for pct in summary['member_discount_pct'][:1]:
        facts.append(f'Member discount {pct}% on the booking engine')
    for o in summary['offers']:
        if o['discount_pct']:
            facts.append(f"Offer \"{o['rate']}\" {o['discount_range']} off")
    for r in summary['rooms']:
        if r['size']:
            facts.append(f"{r['name']}: {r['size']}")
        if r['max_occupancy']:
            facts.append(f"{r['name']}: up to {r['max_occupancy']} guests")
    for c in summary['cancellation_options']:
        facts.append(f'Cancellation option: {c}')
    if facts_file:
        _merge_facts(facts_file, facts, f'booking engine, {today:%d %b %Y}')

    result = {'site': site, 'hotel_id': hotel_id, 'checked': today.isoformat(), 'stays': results,
              'summary': summary, 'calendar': cal, 'engine_settings': {
                  k: engine_cfg.get(k) for k in ('maxBookingDays', 'clubConfiguration', 'showPricesInCalendar')},
              'tracking_in_engine': {k: v for k, v in (engine_cfg.get('tracking') or {}).items()
                                     if isinstance(v, list) and v},
              'website_vs_engine': comparison, 'facts': facts, 'errors': errors,
              'site_pages_rendered': len(site_pages)}
    (out / 'booking_engine.json').write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding='utf-8')
    md = summary_md(result)
    (out / 'booking_engine.md').write_text(md, encoding='utf-8')
    return {'files': [str(out / 'booking_engine.json'), str(out / 'booking_engine.md')],
            'errors': errors, 'summary_md': md[:7000]}


def _merge_facts(facts_file, facts, source):
    f = paths.resolve(facts_file)
    doc = json.loads(f.read_text(encoding='utf-8')) if f.exists() else {'facts': []}
    have = {x.get('fact') for x in doc.get('facts', [])}
    doc.setdefault('facts', []).extend({'fact': x, 'source': source} for x in facts if x not in have)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding='utf-8')


def summary_md(r):
    s, c, w = r['summary'], r['calendar'], r['website_vs_engine']
    L = [f"# Booking engine: {r['site']} (Mirai {r['hotel_id']}), checked {r['checked']}", '']
    for st in r['stays']:
        if st.get('error'):
            L.append(f"- {st['label']} {st['checkin']}: FAILED ({st['error']})")
        else:
            n_rates = sum(len(x['rates']) for x in st['rooms'])
            sold = sum(1 for x in st['rooms'] if x['sold_out'])
            L.append(f"- {st['label']} {st['checkin']}: {len(st['rooms'])} rooms ({sold} sold out), {n_rates} rate "
                     f"options, lowest {s['lowest_price_per_stay'].get(st['label'])} {c.get('currency', '')}")
    L += ['', '## Offers on sale', '']
    L += [f"- {o['rate']}" + (f" (offer discount {o['discount_range']}, on top of the member discount)"
                                if o['discount_range'] else '') for o in s['offers']] or ['- none']
    L += ['', f"- Member (club) discount: {s['member_discount_pct'] or 'not seen'}",
          f"- Boards: {s['boards']}", f"- Cancellation options: {s['cancellation_options']}", '',
          '## Rooms', '']
    L += [f"- {x['name']}: {x['size'] or 'size n/a'}, up to {x['max_occupancy']} guests" for x in s['rooms']]
    L += ['', '## Price calendar (lowest per night)', '']
    L += [f"- {m}: {v['min']}–{v['max']} (avg {v['avg']}), highest {v['highest_dates'][:3]}"
          for m, v in c['by_month'].items()]
    if c['avg_by_weekday']:
        L.append(f"- Average by weekday: {c['avg_by_weekday']}")
    L += ['', '## Website vs booking engine', '']
    for x in w['rooms']:
        if not x['site_page']:
            L.append(f"- {x['room']}: no matching room page found")
        elif x.get('sizes_on_page') and not x.get('size_on_page'):
            L.append(f"- {x['room']}: engine says {x['engine_size']}, page shows {x['sizes_on_page']} ({x['site_page']})")
    L += [f"- Sold with no page on the site: {o['rate']}" for o in w['offers_without_page']]
    L += [f"- Offer page with no matching room rate on sale (expired, or a dining/spa offer): {u}"
          for u in w['offer_pages_without_rate']]
    site_pcts = sorted({x['pct'] for x in w['member_discount_on_site']})
    if site_pcts and s['member_discount_pct'] and set(site_pcts) - set(s['member_discount_pct']):
        L.append(f"- Member discount: site says {site_pcts}%, engine gives {s['member_discount_pct']}%")
    L += ['', f"Facts recorded (source: booking engine): {len(r['facts'])}"]
    return '\n'.join(L) + '\n'
