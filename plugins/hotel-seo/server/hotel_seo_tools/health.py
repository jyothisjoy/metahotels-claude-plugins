"""Health checks for /hotel-seo init --check and the health_check tool."""
import json
import shutil

import requests

from . import __version__, librecrawl_proc, paths

DESKTOP_COPY = paths.HOME / 'server'


def _row(name, ok, detail, fix=''):
    return {'check': name, 'ok': bool(ok), 'detail': detail, 'fix': '' if ok else fix}


def _refresh(token_file, scopes):
    """Refresh a Google token file; returns an access token or raises."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    # Both the ADC file and mcp-gsc's token.json carry client_id, client_secret
    # and refresh_token, which is all from_authorized_user_info needs.
    creds = Credentials.from_authorized_user_info(json.loads(token_file.read_text()), scopes)
    creds.refresh(Request())
    return creds.token


def check_google():
    rows = []
    signin = 'Run /hotel-seo init (Google sign-in as metahotels.m@gmail.com).'
    if not paths.GA_CREDENTIALS.exists():
        rows.append(_row('GA4 sign-in', False, f'missing {paths.GA_CREDENTIALS}', signin))
    else:
        try:
            tok = _refresh(paths.GA_CREDENTIALS, [paths.GA_SCOPE])
            r = requests.get('https://analyticsadmin.googleapis.com/v1beta/accountSummaries',
                             params={'pageSize': 200}, headers={'Authorization': f'Bearer {tok}'}, timeout=20)
            r.raise_for_status()
            props = sum(len(a.get('propertySummaries', [])) for a in r.json().get('accountSummaries', []))
            rows.append(_row('GA4 sign-in', props > 0, f'{props} GA4 properties visible',
                             'Signed in with an account that has no GA4 access. ' + signin))
        except Exception as e:  # noqa: BLE001 - report any failure as a red row
            rows.append(_row('GA4 sign-in', False, f'token refresh or API call failed: {e}', signin))

    if not paths.GSC_TOKEN.exists():
        rows.append(_row('Search Console sign-in', False, f'missing {paths.GSC_TOKEN}', signin))
    else:
        try:
            tok = _refresh(paths.GSC_TOKEN, [paths.GSC_SCOPE])
            r = requests.get('https://www.googleapis.com/webmasters/v3/sites',
                             headers={'Authorization': f'Bearer {tok}'}, timeout=20)
            r.raise_for_status()
            sites = len(r.json().get('siteEntry', []))
            rows.append(_row('Search Console sign-in', sites > 0, f'{sites} Search Console properties visible',
                             'Signed in with an account that has no Search Console access. ' + signin))
        except Exception as e:  # noqa: BLE001
            rows.append(_row('Search Console sign-in', False, f'token refresh or API call failed: {e}', signin))
    if paths.GSC_TOKEN.exists():
        from .docs import DRIVE_SCOPE
        has = DRIVE_SCOPE in (json.loads(paths.GSC_TOKEN.read_text()).get('scopes') or [])
        rows.append(_row('Google Docs output', has, 'allowed' if has else 'the sign-in has no Docs permission',
                         'Run hotel-seo-auth again (one consent screen) to allow "files created by this app"; '
                         'until then lists come as PDF plus a .docs.html file.'))
    from . import keywords
    ok, why = keywords.configured()
    # optional: Keyword Planner only; never fails the check
    rows.append(_row('Google Ads (Keyword Planner)', True, 'set up' if ok else f'optional, not set up: {why}'))
    from . import bing, parity
    for name, mod in (('Rate parity feed (Azure)', parity), ('Bing Webmaster API', bing)):
        ok, why = mod.configured()
        rows.append(_row(name, True, 'set up' if ok else f'optional, not set up: {why}'))
    return rows


def check_chromium():
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            exe = p.chromium.executable_path
        from pathlib import Path
        return _row('Chromium for PDFs', Path(exe).exists(), exe, 'Run /hotel-seo init (installs Chromium).')
    except Exception as e:  # noqa: BLE001
        return _row('Chromium for PDFs', False, str(e), 'Run /hotel-seo init (installs Chromium).')


def run(google=True):
    rows = [
        _row('uv', shutil.which('uv') or shutil.which('uvx'), shutil.which('uv') or 'not on PATH',
             'Run /hotel-seo init (installs uv).'),
        _row('LibreCrawl installed', librecrawl_proc.is_installed(), str(paths.LIBRECRAWL_DIR),
             'Run /hotel-seo init.'),
        _row('LibreCrawl running', librecrawl_proc.is_running(), paths.LIBRECRAWL_URL,
             'Not an error: it starts automatically on the first crawl.'),
        check_chromium(),
        _row('OAuth client file', paths.CLIENT_SECRET.exists(), str(paths.CLIENT_SECRET),
             'Plugin files are incomplete; reinstall the hotel-seo plugin.'),
    ]
    version_file = DESKTOP_COPY / 'hotel_seo_tools' / '__init__.py'
    if version_file.exists():
        desk = version_file.read_text().split('"')[1] if '"' in version_file.read_text() else '?'
        rows.append(_row('Desktop app copy', desk == __version__, f'desktop {desk}, plugin {__version__}',
                         'Run /hotel-seo init to refresh the desktop app copy.'))
    if google:
        rows.extend(check_google())
    # "LibreCrawl running" is informational only.
    all_ok = all(r['ok'] for r in rows if r['check'] != 'LibreCrawl running')
    return {'version': __version__, 'all_ok': all_ok, 'checks': rows}


def as_table(result):
    lines = [f"hotel-seo {result['version']}: {'all good' if result['all_ok'] else 'needs attention'}", '']
    for r in result['checks']:
        mark = 'OK  ' if r['ok'] else ('INFO' if r['check'] == 'LibreCrawl running' else 'FAIL')
        lines.append(f"[{mark}] {r['check']}: {r['detail']}")
        if r['fix']:
            lines.append(f"       fix: {r['fix']}")
    return '\n'.join(lines)


if __name__ == '__main__':
    print(as_table(run()))
