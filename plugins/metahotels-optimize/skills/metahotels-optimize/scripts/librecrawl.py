# usage: python -I librecrawl.py crawl <site-url> <out.json> [--depth=10] [--concurrency=2] [--delay=1] [--js]
#        python -I librecrawl.py summary <out.json>
#        python -I librecrawl.py compare <out.json> <links.json> <index.tsv>
# Drives a local LibreCrawl (playbook step 1c; start it with `librecrawl/.venv/Scripts/python.exe librecrawl-serve.py`,
# local mode, 127.0.0.1:5000) through its API and saves the full result: urls, links, issues.
#   crawl    one crawl, logged out, with the playbook settings (images HEAD-checked, external links HEAD-checked,
#            same browser user agent as crawl.sh), then prints the summary.
#   summary  status codes, issues by type, broken links (internal and external) and redirects with their source pages.
#   compare  against links.py output and crawl.sh's index.tsv for the same site: broken and redirecting targets found
#            by one and not the other, sitemap URLs the crawl never reached, crawled URLs missing from the sitemap.
# Nothing is changed on the site. Never run while a LiteSpeed test option is on (every crawled page is regenerated).
import json, sys, time, urllib.request, http.cookiejar
from collections import Counter, defaultdict
from urllib.parse import urlsplit

SERVER = 'http://127.0.0.1:5000'
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
      'Chrome/140.0.0.0 Safari/537.36')


def opts(args):
    o = {}
    for a in args:
        if a.startswith('--'):
            k, _, v = a[2:].partition('=')
            o[k] = v or True
    return o


class Api:
    def __init__(self, server=SERVER):
        self.server = server
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def call(self, path, body=None, timeout=60):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.server + path, data=data, method='GET' if body is None else 'POST',
                                     headers={'Content-Type': 'application/json'})
        with self.op.open(req, timeout=timeout) as r:
            return json.loads(r.read().decode('utf-8'))


def crawl(site, out, o):
    api = Api()
    print('login', api.call('/api/guest-login', {}))
    settings = {
        'maxDepth': int(o.get('depth', 10)), 'concurrency': int(o.get('concurrency', 2)),
        'crawlDelay': float(o.get('delay', 1)), 'crawlImages': True, 'crawlExternalLinks': False,
        'respectRobotsTxt': True, 'discoverSitemaps': True, 'userAgent': UA, 'timeout': 30,
        'enableJavaScript': bool(o.get('js')), 'enablePageSpeed': False,
    }
    print('settings', api.call('/api/save_settings', settings))
    r = api.call('/api/start_crawl', {'url': site})
    print('start', r)
    if not r.get('success'):
        sys.exit(1)
    t0, last = time.time(), None
    time.sleep(5)
    while True:
        s = api.call('/api/crawl_status?stats_only=1')
        st = s.get('stats', {})
        line = f"{int(time.time() - t0)}s {s['status']} crawled={st.get('crawled')} discovered={st.get('discovered')}"
        if line.split(' ', 1)[1] != last:
            print(line, flush=True)
            last = line.split(' ', 1)[1]
        if s['status'] in ('completed', 'idle', 'demo_stopped'):
            break
        time.sleep(5)
    full = api.call('/api/crawl_status', timeout=300)
    full['_meta'] = {'site': site, 'settings': settings, 'seconds': round(time.time() - t0)}
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(full, f, ensure_ascii=False)
    print('saved', out)
    summary(full)


def path_of(u):
    p = urlsplit(u)
    return p.path + ('?' + p.query if p.query else '')


