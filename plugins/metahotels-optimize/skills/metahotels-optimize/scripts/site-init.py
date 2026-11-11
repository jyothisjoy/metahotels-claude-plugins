"""Onboard a site for a pass (`/metahotels-optimize:optimize <site>`): create its folder and site.json, check every
access the pass needs, and list what to ask the user. Read-only on the website.

Usage (from the work folder or below it): python -I <skill>/scripts/site-init.py <url-or-host> [--slug=<folder>] [--json]
  --slug   the site folder name (default: an existing folder whose site.json has this host, else a folder named
           after the host, e.g. gewanhotels.com -> gewanhotels)

Checks, each reported as ok / ask / warn:
  site        answers 200, final origin (www or not), server, LiteSpeed cache header, CDN (QUIC.cloud, Cloudflare)
  stack       WordPress, Elementor version, Mirai booking engine, chat widget, reCAPTCHA, languages (hreflang)
  sitemap     a sitemap answering 200 with XML (sitemap-urls.py needs it)
  mcp         an MCP entry in ~/.claude.json for this host; else whether the site has the Meta MCP plugin's route
              (/wp-json/mcp/wp-content answers 401 without credentials when the plugin is active)
  access      with an entry: MCP content-integrations-status (writes enabled, administrator, Elementor, Polylang,
              post types) and REST /users/me; fills post_types and languages in site.json
  pagespeed   a PAGESPEED_API_KEY in the site's or the work folder's .env
  owner       always asked once per site: the Mirai booking link per hotel, CDN/DNS plans, plugins and pages the owner
              relies on that the sitemap does not show; plus the wp-admin login in Chrome (checked by Claude in Chrome)
Writes <site>/audit/onboarding-<date>.json. Never overwrites a value already in site.json.
"""
import datetime
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'wp'))
import mcpconf  # noqa: E402
import sitecfg  # noqa: E402

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36'
HOTEL_TYPES = ['offer', 'hotel_room', 'room', 'rooms', 'facility', 'facilities', 'destination', 'restaurant', 'dining',
               'hotel', 'hotels', 'property', 'event', 'events', 'spa', 'meeting', 'job', 'awsm_job_openings']
pos = [a for a in sys.argv[1:] if not a.startswith('--')]
if not pos:
    sys.exit(__doc__)
opt = {a[2:].split('=', 1)[0]: (a.split('=', 1)[1] if '=' in a else True) for a in sys.argv[1:] if a.startswith('--')}
raw = pos[0].strip()
host = urllib.parse.urlparse(raw if '://' in raw else 'https://' + raw).hostname.lower()
results = []


def item(area, status, detail, ask=''):
    results.append({'area': area, 'status': status, 'detail': detail, 'ask': ask})


def fetch(url, method='GET', redirect=True, timeout=60):
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None
    opener = urllib.request.build_opener() if redirect else urllib.request.build_opener(NoRedirect)
    req = urllib.request.Request(url, method=method, headers={'User-Agent': UA, 'Accept-Encoding': 'identity'})
    try:
        with opener.open(req, timeout=timeout) as r:
            return r.status, r.geturl(), dict(r.headers), r.read().decode('utf-8', 'replace') if method == 'GET' else ''
    except urllib.error.HTTPError as e:
        return e.code, url, dict(e.headers or {}), e.read().decode('utf-8', 'replace')[:2000]
    except Exception as e:  # noqa: BLE001
        return 0, url, {}, str(e)[:120]


# work folder and site folder
ws = sitecfg.workspace()
if not ws:
    sys.exit('No work folder: run `/metahotels-optimize:optimize --init` first (init.py creates metahotels.json), '
             'or cd into the work folder.')
slug = opt.get('slug')
if not slug:
    for d in sorted(os.listdir(ws)):
        sj = os.path.join(ws, d, 'site.json')
        if os.path.isfile(sj):
            try:
                if json.load(open(sj, encoding='utf-8')).get('host', '').lower().removeprefix('www.') == host.removeprefix('www.'):
                    slug = d
                    break
            except ValueError:
                pass
if not slug:
    slug = re.sub(r'[^a-z0-9-]', '', host.removeprefix('www.').split('.')[0]) or 'site'
site_dir = os.path.join(ws, slug)
created = not os.path.isdir(site_dir)
for sub in ('', 'audit', 'images', 'rollback'):
    os.makedirs(os.path.join(site_dir, sub), exist_ok=True)
sj_path = os.path.join(site_dir, 'site.json')
site = json.load(open(sj_path, encoding='utf-8')) if os.path.exists(sj_path) else {}
fill = {}


def setdefault(k, v):
    if v not in (None, '', [], {}) and k not in site:
        site[k] = v
        fill[k] = v


