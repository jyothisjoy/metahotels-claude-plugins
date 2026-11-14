"""execute: schema code never lands on the page as text, text replacements go through find-text / replace-text
(pages, Elementor templates, snippets, menus), Elementor pages are never written through post_content, alt text goes
in chunks, the review sheet feeds the business-profile batch, and the Agency Fix List keeps only agency work.
No site or Google calls."""
import json
from pathlib import Path

import pytest

from hotel_seo_tools import execute, execute_report, gbp, gbp_reviews, gbp_write, group, paths


# ---------------------------------------------------------------- schema code

HOTEL = {'@context': 'https://schema.org', '@type': 'Hotel', 'name': 'Example </script><b>x</b>'}


def _data(code):
    body = code.split('>', 1)[1].rsplit('</script>', 1)[0]
    return json.loads(body)


CLEAN = {'@context': 'https://schema.org', '@type': 'Hotel', 'name': 'Example'}


def test_schema_code_wraps_bare_json_and_objects():
    for given in (json.dumps(HOTEL), HOTEL, [HOTEL]):
        code = execute.schema_code(given)
        assert code.startswith('<script type="application/ld+json">') and code.endswith('</script>')
        assert code.count('</script>') == 1                     # a value can't close the tag early
        assert _data(code) in (HOTEL, [HOTEL])
    code = execute.schema_code('<script type="application/ld+json">' + json.dumps(CLEAN) + '</script>')
    assert _data(code) == CLEAN
    # a "</script>" inside an existing block already breaks it on the page: refused, not passed on
    with pytest.raises(ValueError):
        execute.schema_code('<script type="application/ld+json">' + json.dumps(HOTEL) + '</script>')


def test_schema_code_keeps_several_blocks():
    two = ('<script type="application/ld+json">' + json.dumps(CLEAN) + '</script>\n<!-- org -->\n'
           "<script type='application/ld+json'>" + json.dumps({'@context': 'https://schema.org',
                                                               '@type': 'Organization'}) + '</script>')
    assert execute.schema_code(two).count('<script type="application/ld+json">') == 2


@pytest.mark.parametrize('bad, why', [
    ('{"@context": "https://schema.org", "@type": "Hotel",}', 'invalid JSON-LD'),
    ('<script type="application/ld+json">{"@context": "https://schema.org"}</script> Hotel facts', 'outside'),
    ('<div>{"@context": "https://schema.org"}</div>', 'HTML'),
    ('{"@type": "Hotel", "name": "x"}', '@context'),
    ('', 'empty'),
])
def test_schema_code_refuses_what_would_print_on_the_page(bad, why):
    with pytest.raises(ValueError, match=why):
        execute.schema_code(bad)


def test_no_jsonld_in_page_text():
    execute.no_jsonld('<p>Rooms with a view of the creek.</p>', 'x')
    for bad in ('<p>{"@context": "https://schema.org", "@type": "Hotel"}</p>',
                '<script type="application/ld+json">{}</script>', {'editor': '"@type": "FAQPage"'}):
        with pytest.raises(ValueError, match='JSON-LD'):
            execute.no_jsonld(bad, 'the content')


# ---------------------------------------------------------------- a fake site MCP

class FakeMCP(execute.Site):
    """posts: {id: {title, url, post_type, shared?, text}}; elements: {post_id: [flat elements]}."""
    def __init__(self, posts, elements=None, single=True, hotel_paths=(), tools=None, elementor_pages=()):
        self.site = 'https://example-hotels.com'
        self.tools = set(tools or {'find-text', 'replace-text', 'elementor-get-structure', 'elementor-update-element',
                                   'get-post', 'update-post', 'update-media', 'elementor-set-custom-code'})
        self.posts, self.elements, self.elementor_pages = posts, elements or {}, set(elementor_pages)
        self.single, self.hotel_paths = single, list(hotel_paths)
        self._ids, self.types, self.writes = {}, {}, []

    def post_id(self, url):
        hit = next((i for i, p in self.posts.items() if p.get('url') and execute._norm(p['url']) == execute._norm(url)),
                   None)
        if hit is None:
            raise LookupError(f'no post found for {url}')            # as execute.Site.post_id
        return hit

    def read(self, tool, args):
        if tool == 'find-text':
            out = []
            for i, p in self.posts.items():
                if args['find'] in p.get('text', '') or (args.get('match_mode') == 'phone' and
                                                          args['find'].replace(' ', '') in p.get('text', '').replace(' ', '')):
                    out.append({'post_id': i, 'post_type': p.get('post_type', 'page'), 'title': p['title'],
                                **({'url': p['url']} if p.get('url') else {}),
                                **({'shared': p['shared']} if p.get('shared') else {}),
                                'matches': [{'field': 'elementor', 'element_id': p.get('el', 'e1'),
                                             'setting': 'editor'}]})       # as Meta MCP 1.7 names it
            return {'success': True, 'posts': out, 'more': False}
        if tool == 'elementor-get-structure':
            els = self.elements.get(args['post_id'], [])
            if args.get('search'):
                els = [e for e in els if args['search'].lower() in json.dumps(e.get('settings')).lower()]
            return {'elements': els}
        if tool == 'get-post':
            return {'post': {'id': args['post_id'], 'content': '<p>old</p>',
                             **({'elementor': {'element_count': 4}} if args['post_id'] in self.elementor_pages else {})}}
        raise AssertionError(tool)

    def write(self, tool, args):
        self.writes.append((tool, args))
        if tool == 'replace-text':
            return {'success': True, 'dry_run': bool(args.get('dry_run')), 'would_replace': 1, 'total_matches': 1,
                    'posts': [], 'failed': [], 'more': False}
        return {'success': True}


