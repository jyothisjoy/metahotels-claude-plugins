"""Offline tests for the site-structure checks (site_checks.py, registry 1.7): orphans, click depth, EN/AR hreflang
sets, shared boilerplate, link previews, headings, generic anchors, URL variants, and their re-check types.

Run: uv run --offline pytest -q tests/test_site_checks_extended.py      (from plugins/hotel-seo/server)
"""
import json
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from hotel_seo_tools import analysis, checks, paths, report, site_checks as sc

SITE = 'https://hotel.com'
HOST = 'hotel.com'


def U(path):
    return SITE + path


def pg(ptype, **kw):
    p = {'type': ptype, 'robots': '', 'x_robots_tag': '', 'canonical': '', 'hreflang': {}, 'h1': [],
         'og_title': 'Title', 'og_image': '/img.jpg'}
    p.update(kw)
    return p


def crawl(links, urls=()):
    """crawl.json shape: urls (200 pages unless given) and links."""
    seen = {s for s, _ in links} | {t for _, t in links} | set(urls)
    return {'urls': [{'url': u, 'status_code': 200, 'content_type': 'text/html'} for u in sorted(seen)],
            'links': [{'source_url': s, 'target_url': t, 'anchor_text': ''} for s, t in links]}


ok_status = lambda url: 200                                  # noqa: E731
no_probe = lambda url: {'status': 301, 'location': '/'}      # noqa: E731


# ---------------------------------------------------------------- orphans (L01)

def _orphan_site():
    pages = {U('/'): pg('home'), U('/rooms/'): pg('rooms'), U('/rooms/deluxe/'): pg('rooms'),
             U('/rooms/hidden-suite/'): pg('rooms'), U('/old-page/'): pg('other'),
             U('/privacy-policy/'): pg('other'), U('/thank-you/'): pg('other'),
             U('/rooms/noindexed/'): pg('rooms', robots='noindex, follow')}
    data = crawl([(U('/'), U('/rooms/')), (U('/rooms/'), U('/rooms/deluxe/')), (U('/rooms/deluxe/'), U('/'))])
    return pages, data


def test_orphans_flag_unlinked_pages_and_rate_key_pages_high():
    pages, data = _orphan_site()
    graph = sc.link_graph(data, HOST)
    out = {o['url']: o for o in sc.orphans(pages, graph, sc.hotel_mains(SITE, None), extra=[U('/old-page/')])}
    assert set(out) == {U('/rooms/hidden-suite/'), U('/old-page/')}
    assert out[U('/rooms/hidden-suite/')]['key'] is True
    assert out[U('/old-page/')]['key'] is False and 'sitemap' in out[U('/old-page/')]['found_in']


def test_orphans_skip_linked_legal_thankyou_noindex_and_follow_redirects():
    pages, data = _orphan_site()
    # a link to the old address that redirects to the suite counts as a link to the suite
    data['urls'].append({'url': U('/old-suite/'), 'status_code': 200, 'redirects': [{'status_code': 301}],
                         'redirected_to': U('/rooms/hidden-suite/')})
    data['links'].append({'source_url': U('/rooms/'), 'target_url': U('/old-suite/')})
    data['links'].append({'source_url': U('/'), 'target_url': U('/old-page')})        # no trailing slash: same page
    out = sc.orphans(pages, sc.link_graph(data, HOST), sc.hotel_mains(SITE, None))
    assert out == []


# ---------------------------------------------------------------- click depth (L02)

def test_key_page_more_than_three_clicks_is_flagged():
    chain = ['/', '/a/', '/b/', '/c/', '/dining/']
    links = [(U(a), U(b)) for a, b in zip(chain, chain[1:])] + [(U('/'), U('/rooms/')), (U('/rooms/'), U('/rooms/x/'))]
    pages = {U(p): pg('home' if p == '/' else 'other') for p in chain}
    pages[U('/rooms/x/')] = pg('rooms')
    graph = sc.link_graph(crawl(links), HOST)
    out = sc.depth_report(pages, graph, sc.hotel_mains(SITE, None), None)
    assert [(d['url'], d['clicks']) for d in out] == [(U('/dining/'), 4)]


