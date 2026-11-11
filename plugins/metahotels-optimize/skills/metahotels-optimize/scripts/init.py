"""Set up this machine and a work folder for MetaHotels optimization passes (`/metahotels-optimize:optimize --init`).

Usage: python -I <skill>/scripts/init.py [work-folder] [--no-npm] [--test-key] [--json]
  --test-key    one PageSpeed call on example.com to confirm the key works (the key is never printed)
  work-folder   where the site folders and the two cross-site documents live (default: the current folder)
Idempotent: it never overwrites an existing file or a key; run it again after updating the plugin (the plugin
folder is replaced on update, so the Node dependencies have to be installed again).

It does:
  1. checks the prerequisites: Python 3.10+, Node 18+ and npm, bash and curl, Chrome or Chromium, and optionally
     PHP (php -l), git, Pillow >= 11.3 and fonttools (image and icon-font tools)
  2. installs the Node dependencies in <skill>/scripts (npm ci; no browser download, it drives the installed Chrome)
  3. creates in the work folder, when missing:
       metahotels.json            marks the work folder (tools find it from any site folder below it)
       .env                       PAGESPEED_API_KEY= (empty: the user puts their own key in; never printed)
       optimization-results.md, score-vs-experience.md   the two cross-site documents
       .gitignore entry for .env  when the work folder is a git repository
  4. prints what is still missing, as a list of things to ask the user or do.
Nothing on any website is touched.
"""
import datetime
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
args = [a for a in sys.argv[1:] if not a.startswith('--')]
WORK = os.path.abspath(args[0] if args else os.getcwd())
AS_JSON = '--json' in sys.argv
TODAY = datetime.date.today().isoformat()
checks, todo, done = [], [], []


def run(cmd, **kw):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=kw.pop('timeout', 60), **kw)
        return r.returncode, (r.stdout + r.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)


def check(name, ok, detail, need=True, fix=''):
    checks.append({'name': name, 'ok': bool(ok), 'detail': detail, 'required': need})
    if not ok and fix:
        todo.append(('required' if need else 'optional') + ': ' + fix)


