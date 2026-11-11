"""Images printed in the saved pages' HTML (<img src>) that the Elementor trees do not reference: featured images,
block-editor content, theme output. Prints the ones at or above --min-kb with the pages that show them.

Usage (from the site folder): python -I <skill>/scripts/wp/html-images.py <pages-dir> <dir of saved Elementor trees> [--min-kb=80]
"""
import concurrent.futures
import glob
import os
import re
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sitecfg  # noqa: E402

CFG = sitecfg.load()
pages, listed = sys.argv[1], sys.argv[2]
min_kb = next((int(a.split('=')[1]) for a in sys.argv if a.startswith('--min-kb=')), 80)
known = set()
for f in glob.glob(os.path.join(listed, '*.json')):
    known |= set(re.findall(r'([^/\\"]+\.(?:webp|jpe?g|png|avif))"', open(f, encoding='utf-8').read(), re.I))
index = {}
for line in open(os.path.join(pages, 'index.tsv'), encoding='utf-8'):
    p = line.rstrip('\n').split('\t')
    if len(p) >= 6:
        index[p[0].zfill(3)] = p[5]
found = {}
for f in sorted(glob.glob(os.path.join(pages, '*.html'))):
    n = os.path.basename(f)[:-5]
    for tag in re.findall(r'<img\b[^>]*>', open(f, encoding='utf-8', errors='replace').read()):
        m = re.search(r'\ssrc="(https://' + re.escape(CFG['host']) + r'/wp-content/uploads/[^"]+)"', tag)
        if not m:
            continue
        u = m.group(1)
        if u.rsplit('/', 1)[1] in known:
            continue
        cls = re.search(r'class="([^"]*)"', tag)
        wid = re.search(r'wp-image-(\d+)', cls.group(1)) if cls else None
        found.setdefault(u, {'pages': set(), 'cls': 'wp-image-' + wid.group(1) if wid else (cls.group(1)[:30] if cls else '')})['pages'].add(index.get(n, n))


def size(u):
    try:
        req = urllib.request.Request(u, method='HEAD', headers={'User-Agent': 'Mozilla/5.0 perf-audit'})
        with urllib.request.urlopen(req, timeout=60) as h:
            n = int(h.headers.get('content-length') or 0)
        if not n:
            # Behind the CDN a cached file's HEAD can come without content-length: fetch it once.
            with urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': 'Mozilla/5.0 perf-audit'}), timeout=60) as h:
                n = len(h.read())
        return n
    except Exception:  # noqa: BLE001
        return -1


with concurrent.futures.ThreadPoolExecutor(6) as ex:
    sizes = dict(zip(found, ex.map(size, found)))
rows = sorted(found, key=lambda u: -sizes[u])
print('%d <img> URLs not in the Elementor trees; %d at or above %d KB, %.0f KB' % (len(rows), sum(1 for u in rows if sizes[u] >= min_kb * 1024), min_kb, sum(sizes[u] for u in rows if sizes[u] >= min_kb * 1024) / 1024))
for u in rows:
    if sizes[u] < min_kb * 1024:
        break
    pg = sorted(found[u]['pages'])
    print('%6.0f KB  %-60s %-30s %d pages e.g. %s' % (sizes[u] / 1024, u.split('/uploads/')[1][-60:], found[u]['cls'], len(pg), pg[0].replace(CFG['origin'], '')))