POSTS = {
    10: {'title': 'Deluxe Room', 'url': '/rooms/deluxe/', 'text': 'The Deluxe Room is 32 m². Call +971 4 111 2222'},
    11: {'title': 'Contact', 'url': '/contact/', 'text': 'Call us on +971 4 111 2222'},
    20: {'title': 'Header', 'post_type': 'elementor_library', 'shared': 'Elementor template: shows on every page.',
         'text': 'Reservations +971 4 111 2222', 'el': 'h1'},
    30: {'title': 'Other Hotel Contact', 'url': '/other-hotel/contact/', 'text': 'Call +971 4 111 2222'},
}


def test_text_replace_page_level_goes_through_replace_text():
    s = FakeMCP({k: POSTS[k] for k in (10, 11)})
    it = execute._resolve(s, {'type': 'text_replace', 'url': '/rooms/deluxe/', 'find': '32 m²', 'replace': '35 m²'}, [])
    (tool, args), = it['calls']
    assert tool == 'replace-text' and args['post_ids'] == [10] and args['replace'] == '35 m²'
    assert it['undo'] == [['replace-text', {'find': '35 m²', 'replace': '32 m²', 'match_mode': 'exact',
                                            'post_ids': [10], 'max_posts': 1}]]
    v = execute._validate_calls(s, it['calls'])
    assert v['ok'] and s.writes[-1][1]['dry_run'] is True


def test_phone_sitewide_on_single_site_includes_shared_template():
    s = FakeMCP({k: POSTS[k] for k in (10, 11, 20)})
    c = {'type': 'text_replace', 'url': '/rooms/deluxe/', 'find': '+971 4 111 2222', 'replace': '+971 4 999 8888',
         'match_mode': 'phone', 'sitewide': True, 'pages': ['/rooms/deluxe/', '/contact/']}
    it = execute._resolve(s, c, [])
    args = it['calls'][0][1]
    assert args['post_ids'] == [10, 11, 20] and args['match_mode'] == 'phone' and it['shared'] == ['Header']
    assert it['undo'][0][1]['match_mode'] == 'phone' and it['undo'][0][1]['find'] == '+971 4 999 8888'


def test_group_site_splits_shared_templates_and_leaves_other_hotels_alone():
    s = FakeMCP(dict(POSTS), single=False, hotel_paths=['/rooms/', '/contact/'])
    c = {'type': 'text_replace', 'url': '/contact/', 'find': '+971 4 111 2222', 'replace': '+971 4 999 8888',
         'match_mode': 'phone', 'sitewide': True}
    parts = execute._split(execute._resolve(s, c, []))
    assert [p['calls'][0][1]['post_ids'] for p in parts] == [[10, 11], [20]]
    assert 'batch_override' not in parts[0] and parts[1]['batch_override'] == 'group'
    assert all(30 not in p['post_ids'] for p in parts)


def test_text_not_found_says_so():
    s = FakeMCP({11: POSTS[11]})
    with pytest.raises(LookupError, match='not found'):
        execute._resolve(s, {'type': 'text_replace', 'url': '/contact/', 'find': 'Dubai Marina', 'replace': 'x'}, [])


def test_without_replace_text_phone_is_one_item_per_page():
    s = FakeMCP({}, tools={'get-post', 'update-post'})
    c = {'type': 'text_replace', 'url': '/a/', 'find': '+971 4 111 2222', 'replace': '+971 4 999 8888',
         'match_mode': 'phone', 'sitewide': True, 'pages': ['/a/', '/b/'], 'finds': {'/b/': '04 111 2222'},
         'question': 'F1', 'why': 'x'}
    out = execute._expand_corrections([c], s)
    assert [(x['url'], x['find']) for x in out] == [('/a/', '+971 4 111 2222'), ('/b/', '04 111 2222')]
    assert all('pages' not in x and 'match_mode' not in x for x in out)


def test_elementor_text_found_in_template_when_not_on_page():
    els = {20: [{'id': 'h1', 'widget_type': 'heading', 'settings': {'title': 'Book direct and save'}}]}
    s = FakeMCP({10: POSTS[10], 20: dict(POSTS[20], text='Book direct and save')}, elements=els)
    it = execute._resolve(s, {'type': 'elementor_text', 'url': '/rooms/deluxe/', 'find': 'Book direct and save',
                              'settings': {'title': 'Book direct'}}, [])
    assert it['calls'] == [['elementor-update-element', {'post_id': 20, 'element_id': 'h1',
                                                         'settings': {'title': 'Book direct'}}]]
    assert 'template' in it['page'] and 'batch_override' not in it
    s.single = False
    assert execute._resolve(s, {'type': 'elementor_text', 'url': '/rooms/deluxe/', 'find': 'Book direct and save',
                                'settings': {'title': 'Book direct'}}, [])['batch_override'] == 'group'


def test_post_content_on_elementor_page_writes_the_text_widget():
    els = {10: [{'id': 'h', 'widget_type': 'heading', 'settings': {'title': 'Deluxe'}},
                {'id': 't', 'widget_type': 'text-editor', 'settings': {'editor': '<p>Short.</p>'}}]}
    s = FakeMCP({10: POSTS[10]}, elements=els, elementor_pages={10})
    it = execute._resolve(s, {'type': 'post_content', 'url': '/rooms/deluxe/', 'content': 'A longer text.'}, [])
    assert it['calls'] == [['elementor-update-element', {'post_id': 10, 'element_id': 't',
                                                         'settings': {'editor': '<p>A longer text.</p>'}}]]
    assert it['undo'][0][1]['settings'] == {'editor': '<p>Short.</p>'}
    els[10].append({'id': 't2', 'widget_type': 'text-editor', 'settings': {'editor': '<p>More.</p>'}})
    with pytest.raises(LookupError, match='2 text widgets'):
        execute._resolve(s, {'type': 'post_content', 'url': '/rooms/deluxe/', 'content': 'x'}, [])
    plain = FakeMCP({10: POSTS[10]})
    it = execute._resolve(plain, {'type': 'post_content', 'url': '/rooms/deluxe/', 'content': 'x'}, [])
    assert it['calls'][0][0] == 'update-post'                      # not an Elementor page: post content as before
    with pytest.raises(ValueError, match='JSON-LD'):
        execute._resolve(plain, {'type': 'post_content', 'url': '/rooms/deluxe/',
                                 'content': '{"@context": "https://schema.org"}'}, [])


