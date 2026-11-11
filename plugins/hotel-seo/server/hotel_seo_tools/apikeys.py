"""API keys for the claude-seo agents: Google (PageSpeed Insights + CrUX), Moz, Geoapify.

Read from the work folder's .env (GOOGLE_API_KEY, MOZ_API, GEOAPIFY_KEY), or else from
~/.metahotels-seo/api-keys.json, saved by `hotel-seo-key-login <name>` (typed by the user, hidden). The Google
sign-in (OAuth) does not cover PageSpeed / CrUX, so the Google key is separate. The keys are never returned by any MCP tool: `seo_check` hands them to the vendored scripts as
environment variables and redacts them from anything it returns.

  google    Cloud console (project metahotels-analytics) -> APIs & Services -> Credentials -> API key,
            restricted to "PageSpeed Insights API" and "Chrome UX Report API" (enable both first).
  moz       moz.com -> API -> Free plan -> token (or "access-id:secret").
  geoapify  myprojects.geoapify.com -> project -> API key (free tier).
"""
import argparse
import getpass
import json

import requests

from . import paths

FILE = paths.HOME / 'api-keys.json'
KEYS = {
    'google': {'field': 'google_api_key', 'env': 'GOOGLE_API_KEY',
               'dotenv': ('PAGESPEED_API_KEY', 'GOOGLE_API_KEY', 'GOOGLE_KEY', 'PSI_API_KEY'),
               'used_by': 'seo-performance, seo-agentic'},
    'moz': {'field': 'moz_api_key', 'env': 'MOZ_API_KEY', 'dotenv': ('MOZ_API', 'MOZ_API_KEY', 'MOZ_KEY'),
            'used_by': 'seo-backlinks'},
    'geoapify': {'field': 'geoapify_api_key', 'env': 'GEOAPIFY_API_KEY',
                 'dotenv': ('GEOAPIFY_KEY', 'GEOAPIFY_API_KEY'), 'used_by': 'seo-maps, keyword candidates'},
    'serper': {'field': 'serper_api_key', 'env': 'SERPER_API_KEY', 'dotenv': ('SERPER_API', 'SERPER_API_KEY', 'SERPER_KEY'),
               'used_by': 'monthly report keyword rankings'},
}


