"""Start the Google MCP servers with this machine's token paths.

  hotel-seo-launch gsc   -> mcp-search-console (Search Console)
  hotel-seo-launch ga4   -> analytics-mcp (Google Analytics 4)

Used from the plugin's .mcp.json and the desktop app config, so token
locations are worked out per machine instead of hard-coded.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import paths

SERVERS = {
    'gsc': ['mcp-search-console'],
    'ga4': ['analytics-mcp'],
}


def find_uvx():
    found = shutil.which('uvx')
    if found:
        return found
    uv = shutil.which('uv')
    if uv:
        cand = Path(uv).with_name('uvx.exe' if os.name == 'nt' else 'uvx')
        if cand.exists():
            return str(cand)
    for cand in (Path.home() / '.local' / 'bin' / ('uvx.exe' if os.name == 'nt' else 'uvx'),
                 Path.home() / '.cargo' / 'bin' / 'uvx'):
        if cand.exists():
            return str(cand)
    sys.exit('uvx not found. Run /hotel-seo init.')


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in SERVERS:
        sys.exit('usage: hotel-seo-launch gsc|ga4')
    which = sys.argv[1]
    env = dict(os.environ)
    if which == 'gsc':
        env['GSC_OAUTH_CLIENT_SECRETS_FILE'] = str(paths.CLIENT_SECRET)
        env['GSC_CONFIG_DIR'] = str(paths.GSC_CONFIG_DIR)
    else:
        env['GOOGLE_APPLICATION_CREDENTIALS'] = str(paths.GA_CREDENTIALS)
        env['GOOGLE_PROJECT_ID'] = paths.GCP_PROJECT
        env['GOOGLE_CLOUD_PROJECT'] = paths.GCP_PROJECT
    cmd = [find_uvx(), '--python', '3.11', *SERVERS[which]]
    # Inherit stdin/stdout so the MCP stdio stream passes straight through.
    sys.exit(subprocess.call(cmd, env=env))


if __name__ == '__main__':
    main()