def test_schema_snippet_is_normalised_and_rechecked():
    s = FakeMCP({10: POSTS[10]})
    it = execute._resolve(s, {'type': 'schema_snippet', 'title': 'Hotel schema', 'code': json.dumps(HOTEL),
                              'conditions': ['page:/rooms/deluxe/']}, [])
    args = it['calls'][0][1]
    assert args['code'].startswith('<script type="application/ld+json">') and args['location'] == 'elementor_head'
    assert args['conditions'] == ['include/singular/page/10'] and it['check_urls'] == ['/rooms/deluxe/']
    checks = execute._schema_checks(it['check_urls'])
    assert {c['type'] for c in checks} == {'jsonld_valid', 'text_absent'}
    with pytest.raises(ValueError):
        execute._resolve(s, {'type': 'schema_snippet', 'title': 'x', 'code': '{"@type": "Hotel"', 'conditions': []}, [])


def test_visible_text_check_catches_dumped_json():
    from bs4 import BeautifulSoup
    from hotel_seo_tools import checks
    ok = BeautifulSoup('<head><script type="application/ld+json">{"@context": "https://schema.org"}</script></head>'
                       '<body><p>Welcome</p></body>', 'html.parser')
    dumped = BeautifulSoup('<body><p>{"@context": "https://schema.org", "@type": "Hotel"}</p></body>', 'html.parser')
    assert '"@context"' not in checks._haystack(ok, 'visible')
    assert '"@context"' in checks._haystack(dumped, 'visible')


def test_alt_text_goes_in_chunks_of_50_and_reads_each_result():
    s = FakeMCP({})

    def write(tool, args):
        s.writes.append((tool, args))
        res = [{'success': False, 'error': 'no attachment'} if x['attachment_id'] == 7 else {'success': True}
               for x in args['items']]
        return {'success': True, 'results': res, 'failed': sum(not r['success'] for r in res)}
    s.write = write
    items = [{'id': f'a{i}', 'calls': [['update-media', {'items': [{'attachment_id': i, 'alt_text': f'alt {i}'}]}]]}
             for i in range(120)]
    sent, refused = execute._send_media_chunks(s, items)
    assert [len(a['items']) for _, a in s.writes] == [50, 50, 20]
    assert len(sent) == 119 and refused == {'a7': 'update-media: no attachment'}     # not logged as done
    with pytest.raises(RuntimeError, match='no attachment'):
        execute._write_call(s, 'update-media', {'items': [{'attachment_id': 7, 'alt_text': 'x'}]})


def test_image_in_widget_html_gets_its_alt_in_the_tag(monkeypatch):
    src = 'https://example-hotels.com/wp-content/uploads/pool-deck-1024x683.jpg'
    tag = f'<img class="w" src="{src}" alt="">'
    els = {10: [{'id': 'e1', 'widget_type': 'text-editor', 'settings': {'editor': f'<p>Pool</p>{tag}'}}]}
    s = FakeMCP({10: dict(POSTS[10], text=tag, el='e1')}, elements=els)
    monkeypatch.setattr(execute, '_media', lambda site, url: (None, None))
    it = execute._resolve(s, {'type': 'alt_text', 'image': src, 'alt': 'Pool deck with sun loungers at "Example"'}, [])
    (tool, args), = it['calls']
    assert tool == 'replace-text' and args['find'] == tag and args['post_ids'] == [10]
    assert args['replace'] == tag.replace('alt=""', 'alt="Pool deck with sun loungers at &quot;Example&quot;"')
    assert it['undo'][0][1]['find'] == args['replace']
    assert execute._with_alt('<img src="x.jpg">', 'A') == '<img alt="A" src="x.jpg">'


# ---------------------------------------------------------------- report folders and the Agency Fix List

def test_reports_dir_is_dated(tmp_path, monkeypatch):
    monkeypatch.setenv('HOTEL_SEO_HOME', str(tmp_path))
    h = tmp_path / 'site' / 'hotels' / 'ex'
    assert paths.reports_dir(h, '2026-11-13') == h / 'Reports' / '2026-11-13'
    assert paths.reports_dir(h / 'Reports', '2026-11-13') == h / 'Reports' / '2026-11-13'
    assert paths.reports_dir(h / 'Reports' / '2026-11-01') == h / 'Reports' / '2026-11-01'
    assert paths.owner_dir(h / 'Reports' / '2026-11-13') == h and paths.owner_dir(h / 'Reports') == h


def test_file_numbers_count_dated_folders(tmp_path, monkeypatch):
    monkeypatch.setenv('HOTEL_SEO_HOME', str(tmp_path))
    from hotel_seo_tools import pdf
    d = paths.reports_dir(tmp_path / 'a', '2026-11-01')
    d.mkdir(parents=True)
    (d / '41 - Example Audit Report (1 Nov).pdf').write_bytes(b'%PDF')
    assert pdf.next_file_number() == 42


