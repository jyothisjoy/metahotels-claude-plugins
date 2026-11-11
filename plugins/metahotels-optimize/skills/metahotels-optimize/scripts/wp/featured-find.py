"""Find the posts (any content type) whose featured image is one of the given attachment ids.

Usage (from the site folder): python -I <skill>/scripts/wp/featured-find.py <out.json> <id> [<id> ...]
Lists every post of the site.json post_types through the MCP (custom types are often not in REST) and writes {attachment id: [{post id, type, status, title}]} to <out.json>.
"""
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sitecfg  # noqa: E402

CFG = sitecfg.load()
SERVER = CFG['mcp_server']
TYPES = CFG['post_types']
out, want = sys.argv[1], {int(a) for a in sys.argv[2:]}
found = {i: [] for i in sorted(want)}
tmp = os.path.join(tempfile.gettempdir(), 'featured-find.json')
for t in TYPES:
    page = 1
    while True:
        args = json.dumps({'post_type': t, 'per_page': 100, 'page': page, 'status': 'any'})
        r = subprocess.run([sys.executable, '-I', sitecfg.MCP_CALL, SERVER, 'mcp-adapter-list-posts', args, tmp], capture_output=True, text=True)
        d = json.load(open(tmp, encoding='utf-8')) if r.returncode == 0 else {}
        if not d.get('success'):
            print(t, 'page', page, 'failed', str(d)[:200])
            break
        for p in d['posts']:
            if p.get('featured_media') in want:
                found[p['featured_media']].append({'post': p['id'], 'type': t, 'status': p['status'], 'title': p['title']})
        print(t, 'page', page, len(d['posts']), 'of', d.get('total'), flush=True)
        if page >= (d.get('total_pages') or 1):
            break
        page += 1
json.dump(found, open(out, 'w', encoding='utf-8'), indent=1)
for i, ps in found.items():
    print(i, ['%s %s %s' % (p['type'], p['post'], p['status']) for p in ps])
