"""One Google sign-in for everything the plugin uses: Search Console, GA4, Google Ads (Keyword
Planner) and Google Business Profile (listings, performance, reviews, photos, hotel amenities; changes only after
approval). Leave Ads or Business Profile out with --no-ads / --no-gbp (the old --with-ads / --with-gbp flags are still
accepted and change nothing).

Asks for the permissions on one consent screen and writes:
  ~/.metahotels-seo/google/adc.json        (GA4, Business Profile; ADC authorized_user format)
  ~/.metahotels-seo/google/gsc/token.json  (Search Console, mcp-gsc format)

Google lets you untick permissions on the consent screen; the sign-in then says which ones are missing. After it,
every Business Profile API is tried once and any that is switched off on the Cloud project is listed with its link.

Sign in as metahotels.m@gmail.com. The OAuth app is published, so tokens
don't expire after 7 days; Google shows an "unverified app" warning:
Advanced -> Go to MetaHotels SEO.
"""
import argparse
import json
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

from . import paths
from .gbp import GBP_SCOPE
from .keywords import ADS_SCOPE

NAMES = {paths.GA_SCOPE: 'Google Analytics (GA4)', paths.GSC_SCOPE: 'Search Console',
         ADS_SCOPE: 'Google Ads (Keyword Planner)', GBP_SCOPE: 'Google Business Profile'}


def scopes(no_ads=False, no_gbp=False):
    return ([paths.GA_SCOPE, paths.GSC_SCOPE] + ([] if no_ads else [ADS_SCOPE])
            + ([] if no_gbp else [GBP_SCOPE]))


def missing(asked, granted):
    """Permissions asked for but not granted (unticked on Google's consent screen)."""
    return [NAMES.get(s, s) for s in asked if s not in set(granted or [])]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--no-browser', action='store_true', help='print the sign-in link instead of opening a browser')
    ap.add_argument('--port', type=int, default=8085)
    ap.add_argument('--no-ads', action='store_true', help='leave Google Ads (Keyword Planner) out')
    ap.add_argument('--no-gbp', action='store_true', help='leave Google Business Profile out')
    ap.add_argument('--with-ads', action='store_true', help=argparse.SUPPRESS)   # old flags: now the default
    ap.add_argument('--with-gbp', action='store_true', help=argparse.SUPPRESS)
    args = ap.parse_args()

    if not paths.CLIENT_SECRET.exists():
        sys.exit(f'OAuth client file missing: {paths.CLIENT_SECRET}')
    asked = scopes(args.no_ads, args.no_gbp)
    flow = InstalledAppFlow.from_client_secrets_file(str(paths.CLIENT_SECRET), asked)
    # 127.0.0.1, not "localhost": on some Windows PCs localhost resolves to IPv6 (::1),
    # where the listener isn't, and the redirect back from Google fails.
    creds = flow.run_local_server(
        host='127.0.0.1',
        port=args.port,
        open_browser=not args.no_browser,
        access_type='offline',
        prompt='consent',
        authorization_prompt_message='AUTH_URL: {url}',
        success_message='Signed in. You can close this tab and go back to Claude.',
        timeout_seconds=600,
    )
    if not creds.refresh_token:
        sys.exit('Google returned no refresh token. Run the sign-in again.')

    client = json.loads(paths.CLIENT_SECRET.read_text())['installed']
    paths.GOOGLE_DIR.mkdir(parents=True, exist_ok=True)
    paths.GA_CREDENTIALS.write_text(json.dumps({
        'type': 'authorized_user',
        'client_id': client['client_id'],
        'client_secret': client['client_secret'],
        'refresh_token': creds.refresh_token,
        'quota_project_id': client['project_id'],
        'scopes': list(creds.scopes or []),
    }, indent=2))
    paths.GSC_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    paths.GSC_TOKEN.write_text(creds.to_json())
    print(f'WROTE {paths.GA_CREDENTIALS}', flush=True)
    print(f'WROTE {paths.GSC_TOKEN}', flush=True)

    gone = missing(asked, creds.scopes)
    if gone:
        print('MISSING PERMISSIONS (unticked on the consent screen): ' + ', '.join(gone)
              + '. Run the sign-in again and tick every box.', flush=True)
    if GBP_SCOPE in (creds.scopes or []):
        from . import gbp
        gbp._token.clear()
        r = gbp.api_check()
        for api, state in (r.get('apis') or {}).items():
            print(f'BUSINESS PROFILE {api}: {state}', flush=True)
        if not r.get('checked'):
            print(f'BUSINESS PROFILE not checked: {r.get("reason")}', flush=True)


if __name__ == '__main__':
    main()
