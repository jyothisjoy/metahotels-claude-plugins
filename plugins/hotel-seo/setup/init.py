"""/hotel-seo init: set up this machine for the hotel-seo skill. Safe to re-run.

Run from the plugin folder with uv (which provides Python):
  uv run --project <plugin>/server python <plugin>/setup/init.py [--check] [--skip-google] [--skip-desktop]

Steps:
  1. LibreCrawl at the pinned version in ~/.metahotels-seo/librecrawl (patched to
     listen on 127.0.0.1:5057), its venv, and Chromium.
  2. Chromium for the PDF renderer.
  3. Desktop app: a copy of the MCP server in ~/.metahotels-seo/server, the three
     MCP servers merged into claude_desktop_config.json (backed up first), and the
     skill zipped for upload.
  4. Google sign-in (one consent screen for GA4 + Search Console) if needed.
  5. Health check and a one-page test crawl.
"""
import argparse
import io
import json
import os
import platform
import secrets
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]
SERVER_SRC = PLUGIN_DIR / 'server'
SKILL_SRC = PLUGIN_DIR / 'skills' / 'hotel-seo'
sys.path.insert(0, str(SERVER_SRC))

from hotel_seo_tools import __version__, health, librecrawl_proc, paths  # noqa: E402

LIBRECRAWL_REPO = 'PhialsBasement/LibreCrawl'
LIBRECRAWL_PIN = '05a1372de8334ca18dec0bc1f7470c62901a9418'   # 29 Sep 2026, tested 14 Oct 2026
VERSION_FILE = paths.LIBRECRAWL_DIR / '.hotel-seo-pin'
SERVE_ORIG = "serve(app, host='0.0.0.0', port=5000, threads=8)"
SERVE_NEW = ("serve(app, host=os.environ.get('LIBRECRAWL_HOST', '0.0.0.0'), "
             "port=int(os.environ.get('LIBRECRAWL_PORT', '5000')), threads=8)")
DESKTOP_WORK = Path.home() / 'Documents' / 'MetaHotels SEO'
SERVER_NAMES = ('hotel-seo-tools', 'hotel-seo-gsc', 'hotel-seo-ga4')


def say(msg):
    print(msg, flush=True)


def run(cmd, **kw):
    say('  $ ' + ' '.join(str(c) for c in cmd))
    subprocess.run([str(c) for c in cmd], check=True, **kw)


def find_uv():
    uv = shutil.which('uv')
    if uv:
        return uv
    for cand in (Path.home() / '.local' / 'bin' / ('uv.exe' if os.name == 'nt' else 'uv'),
                 Path.home() / '.cargo' / 'bin' / 'uv'):
        if cand.exists():
            return str(cand)
    sys.exit('uv not found. Install it first (see SKILL.md, /hotel-seo init step 1).')


# ---------------------------------------------------------------- 1. LibreCrawl

def install_librecrawl(uv, force=False):
    say('\n[1/5] LibreCrawl')
    pinned = VERSION_FILE.exists() and VERSION_FILE.read_text().strip() == LIBRECRAWL_PIN
    if librecrawl_proc.is_installed() and pinned and not force:
        say(f'  already installed at {paths.LIBRECRAWL_DIR} (pin {LIBRECRAWL_PIN[:7]})')
        return
    if librecrawl_proc.is_running():
        say('  stopping the running LibreCrawl before updating it')
        librecrawl_proc.stop()
        time.sleep(2)

    url = f'https://codeload.github.com/{LIBRECRAWL_REPO}/zip/{LIBRECRAWL_PIN}'
    say(f'  downloading {url}')
    with urllib.request.urlopen(url, timeout=120) as r:
        archive = zipfile.ZipFile(io.BytesIO(r.read()))

    dest = paths.LIBRECRAWL_DIR
    keep = {}
    for name in ('data', '.env'):     # crawl history and settings survive updates
        if (dest / name).exists():
            keep[name] = dest.parent / f'.librecrawl-keep-{name}'
            shutil.rmtree(keep[name], ignore_errors=True) if keep[name].is_dir() else keep[name].unlink(missing_ok=True)
            shutil.move(str(dest / name), str(keep[name]))
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    root = archive.namelist()[0].split('/')[0]
    for member in archive.infolist():
        rel = member.filename[len(root) + 1:]
        if not rel:
            continue
        target = dest / rel
        if member.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(member))
    for name, tmp in keep.items():
        if (dest / name).exists():
            shutil.rmtree(dest / name) if (dest / name).is_dir() else (dest / name).unlink()
        shutil.move(str(tmp), str(dest / name))

    main_py = dest / 'main.py'
    src = main_py.read_text(encoding='utf-8')
    if SERVE_ORIG not in src:
        sys.exit('LibreCrawl main.py changed upstream; the localhost patch no longer applies. '
                 'Update SERVE_ORIG in setup/init.py.')
    main_py.write_text(src.replace(SERVE_ORIG, SERVE_NEW), encoding='utf-8')
    say('  patched main.py: listens on LIBRECRAWL_HOST:LIBRECRAWL_PORT (127.0.0.1:5057)')

    env_file = dest / '.env'
    if not env_file.exists():
        env_file.write_text(
            '# Written by /hotel-seo init. Local mode = no login; bound to 127.0.0.1 by the launcher.\n'
            'LOCAL_MODE=true\nHOST_BINDING=127.0.0.1\n'
            f'SECRET_KEY={secrets.token_hex(32)}\n', encoding='utf-8')
    (dest / 'data').mkdir(exist_ok=True)

    run([uv, 'venv', '--python', '3.11', '--allow-existing', dest / '.venv'])
    py = paths.librecrawl_python()
    run([uv, 'pip', 'install', '--python', py, '-r', dest / 'requirements.txt'])
    run([py, '-m', 'playwright', 'install', 'chromium'])
    VERSION_FILE.write_text(LIBRECRAWL_PIN)
    say('  LibreCrawl ready')


