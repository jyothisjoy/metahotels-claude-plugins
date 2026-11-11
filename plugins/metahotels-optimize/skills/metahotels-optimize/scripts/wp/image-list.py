"""List the images referenced by saved Elementor trees with their file size, to choose what to re-encode.

Usage (from the site folder): python -I <skill>/scripts/wp/image-list.py <out.json> <elementor-A.json> [<elementor-B.json> ...] [--min-kb=80]
For every image URL on this site referenced in the element settings: attachment id, bytes, which posts/elements
use it and under which setting. Writes the ones at or above --min-kb to <out.json> in the format
optimize-images.py reads ([{id, url, max, fmt, alt, title, uses}]), and prints all of them, largest first.
Format (playbook step 2b): AVIF when every use is a background or slideshow (full URL, no sub-sizes needed),
WebP when any use is an image widget, gallery or carousel (WordPress builds the crop sizes from WebP; these hosts
cannot write AVIF sub-sizes).
Alt text and title are read from the original attachment (public REST) so the new one carries them.
"""
import concurrent.futures
import glob
import html
import json
import os
import re
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sitecfg  # noqa: E402

CFG = sitecfg.load()
HOST = CFG['host'] + '/wp-content/uploads/'
args = [a for a in sys.argv[1:] if not a.startswith('--')]
min_kb = next((int(a.split('=')[1]) for a in sys.argv if a.startswith('--min-kb=')), 80)
out = args[0]
files = [f for a in args[1:] for f in (glob.glob(a) or [a])]
refs = {}


def walk(post, el, node, path):
    if isinstance(node, dict):
        url = node.get('url')
        if isinstance(url, str) and re.search(r'\.(webp|jpe?g|png|avif)(\?|$)', url, re.I) and HOST in url:
            r = refs.setdefault(url, {'id': node.get('id'), 'url': url, 'uses': []})
            r['uses'].append('%s:%s:%s:%s' % (post, el['id'], el.get('widgetType') or el.get('elType'), '.'.join(str(p) for p in path)))
        for k, v in node.items():
            walk(post, el, v, path + [k])
    elif isinstance(node, list):
        for i, v in enumerate(node):
            walk(post, el, v, path + [i])


def elements(post, els):
    for el in els:
        walk(post, el, el.get('settings') or {}, [])
        elements(post, el.get('elements') or [])


def get(url, method='GET'):
    req = urllib.request.Request(url, method=method, headers={'User-Agent': 'Mozilla/5.0 perf-audit'})
    return urllib.request.urlopen(req, timeout=60)


for f in files:
    d = json.load(open(f, encoding='utf-8'))
    els = d.get('elements')
    if isinstance(els, str):
        els = json.loads(els)
    elements(re.search(r'elementor-(\d+)-', os.path.basename(f)).group(1), els or [])

def size(r):
    try:
        with get(r['url'], 'HEAD') as h:
            r['bytes'] = int(h.headers.get('content-length') or 0)
        if not r['bytes']:
            # Behind the CDN a cached file's HEAD can come without content-length: fetch it once.
            with get(r['url']) as h:
                r['bytes'] = len(h.read())
    except Exception as e:  # noqa: BLE001
        r['bytes'] = -1
        r['error'] = str(e)[:60]


print('%d distinct image URLs in %d documents' % (len(refs), len(files)), flush=True)
with concurrent.futures.ThreadPoolExecutor(6) as ex:
    list(ex.map(size, refs.values()))


def is_bg(use):
    key = use.split(':', 3)[3]
    return 'background' in key


rows = sorted(refs.values(), key=lambda r: -r['bytes'])
total = sum(r['bytes'] for r in rows if r['bytes'] > 0)
print('%d images, %.0f KB in total; %d at or above %d KB; %d missing' % (len(rows), total / 1024, sum(1 for r in rows if r['bytes'] >= min_kb * 1024), min_kb, sum(1 for r in rows if r['bytes'] < 0)))
big = []
for r in rows:
    bg = all(is_bg(u) for u in r['uses'])
    keys = sorted({u.split(':', 3)[3].split('.')[0] for u in r['uses']})
    posts = sorted({u.split(':')[0] for u in r['uses']})
    print('%6.0f KB  id=%-6s %-4s %-58s posts=%s keys=%s' % (r['bytes'] / 1024, r['id'], 'bg' if bg else 'img', r['url'].rsplit('/', 1)[1][-58:], ','.join(posts[:8]) + ('…%d' % len(posts) if len(posts) > 8 else ''), ','.join(keys)))
    if r['bytes'] < min_kb * 1024 or not str(r['id'] or '').isdigit():
        continue
    big.append({'id': int(r['id']), 'url': r['url'], 'max': 1920 if bg else 1600, 'fmt': 'avif' if bg else 'webp', 'bytes': r['bytes'], 'uses': r['uses']})
ids = sorted({i['id'] for i in big})
media = {}
for n in range(0, len(ids), 100):
    q = ','.join(str(i) for i in ids[n:n + 100])
    with get(CFG['origin'] + '/wp-json/wp/v2/media?per_page=100&include=%s&_fields=id,alt_text,title,source_url' % q) as h:
        media.update({m['id']: m for m in json.loads(h.read().decode())})
for item in big:
    m = media.get(item['id'])
    if not m:
        item['media_error'] = 'no attachment'
        continue
    item['alt'] = m.get('alt_text') or ''
    item['title'] = html.unescape((m.get('title') or {}).get('rendered') or '')
    item['source_url'] = m.get('source_url')
os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
json.dump(big, open(out, 'w', encoding='utf-8'), indent=1)
print('wrote', out, len(big), '| total %.0f KB' % (sum(i['bytes'] for i in big) / 1024))