@pytest.fixture
def site(tmp_path, monkeypatch):
    monkeypatch.setenv('HOTEL_SEO_HOME', str(tmp_path))
    group.save('example-hotels.com', {'name': 'Example', 'site': 'https://example-hotels.com/'},
               [{'slug': 'ex', 'name': 'Example Hotel Apartments', 'paths': ['/'], 'city': 'Dubai'}])
    d = tmp_path / 'example-hotels.com'
    run = d / 'audit-2026-11-10'
    run.mkdir(parents=True)
    sec = {'severity': 'Medium', 'owner': 'seo', 'checks': [], 'blocks': [{'p': '**Fix:** do it.'}]}
    rep = {'title': 'Audit Report', 'hotel': 'Example', 'sections': [
        dict(sec, number=1, title='Alt text missing', category='Images', finding_id='img-alt',
             actions=[{'type': 'alt_text', 'image': '/a.jpg', 'alt': 'Pool'}]),
        dict(sec, number=2, title='Group title template', category='Technical', finding_id='rm-titles',
             actions=[{'type': 'rankmath_setting', 'group': 'titles', 'settings': {'x': 1}}]),
        dict(sec, number=3, title='Map embed', category='Local', finding_id='maps-embed', actions=[]),
        dict(sec, number=4, title='Slider caption', category='Content', finding_id='slider', actions=[],
             manual='the caption is set inside Slider Revolution, which no MCP tool reaches'),
        dict(sec, number=5, title='OTA listings', category='Local', finding_id='ota', actions=[], owner='metahotels')]}
    (run / 'audit-report.json').write_text(json.dumps(rep), encoding='utf-8')
    return d, run


def test_agency_list_keeps_only_agency_work(site):
    d, run = site
    ed = d / 'execute-2026-11-11'
    ed.mkdir()
    plan = {'site': 'https://example-hotels.com/', 'hotel': 'ex', 'source_run': str(run), 'approved': [], 'done': [],
            'recheck': {}, 'batches': {'alt-text': [{'id': 'a1', 'finding': 'img-alt', 'batch': 'alt-text',
                                                     'action': {'type': 'alt_text', 'image': '/a.jpg', 'alt': 'Pool'}}]},
            'skipped': [{'finding': 'rm-titles', 'action': 'rankmath_setting',
                         'reason': 'group-wide: runs only in the group batch (execute without --hotel)'}]}
    (ed / 'plan.json').write_text(json.dumps(plan), encoding='utf-8')
    r = execute_report.build('example-hotels.com', 'ex')
    ag = json.loads(Path(r['agency_fix_list']).read_text(encoding='utf-8'))
    titles = [s.get('title') for s in ag['sections']]
    assert titles == ['Content', 'Slider caption']           # only what no tool can reach; never the other four
    ex_ = json.loads(Path(r['execute_report']).read_text(encoding='utf-8'))
    out = next(s for s in ex_['sections'] if s['title'].startswith('Outside the website'))
    assert out['blocks'][1]['table']['rows'][0][0] == 'OTA listings'
    ex = json.loads(Path(r['execute_report']).read_text(encoding='utf-8'))
    still = next(s for s in ex['sections'] if s['title'].startswith('Still to run'))
    rows = {row[0]: row[1] for row in still['blocks'][1]['table']['rows']}
    assert rows['Alt text missing'] == 'alt-text' and 'group run' in rows['Group title template']
    assert 'add its execute action' in rows['Map embed']
    assert r['still_to_run'] == 3 and Path(r['out_dir']).parent.name == 'Reports'


def test_agency_schema_step_shows_wrapped_code():
    steps = execute_report.steps_for({'type': 'schema_snippet', 'code': json.dumps(HOTEL), 'conditions': ['x']})
    assert '<script type="application/ld+json">' in steps[1]
    assert 'not valid' in execute_report.steps_for({'type': 'schema_snippet', 'code': '{bad', 'conditions': []})[0]


# ---------------------------------------------------------------- Business Profile

def test_gbp_description_refused_on_hotel_profiles():
    with pytest.raises(ValueError, match='hotel profiles'):
        execute._gbp_change({'type': 'gbp', 'field': 'description', 'value': 'x'})


def test_review_sheet_rows_join_the_business_profile_batch(site, monkeypatch, tmp_path):
    d, _ = site
    hdir = d
    (hdir / 'gbp').mkdir()
    drafts = hdir / 'gbp' / 'review-replies-2026-11-11.json'
    reply = 'Thank you, Sara. We are glad the pool and the reception team looked after you.'
    drafts.write_text(json.dumps({'hotel': 'Example Hotel Apartments', 'location': 'locations/1', 'created': '2026-11-11',
                                  'replies': [{'review_id': 'r1', 'stars': 5, 'language': 'en', 'first_name': 'Sara',
                                               'reviewer': 'Sara Ahmed', 'comment': 'Lovely pool.', 'reply': reply},
                                              {'review_id': 'r4', 'stars': 1, 'language': 'ar', 'first_name': 'Omar',
                                               'comment': 'الغرفة كانت متسخة', 'check_with_user_first': True,
                                               'reply': 'نعتذر عن تجربتك.'}]}), encoding='utf-8')
    x = gbp_reviews.write_sheet(drafts)
    assert [r['review_id'] for r in gbp_reviews.read_sheet(x)['replies']] == ['r1']     # 1 star starts as "No"
    monkeypatch.setattr(execute, 'Site', lambda site: FakeMCP({}))
    monkeypatch.setattr(gbp, 'configured', lambda: (True, ''))
    monkeypatch.setattr(gbp, 'hotel_location', lambda g, s: {'location': 'locations/1'})
    proposed = []

    def propose(location, changes, out_dir='', allow_risky=False):
        proposed.append(changes)
        f = Path(out_dir) / 'c.json'
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({'id': 'abc', 'ops': [{'kind': 'reviews', 'rows': [['reply', '', 'x']]}]}))
        return {'checked': True, 'change_id': 'abc', 'change_file': str(f)}
    monkeypatch.setattr(gbp_write, 'propose', propose)
    r = execute.plan('example-hotels.com', 'ex', only=['gbp-review-replies'])
    pl = json.loads(Path(r['plan_file']).read_text(encoding='utf-8'))
    it, = pl['batches'][execute.GBP_BATCH]
    assert it['gbp_key'] == 'review_replies' and proposed == [{'review_replies': [{'review_id': 'r1', 'reply': reply}]}]

    def apply(change_file, confirm):
        return {'checked': True, 'status': 'applied', 'results': [{'result': 'sent'}]}
    monkeypatch.setattr(gbp_write, 'apply', apply)
    execute.run_batch(r['plan_file'], execute.GBP_BATCH, approved=True)
    from openpyxl import load_workbook
    ws = load_workbook(x)['Replies']
    head = [c.value for c in ws[1]]
    assert ws.cell(row=2, column=head.index('Status') + 1).value.startswith('Posted')
    assert gbp_reviews.read_sheet(x)['replies'] == []