def test_group_depth_counts_from_the_hotels_own_section():
    reg = {'hotels': [{'slug': 'a', 'paths': ['/hotels/a/']}, {'slug': 'b', 'paths': ['/hotels/b/']}]}
    chain = ['/hotels/b/', '/hotels/b/1/', '/hotels/b/2/', '/hotels/b/3/', '/hotels/b/rooms/y/']
    links = [(U(a), U(b)) for a, b in zip(chain, chain[1:])] + [
        (U('/'), U('/hotels/a/')), (U('/'), U('/hotels/b/')), (U('/hotels/a/'), U('/hotels/a/rooms/x/')),
        (U('/'), U('/hotels/b/rooms/y/'))]                      # 1 click from the group home, 4 from hotel b
    pages = {U(p): pg('other') for p in chain[:-1]}
    pages.update({U('/hotels/b/rooms/y/'): pg('rooms'), U('/hotels/a/rooms/x/'): pg('rooms'), U('/'): pg('home')})
    out = sc.depth_report(pages, sc.link_graph(crawl(links), HOST), sc.hotel_mains(SITE, reg), reg)
    assert [(d['url'], d['clicks'], d['start']) for d in out] == [(U('/hotels/b/rooms/y/'), 4, U('/hotels/b/'))]


# ---------------------------------------------------------------- hreflang (T15)

def _pair(en, ar, xd=True):
    alts = {'en': U(en), 'ar': U(ar)} | ({'x-default': U(en)} if xd else {})
    return alts


def test_hreflang_incomplete_missing_language_xdefault_and_self():
    pages = {U('/'): pg('home', hreflang=_pair('/', '/ar/', xd=False)),
             U('/ar/'): pg('other', hreflang=_pair('/', '/ar/')),
             U('/rooms/deluxe/'): pg('rooms', hreflang={'en': U('/rooms/deluxe/')}),
             U('/offers/summer/'): pg('offers'),
             U('/rooms/twin/'): pg('rooms', hreflang={'en': U('/rooms/other/'), 'ar': U('/ar/rooms/twin/')})}
    out = {x['url']: x['problems'] for x in sc.hreflang_sets(pages, sc.hotel_mains(SITE, None))['incomplete']}
    assert out[U('/')] == ['no x-default']
    assert out[U('/rooms/deluxe/')] == ['no ar version linked']
    assert out[U('/offers/summer/')] == ['no hreflang tags (no linked translation)']
    assert out[U('/rooms/twin/')] == ['the set does not list the page itself']
    assert U('/ar/') not in out


def test_hreflang_complete_pair_and_one_language_site_pass():
    pages = {U('/'): pg('home', hreflang=_pair('/', '/ar/')), U('/ar/'): pg('other', hreflang=_pair('/', '/ar/'))}
    assert sc.hreflang_sets(pages, sc.hotel_mains(SITE, None))['incomplete'] == []
    mono = {U('/'): pg('home'), U('/rooms/x/'): pg('rooms')}
    assert sc.hreflang_sets(mono, sc.hotel_mains(SITE, None)) == {'languages': [], 'incomplete': []}


def test_hreflang_return_link_missing_when_target_has_no_tags():
    pages = {U('/rooms/a/'): pg('rooms', hreflang={'en': U('/rooms/a/'), 'ar': U('/ar/rooms/a/')}),
             U('/ar/rooms/a/'): pg('rooms', hreflang={})}
    out = analysis.hreflang_report(pages, {'urls': []})
    assert [(x['url'], x['code']) for x in out['no_return_link']] == [(U('/rooms/a/'), 'ar')]
    pages[U('/ar/rooms/a/')]['hreflang'] = {'en': U('/rooms/a/'), 'ar': U('/ar/rooms/a/')}
    assert analysis.hreflang_report(pages, {'urls': []})['no_return_link'] == []


# ---------------------------------------------------------------- boilerplate (O20)

SHARED = 'The {n} is the perfect choice for families who want space and comfort during their stay in Dubai.'


