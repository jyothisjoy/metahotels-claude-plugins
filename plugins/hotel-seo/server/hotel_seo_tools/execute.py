"""/hotel-seo execute: apply a list's fixes to the live site through the hotel's own WordPress MCP tools, in batches the
user approves, and count an item done only when the live page shows it.

Ported from the Abar and Rose runs (handoff, Nov 2026) onto this plugin's lists. Python plans, gates, logs and
verifies; Claude makes the writes with the site's MCP tools (the server named after the site, e.g.
"abarhotels-content": seo-update-posts, redirects-create, elementor-update-element, update-media, ...).

  plan(list_json)                        dry run: every item turned into an action with its page, the new value and
                                         the checks that prove it; blockers (Yoast, approvals) found before anything runs
  start_batch(plan_file, batch, approved) the gate: refuses without the user's yes or, where the hotel requires it,
                                         the client's recorded approval; returns the items to write
  record_item(plan_file, item_id, ...)   the before value (for undo) and what was written
  verify_batch(plan_file, batch)         runs each item's checks on the live page: done, or "unverified" when the
                                         site accepted the write but the page doesn't show it; writes the indexing list
  record_client_approval(plan_file, by)  who approved and how; never inferred
  undo_steps(plan_file)                  the before values to write back, newest first
  resolve_post(site, url)                the post behind a full URL (never by slug alone: group sites share slugs)
  elementor_settings(element, text)      the settings key the widget really renders

Never: prices, offers, discounts or member benefits; anything [CONFIRM] or held for the hotel; Web Team items;
deleting posts, pages, media, users or menus; plugins and themes; another hotel's pages; Google Business Profile.
"""
import json
import re
from datetime import date, datetime
from urllib.parse import quote, urljoin, urlparse

import requests

from . import checks as chk, paths
from .librecrawl import UA

BATCH_ORDER = ['booking-path', 'seo-fields', 'redirects', 'text', 'links', 'alt-text', 'schema', 'manual']
BATCH_TOOL = {'seo-fields': 'seo-update-posts (read first with seo-get-posts)',
              'redirects': 'redirects-create (check redirects-list first)',
              'text': 'elementor-get-structure → elementor-update-element (or get-post → update-post for non-Elementor '
                      'content)',
              'links': 'elementor-get-structure → elementor-update-element (the link setting), or update-post',
              'booking-path': 'elementor-get-structure → elementor-update-element (button / link url)',
              'alt-text': 'update-media (find the attachment by its URL)',
              'schema': 'elementor-list-custom-code / elementor-set-custom-code, or Rank Math schema in wp-admin',
              'manual': 'Claude in Chrome in the user\'s logged-in browser, or leave it on the agency list'}
PRICE = re.compile(r'(?:AED|USD|EUR|SAR|EGP|\$|€)\s?\d|\d\s?(?:AED|USD|EUR|SAR|EGP|dirhams?)\b|\d+\s?%\s*(?:off|discount)'
                   r'|\b(?:discount|save)\s+\d+\s?%', re.I)
CHROME_HINTS = [(re.compile(r'rank ?math|seo title|meta description|sitemap|noindex', re.I), 'seo-update-posts / '
                 'seo-update-settings'),
                (re.compile(r'footer|header|template|tel:|phone', re.I), 'elementor-update-element'),
                (re.compile(r'\bH1\b|heading', re.I), 'elementor-update-element'),
                (re.compile(r'menu', re.I), 'update-menu-item'),
                (re.compile(r'redirect', re.I), 'redirects-create'),
                (re.compile(r'custom code|snippet|schema|json-ld', re.I), 'elementor-set-custom-code'),
                (re.compile(r'alt text|image', re.I), 'update-media'),
                (re.compile(r'block|gutenberg|post content', re.I), 'update-post')]
# The setting that holds a widget's visible text. Writing "title" to a text-editor widget "succeeds" and changes
# nothing on the page (Rose, Nov 2026: an H1 fix reported done; the re-check found 0 of 7).
WIDGET_TEXT_KEY = {'heading': 'title', 'text-editor': 'editor', 'button': 'text', 'icon-box': 'title_text',
                   'image-box': 'title_text', 'animated-headline': 'before_text', 'call-to-action': 'title'}
