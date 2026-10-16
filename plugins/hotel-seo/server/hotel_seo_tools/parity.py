"""Rate parity from the daily Magic Parity feed (Azure Blob Storage), read by hotel.

The same files the 6am leak report and the Magic Parity dashboard ingest:
  Docs/Website Parity YYYYMMDD.csv              hotel website vs OTAs (one row per check)
  Docs/Google Parity YYYYMMDD.csv               the same for Google Hotel Ads
  Docs/metahotels_hotel_services_YYYYMMDD.csv   hotel roster: id_hotel, hotel_name, idtokenprovider (Mirai ID)

Playbook: if the hotel's own site is dearer than the OTAs, page fixes won't win the booking, so a
losing parity picture goes at the top of the Priority list.

Connection: ~/.metahotels-seo/parity.json {"connection_string", "container"}, written by
`hotel-seo-parity-login` (pasted, or read from a .env file with --from-env), or the
AZURE_STORAGE_CONNECTION_STRING / AZURE_STORAGE_CONTAINER_NAME environment variables.
"""
import argparse
import csv
import getpass
import io
import json
import os
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

from . import paths

CONFIG = paths.HOME / 'parity.json'
PATTERNS = {'web': re.compile(r'Docs/Website Parity (\d{8})\.csv$', re.I),
            'gha': re.compile(r'Docs/Google Parity (\d{8})\.csv$', re.I),
            'hotels': re.compile(r'Docs/metahotels_hotel_services_(\d{8})\.csv$', re.I)}
CACHE = paths.HOME / 'parity-cache'


def _clean(v):
    return (v or '').strip().strip('"').strip("'")


def settings():
    if CONFIG.exists():
        c = json.loads(CONFIG.read_text())
        return _clean(c.get('connection_string')), _clean(c.get('container')) or 'granules'
    return _clean(os.environ.get('AZURE_STORAGE_CONNECTION_STRING')), \
        _clean(os.environ.get('AZURE_STORAGE_CONTAINER_NAME')) or 'granules'


def configured():
    conn, _ = settings()
    return (True, '') if conn else (False, f'no parity feed connection: run hotel-seo-parity-login ({CONFIG})')


def _container():
    from azure.storage.blob import BlobServiceClient
    conn, name = settings()
    return BlobServiceClient.from_connection_string(conn).get_container_client(name)


def _latest(container, kind, days):
    files = []
    for b in container.list_blobs(name_starts_with='Docs/'):
        m = PATTERNS[kind].search(b.name)
        if m:
            files.append((m.group(1), b.name))
    files.sort(reverse=True)
    return files[:days]


def _read(container, name):
    """Download once per file; cached on disk (the daily files never change)."""
    CACHE.mkdir(parents=True, exist_ok=True)
    local = CACHE / re.sub(r'[^\w.-]', '_', name)
    if not local.exists():
        local.write_bytes(container.download_blob(name).readall())
    text = local.read_bytes().decode('utf-8-sig', errors='replace')
    return list(csv.DictReader(io.StringIO(text)))


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def hotel_roster():
    """Mirai ID (idtokenprovider) -> hotel name, from the newest hotel services file."""
    ok, why = configured()
    if not ok:
        return {}
    c = _container()
    latest = _latest(c, 'hotels', 1)
    if not latest:
        return {}
    return {_clean(r.get('idtokenprovider')): _clean(r.get('hotel_name'))
            for r in _read(c, latest[0][1]) if r.get('idtokenprovider')}


def _bml(r):
    return (r.get('bml_name') or '').strip().lower()


def _matches(row, hotel, hotel_id):
    if hotel_id:
        return _clean(row.get('id_hotel')) == str(hotel_id)
    name = (row.get('hotel_name') or '').lower()
    words = [w for w in re.findall(r'[a-z0-9]+', hotel.lower()) if w not in {'hotel', 'resort', 'the', 'and'}]
    return bool(words) and all(w in name for w in words)


