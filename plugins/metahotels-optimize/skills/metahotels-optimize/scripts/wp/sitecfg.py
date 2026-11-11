"""Per-site settings for the skill's tools, read from site.json in the folder a tool is run from (the site folder).

Every tool in scripts/ and scripts/wp/ is run with the site folder as the working directory, so rollback/, images/,
audit/ and site.json are all relative to it. Set SITE_JSON to use a site.json elsewhere.
See references/site-setup.md for the fields; only "host" and "mcp_server" are required.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))       # <skill>/scripts/wp
SCRIPTS = os.path.dirname(HERE)                           # <skill>/scripts
MCP_CALL = os.path.join(HERE, 'mcp_call.py')
WP = os.path.join(SCRIPTS, 'wp.py')
DEFAULT_POST_TYPES = ['post', 'page']


def workspace(start=None):
    """The work folder: the nearest folder at or above `start` (default: cwd) holding metahotels.json (init.py)."""
    d = os.path.abspath(start or os.getcwd())
    while True:
        if os.path.isfile(os.path.join(d, 'metahotels.json')):
            return d
        up = os.path.dirname(d)
        if up == d:
            return None
        d = up


def psi_env(site_dir=None):
    """The .env holding PAGESPEED_API_KEY: the site folder's own, else the work folder's (init.py creates it)."""
    site_dir = site_dir or os.getcwd()
    cands = [os.path.join(site_dir, '.env')]
    ws = workspace(site_dir)
    if ws:
        cands.append(os.path.join(ws, '.env'))
    for p in cands:
        if os.path.isfile(p) and read_key(p):
            return p
    return next((p for p in cands if os.path.isfile(p)), cands[-1])


def read_key(path):
    try:
        for line in open(path, encoding='utf-8'):
            if line.strip().startswith('PAGESPEED_API_KEY'):
                return line.split('=', 1)[1].strip().strip('"\'') if '=' in line else ''
    except OSError:
        pass
    return ''


def load(path=None):
    path = path or os.environ.get('SITE_JSON') or 'site.json'
    if not os.path.exists(path):
        sys.exit('site.json not found at %s: run the tool from the site folder (references/site-setup.md)'
                 % os.path.abspath(path))
    c = json.load(open(path, encoding='utf-8'))
    for k in ('host', 'mcp_server'):
        if not c.get(k):
            sys.exit('site.json: "%s" is required' % k)
    c.setdefault('origin', 'https://' + c['host'])
    c['origin'] = c['origin'].rstrip('/')
    c.setdefault('post_types', DEFAULT_POST_TYPES)
    if not c.get('psi_env'):
        c['psi_env'] = psi_env(os.path.dirname(os.path.abspath(path)))
    c.setdefault('pages', {})
    return c


if __name__ == '__main__':
    # python -I sitecfg.py --shell: shell assignments for the bash tools (eval "$(...)")
    import shlex
    c = load()
    pages = c['pages']
    out = {
        'SITE_HOST': c['host'],
        'SITE_URL': c['origin'] + '/',
        'SITE_MCP': c['mcp_server'],
        'SITE_PSI_ENV': os.path.abspath(c['psi_env']),
        # representative pages for the judge: an inner page with the same header (cold check) and a page with
        # carousels (lazy-load checks); paths relative to the origin
        'SITE_INNER': c['origin'] + pages.get('inner', '/'),
        'SITE_CAROUSEL': c['origin'] + pages.get('carousel', '/'),
    }
    print('\n'.join('%s=%s' % (k, shlex.quote(v)) for k, v in out.items()))