TEXT_KEYS = ('title', 'editor', 'text', 'title_text', 'description_text', 'heading', 'content')
SEO_FIELD = {'title': 'title', 'meta': 'description', 'canonical': 'canonical', 'noindex': 'robots'}
NOW_COL = re.compile(r'^(now|current|currently|old|was|before|live now)\b', re.I)
NEW_COL = re.compile(r'change to|new|replace with|should (?:read|be)|after|fix', re.I)
WHERE_COL = re.compile(r'^(where|page|url|on)\b', re.I)


def _now():
    return datetime.now().isoformat(timespec='seconds')


def _load(plan_file):
    pf = paths.resolve(plan_file)
    return pf, json.loads(pf.read_text(encoding='utf-8'))


def _save(pf, pl):
    pf.write_text(json.dumps(pl, indent=1, ensure_ascii=False), encoding='utf-8')


def _full(site, u):
    return urljoin(site.rstrip('/') + '/', u) if u else ''


def _seo_plugin(site):
    """The SEO plugin the site's REST API exposes: 'Rank Math', 'Yoast SEO', ... or ''."""
    try:
        r = requests.get(site.rstrip('/') + '/wp-json/', headers={'User-Agent': UA}, timeout=25)
        ns = r.json().get('namespaces', []) if r.status_code == 200 else []
    except (requests.RequestException, ValueError):
        return ''
    names = {'rankmath/v1': 'Rank Math', 'yoast/v1': 'Yoast SEO', 'aioseo/v1': 'All in One SEO',
             'seopress/v1': 'SEOPress'}
    return ', '.join(v for k, v in names.items() if k in ns)


def _live_h1(site, url):
    try:
        from bs4 import BeautifulSoup
        r = requests.get(_full(site, url), headers={'User-Agent': UA}, timeout=25)
        return [re.sub(r'\s+', ' ', h.get_text(' ')).strip() for h in BeautifulSoup(r.text, 'html.parser').find_all('h1')]
    except requests.RequestException:
        return []


def _blocked(text):
    if '[CONFIRM' in text or '[waiting' in text.lower():
        return 'has [CONFIRM] or waits for the hotel'
    if PRICE.search(text):
        return 'contains a price or discount: never written by execute'
    return ''


def _table_replacements(site, section):
    """Rows of a "Where | Now | Change to" table → (url, find, replace)."""
    out = []
    for b in section.get('blocks', []):
        (kind, val), = b.items()
        if kind != 'table':
            continue
        cols = [str(c) for c in val.get('columns', [])]
        wi = next((i for i, c in enumerate(cols) if WHERE_COL.search(c)), None)
        ni = next((i for i, c in enumerate(cols) if NOW_COL.search(c)), None)
        ci = next((i for i, c in enumerate(cols) if i != ni and NEW_COL.search(c)), None)
        if wi is None or ni is None or ci is None:
            continue
        for row in val.get('rows', []):
            if max(wi, ni, ci) >= len(row):
                continue
            m = chk.PATH_RE.search(str(row[wi]))
            path = (next((g for g in m.groups() if g), None) or m.group(0)) if m else ''
            raw = f'{row[ni]} {row[ci]}'
            find, repl = chk._plain(row[ni]), chk._plain(row[ci])
            if path and find and repl and repl.lower() not in ('keep', 'delete', 'remove'):
                out.append((_full(site, path), find, repl, raw))
    return out


