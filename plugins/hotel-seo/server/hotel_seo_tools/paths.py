"""Where hotel-seo keeps things on each machine.

Everything that must survive plugin updates lives in ~/.metahotels-seo
(override with METAHOTELS_SEO_HOME): the LibreCrawl install, Google tokens
and the copy of this server the desktop app runs.
"""
import os
from pathlib import Path

HOME = Path(os.environ.get('METAHOTELS_SEO_HOME') or Path.home() / '.metahotels-seo')
LIBRECRAWL_DIR = HOME / 'librecrawl'
GOOGLE_DIR = HOME / 'google'
GA_CREDENTIALS = GOOGLE_DIR / 'adc.json'
GSC_CONFIG_DIR = GOOGLE_DIR / 'gsc'
GSC_TOKEN = GSC_CONFIG_DIR / 'token.json'
LOG_DIR = HOME / 'logs'

PACKAGE_DIR = Path(__file__).resolve().parent
SERVER_DIR = PACKAGE_DIR.parent              # plugins/hotel-seo/server (or ~/.metahotels-seo/server)
PLUGIN_DIR = SERVER_DIR.parent               # plugins/hotel-seo


def _client_secret():
    # The plugin ships it; init also copies it to ~/.metahotels-seo/google for the desktop app copy.
    for cand in (os.environ.get('HOTEL_SEO_CLIENT_SECRET'),
                 PLUGIN_DIR / 'setup' / 'google' / 'client_secret.json',
                 GOOGLE_DIR / 'client_secret.json'):
        if cand and Path(cand).exists():
            return Path(cand)
    return GOOGLE_DIR / 'client_secret.json'


CLIENT_SECRET = _client_secret()

GCP_PROJECT = 'metahotels-analytics'
GA_SCOPE = 'https://www.googleapis.com/auth/analytics.readonly'
GSC_SCOPE = 'https://www.googleapis.com/auth/webmasters'

LIBRECRAWL_PORT = int(os.environ.get('LIBRECRAWL_PORT', '5057'))  # not 5000: macOS AirPlay uses it
LIBRECRAWL_URL = f'http://127.0.0.1:{LIBRECRAWL_PORT}'


def librecrawl_python():
    sub = 'Scripts/python.exe' if os.name == 'nt' else 'bin/python'
    return LIBRECRAWL_DIR / '.venv' / sub


def work_dir():
    """Base for relative output paths.

    Claude Code starts MCP servers in the project folder, so relative paths land
    where Claude was started. The desktop app has no project folder; init sets
    HOTEL_SEO_HOME there.
    """
    base = os.environ.get('HOTEL_SEO_HOME')
    return Path(base).expanduser() if base else Path.cwd()


def resolve(path):
    p = Path(path).expanduser()
    return p if p.is_absolute() else work_dir() / p
