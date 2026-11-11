"""Remove slides whose image attachment was deleted (Gewan owner, 2026-10-14: "remove the slides").

Usage (from the site folder): python -I <skill>/scripts/wp/remove-dead-slides.py <dead.json> [--apply] [--revert]
<dead.json>: [{"post": 9524, "element": "da7532e", "ids": [28549]}, ...] (check-images.py lists the candidates).
For each element, finds the list setting (background slideshow gallery, carousel or gallery) that holds the
attachment ids, confirms each id is gone from the media library (REST 404) and that its file URL is a 404, then
writes the list without them. Rollback: rollback/slides-<post>-<element>-before.json (the whole setting).
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sitecfg  # noqa: E402

SERVER = sitecfg.load()['mcp_server']
DEAD = {(int(d['post']), d['element']): [int(i) for i in d['ids']]
        for d in json.load(open(sys.argv[1], encoding='utf-8'))}
rollback = os.path.abspath('rollback')
os.makedirs(rollback, exist_ok=True)
mcp = sitecfg.MCP_CALL
apply = '--apply' in sys.argv
revert = '--revert' in sys.argv


def call(tool, args, out):
    r = subprocess.run([sys.executable, '-I', mcp, SERVER, tool, args, out], capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(out):
        print('MCP call failed:', (r.stdout + r.stderr)[:300])
        sys.exit(1)
    return json.load(open(out, encoding='utf-8'))


def media_status(mid):
    env = dict(os.environ, MSYS_NO_PATHCONV='1')
    r = subprocess.run([sys.executable, '-I', sitecfg.WP, SERVER, 'GET', '/wp-json/wp/v2/media/%d' % mid], capture_output=True, text=True, env=env)
    return 'gone' if ('rest_post_invalid_id' in r.stdout or '"status": 404' in r.stdout or '"status":404' in r.stdout) else 'EXISTS?'


def url_status(u):
    r = subprocess.run(['curl', '-s', '-o', os.devnull, '--retry', '2', '-w', '%{http_code}', u], capture_output=True, text=True)
    return r.stdout


def find(elements, el):
    for e in elements:
        if e['id'] == el:
            return e
        r = find(e.get('elements', []), el)
        if r:
            return r


def element(post, el):
    tmp = os.path.join(rollback, 'slides-%d-current.json' % post)
    d = call('mcp-adapter-elementor-get-data', json.dumps({'post_id': post}), tmp)
    os.remove(tmp)
    return find(d.get('elements', []), el)


def img(x):
    """Gallery items are {id, url}; media-carousel slides keep the attachment in x['image']."""
    return x if 'url' in x else (x.get('image') or {})


def list_key(settings, ids):
    for k, v in settings.items():
        if isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
            if any(str(img(x).get('id')) in [str(i) for i in ids] for x in v):
                return k


def update(post, el, key, value, tag):
    payload = os.path.join(rollback, 'slides-%d-%s-%s.json' % (post, el, tag))
    json.dump({'post_id': post, 'element_id': el, 'operation': 'merge', 'settings': {key: value}}, open(payload, 'w', encoding='utf-8'), indent=1)
    return bool(call('mcp-adapter-elementor-update-element', payload, payload.replace('.json', '.result.json')).get('success'))


for (post, el), ids in DEAD.items():
    before_file = os.path.join(rollback, 'slides-%d-%s-before.json' % (post, el))
    e = element(post, el)
    if not e:
        print(post, el, 'element not found, skipped')
        continue
    s = e.get('settings', {})
    if revert:
        b = json.load(open(before_file, encoding='utf-8'))
        ok = update(post, el, b['key'], b['value'], 'revert')
        print(post, el, 'reverted' if ok and element(post, el)['settings'].get(b['key']) == b['value'] else 'REVERT MISMATCH')
        continue
    key = list_key(s, ids)
    if not key:
        print(post, el, 'no list holds', ids, '- skipped')
        continue
    items = s[key]
    dead = [x for x in items if str(img(x).get('id')) in [str(i) for i in ids]]
    checks = ['%s media %s file %s' % (img(x).get('id'), media_status(int(img(x).get('id'))), url_status(img(x).get('url', ''))) for x in dead]
    print(post, el, e.get('elType'), e.get('widgetType', ''), key, len(items), '->', len(items) - len(dead), '|', '; '.join(checks), end='')
    if any('EXISTS' in c or not c.endswith('404') for c in checks):
        print(' | image still there, skipped')
        continue
    if not os.path.exists(before_file):
        json.dump({'key': key, 'value': items}, open(before_file, 'w', encoding='utf-8'), indent=1)
    new = [x for x in items if x not in dead]
    if not apply:
        print(' | dry run')
        continue
    ok = update(post, el, key, new, 'apply')
    print(' | applied', 'OK' if ok and element(post, el)['settings'].get(key) == new else 'MISMATCH')
