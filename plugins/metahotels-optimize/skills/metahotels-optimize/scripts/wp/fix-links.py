"""Point internal links straight at their final page (owner, Gewan 2026-10-15: "find the redirects and apply it
directly"; a standing default since), and fix the links whose redirect lands on the wrong page.

Usage (from the site folder): python -I <skill>/scripts/wp/fix-links.py <rules.json> [--apply] [--revert]
<rules.json> (paths are site-relative; see references/links-and-ctas.md for how to build it from links.py output):
  {"rules":   [["/old-path/(.*)", "/new-path/\\1"], ...],          regex on the path, with or without the host
   "extra":   [{"post": 29223, "element": "94cd692", "url": "/hotels/x/dining/"}],   set one widget's link
   "remove":  [{"post": 29217, "element": "cf7406d", "paths": ["/room/superior-room/"]}],  drop icon-list items
   "nolink":  [{"post": 24125, "element": "c6dfa15", "type": "date"}]}       post-info item: link off
Open every redirect's final page before writing a rule: on Gewan four landed on another hotel's page.
Scans every saved Elementor tree in audit/elementor/ for link values (`url` fields and href="..." inside HTML) that
match the rules, re-reads each matching document live, rewrites the matching values and saves each changed element with
mcp-adapter-elementor-update-element (operation merge, only the changed top-level settings). Also: EXTRA (targeted
link changes), REMOVE (icon-list items to drop) and NOLINK (post-info items whose link is switched off).
Every target URL is checked to answer 200 before anything is written.
Rollback: rollback/links-<post>-<element>-before.json (the element's changed settings as they were).
"""
import glob
import json
import os
import re
import subprocess
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sitecfg  # noqa: E402

CFG = sitecfg.load()
SERVER = CFG['mcp_server']
HOST = CFG['origin']
root = os.getcwd()
rollback = os.path.join(root, 'rollback')
os.makedirs(rollback, exist_ok=True)
mcp = sitecfg.MCP_CALL
SPEC = json.load(open(next(a for a in sys.argv[1:] if not a.startswith('--')), encoding='utf-8'))
apply = '--apply' in sys.argv
revert = '--revert' in sys.argv

# (regex on the path, replacement). Paths are matched with or without the host; the result is always absolute.
RULES = [tuple(r) for r in SPEC.get('rules', [])]
_GEWAN_EXAMPLE_RULES = [  # not used: the shape of a real rule list (Gewan 2026-10-15)
    (r'/hotels/gewan-palace-resort-new-alamein/(.*)', r'/hotels/gewan-palace-new-alamein/\1'),
    (r'/hotels/royal-m-hotel-resort-fujairah/(.*)', r'/hotels/royal-m-hotel-fujairah/\1'),  # dining/ exists: the menu uses it
    (r'/royal-m-hotel-resort-abu-dhabi/amenities/?', r'/hotels/royal-m-hotel-resort-abu-dhabi/amenities/'),
    (r'/royal-m-hotel-resort-abu-dhabi/(.*)', r'/hotels/royal-m-hotel-resort-abu-dhabi/\1'),
    (r'/hotels/coming-soon/', r'/coming-soon/'),
    (r'/hotels/contact/', r'/contact/'),  # the group footer: the header's "Contact" goes to the group page too
    (r'/hotels/gewan-hotel-cairo/dining/?', r'/hotels/gewan-hotel-cairo/dining-2/'),
    (r'/room/deluxe-rooms-lake-sea-view/', r'/room/deluxe-room-lake-view/'),
    (r'/room/royal-villa-five-bedroom-with-sea-view/', r'/room/royal-villa/'),
    (r'/room/suite-room-2/', r'/room/one-bedroom-suite/'),
    (r'/careers', r'/careers/'),
    (r'/facilities', r'/facilities/'),
]
RULES = [(re.compile(r'^(?:%s)?%s$' % (re.escape(HOST), a)), b) for a, b in RULES]
# (post, element): new link url, for links that are empty or point at another hotel's page
EXTRA = {(int(x['post']), x['element']): x['url'] for x in SPEC.get('extra', [])}
# icon-list items to drop, e.g. footer rooms the hotel does not have (their old URLs redirect to another hotel)
REMOVE = {(int(x['post']), x['element']): x['paths'] for x in SPEC.get('remove', [])}
# post-info items whose link is switched off, e.g. a date linking to a day archive that redirects to the homepage
NOLINK = {(int(x['post']), x['element']): x.get('type', 'date') for x in SPEC.get('nolink', [])}

checked = {}


def status(url):
    if url not in checked:
        req = urllib.request.Request(url, method='HEAD', headers={'User-Agent': 'Mozilla/5.0 perf-audit'})

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None
        try:
            checked[url] = urllib.request.build_opener(NoRedirect).open(req, timeout=60).status
        except urllib.error.HTTPError as e:
            checked[url] = e.code
        except Exception as e:  # noqa: BLE001
            checked[url] = str(e)[:40]
    return checked[url]


def new_url(u):
    for rx, rep in RULES:
        m = rx.match(u.strip())
        if m:
            return HOST + m.expand(rep)


def rewrite(v):
    """Return (new value, [(old, new)]) for one settings value."""
    changes = []
    if isinstance(v, dict):
        out = {}
        for k, x in v.items():
            # Elementor link objects keep the target in `url`; theme widgets often use plain text fields instead
            # (EliteStay footer lists: `btn_url`, jacobshotels 2026-10-29).
            if (k == 'url' or k.endswith('_url') or k.endswith('_link')) and isinstance(x, str) and new_url(x):
                out[k] = new_url(x)
                changes.append((x, out[k]))
            else:
                out[k], c = rewrite(x)
                changes += c
        return out, changes
    if isinstance(v, list):
        out = []
        for x in v:
            y, c = rewrite(x)
            out.append(y)
            changes += c
        return out, changes
    if isinstance(v, str) and 'href=' in v:
        def sub(m):
            n = new_url(m.group(2))
            if n:
                changes.append((m.group(2), n))
                return m.group(1) + n + m.group(3)
            return m.group(0)
        return re.sub(r'(href=")([^"]*)(")', sub, v), changes
    return v, changes