# ---------------------------------------------------------------- the alt-text worklist

from hotel_seo_tools import alt_text  # noqa: E402


def test_image_key_joins_copies():
    k = alt_text.image_key
    assert k('https://x.com/up/pool-1024x683.jpg?v=2') == k('https://x.com/up/pool.jpg') == \
        k('https://x.com/up/pool-scaled.jpg')
    assert k('https://x.com/up/pool.jpg.webp') == k('https://x.com/up/pool.jpg') != k('https://x.com/up/pool2.jpg')


def test_alt_lint():
    ok, warn = alt_text.lint('Rooftop pool with sun loungers at Example Hotel', 'Example Hotel Apartments')
    assert ok == [] and warn == []
    for bad in ('Image of the pool at Example', 'IMG_2034 pool Example',
                'Pool deck, pool, hotel pool, Dubai pool, best pool Example', 'Pool from AED 99 at Example', 'x' * 130):
        assert alt_text.lint(bad, 'Example Hotel')[0], bad
    assert alt_text.lint('Pool at sunset', 'Example Hotel Apartments')[1]          # no hotel name: a warning


@pytest.fixture
def alt_site(site):
    d, run = site
    crawl = d / 'crawl-2026-11-10'
    crawl.mkdir()
    rows = [('https://example-hotels.com/', 'https://example-hotels.com/up/pool-1024x683.jpg'),
            ('https://example-hotels.com/rooms/', 'https://example-hotels.com/up/pool.jpg.webp'),
            ('https://example-hotels.com/rooms/', 'https://example-hotels.com/up/twin.jpg'),
            ('https://example-hotels.com/', 'https://example-hotels.com/up/divider.png')]
    with open(crawl / 'images_missing_alt.csv', 'w', encoding='utf-8', newline='') as fh:
        fh.write('page_url,image_src,alt_state\n' + ''.join(f'{p},{i},no alt attribute\n' for p, i in rows))
    (crawl / 'findings.json').write_text(json.dumps({'pages': {'https://example-hotels.com/rooms/': {
        'title': 'Rooms', 'h1': ['Rooms and apartments']}}}), encoding='utf-8')
    rep = json.loads((run / 'audit-report.json').read_text(encoding='utf-8'))
    rep['sections'].append({'number': 9, 'title': 'Images without alt text', 'severity': 'Medium', 'category': 'Images',
                            'owner': 'seo', 'finding_id': 'core-images-missing-alt', 'blocks': [], 'actions': [],
                            'checks': [{'type': 'alt_present', 'url': '/', 'image': 'pool-1024x683.jpg'}]})
    (run / 'audit-report.json').write_text(json.dumps(rep), encoding='utf-8')
    return d, run


def test_worklist_fill_check_writes_actions(alt_site):
    d, run = alt_site
    r = alt_text.worklist('example-hotels.com', 'ex', download=False)
    assert r['images'] == 3 and r['image_tags'] == 4 and r['remaining'] == 3
    doc = json.loads(Path(r['file']).read_text(encoding='utf-8'))
    pool = next(i for i in doc['images'] if 'pool' in i['key'])
    assert len(pool['pages']) == 2 and pool['variants']
    twin = next(i for i in doc['images'] if 'twin' in i['key'])
    assert twin['context'][0]['h1'] == 'Rooms and apartments'
    ids = {('pool' if 'pool' in i['key'] else 'twin' if 'twin' in i['key'] else 'div'): i['id'] for i in doc['images']}
    b = alt_text.batch(r['file'], 2)
    assert len(b['images']) == 2 and b['remaining'] == 3
    alt_text.fill(r['file'], {ids['pool']: 'Rooftop pool with sun loungers at Example Hotel',
                              ids['twin']: 'Rooftop pool with sun loungers at Example Hotel'})
    chk = alt_text.check(r['file'])
    assert any('same alt' in p for p in chk['problems']) and 'applied' not in chk
    alt_text.fill(r['file'], {ids['twin']: 'Twin room with two single beds and a desk at Example Hotel',
                              ids['div']: {'decorative': True}})
    chk = alt_text.check(r['file'])
    assert chk['problems'] == [] and chk['remaining'] == 0 and chk['applied'] and chk['actions'] == 2
    rep = json.loads((run / 'audit-report.json').read_text(encoding='utf-8'))
    sec = next(s for s in rep['sections'] if s['finding_id'] == 'core-images-missing-alt')
    assert {a['alt'] for a in sec['actions']} == {'Rooftop pool with sun loungers at Example Hotel',
                                                  'Twin room with two single beds and a desk at Example Hotel'}
    assert {c['url'] for c in sec['checks']} == {'https://example-hotels.com/', 'https://example-hotels.com/rooms/'}
    again = alt_text.worklist('example-hotels.com', 'ex', download=False)          # same day: alt kept
    assert again['remaining'] == 0