def plan(list_json, out_dir=''):
    """Dry run. Nothing is written to the site."""
    src = paths.resolve(list_json)
    doc = json.loads(src.read_text(encoding='utf-8'))
    site = (doc.get('site') or '').rstrip('/')
    if not site:
        raise ValueError('The list has no "site"; add it and plan again.')
    domain_dir = src.parent.parent if src.parent.name in ('lists', 'Reports') else src.parent
    out = paths.resolve(out_dir) if out_dir else domain_dir / f'execute-{date.today().isoformat()}'
    out.mkdir(parents=True, exist_ok=True)
    hotel = {}
    if (domain_dir / 'hotel.json').exists():
        try:
            hotel = json.loads((domain_dir / 'hotel.json').read_text(encoding='utf-8'))
        except ValueError:
            pass
    prefs = hotel.get('preferences') or {}
    web_team = 'web team' in str(doc.get('title', '')).lower()
    items, skipped = [], []
    for s in doc.get('sections', []):
        sec = f"{s.get('number', '')} {s.get('title', '')}".strip()
        if web_team:
            skipped.append({'section': sec, 'why': 'Web Team list: developer work, not execute'})
            continue
        if s.get('hold'):
            skipped.append({'section': sec, 'why': f"held: {s['hold']}"})
            continue
        n = 0

        def add(batch, page, action, new, checks, note=''):
            nonlocal n
            why = _blocked(json.dumps(new, ensure_ascii=False))
            if why:
                skipped.append({'section': sec, 'page': page, 'why': why})
                return
            n += 1
            item = {'id': f"{s.get('number', 'x')}-{n}", 'section': sec, 'batch': batch, 'page': page,
                    'action': action, 'new': new, 'checks': checks, 'status': 'planned', 'tool': BATCH_TOOL[batch]}
            if note:
                item['note'] = note
            if batch == 'manual':
                for rx, tool in CHROME_HINTS:
                    if rx.search(sec + ' ' + json.dumps(new, ensure_ascii=False)):
                        item['try_first'] = {'tool': tool, 'note': 'the site tools can usually do this: read the current '
                                             'value, show the change, write after approval; Chrome only if they can\'t'}
                        break
            items.append(item)

        checks = s.get('checks', [])
        seo = {}
        for c in checks:
            t = c.get('type')
            if t in SEO_FIELD:
                url = _full(site, c.get('url', ''))
                v = c.get('expected')
                if t == 'noindex':
                    v = ['noindex'] if c.get('expected', True) else ['index']
                if t == 'canonical' and _full(site, str(v)).rstrip('/') == url.rstrip('/'):
                    v = ''          # self-canonical: an empty Rank Math field is the page itself
                seo.setdefault(url, ({}, []))
                seo[url][0][SEO_FIELD[t]] = v
                seo[url][1].append(c)
            elif t == 'redirect':
                add('redirects', _full(site, c['source']), 'redirect',
                    {'source': urlparse(_full(site, c['source'])).path, 'target': _full(site, c['expected']),
                     'code': 301}, [c])
            elif t == 'alt':
                add('alt-text', _full(site, c.get('url', '')), 'alt_text',
                    {'image': c.get('image'), 'alt': c.get('expected')}, [c])
            elif t == 'h1':
                url = _full(site, c.get('url', ''))
                now = _live_h1(site, url)
                add('text', url, 'h1', {'find': now[0] if now else '', 'replace': c.get('expected'),
                                        'all_h1_now': now},
                    [c], 'Elementor heading widget: key "title". If no Elementor element holds it, the H1 is the post '
                         'title (update-post title) or the theme template (manual).')
        for url, (fields, cs) in seo.items():
            add('seo-fields', url, 'seo_fields', fields, cs)
        # text replacements from "Where | Now | Change to" tables, proven by text_present / text_absent checks
        for url, find, repl, raw in _table_replacements(site, s):
            cs = [c for c in checks if c.get('type') in ('text_present', 'text_absent')
                  and _full(site, c.get('url', '')).rstrip('/') == url.rstrip('/')]
            why = _blocked(raw)
            if why:
                skipped.append({'section': sec, 'page': url, 'why': why})
                continue
            add('text', url, 'text_replace', {'find': find, 'replace': repl}, cs)
        # link swaps: a link_absent and a link_present on the same page
        by_url = {}
        for c in checks:
            if c.get('type') in ('link_absent', 'link_present') and c.get('url') != 'sitewide':
                by_url.setdefault(_full(site, c.get('url', '')), {})[c['type']] = c
        for url, pair in by_url.items():
            if 'link_absent' in pair and 'link_present' in pair:
                new_href = pair['link_present'].get('href', '')
                batch = 'booking-path' if re.search(r'idtokenprovider|mirai|book', new_href, re.I) else 'links'
                add(batch, url, 'link_replace', {'old_href': pair['link_absent'].get('href', ''), 'new_href': new_href},
                    list(pair.values()))
        planned = {json.dumps(c, sort_keys=True) for it in items for c in it['checks']}
        rest = [c for c in checks if json.dumps(c, sort_keys=True) not in planned and c.get('type') != 'manual']
        schema = [c for c in rest if c.get('type') in ('schema_block_equals', 'schema_count')]
        if schema:
            add('schema', ', '.join(sorted({_full(site, c.get('url', '')) for c in schema})), 'schema',
                {'blocks': [c.get('expected') for c in schema if c.get('type') == 'schema_block_equals'],
                 'counts': [{k: c.get(k) for k in ('url', 'schema_type', 'expected')} for c in schema
                            if c.get('type') == 'schema_count']}, schema)
        other = [c for c in rest if c not in schema]
        if other or not checks:
            add('manual', ', '.join(sorted({_full(site, c.get('url') or c.get('source') or '') for c in other})) or site,
                'manual', {'steps': f"section {sec}: follow the list's own steps",
                           'checks': [{k: c.get(k) for k in ('type', 'url', 'text', 'expected', 'href') if c.get(k)}
                                      for c in other]}, other)
    seo_plugin = _seo_plugin(site)
    blockers = []
    if any(i['batch'] == 'seo-fields' for i in items) and seo_plugin and 'Rank Math' not in seo_plugin:
        blockers.append({'batch': 'seo-fields', 'why': f'the site runs {seo_plugin}, not Rank Math: the site tools write '
                         'Rank Math fields, and Yoast meta keys are protected in the WordPress MCP. Fix first: allow-list '
                         'the Yoast keys in the MCP plugin, or do these in wp-admin with Claude in Chrome (Abar/Rose, '
                         'Nov 2026: every title/meta write was skipped mid-run)'})
    batches = {b: [i['id'] for i in items if i['batch'] == b] for b in BATCH_ORDER}
    pl = {'site': site, 'hotel': doc.get('hotel'), 'list': str(src), 'list_title': f"{doc.get('title', '')} "
          f"({doc.get('date', '')})", 'planned': _now(), 'seo_plugin': seo_plugin or 'unknown',
          'client_approval_required': bool(prefs.get('client_approval')), 'client_approval': None,
          'units': prefs.get('units'), 'blockers': blockers, 'skipped': skipped,
          'batches': {b: ids for b, ids in batches.items() if ids}, 'items': items, 'log': []}
    pf = out / 'plan.json'
    _save(pf, pl)
    return {'plan_file': str(pf), 'blockers': blockers, 'client_approval_required': pl['client_approval_required'],
            'batches': {b: len(v) for b, v in pl['batches'].items()}, 'skipped': skipped,
            'tables': {b: [[i['id'], i['page'], i['action'], json.dumps(i['new'], ensure_ascii=False)[:160]]
                           for i in items if i['batch'] == b] for b in pl['batches']},
            'next': 'Show each batch as a table (page, field, now → new) and ask. Only on a clear yes: '
                    'start_batch(plan_file, batch, approved=true).'}


