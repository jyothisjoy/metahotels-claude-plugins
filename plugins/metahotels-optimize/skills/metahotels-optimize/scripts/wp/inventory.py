"""Site-wide inventory from the pages saved by crawl.sh.

Usage: python -I inventory.py <pages-dir> [--pages]
Prints, over all crawled pages: status/cache summary, Elementor widget types (pages using each), stylesheet and
script handles (pages carrying each), Elementor documents by type, and per-page feature flags. With --pages it
also prints one line per page.
"""
import collections
import html as htmllib
import json
import os
import re
import sys

d = sys.argv[1]
per_page = '--pages' in sys.argv
rows = [l.rstrip('\n').split('\t') for l in open(os.path.join(d, 'index.tsv'), encoding='utf-8') if l.strip()]

widgets = collections.defaultdict(set)
css = collections.defaultdict(set)
js = collections.defaultdict(set)
docs = collections.defaultdict(set)
flags = collections.defaultdict(set)
status = collections.Counter()
cache = collections.Counter()
sizes = []
lines = []


def attr(tag, name):
    m = re.search(r'\b' + name + r'\s*=\s*(["\'])(.*?)\1', tag, re.S)
    return m.group(2) if m else ''


for n, code, size, secs, ls, url in rows:
    status[code] += 1
    cache[ls] += 1
    path = re.sub(r'^https?://[^/]+', '', url) or '/'
    f = os.path.join(d, n + '.html')
    if code != '200' or not os.path.exists(f):
        lines.append('%s %s' % (code, path))
        continue
    s = open(f, encoding='utf-8', errors='replace', newline='').read()
    sizes.append((len(s), path))
    for w in set(re.findall(r'data-widget_type="([^"]+)"', s)):
        widgets[w].add(path)
    for m in re.finditer(r'<link\b[^>]*>', s):
        t = m.group(0)
        if re.search(r'rel\s*=\s*["\']stylesheet', t):
            css[attr(t, 'id') or re.sub(r'\?.*', '', attr(t, 'href'))[-70:]].add(path)
    for m in re.finditer(r'<script\b[^>]*\bsrc\s*=[^>]*>', s):
        t = m.group(0)
        js[attr(t, 'id') or re.sub(r'\?.*', '', attr(t, 'src'))[-70:]].add(path)
    page_docs = []
    for m in re.finditer(r'data-elementor-type="([^"]+)"[^>]*data-elementor-id="(\d+)"', s):
        docs['%s #%s' % (m.group(1), m.group(2))].add(path)
        page_docs.append('%s#%s' % (m.group(1)[:6], m.group(2)))
    f_ = []
    checks = [
        ('db-error', r'Error establishing a database connection'),
        ('mirai-component', r'data-mirai-component'),
        ('mirai-loader', r'static\.mirai\.com/core/index\.js'),
        ('chatbot', r'directchat-widget'),
        ('recaptcha', r'recaptcha/api\.js'),
        ('brevo-form', r'class="brevo-form"'),
        ('popup', r'data-elementor-type="popup"'),
        ('bg-video', r'background_video_link'),
        ('bg-slideshow', r'background_slideshow_gallery'),
        ('swiper', r'class="[^"]*\bswiper\b'),
        ('iframe-map', r'<iframe[^>]*maps\.google'),
        ('iframe-youtube', r'<iframe[^>]*youtube'),
        ('video-tag', r'<video\b'),
        ('loop-grid', r'data-widget_type="loop-(grid|carousel)'),
        ('gallery', r'data-widget_type="(gallery|image-gallery|image-carousel|media-carousel)'),
        ('sticky', r'&quot;sticky&quot;:&quot;'),
        ('entrance-anim', r'elementor-invisible'),
        ('gf-external', r'fonts\.googleapis\.com'),
        ('preload-img', r'<link[^>]*rel=["\']preload["\'][^>]*as=["\']image'),
        ('lazyloaded', r'data-lazyloaded'),
        ('ls-min', r'/wp-content/litespeed/(css|js)/'),
    ]
    for name, pat in checks:
        c = len(re.findall(pat, s))
        if c:
            flags[name].add(path)
            f_.append('%s=%d' % (name, c))
    imgs = len(re.findall(r'<img\b', s))
    lazy = len(re.findall(r'<img\b[^>]*loading=["\']lazy', s))
    lines.append('%s %-4s %6.1fK %5ss img=%d/%d lazy  %s  [%s]  %s' % (code, ls, len(s) / 1024, secs[:4], lazy, imgs, path, ' '.join(page_docs), ' '.join(f_)))

total = len(rows)
print('pages:', total, ' status:', dict(status), ' x-litespeed-cache at crawl:', dict(cache))
print('largest HTML:', ', '.join('%s %.0fK' % (p, b / 1024) for b, p in sorted(sizes, reverse=True)[:5]))


def table(title, m, limit=None):
    print('\n== %s (%d)' % (title, len(m)))
    for k, v in sorted(m.items(), key=lambda x: (-len(x[1]), x[0]))[:limit]:
        eg = '' if len(v) > 6 else '  e.g. ' + ', '.join(sorted(v)[:3])
        print('  %4d  %s%s' % (len(v), k, eg))


table('widget types: pages using each', widgets)
table('stylesheets: pages carrying each', css)
table('scripts: pages carrying each', js)
table('feature flags: pages', flags)
table('elementor documents: pages', {k: v for k, v in docs.items() if not k.startswith(('wp-page', 'wp-post', 'loop-item'))})

if per_page:
    print('\n== pages')
    for l in lines:
        print(l)