def _load():
    try:
        return json.loads(FILE.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def _dotenv():
    """Keys in the .env file of the work folder (same file as MIRAI_USER / MIRAI_PASS)."""
    from .mirai import _dotenv as read
    return read(paths.work_dir() / '.env')


def where(name):
    """Where the key for `name` comes from: '.env (<VAR>)', 'hotel-seo-key-login', or ''."""
    env = _dotenv()
    for var in KEYS[name]['dotenv']:
        if (env.get(var) or '').strip():
            return f'.env ({var})'
    return 'hotel-seo-key-login' if (_load().get(KEYS[name]['field']) or '').strip() else ''


def get(name):
    """The key for `name` (google | moz | geoapify): the work folder's .env first (e.g. MOZ_API, GEOAPIFY_KEY,
    GOOGLE_API_KEY), then the one saved with hotel-seo-key-login; '' if neither."""
    env = _dotenv()
    for var in KEYS[name]['dotenv']:
        v = (env.get(var) or '').strip()
        if v:
            return v
    return (_load().get(KEYS[name]['field']) or '').strip()


def env():
    """Environment variables for the vendored scripts, from the stored keys (and the Bing key)."""
    out = {}
    for name, k in KEYS.items():
        v = get(name)
        if v:
            out[k['env']] = v
    from . import bing
    if bing.CONFIG.exists():
        try:
            out['BING_WEBMASTER_API_KEY'] = json.loads(bing.CONFIG.read_text())['api_key']
        except (OSError, ValueError, KeyError):
            pass
    return out


def secrets():
    """Every secret value seo_check must never return."""
    return [v for v in env().values() if v and len(v) >= 6]


def test(name, key=None):
    """One cheap call that proves the key works. Returns (ok, detail)."""
    key = key if key is not None else get(name)
    if not key:
        return False, 'not set'
    try:
        if name == 'google':
            return _test_google(key)
        if name == 'moz':
            hdr = {'Content-Type': 'application/json'}
            if ':' in key:
                import base64
                hdr['Authorization'] = 'Basic ' + base64.b64encode(key.encode()).decode()
            else:
                hdr['x-moz-token'] = key
            r = requests.post('https://api.moz.com/v2/url_metrics', headers=hdr,
                              json={'targets': ['moz.com']}, timeout=30)
            if r.status_code == 200:
                return True, 'Moz API answers'
            return False, f'Moz API {r.status_code}: {_msg(r)}'
        if name == 'serper':
            # the account endpoint shows the balance without spending a credit
            r = requests.get('https://google.serper.dev/account', headers={'X-API-KEY': key}, timeout=30)
            if r.status_code == 200:
                bal = (r.json() or {}).get('balance')
                return True, 'Serper answers' + (f' ({bal} credits left)' if bal is not None else '')
            if r.status_code in (401, 403):
                return False, f'Serper {r.status_code}: key refused'
            return True, f'Serper key set (balance check answered {r.status_code}; checked on first use)'
        if name == 'geoapify':
            r = requests.get('https://api.geoapify.com/v1/geocode/search',
                             params={'text': 'Dubai', 'limit': 1, 'apiKey': key}, timeout=30)
            if r.status_code == 200:
                return True, 'Geoapify answers'
            return False, f'Geoapify {r.status_code}: {_msg(r)}'
    except requests.RequestException as e:
        return False, f'{type(e).__name__}: {str(e)[:200]}'
    return False, f'unknown key name {name}'


def google_apis(key=None):
    """{'pagespeed': (ok, detail), 'crux': (ok, detail)}: the same key can have one API enabled and not the other."""
    key = key if key is not None else get('google')
    out = {}
    r = requests.post('https://chromeuxreport.googleapis.com/v1/records:queryRecord',
                      headers={'X-Goog-Api-Key': key}, json={'origin': 'https://www.google.com'}, timeout=30)
    out['crux'] = (r.status_code == 200, 'answers' if r.status_code == 200 else f'{r.status_code}: {_msg(r)}')
    # a tiny PSI call: an invalid URL answers 400 from PSI itself when the key works; 403 / 429 mean key trouble
    r = requests.get('https://www.googleapis.com/pagespeedonline/v5/runPagespeed',
                     params={'url': 'https://example.invalid/', 'key': key}, timeout=60)
    bad_key = r.status_code in (401, 403, 429) or 'API key' in _msg(r) or 'API_KEY' in r.text[:500]
    out['pagespeed'] = (not bad_key, 'answers' if not bad_key else f'{r.status_code}: {_msg(r)}')
    return out


def _test_google(key):
    apis = google_apis(key)
    psi_ok, crux_ok = apis['pagespeed'][0], apis['crux'][0]
    if psi_ok and crux_ok:
        return True, 'PageSpeed Insights and Chrome UX Report APIs answer'
    if psi_ok:
        return True, ('PageSpeed works; Chrome UX Report API not enabled for this key (' + apis['crux'][1] +
                      '): enable it in the Cloud console for real-user Core Web Vitals history')
    return False, (f"PageSpeed {apis['pagespeed'][1]}; CrUX {apis['crux'][1]} (enable \"PageSpeed Insights API\" "
                   'and "Chrome UX Report API" for the key)')


def _msg(r):
    try:
        j = r.json()
        e = j.get('error') if isinstance(j, dict) else None
        if isinstance(e, dict):
            return str(e.get('message', ''))[:200]
        return str(e or j.get('message') or '')[:200]
    except ValueError:
        return r.text[:200]


def status():
    """[(name, ok, detail)] for health_check; never shows the key."""
    rows = []
    for name, k in KEYS.items():
        if not get(name):
            rows.append((name, False, f'not set (used by {k["used_by"]}): add {k["dotenv"][0]}=... to the .env file '
                                      f'in the work folder ({paths.work_dir()})'))
            continue
        ok, why = test(name)
        rows.append((name, ok, f'{why} (from {where(name)})'))
    return rows


def login():
    """hotel-seo-key-login google|moz|geoapify: store an API key (typed, hidden) and test it."""
    ap = argparse.ArgumentParser(description='Save an API key for the hotel-seo agents.')
    ap.add_argument('name', choices=sorted(KEYS))
    args = ap.parse_args()
    key = getpass.getpass(f'{args.name} API key (hidden): ').strip()
    if not key:
        raise SystemExit('Nothing saved.')
    ok, why = test(args.name, key)
    data = _load()
    data[KEYS[args.name]['field']] = key
    paths.HOME.mkdir(parents=True, exist_ok=True)
    FILE.write_text(json.dumps(data, indent=2), encoding='utf-8')
    try:
        FILE.chmod(0o600)
    except OSError:
        pass
    print(f'Saved to {FILE}. Test: {"OK" if ok else "FAILED"} ({why})')


if __name__ == '__main__':
    login()