def record_client_approval(plan_file, by, note=''):
    """The client's yes to this change list: who and how ("Mr Yunus, email 6 Nov"). Never inferred."""
    if not str(by).strip():
        raise ValueError('say who approved and how, e.g. "Mr Yunus, email 6 Nov"')
    pf, pl = _load(plan_file)
    pl['client_approval'] = {'by': by, 'note': note, 'recorded': _now()}
    pl['log'].append({'at': _now(), 'event': 'client_approval', 'by': by, 'note': note})
    _save(pf, pl)
    return {'recorded': True, 'by': by}


def start_batch(plan_file, batch, approved=False):
    """The gate before any write. approved=True only after the user said yes to this batch's table."""
    pf, pl = _load(plan_file)
    if not approved:
        raise PermissionError('Show the batch table to the user and pass approved=true only after they approve it.')
    if pl.get('client_approval_required') and not pl.get('client_approval'):
        raise PermissionError('This hotel approves every change before it goes live. Send the client the change list, '
                              'then record_client_approval(plan_file, by="<name>, <channel> <date>") once the user '
                              'confirms their yes.')
    block = [b for b in pl.get('blockers', []) if b['batch'] == batch]
    if block:
        raise PermissionError(block[0]['why'])
    ids = pl['batches'].get(batch)
    if not ids:
        raise LookupError(f'no batch {batch} in the plan; batches: {list(pl["batches"])}')
    pl['log'].append({'at': _now(), 'event': 'batch_approved', 'batch': batch})
    _save(pf, pl)
    items = [i for i in pl['items'] if i['id'] in ids and i['status'] in ('planned', 'failed', 'unverified')]
    return {'batch': batch, 'site': pl['site'], 'tool': BATCH_TOOL[batch], 'items': items,
            'how': ['Use the site\'s own MCP server (named after the domain, e.g. "abarhotels-content").',
                    'Find each post by its full URL with resolve_post (never by slug alone).',
                    'Read the current value first; record_item(plan_file, id, before=<current>, ...) BEFORE writing.',
                    'Elementor: elementor_settings(element, new_text) gives the key the widget really renders.',
                    'Then write, record_item(..., after=<written>, written=true), purge the cache, and '
                    'verify_batch(plan_file, batch). Stop at the first error and tell the user.']}