def report(hotel='', mirai_id='', days=7, source='web', out_dir=''):
    """Parity for one hotel over the last `days` daily files: Beat / Meet / Lose share of the checks
    where the OTA showed a price, by OTA, device, guest country and lead time, the price gap, and
    the worst losing checks with screenshots. Feed conventions: `price` is the OTA's price,
    `price_customer` the hotel site's; a positive price_difference means the site is dearer (Lose).
    Prefer mirai_id (idtokenprovider): it is resolved to the feed's id_hotel through the roster."""
    ok, why = configured()
    if not ok:
        return {'checked': False, 'reason': why}
    c = _container()
    hotel_id = ''
    if mirai_id:
        latest = _latest(c, 'hotels', 1)
        roster = _read(c, latest[0][1]) if latest else []
        hit = next((r for r in roster if _clean(r.get('idtokenprovider')) == str(mirai_id)), None)
        if not hit:
            return {'checked': True, 'found': False, 'reason': f'Mirai ID {mirai_id} is not in the parity feed roster'}
        hotel_id, hotel = _clean(hit.get('id_hotel')), _clean(hit.get('hotel_name'))
    files = _latest(c, source, days)
    if not files:
        return {'checked': False, 'reason': f'no {source} parity files in the container'}
    rows = []
    for d, name in files:
        for r in _read(c, name):
            if _matches(r, hotel, hotel_id):
                r['_report_date'] = d
                rows.append(r)
    hotels_hit = Counter(r.get('hotel_name') for r in rows)
    if len(hotels_hit) > 1:
        return {'checked': True, 'found': False, 'reason': f'"{hotel}" matches {len(hotels_hit)} hotels; '
                'give mirai_id', 'matches': dict(hotels_hit)}
    if not rows:
        names = Counter(r.get('hotel_name') for r in _read(c, files[0][1]))
        close = [n for n in names if n and any(w in n.lower() for w in hotel.lower().split() if len(w) > 3)]
        return {'checked': True, 'found': False, 'files': [n for _, n in files],
                'reason': f'no rows for "{hotel}" in the last {len(files)} files',
                'similar_hotel_names': close[:10], 'hotels_in_feed': len(names)}

    def bml(rs):
        priced = [r for r in rs if _bml(r) in ('beat', 'meet', 'lose')]
        n = len(priced) or 1
        c_ = Counter(_bml(r) for r in priced)
        return {'checks': len(rs), 'priced': len(priced), 'no_price': len(rs) - len(priced),
                **{k.title(): round(100 * c_.get(k, 0) / n, 1) for k in ('beat', 'meet', 'lose')}}

    def group(key):
        g = defaultdict(list)
        for r in rows:
            g[(r.get(key) or '').strip() or '(blank)'].append(r)
        out = []
        for k, rs in g.items():
            lose = [abs(_num(r.get('price_difference')) or 0) for r in rs if _bml(r) == 'lose']
            out.append(dict(bml(rs), name=k, avg_lose_gap_pct=round(100 * sum(lose) / len(lose), 1) if lose else 0))
        return sorted(out, key=lambda x: (-x['Lose'], -x['checks']))

    unsolved = [r for r in rows if (r.get('disparity_status_name') or '').lower() == 'unsolved' and _bml(r) == 'lose']
    worst = sorted((r for r in rows if _bml(r) == 'lose'), key=lambda r: -(_num(r.get('price_difference')) or 0))[:10]
    result = {
        'checked': True, 'found': True, 'hotel': rows[0].get('hotel_name'), 'source': source,
        'files': [n for _, n in files], 'dates': f'{files[-1][0]}..{files[0][0]}',
        'currency': Counter(r.get('currency') for r in rows).most_common(1)[0][0],
        'overall': bml(rows),
        'unsolved_lose_checks': len(unsolved),
        'by_ota': group('ota_name'), 'by_device': group('device_name'),
        'by_guest_country': group('country')[:12], 'by_lead_time': group('grouped_leadtime_name'),
        'by_gap': dict(Counter(r.get('disparity_range_name') for r in rows if _bml(r) == 'lose')),
        'worst_losses': [{'date': r['_report_date'], 'ota': r.get('ota_name'), 'stay': r.get('date_in'),
                          'nights': r.get('lenght_of_stay'), 'site_price': r.get('price_customer'),
                          'ota_price': r.get('price'),
                          'gap_pct': round(100 * (_num(r.get('price_difference')) or 0), 1),
                          'device': r.get('device_name'), 'guest_country': r.get('country'),
                          'screenshot': r.get('screenshot_url')} for r in worst],
    }
    lose = result['overall']['Lose']
    result['verdict'] = ('LOSING: the hotel site is dearer than an OTA on {}% of priced checks; put parity at the '
                         'top of the Priority list'.format(lose) if lose >= 20 else
                         'Mostly at parity ({}% of priced checks Lose)'.format(lose))
    if out_dir:
        out = paths.resolve(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / f'parity-{source}.json').write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding='utf-8')
        result['file'] = str(out / f'parity-{source}.json')
    return result


def _from_env_file(path):
    vals = {}
    for line in open(path, encoding='utf-8'):
        if '=' in line and not line.lstrip().startswith('#'):
            k, v = line.split('=', 1)
            vals[k.strip()] = _clean(v)
    return vals.get('AZURE_STORAGE_CONNECTION_STRING', ''), vals.get('AZURE_STORAGE_CONTAINER_NAME', '')


def login():
    """hotel-seo-parity-login: store the parity feed's Azure connection on this machine."""
    ap = argparse.ArgumentParser(description='Save the Azure connection for the daily parity feed.')
    ap.add_argument('--from-env', help='read AZURE_STORAGE_CONNECTION_STRING / _CONTAINER_NAME from this .env file '
                                       '(e.g. the Magic Parity project)')
    args = ap.parse_args()
    if args.from_env:
        conn, container = _from_env_file(args.from_env)
    else:
        conn = getpass.getpass('Azure storage connection string (hidden): ')
        container = input('Container name (Enter = granules): ').strip()
    conn = _clean(conn)
    if 'AccountName=' not in conn:
        raise SystemExit('That does not look like an Azure storage connection string; nothing saved.')
    paths.HOME.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps({'connection_string': conn, 'container': container or 'granules'}, indent=2))
    try:
        CONFIG.chmod(0o600)
    except OSError:
        pass
    print(f'Saved to {CONFIG} (container {container or "granules"}).')


if __name__ == '__main__':
    login()