def test_boilerplate_finds_name_swapped_sentence_on_most_room_pages():
    names = ['Deluxe Room', 'Superior Room', 'Family Suite', 'Executive Suite', 'Studio Apartment']
    pages = {}
    for i, n in enumerate(names):
        own = f'This room has its own view number {i} over the creek and a desk by the window.' \
              f' Unique line {"abcde"[i]} about the {n} bathroom with a rain shower and bath.'
        sents = sc.sentences(SHARED.format(n=n) + ' ' + own + ' Book now and save.')
        pages[U(f'/rooms/r{i}/')] = pg('rooms', h1=[n], main_sentences=sents)
    out = sc.boilerplate(pages, None)
    shared = [r for r in out['shared'] if 'perfect choice' in r['sentence']]
    assert shared and shared[0]['pages'] == 5 and shared[0]['of'] == 5
    assert all('Book now' not in r['sentence'] for r in out['shared'])         # under 8 words
    # the re-check text is the page's own wording
    s, k, n, kind = out['per_page'][U('/rooms/r1/')][0]
    assert 'Superior Room' in s and (k, n, kind) == (5, 5, 'rooms')


def test_boilerplate_ignores_unique_copy_and_small_groups():
    pages = {U(f'/rooms/r{i}/'): pg('rooms', h1=[f'Room {i}'], main_sentences=sc.sentences(
        f'Room {i} looks over the {c} side of the creek with a long sofa and a desk.'))
        for i, c in enumerate(['north', 'south', 'east', 'west', 'old'])}
    assert sc.boilerplate(pages, None)['shared'] == []
    few = {U(f'/offers/o{i}/'): pg('offers', main_sentences=[SHARED.format(n='offer')]) for i in range(3)}
    assert sc.boilerplate(few, None)['shared'] == []                           # fewer than 4 offer pages


def test_page_extras_keeps_headings_and_chrome_out_of_sentences():
    html = ('<html><head><title>Deluxe Room | Hotel</title><meta property="og:title" content="Deluxe"></head><body>'
            '<header><p>Header promo line that is long enough to count as one sentence.</p></header>'
            '<h1>Deluxe Room</h1><h2>About the room</h2><div><p>The Deluxe Room is the perfect choice for families '
            'who want <a href="/x/">space</a> and comfort in Dubai.</p></div></body></html>')
    soup = BeautifulSoup(html, 'html.parser')
    ex = sc.page_extras(soup, sc.strip_chrome(soup), U('/rooms/deluxe/'), 'rooms', HOST)
    assert ex['main_sentences'] == ['The Deluxe Room is the perfect choice for families who want space and '
                                    'comfort in Dubai.']
    assert ex['og_title'] == 'Deluxe' and ex['og_image'] == '' and ex['headings'][0] == [1, 'Deluxe Room']
    assert 'main_sentences' not in sc.page_extras(soup, sc.strip_chrome(soup), U('/blog/x/'), 'blog', HOST)


# ---------------------------------------------------------------- link previews (O21)

def test_link_previews_missing_and_broken_image_on_key_pages():
    pages = {U('/'): pg('home', og_image=''), U('/rooms/x/'): pg('rooms', og_image='/gone.jpg'),
             U('/offers/y/'): pg('offers', og_title=''), U('/blog/post/'): pg('blog', og_image=''),
             U('/dining/'): pg('other')}
    status = lambda url: 404 if url.endswith('gone.jpg') else 200            # noqa: E731
    out = {x['url']: x['problems'] for x in sc.link_previews(pages, sc.hotel_mains(SITE, None), status)}
    assert out == {U('/'): ['no og:image'], U('/rooms/x/'): ['og:image /gone.jpg returns 404'],
                   U('/offers/y/'): ['no og:title']}                         # blog posts are not key pages


# ---------------------------------------------------------------- headings (O04)

HTML_HEADINGS = """<html><body><header><h5>Menu</h5></header>
<h1>Deluxe Room</h1><h2>Overview</h2><h4>Bed</h4><h3></h3><h2><img alt="Logo"></h2>
<footer><h6>Footer</h6></footer></body></html>"""


def test_heading_levels_skipped_and_empty_from_main_content_only():
    hs = sc.headings(sc.strip_chrome(BeautifulSoup(HTML_HEADINGS, 'html.parser')))
    assert hs == [[1, 'Deluxe Room'], [2, 'Overview'], [4, 'Bed'], [3, ''], [2, 'Logo']]
    pr = sc.heading_problems(hs)
    assert pr == {'skipped': ['H2 → H4 ("Bed")'], 'empty': ['empty H3']}