def record_item(plan_file, item_id, before=None, after=None, written=False, post_id=None, element_id=None,
                tool='', note=''):
    """Log one item: its before value (for undo) and what was written. Call with before= ahead of the write."""
    pf, pl = _load(plan_file)
    it = next((i for i in pl['items'] if i['id'] == item_id), None)
    if not it:
        raise LookupError(f'no item {item_id}')
    if before is not None and 'before' not in it:
        it['before'] = before
    for k, v in (('post_id', post_id), ('element_id', element_id), ('tool_used', tool), ('note', note)):
        if v:
            it[k] = v
    if after is not None:
        it['after'] = after
    if written:
        it['status'] = 'written'
        it['written_at'] = _now()
    elif note and after is None and before is None:
        it['status'] = 'failed'
    pl['log'].append({'at': _now(), 'event': 'item', 'id': item_id, 'written': written, 'note': note})
    _save(pf, pl)
    return {'id': item_id, 'status': it['status']}


def verify_batch(plan_file, batch):
    """Each written item's checks on the live page. Done only when the page shows it; "unverified" when the site
    accepted the write but the page doesn't (wrong widget key, template override, cache)."""
    pf, pl = _load(plan_file)
    f = chk.Fetcher(pl['site'])
    rows, changed = [], []
    for it in pl['items']:
        if it['batch'] != batch or it['status'] not in ('written', 'unverified', 'done'):
            continue
        res = [{'check': chk.describe(c), **chk.run_check(c, f, [])} for c in it['checks']]
        auto = [r for r in res if r['result'] != 'manual']
        ok = bool(auto) and all(r['result'] == 'pass' for r in auto)
        it['status'] = 'done' if ok else ('written' if not auto else 'unverified')
        it['verified'] = {'at': _now(), 'checks': res}
        rows.append({'id': it['id'], 'page': it['page'], 'status': it['status'],
                     'failing': [r for r in auto if r['result'] != 'pass']})
        if ok and it['page'].startswith('http'):
            changed.append(it['page'])
    if changed:
        ed = pf.parent
        prop = 'sc-domain:' + urlparse(pl['site']).netloc.replace('www.', '')
        f_idx = ed / 'indexing-requests.md'
        lines = [] if f_idx.exists() else [f"# Request indexing: {pl.get('hotel')} · execute", '',
                                           'One link per changed page: open it (signed in to Search Console) and click '
                                           '**Request indexing** once. Google\'s API can\'t request indexing.', '']
        done_before = f_idx.read_text(encoding='utf-8') if f_idx.exists() else ''
        for u in dict.fromkeys(changed):
            if u in done_before:
                continue
            lines.append(f'- [ ] {u}  \n  https://search.google.com/search-console/inspect?resource_id='
                         f'{quote(prop, safe="")}&id={quote(u, safe="")}')
        with open(f_idx, 'a', encoding='utf-8') as fh:
            fh.write('\n'.join(lines) + '\n')
    pl['log'].append({'at': _now(), 'event': 'verified', 'batch': batch,
                      'done': sum(r['status'] == 'done' for r in rows)})
    _save(pf, pl)
    return {'batch': batch, 'items': rows, 'done': sum(r['status'] == 'done' for r in rows),
            'unverified': [r for r in rows if r['status'] == 'unverified'],
            'indexing_requests': str(pf.parent / 'indexing-requests.md') if changed else None,
            'note': 'An unverified item is NOT done: read the element / template, find why the page doesn\'t show it, '
                    'fix and verify again. Never report it as done.'}


