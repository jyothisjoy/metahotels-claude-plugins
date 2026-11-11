"""Save the Elementor tree of every document the site prints (step 2b step 1, and the rollback for every content
batch): pages, posts, header, footer, popups, loop items.

Usage (from the site folder): python -I <skill>/scripts/wp/save-trees.py <pages-dir> [out-dir] [--tag=before] [--refresh]
Collects every data-elementor-id from the saved pages (crawl.sh / warm.sh output) and writes
<out-dir>/elementor-<id>-<tag>.json (default audit/elementor/, tag "before") with mcp-adapter-elementor-get-data.
Existing files are kept (they are the rollback) unless --refresh. Popups and templates that no saved page prints
(a popup on a timer still prints its document; a template used only by a draft does not) can be added by id:
--ids=123,456. Prints the document types found and any read that failed.
"""
import collections
import glob
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sitecfg  # noqa: E402

SERVER = sitecfg.load()['mcp_server']
pos = [a for a in sys.argv[1:] if not a.startswith('--')]
pages = pos[0]
out = pos[1] if len(pos) > 1 else os.path.join('audit', 'elementor')
tag = next((a.split('=', 1)[1] for a in sys.argv if a.startswith('--tag=')), 'before')
extra = next((a.split('=', 1)[1] for a in sys.argv if a.startswith('--ids=')), '')
refresh = '--refresh' in sys.argv
os.makedirs(out, exist_ok=True)

docs = collections.OrderedDict()
for f in sorted(glob.glob(os.path.join(pages, '*.html'))):
    h = open(f, encoding='utf-8', errors='replace').read()
    for t, i in re.findall(r'data-elementor-type="([^"]+)"[^>]*data-elementor-id="(\d+)"', h):
        docs.setdefault(int(i), t)
for i in [x for x in extra.split(',') if x.strip()]:
    docs.setdefault(int(i), 'extra')
print('documents:', len(docs), dict(collections.Counter(docs.values())))
failed = []
for n, (i, t) in enumerate(docs.items(), 1):
    path = os.path.join(out, 'elementor-%d-%s.json' % (i, tag))
    if os.path.exists(path) and not refresh:
        continue
    r = subprocess.run([sys.executable, '-I', sitecfg.MCP_CALL, SERVER, 'mcp-adapter-elementor-get-data',
                        '{"post_id": %d}' % i, path], capture_output=True, text=True)
    ok = r.returncode == 0 and 'isError=False' in r.stdout
    if not ok:
        failed.append((i, t, (r.stdout + r.stderr).strip()[:120]))
        if os.path.exists(path):
            os.remove(path)
    print('%4d/%d %-12s %-6d %s' % (n, len(docs), t, i, 'ok' if ok else 'FAILED'), flush=True)
print('saved in', out, '| failed:', len(failed))
for f in failed:
    print('  ', *f)
