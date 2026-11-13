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
        return next(i for i, p in self.posts.items() if p.get('url') and execute._norm(p['url']) == execute._norm(url))

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
                                             'path': 'editor'}]})
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


def test_alt_text_goes_in_chunks_of_50():
    s = FakeMCP({})
    items = [{'id': f'a{i}', 'calls': [['update-media', {'items': [{'attachment_id': i, 'alt_text': f'alt {i}'}]}]]}
             for i in range(120)]
    sent = execute._send_media_chunks(s, items)
    assert len(sent) == 120 and [len(a['items']) for _, a in s.writes] == [50, 50, 20]


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
        dict(sec, number=3, title='Map embed', category='Local', finding_id='maps-embed', actions=[])]}
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
    assert 'Map embed' in titles and 'Alt text missing' not in titles and 'Group title template' not in titles
    ex = json.loads(Path(r['execute_report']).read_text(encoding='utf-8'))
    still = next(s for s in ex['sections'] if s['title'].startswith('Still to run'))
    rows = {row[0]: row[1] for row in still['blocks'][1]['table']['rows']}
    assert rows['Alt text missing'] == 'alt-text' and 'group run' in rows['Group title template']
    assert r['still_to_run'] == 2 and Path(r['out_dir']).parent.name == 'Reports'


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
