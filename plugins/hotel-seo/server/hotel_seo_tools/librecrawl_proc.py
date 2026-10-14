"""Find, start and stop the local LibreCrawl.

LibreCrawl runs in local mode (no login, admin tier) bound to 127.0.0.1 only,
on LIBRECRAWL_PORT (default 5057). The MCP server starts it on demand, so
nobody has to keep a console window open.
"""
import os
import subprocess
import sys
import time

import requests

from . import paths

PID_FILE = paths.HOME / 'librecrawl.pid'


def is_installed():
    return (paths.LIBRECRAWL_DIR / 'main.py').exists() and paths.librecrawl_python().exists()


def is_running(timeout=3):
    try:
        r = requests.get(f'{paths.LIBRECRAWL_URL}/api/user/info', timeout=timeout)
        return r.status_code == 200 and r.json().get('success') is True
    except (requests.RequestException, ValueError):
        return False


def start(wait=90):
    """Start LibreCrawl in the background if it isn't already up. Returns a status string."""
    if is_running():
        return 'already running'
    if not is_installed():
        raise RuntimeError('LibreCrawl is not installed on this machine. Run /hotel-seo init.')

    env = dict(os.environ)
    env.update({
        'LIBRECRAWL_HOST': '127.0.0.1',
        'LIBRECRAWL_PORT': str(paths.LIBRECRAWL_PORT),
        'PYTHONUTF8': '1',
        'PYTHONUNBUFFERED': '1',
    })
    paths.LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = open(paths.LOG_DIR / 'librecrawl.log', 'ab')
    kwargs = dict(cwd=str(paths.LIBRECRAWL_DIR), env=env, stdin=subprocess.DEVNULL,
                  stdout=log, stderr=subprocess.STDOUT)
    if os.name == 'nt':
        kwargs['creationflags'] = (subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
                                   | subprocess.CREATE_NO_WINDOW)
    else:
        kwargs['start_new_session'] = True
    proc = subprocess.Popen([str(paths.librecrawl_python()), 'main.py', '--local'], **kwargs)
    PID_FILE.write_text(str(proc.pid))

    deadline = time.time() + wait
    while time.time() < deadline:
        if is_running(timeout=2):
            return f'started (pid {proc.pid})'
        if proc.poll() is not None:
            raise RuntimeError(f'LibreCrawl exited with code {proc.returncode}. '
                               f'See {paths.LOG_DIR / "librecrawl.log"}')
        time.sleep(1)
    raise RuntimeError(f'LibreCrawl did not answer within {wait}s. See {paths.LOG_DIR / "librecrawl.log"}')


def stop():
    if not PID_FILE.exists():
        return 'not started by hotel-seo'
    pid = int(PID_FILE.read_text().strip() or 0)
    PID_FILE.unlink(missing_ok=True)
    if not pid:
        return 'no pid'
    try:
        if os.name == 'nt':
            subprocess.run(['taskkill', '/PID', str(pid), '/T', '/F'], capture_output=True)
        else:
            os.kill(pid, 15)
        return f'stopped pid {pid}'
    except OSError as e:
        return f'could not stop pid {pid}: {e}'


if __name__ == '__main__':
    print({'start': start, 'stop': stop}.get(sys.argv[1] if len(sys.argv) > 1 else 'start', start)())