# site
st, final, hdr, html = fetch('https://%s/' % host)
h = {k.lower(): v for k, v in hdr.items()}
if st == 200:
    origin = '%s://%s' % urllib.parse.urlparse(final)[:2]
    cdn = 'QUIC.cloud' if 'x-qc-cache' in h else 'Cloudflare' if 'cf-ray' in h else ''
    item('site', 'ok', '%s answers 200; server %s; x-litespeed-cache %s%s' % (origin, h.get('server', '?'),
         h.get('x-litespeed-cache', '-'), '; CDN ' + cdn if cdn else ''))
    if 'litespeed' not in h.get('server', '').lower() and 'x-litespeed-cache' not in h and 'x-litespeed-cache-control' not in h:
        item('site', 'warn', 'no LiteSpeed headers: the LiteSpeed parts of the playbook may not apply')
else:
    origin = 'https://' + host
    item('site', 'warn', 'https://%s/ answered %s %s' % (host, st, html[:80] if st == 0 else ''),
         'The site did not answer 200. Is the address right, and is the site up?')
real_host = urllib.parse.urlparse(origin).hostname
setdefault('host', real_host)
if real_host != host.removeprefix('www.') and 'origin' not in site:
    setdefault('origin', origin)

# stack
if html:
    el = re.search(r'content="Elementor ([\d.]+)', html)
    langs = sorted(set(re.findall(r'hreflang="([a-zA-Z-]+)"', html)) - {'x-default'})
    mirai = len(re.findall(r'data-mirai-component', html))
    book = sorted(set(re.findall(r'https://reservation\.mirai\.com/[^"\'\s<>]+', html)))
    item('stack', 'ok' if 'wp-content' in html else 'warn', 'WordPress %s; Elementor %s; Mirai components %d; booking '
         'links on the homepage %d; chat widget %s; reCAPTCHA %s; languages %s' % (
             'yes' if 'wp-content' in html else 'NOT FOUND', el.group(1) if el else 'not found', mirai, len(book),
             'yes' if 'hdr_chatbot' in html else 'no', 'yes' if 'recaptcha' in html else 'no', ', '.join(langs) or 'one'))
    if langs:
        setdefault('languages', langs)
else:
    book = []

# sitemap
sm = None
for cand in ('/sitemap_index.xml', '/wp-sitemap.xml', '/sitemap.xml'):
    s, _, _, body = fetch(origin + cand)
    if s == 200 and '<loc>' in body:
        sm = cand
        break
item('sitemap', 'ok' if sm else 'warn', ('%s answers with XML' % sm) if sm else 'no sitemap answers 200 with XML',
     '' if sm else 'No sitemap found. Is one enabled (Rank Math, Yoast or WordPress core)? If it was working before, '
     'open wp-admin/options-permalink.php once (rebuilds the rules).')

# MCP
hits = mcpconf.by_host(real_host)
server = site.get('mcp_server')
if server and not any(n == server for _, n, _, _ in hits):
    item('mcp', 'warn', 'site.json names %r but no entry with that name is on this host' % server)
    server = None
if not server:
    content = [x for x in hits if x[2].rstrip('/').endswith('/wp-content')]
    pick = (content or hits or [None])[0]
    server = pick[1] if pick else None
if server:
    setdefault('mcp_server', server)
    item('mcp', 'ok', 'MCP entry %r (%s)' % (server, next(s for s, n, _, _ in hits if n == server)))
else:
    s, _, _, body = fetch(origin + '/wp-json/')
    has_route = '"mcp"' in body or '/mcp/' in body
    s2, _, _, _ = fetch(origin + '/wp-json/mcp/wp-content', method='POST')
    name = slug + '-content'
    if has_route or s2 in (401, 403, 405):
        how = ('The site has the Meta MCP plugin (route /wp-json/mcp/wp-content answers %s without credentials), but '
               'Claude Code has no entry for it. Create an application password for an administrator (wp-admin > Users >'
               ' Profile > Application Passwords), then in your own terminal (not in this chat, it holds the password):\n'
               '    claude mcp add --transport http --scope user %s %s/wp-json/mcp/wp-content --header "Authorization: Basic <base64 of user:application-password>"\n'
               'The base64 value: python -c "import base64;print(base64.b64encode(b\'USER:APP PASSWORD\').decode())". '
               'The tools read ~/.claude.json directly, so no restart is needed for them; restart Claude Code (or /mcp) for '
               'the MCP tools in chat.') % (s2, name, origin)
        item('mcp', 'ask', 'no MCP entry for %s; the Meta MCP route exists' % real_host, how)
    else:
        item('mcp', 'ask', 'no MCP entry for %s and no Meta MCP route on the site (/wp-json/mcp/wp-content answered %s)' % (real_host, s2),
             'The site needs the Meta MCP WordPress plugin (MetaHotels\' fork of the WordPress MCP Adapter) installed and '
             'active, with writes enabled in its settings; then an MCP entry named %s (this check prints the command once the '
             'route exists). Can you install it, or should the pass run without content changes (measure and report only)?' % name)
    setdefault('mcp_server', name)

