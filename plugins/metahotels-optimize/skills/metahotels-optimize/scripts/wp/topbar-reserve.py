"""Reserve the settled size of the Mirai wrappers in each header's sticky top bar and menu row (desktop only).

Usage (from the site folder): python -I <skill>/scripts/wp/topbar-reserve.py <sizes.json> [--apply] [--revert] [--only=<post>]
<sizes.json>: {"media": "(min-width:1025px)", "measured": "2026-10-14, checks/finder-size.js",
               "items": [{"post": 8121, "element": "a0526e1", "css": "min-width:755px;min-height:54px"}, ...]}
Measure each wrapper's settled size per breakpoint first (checks/finder-size.js, checks/topbar-size.js).
Owner's standing decision (2026-10-14): reserving the space on our own wrapper widget needs no approval.
Example from Gewan (2026-10-14):
Until the booking engine renders (after the load event) the finder and the session / My booking links are 0x0,
so the top bar grows from 40 to 74 px, the page moves down 34 px and the heading next to the finder jumps
sideways: desktop layout shift 0.22-0.25. This appends a block to the custom CSS of each wrapper HTML widget
(our own widget, not the booking engine) that gives it its settled size from the start. Hotel finders grow with
the screen width (755-982 px), so they get min-width = the smallest settled width; the result after Mirai has
rendered is unchanged at every width (settled before = settled after). The top bar is hidden below 1025 px there,
so every rule was inside @media (min-width:1025px); set "media" to the breakpoints where the bar is shown.
  default   print what would change; save rollback/topbar-<post>-<element>-before.json (the current custom CSS).
  --apply   merge the new custom CSS (MCP elementor-update-element) and read it back.
  --revert  write the saved custom CSS back.
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sitecfg  # noqa: E402

SERVER = sitecfg.load()['mcp_server']
MARK = '/* Reserved size until the booking engine renders */'
SPEC = json.load(open(sys.argv[1], encoding='utf-8'))
MEDIA = SPEC.get('media', '(min-width:768px)')
MEASURED = SPEC.get('measured', '')
SIZES = {}
for it in SPEC['items']:
    SIZES.setdefault(int(it['post']), []).append((it['element'], it['css']))
_GEWAN_EXAMPLE = {
    8110: [('67fd580', 'width:750px;min-height:54px'), ('c95085a', 'min-width:72px;min-height:20px'), ('5742fd5', 'width:87px;min-height:24px')],
    8121: [('a0526e1', 'min-width:755px;min-height:54px'), ('7a3a894', 'min-width:173px;min-height:20px')],
    9514: [('b9b005e', 'min-width:755px;min-height:54px'), ('bbf6312', 'min-width:173px;min-height:20px')],
    9081: [('429f474', 'min-width:755px;min-height:54px'), ('b2d9d9c', 'min-width:173px;min-height:20px')],
    10929: [('66a73d6', 'min-width:749px;min-height:54px'), ('49b015e', 'min-width:173px;min-height:20px')],
    9888: [('bf790f1', 'min-width:755px;min-height:54px'), ('83b4737', 'min-width:173px;min-height:20px')],
    9963: [('c85c815', 'min-width:755px;min-height:54px'), ('86f3ddd', 'min-width:173px;min-height:20px')],
    26105: [('ca11471', 'min-width:747px;min-height:54px'), ('d77836e', 'min-width:173px;min-height:20px')],
    29214: [('bdefec3', 'min-width:755px;min-height:54px'), ('cd4ea69', 'min-width:173px;min-height:20px')],
    27899: [('5985faf', 'min-width:755px;min-height:54px'), ('2cdb993', 'min-width:173px;min-height:20px')],
    26753: [('e45bb2c', 'min-width:755px;min-height:54px'), ('b91b011', 'min-width:173px;min-height:20px')],
}  # not used: the shape of a real sizes list (Gewan 2026-10-14)
rollback = os.path.abspath('rollback')
os.makedirs(rollback, exist_ok=True)
mcp = sitecfg.MCP_CALL
apply = '--apply' in sys.argv
revert = '--revert' in sys.argv
only = next((int(a.split('=')[1]) for a in sys.argv if a.startswith('--only=')), None)


def call(tool, args, out):
    r = subprocess.run([sys.executable, '-I', mcp, SERVER, tool, args, out], capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(out):
        print('MCP call failed:', (r.stdout + r.stderr)[:300])
        sys.exit(1)
    return json.load(open(out, encoding='utf-8'))


def find(elements, el):
    for e in elements:
        if e['id'] == el:
            return e
        r = find(e.get('elements', []), el)
        if r:
            return r


def widget(post, el):
    tmp = os.path.join(rollback, 'topbar-%d-current.json' % post)
    d = call('mcp-adapter-elementor-get-data', json.dumps({'post_id': post}), tmp)
    os.remove(tmp)
    return find(d['elements'], el)


def block(decl):
    return '\n'.join([
        MARK,
        '/* Settled size of the Mirai component in this widget, so the top bar does not grow and nothing moves when',
        '   the booking engine renders. Measured %s; measure again if the' % (MEASURED or 'before saving'),
        '   finder or the link texts change. */',
        '@media %s{ selector{%s} }' % (MEDIA, decl),
        '',
    ])


def update(post, el, css, tag):
    payload = os.path.join(rollback, 'topbar-%d-%s-%s.json' % (post, el, tag))
    json.dump({'post_id': post, 'element_id': el, 'operation': 'merge', 'settings': {'custom_css': css}}, open(payload, 'w', encoding='utf-8'), indent=1)
    return bool(call('mcp-adapter-elementor-update-element', payload, payload.replace('.json', '.result.json')).get('success'))


for post, items in SIZES.items():
    if only and post != only:
        continue
    for el, decl in items:
        before_file = os.path.join(rollback, 'topbar-%d-%s-before.json' % (post, el))
        w = widget(post, el)
        if not w or w.get('widgetType') != 'html' or 'data-mirai-component' not in (w['settings'].get('html') or ''):
            print(post, el, 'not the expected Mirai HTML widget, skipped')
            continue
        css = w['settings'].get('custom_css') or ''
        if revert:
            old = json.load(open(before_file, encoding='utf-8'))['custom_css']
            ok = update(post, el, old, 'revert')
            print(post, el, 'reverted' if ok and (widget(post, el)['settings'].get('custom_css') or '') == old else 'REVERT MISMATCH')
            continue
        if MARK in css:
            print(post, el, 'already reserved, skipped')
            continue
        if not os.path.exists(before_file):
            json.dump({'custom_css': css}, open(before_file, 'w', encoding='utf-8'), indent=1)
        new = (css.rstrip('\n').replace('\r\n', '\n') + '\n' if css else '') + block(decl)
        if '\r\n' in css:
            new = new.replace('\n', '\r\n')
        print(post, el, decl, '| css', len(css), '->', len(new), end='')
        if not apply:
            print(' | dry run')
            continue
        ok = update(post, el, new, 'apply')
        print(' | applied', 'OK' if ok and (widget(post, el)['settings'].get('custom_css') or '') == new else 'MISMATCH')
