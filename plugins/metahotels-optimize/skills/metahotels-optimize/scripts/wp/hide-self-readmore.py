"""Hide each hotel footer's "Read More" button on the page it links to (its own About page), where it is a link to
the page the visitor is already on. Elsewhere the button is unchanged.

Usage (from the site folder): python -I <skill>/scripts/wp/hide-self-readmore.py <items.json> [--apply] [--revert]
<items.json>: [{"footer": 27900, "element": "6790f00", "page_id": 28949,
                "url": "https://site/hotels/x/about-us/"}, ...]   (footer template, button widget, About page id, its URL)
Custom CSS on the button widget: body.page-id-<about page> selector{display:none}. The page id comes from the body
class of the saved About page (crawl.sh output). links.py lists these as "links to its own page".
Rollback: rollback/readmore-<footer>-<widget>-before.json.
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sitecfg  # noqa: E402

SERVER = sitecfg.load()['mcp_server']
# footer template, button widget, About page id, About page URL the button links to
ITEMS = [(int(x['footer']), x['element'], int(x['page_id']), x['url'])
         for x in json.load(open(next(a for a in sys.argv[1:] if not a.startswith('--')), encoding='utf-8'))]
_GEWAN_EXAMPLE = [  # not used: the shape of a real list (Gewan 2026-10-15)
    (27900, '6790f00', 28949, 'https://gewanhotels.com/hotels/gewan-resort-new-alamein/about-us/'),
    (29217, '6790f00', 29547, 'https://gewanhotels.com/hotels/gewan-palace-new-alamein/about-us/'),
    (26110, '6790f00', 26573, 'https://gewanhotels.com/hotels/gewan-hotel-cairo/about-us/'),
    (9892, '47dad07', 9995, 'https://gewanhotels.com/hotels/the-uptown-apartments-abu-dhabi/about-us/'),
    (10936, '9d7448c', 11081, 'https://gewanhotels.com/hotels/md-hotel-by-gewan/about-us/'),
    (9519, '33741bf', 9637, 'https://gewanhotels.com/hotels/royal-m-hotel-resort-al-aqah/about-us/'),
    (8134, 'fd3caa4', 1717, 'https://gewanhotels.com/hotels/royal-m-hotel-resort-abu-dhabi/about-us/'),
    (26755, '6790f00', 27557, 'https://gewanhotels.com/hotels/gewan-white-beach-resort-new-alamein/about-us/'),
]
rollback = os.path.abspath('rollback')
os.makedirs(rollback, exist_ok=True)
mcp = sitecfg.MCP_CALL


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


def settings(post, el):
    tmp = os.path.join(rollback, 'readmore-%d-current.json' % post)
    d = call('mcp-adapter-elementor-get-data', json.dumps({'post_id': post}), tmp)
    os.remove(tmp)
    return find(d.get('elements', d), el)['settings']


def update(post, el, css, tag):
    payload = os.path.join(rollback, 'readmore-%d-%s-%s.json' % (post, el, tag))
    json.dump({'post_id': post, 'element_id': el, 'operation': 'merge', 'settings': {'custom_css': css}},
              open(payload, 'w', encoding='utf-8'), indent=1)
    return bool(call('mcp-adapter-elementor-update-element', payload, payload.replace('.json', '.result.json')).get('success'))


for post, el, page, url in ITEMS:
    bf = os.path.join(rollback, 'readmore-%d-%s-before.json' % (post, el))
    s = settings(post, el)
    if '--revert' in sys.argv:
        old = json.load(open(bf, encoding='utf-8'))['custom_css']
        print(post, el, 'reverted' if update(post, el, old, 'revert') and settings(post, el).get('custom_css', '') == old else 'REVERT MISMATCH')
        continue
    link = (s.get('link') or {}).get('url', '')
    if link != url:
        print(post, el, 'links to %r, expected %s: skipped' % (link, url))
        continue
    css = s.get('custom_css', '') or ''
    rule = 'body.page-id-%d selector{display:none}' % page
    if rule in css:
        print(post, el, 'already set')
        continue
    if not os.path.exists(bf):
        json.dump({'custom_css': css}, open(bf, 'w', encoding='utf-8'), indent=1)
    new = (css.rstrip() + '\n' if css.strip() else '') + '/* hidden on the page it links to */\n' + rule
    if '--apply' in sys.argv:
        print(post, el, 'applied', 'OK' if update(post, el, new, 'apply') and settings(post, el).get('custom_css') == new else 'MISMATCH')
    else:
        print(post, el, 'dry run:', rule)