# access through the entry
if server:
    tmp = os.path.join(site_dir, 'audit', 'integrations-status.json')
    r = subprocess.run([sys.executable, '-I', os.path.join(HERE, 'wp', 'mcp_call.py'), server,
                        'mcp-adapter-content-integrations-status', '{}', tmp], capture_output=True, text=True)
    if r.returncode == 0 and os.path.exists(tmp):
        d = json.load(open(tmp, encoding='utf-8'))
        perm = d.get('permissions') or {}
        elx = d.get('elementor') or {}
        pll = d.get('polylang') or {}
        admin = 'administrator' in (perm.get('roles') or [])
        writes = d.get('writes_enabled')
        item('access', 'ok' if admin and writes else 'ask',
             'Meta MCP %s; user %s (%s); writes %s; Elementor %s%s; Polylang %s' % (
                 d.get('plugin_version'), perm.get('user_login'), ','.join(perm.get('roles') or []), 'on' if writes else 'OFF',
                 elx.get('version') or 'off', ' Pro' if elx.get('pro_active') else '', ', '.join(
                     l.get('slug', str(l)) if isinstance(l, dict) else str(l) for l in pll.get('languages') or []) or 'off'),
             '' if admin and writes else 'The MCP user is not an administrator or writes are off in the Meta MCP settings. '
             'Image uploads, Elementor edits and REST reads of plugins and Custom Code need both: can you change that?')
        types = (d.get('wordpress') or {}).get('post_types') or []
        setdefault('post_types', list(dict.fromkeys(['post', 'page'] + [t for t in (elx.get('enabled_post_types') or []) + types
                                                                        if t in HOTEL_TYPES])))
        if pll.get('languages'):
            setdefault('languages', [l.get('slug', l) if isinstance(l, dict) else l for l in pll['languages']])
    else:
        item('access', 'ask', 'MCP call failed: %s' % (r.stdout + r.stderr).strip()[:200],
             'The MCP entry exists but the call failed (wrong application password, the plugin off, or a security plugin '
             'blocking REST). Can you check the entry and the plugin?')

# PageSpeed key
env = sitecfg.psi_env(site_dir)
key = bool(sitecfg.read_key(env) or os.environ.get('PAGESPEED_API_KEY'))
item('pagespeed', 'ok' if key else 'ask', ('key found in ' + env) if key else 'no key in ' + env,
     '' if key else 'Put your PageSpeed Insights API key in %s as PAGESPEED_API_KEY=... (edit the file yourself, do not '
     'paste it here). Without it the pass measures on the throttled phone only, with no PageSpeed scores.' % env)

# owner and browser: always confirmed once per site
if not site.get('booking_links'):
    item('owner', 'ask', 'booking links per hotel not recorded (%d Mirai link(s) on the homepage now)' % len(book),
         'What is the Mirai booking link for each hotel on this site? (Rule: never built or copied from another hotel; '
         'they go into site.json booking_links.)')
item('owner', 'ask', 'context only the owner knows',
     'Is a CDN or DNS change planned during the work? Are there plugins, popups or pages the owner relies on that the '
     'site does not show (drafts, seasonal popups, backup pages)? Should this site get a report (or --omit-report)?')
item('browser', 'ask', 'LiteSpeed and Elementor settings are read and changed in your Chrome',
     'Is Chrome (with the Claude in Chrome extension) logged into %s/wp-admin/ ?' % origin)

# write site.json and the onboarding record
if not os.path.exists(sj_path):
    base = {'host': None, 'mcp_server': None, 'psi_env': None, 'post_types': None, 'languages': None,
            'pages': {}, 'selectors': {}, 'markers': {}, 'booking_links': {}, 'notes': []}
    site = {k: (site.get(k, v)) for k, v in base.items() if site.get(k, v) is not None} | {k: v for k, v in site.items() if k not in base}
json.dump(site, open(sj_path, 'w', encoding='utf-8', newline='\n'), indent=2, ensure_ascii=False)
rec = {'date': datetime.date.today().isoformat(), 'site_dir': site_dir, 'created': created, 'filled': fill, 'checks': results}
json.dump(rec, open(os.path.join(site_dir, 'audit', 'onboarding-%s.json' % rec['date']), 'w', encoding='utf-8'), indent=1, ensure_ascii=False)

if '--json' in opt:
    print(json.dumps(rec, indent=1, ensure_ascii=False))
    sys.exit()
print('site folder: %s%s' % (site_dir, ' (created)' if created else ''))
if fill:
    print('site.json filled: ' + ', '.join('%s=%s' % (k, json.dumps(v, ensure_ascii=False)[:80]) for k, v in fill.items()))
print()
for r in results:
    print('  %-4s %-9s %s' % (r['status'].upper() if r['status'] != 'ok' else 'ok', r['area'], r['detail']))
asks = [r for r in results if r['ask']]
print('\nto ask the user (%d):' % len(asks))
for i, r in enumerate(asks, 1):
    print('%d. [%s] %s' % (i, r['area'], r['ask']))
