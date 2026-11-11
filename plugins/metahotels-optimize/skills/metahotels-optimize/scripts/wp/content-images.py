"""Swap block-editor image blocks in a post's content to the re-encoded WebP attachments (playbook step 2b).

Usage (from the site folder): python -I <skill>/scripts/wp/content-images.py <post-id> [--apply | --revert]
For each `<!-- wp:image {"id":N,...,"sizeSlug":S} -->` whose N has a WebP re-encode in images/uploaded*.json:
the block id, the img class wp-image-N and the img src (the new attachment's S size, else its full URL) are
replaced. Rollback: rollback/content-images-<post>-before.json, written before the first change.
"""
import glob
import json
import os
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sitecfg  # noqa: E402

SERVER = sitecfg.load()['mcp_server']
post = int(sys.argv[1])
mode = sys.argv[2] if len(sys.argv) > 2 else ''
RB = 'rollback/content-images-%d-before.json' % post
tmp = os.path.join(tempfile.gettempdir(), 'content-images.json')


def call(tool, args):
    r = subprocess.run([sys.executable, '-I', sitecfg.MCP_CALL, SERVER, tool, json.dumps(args), tmp], capture_output=True, text=True)
    return json.load(open(tmp, encoding='utf-8')) if r.returncode == 0 and os.path.exists(tmp) else {}


def content():
    d = call('mcp-adapter-get-post', {'post_id': post})
    p = d.get('post', d)
    c = p.get('content')
    return c.get('raw', '') if isinstance(c, dict) else (c or '')


def save(c):
    return bool(call('mcp-adapter-update-post', {'post_id': post, 'content': c}).get('success'))


if mode == '--revert':
    old = json.load(open(RB, encoding='utf-8'))['content']
    print(post, 'reverted' if save(old) and content() == old else 'REVERT MISMATCH')
    sys.exit()

webp = {}
for f in glob.glob('images/uploaded*.json'):
    for u in json.load(open(f, encoding='utf-8')):
        if u['new_url'].endswith('.webp'):
            webp[int(u['old_id'])] = int(u['new_id'])
c = content()
new = c
for m in re.finditer(r'<!-- wp:image (\{[^>]*?\}) -->(.*?)<!-- /wp:image -->', c, re.S):
    attrs = json.loads(m.group(1))
    old_id = int(attrs.get('id') or 0)
    if old_id not in webp:
        continue
    nid = webp[old_id]
    sub = subprocess.run([sys.executable, '-I', sitecfg.WP, SERVER, 'GET', '/wp-json/wp/v2/media/%d?context=edit&_fields=source_url,media_details' % nid], capture_output=True, text=True, env=dict(os.environ, MSYS_NO_PATHCONV='1'))
    md = json.loads(sub.stdout)
    sizes = md['media_details'].get('sizes') or {}
    src = (sizes.get(attrs.get('sizeSlug') or 'full') or {}).get('source_url') or md['source_url']
    block = m.group(0)
    old_src = re.search(r'<img[^>]*\ssrc="([^"]+)"', block).group(1)
    nb = block.replace('"id":%d' % old_id, '"id":%d' % nid, 1).replace('wp-image-%d' % old_id, 'wp-image-%d' % nid).replace(old_src, src)
    new = new.replace(block, nb)
    print(old_id, '->', nid, old_src.rsplit('/', 1)[1], '->', src.rsplit('/', 1)[1])
if new == c:
    print('nothing to change')
    sys.exit()
if mode != '--apply':
    print('dry run')
    sys.exit()
if not os.path.exists(RB):
    json.dump({'content': c}, open(RB, 'w', encoding='utf-8'), indent=1)
print('applied', 'OK' if save(new) and content() == new else 'MISMATCH')