def call(tool, args, out):
    r = subprocess.run([sys.executable, '-I', mcp, SERVER, tool, args, out], capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(out):
        print('MCP call failed:', (r.stdout + r.stderr)[:300])
        sys.exit(1)
    return json.load(open(out, encoding='utf-8'))


def tree(post):
    tmp = os.path.join(rollback, 'links-%d-current.json' % post)
    d = call('mcp-adapter-elementor-get-data', json.dumps({'post_id': post}), tmp)
    os.remove(tmp)
    return d.get('elements', d)


def walk(es):
    for e in es:
        yield e
        yield from walk(e.get('elements', []))


def update(post, el, settings, tag):
    payload = os.path.join(rollback, 'links-%d-%s-%s.json' % (post, el, tag))
    json.dump({'post_id': post, 'element_id': el, 'operation': 'merge', 'settings': settings},
              open(payload, 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
    return bool(call('mcp-adapter-elementor-update-element', payload, payload.replace('.json', '.result.json')).get('success'))


def plan(post, els):
    """[(element, {key: new value}, {key: old value}, [descriptions])] for one document."""
    out = []
    for e in walk(els):
        s = e.get('settings') or {}
        if not isinstance(s, dict):
            continue
        new, old, desc = {}, {}, []
        for k, v in s.items():
            if k == '__dynamic__':
                continue
            nv, c = rewrite({k: v})
            nv = nv[k]
            if c:
                new[k], old[k] = nv, v
                desc += ['%s: %s -> %s' % (k, a, b) for a, b in c]
        key = (post, e['id'])
        if key in EXTRA:
            # Jeg Kit buttons keep their link in sg_content_link; core widgets in link. An absolute URL (booking
            # engine, another host) is used as given; a site path gets the host (fixed 2026-10-23, Wescott).
            lk = 'sg_content_link' if isinstance(s.get('sg_content_link'), dict) and not isinstance(s.get('link'), dict) else 'link'
            target = EXTRA[key] if re.match(r'^[a-z][a-z0-9+.-]*:', EXTRA[key], re.I) else HOST + EXTRA[key]
            link = dict(s.get(lk) or {}, url=target)
            old[lk], new[lk] = s.get(lk), link
            desc.append('%s: %r -> %s' % (lk, (s.get(lk) or {}).get('url'), link['url']))
        if key in REMOVE:
            items = new.get('icon_list', s.get('icon_list', []))  # on top of the URL rewrite above, not instead of it
            keep = [i for i in items if not any((i.get('link') or {}).get('url', '').endswith(p) for p in REMOVE[key])]
            if len(keep) != len(items):
                old['icon_list'], new['icon_list'] = items, keep
                desc.append('icon_list: removed %d item(s) %s' % (len(items) - len(keep), REMOVE[key]))
        if key in NOLINK:
            items = s.get('icon_list', [])
            # "type" and "link" are absent when they hold their defaults ("date", "yes")
            ch = [dict(i, link='') if i.get('type', 'date') == NOLINK[key] and i.get('link', 'yes') != '' else i for i in items]
            if ch != items:
                old['icon_list'], new['icon_list'] = items, ch
                desc.append('icon_list: link switched off on the %s item' % NOLINK[key])
        if new:
            out.append((e, new, old, desc))
    return out


saved = sorted(int(re.search(r'elementor-(\d+)-', f).group(1)) for f in glob.glob(os.path.join(root, 'audit', 'elementor', 'elementor-*-before.json')))
if revert:
    for f in sorted(glob.glob(os.path.join(rollback, 'links-*-before.json'))):
        post, el = re.search(r'links-(\d+)-(\w+)-before', f).groups()
        old = json.load(open(f, encoding='utf-8'))
        print(post, el, 'reverted' if update(int(post), el, old, 'revert') else 'REVERT FAILED')
    sys.exit()

todo = []
for post in saved:
    data = json.load(open(os.path.join(root, 'audit', 'elementor', 'elementor-%d-before.json' % post), encoding='utf-8'))
    if plan(post, data.get('elements', data) if isinstance(data, dict) else data):
        todo.append(post)
print('documents with changes (from the saved trees):', len(todo), todo)

bad = 0
for post in todo:
    for e, new, old, desc in plan(post, tree(post)):
        targets = set(re.findall(re.escape(HOST) + r'/[^\s\'"]*', ' '.join(d.split(' -> ', 1)[-1] for d in desc)))
        st = {t: status(t) for t in targets}
        ok = all(x == 200 for x in st.values())
        bad += not ok
        print('%-6d %s %-16s %s' % (post, e['id'], e.get('widgetType', e.get('elType')), '' if ok else 'TARGET NOT 200 %s' % st))
        for d in desc:
            print('        ' + d)
        if not apply or not ok:
            continue
        bf = os.path.join(rollback, 'links-%d-%s-before.json' % (post, e['id']))
        if not os.path.exists(bf):
            json.dump(old, open(bf, 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
        res = update(post, e['id'], new, 'apply')
        now = next(x for x in walk(tree(post)) if x['id'] == e['id'])['settings']
        print('        applied', 'OK' if res and all(now.get(k) == v for k, v in new.items()) else 'MISMATCH')
print('elements with a target that is not 200:', bad)