# 1. prerequisites
check('python', sys.version_info >= (3, 10), sys.version.split()[0], fix='install Python 3.10 or newer')
node = shutil.which('node')
nv = run([node, '-v'])[1] if node else ''
m = re.match(r'v(\d+)', nv)
check('node', m and int(m.group(1)) >= 18, nv or 'not found', fix='install Node.js 18 or newer (https://nodejs.org)')
npm = shutil.which('npm') or shutil.which('npm.cmd')
check('npm', npm, npm or 'not found', fix='install npm (comes with Node.js)')
bash = shutil.which('bash')
check('bash', bash, bash or 'not found', fix='install Git for Windows (Git Bash) or use a system with bash')
check('curl', shutil.which('curl'), shutil.which('curl') or 'not found', fix='install curl')
chrome = os.environ.get('CHROME_PATH') or next((p for p in {
    'win32': ['C:/Program Files/Google/Chrome/Application/chrome.exe',
              'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
              os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Google/Chrome/Application/chrome.exe')],
    'darwin': ['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', '/Applications/Chromium.app/Contents/MacOS/Chromium'],
}.get(sys.platform, ['/usr/bin/google-chrome', '/usr/bin/google-chrome-stable', '/usr/bin/chromium', '/usr/bin/chromium-browser', '/snap/bin/chromium'])
    if os.path.exists(p)), None)
check('chrome', chrome, chrome or 'not found', fix='install Google Chrome, or set CHROME_PATH to a Chrome/Chromium executable')
php = os.environ.get('PHP_BIN') or shutil.which('php') or ('C:/xampp/php/php.exe' if os.path.exists('C:/xampp/php/php.exe') else None)
check('php', php, php or 'not found', need=False, fix='install a PHP CLI (or set PHP_BIN) to lint the site plugin before zipping')
check('git', shutil.which('git'), shutil.which('git') or 'not found', need=False, fix='install git (LibreCrawl clone, plugin updates)')
code, out = run([sys.executable, '-c', 'import PIL; print(PIL.__version__)'])
pil_ok = code == 0 and tuple(int(x) for x in re.findall(r'\d+', out)[:2]) >= (11, 3)
check('pillow', pil_ok, out if code == 0 else 'not installed', need=False,
      fix='pip install --user "pillow>=11.3"   (the image re-encode, step 2b, needs AVIF support)')
code, out = run([sys.executable, '-c', 'import fontTools, brotli; print(fontTools.version)'])
check('fonttools', code == 0, out if code == 0 else 'not installed', need=False,
      fix='pip install --user fonttools brotli   (only for icon-font subsets)')

# 2. Node dependencies of the tools
nm = os.path.join(HERE, 'node_modules')
lock = os.path.join(HERE, 'package-lock.json')
stamp = os.path.join(nm, '.package-lock.json')
fresh = os.path.isdir(nm) and os.path.exists(stamp) and os.path.getmtime(stamp) >= os.path.getmtime(lock)
if fresh:
    check('node deps', True, 'installed in ' + nm)
elif '--no-npm' in sys.argv or not npm:
    check('node deps', False, 'not installed', fix='npm ci  (in %s)' % HERE)
else:
    code, out = run([npm, 'ci', '--no-audit', '--no-fund'], cwd=HERE, timeout=600, shell=sys.platform == 'win32')
    check('node deps', code == 0, (out.splitlines() or [''])[-1][:160], fix='npm ci failed in %s: %s' % (HERE, out[-300:]))
    if code == 0:
        done.append('installed the Node dependencies in ' + HERE)

# 3. work folder
os.makedirs(WORK, exist_ok=True)


def create(name, text):
    p = os.path.join(WORK, name)
    if os.path.exists(p):
        return False
    with open(p, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)
    done.append('created ' + p)
    return True


create('metahotels.json', json.dumps({
    'about': 'Work folder for MetaHotels optimization passes (metahotels-optimize plugin). One folder per site.',
    'created': TODAY,
    'defaults': {'report': True},
}, indent=2) + '\n')
env = os.path.join(WORK, '.env')
if not create('.env', '# PageSpeed Insights API key used by every site in this folder (a site folder can have its own .env).\n'
                      '# Create one: Google Cloud console > APIs & Services > enable "PageSpeed Insights API" > Credentials >\n'
                      '# Create credentials > API key. Paste it after the = sign, no quotes. Never commit this file.\n'
                      'PAGESPEED_API_KEY=\n'):
    if not re.search(r'^\s*PAGESPEED_API_KEY\s*=', open(env, encoding='utf-8').read(), re.M):
        with open(env, 'a', encoding='utf-8', newline='\n') as f:
            f.write('\nPAGESPEED_API_KEY=\n')
        done.append('added an empty PAGESPEED_API_KEY line to ' + env)
sys.path.insert(0, os.path.join(HERE, 'wp'))
import sitecfg  # noqa: E402
key = sitecfg.read_key(env) or os.environ.get('PAGESPEED_API_KEY', '')
check('pagespeed key', key, ('set in ' + env) if key else 'empty in ' + env,
      fix='put your PageSpeed Insights API key in %s (PAGESPEED_API_KEY=...). Edit the file yourself; do not paste the key into the chat' % env)
if key and '--test-key' in sys.argv:
    # one mobile run on example.com, about 15 s; the key itself is never printed
    import urllib.error
    import urllib.parse
    import urllib.request
    api = 'https://www.googleapis.com/pagespeedonline/v5/runPagespeed?' + urllib.parse.urlencode(
        {'url': 'https://example.com/', 'strategy': 'mobile', 'category': 'performance', 'key': key})
    try:
        with urllib.request.urlopen(api, timeout=180) as r:
            ok = 'lighthouseResult' in json.loads(r.read().decode())
        check('pagespeed api', ok, 'test call answered' if ok else 'unexpected answer')
    except urllib.error.HTTPError as e:
        msg = e.read().decode('utf-8', 'replace')
        reason = (re.search(r'"message":\s*"([^"]+)"', msg) or re.search(r'(.{0,120})', msg)).group(1)
        check('pagespeed api', False, 'HTTP %s: %s' % (e.code, reason[:140].replace(key, '<key>')),
              fix='the PageSpeed key was refused: check it is an API key with the PageSpeed Insights API enabled')
    except Exception as e:  # noqa: BLE001
        check('pagespeed api', False, str(e)[:120], fix='the PageSpeed test call failed (network?): run --init --test-key again')
create('optimization-results.md', '# Optimization results\n\nLast updated: %s\n\nWhat was changed on each site and the before and '
       'after. One section per site, added at the end of each pass (references/report.md). Mobile rows before desktop.\n\n'
       '## At a glance\n\n| Site | Pass | PageSpeed mobile before | PageSpeed mobile after | Throttled largest paint before | after | Page weight before | after |\n'
       '|---|---|---|---|---|---|---|---|\n' % TODAY)
create('score-vs-experience.md', '# Score versus visitor experience\n\nLast updated: %s\n\nThe decisions where a lab number '
       'and what a visitor gets disagreed: a score gain taken at a real-load cost, a score gain left off because it was a '
       'huge departure for visitors, a change kept although the score stayed flat or fell, a measured gain rejected because '
       'it broke something. One section per site (references/report.md).\n' % TODAY)
if os.path.isdir(os.path.join(WORK, '.git')):
    gi = os.path.join(WORK, '.gitignore')
    have = open(gi, encoding='utf-8').read() if os.path.exists(gi) else ''
    if not re.search(r'^\.env$', have, re.M):
        with open(gi, 'a', encoding='utf-8', newline='\n') as f:
            f.write(('\n' if have and not have.endswith('\n') else '') + '.env\n*/.env\n')
        done.append('added .env to ' + gi)

# 4. what is left
todo += ['per site: run `/metahotels-optimize:optimize <site>`; it checks the site\'s MCP server, wp-admin access and '
         'what the owner must provide, and asks for each missing item']
if AS_JSON:
    print(json.dumps({'work_folder': WORK, 'skill': SKILL, 'checks': checks, 'done': done, 'todo': todo}, indent=1))
    sys.exit()
print('work folder:', WORK)
print('skill:      ', SKILL)
print()
for c in checks:
    print('  %-4s %-14s %s%s' % ('ok' if c['ok'] else ('MISS' if c['required'] else 'opt'), c['name'], c['detail'][:110],
                                '' if c['required'] else '  (optional)'))
if done:
    print('\ndone:')
    for d in done:
        print('  - ' + d)
print('\nstill to do:')
for t in todo:
    print('  - ' + t)
