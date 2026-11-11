# usage: python -I links.py <pages-dir> <origin> [--check] [--sleep=0.4] [--json=out.json]
# Playbook step 1b: broken links and calls to action without a link, from saved pages.
# <pages-dir> holds one HTML file per sitemap URL plus index.tsv (n, status, bytes, seconds, cache, url), which is
# what a site's tools/crawl.sh writes (curl every sitemap URL once, logged out).
#   1. Every <a href> on every page, with the Elementor document (header/footer/page/popup/loop-item + id) and the
#      widget (data-id + type) it sits in.
#   2. With --check: each distinct internal target is requested once (redirects not followed). Reports 4xx/5xx
#      targets, targets that only work through a redirect, and sitemap URLs that redirect.
#   3. Calls to action without a link: buttons, button-styled links, icon/image boxes and menu items whose href is
#      missing, empty, "#" or the page itself. Not counted: dropdown parents in a menu, popup triggers, in-page
#      anchors whose target id exists, anything inside a booking-engine component.
#   4. "Book now" style links (book, reserve, availability, and the Arabic equivalents) with where they point,
#      so each can be compared with the hotel's booking endpoint. Never guess a booking URL: ask the owner.
# The findings name the widget id, so the second pass with the MCP (elementor-get-data, get-menu) can go straight
# to the element. Nothing is changed on the site.
import collections
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # Arabic link texts on a Windows console
args = [a for a in sys.argv[1:] if not a.startswith('--')]
pages_dir, origin = args[0], args[1].rstrip('/')
check = '--check' in sys.argv
pause = next((float(a.split('=')[1]) for a in sys.argv if a.startswith('--sleep=')), 0.4)
json_out = next((a.split('=', 1)[1] for a in sys.argv if a.startswith('--json=')), None)
host = urllib.parse.urlparse(origin).netloc
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36'
BOOK = re.compile(r'\bbook\b|book now|booking|reserve|availability|احجز|حجز', re.I)
VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'source', 'track', 'wbr'}


class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.doc = '-'
        self.widget = ('', '')
        self.links = []
        self.ids = set()
        self.cur = None
        self.mirai_depth = 0
        self.depth = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag not in VOID:
            self.depth += 1
        if a.get('id'):
            self.ids.add(a['id'])
        if a.get('name') and tag == 'a':
            self.ids.add(a['name'])
        if 'data-elementor-type' in a:
            self.doc = '%s#%s' % (a['data-elementor-type'], a.get('data-elementor-id', '?'))
        if a.get('data-element_type') == 'widget':
            self.widget = (a.get('data-id', ''), a.get('data-widget_type', ''))
        if 'data-mirai-component' in a and not self.mirai_depth:
            self.mirai_depth = self.depth
        if tag == 'a':
            self.cur = {'href': a.get('href'), 'cls': a.get('class') or '', 'role': a.get('role') or '',
                        'doc': self.doc, 'widget': self.widget[0], 'wtype': self.widget[1], 'text': '',
                        'mirai': bool(self.mirai_depth), 'aria': a.get('aria-label') or '',
                        'popup': 'elementor-action' in (a.get('href') or ''), 'has_img': False}
        elif tag == 'img' and self.cur is not None:
            self.cur['has_img'] = True
            if not self.cur['text'] and a.get('alt'):
                self.cur['aria'] = self.cur['aria'] or a['alt']

    def handle_endtag(self, tag):
        if tag == 'a' and self.cur is not None:
            self.cur['text'] = re.sub(r'\s+', ' ', self.cur['text']).strip()[:60]
            self.links.append(self.cur)
            self.cur = None
        if tag not in VOID:
            if self.mirai_depth and self.depth <= self.mirai_depth:
                self.mirai_depth = 0
            self.depth -= 1

    def handle_data(self, data):
        if self.cur is not None:
            self.cur['text'] += data


def norm(href, base):
    u = urllib.parse.urljoin(base, href.strip())
    p = urllib.parse.urlparse(u)
    return urllib.parse.urlunparse((p.scheme, p.netloc, p.path, '', p.query, ''))


