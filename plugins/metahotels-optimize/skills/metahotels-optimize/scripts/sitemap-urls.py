"""Every page URL in the site's sitemaps, written to audit/urls.txt (the list crawl.sh, warm.sh and state.sh use).

Usage (from the site folder): python -I <skill>/scripts/sitemap-urls.py [origin] [--out=audit/urls.txt]
Tries /sitemap_index.xml (Rank Math, Yoast) then /wp-sitemap.xml (WordPress core) and follows nested sitemaps.
Stops with an error when no sitemap answers 200 with XML: on Khalidia (2026-10-14) Rank Math's sitemap fell out of
the rewrite rules after a plugin update and sweep.js silently swept only the homepage. The fix is to open
wp-admin/options-permalink.php (rebuilds the rules, saves nothing), then LiteSpeed "Purge 404".
Prints the count per sitemap; files under /wp-content/ (image sitemaps) are left out.
"""
import os
import re
import sys
import urllib.request

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36'
pos = [a for a in sys.argv[1:] if not a.startswith('--')]
out = next((a.split('=', 1)[1] for a in sys.argv if a.startswith('--out=')), os.path.join('audit', 'urls.txt'))
if pos:
    origin = pos[0].rstrip('/')
else:
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'wp'))
    import sitecfg
    origin = sitecfg.load()['origin']


def get(u):
    try:
        req = urllib.request.Request(u, headers={'User-Agent': UA, 'Accept-Encoding': 'identity'})
        with urllib.request.urlopen(req, timeout=90) as f:
            return f.status, f.headers.get('content-type', ''), f.read().decode('utf-8', 'replace')
    except urllib.error.HTTPError as e:
        return e.code, '', ''
    except Exception as e:  # noqa: BLE001
        return 0, str(e)[:60], ''


root = None
for cand in ('/sitemap_index.xml', '/wp-sitemap.xml', '/sitemap.xml'):
    st, ct, body = get(origin + cand)
    print('%s %s %s' % (st, cand, ct.split(';')[0]))
    if st == 200 and '<loc>' in body:
        root = origin + cand
        break
if not root:
    sys.exit('no sitemap answers 200 with XML: rebuild the rewrite rules (options-permalink.php) and check again')

urls, seen = [], set()


def walk(u, depth=0):
    if u in seen or depth > 3:
        return
    seen.add(u)
    st, _, body = get(u)
    locs = [re.sub(r'<!\[CDATA\[|\]\]>', '', x).strip() for x in re.findall(r'<loc>(.*?)</loc>', body, re.S)]
    if '<sitemapindex' in body:
        for x in locs:
            walk(x, depth + 1)
        return
    pages = [x for x in locs if '/wp-content/' not in x]
    print('%4d  %s%s' % (len(pages), u.replace(origin, ''), '' if st == 200 else '  (status %s)' % st))
    for x in pages:
        if x not in urls:
            urls.append(x)


walk(root)
os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
open(out, 'w', encoding='utf-8', newline='\n').write('\n'.join(urls) + '\n')
print('wrote %s: %d URLs' % (out, len(urls)))
