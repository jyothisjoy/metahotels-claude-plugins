"""With LiteSpeed CSS Combine on: does every page's combined stylesheet contain the CSS of every Elementor document
the page renders?

Usage: python -I check-bundles.py <urls.txt> [--sleep=1.0]
For each URL: fetch the page (this also warms the cache), collect the ids of the Elementor documents in the HTML
(page, header, footer, popup, loop items) and the /wp-content/litespeed/css/ stylesheet(s) it links, and check
that the stylesheets contain rules for `.elementor-<id>` for every one of those ids. A document's CSS that is
missing from the bundle means that document is unstyled on that page. Pages without a combined stylesheet are
checked against their separate post-<id>.css links instead.
"""
import re
import sys
import time
import urllib.request

urls = [l.strip() for l in open(sys.argv[1], encoding='utf-8') if l.strip()]
pause = next((float(a.split('=')[1]) for a in sys.argv if a.startswith('--sleep=')), 1.0)
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36'
bundles = {}


def get(u):
    for attempt in range(3):
        try:
            req = urllib.request.Request(u, headers={'User-Agent': UA})
            with urllib.request.urlopen(req, timeout=90) as f:
                return f.status, f.headers.get('x-litespeed-cache', '-'), f.read().decode('utf-8', 'replace')
        except Exception as e:  # noqa: BLE001
            err = str(e)[:80]
            time.sleep(2)
    return 0, err, ''


bad = 0
states = {}
for i, u in enumerate(urls, 1):
    code, cache, html = get(u)
    path = re.sub(r'^https?://[^/]+', '', u) or '/'
    if code != 200 or 'Error establishing a database connection' in html:
        print('FETCH %s %s %s' % (code, cache, path), flush=True)
        bad += 1
        continue
    ids = sorted(set(re.findall(r'data-elementor-type="[a-z-]+" data-elementor-id="(\d+)"', html)), key=int)
    links = re.findall(r'<link[^>]*rel=[\'"]stylesheet[\'"][^>]*>', html)
    hrefs = [re.search(r'href=[\'"]([^\'"]+)', l).group(1) for l in links if 'href=' in l]
    combined = [h for h in hrefs if '/wp-content/litespeed/css/' in h]
    kind = 'combined' if len(combined) <= 2 and len(hrefs) <= 6 else 'separate'
    states[kind] = states.get(kind, 0) + 1
    css = ''
    for h in combined:
        if h not in bundles:
            bundles[h] = get(h.replace('&#038;', '&').replace('&amp;', '&'))[2]
        css += bundles[h]
    css += ' '.join(re.findall(r'<style[^>]*>(.*?)</style>', html, re.S))
    missing = [x for x in ids if not re.search(r'\.elementor-' + x + r'[ .:{,>\[]', css)]
    if missing or not combined:
        bad += 1
        print('MISSING %-9s %s ids=%s missing=%s bundles=%d' % (kind, path, ','.join(ids), ','.join(missing) or '-', len(combined)), flush=True)
    if i % 50 == 0:
        print('... %d/%d checked, %d distinct stylesheets, %d problems' % (i, len(urls), len(bundles), bad), flush=True)
    time.sleep(pause)
print('done: %d pages, states %s, %d distinct stylesheets, %d problems' % (len(urls), states, len(bundles), bad))
