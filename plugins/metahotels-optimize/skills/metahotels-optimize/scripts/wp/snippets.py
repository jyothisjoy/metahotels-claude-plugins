"""Summarise Elementor Custom Code snippets saved from /wp-json/wp/v2/elementor_snippet?context=edit.

Usage: python -I snippets.py <snippets.json> [--dump=<dir>]
"""
import json
import os
import re
import sys

data = json.load(open(sys.argv[1], encoding='utf-8'))
dump = next((a.split('=', 1)[1] for a in sys.argv[2:] if a.startswith('--dump=')), None)
if dump:
    os.makedirs(dump, exist_ok=True)

print('snippets:', len(data))
for s in sorted(data, key=lambda s: s['id']):
    meta = s.get('meta') or {}
    code = meta.get('_elementor_code') or ''
    title = (s.get('title') or {}).get('raw') or (s.get('title') or {}).get('rendered') or ''
    srcs = re.findall(r'<script\b[^>]*\bsrc\s*=\s*["\']([^"\']+)', code)
    links = re.findall(r'<link\b[^>]*\bhref\s*=\s*["\']([^"\']+)', code)
    tags = [t for t, p in [
        ('mirai', r'mirai'), ('gtm/ga', r'googletagmanager|gtag\('), ('fb', r'fbq\(|facebook'),
        ('chat', r'chat', ), ('video', r'<video|\.mp4|createElement\(.video'), ('recaptcha', r'recaptcha'),
        ('style', r'<style'), ('timer', r'setTimeout|setInterval'), ('onload', r'addEventListener\(.load|window\.onload'),
        ('DCL', r'DOMContentLoaded'), ('jquery', r'jQuery|\$\(')] if re.search(p, code, re.I)]
    print('\n#%s [%s] %s' % (s['id'], s.get('status'), title))
    print('   location=%s priority=%s bytes=%d modified=%s' % (
        meta.get('_elementor_location'), meta.get('_elementor_priority'), len(code), s.get('modified')))
    other = {k: v for k, v in meta.items() if k not in ('_elementor_code', '_elementor_location', '_elementor_priority') and v not in ('', None, [], {})}
    if other:
        print('   meta:', json.dumps(other)[:300])
    if tags:
        print('   tags:', ', '.join(tags))
    for u in srcs:
        print('   script src:', u[:140])
    for u in links:
        print('   link href:', u[:140])
    if dump:
        with open(os.path.join(dump, 'snippet-%s.html' % s['id']), 'w', encoding='utf-8', newline='') as f:
            f.write(code)