def test_heading_levels_in_order_pass():
    assert sc.heading_problems([[1, 'a'], [2, 'b'], [3, 'c'], [2, 'd'], [3, 'e'], [4, 'f'], [2, 'g']]) == \
        {'skipped': [], 'empty': []}


# ---------------------------------------------------------------- generic anchors (O13 / L05)

def _anchors(n_generic, n_good):
    links = ''.join(f'<a href="/rooms/r{i}/">Read more</a>' for i in range(n_generic))
    links += ''.join(f'<a href="/rooms/g{i}/">Deluxe Room {i}</a>' for i in range(n_good))
    html = f'<html><body><nav><a href="/x/">Click here</a></nav>{links}<a href="https://other.com/">here</a></body></html>'
    return sc.anchor_stats(sc.strip_chrome(BeautifulSoup(html, 'html.parser')), U('/rooms/'), HOST)


def test_generic_anchor_share_over_threshold():
    st = _anchors(4, 4)
    assert st['body_links'] == 8 and st['generic_anchor_count'] == 4 and st['generic_anchors'] == {'read more': 4}
    assert sc.generic_over(st)


def test_generic_anchor_share_under_threshold_or_too_few():
    assert not sc.generic_over(_anchors(2, 1))       # 67% but only 2 links
    assert not sc.generic_over(_anchors(3, 10))      # 3 of 13


# ---------------------------------------------------------------- URL variants (T08)

def test_url_variants_from_the_crawl():
    data = {'urls': [{'url': U('/Rooms/'), 'status_code': 200}, {'url': U('/rooms/'), 'status_code': 200}],
            'links': [{'source_url': U('/'), 'target_url': U('/rooms/')}]}
    pages = {U('/rooms/'): pg('rooms')}
    out = sc.url_duplicates(pages, data, sc.hotel_mains(SITE, None), no_probe)
    assert [(x['url'], x['variant']) for x in out] == [(U('/rooms/'), U('/Rooms/'))]
    for u in data['urls']:
        u['canonical_url'] = U('/rooms/')
    assert sc.url_duplicates(pages, data, sc.hotel_mains(SITE, None), no_probe) == []


def test_url_variants_probed_live():
    assert sc.variants(U('/rooms/deluxe/')) == [U('/rooms/deluxe'), U('/Rooms/deluxe/')]
    pages = {U('/rooms/deluxe/'): pg('rooms')}
    answers = {U('/rooms/deluxe'): {'status': 200, 'canonical': ''},                     # duplicate
               U('/Rooms/deluxe/'): {'status': 200, 'canonical': U('/rooms/deluxe/')}}  # canonical to the page
    out = sc.url_duplicates(pages, {'urls': [], 'links': []}, sc.hotel_mains(SITE, None), answers.get)
    assert [(x['variant'], x['source']) for x in out] == [(U('/rooms/deluxe'), 'live request')]
    assert sc.variant_ok(U('/rooms/deluxe/'), U('/rooms/deluxe'), {'status': 301})
    assert sc.variant_ok(U('/rooms/deluxe/'), U('/rooms/deluxe'), {'status': 404})
    assert not sc.variant_ok(U('/rooms/deluxe/'), U('/rooms/deluxe'), {'status': 200, 'canonical': U('/rooms/deluxe')})


# ---------------------------------------------------------------- run(), report table, routing, schema

def _full_site():
    pages, data = _orphan_site()
    pages[U('/rooms/deluxe/')].update(headings=[[1, 'D'], [3, 'x']], body_links=4, generic_anchor_count=3,
                                      generic_anchors={'read more': 3}, og_image='')
    data['urls'].append({'url': U('/Rooms/'), 'status_code': 200, 'content_type': 'text/html'})
    return pages, data


def test_run_issues_have_registered_ids_and_rechecks():
    pages, data = _full_site()
    res = sc.run(pages, data, HOST, SITE, None, extra=[U('/old-page/')], image_status=ok_status, probe=no_probe)
    got = {i['check'] for i in res['issues']}
    assert {'orphan_key_page', 'orphan_page', 'heading_level_skipped', 'generic_anchor_text', 'link_preview_missing',
            'url_variant_duplicate'} <= got
    assert got <= set(report.CORE)
    for i in res['issues']:
        assert i['recheck']['type'] in checks.AUTO and i['recheck']['url']
    assert next(i for i in res['issues'] if i['check'] == 'orphan_key_page')['sev'] == 'Priority'
    assert res['report']['counts']['orphan_key_pages'] == 1


