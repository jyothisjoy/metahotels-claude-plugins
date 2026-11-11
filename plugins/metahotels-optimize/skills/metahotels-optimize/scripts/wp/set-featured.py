"""Point featured images at the re-encoded WebP attachments (playbook step 2b).

Usage (from the site folder): python -I <skill>/scripts/wp/set-featured.py [--apply | --revert]
Lists every post of the site.json post_types through the MCP; any post whose
featured image is an original that has a WebP re-encode (images/uploaded*.json, round one and the featured round)
is switched to the new attachment with mcp-adapter-update-post (featured_media). AVIF re-encodes are never used as
featured images (hosts that cannot write AVIF build no crop sizes; social previews need WebP). Without --apply it only prints.
Rollback: rollback/featured-images-before.json (post, old id), written before the first change; --revert restores it.
"""
import glob
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
RB = 'rollback/featured-images-before.json'
mode = sys.argv[1] if len(sys.argv) > 1 else ''
tmp = os.path.join(tempfile.gettempdir(), 'set-featured.json')


def call(tool, args):
    r = subprocess.run([sys.executable, '-I', sitecfg.MCP_CALL, SERVER, tool, json.dumps(args), tmp], capture_output=True, text=True)
    return json.load(open(tmp, encoding='utf-8')) if r.returncode == 0 and os.path.exists(tmp) else {}


if mode == '--revert':
    for r in json.load(open(RB, encoding='utf-8')):
        print(r['post'], '->', r['old_id'], call('mcp-adapter-update-post', {'post_id': r['post'], 'featured_media': r['old_id']}).get('success'))
    sys.exit()

webp = {}
for f in glob.glob('images/uploaded*.json'):
    for u in json.load(open(f, encoding='utf-8')):
        if u['new_url'].endswith('.webp'):
            webp[int(u['old_id'])] = (int(u['new_id']), u['new_url'])
rows = []
for t in TYPES:
    page = 1
    while True:
        d = call('mcp-adapter-list-posts', {'post_type': t, 'per_page': 100, 'page': page, 'status': 'any'})
        if not d.get('success'):
            print(t, 'list failed', str(d)[:200])
            sys.exit(1)
        for p in d['posts']:
            fm = int(p.get('featured_media') or 0)
            if fm in webp:
                rows.append({'post': p['id'], 'type': t, 'status': p['status'], 'old_id': fm, 'new_id': webp[fm][0]})
        if page >= (d.get('total_pages') or 1):
            break
        page += 1
print(len(rows), 'posts to change')
if mode != '--apply':
    for r in rows:
        print(r['post'], r['type'], r['status'], r['old_id'], '->', r['new_id'], webp[r['old_id']][1].rsplit('/', 1)[1])
    sys.exit()
if not os.path.exists(RB):
    json.dump(rows, open(RB, 'w', encoding='utf-8'), indent=1)
for r in rows:
    ok = call('mcp-adapter-update-post', {'post_id': r['post'], 'featured_media': r['new_id']}).get('success')
    print(r['post'], r['type'], r['old_id'], '->', r['new_id'], 'OK' if ok else 'FAILED', flush=True)