# ---------------------------------------------------------------- 2. Chromium for PDFs

def install_pdf_chromium():
    say('\n[2/5] Chromium for PDFs')
    run([sys.executable, '-m', 'playwright', 'install', 'chromium'])


# ---------------------------------------------------------------- 3. Desktop app

def desktop_config_paths():
    if platform.system() == 'Darwin':
        return [Path.home() / 'Library' / 'Application Support' / 'Claude' / 'claude_desktop_config.json']
    if os.name == 'nt':
        found = [Path(os.environ.get('APPDATA', '')) / 'Claude' / 'claude_desktop_config.json']
        pkgs = Path(os.environ.get('LOCALAPPDATA', '')) / 'Packages'
        if pkgs.exists():    # Microsoft Store install
            found += [p / 'LocalCache' / 'Roaming' / 'Claude' / 'claude_desktop_config.json'
                      for p in pkgs.glob('Claude_*')]
        return found
    return [Path.home() / '.config' / 'Claude' / 'claude_desktop_config.json']


def stop_copy_processes(copy):
    """The desktop app keeps hotel-seo-tools / gsc / ga4 running from the server copy, and on Windows
    their open files can't be deleted. Stop them (the app restarts them when reopened)."""
    if os.name != 'nt':
        return []
    ps = ("Get-CimInstance Win32_Process | Where-Object { ($_.ExecutablePath -and $_.ExecutablePath.StartsWith($env:HSC, "
          "'OrdinalIgnoreCase')) -or ($_.CommandLine -and $_.CommandLine.IndexOf($env:HSC, "
          "[StringComparison]::OrdinalIgnoreCase) -ge 0) } | Where-Object { $_.ProcessId -ne $PID } | "
          "Select-Object -ExpandProperty ProcessId")
    try:
        out = subprocess.run(['powershell', '-NoProfile', '-Command', ps], capture_output=True, text=True,
                             env={**os.environ, 'HSC': str(copy)}, timeout=60).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    pids = [p for p in out.split() if p.isdigit() and int(p) != os.getpid()]
    for pid in pids:
        subprocess.run(['taskkill', '/F', '/T', '/PID', pid], capture_output=True)
    return pids


def setup_desktop(uv):
    say('\n[3/5] Claude desktop app')
    copy = paths.HOME / 'server'
    if copy.exists():
        stopped = stop_copy_processes(copy)
        if stopped:
            say(f'  stopped {len(stopped)} desktop-app server process(es) using the old copy; '
                'quit and reopen the desktop app afterwards')
            time.sleep(2)
        try:
            shutil.rmtree(copy)
        except OSError as e:
            sys.exit(f'  Could not replace {copy}: {e}\n  A program still has files open there (usually the Claude '
                     'desktop app). Quit the desktop app completely (tray icon -> Quit) and run init again.')
    shutil.copytree(SERVER_SRC, copy, ignore=shutil.ignore_patterns('.venv', '__pycache__', '*.pyc'))
    paths.GOOGLE_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(PLUGIN_DIR / 'setup' / 'google' / 'client_secret.json', paths.GOOGLE_DIR / 'client_secret.json')
    run([uv, 'sync', '--project', copy, '--quiet'])
    say(f'  server copy at {copy}')

    DESKTOP_WORK.mkdir(parents=True, exist_ok=True)
    common_env = {'HOTEL_SEO_HOME': str(DESKTOP_WORK), 'PYTHONUTF8': '1'}
    servers = {
        'hotel-seo-tools': {'command': uv, 'args': ['run', '--project', str(copy), 'hotel-seo-tools'],
                            'env': common_env},
        'hotel-seo-gsc': {'command': uv, 'args': ['run', '--project', str(copy), 'hotel-seo-launch', 'gsc'],
                          'env': common_env},
        'hotel-seo-ga4': {'command': uv, 'args': ['run', '--project', str(copy), 'hotel-seo-launch', 'ga4'],
                          'env': common_env},
    }
    targets = [p for p in desktop_config_paths() if p.parent.exists()]
    if not targets:
        say('  Claude desktop app not found; skipped. Re-run init after installing it.')
    for cfg in targets:
        data = {}
        if cfg.exists():
            backup = cfg.with_name(f'claude_desktop_config.backup-{time.strftime("%Y%m%d-%H%M%S")}.json')
            shutil.copy2(cfg, backup)
            data = json.loads(cfg.read_text(encoding='utf-8') or '{}')
            say(f'  backed up {cfg.name} -> {backup.name}')
        data.setdefault('mcpServers', {}).update(servers)
        cfg.write_text(json.dumps(data, indent=2), encoding='utf-8')
        say(f'  added {", ".join(SERVER_NAMES)} to {cfg}')

    zip_path = paths.HOME / 'hotel-seo-skill.zip'
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as z:
        for f in SKILL_SRC.rglob('*'):
            if f.is_file():
                z.write(f, Path('hotel-seo') / f.relative_to(SKILL_SRC))
    say(f'  skill zip for the desktop app: {zip_path}')
    say('  -> In the desktop app: Settings -> Capabilities -> Skills -> Upload skill, pick that zip,')
    say('     then fully quit and reopen the app so it loads the three MCP servers.')