rows = [l.rstrip('\n').split('\t') for l in open(os.path.join(pages_dir, 'index.tsv'), encoding='utf-8') if l.strip()]
targets = collections.defaultdict(list)      # internal url -> [(page, doc, widget, wtype, text)]
external = collections.Counter()
cta = []
malformed = []    # (where..., href): a scheme that is not a real one, e.g. ttps:// (Gewan 2026-10-15)
book = collections.defaultdict(list)
sitemap = set()
for n, code, size, secs, cache, url in rows:
    sitemap.add(url)
    f = os.path.join(pages_dir, n + '.html')
    if not os.path.exists(f):
        continue
    p = Page()
    try:
        p.feed(open(f, encoding='utf-8', errors='replace').read())
    except Exception as e:  # noqa: BLE001
        print('parse error', url, str(e)[:60])
    path = url.replace(origin, '') or '/'
    for a in p.links:
        href = (a['href'] or '').strip()
        label = a['text'] or a['aria'] or ('[image]' if a['has_img'] else '')
        where = (path, a['doc'], a['widget'], a['wtype'], label)
        if a['mirai']:
            continue
        base_type = a['wtype'].split('.')[0]
        # Toggles that are links only in markup: accordion and tab titles, gallery filters, carousel arrows.
        if re.search(r'accordion|toggle|tabs|gallery|carousel|slides|lightbox', base_type):
            if a['href'] is None or href.startswith('#') or href == '':
                continue
        is_button = bool(re.search(r'elementor-button|elementskit-btn|ekit-btn|jeg-elementor-kit|e-n-menu-title', a['cls'])) or a['role'] == 'button'
        is_menu = bool(re.search(r'elementor-item|ekit-menu-nav-link|menu-link', a['cls']))
        is_box = a['wtype'].split('.')[0] in ('icon-box', 'image-box', 'call-to-action', 'banner', 'elementskit-icon-box', 'elementskit-image-box')
        if BOOK.search(label):
            book[href or '(no href)'].append(where)
        empty = href in ('', '#') or (href.startswith('#') and len(href) > 1 and False)
        # A loop card of the page's own post links to the page it is on by design, so loop items are left out.
        self_link = (bool(href) and not href.startswith('#') and norm(href, url).rstrip('/') == url.rstrip('/')
                     and is_button and not a['doc'].startswith('loop-item'))
        if a['href'] is None or empty or self_link:
            dropdown = is_menu and bool(re.search(r'dropdown|has-submenu|ekit-menu-dropdown-toggle|menu-item-has-children', a['cls']))
            if (is_button or is_box or (is_menu and not dropdown)) and not a['popup']:
                cta.append(where + ('no href' if a['href'] is None else 'href="%s"' % href if not self_link else 'links to its own page',))
            continue
        if href.startswith('#'):
            if 'elementor-action' in href:
                continue
            if href[1:] not in p.ids and (is_button or is_box or is_menu):
                cta.append(where + ('anchor %s has no target on the page' % href,))
            continue
        if re.match(r'(mailto|tel|javascript|whatsapp|sms|viber):', href, re.I):
            continue
        u = norm(href, url)
        pu = urllib.parse.urlparse(u)
        if pu.scheme not in ('http', 'https'):
            if re.match(r'[a-z]{2,8}:', href, re.I) and not re.match(r'(data|skype|maps|geo|fb-messenger|intent|market|itms-apps):', href, re.I):
                malformed.append(where + (href,))
            continue
        if pu.netloc in (host, 'www.' + host):
            targets[u].append(where)
        else:
            external[pu.netloc] += 1

print('pages %d | distinct internal targets %d | external hosts %d' % (len(rows), len(targets), len(external)))
print('external hosts:', ', '.join('%s (%d)' % kv for kv in external.most_common(14)))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


opener = urllib.request.build_opener(NoRedirect)


