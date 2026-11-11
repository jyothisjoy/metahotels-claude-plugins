"""Outline of a saved Elementor page: top-level documents and containers with their settings that matter for
loading (background video/slideshow/image, sticky, lazy class), plus mirai components, iframes and popups.

Usage: python -I outline.py <page.html>
"""
import html as htmllib
import json
import re
import sys

src = open(sys.argv[1], encoding='utf-8', errors='replace', newline='').read()

print('== elementor documents')
for m in re.finditer(r'<(\w+)\b[^>]*data-elementor-type="([^"]+)"[^>]*>', src):
    t = m.group(0)
    i = re.search(r'data-elementor-id="(\d+)"', t)
    s = re.search(r'data-elementor-settings="([^"]*)"', t)
    print('  %-10s id=%-6s at %-7d %s' % (m.group(2), i.group(1) if i else '', m.start(), htmllib.unescape(s.group(1))[:300] if s else ''))

print('\n== elements with data-settings')
for m in re.finditer(r'<(\w+)\b[^>]*data-settings="([^"]*)"[^>]*>', src):
    t = m.group(0)
    try:
        st = json.loads(htmllib.unescape(m.group(2)))
    except ValueError:
        continue
    keys = {k: v for k, v in st.items() if re.search(r'background_(video|slideshow|background)|sticky|motion_fx|_animation$|^animation$|lazyload', k)}
    if not keys:
        continue
    eid = re.search(r'data-id="([^"]+)"', t)
    et = re.search(r'data-element_type="([^"]+)"', t)
    cls = re.search(r'class="([^"]*)"', t)
    lazy = 'e-lazyload' in (cls.group(1) if cls else '')
    for k, v in list(keys.items()):
        if isinstance(v, list):
            keys[k] = '[%d items] %s' % (len(v), json.dumps(v[:1])[:160])
    print('  %-9s %-10s at %-7d lazy=%s %s' % (eid.group(1) if eid else '', et.group(1) if et else '', m.start(), lazy, json.dumps(keys)[:420]))

print('\n== mirai')
for m in re.finditer(r'<[^>]*data-mirai-(?:component|id)[^>]*>', src):
    print('  at %-7d %s' % (m.start(), m.group(0)[:200]))

print('\n== iframes')
for m in re.finditer(r'<iframe\b[^>]*>', src):
    print('  at %-7d %s' % (m.start(), re.sub(r'\?[^"]*', '?…', m.group(0))[:240]))

print('\n== recaptcha / forms')
for m in re.finditer(r'<form\b[^>]*>', src):
    print('  form at %-7d %s' % (m.start(), m.group(0)[:200]))
for m in re.finditer(r'<script\b[^>]*recaptcha[^>]*>', src):
    print('  script at %-7d %s' % (m.start(), re.sub(r'\?[^"]*', '?…', m.group(0))[:200]))

print('\n== body position markers')
for name in ('<body', '</head>', '<header', '<main', '<footer', 'directchat-widget', 'static.mirai.com/core/index.js'):
    print('  %-34s %s' % (name, [m.start() for m in re.finditer(re.escape(name), src)][:6]))