def summary(d):
    urls, links, issues = d.get('urls', []), d.get('links', []), d.get('issues', [])
    internal = [u for u in urls if u.get('is_internal')]
    print(f"\nURLs: {len(urls)} ({len(internal)} internal), links: {len(links)}, issues: {len(issues)}, "
          f"seconds: {d.get('_meta', {}).get('seconds')}")
    print('status codes (internal):', dict(Counter(u.get('status_code') for u in internal)))
    print('\nissues by type:')
    for (t, cat, name), n in sorted(Counter((i['type'], i['category'], i['issue']) for i in issues).items(),
                                    key=lambda x: (x[0][0] != 'error', -x[1])):
        print(f'  {n:5d}  {t:7s} {cat:16s} {name}')
    bad = defaultdict(set)
    for l in links:
        s = l.get('target_status')
        if s is not None and (s == 0 or s >= 400):
            bad[(l['target_url'], s, l['is_internal'], l.get('placement'))].add(path_of(l['source_url']))
    print(f'\nbroken link targets: {len(bad)}')
    for (t, s, internal_, place), src in sorted(bad.items(), key=lambda x: (not x[0][2], x[0][0])):
        print(f"  {s} {'int' if internal_ else 'ext'} {place:10s} {t}\n      from {len(src)}: {', '.join(sorted(src)[:4])}")
    red = defaultdict(set)
    for l in links:
        s = l.get('target_status')
        if s and 300 <= s < 400:
            red[(l['target_url'], s)].add(path_of(l['source_url']))
    print(f'\nredirecting link targets: {len(red)}')
    for (t, s), src in sorted(red.items()):
        print(f"  {s} {t}  (from {len(src)})")


def compare(d, links_json, index_tsv):
    lp = json.load(open(links_json, encoding='utf-8'))
    sitemap = set()
    for line in open(index_tsv, encoding='utf-8'):
        parts = line.rstrip('\n').split('\t')
        if len(parts) >= 6:
            sitemap.add(parts[-1].rstrip('/'))
    lc_links = d.get('links', [])
    norm = lambda u: u.split('#')[0].rstrip('/')
    lc_bad = {norm(l['target_url']): l['target_status'] for l in lc_links
              if l.get('is_internal') and l.get('target_status') is not None
              and (l['target_status'] == 0 or l['target_status'] >= 400)}
    lc_red = {norm(l['target_url']): l['target_status'] for l in lc_links
              if l.get('is_internal') and l.get('target_status') and 300 <= l['target_status'] < 400}
    lp_bad = {norm(b['url']): b['status'] for b in lp.get('broken', [])}
    lp_red = {norm(b['url']): b['status'] for b in lp.get('redirects', [])}
    lc_status = {norm(l['target_url']): l.get('target_status') for l in lc_links}
    print(f'broken internal targets: links.py {len(lp_bad)}, LibreCrawl {len(lc_bad)}')
    for u in sorted(set(lp_bad) - set(lc_bad)):
        print(f'  only links.py   {lp_bad[u]} {u}  (LibreCrawl saw: {lc_status.get(u, "not linked")})')
    for u in sorted(set(lc_bad) - set(lp_bad)):
        print(f'  only LibreCrawl {lc_bad[u]} {u}')
    print(f'redirecting internal targets: links.py {len(lp_red)}, LibreCrawl {len(lc_red)}')
    for u in sorted(set(lp_red) - set(lc_red)):
        print(f'  only links.py   {lp_red[u]} {u}  (LibreCrawl saw: {lc_status.get(u, "not linked")})')
    for u in sorted(set(lc_red) - set(lp_red)):
        print(f'  only LibreCrawl {lc_red[u]} {u}')
    crawled = {norm(u['url']): u.get('status_code') for u in d.get('urls', []) if u.get('is_internal')}
    ok = {u for u, s in crawled.items() if s == 200}
    print(f'\nsitemap URLs: {len(sitemap)}, crawled internal 200: {len(ok)}')
    miss = sorted(sitemap - set(crawled))
    print(f'in the sitemap, never reached by following links: {len(miss)}')
    for u in miss:
        print('  ', u)
    extra = sorted(u for u in ok - sitemap)
    print(f'answer 200, linked, not in the sitemap: {len(extra)}')
    for u in extra:
        print('  ', u)


if __name__ == '__main__':
    a = sys.argv[1:]
    if not a:
        sys.exit(__doc__ or 'see the header of this file')
    if a[0] == 'crawl':
        crawl(a[1], a[2], opts(a[3:]))
    elif a[0] == 'summary':
        summary(json.load(open(a[1], encoding='utf-8')))
    elif a[0] == 'compare':
        compare(json.load(open(a[1], encoding='utf-8')), a[2], a[3])
