"""List every link value in the saved Elementor trees: per document and widget, the setting path and the URL.

Usage: python -I link-scan.py <elementor-dir> [regex]
Without a regex it prints buttons whose link is empty or "#". With one, every link value or href matching it.
For each widget it also prints the nearest heading before it in the same document, to tell sections apart.
"""
import glob
import json
import os
import re
import sys

d = sys.argv[1]
rx = re.compile(sys.argv[2]) if len(sys.argv) > 2 else None


def strings(v, path):
    if isinstance(v, dict):
        for k, x in v.items():
            yield from strings(x, path + [k])
    elif isinstance(v, list):
        for i, x in enumerate(v):
            yield from strings(x, path + [i])
    elif isinstance(v, str):
        yield path, v


for f in sorted(glob.glob(os.path.join(d, 'elementor-*-before.json'))):
    doc = re.search(r'elementor-(\d+)-', f).group(1)
    data = json.load(open(f, encoding='utf-8'))
    els = data.get('elements', data) if isinstance(data, dict) else data
    last = ['']

    def walk(es):
        for e in es:
            s = e.get('settings', {}) or {}
            if e.get('elType') == 'widget':
                wt = e.get('widgetType')
                if wt in ('heading', 'theme-post-title') and isinstance(s.get('title'), str):
                    last[0] = re.sub(r'<[^>]+>', '', s['title'])[:40]
                if rx is None:
                    if wt == 'button':
                        u = (s.get('link') or {}).get('url', '') if isinstance(s.get('link'), dict) else ''
                        dyn = (s.get('__dynamic__') or {}).get('link')
                        if u.strip() in ('', '#') and not dyn:
                            print('%-6s %s %-12s link=%r text=%r | after heading %r' % (doc, e['id'], wt, u, s.get('text'), last[0]))
                else:
                    for p, v in strings(s, []):
                        if p and p[-1] == 'url' and rx.search(v):
                            print('%-6s %s %-14s %s = %s | %r' % (doc, e['id'], wt, '.'.join(map(str, p)), v, last[0]))
                        elif isinstance(v, str) and 'href=' in v:
                            for h in re.findall(r'href="([^"]*)"', v):
                                if rx.search(h):
                                    print('%-6s %s %-14s %s href %s | %r' % (doc, e['id'], wt, '.'.join(map(str, p)), h, last[0]))
            walk(e.get('elements', []))
    walk(els)
