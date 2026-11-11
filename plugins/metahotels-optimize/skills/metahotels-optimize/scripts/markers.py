"""Which LiteSpeed options, fixes and third parties a saved page was built with, from its HTML.

Usage (from the site folder): python -I <skill>/scripts/markers.py <file.html | pages-dir> [--per-page]
  one file   one line of name=count for every marker found (judge.sh prints it before each A/B test)
  a dir      pages carrying each marker (warm.sh and state.sh print it after a re-warm), --per-page adds one line
             per page with its non-zero markers: proof that no page kept a tested option after a revert
Site-specific markers (the site plugin's own <style id>, metahotels-core output) come from site.json "markers":
{"name": "regex", ...}. A marker is a regex counted in the raw HTML.
"""
import glob
import json
import os
import re
import sys

MARKERS = [
    # LiteSpeed page optimization
    ('lsCss', r'/wp-content/litespeed/css/'),          # minified or combined CSS
    ('lsJs', r'/wp-content/litespeed/js/'),            # minified or combined JS
    ('cssLinks', r'<link[^>]*rel=[\'"]stylesheet'),
    ('scriptSrc', r'<script[^>]*\ssrc='),
    ('deferAttr', r'<script[^>]* defer'),
    ('dataUriJs', r'src="data:text/javascript'),       # JS Defer turns inline scripts into data: URIs
    ('delayed', r'type="litespeed/javascript"'),       # JS Delay
    ('ccss', r'id="litespeed-ccss"'),
    ('ccssQueue', r'CCSS in queue'),
    ('cssAsync', r'rel=[\'"]preload[\'"][^>]*as=[\'"]style'),
    ('imgLazyLS', r'<img[^>]*data-src='),              # LiteSpeed image lazy-load
    ('imgLazyNative', r'<img[^>]*loading="lazy"'),
    ('iframeLazyLS', r'<iframe[^>]*data-lazyloaded'),
    ('iframeBlank', r'<iframe[^>]*src="about:blank"'),  # the 7.9.1 iframe fault: two src attributes
    ('preconnect', r'rel=[\'"]preconnect'),
    ('emoji', r'wp-emoji-release|_wpemojiSettings'),
    ('pageCachedLS', r'Page cached by LiteSpeed'),
    # hero, fonts, Elementor
    ('preloadImage', r'<link[^>]*rel=["\']preload["\'][^>]*as=["\']image'),
    ('preloadFont', r'<link[^>]*rel=["\']preload["\'][^>]*as=["\']font'),
    ('fetchpriorityHigh', r'fetchpriority="high"'),
    ('entranceHidden', r'elementor-invisible'),
    ('dialogCss', r'conditionals/dialog\.min\.css'),
    ('gfExternal', r'fonts\.googleapis\.com'),
    ('pageTransition', r'<e-page-transition'),
    # third parties
    ('miraiCss', r'static\.mirai\.com/core/index\.css'),
    ('miraiLoader', r'static\.mirai\.com/core/index\.js'),
    ('miraiComponent', r'data-mirai-component'),
    ('chatLazy', r'function want\(\)'),
    ('chatSync', r'<script src="https://storage\.googleapis\.com/hdr_chatbot'),
    ('recaptchaSync', r'<script[^>]*src="https://www\.google\.com/recaptcha/api\.js'),
    ('recaptchaLazyOn', r'recaptchaLazy = true'),
    ('recaptchaLazyOff', r'recaptchaLazy = false'),
    ('dbError', r'Error establishing a database connection'),
]


def site_markers():
    p = os.environ.get('SITE_JSON') or 'site.json'
    if os.path.exists(p):
        return list((json.load(open(p, encoding='utf-8')).get('markers') or {}).items())
    return []


ALL = [(n, re.compile(r)) for n, r in MARKERS + site_markers()]


def count(path):
    h = open(path, encoding='utf-8', errors='replace').read()
    return {n: len(rx.findall(h)) for n, rx in ALL}, len(h)


target = sys.argv[1]
if os.path.isfile(target):
    c, size = count(target)
    print('bytes=%d ' % size + ' '.join('%s=%d' % (n, v) for n, v in c.items() if v))
    sys.exit()
files = sorted(glob.glob(os.path.join(target, '*.html')))
index = {}
p = os.path.join(target, 'index.tsv')
if os.path.exists(p):
    for line in open(p, encoding='utf-8'):
        f = line.rstrip('\n').split('\t')
        if len(f) >= 2:
            index[f[0]] = f[-1]
pages = {n: 0 for n, _ in ALL}
rows = []
for f in files:
    c, _ = count(f)
    for n, v in c.items():
        pages[n] += bool(v)
    key = os.path.basename(f)[:-5]
    rows.append('%s %s' % (index.get(key, index.get(key.lstrip('0'), key)), ' '.join('%s=%d' % (n, v) for n, v in c.items() if v)))
print('pages: %d' % len(files))
print('pages carrying each marker: ' + '  '.join('%s %d' % (n, v) for n, v in pages.items() if v))
if '--per-page' in sys.argv:
    print('\n'.join(rows))