# ---------------------------------------------------------------- 4. Google sign-in

ADS_MANAGER_ID = '437-179-3247'    # MetaHotels Manager (Google Ads); Keyword Planner runs through it


def google_signin(no_browser=False):
    say('\n[4/5] Google sign-in')
    from hotel_seo_tools import keywords
    if not keywords.ADS_CONFIG.exists():
        paths.GOOGLE_DIR.mkdir(parents=True, exist_ok=True)
        keywords.ADS_CONFIG.write_text(json.dumps({'login_customer_id': ADS_MANAGER_ID,
                                                   'customer_id': ADS_MANAGER_ID}, indent=2))
        say(f'  Keyword Planner: Google Ads manager {ADS_MANAGER_ID} saved to {keywords.ADS_CONFIG}')
    rows = health.check_google()
    from hotel_seo_tools import gbp
    if all(r['ok'] for r in rows) and keywords.configured()[0] and gbp.configured()[0]:
        for r in rows:
            say(f"  {r['check']}: {r['detail']}")
        say('  already signed in')
        return
    say('  Sign in as metahotels.m@gmail.com and allow every permission (Analytics, Search Console, Drive')
    say('  files, Google Ads, Business Profile). If Google shows "Google hasn\'t verified this app": click Advanced ->')
    say('  Go to MetaHotels SEO (unsafe) -> Continue. Waiting up to 10 minutes...')
    cmd = [sys.executable, '-m', 'hotel_seo_tools.google_auth', '--with-ads', '--with-gbp'] + (['--no-browser'] if no_browser else [])
    run(cmd, cwd=str(SERVER_SRC))


# ---------------------------------------------------------------- 5. checks

def final_check(test_crawl=True):
    say('\n[5/5] Health check')
    result = health.run()
    say(health.as_table(result))
    if test_crawl:
        from hotel_seo_tools import librecrawl
        import tempfile
        say('\n  test crawl of https://example.com/ (1 URL)...')
        try:
            with tempfile.TemporaryDirectory() as tmp:
                r = librecrawl.crawl('https://example.com/', tmp, max_urls=1)
            say(f"  [OK  ] test crawl: {r['internal_urls']} URL(s), status codes {r['status_codes']}")
        except Exception as e:  # noqa: BLE001
            say(f'  [FAIL] test crawl: {e}')
            result['all_ok'] = False
    return result['all_ok']


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--check', action='store_true', help='health check only; install nothing')
    ap.add_argument('--skip-google', action='store_true')
    ap.add_argument('--skip-desktop', action='store_true')
    ap.add_argument('--no-browser', action='store_true', help='print the Google sign-in link instead of opening it')
    ap.add_argument('--force-librecrawl', action='store_true', help='reinstall LibreCrawl even if the pin matches')
    args = ap.parse_args()

    say(f'hotel-seo {__version__} init on {platform.system()} ({paths.HOME})')
    if args.check:
        ok = final_check(test_crawl=False)
        sys.exit(0 if ok else 1)

    uv = find_uv()
    paths.HOME.mkdir(parents=True, exist_ok=True)
    install_librecrawl(uv, force=args.force_librecrawl)
    install_pdf_chromium()
    if args.skip_desktop:
        say('\n[3/5] Claude desktop app: skipped')
    else:
        setup_desktop(uv)
    if args.skip_google:
        say('\n[4/5] Google sign-in: skipped')
    else:
        google_signin(no_browser=args.no_browser)
    ok = final_check()
    say('\nAll set. Give Claude a hotel website: /hotel-seo example-hotel.com' if ok
        else '\nSome checks failed; see the fix lines above.')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