def undo_steps(plan_file):
    """The writes to reverse, newest first, with the before values recorded ahead of each write. Redirects created by
    the run are deleted; nothing else is deleted."""
    _, pl = _load(plan_file)
    done = [i for i in pl['items'] if i['status'] in ('written', 'done', 'unverified')]
    done.sort(key=lambda i: i.get('written_at', ''), reverse=True)
    out = []
    for i in done:
        if i['action'] == 'redirect':
            out.append({'id': i['id'], 'do': 'redirects-delete the rule this run created', 'rule': i['new']})
        elif 'before' in i:
            out.append({'id': i['id'], 'page': i['page'], 'post_id': i.get('post_id'), 'element_id': i.get('element_id'),
                        'tool': i.get('tool_used') or i['tool'], 'write_back': i['before']})
        else:
            out.append({'id': i['id'], 'page': i['page'], 'do': 'no before value recorded: restore by hand'})
    return {'site': pl['site'], 'steps': out}


def resolve_post(site, url):
    """The WordPress post behind a full URL. A slug alone is not enough on a group site, where every hotel has
    /about-us/ and /rooms/ (Rose, Nov 2026: about 130 changes aimed at the wrong page). Asks the public REST API
    for every post with the last slug and keeps the one whose link matches the full path; two matches is an error.
    Post types not in REST (some custom room types) return not_found: then use the site tools' get-post / list-posts
    and compare the link the same way."""
    site = site.rstrip('/')
    want = urlparse(_full(site, url)).path.rstrip('/') + '/'
    slug = want.strip('/').split('/')[-1] if want.strip('/') else ''
    s = requests.Session()
    s.headers['User-Agent'] = UA
    if not slug:
        return {'url': url, 'front_page': True, 'note': 'the homepage: use the site settings / front page id'}
    try:
        types = s.get(site + '/wp-json/wp/v2/types', timeout=25).json()
        bases = sorted({t.get('rest_base') for t in types.values() if isinstance(t, dict) and t.get('rest_base')}
                       - {'media', 'attachment', 'wp_block', 'wp_template', 'wp_template_part', 'wp_navigation',
                          'wp_global_styles', 'wp_font_family', 'wp_font_face', 'menu-items', 'blocks'})
    except (requests.RequestException, ValueError, AttributeError):
        bases = ['pages', 'posts']
    hits = []
    for b in bases:
        rows, page = [], 1
        while page <= 10:                     # a group site can have dozens of posts with one slug
            try:
                r = s.get(f'{site}/wp-json/wp/v2/{b}', params={'slug': slug, '_fields': 'id,link,type,status',
                                                               'per_page': 100, 'page': page}, timeout=25)
                got = r.json() if r.status_code == 200 else []
            except (requests.RequestException, ValueError):
                break
            if not isinstance(got, list) or not got:
                break
            rows += got
            if len(got) < 100:
                break
            page += 1
        for p in rows:
            if urlparse(p.get('link', '')).path.rstrip('/') + '/' == want:
                hits.append({'post_id': p['id'], 'type': p.get('type') or b, 'link': p.get('link')})
    if len(hits) > 1:
        return {'url': url, 'error': f'{len(hits)} posts have the path {want}: resolve by hand', 'matches': hits}
    if not hits:
        return {'url': url, 'not_found': True, 'note': f'no public post with the path {want} (the type may not be in '
                'REST): use the site tools (list-posts / get-post) and compare the full link'}
    return {'url': url, **hits[0]}


def elementor_settings(element, new_text, key=''):
    """Settings for elementor-update-element that the widget really renders: heading → title, text-editor → editor
    (wrapped in <p>), button → text, icon-box / image-box → title_text; an unknown widget uses its only text key.
    element: one element from elementor-get-structure (with settings)."""
    have = element.get('settings') or {}
    wtype = element.get('widgetType') or element.get('widget_type') or ''
    want = WIDGET_TEXT_KEY.get(wtype)
    if not want:
        present = [k for k in TEXT_KEYS if isinstance(have.get(k), str) and have.get(k)]
        want = present[0] if len(present) == 1 else None
    if key and want and key != want and key not in have:
        key = want
    key = key or want
    if not key:
        return {'error': f'widget "{wtype}" has no single text key ({[k for k in TEXT_KEYS if k in have]}): '
                         'pick it by reading the element'}
    v = new_text
    if key == 'editor' and isinstance(v, str) and not v.lstrip().startswith('<'):
        v = f'<p>{v}</p>'
    return {'widget': wtype, 'settings': {key: v}, 'before': {key: have.get(key)}}