def test_refused_image_goes_to_agency_with_its_alt(alt_site):
    d, run = alt_site
    ed = d / 'execute-2026-11-11'
    ed.mkdir()
    act = {'type': 'alt_text', 'image': 'https://example-hotels.com/up/slider.jpg', 'alt': 'Lobby at Example Hotel',
           'pages': ['/']}
    plan = {'site': 'https://example-hotels.com/', 'hotel': 'ex', 'source_run': str(run),
            'approved': [{'batch': 'alt-text'}], 'done': [], 'recheck': {}, 'skipped': [],
            'batches': {'alt-text': [{'id': 'a1', 'finding': 'core-images-missing-alt', 'batch': 'alt-text',
                                      'action': act}]},
            'failed': [{'id': 'a1', 'finding': 'core-images-missing-alt', 'batch': 'alt-text',
                        'error': 'update-media: no attachment'}]}
    (ed / 'plan.json').write_text(json.dumps(plan), encoding='utf-8')
    r = execute_report.build('example-hotels.com', 'ex')
    ag = json.dumps(json.loads(Path(r['agency_fix_list']).read_text(encoding='utf-8')), ensure_ascii=False)
    assert 'Lobby at Example Hotel' in ag and 'slider.jpg' in ag


# ---------------------------------------------------------------- redirects: Redirection or Rank Math

def test_created_redirect_ids_from_rule_objects():
    assert execute._created_ids([{'created': [{'id': 4, 'source': '/a/'}, {'id': 5}], 'provider': 'rank_math'}]) == [4, 5]
    assert execute._created_ids([{'ids': [7], 'created': [{'id': 7}]}]) == [7]


def test_redirects_writable_with_rank_math_only():
    s = FakeMCP({})
    s.integrations = {'site_tools': {'redirection': {'active': False}, 'rank_math_redirections': {'active': True}}}
    assert execute._redirects_writable(s)
    s.integrations = {'site_tools': {'redirection': {'active': False}}}           # Meta MCP before 1.7, Rank Math only
    assert not execute._redirects_writable(s)
    s.integrations = {}
    assert execute._redirects_writable(s)                                         # unknown: let the site answer


def test_find_text_and_resolve_url_are_read_tools():
    from hotel_seo_tools import sites
    for t in ('find-text', 'mcp-adapter-find-text', 'resolve-url', 'list-media', 'elementor-get-structure'):
        assert sites.is_read_tool(t), t
    for t in ('replace-text', 'update-media', 'elementor-update-element', 'redirects-create'):
        assert not sites.is_read_tool(t), t


# ---------------------------------------------------------------- map widget, tel: links, prices, translations

def test_map_widget_location_set_by_widget_type():
    els = {11: [{'id': 'm1', 'widget_type': 'google_maps', 'settings': {'address': 'Al Nakheel Hotel, RAK', 'zoom': 14}},
                {'id': 't1', 'widget_type': 'text-editor', 'settings': {'editor': '<p>Find us</p>'}}]}
    s = FakeMCP({11: POSTS[11]}, elements=els)
    it = execute._resolve(s, {'type': 'elementor_widget', 'url': '/contact/', 'widget_type': 'google_maps',
                              'settings': {'address': '25.5719418, 56.3435306'}}, [])
    assert it['calls'] == [['elementor-update-element', {'post_id': 11, 'element_id': 'm1',
                                                         'settings': {'address': '25.5719418, 56.3435306'}}]]
    assert it['undo'][0][1]['settings'] == {'address': 'Al Nakheel Hotel, RAK'}
    els[11].append({'id': 'm2', 'widget_type': 'google_maps', 'settings': {'address': 'Dubai office'}})
    with pytest.raises(LookupError, match='2 google_maps'):
        execute._resolve(s, {'type': 'elementor_widget', 'url': '/contact/', 'widget_type': 'google_maps',
                             'settings': {'address': 'x'}}, [])
    it = execute._resolve(s, {'type': 'elementor_widget', 'url': '/contact/', 'widget_type': 'google_maps',
                              'find': 'nakheel', 'settings': {'address': 'x'}}, [])
    assert it['calls'][0][1]['element_id'] == 'm1'


def test_link_phone_wraps_only_plain_text():
    html_in = ('<p>Call +971 7 228 2222 or <a href="tel:+97172282222">+971 7 228 2222</a>.</p>'
               '<img alt="+971 7 228 2222" src="x.jpg"> Fax 04 111 9999')
    out, n = execute.link_phone(html_in, '+971 7 228 2222')
    assert n == 1 and out.count('href="tel:+97172282222"') == 2
    assert '<a href="tel:+97172282222">+971 7 228 2222</a> or' in out and 'Fax 04 111 9999' in out
    assert execute.tel_href('00971 7 228 2222') == 'tel:+97172282222'