def test_every_new_check_is_in_the_report_table_and_registry():
    ids = ['orphan_key_page', 'orphan_page', 'key_page_too_deep', 'hreflang_incomplete', 'boilerplate_shared',
           'link_preview_missing', 'heading_level_skipped', 'heading_empty', 'generic_anchor_text',
           'url_variant_duplicate']
    reg = (paths.PLUGIN_DIR / 'skills' / 'hotel-seo' / 'references' / 'audit-checks.md').read_text(encoding='utf-8')
    for i in ids:
        cat, sev, title, fix, rk = report.CORE[i]
        assert cat in report.CHAPTER_ORDER and sev in report.SEV_RANK and title and fix and rk in checks.AUTO
        assert f'`{i}`' in reg, i


def test_core_findings_route_variants_to_web_and_carry_rechecks(tmp_path):
    pages, data = _full_site()
    res = sc.run(pages, data, HOST, SITE, None, image_status=ok_status, probe=no_probe)
    issues = [{'check': i['check'], 'url': i['url'], 'page_type': pages.get(i['url'], {}).get('type', 'other'),
               'severity': i['sev'] or 'Secondary', 'detail': i['detail'], 'recheck': i['recheck']}
              for i in res['issues']]
    (tmp_path / 'findings.json').write_text(json.dumps({'issues': issues}), encoding='utf-8')
    findings, chk = report.core_findings(str(tmp_path), None, 'hotel')
    by = {f['check']: f for f in findings}
    assert by['url_variant_duplicate']['owner'] == 'web'
    assert by['orphan_key_page']['owner'] == 'seo' and by['orphan_key_page']['severity'] == 'High'
    assert by['orphan_key_page']['checks'] == [{'type': 'inlinked', 'url': U('/rooms/hidden-suite/')}]
    assert {c['id'] for c in chk} >= {'core:orphan_page', 'core:boilerplate_shared'}


def test_new_check_types_validate_against_the_report_schema():
    import jsonschema
    schema = json.loads((paths.PLUGIN_DIR / 'skills' / 'hotel-seo' / 'templates' / 'report.schema.json')
                        .read_text(encoding='utf-8'))
    v = jsonschema.Draft7Validator(dict(schema['definitions']['check'] if 'definitions' in schema
                                        else schema['check'], **({'definitions': schema['definitions']}
                                                                 if 'definitions' in schema else {})))
    for c in [{'type': 'inlinked', 'url': '/x/'}, {'type': 'click_depth', 'url': '/x/', 'source': '/', 'expected': 3},
              {'type': 'hreflang_ok', 'url': '/x/', 'languages': ['ar', 'en'], 'x_default': True},
              {'type': 'og_present', 'url': '/x/'}, {'type': 'heading_levels', 'url': '/x/', 'what': 'empty'},
              {'type': 'generic_anchors_max', 'url': '/x/', 'expected': 0.25},
              {'type': 'variant_resolved', 'url': '/x/', 'source': '/X/'}]:
        assert not list(v.iter_errors(c)), c


# ---------------------------------------------------------------- live re-checks (fake site)

class Resp:
    def __init__(self, url, status=200, text='', headers=None, history=()):
        self.url, self.status_code, self.text = url, status, text
        self.headers = {'content-type': 'text/html'} | (headers or {})
        self.history = list(history)

    def close(self):
        pass


class Session:
    def __init__(self, site):
        self.site = site

    def get(self, url, allow_redirects=True, timeout=0, stream=False):
        return self.site.resp(url, allow_redirects)

    head = get


