"""Which globally loaded libraries are actually used, per crawled page.

usage: python -I usage.py <pages-dir>
Counts, over every saved page, the markup that needs each library (careers plugin, theme carousels, icon fonts,
Font Awesome 4 class names) and the stylesheet/script handles present, so unused ones can be proposed for removal.
"""
import collections
import io
import os
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
d = sys.argv[1]
rows = [l.rstrip('\n').split('\t') for l in open(os.path.join(d, 'index.tsv'), encoding='utf-8') if l.strip()]

MARKS = {
    'awsm (careers) markup': r'class="[^"]*\bawsm-(?!b-)[a-z-]+',
    'awsm block markup': r'class="[^"]*\bawsm-b-',
    'owl carousel': r'class="[^"]*\bowl-carousel\b',
    'slick': r'class="[^"]*\bslick-|data-slick|class="[^"]*\bova-slick',
    'masonry/isotope': r'class="[^"]*\b(masonry|isotope|grid-sizer)\b',
    'ovaicon icon': r'class="[^"]*\bovaicon-',
    'icomoon icon': r'class="[^"]*\bicomoon-',
    'flaticon': r'class="[^"]*\bflaticon',
    'fa4 class (fa fa-)': r'class="[^"]*\bfa fa-',
    'fa5 font class (fas/far/fab)': r'<i[^>]*class="[^"]*\b(fas|far|fab) fa-',
    'fa svg inline (e-font-icon-svg)': r'e-font-icon-svg',
    'eicons': r'class="[^"]*\beicon-',
    'romancy widget': r'data-widget_type="romancy_',
    'ova widget': r'data-widget_type="ova_',
    'form': r'<form\b',
    'brevo form': r'class="brevo-form"',
    'recaptcha': r'recaptcha/api\.js',
    'iframe': r'<iframe\b',
    'popup': r'data-elementor-type="popup"',
    'chatbot': r'directchat-widget',
    'mirai finder': r'data-mirai-component="finder"',
    'mirai other': r'data-mirai-component="(?!finder)',
    'bg slideshow': r'background_slideshow_gallery',
    'bg video': r'background_video_link',
    'elementor-invisible': r'elementor-invisible',
    'sticky': r'&quot;sticky&quot;:&quot;',
    'gallery widget': r'data-widget_type="gallery',
    'lottie': r'data-widget_type="lottie',
}
pages = collections.Counter()
total = collections.Counter()
example = {}
handles = collections.Counter()
widgets = collections.Counter()
for r in rows:
    n, status, url = r[0], r[1], r[-1]
    p = os.path.join(d, n + '.html')
    if status != '200' or not os.path.exists(p):
        continue
    doc = open(p, encoding='utf-8', errors='replace', newline='').read()
    for name, pat in MARKS.items():
        c = len(re.findall(pat, doc))
        if c:
            pages[name] += 1
            total[name] += c
            example.setdefault(name, url)
    for m in re.finditer(r"<(?:link|script)\b[^>]*\bid=[\"']([^\"']+?)-(css|js)[\"']", doc):
        handles[m.group(1) + ' (' + m.group(2) + ')'] += 1
    for w in set(re.findall(r'data-widget_type="([^"]+)"', doc)):
        widgets[w] += 1

npages = sum(1 for r in rows if r[1] == '200')
print('pages', npages)
print('== markup')
for name in MARKS:
    print('  %-34s pages %3d  hits %5d  %s' % (name, pages[name], total[name], re.sub(r'^https?://[^/]+', '', example.get(name, ''))[:60]))
print('== handles (pages)')
for h, c in sorted(handles.items(), key=lambda x: (-x[1], x[0])):
    print('  %3d %s' % (c, h))
print('== widget types (pages)')
for w, c in sorted(widgets.items(), key=lambda x: (-x[1], x[0])):
    print('  %3d %s' % (c, w))