def test_phone_link_never_touches_schema_and_links_widgets():
    text = 'Reservations +971 7 228 2222'
    posts = {10: dict(POSTS[10], text=text, el='t1'), 20: dict(POSTS[20], text=text, el='b1')}
    els = {10: [{'id': 't1', 'widget_type': 'text-editor', 'settings': {'editor': f'<p>{text}</p>'}}],
           20: [{'id': 'b1', 'widget_type': 'button', 'settings': {'text': '+971 7 228 2222', 'link': {'url': ''}}}]}
    s = FakeMCP(posts, elements=els)
    asked = []
    orig = s.read

    def read(tool, args):
        if tool == 'find-text':
            asked.append(args)
            out = orig(tool, args)
            for p in out['posts']:
                p['matches'] = [{'field': 'elementor', 'element_id': posts[p['post_id']]['el'],
                                 'setting': 'editor' if p['post_id'] == 10 else 'text'}]
            return out
        return orig(tool, args)
    s.read = read
    it = execute._resolve(s, {'type': 'phone_link', 'phone': '+971 7 228 2222'}, [])
    assert asked[0]['fields'] == ['elementor', 'content'] and asked[0]['match_mode'] == 'phone'   # no custom_code
    by = {c[1]['element_id']: c[1]['settings'] for c in it['calls']}
    assert by['t1']['editor'] == '<p>Reservations <a href="tel:+97172282222">+971 7 228 2222</a></p>'
    assert by['b1'] == {'link': {'url': 'tel:+97172282222'}}
    assert {u[1]['element_id'] for u in it['undo']} == {'t1', 'b1'}


def test_price_guard_checks_only_the_new_text():
    a_remove = {'type': 'text_replace', 'url': '/faq/', 'find': 'Rates from 400–1600 AED a night.', 'replace': ''}
    a_write = {'type': 'text_replace', 'url': '/faq/', 'find': 'Ask us for rates.', 'replace': 'From AED 400.'}
    assert not execute.PRICE.search(execute._new_text(a_remove)) and execute.PRICE.search(execute._payload_text(a_remove))
    assert execute.PRICE.search(execute._new_text(a_write))


def test_schema_condition_falls_back_to_url(monkeypatch):
    s = FakeMCP({10: POSTS[10]})
    it = execute._resolve(s, {'type': 'schema_snippet', 'title': 'AR room', 'code': json.dumps(HOTEL),
                              'conditions': ['page:/ar/rooms/deluxe/']}, [])
    assert it['calls'][0][1]['conditions'] == ['include:/ar/rooms/deluxe/']


def test_translations_noted_for_text_changes():
    s = FakeMCP({10: POSTS[10]})
    s.tools.add('polylang-get-post-translations')
    orig = s.read
    s.read = lambda tool, args: ({'translations': {'en': {'id': 10, 'link': '/rooms/deluxe/'},
                                                    'ar': {'id': 40, 'link': '/ar/rooms/deluxe/'},
                                                    'ru': {'id': 41, 'link': '/ru/rooms/deluxe/'}}}
                                 if tool == 'polylang-get-post-translations' else orig(tool, args))
    it = {'action': {'type': 'text_replace'}, 'post_id': 10, 'batch': 'elementor-text'}
    execute._note_translations(s, it)
    assert it['translations'] == {'ar': '/ar/rooms/deluxe/', 'ru': '/ru/rooms/deluxe/'}


# ---------------------------------------------------------------- fewer agency items (Shams Alam, 14 Nov)

def test_core_actions_for_code_checks():
    from hotel_seo_tools import report
    fj = {'pages': {
        'https://x.com/': {'type': 'home', 'og_image': 'https://x.com/og.jpg', 'title': 'Home'},
        'https://x.com/dining/': {'title': 'Dining | X', 'h1': ['Dining'],
                                  'generic_links': [['view more', 'https://x.com/beach-bar/']]},
        'https://x.com/beach-bar/': {'title': 'The Beach Bar | X', 'h1': ['The Beach Bar']},
        'https://x.com/contact/': {'title': 'Contact Shams Alam'}}}
    heads = report.core_actions('heading_level_skipped', [
        {'url': 'https://x.com/room/', 'detail': 'H1 → H3 ("Room Detail"), H2 → H4 ("Description")'}], fj)
    assert heads == [{'type': 'heading_level', 'url': 'https://x.com/room/', 'find': 'Room Detail', 'level': 2},
                     {'type': 'heading_level', 'url': 'https://x.com/room/', 'find': 'Description', 'level': 3}]
    links = report.core_actions('generic_anchor_text', [{'url': 'https://x.com/dining/', 'detail': ''}], fj)
    assert links == [{'type': 'link_text', 'url': 'https://x.com/dining/', 'href': 'https://x.com/beach-bar/',
                      'find': 'view more', 'new_text': 'The Beach Bar'}]
    og = report.core_actions('link_preview_missing', [{'url': 'https://x.com/contact/', 'detail': 'no og:image'}], fj)
    assert og == [{'type': 'seo_fields', 'url': 'https://x.com/contact/',
                   'fields': {'facebook_image': 'https://x.com/og.jpg'}}]


def test_generic_links_keep_their_target():
    from bs4 import BeautifulSoup
    from hotel_seo_tools import site_checks
    soup = BeautifulSoup('<main><a href="/beach-bar/">View more</a><a href="/rooms/">Our rooms</a></main>', 'html.parser')
    st = site_checks.anchor_stats(soup, 'https://x.com/dining/', 'x.com')
    assert st['generic_links'] == [['View more', 'https://x.com/beach-bar/']]


def test_heading_level_sets_the_tag_setting_not_the_text():
    els = {10: [{'id': 'h', 'widget_type': 'heading', 'settings': {'title': 'Room Detail', 'header_size': 'h3'}},
                {'id': 'b', 'widget_type': 'icon-box', 'settings': {'title_text': 'Description'}}]}
    s = FakeMCP({10: POSTS[10]}, elements=els)
    it = execute._resolve(s, {'type': 'heading_level', 'url': '/rooms/deluxe/', 'find': 'Room Detail', 'level': 2}, [])
    assert it['calls'][0][1]['settings'] == {'header_size': 'h2'} and it['undo'][0][1]['settings'] == {'header_size': 'h3'}
    it = execute._resolve(s, {'type': 'heading_level', 'url': '/rooms/deluxe/', 'find': 'Description', 'level': 3}, [])
    assert it['calls'][0][1]['settings'] == {'title_size': 'h3'}
    # the old one-key remap would have written "h2" into the heading text
    assert execute._rendered_settings(els[10][0], {'header_size': 'h2'}) == {'header_size': 'h2'}


