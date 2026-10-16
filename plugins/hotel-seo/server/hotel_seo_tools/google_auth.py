"""One Google sign-in for Search Console and GA4, plus Google Ads (Keyword Planner) with --with-ads.

Asks for the read scopes on one consent screen and writes:
  ~/.metahotels-seo/google/adc.json        (GA4, ADC authorized_user format)
  ~/.metahotels-seo/google/gsc/token.json  (Search Console, mcp-gsc format)

Sign in as metahotels.m@gmail.com. The OAuth app is published, so tokens
don't expire after 7 days; Google shows an "unverified app" warning:
Advanced -> Go to Google Analytics MCP.
"""
import argparse
import json
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

from . import paths
from .keywords import ADS_SCOPE


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--no-browser', action='store_true', help='print the sign-in link instead of opening a browser')
    ap.add_argument('--port', type=int, default=8085)
    ap.add_argument('--with-ads', action='store_true',
                    help='also ask for Google Ads (Keyword Planner); Google may ask to verify it is you again')
    args = ap.parse_args()

    if not paths.CLIENT_SECRET.exists():
        sys.exit(f'OAuth client file missing: {paths.CLIENT_SECRET}')
    flow = InstalledAppFlow.from_client_secrets_file(str(paths.CLIENT_SECRET), [paths.GA_SCOPE, paths.GSC_SCOPE] + ([ADS_SCOPE] if args.with_ads else []))
    creds = flow.run_local_server(
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


if __name__ == '__main__':
    main()
