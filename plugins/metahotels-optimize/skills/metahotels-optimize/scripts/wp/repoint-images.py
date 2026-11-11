"""Repoint Elementor image settings from the original attachments to the optimized ones.

usage: python -I repoint-images.py <mcp-server-name> <post-id> <elementor-before.json> <uploaded.json> [--apply] [--revert]

For every element of the saved tree whose settings reference an attachment listed in uploaded.json, builds the
changed top-level settings (whole value of each key, with id + url swapped) and, with --apply, sends them with
mcp-adapter-elementor-update-element (merge). Without --apply it only prints what would change.
--revert sends the original values from the saved tree instead (rollback).
The payloads are written next to uploaded.json as repoint-<post>-<element>.json.
"""
import copy
import json
import os
import subprocess
import sys

server, post_id, before_path, uploaded_path = sys.argv[1:5]
apply = '--apply' in sys.argv
revert = '--revert' in sys.argv
here = os.path.dirname(os.path.abspath(__file__))
outdir = os.path.dirname(os.path.abspath(uploaded_path))
newmap = {u['old_id']: u for u in json.load(open(uploaded_path, encoding='utf-8'))}
tree = json.load(open(before_path, encoding='utf-8'))


def swap(node, hits):
    """Replace {id, url} image objects in place; returns number of replacements."""
    n = 0
    if isinstance(node, dict):
        # Some attachment ids on this site are saved as numeric strings; keep the type that was there.
        oid = node.get('id')
        key = int(oid) if isinstance(oid, int) or (isinstance(oid, str) and oid.isdigit()) else None
        if key in newmap and isinstance(node.get('url'), str) and node['url'] == newmap[key]['old_url']:
            u = newmap[key]
            hits.append('%s -> %s' % (node['id'], u['new_id']))
            node['id'] = u['new_id'] if isinstance(oid, int) else str(u['new_id'])
            node['url'] = u['new_url']
            n += 1
        for v in node.values():
            n += swap(v, hits)
    elif isinstance(node, list):
        for v in node:
            n += swap(v, hits)
    return n


def walk(els, out):
    for el in els:
        s = el.get('settings')
        if isinstance(s, dict):
            changed = {}
            hits = []
            for k, v in s.items():
                nv = copy.deepcopy(v)
                if swap(nv, hits):
                    changed[k] = v if revert else nv
            if changed:
                out.append((el['id'], el.get('widgetType') or el.get('elType'), changed, hits))
        walk(el.get('elements') or [], out)


todo = []
walk(tree['elements'], todo)
total = 0
for el_id, kind, changed, hits in todo:
    total += len(hits)
    print(el_id.ljust(9), str(kind).ljust(16), ','.join(changed.keys()).ljust(46), ' '.join(hits))
    if not apply:
        continue
    payload = os.path.join(outdir, 'repoint-%s-%s%s.json' % (post_id, el_id, '-revert' if revert else ''))
    json.dump({'post_id': int(post_id), 'element_id': el_id, 'operation': 'merge', 'settings': changed}, open(payload, 'w', encoding='utf-8'), indent=1)
    res = payload.replace('.json', '.result.json')
    r = subprocess.run([sys.executable, '-I', os.path.join(here, 'mcp_call.py'), server, 'mcp-adapter-elementor-update-element', payload, res], capture_output=True, text=True)
    ok = json.load(open(res, encoding='utf-8')).get('success') if r.returncode == 0 and os.path.exists(res) else None
    print('   ->', 'success' if ok else 'FAILED ' + (r.stdout + r.stderr)[:300])
    if not ok:
        sys.exit(1)
print(len(todo), 'elements,', total, 'image references', '(applied)' if apply else '(dry run)')