def test_link_text_on_page_and_in_loop_template():
    els = {11: [{'id': 'btn', 'widget_type': 'button',
                 'settings': {'text': 'View more', 'link': {'url': 'https://example-hotels.com/beach-bar/'}}},
                {'id': 'btn2', 'widget_type': 'button',
                 'settings': {'text': 'View more', 'link': {'url': 'https://example-hotels.com/spa/'}}}]}
    s = FakeMCP({11: POSTS[11]}, elements=els)
    it = execute._resolve(s, {'type': 'link_text', 'url': '/contact/', 'href': 'https://example-hotels.com/beach-bar/',
                              'find': 'view more', 'new_text': 'The Beach Bar'}, [])
    assert it['calls'] == [['elementor-update-element', {'post_id': 11, 'element_id': 'btn',
                                                         'settings': {'text': 'The Beach Bar'}}]]
    loop = {'title': 'Restaurant card', 'post_type': 'elementor_library', 'shared': 'template', 'text': 'view more',
            'el': 'lb', 'template_type': 'loop-item'}
    els2 = {11: [], 50: [{'id': 'lb', 'widget_type': 'button', 'settings': {'text': 'view more'}}]}
    s2 = FakeMCP({11: POSTS[11], 50: loop}, elements=els2)
    orig = s2.read

    def read(tool, args):
        out = orig(tool, args)
        if tool == 'find-text':
            for p_ in out['posts']:
                if p_['post_id'] == 50:
                    p_['template_type'] = 'loop-item'
                    p_['matches'][0]['setting'] = 'text'
        return out
    s2.read = read
    it = execute._resolve(s2, {'type': 'link_text', 'url': '/contact/', 'href': 'https://example-hotels.com/x/',
                               'find': 'view more', 'new_text': 'X'}, [])
    dyn = it['calls'][0][1]['settings']['__dynamic__']['text']
    assert it['post_id'] == 50 and 'name="post-title"' in dyn


def test_insert_text_goes_under_the_h1_and_undoes_by_deleting():
    els = {10: [{'id': 'h1', 'widget_type': 'heading', 'el_type': 'widget',
                 'settings': {'title': 'Superior Room', 'header_size': 'h1'}},
                {'id': 't', 'widget_type': 'text-editor', 'el_type': 'widget', 'settings': {'editor': '<p>Amenities</p>'}}]}
    s = FakeMCP({10: dict(POSTS[10], text='Superior Room')}, elements=els, elementor_pages={10})
    it = execute._resolve(s, {'type': 'insert_text', 'url': '/rooms/deluxe/',
                              'text': 'The Superior Room is a 20 m² beachfront room.'}, [])
    (tool, args), = it['calls']
    assert tool == 'elementor-insert-element' and args['anchor_id'] == 'h1' and args['position'] == 'after'
    assert args['element'] == {'widgetType': 'text-editor',
                               'settings': {'editor': '<p>The Superior Room is a 20 m² beachfront room.</p>'}}
    assert it['undo'] == 'delete-inserted'
    it = execute._resolve(s, {'type': 'insert_text', 'url': '/rooms/deluxe/', 'anchor': 'Amenities', 'position': 'before',
                              'html': '<p>Lead.</p>'}, [])
    assert it['calls'][0][1]['anchor_id'] == 't' and it['calls'][0][1]['position'] == 'before'
    with pytest.raises(LookupError, match='already on the page'):
        execute._resolve(s, {'type': 'insert_text', 'url': '/rooms/deluxe/', 'text': 'Superior Room'}, [])


def test_same_change_from_two_findings_runs_once(site, monkeypatch):
    d, run = site
    act = {'type': 'text_replace', 'url': 'https://example-hotels.com/rooms/deluxe/', 'find': '32 m²', 'replace': '20 m²'}
    rep = json.loads((run / 'audit-report.json').read_text(encoding='utf-8'))
    base = {'severity': 'High', 'owner': 'seo', 'checks': [], 'blocks': [{'p': '**Fix:** 20 m².'}]}
    rep['sections'] = [dict(base, number=1, title='Size conflict', category='AI Search', finding_id='ai-size', actions=[act]),
                       dict(base, number=2, title='Size vs engine', category='Booking path & facts',
                            finding_id='booking-size', actions=[dict(act)])]
    (run / 'audit-report.json').write_text(json.dumps(rep), encoding='utf-8')
    monkeypatch.setattr(execute, 'Site', lambda site: FakeMCP({10: POSTS[10]}))
    r = execute.plan('example-hotels.com', 'ex')
    pl = json.loads(Path(r['plan_file']).read_text(encoding='utf-8'))
    planned = [i for b in pl['batches'].values() for i in b]
    assert len(planned) == 1 and planned[0]['finding'] == 'ai-size'
    dup, = [x for x in pl['skipped'] if x.get('same_as')]
    assert dup['finding'] == 'booking-size' and dup['same_as']['id'] == planned[0]['id']
    pl['done'] = [planned[0]['id']]
    pl['recheck'] = {'ai-size': {'status': 'Done'}}
    Path(r['plan_file']).write_text(json.dumps(pl), encoding='utf-8')
    out = execute_report.build('example-hotels.com', 'ex', r['plan_file'])
    ag = json.loads(Path(out['agency_fix_list']).read_text(encoding='utf-8'))
    assert [s.get('title') for s in ag['sections']] == ['Nothing left']
