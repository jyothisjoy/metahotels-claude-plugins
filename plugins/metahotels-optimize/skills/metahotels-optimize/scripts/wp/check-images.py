"""After the image re-encode (playbook step 2b): every uploaded image a saved page uses, in the HTML and in the
Elementor post CSS files it links, must answer 200 with an image type; and no page should still use an original
that has a re-encode.

Usage (from the site folder): python -I <skill>/scripts/wp/check-images.py <pages-dir> [uploaded.json ...]
Prints: distinct image URLs, how many are re-encodes (-opt), failures, and originals still referenced (with pages).
"""
import concurrent.futures
import glob
import json
import os
import re
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sitecfg  # noqa: E402

HOSTRX = re.escape(sitecfg.load()['host'])
pages = sys.argv[1]
uploaded = sys.argv[2:] or glob.glob('images/uploaded*.json')
olds = {}
for f in uploaded:
    for u in json.load(open(f, encoding='utf-8')):
        olds[u['old_url'].rsplit('/', 1)[1].rsplit('.', 1)[0]] = u['old_url']
IMG = re.compile(r'https:(?:\\?/){2}' + HOSTRX + r'(?:\\?/)wp-content(?:\\?/)uploads(?:\\?/)[^"\'\s)>]+?\.(?:webp|jpe?g|png|avif|gif)(?![\w.\-/])', re.I)  # lookahead: 'x.jpg-scaled.jpg' is one file
UA = {'User-Agent': 'Mozilla/5.0 perf-audit'}
index = {}
p = os.path.join(pages, 'index.tsv')
if os.path.exists(p):
    for line in open(p, encoding='utf-8'):
        c = line.rstrip('\n').split('\t')
        if len(c) >= 6:
            index[c[0].zfill(3)] = c[5]
urls = {}
css = {}
for f in sorted(glob.glob(os.path.join(pages, '*.html'))):
    n = os.path.basename(f)[:-5]
    h = open(f, encoding='utf-8', errors='replace').read()
    for u in IMG.findall(h):
        urls.setdefault(u.replace('\\/', '/'), set()).add(n)
    for c in re.findall(r'href=["\'](https://' + HOSTRX + r'/wp-content/uploads/elementor/css/post-\d+\.css)[^"\']*', h):
        css.setdefault(c, set()).add(n)


def fetch(u):
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60) as r:
            return r.status, r.headers.get('content-type', ''), r.read()
    except urllib.error.HTTPError as e:
        return e.code, '', b''
    except Exception as e:  # noqa: BLE001
        return 0, str(e)[:40], b''


with concurrent.futures.ThreadPoolExecutor(6) as ex:
    for c, (st, ct, body) in zip(css, ex.map(fetch, css)):
        for u in IMG.findall(body.decode('utf-8', 'replace')):
            urls.setdefault(u.replace('\\/', '/'), set()).update(css[c])


def head(u):
    try:
        with urllib.request.urlopen(urllib.request.Request(u, method='HEAD', headers=UA), timeout=60) as r:
            return r.status, r.headers.get('content-type', '')
    except urllib.error.HTTPError as e:
        return e.code, ''
    except Exception as e:  # noqa: BLE001
        return 0, str(e)[:40]


with concurrent.futures.ThreadPoolExecutor(6) as ex:
    res = dict(zip(urls, ex.map(head, urls)))
opt = [u for u in urls if '-opt' in u.rsplit('/', 1)[1]]
bad_opt = [u for u in opt if res[u][0] != 200 or not res[u][1].startswith('image/')]
print('%d image URLs from %d pages and %d post CSS files; %d re-encodes, %d of them failing' % (len(urls), len(glob.glob(os.path.join(pages, '*.html'))), len(css), len(opt), len(bad_opt)))
for u in bad_opt:
    print('  FAIL', res[u], u)
other_bad = [u for u in urls if u not in opt and res[u][0] != 200]
print('other image URLs not 200: %d' % len(other_bad))
for u in sorted(other_bad)[:15]:
    print('  ', res[u][0], u.split('/uploads/')[1], 'e.g.', index.get(sorted(urls[u])[0], sorted(urls[u])[0]))
left = {}
for u in urls:
    stem = re.sub(r'-\d+x\d+$', '', u.rsplit('/', 1)[1].rsplit('.', 1)[0])
    if stem in olds:
        left[u] = urls[u]
print('originals with a re-encode still referenced: %d' % len(left))
for u in sorted(left, key=lambda x: -len(left[x]))[:25]:
    print('  %3d pages  %s  e.g. %s' % (len(left[u]), u.split('/uploads/')[1], index.get(sorted(left[u])[0], sorted(left[u])[0])))
