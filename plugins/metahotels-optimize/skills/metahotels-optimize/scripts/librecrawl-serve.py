# usage: <LIBRECRAWL_DIR>/.venv/Scripts/python.exe <skill>/scripts/librecrawl-serve.py   (run_in_background)
# LIBRECRAWL_DIR: the LibreCrawl clone (default: librecrawl/ next to this script); setup in references/link-check.md.
# Starts the local LibreCrawl (playbook step 1c) in local mode on 127.0.0.1:5000 only. Its own main.py always binds
# 0.0.0.0, and local mode has no login, so it would be open to the whole network. Also skips opening a browser tab.
import os, sys, webbrowser
import waitress

HERE = os.environ.get('LIBRECRAWL_DIR') or os.path.join(os.path.dirname(os.path.abspath(__file__)), 'librecrawl')
os.chdir(HERE)
sys.path.insert(0, HERE)
sys.argv = ['main.py', '--local', '--disable-register']

_serve = waitress.serve
waitress.serve = lambda app, **kw: _serve(app, host='127.0.0.1', port=5000, threads=kw.get('threads', 8))
webbrowser.open = lambda *a, **k: None

import main  # noqa: E402  (parses sys.argv above)
main.main()
