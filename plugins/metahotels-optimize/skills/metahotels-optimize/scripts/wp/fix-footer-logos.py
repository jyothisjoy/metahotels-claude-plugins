"""Point the footer logo widgets' mobile and sticky logo at the widget's own desktop logo.

Usage (from the site folder): python -I <skill>/scripts/wp/fix-footer-logos.py <logos.json> [--apply] [--revert]
<logos.json>: {"widgets": [[14447, "375d108"], ...], "missing": ["logo_old.webp", ...]}
  widgets: (template post, ova_logo widget id) pairs; missing: file names that answer 404 (sweep.js lists them).
The OVA logo widget (Ova themes, e.g. Khalidia's) prints three <img> tags (desktop, mobile, sticky) whether or not
they are shown. On Khalidia (2026-10-13) the mobile and sticky images in seven footer templates were deleted files, so every page
view requested them and got WordPress's 404 page (about 245 KB of HTML built in PHP, 60-80 KB on the wire), and
on the footers that show the widget on phones the visitor saw a broken image.
  default   read each template (MCP elementor-get-data), save rollback/footer-logo-<post>-<widget>-before.json and
            print what would change. Nothing is changed on the site.
  --apply   merge the new mobile_logo / sticky_logo into the widget (MCP elementor-update-element), then re-read.
  --revert  write the saved mobile_logo / sticky_logo back.
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sitecfg  # noqa: E402

SERVER = sitecfg.load()['mcp_server']
SPEC = json.load(open(next(a for a in sys.argv[1:] if not a.startswith('--')), encoding='utf-8'))
WIDGETS = [(int(p), w) for p, w in SPEC['widgets']]
MISSING = tuple(SPEC['missing'])
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


def find(els, wid):
    for e in els:
        if e['id'] == wid:
            return e
        r = find(e.get('elements') or [], wid)
        if r:
            return r


def widget(post, wid):
    tmp = os.path.join(rollback, 'footer-logo-%d-current.json' % post)
    d = call('mcp-adapter-elementor-get-data', json.dumps({'post_id': post}), tmp)
    os.remove(tmp)
    return find(d['elements'], wid)


def update(post, wid, settings, tag):
    payload = os.path.join(rollback, 'footer-logo-%d-%s-%s.json' % (post, wid, tag))
    json.dump({'post_id': post, 'element_id': wid, 'operation': 'merge', 'settings': settings}, open(payload, 'w', encoding='utf-8'), indent=1)
    res = call('mcp-adapter-elementor-update-element', payload, payload.replace('.json', '.result.json'))
    return bool(res.get('success'))


for post, wid in WIDGETS:
    before_file = os.path.join(rollback, 'footer-logo-%d-%s-before.json' % (post, wid))
    w = widget(post, wid)
    if not w or w.get('widgetType') != 'ova_logo':
        print(post, wid, 'widget not found, skipped')
        continue
    s = w['settings']
    if revert:
        old = json.load(open(before_file, encoding='utf-8'))
        ok = update(post, wid, {'mobile_logo': old['mobile_logo'], 'sticky_logo': old['sticky_logo']}, 'revert')
        now = widget(post, wid)['settings']
        print(post, wid, 'reverted' if ok and now['mobile_logo'] == old['mobile_logo'] and now['sticky_logo'] == old['sticky_logo'] else 'REVERT MISMATCH')
        continue
    desk = s.get('desk_logo') or {}
    todo = {k: dict(desk) for k in ('mobile_logo', 'sticky_logo') if any(m in ((s.get(k) or {}).get('url') or '') for m in MISSING)}
    if not todo:
        print(post, wid, 'nothing to change (already fixed)')
        continue
    if not desk.get('url') or any(m in desk['url'] for m in MISSING):
        print(post, wid, 'desktop logo unusable, skipped')
        continue
    if not os.path.exists(before_file):
        json.dump({k: s.get(k) for k in ('desk_logo', 'mobile_logo', 'sticky_logo')}, open(before_file, 'w', encoding='utf-8'), indent=1)
    print(post, wid, ', '.join('%s: %s -> %s' % (k, s[k]['url'].split('/')[-1], desk['url'].split('/')[-1]) for k in todo), end='')
    if not apply:
        print(' | dry run')
        continue
    ok = update(post, wid, todo, 'apply')
    now = widget(post, wid)['settings']
    good = ok and all(now[k].get('url') == desk['url'] for k in todo) and now.get('desk_logo') == desk
    print(' | applied', 'OK' if good else 'MISMATCH')
