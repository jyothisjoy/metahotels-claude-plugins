"""Entrance animations in the first top-level element of each crawled page, with their per-device settings.

usage: python -I entrance.py <pages-dir>
The first top-level element of the page document (wp-page, wp-post, single-page, single-post) is what is above the
fold. Every element in it that Elementor hides until its script runs (.elementor-invisible) is listed with the
animation it uses on desktop, tablet and mobile, the delay and the speed class.
"""
import collections
import html as htmlmod
import io
import json
import os
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
d = sys.argv[1]
rows = [l.rstrip('\n').split('\t') for l in open(os.path.join(d, 'index.tsv'), encoding='utf-8') if l.strip()]
tok = re.compile(r'<(/?)(div|section)\b([^>]*)>', re.S)
combos = collections.defaultdict(list)
pages_with = 0
for r in rows:
    n, status, url = r[0], r[1], r[-1]
    p = os.path.join(d, n + '.html')
    if status != '200' or not os.path.exists(p):
        continue
    doc = open(p, encoding='utf-8', errors='replace', newline='').read()
    m = re.search(r'<div[^>]*data-elementor-type="(wp-page|wp-post|single-page|single-post|single)"[^>]*>', doc)
    if not m:
        continue
    depth = 0
    first_end = None
    found = []
    for t in tok.finditer(doc, m.end()):
        if t.group(1):
            depth -= 1
            if depth == 0:
                first_end = t.end()
                break
            if depth < 0:
                break
            continue
        depth += 1
        attrs = t.group(3)
        if 'elementor-invisible' in attrs:
            s = re.search(r'data-settings="([^"]*)"', attrs)
            st = json.loads(htmlmod.unescape(s.group(1))) if s else {}
            a = {k: v for k, v in st.items() if 'animation' in k}
            speed = 'slow' if 'animated-slow' in attrs else 'fast' if 'animated-fast' in attrs else 'normal'
            did = re.search(r'data-id="([^"]+)"', attrs)
            wt = re.search(r'data-widget_type="([^"]+)"', attrs) or re.search(r'data-element_type="([^"]+)"', attrs)
            found.append((did.group(1) if did else '?', wt.group(1) if wt else '?', speed, json.dumps(a, sort_keys=True)))
    if found:
        pages_with += 1
        for f in found:
            combos[(f[2], f[3], f[1])].append(re.sub(r'^https?://[^/]+', '', url) + '#' + f[0])
print('pages with hidden-until-script elements in the first section:', pages_with)
for (speed, a, wt), where in sorted(combos.items(), key=lambda x: -len(x[1])):
    print('%3d  %-7s %-40s %s' % (len(where), speed, wt, a))
    print('       e.g. ' + ', '.join(where[:3])[:200])