class FakeSite:
    """pages: path -> html; redirects: path -> target path; images: path -> status."""
    def __init__(self, pages, redirects=None, images=None):
        self.pages, self.redirects, self.images = pages, redirects or {}, images or {}
        self.site = SITE + '/'
        self.s = Session(self)

    def url(self, u):
        return urljoin(self.site, u)

    def resp(self, url, follow=True):
        path = '/' + url.split('://', 1)[-1].split('/', 1)[-1] if '://' in url else url
        if path in self.images:
            return Resp(url, self.images[path], headers={'content-type': 'image/jpeg'})
        if path in self.redirects:
            if not follow:
                return Resp(url, 301, headers={'Location': self.redirects[path]})
            r = self.resp(U(self.redirects[path]))
            r.history = [Resp(url, 301)]
            return r
        if path in self.pages:
            return Resp(url, 200, self.pages[path])
        return Resp(url, 404, 'not found')

    def get(self, u):
        r = self.resp(self.url(u))
        return r, BeautifulSoup(r.text, 'html.parser') if r.status_code == 200 else None


def _head(alts='', extra=''):
    links = ''.join(f'<link rel="alternate" hreflang="{c}" href="{SITE}{p}">' for c, p in alts)
    return f'<html><head>{links}{extra}</head><body>'


def test_live_recheck_types():
    en_ar = [('en', '/'), ('ar', '/ar/'), ('x-default', '/')]
    f = FakeSite({
        '/': _head(en_ar, '<meta property="og:title" content="Hotel"><meta property="og:image" content="/ok.jpg">')
             + '<a href="/rooms/">Rooms</a></body></html>',
        '/ar/': _head(en_ar) + '</body></html>',
        '/rooms/': _head() + '<a href="/rooms/deluxe/">Deluxe</a><h1>R</h1><h3>skip</h3></body></html>',
        '/rooms/deluxe/': _head() + '<a href="/rooms/a/">Read more</a><a href="/rooms/b/">Read more</a>'
                          '<a href="/rooms/c/">Read more</a><a href="/rooms/d/">Deluxe</a></body></html>',
        '/rooms/deluxe': _head() + '</body></html>',
    }, redirects={'/Rooms/': '/rooms/'}, images={'/ok.jpg': 200})
    run = lambda c, sw=('/',): checks.run_check(c, f, list(sw))                              # noqa: E731
    assert run({'type': 'hreflang_ok', 'url': '/', 'languages': ['ar', 'en'], 'x_default': True})['result'] == 'pass'
    assert run({'type': 'og_present', 'url': '/'})['result'] == 'pass'
    assert run({'type': 'og_present', 'url': '/ar/'})['result'] == 'fail'
    assert run({'type': 'inlinked', 'url': '/rooms/deluxe/'}, ['/', '/rooms/'])['result'] == 'pass'
    assert run({'type': 'inlinked', 'url': '/rooms/zzz/'}, ['/', '/rooms/'])['result'] == 'fail'
    assert run({'type': 'click_depth', 'url': '/rooms/deluxe/', 'source': '/', 'expected': 3})['result'] == 'pass'
    assert run({'type': 'click_depth', 'url': '/rooms/deluxe/', 'source': '/', 'expected': 1})['result'] == 'fail'
    assert run({'type': 'heading_levels', 'url': '/rooms/', 'what': 'skipped'})['result'] == 'fail'
    assert run({'type': 'heading_levels', 'url': '/rooms/', 'what': 'empty'})['result'] == 'pass'
    assert run({'type': 'generic_anchors_max', 'url': '/rooms/deluxe/', 'expected': 0.25})['result'] == 'fail'
    assert run({'type': 'generic_anchors_max', 'url': '/rooms/', 'expected': 0.25})['result'] == 'pass'
    assert run({'type': 'variant_resolved', 'url': '/rooms/', 'source': '/Rooms/'})['result'] == 'pass'
    assert run({'type': 'variant_resolved', 'url': '/rooms/deluxe/', 'source': '/rooms/deluxe'})['result'] == 'fail'
    for t in sc.LIVE:
        assert checks.describe({'type': t, 'url': '/x/', 'source': '/'})


def test_live_hreflang_fails_without_return_link():
    f = FakeSite({'/rooms/a/': _head([('en', '/rooms/a/'), ('ar', '/ar/rooms/a/')]) + '</body></html>',
                  '/ar/rooms/a/': _head() + '</body></html>'})
    r = checks.run_check({'type': 'hreflang_ok', 'url': '/rooms/a/'}, f, ['/'])
    assert r['result'] == 'fail' and 'does not link back' in r['actual']