def status(u):
    for attempt in range(3):
        try:
            req = urllib.request.Request(urllib.parse.quote(u, safe=':/?&=%#+,;@!$\'()*~'), headers={'User-Agent': UA})
            with opener.open(req, timeout=60) as r:
                r.read(200)
                return r.status, ''
        except urllib.error.HTTPError as e:
            return e.code, e.headers.get('Location', '') or ''
        except Exception as e:  # noqa: BLE001
            err = str(e)[:50]
            time.sleep(2)
    return 0, err


result = {'broken': [], 'redirects': [], 'cta': [], 'book': {}}
if check:
    known_ok = {r[5] for r in rows if r[1] == '200'}
    todo = sorted(targets)
    print('checking %d targets (%d already known 200 from the crawl) ...' % (len(todo), sum(1 for t in todo if t in known_ok)), flush=True)
    for i, u in enumerate(todo, 1):
        if u in known_ok:
            continue
        code, loc = status(u)
        if code >= 400 or code == 0:
            result['broken'].append({'url': u, 'status': code, 'note': loc, 'from': targets[u]})
        elif 300 <= code < 400:
            result['redirects'].append({'url': u, 'status': code, 'to': loc, 'from': targets[u]})
        time.sleep(pause)

    def show(title, items, key):
        print('\n== %s (%d)' % (title, len(items)))
        for it in sorted(items, key=lambda x: -len(x['from'])):
            srcs = it['from']
            pages = sorted({s[0] for s in srcs})
            where = collections.Counter('%s %s %s' % (s[1], s[2], s[3]) for s in srcs).most_common(3)
            print('  %s %s%s' % (it['status'], it['url'].replace(origin, ''), ' -> ' + it[key].replace(origin, '') if it.get(key) else ''))
            print('      linked from %d page(s), e.g. %s | in %s | text "%s"' % (
                len(pages), ', '.join(pages[:3]), '; '.join('%s (%d)' % w for w in where), srcs[0][4]))

    show('broken internal links', result['broken'], 'note')
    show('internal links that only work through a redirect', result['redirects'], 'to')
    redir_sitemap = [r for r in rows if r[1] not in ('200',)]
    print('\n== sitemap URLs that did not answer 200 (%d)' % len(redir_sitemap))
    for r in redir_sitemap:
        print('  %s %s' % (r[1], r[5]))

print('\n== links with a malformed scheme, e.g. ttps:// (%d)' % len(malformed))
for m in malformed:
    print('  %-16s widget %-9s %-26s "%s" | href=%s | page %s' % (m[1], m[2], m[3], m[4], m[5][:80], m[0]))
result['malformed'] = [{'page': m[0], 'doc': m[1], 'widget': m[2], 'type': m[3], 'text': m[4], 'href': m[5]} for m in malformed]

print('\n== calls to action without a link (%d occurrences)' % len(cta))
groups = collections.defaultdict(list)
for path, doc, widget, wtype, label, why in cta:
    groups[(doc, widget, wtype, label, why)].append(path)
for (doc, widget, wtype, label, why), pages in sorted(groups.items(), key=lambda x: -len(x[1])):
    print('  %-16s widget %-9s %-26s "%s" | %s | %d page(s), e.g. %s' % (doc, widget, wtype, label, why, len(set(pages)), ', '.join(sorted(set(pages))[:3])))
    result['cta'].append({'doc': doc, 'widget': widget, 'type': wtype, 'text': label, 'why': why, 'pages': sorted(set(pages))})

print('\n== "book" links by target (%d targets)' % len(book))
for href, srcs in sorted(book.items(), key=lambda x: -len(x[1])):
    docs = collections.Counter('%s %s "%s"' % (s[1], s[2], s[4]) for s in srcs).most_common(4)
    print('  %-70s %4d links on %3d page(s) | %s' % (href[:70], len(srcs), len({s[0] for s in srcs}), '; '.join('%s (%d)' % d for d in docs)))
    result['book'][href] = {'links': len(srcs), 'pages': sorted({s[0] for s in srcs})[:10], 'where': docs}

if json_out:
    json.dump(result, open(json_out, 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
    print('\nwrote', json_out)
