"""Repoint every document that uses a re-encoded image (step 2b step 5), one document at a time.

Usage (from the site folder): python -I <skill>/scripts/wp/repoint-all.py <list.json> <uploaded.json> [--apply]
<list.json> is image-list.py's output (each image's "uses" names the documents); <uploaded.json> is wp_upload.py's.
For each document that uses an uploaded image: read its tree fresh (rollback copy
audit/elementor/elementor-<post>-pre-images.json, kept if it exists), then run repoint-images.py on it (dry run
unless --apply). Rollback of one document:
  python -I <skill>/scripts/wp/repoint-images.py <server> <post> audit/elementor/elementor-<post>-pre-images.json <uploaded.json> --apply --revert
Generalised from Khalidia's repoint-all.sh (2026-10-13).
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sitecfg  # noqa: E402

SERVER = sitecfg.load()['mcp_server']
lst, up = sys.argv[1], sys.argv[2]
apply = '--apply' in sys.argv
uploaded = {int(u['old_id']) for u in json.load(open(up, encoding='utf-8'))}
posts = set()
for it in json.load(open(lst, encoding='utf-8')):
    if int(it['id']) in uploaded:
        posts.update(int(x.split(':')[0]) for x in it.get('uses', []))
os.makedirs(os.path.join('audit', 'elementor'), exist_ok=True)
print('documents:', len(posts), '(apply)' if apply else '(dry run)')
for p in sorted(posts):
    b = os.path.join('audit', 'elementor', 'elementor-%d-pre-images.json' % p)
    if not os.path.exists(b):
        r = subprocess.run([sys.executable, '-I', sitecfg.MCP_CALL, SERVER, 'mcp-adapter-elementor-get-data',
                            '{"post_id": %d}' % p, b], capture_output=True, text=True)
        if r.returncode != 0:
            print(p, 'READ FAILED', (r.stdout + r.stderr)[:200])
            continue
    print('==', p, flush=True)
    r = subprocess.run([sys.executable, '-I', os.path.join(sitecfg.HERE, 'repoint-images.py'), SERVER, str(p), b, up]
                       + (['--apply'] if apply else []), capture_output=True, text=True)
    print('\n'.join((r.stdout + r.stderr).strip().splitlines()[-3:]), flush=True)
    if r.returncode != 0:
        print(p, 'STOPPED: repoint failed')
        sys.exit(1)
