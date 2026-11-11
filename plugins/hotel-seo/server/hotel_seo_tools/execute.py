"""/hotel-seo execute: apply the audit's fixes to the live site through its WordPress MCP, in approved batches.

  plan(group_dir, slug)        dry run: every action resolved to a post id, its current value read, the new value
                               shown; nothing written. Writes hotels/<slug>/execute-<date>/plan.json.
  run_batch(plan_file, batch)  runs ONE batch the user approved: before-values saved, tool called, stop at the
                               first error, cache purged, each finding re-checked on the live site.
  undo(plan_file)              writes the before-values back (redirects created by the run are deleted; created
                               pages go back to draft, never deleted).
  record_client_approval(...)  the client's yes, for hotels whose hotel.json says preferences.client_approval: true
                               (no batch runs until it is recorded).

Never: prices / offers / discounts / member benefits, anything [CONFIRM] or on hold, Web Team items, deleting posts,
pages, media, users or menus, plugins / themes, other hotels' pages.
Google Business Profile: "gbp" actions (and a website link the latest gbp_report flags) become the hotel's own
"business-profile" batch: one gbp_write proposal per field (description, website with the team UTM tags, phone, hours,
special hours, additional categories, attributes; never name, address or primary category), sent with gbp_write.apply
when the user approves the batch, logged in changes.json like site changes, undone by proposing the logged "before"
values (which the user approves again). A hotel without a linked profile (gbp_link) gets no such batch.
Group-wide changes (Rank Math settings, shared templates, sitewide snippets) only run in the group batch, from an
execute without --hotel. Chrome steps are listed for Claude in Chrome and approved like any batch.
"""
import html
import json
import re
import time
from collections import defaultdict
from datetime import date
from urllib.parse import urlparse

import requests

from . import checks as chk, group as grp, paths, sites
from .librecrawl import UA

BATCH_ORDER = ['booking-path', 'hotel-answers', 'seo-fields', 'redirects', 'elementor-text', 'schema', 'alt-text', 'post-status',
               'menus', 'new-pages', 'chrome', 'site-settings', 'business-profile', 'group']
TYPE_BATCH = {'seo_fields': 'seo-fields', 'redirect': 'redirects', 'elementor_text': 'elementor-text',
              'schema_snippet': 'schema', 'alt_text': 'alt-text', 'post_status': 'post-status',
              'post_content': 'elementor-text', 'menu': 'menus', 'page_create': 'new-pages', 'chrome': 'chrome',
              'rankmath_setting': 'group', 'text_replace': 'hotel-answers'}
NEEDS_TOOL = {'seo_fields': 'seo-update-posts', 'redirect': 'redirects-create', 'alt_text': 'update-media',
              'elementor_text': 'elementor-update-element', 'schema_snippet': 'elementor-set-custom-code',
              'rankmath_setting': 'seo-update-settings', 'post_status': 'set-post-status',
              'post_content': 'update-post', 'menu': 'update-menu-item', 'page_create': 'create-post'}
PRICE = re.compile(r'(?:AED|USD|EUR|SAR|EGP|\$|€)\s?\d|\d\s?(?:AED|USD|EUR|SAR|EGP|dirhams?)\b|\d+\s?%\s*(?:off|discount)'
                   r'|\b(?:discount|save)\s+\d+\s?%', re.I)


def _norm(u):
    p = urlparse(u if '//' in u else 'https://x' + u)
    return (p.path or '/').rstrip('/') + '/'


def _payload_text(a):
    return json.dumps({k: v for k, v in a.items() if k not in ('type',)}, ensure_ascii=False)


class Site:
    """One site's MCP connection with a post-id resolver (cached)."""

    def __init__(self, site):
        self.site = site.rstrip('/')
        st = sites.status(self.site)
        if not st.get('connected'):
            raise ConnectionError(st.get('reason') or 'cannot connect')
        self.tools = set(st.get('read_tools', []) + st.get('write_tools', []))
        integ = st.get('integrations') or {}
        wp = integ.get('wordpress', {}) if isinstance(integ, dict) else {}
        self.post_types = [t for t in wp.get('post_types', []) if t not in (
            'attachment', 'wp_block', 'wp_template', 'wp_template_part', 'wp_navigation', 'wp_font_family',
            'wp_font_face', 'elementor_library', 'elementor_snippet', 'e-floating-buttons')] or ['page', 'post']
        self.integrations = integ
        self._ids = {}
        self.types = {}

    def read(self, tool, args):
        r = sites.call(self.site, tool, args)
        if r.get('is_error'):
            raise RuntimeError(f'{tool}: {r.get("text", "")[:300]}')
        return r.get('structured') or {}

    def write(self, tool, args):
        r = sites.call(self.site, tool, args, _write_ok=True)
        if r.get('is_error'):
            raise RuntimeError(f'{tool}: {r.get("text", "")[:300]}')
        return r.get('structured') or {}

    def post_id(self, url):
        key = _norm(url)
        if key in self._ids:
            return self._ids[key]
        if key == '/':
            try:
                s = self.read('get-site-settings', {})
                pid = (s.get('settings') or s).get('page_on_front') or (s.get('reading') or {}).get('page_on_front')
                if pid:
                    self._ids[key] = int(pid)
                    return int(pid)
            except Exception:  # noqa: BLE001
                pass
        slug = key.strip('/').split('/')[-1]
        no_link = []
        for pt in self.post_types:
            try:
                d = self.read('get-post', {'slug': slug, 'post_type': pt, 'include_content': False,
                                           'include_elementor': False, 'include_terms': False})
            except Exception:  # noqa: BLE001
                continue
            post = d.get('post') or d
            link = post.get('link') or post.get('permalink') or ''
            if post.get('id') and link and _norm(link) == key:
                self._ids[key] = int(post['id'])
                self.types[key] = pt
                return int(post['id'])
            if post.get('id') and not link:
                no_link.append((int(post['id']), pt))
        # A slug alone is not enough on a group site, where every hotel has /about-us/ and /rooms/ (Rose, Nov 2026:
        # about 130 changes aimed at the wrong page): match the full path through the public REST API.
        rest = resolve_post(self.site, url)
        if rest.get('error'):
            raise LookupError(rest['error'])
        if rest.get('post_id'):
            self._ids[key] = int(rest['post_id'])
            self.types[key] = rest.get('type') or ''
            return int(rest['post_id'])
        if len(no_link) == 1 and rest.get('not_found'):
            # the MCP gave no link and the type isn't in REST: the only candidate (as before)
            self._ids[key], self.types[key] = no_link[0]
            return no_link[0][0]
        raise LookupError(f'no post found for {url}')


def _latest(d, prefix):
    found = sorted((p for p in d.glob(prefix + '*') if p.is_dir()), key=lambda p: p.name)
    return found[-1] if found else None


QREF = re.compile(r'\[CONFIRM ([QRDFB]\d+)')


def _answer_state(qid, item, text):
    """yes / no / value / waiting for one question the action depends on."""
    from . import questions as qm
    a = (item or {}).get('answer') or {}
    if not a:
        return 'waiting'
    if item['sheet'] == 'Questions':
        return qm.classify(a.get('answer'))

    def nums(rx):
        return [qm._num(m.group(1)) for m in rx.finditer(text)]
    if item['sheet'] == 'Rooms':
        # compare only the kind of fact the text states: sizes with the size, guest numbers with the guests
        sizes, guests = nums(qm.SIZE), nums(re.compile(r'(\d+)\s*(?:guests?|people|persons|adults)', re.I))
        size = qm._num(a.get('size_m2'))
        adults, kids = qm._num(a.get('max_adults')), qm._num(a.get('max_children')) or 0
        ok_size = not sizes or (size is not None and all(x == size for x in sizes))
        ok_guests = not guests or (adults is not None and all(x in (adults, adults + kids) for x in guests))
        beds = str(a.get('beds') or '').lower()
        stated = sizes or guests or (beds and beds in text.lower())
        return 'yes' if stated and ok_size and ok_guests else 'value'
    if item['sheet'] == 'Distances':
        km = nums(re.compile(r'(\d+(?:\.\d+)?)\s?(?:km|kilomet)', re.I))
        want = qm._num(a.get('road_km'))
        return 'yes' if km and want is not None and all(x == want for x in km) else 'value'
    v = str(a.get('value') or '').strip().lower()
    return 'yes' if v and v in text.lower() else 'value'


def _strip_confirmed(obj, ids):
    if isinstance(obj, dict):
        return {k: _strip_confirmed(v, ids) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_strip_confirmed(v, ids) for v in obj]
    if isinstance(obj, str) and '[CONFIRM' in obj:
        return re.sub(r'\s{2,}', ' ', re.sub(r'\s?\[CONFIRM (' + '|'.join(map(re.escape, ids)) + r')\b[^\]]*\]', '', obj))
    return obj


def _hotel_gate(text, answers, hold_q=None):
    """(ok, reason, confirmed_ids, rewording) for an action given the hotel's answers."""
    ids = list(dict.fromkeys(QREF.findall(text)))
    if hold_q:
        ids.append(hold_q)
    if '[CONFIRM' in text and not QREF.search(text):
        return False, 'contains [CONFIRM] with no question number: run hotel_questions', [], None
    states = {i: _answer_state(i, answers.get(i), text) for i in ids}
    wait = [i for i, st in states.items() if st == 'waiting']
    no = [i for i, st in states.items() if st == 'no']
    val = [i for i, st in states.items() if st == 'value']
    if wait:
        return False, f"waiting for the hotel ({', '.join(wait)})", [], None
    if no:
        return False, f"the hotel said no ({', '.join(no)})", [], None
    if val:
        return False, (f"the hotel answered {', '.join(val)} with new details: reword the text with the answer in the "
                       'report JSON, then plan again'), [], {i: (answers.get(i) or {}).get('answer') for i in val}
    return True, '', [i for i in ids if i != hold_q], None


def plan(group_dir, slug, only=None):
    """Dry run for one hotel ('group' = the group batch: site-wide actions of a group site). On a single-hotel site
    site-wide actions are part of the hotel's own plan (batch "site-settings"). Returns batches with current -> new."""
    reg = grp.load(group_dir)
    single = grp.is_single(reg)
    if single and slug == 'group':
        slug = reg['hotels'][0]['slug']
    site = reg['group']['site']
    s = Site(site)
    hdir = grp.site_dir(group_dir, reg) if slug == 'group' else grp.hotel_dir(group_dir, slug, reg)
    run = _latest(hdir, 'audit-')
    if not run:
        raise FileNotFoundError(f'no audit for {slug}: run the audit first')
    report = json.loads((run / ('group-summary.json' if slug == 'group' else 'audit-report.json')).read_text(
        encoding='utf-8'))
    build = run / 'build-plan.json'
    pages_spec = json.loads(build.read_text(encoding='utf-8')).get('pages', []) if build.exists() else []
    from . import questions as qm
    qdata = qm.load(group_dir, slug) if slug != 'group' else None
    answers = {i['id']: i for i in (qdata or {}).get('items', [])}
    hold_qs = {i.get('finding_id'): i['id'] for i in answers.values() if i.get('type') == 'hold'}
    rooms_answered = any(i['sheet'] == 'Rooms' and i.get('answer') for i in answers.values())
    rewording = []
    planned, skipped, gbp_acts = [], [], []
    n = 0
    for sec in report.get('sections', []):
        acts = sec.get('actions') or []
        if not acts:
            continue
        fid = sec.get('finding_id', sec.get('title'))
        if only and fid not in only and sec.get('category') not in only:
            continue
        if sec.get('owner') == 'web':
            skipped.append({'finding': fid, 'reason': 'Web Team item: execute never applies these'})
            continue
        hold_q = None
        if sec.get('hold'):
            if fid in ('booking-room_size_mismatch', 'facts-bookingcom-conflicts') and rooms_answered:
                skipped.append({'finding': fid, 'reason': "covered by the hotel's room answers (hotel-answers batch)"})
                continue
            hold_q = hold_qs.get(fid)
            if not hold_q:
                skipped.append({'finding': fid, 'reason': f"on hold: {sec['hold']}"})
                continue
        for a in acts:
            n += 1
            item = {'id': f'a{n}', 'finding': fid, 'title': sec.get('title'), 'category': sec.get('category'),
                    'action': a, 'checks': sec.get('checks', [])}
            text = _payload_text(a)
            if '[CONFIRM' in text or hold_q:
                ok, why, confirmed, reword = _hotel_gate(text, answers, hold_q)
                if not ok:
                    skipped.append({'finding': fid, 'action': a['type'], 'act': a, 'reason': why})
                    if reword:
                        rewording.append({'finding': fid, 'title': sec.get('title'), 'action': a, 'answers': reword})
                    continue
                if confirmed:
                    a = _strip_confirmed(a, confirmed)
                    item['action'] = a
                    item['hotel_confirmed'] = confirmed
                text = _payload_text(a)
            if PRICE.search(text):
                skipped.append({'finding': fid, 'action': a['type'], 'act': a, 'reason': 'contains a price or discount: never changed'})
                continue
            if a['type'] == 'gbp':           # Business Profile: its own batch, planned below
                gbp_acts.append({'finding': fid, 'title': sec.get('title'), 'category': sec.get('category'),
                                 'action': a, **({'hotel_confirmed': item['hotel_confirmed']}
                                                 if item.get('hotel_confirmed') else {})})
                continue
            group_wide = a['type'] == 'rankmath_setting' or (a['type'] == 'elementor_text' and a.get('template')) or (
                a['type'] == 'schema_snippet' and any('general' in c for c in a.get('conditions', [])))
            if group_wide and slug != 'group' and not single:
                skipped.append({'finding': fid, 'action': a['type'], 'act': a, 'reason': 'group-wide: runs only in the group batch '
                                                                             '(execute without --hotel)'})
                continue
            tool = NEEDS_TOOL.get(a['type'])
            if a['type'] != 'chrome' and tool and tool not in s.tools:
                item.update(batch='chrome', via='chrome',
                            note=f'{tool} is not available on this site: do it in wp-admin with Claude in Chrome')
            else:
                item['batch'] = 'booking-path' if sec.get('category') == 'Booking path & facts' and a['type'] != 'chrome' \
                    else (('site-settings' if single else 'group') if group_wide else TYPE_BATCH.get(a['type'], 'chrome'))
            try:
                item.update(_resolve(s, a, pages_spec))
            except Exception as e:  # noqa: BLE001
                skipped.append({'finding': fid, 'action': a['type'], 'act': a, 'reason': f'could not resolve: {str(e)[:200]}'})
                continue
            item['validation'] = _validate_calls(s, item.get('calls') or [])
            if item['validation'].get('ok') is False:
                skipped.append({'finding': fid, 'action': a['type'], 'act': a,
                                'reason': 'the site rejected it in a dry run: ' + item['validation'].get('error', '')})
                continue
            planned.append(item)
    if qdata:
        for c in qm.corrections(group_dir, slug):
            n += 1
            item = {'id': f'a{n}', 'finding': f"hotel-answer-{c['question']}", 'title': c['why'],
                    'category': 'Hotel answers', 'action': c, 'batch': 'hotel-answers',
                    'checks': [{'type': 'text_present', 'url': c['url'], 'text': c['replace']},
                               {'type': 'text_absent', 'url': c['url'], 'text': c['find']}]}
            try:
                item.update(_resolve(s, c, pages_spec))
            except Exception as e:  # noqa: BLE001
                skipped.append({'finding': item['finding'], 'action': 'text_replace', 'page': c['url'],
                                'find': c['find'], 'replace': c['replace'],
                                'reason': f'could not change it through MCP: {str(e)[:200]}'})
                continue
            planned.append(item)
    if slug != 'group' and not any(x['action'].get('field') == 'website' for x in gbp_acts):
        hotel = next((h for h in reg['hotels'] if h['slug'] == slug), {})
        hotel_url = site.rstrip('/') + ('/' if single else '/' + ((hotel.get('paths') or ['/'])[0]).lstrip('/'))
        gbp_acts += [x for x in _gbp_report_actions(hdir, hotel_url)
                     if not only or x['finding'] in only or x['category'] in only]
    gbp_items, gbp_skipped, gbp_note, n = _gbp_plan(group_dir, slug, hdir, gbp_acts, n)
    planned += gbp_items
    skipped += gbp_skipped
    batches = defaultdict(list)
    for it in planned:
        batches[it['batch']].append(it)
    prefs = hotel_preferences(hdir)
    out = {'site': site, 'hotel': slug, 'created': time.strftime('%Y-%m-%d %H:%M'), 'source_run': str(run),
           'batches': {b: batches[b] for b in BATCH_ORDER if batches.get(b)}, 'skipped': skipped,
           'rewording': rewording, 'approved': [], 'done': [], 'recheck': {},
           'client_approval_required': bool(prefs.get('client_approval')), 'client_approval': None,
           'units': prefs.get('units'), **({'business_profile': gbp_note} if gbp_note else {})}
    ed = hdir / f'execute-{date.today().isoformat()}'
    ed.mkdir(parents=True, exist_ok=True)
    f = ed / 'plan.json'
    f.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding='utf-8')
    table = {b: [[it['id'], it.get('page') or it['action'].get('url') or it['action'].get('source', ''),
                  it.get('field', it['action']['type']), str(it.get('current'))[:120], str(it.get('new'))[:120]]
                 + ([f"change {it['change_id']}"] if it.get('change_id') else [])
                 for it in items] for b, items in out['batches'].items()}
    return {'plan_file': str(f), 'batches': {b: len(v) for b, v in out['batches'].items()}, 'skipped': len(skipped),
            'rewording': rewording, 'client_approval_required': out['client_approval_required'],
            **({'units': out['units']} if out['units'] else {}),
            'skipped_reasons': skipped[:40], 'table': table,
            **({'business_profile': gbp_note} if gbp_note else {}),
            'next': ('This hotel approves every change before it goes live (hotel.json preferences.client_approval): '
                     'send the client these tables first and record_client_approval(plan_file, by) once the user '
                     'confirms their yes. ' if out['client_approval_required'] else '')
                    + 'Show each batch as a table (page, field, current -> new) and ask the user to approve it; then '
                    'run_execute_batch(plan_file, batch). Nothing has been written.'
                    + (f' The {GBP_BATCH} batch changes the live Google profile: show its rows with their change ids; '
                       'the user\'s yes to that table approves those ids (proposals expire after 24 hours: '
                       'execute_gbp_refresh(plan_file) proposes them again with new ids).'
                       if out['batches'].get(GBP_BATCH) else '')}


DRY_RUN_TOOLS = {'seo-update-posts', 'seo-update-settings'}


def _validate_calls(s, calls):
    """Ask the site to validate changes without saving them, where the tool has dry_run."""
    checked = []
    for tool, args in calls:
        if tool in DRY_RUN_TOOLS:
            try:
                res = s.write(tool, dict(args, dry_run=True))
                errs = res.get('errors') or {}
                if errs or res.get('success') is False:
                    return {'ok': False, 'error': json.dumps(errs or res, ensure_ascii=False)[:300]}
                checked.append(tool)
            except Exception as e:  # noqa: BLE001
                return {'ok': False, 'error': str(e)[:300]}
    return {'ok': True, 'dry_run': checked} if checked else {'ok': None, 'note': 'no dry-run available for this tool'}


def _copy_html(text):
    """Build Plan copy (paragraphs, '## ' headings, '- ' bullets, **bold**) -> simple HTML for a new page."""
    out, items = [], []

    def flush():
        if items:
            out.append('<ul>' + ''.join(f'<li>{i}</li>' for i in items) + '</ul>')
            items.clear()
    for block in re.split(r'\n\s*\n', text or ''):
        for line in block.split('\n'):
            t = html.escape(line.strip())
            t = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', t)
            if not t:
                continue
            if t.startswith('- '):
                items.append(t[2:])
                continue
            flush()
            m = re.match(r'^(#{2,4})\s+(.*)$', t)
            out.append(f'<h{len(m.group(1))}>{m.group(2)}</h{len(m.group(1))}>' if m else f'<p>{t}</p>')
        flush()
    return '\n'.join(out)


def _media(site, image_url):
    """Public WordPress REST lookup of an attachment by file name: (id, alt_text)."""
    name = image_url.rsplit('/', 1)[-1]
    base = re.sub(r'-\d+x\d+(?=\.\w+$)', '', name).rsplit('.', 1)[0]
    r = requests.get(site.rstrip('/') + '/wp-json/wp/v2/media', params={'search': base, 'per_page': 20},
                     headers={'User-Agent': sites.USER_AGENT}, timeout=30)
    if r.status_code == 200:
        for m in r.json():
            if base in (m.get('source_url') or ''):
                return m['id'], m.get('alt_text', '')
    return None, None


def _resolve(s, a, pages_spec):
    """Turn an action into concrete tool calls with the current value. No writes."""
    t = a['type']
    if t == 'seo_fields':
        pid = s.post_id(a['url'])
        cur = s.read('seo-get-posts', {'post_ids': [pid]})
        post = (cur.get('posts') or [{}])[0]
        seo = post.get('seo') or post
        # the read tool returns HTML-escaped text (&amp;); store and restore the real characters
        current = {k: (html.unescape(seo.get(k)) if isinstance(seo.get(k), str) else seo.get(k)) for k in a['fields']}
        return {'page': a['url'], 'post_id': pid, 'field': ', '.join(a['fields']), 'current': current,
                'new': a['fields'], 'calls': [['seo-update-posts', {'posts': [dict(a['fields'], post_id=pid)]}]],
                'undo': [['seo-update-posts', {'posts': [dict(current, post_id=pid)]}]]}
    if t == 'redirect':
        existing = s.read('redirects-list', {'source': a['source'], 'per_page': 50}) if 'redirects-list' in s.tools else {}
        rule = {'source': a['source'], 'target': a.get('target', ''), 'code': a.get('code', 301),
                'regex': bool(a.get('regex'))}
        return {'page': a['source'], 'field': 'redirect', 'current': (existing.get('redirects') or existing.get('items')
                                                                     or [])[:3], 'new': rule,
                'calls': [['redirects-create', {'redirects': [rule], 'on_existing': 'error'}]], 'undo': 'delete-created'}
    if t == 'alt_text':
        mid, alt = _media(s.site, a['image'])
        item = {'id': mid} if mid else {'url': a['image']}
        return {'page': a['image'], 'field': 'alt', 'current': alt, 'new': a['alt'],
                'calls': [['update-media', {'items': [dict({'attachment_id': mid} if mid else {'url': a['image']},
                                                            alt_text=a['alt'])]}]],
                'undo': [['update-media', {'items': [dict({'attachment_id': mid} if mid else {'url': a['image']},
                                                           alt_text=alt or '')]}]] if alt is not None else None,
                'media': item}
    if t in ('elementor_text', 'post_content'):
        pid = s.post_id(a['url'])
        if t == 'post_content':
            cur = s.read('get-post', {'post_id': pid, 'include_elementor': False})
            old = (cur.get('post') or cur).get('content', '')
            return {'page': a['url'], 'post_id': pid, 'field': 'content', 'current': old[:300], 'new': a['content'][:300],
                    'calls': [['update-post', {'post_id': pid, 'content': a['content']}]],
                    'undo': [['update-post', {'post_id': pid, 'content': old}]]}
        st = s.read('elementor-get-structure', {'post_id': pid, 'search': a['find'][:60], 'include_settings': True})
        els = st.get('elements') or []
        if len(els) != 1:
            raise LookupError(f'"{a["find"][:60]}" matches {len(els)} Elementor elements on {a["url"]}: needs one')
        el = els[0]
        settings = _rendered_settings(el, a['settings'])
        old = {k: (el.get('settings') or {}).get(k) for k in settings}
        return {'page': a['url'], 'post_id': pid, 'field': 'elementor ' + ', '.join(settings), 'current': old,
                'new': settings, 'calls': [['elementor-update-element', {'post_id': pid, 'element_id': el['id'],
                                                                          'settings': settings}]],
                'undo': [['elementor-update-element', {'post_id': pid, 'element_id': el['id'], 'settings': old}]]}
    if t == 'schema_snippet':
        cur = None
        if a.get('replace_snippet_id'):
            cur = s.read('elementor-get-custom-code', {'post_id': a['replace_snippet_id']})
        conds = []
        for c in a['conditions']:
            if str(c).startswith('page:'):
                url = c.split(':', 1)[1]
                if _norm(url) == '/':
                    conds.append('include/singular/front_page')
                else:
                    pid = s.post_id(url)
                    conds.append(f"include/singular/{s.types.get(_norm(url), 'page')}/{pid}")
            else:
                conds.append(c)
        args = {'title': a['title'], 'code': a['code'], 'conditions': conds, 'status': 'publish',
                'location': 'elementor_head'}
        if a.get('replace_snippet_id'):
            args['post_id'] = a['replace_snippet_id']
        old = (cur or {}).get('snippet') or cur
        return {'page': ', '.join(a['conditions']), 'field': 'schema snippet', 'current': (old or {}).get('code', '')[:200]
                if isinstance(old, dict) else None, 'new': a['code'][:200],
                'calls': [['elementor-set-custom-code', args]],
                'undo': [['elementor-set-custom-code', {'post_id': a['replace_snippet_id'], 'code': old.get('code')}]]
                if a.get('replace_snippet_id') and isinstance(old, dict) else 'draft-created'}
    if t == 'rankmath_setting':
        cur = s.read('seo-get-settings', {'group': a['group'], 'keys': list(a['settings'])})
        current = cur.get('settings') or cur
        return {'page': f"Rank Math {a['group']}", 'field': ', '.join(a['settings']), 'current': current,
                'new': a['settings'], 'calls': [['seo-update-settings', {'group': a['group'], 'settings': a['settings']}]],
                'undo': [['seo-update-settings', {'group': a['group'], 'settings': {k: current.get(k) for k in
                                                                                    a['settings']}}]]}
    if t == 'post_status':
        pid = s.post_id(a['url'])
        cur = s.read('get-post', {'post_id': pid, 'include_content': False, 'include_elementor': False})
        old = (cur.get('post') or cur).get('status')
        return {'page': a['url'], 'post_id': pid, 'field': 'status', 'current': old, 'new': a['status'],
                'calls': [['set-post-status', {'post_id': pid, 'status': a['status']}]],
                'undo': [['set-post-status', {'post_id': pid, 'status': old}]]}
    if t == 'menu':
        m = s.read('get-menu', {'menu': a['menu'], 'format': 'flat'})
        items = m.get('items') or m.get('flat') or []
        hit = [i for i in items if _norm(str(i.get('url', ''))) == _norm(a['find_url'])]
        if not hit:
            raise LookupError(f"no item linking to {a['find_url']} in menu {a['menu']}")
        args, undo = {'item_id': hit[0]['id']}, {'item_id': hit[0]['id']}
        if a.get('new_url'):
            args.update(type='custom', url=a['new_url'])
            undo.update(type='custom', url=hit[0].get('url'))
        if a.get('new_title'):
            args['title'] = a['new_title']
            undo['title'] = hit[0].get('title')
        return {'page': f"menu {a['menu']}", 'field': 'menu item', 'current': {'url': hit[0].get('url'),
                                                                                'title': hit[0].get('title')},
                'new': {k: a.get(k) for k in ('new_url', 'new_title') if a.get(k)},
                'calls': [['update-menu-item', args]], 'undo': [['update-menu-item', undo]]}
    if t == 'page_create':
        spec = next((p for p in pages_spec if p.get('id') == a['page_id']), None)
        if not spec:
            raise LookupError(f"no page {a['page_id']} in build-plan.json")
        body = json.dumps({k: spec.get(k) for k in ('copy', 'content_html', 'jsonld', 'seo_title', 'meta_description',
                                                    'h1', 'title')}, ensure_ascii=False)
        if '[CONFIRM' in body or spec.get('hold'):
            raise ValueError('the page still has [CONFIRM] facts or is held for the hotel')
        if PRICE.search(body):
            raise ValueError('the page copy contains a price or discount: never published by execute')
        return {'page': spec.get('url'), 'field': 'new page', 'current': None,
                'new': {k: spec.get(k) for k in ('title', 'url', 'seo_title', 'meta_description')},
                'calls': [['create-post', {'post_type': spec.get('post_type', 'page'), 'title': spec['title'],
                                           'slug': spec['url'].strip('/').split('/')[-1],
                                           'content': spec.get('content_html') or _copy_html(spec.get('copy', '')),
                                           'status': 'publish'}]],
                'then': {'seo_fields': {k: spec[k] for k in ('seo_title', 'meta_description') if spec.get(k)},
                         'schema': spec.get('jsonld')}, 'undo': 'draft-created'}
    if t == 'text_replace':
        pid = s.post_id(a['url'])
        calls, undo = [], []
        if 'elementor-get-structure' in s.tools:
            st = s.read('elementor-get-structure', {'post_id': pid, 'search': a['find'][:60], 'include_settings': True})
            for el in st.get('elements') or []:
                sett = el.get('settings') or {}
                new = {k: v.replace(a['find'], a['replace']) for k, v in sett.items()
                       if isinstance(v, str) and a['find'] in v}
                if new:
                    calls.append(['elementor-update-element', {'post_id': pid, 'element_id': el['id'], 'settings': new}])
                    undo.append(['elementor-update-element', {'post_id': pid, 'element_id': el['id'],
                                                              'settings': {k: sett[k] for k in new}}])
        if not calls:
            cur = s.read('get-post', {'post_id': pid, 'include_elementor': False})
            content = (cur.get('post') or cur).get('content', '') or ''
            if a['find'] in content:
                calls = [['update-post', {'post_id': pid, 'content': content.replace(a['find'], a['replace'])}]]
                undo = [['update-post', {'post_id': pid, 'content': content}]]
        if not calls:
            raise LookupError(f'"{a["find"]}" is not in the page\'s editable text (it may come from a template, '
                              'a widget the tools cannot reach, or the booking engine)')
        return {'page': a['url'], 'post_id': pid, 'field': 'text', 'current': a['find'], 'new': a['replace'],
                'calls': calls, 'undo': undo}
    if t == 'chrome':
        return {'page': a['where'], 'field': 'Claude in Chrome', 'current': None, 'new': a['steps'], 'calls': [],
                'via': 'chrome', 'undo': 'manual: reverse the steps by hand'}
    raise ValueError(f'unknown action type {t}')


def run_batch(plan_file, batch, approved=False):
    """Run one approved batch. approved must be True (the user said yes to this batch's table)."""
    if not approved:
        raise PermissionError('Show the batch table to the user and pass approved=true only after they approve it.')
    pf = paths.resolve(plan_file)
    pl = json.loads(pf.read_text(encoding='utf-8'))
    if pl.get('client_approval_required') and not pl.get('client_approval'):
        raise PermissionError('This hotel approves every change before it goes live (hotel.json '
                              'preferences.client_approval). Send the client the change list, then '
                              'record_client_approval(plan_file, by="<name>, <channel> <date>") once the user confirms '
                              'their yes. Never assume approval.')
    items = pl['batches'].get(batch)
    if not items:
        raise LookupError(f'no batch {batch} in the plan')
    if batch == GBP_BATCH:
        return _run_gbp(pf, pl, batch, items)
    if batch == 'chrome':
        return {'batch': batch, 'via': 'chrome', 'steps': [{'id': it['id'], 'where': it['page'], 'steps': it['new'],
                                                            'note': it.get('note')} for it in items],
                'next': 'Do each step with Claude in Chrome in a new tab (the user is logged in; never type passwords), '
                        'save before/after screenshots to execute-<date>/chrome/, then record_chrome_step.'}
    lock = pf.parent / '.lock'
    if lock.exists() and time.time() - lock.stat().st_mtime < 3600:
        raise RuntimeError('another execute is running on this site (lock file); wait or remove it if stale')
    lock.write_text(time.strftime('%Y-%m-%d %H:%M'))
    s = Site(pl['site'])
    before_f, changes_f = pf.parent / 'before.json', pf.parent / 'changes.json'
    before = json.loads(before_f.read_text(encoding='utf-8')) if before_f.exists() else {}
    changes = json.loads(changes_f.read_text(encoding='utf-8')) if changes_f.exists() else []
    done, failed, post_ids = [], None, set()
    try:
        for it in items:
            if it.get('via') == 'chrome' or it['id'] in pl.get('done', []):
                continue
            before[it['id']] = {'current': it.get('current'), 'undo': it.get('undo'), 'action': it['action']}
            before_f.write_text(json.dumps(before, indent=1, ensure_ascii=False), encoding='utf-8')
            try:
                results = []
                for tool, args in it['calls']:
                    results.append(s.write(tool, args))
                if it['action']['type'] == 'page_create':
                    res = results[-1]
                    pid = (res.get('post') or res).get('id') or res.get('post_id')
                    it['created_post_id'] = pid
                    if it.get('then', {}).get('seo_fields') and pid:
                        f = it['then']['seo_fields']
                        s.write('seo-update-posts', {'posts': [{'post_id': pid, 'title': f.get('seo_title'),
                                                                'description': f.get('meta_description')}]})
                    if it.get('then', {}).get('schema') and pid and 'elementor-set-custom-code' in s.tools:
                        s.write('elementor-set-custom-code', {'title': f"Schema: {it['new'].get('title')}",
                                                              'code': it['then']['schema'], 'status': 'publish',
                                                              'conditions': [f'include/singular/page/{pid}']})
                if it['action']['type'] == 'redirect':
                    it['created_ids'] = [i for r in results for i in (r.get('ids') or r.get('created') or [])
                                         if isinstance(i, int)]
                if it.get('post_id'):
                    post_ids.add(it['post_id'])
                changes.append({'id': it['id'], 'finding': it['finding'], 'page': it.get('page'),
                                'field': it.get('field'), 'old': it.get('current'), 'new': it.get('new'),
                                'at': time.strftime('%Y-%m-%d %H:%M:%S'), 'created_post_id': it.get('created_post_id'),
                                'created_ids': it.get('created_ids')})
                changes_f.write_text(json.dumps(changes, indent=1, ensure_ascii=False), encoding='utf-8')
                pl.setdefault('done', []).append(it['id'])
                done.append(it['id'])
            except Exception as e:  # noqa: BLE001 - stop the batch at the first error
                failed = {'id': it['id'], 'finding': it['finding'], 'error': str(e)[:400]}
                break
        pl.setdefault('approved', []).append({'batch': batch, 'at': time.strftime('%Y-%m-%d %H:%M')})
        pf.write_text(json.dumps(pl, indent=1, ensure_ascii=False), encoding='utf-8')
        purge = None
        if done and 'purge-cache' in s.tools:
            try:
                purge = s.write('purge-cache', {'post_ids': sorted(post_ids)} if post_ids and batch != 'group' else {})
            except Exception as e:  # noqa: BLE001
                purge = {'error': str(e)[:200]}
    finally:
        lock.unlink(missing_ok=True)
    rechecked = _recheck(pl['site'], [it for it in items if it['id'] in done])
    pl = json.loads(pf.read_text(encoding='utf-8'))
    for r in rechecked:
        pl.setdefault('recheck', {})[r['finding']] = dict(r, at=time.strftime('%Y-%m-%d %H:%M'))
    if failed:
        pl.setdefault('failed', []).append(dict(failed, batch=batch))
    pf.write_text(json.dumps(pl, indent=1, ensure_ascii=False), encoding='utf-8')
    return {'batch': batch, 'done': len(done), 'of': len(items), 'failed': failed, 'cache_purged': purge,
            'recheck': rechecked, 'changes_file': str(changes_f), 'before_file': str(before_f),
            'undo': f'undo_execute("{plan_file}")'}


def hotel_preferences(hotel_dir):
    """preferences from <hotel dir>/hotel.json (hotel_settings): client_approval, units. Empty when there is none."""
    f = paths.resolve(hotel_dir) / 'hotel.json'
    try:
        return (json.loads(f.read_text(encoding='utf-8')).get('preferences') or {}) if f.exists() else {}
    except (ValueError, OSError):
        return {}


def record_client_approval(plan_file, by, note=''):
    """The client's yes to this change list: who and how ("Mr Yunus, email 6 Nov"). Never inferred."""
    if not str(by).strip():
        raise ValueError('say who approved and how, e.g. "Mr Yunus, email 6 Nov"')
    pf = paths.resolve(plan_file)
    pl = json.loads(pf.read_text(encoding='utf-8'))
    pl['client_approval'] = {'by': by, 'note': note, 'recorded': time.strftime('%Y-%m-%d %H:%M')}
    pf.write_text(json.dumps(pl, indent=1, ensure_ascii=False), encoding='utf-8')
    return {'recorded': True, 'by': by, 'plan_file': str(pf)}


WIDGET_TEXT_KEY = {'heading': 'title', 'text-editor': 'editor', 'button': 'text', 'icon-box': 'title_text',
                   'image-box': 'title_text', 'call-to-action': 'title', 'animated-headline': 'before_text'}
TEXT_KEYS = ('title', 'editor', 'text', 'title_text', 'description_text', 'heading', 'content')


def elementor_settings(element, new_text, key=''):
    """Settings for elementor-update-element that the widget really renders: heading -> title, text-editor -> editor
    (wrapped in <p>), button -> text, icon-box / image-box -> title_text; an unknown widget uses its only text key.
    element: one element from elementor-get-structure (with settings). Writing the wrong key "succeeds" and changes
    nothing on the page."""
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


def _rendered_settings(el, settings):
    """One text value for a key the element doesn't have goes to the key its widget renders."""
    have = el.get('settings') or {}
    if len(settings) != 1:
        return settings
    (k, v), = settings.items()
    if k in have or not isinstance(v, str):
        return settings
    fixed = elementor_settings(el, v, k)
    return fixed.get('settings') or settings


def _full(site, u):
    return u if u.startswith('http') else site.rstrip('/') + '/' + u.lstrip('/')


def resolve_post(site, url):
    """The WordPress post behind a full URL. A slug alone is not enough on a group site, where every hotel has
    /about-us/ and /rooms/. Asks the public REST API for every post with the last slug and keeps the one whose link
    matches the full path; two matches is an error. Post types not in REST return not_found."""
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
        for row in rows:
            if isinstance(row, dict) and urlparse(row.get('link', '')).path.rstrip('/') + '/' == want:
                hits.append({'post_id': row['id'], 'type': row.get('type') or b, 'link': row.get('link')})
    if len(hits) > 1:
        return {'url': url, 'error': f'{len(hits)} posts have the path {want}: resolve by hand', 'matches': hits}
    if not hits:
        return {'url': url, 'not_found': True, 'note': f'no public post with the path {want} (the type may not be in '
                'REST): use the site tools (list-posts / get-post) and compare the full link'}
    return {'url': url, **hits[0]}


def _recheck(site, items):
    f = chk.Fetcher(site, delay=0.2)
    out = []
    seen = set()
    for it in items:
        if it['finding'] in seen:
            continue
        seen.add(it['finding'])
        rows = [dict(check=chk.describe(c), **chk.run_check(c, f, ['/'])) for c in it.get('checks', [])[:30]]
        auto = [r for r in rows if r['result'] != 'manual']
        passed = sum(r['result'] == 'pass' for r in auto)
        out.append({'finding': it['finding'], 'status': 'Manual' if not auto else 'Done' if passed == len(auto) else
                    'Partly' if passed else 'Open', 'passed': passed, 'checks': len(auto)})
    return out


def undo(plan_file):
    """Write the before-values back, newest change first."""
    pf = paths.resolve(plan_file)
    pl = json.loads(pf.read_text(encoding='utf-8'))
    before = json.loads((pf.parent / 'before.json').read_text(encoding='utf-8'))
    changes = json.loads((pf.parent / 'changes.json').read_text(encoding='utf-8'))
    s = None
    restored, problems, gbp_undo = [], [], []
    for ch in reversed(changes):
        b = before.get(ch['id'], {})
        u = b.get('undo')
        if u == 'gbp-reverse' or ch.get('via') == 'business_profile':
            try:     # the live profile is only changed back after the user approves the reverse proposal
                gbp_undo.append(dict(_gbp_undo(ch, pf.parent.parent / 'gbp' / 'changes'), id=ch['id'],
                                     field=ch.get('field')))
            except Exception as e:  # noqa: BLE001
                problems.append({'id': ch['id'], 'error': str(e)[:300]})
            continue
        try:
            s = s or Site(pl['site'])
            if isinstance(u, list):
                for tool, args in u:
                    s.write(tool, args)
            elif u == 'delete-created' and ch.get('created_ids'):
                s.write('redirects-delete', {'ids': ch['created_ids'], 'confirm': True})
            elif u == 'draft-created' and ch.get('created_post_id'):
                s.write('set-post-status', {'post_id': ch['created_post_id'], 'status': 'draft'})
            else:
                problems.append({'id': ch['id'], 'reason': f'no automatic undo ({u})'})
                continue
            restored.append(ch['id'])
        except Exception as e:  # noqa: BLE001
            problems.append({'id': ch['id'], 'error': str(e)[:300]})
    if s and 'purge-cache' in s.tools and restored:
        try:
            s.write('purge-cache', {})
        except Exception:  # noqa: BLE001
            pass
    (pf.parent / 'undo.json').write_text(json.dumps({'restored': restored, 'problems': problems,
                                                     'business_profile_proposed': gbp_undo,
                                                     'at': time.strftime('%Y-%m-%d %H:%M')}, indent=1,
                                                    ensure_ascii=False), encoding='utf-8')
    out = {'restored': len(restored), 'problems': problems}
    if gbp_undo:
        out['business_profile'] = gbp_undo
        out['next'] = ('Business Profile changes are NOT undone yet: each was proposed back to its logged before value. '
                       'Show each preview word for word; gbp_apply(change_file, confirm=change_id) only after the user '
                       'approves that id in a later message.')
    return out


def record_chrome_step(plan_file, item_id, done=True, note=''):
    """Mark a Chrome step as done (or not done, with why) after doing it with Claude in Chrome."""
    pf = paths.resolve(plan_file)
    pl = json.loads(pf.read_text(encoding='utf-8'))
    items = {it['id']: it for b in pl['batches'].values() for it in b}
    if item_id not in items:
        raise LookupError(f'no item {item_id} in the plan')
    pl.setdefault('chrome_log', []).append({'id': item_id, 'done': bool(done), 'note': note,
                                            'at': time.strftime('%Y-%m-%d %H:%M')})
    if done and item_id not in pl.setdefault('done', []):
        pl['done'].append(item_id)
        it = items[item_id]
        changes_f = pf.parent / 'changes.json'
        changes = json.loads(changes_f.read_text(encoding='utf-8')) if changes_f.exists() else []
        changes.append({'id': item_id, 'finding': it['finding'], 'page': it.get('page'), 'field': 'Claude in Chrome',
                        'old': None, 'new': it.get('new'), 'note': note, 'at': time.strftime('%Y-%m-%d %H:%M:%S')})
        changes_f.write_text(json.dumps(changes, indent=1, ensure_ascii=False), encoding='utf-8')
    pf.write_text(json.dumps(pl, indent=1, ensure_ascii=False), encoding='utf-8')
    return {'recorded': item_id, 'done': bool(done)}


# ---------------------------------------------------------------- Google Business Profile batch

GBP_BATCH = 'business-profile'
# the fields execute changes, with the label used in changes.json / reports (no word the monthly report maps to a
# site field: "description" would read as a meta description)
GBP_FIELDS = {'description': 'profile text', 'website': 'website link', 'phone': 'phone number',
              'regular_hours': 'opening hours', 'special_hours': 'special hours',
              'additional_categories': 'extra categories', 'attributes': 'amenities (attributes)'}
GBP_LOCKED = {'title', 'name', 'business_name', 'address', 'primary_category'}
GBP_UTM = 'utm_source=google&utm_medium=organic&utm_campaign=gbp'      # the team's link (SKILL.md, Business Profile)


def gbp_url_with_utm(url):
    """The profile's website link with the team's UTM tags (kept as is when it already has UTM tags)."""
    url = str(url or '').strip()
    if not url or 'utm_' in url:
        return url
    base, _, frag = url.partition('#')
    return base + ('&' if '?' in base else '?') + GBP_UTM + (f'#{frag}' if frag else '')


def _gbp_change(a):
    """(key, value) for gbp_write.propose from one "gbp" action; ValueError when execute never makes it."""
    field = str(a.get('field', '')).strip()
    if field in GBP_LOCKED:
        raise ValueError(f'Business Profile {field} is locked (it can send the profile back to verification): '
                         'never through execute; only as its own Business Profile change when the user asks for it')
    if field not in GBP_FIELDS:
        raise ValueError(f'"{field}" is not a Business Profile fix execute makes (only {", ".join(GBP_FIELDS)}); '
                         'posts, photos and review replies have their own path')
    v = a.get('value')
    if v is None or v == '':
        raise ValueError(f'Business Profile {field}: no value')
    return field, (gbp_url_with_utm(v) if field == 'website' else v)


def _gbp_report_actions(hdir, hotel_url):
    """A website-link fix from the hotel's latest gbp_report (<hotel dir>/gbp/gbp-<date>.json) when it lists
    problems with the link (redirects, another host, no UTM tags, not a 200)."""
    reps = sorted((hdir / 'gbp').glob('gbp-2*.json'))
    if not reps or not hotel_url:
        return []
    try:
        rep = json.loads(reps[-1].read_text(encoding='utf-8'))
    except (ValueError, OSError):
        return []
    w = (rep.get('vs_website') or {}).get('website') or {}
    probs, uri, final = w.get('problems') or [], w.get('website_uri', ''), w.get('final_url') or ''

    def host(u):
        return re.sub(r'^www\.', '', urlparse(u).netloc.lower())
    if not probs:
        return []
    base = re.split(r'[?#]', final)[0] if w.get('status') == 200 and final and host(final) == host(hotel_url) \
        else hotel_url
    new = gbp_url_with_utm(base)
    if new == uri:
        return []
    return [{'finding': 'gbp-website-link', 'category': 'Local',
             'title': f"Business Profile website link (gbp_report {rep.get('generated', '')}): " + '; '.join(probs),
             'action': {'type': 'gbp', 'field': 'website', 'value': new}}]


def _gbp_propose(item, out_dir):
    """One gbp_write proposal for one plan item: fills change_id / change_file / current / new. Sends nothing."""
    from . import gbp_write
    res = gbp_write.propose(item['location'], {item['gbp_key']: item['gbp_value']}, out_dir=str(out_dir))
    if not res.get('checked'):
        raise RuntimeError(res.get('reason') or 'the proposal failed')
    c = json.loads(paths.resolve(res['change_file']).read_text(encoding='utf-8'))
    rows = [r for op in c.get('ops', []) for r in op.get('rows', [])]
    one = len(rows) == 1
    item.update(change_id=res['change_id'], change_file=res['change_file'], expires=c.get('expires'),
                current=rows[0][1] if one else {r[0]: r[1] for r in rows},
                new=rows[0][2] if one else {r[0]: r[2] for r in rows}, warnings=c.get('warnings', []))
    return item


def _gbp_plan(group_dir, slug, hdir, acts, n):
    """The business-profile batch: (items, skipped, note, n). One proposal (change id) per field."""
    from . import gbp
    if not acts:
        return [], [], None, n

    def skip_all(reason):
        return [], [{'finding': x['finding'], 'action': 'gbp', 'act': x['action'], 'reason': reason}
                    for x in acts], {'status': 'skipped', 'reason': reason}, n
    if slug == 'group':
        return skip_all('Business Profile changes are per hotel: run execute_plan for each hotel')
    loc = gbp.hotel_location(group_dir, slug).get('location')
    if not loc:
        return skip_all(f'Business Profile batch skipped: hotel "{slug}" has no linked Business Profile. Link it with '
                        f'gbp_link("<domain>", "{slug}", "locations/<id>") (gbp_locations lists them), then '
                        'execute_plan again')
    ok, why = gbp.configured()
    if not ok:
        return skip_all(f'Business Profile batch skipped: {why}')
    items, skipped, seen = [], [], set()
    out_dir = hdir / 'gbp' / 'changes'
    for x in acts:
        try:
            key, val = _gbp_change(x['action'])
            if key in seen:
                raise ValueError(f'another finding already changes the Business Profile {key} in this plan')
        except ValueError as e:
            skipped.append({'finding': x['finding'], 'action': 'gbp', 'act': x['action'], 'reason': str(e)})
            continue
        seen.add(key)
        n += 1
        it = {'id': f'a{n}', 'finding': x['finding'], 'title': x.get('title'), 'category': x.get('category'),
              'action': x['action'], 'batch': GBP_BATCH, 'via': 'business_profile', 'page': 'Google Business Profile',
              'field': f'Business Profile: {GBP_FIELDS[key]}', 'gbp_key': key, 'gbp_value': val, 'location': loc,
              'checks': [], **({'hotel_confirmed': x['hotel_confirmed']} if x.get('hotel_confirmed') else {})}
        try:
            items.append(_gbp_propose(it, out_dir))
        except Exception as e:  # noqa: BLE001 - Google's validation or sign-in: skip this field, say why
            n -= 1           # the id is reused by the next item
            skipped.append({'finding': x['finding'], 'action': 'gbp', 'act': x['action'],
                            'reason': f'Business Profile rejected it in the dry run: {str(e)[:300]}'})
    return items, skipped, {'status': 'planned' if items else 'nothing to change', 'location': loc,
                            'items': len(items)}, n


def propose_gbp_batch(plan_file):
    """Propose the plan's not-yet-sent Business Profile items again (new change ids), e.g. after the 24-hour expiry
    or after the client's approval. The user approves the new ids before run_execute_batch."""
    pf = paths.resolve(plan_file)
    pl = json.loads(pf.read_text(encoding='utf-8'))
    items = pl.get('batches', {}).get(GBP_BATCH) or []
    if not items:
        raise LookupError(f'no {GBP_BATCH} batch in the plan')
    out_dir, rows, problems = pf.parent.parent / 'gbp' / 'changes', [], []
    for it in items:
        if it['id'] in pl.get('done', []):
            continue
        try:
            _gbp_propose(it, out_dir)
            rows.append([it['id'], it['field'], str(it.get('current'))[:120], str(it.get('new'))[:120],
                         f"change {it['change_id']}"])
        except Exception as e:  # noqa: BLE001
            problems.append({'id': it['id'], 'error': str(e)[:300]})
    pf.write_text(json.dumps(pl, indent=1, ensure_ascii=False), encoding='utf-8')
    return {'plan_file': str(pf), 'table': rows, 'problems': problems,
            'next': 'Show the table with the new change ids and ask the user; then run_execute_batch(plan_file, '
                    f'"{GBP_BATCH}", approved=true).'}


def _run_gbp(pf, pl, batch, items):
    """Send the approved Business Profile proposals (gbp_write.apply), stop at the first that isn't applied, and log
    each in changes.json / before.json like a site change."""
    from . import gbp_write
    before_f, changes_f = pf.parent / 'before.json', pf.parent / 'changes.json'
    before = json.loads(before_f.read_text(encoding='utf-8')) if before_f.exists() else {}
    changes = json.loads(changes_f.read_text(encoding='utf-8')) if changes_f.exists() else []
    done, failed, rechecked = [], None, []
    for it in items:
        if it['id'] in pl.get('done', []):
            continue
        if not it.get('change_file'):
            failed = {'id': it['id'], 'finding': it['finding'], 'error': 'no proposal: execute_gbp_refresh(plan_file)'}
            break
        res = gbp_write.apply(it['change_file'], it['change_id'])
        if not res.get('checked') or res.get('status') != 'applied':
            why = res.get('reason') or '; '.join(f"{r.get('what')}: {r.get('result')} {r.get('why', '')}".strip()
                                                 for r in res.get('results', []))
            if 'expired' in why or 'changed since' in why or 'propose again' in why:
                why += ('. Run execute_gbp_refresh(plan_file), show the new change ids and ask the user again')
            failed = {'id': it['id'], 'finding': it['finding'], 'error': why[:500]}
            break
        read_back = next((r.get('read_back') for r in res.get('results', []) if r.get('read_back')), '')
        status = 'Done' if read_back == 'live now' else 'Pending Google review' if read_back else 'Sent'
        before[it['id']] = {'current': it.get('current'), 'undo': 'gbp-reverse', 'action': it['action'],
                            'gbp': {'change_file': it['change_file'], 'change_id': it['change_id'],
                                    'location': it.get('location')}}
        # page '' : not a page of the site (the monthly readback compares site pages in Search Console)
        changes.append({'id': it['id'], 'finding': it['finding'], 'page': '', 'field': it.get('field'),
                        'old': it.get('current'), 'new': it.get('new'), 'at': time.strftime('%Y-%m-%d %H:%M:%S'),
                        'via': 'business_profile', 'location': it.get('location'), 'change_id': it['change_id'],
                        'change_file': it['change_file'], 'read_back': read_back or 'sent'})
        before_f.write_text(json.dumps(before, indent=1, ensure_ascii=False), encoding='utf-8')
        changes_f.write_text(json.dumps(changes, indent=1, ensure_ascii=False), encoding='utf-8')
        pl.setdefault('done', []).append(it['id'])
        done.append(it['id'])
        rechecked.append({'finding': it['finding'], 'status': status, 'passed': int(status == 'Done'), 'checks': 1,
                          'via': 'business_profile', 'read_back': read_back or 'sent'})
    pl.setdefault('approved', []).append({'batch': batch, 'at': time.strftime('%Y-%m-%d %H:%M')})
    for r in rechecked:
        pl.setdefault('recheck', {})[r['finding']] = dict(r, at=time.strftime('%Y-%m-%d %H:%M'))
    if failed:
        pl.setdefault('failed', []).append(dict(failed, batch=batch))
    pf.write_text(json.dumps(pl, indent=1, ensure_ascii=False), encoding='utf-8')
    return {'batch': batch, 'done': len(done), 'of': len(items), 'failed': failed, 'recheck': rechecked,
            'changes_file': str(changes_f), 'before_file': str(before_f), 'log': str(gbp_write.LOG),
            'note': '"Pending Google review" is normal: Google checks most profile edits before they show.',
            'undo': f'undo_execute("{pf}") proposes the before values again (the user approves them)'}


def _hm(t):
    t = t or {}
    return f"{int(t.get('hours', 0)):02d}:{int(t.get('minutes', 0)):02d}"


def _ymd(d):
    return f"{int(d['year']):04d}-{int(d['month']):02d}-{int(d['day']):02d}"


def _attr_back(a):
    if not a:
        return None
    if a.get('uriValues'):
        return a['uriValues'][0].get('uri')
    if a.get('repeatedEnumValue'):
        return list(a['repeatedEnumValue'].get('setValues') or [])
    vals = a.get('values')
    if vals is None:
        return None
    return vals[0] if len(vals) == 1 else vals


def reverse_changes(change_file):
    """(location, changes, notes): the gbp_write.propose `changes` that put back the logged "before" values of an
    applied change file (only the operations that were sent)."""
    c = json.loads(paths.resolve(change_file).read_text(encoding='utf-8'))
    results = c.get('results') or []
    rev, notes = {}, []
    for i, op in enumerate(c.get('ops', [])):
        if results and (i >= len(results) or results[i].get('result') != 'sent'):
            continue
        b = op.get('before')
        if op.get('kind') == 'listing':
            for k, v in (b or {}).items():
                if k == 'websiteUri':
                    if v:
                        rev['website'] = v
                    else:
                        notes.append('the website link was empty before: remove it in the profile by hand')
                elif k == 'phoneNumbers':
                    if (v or {}).get('primaryPhone'):
                        rev['phone'] = v['primaryPhone']
                    else:
                        notes.append('the phone was empty before: remove it in the profile by hand')
                elif k == 'profile':
                    rev['description'] = (v or {}).get('description', '')
                elif k == 'regularHours':
                    rev['regular_hours'] = [{'day': p.get('openDay'), 'open': _hm(p.get('openTime')),
                                             'close': _hm(p.get('closeTime')), 'close_day': p.get('closeDay') or
                                             p.get('openDay')} for p in (v or {}).get('periods', [])]
                elif k == 'specialHours':
                    rows = []
                    for p in (v or {}).get('specialHourPeriods', []):
                        r = {'date': _ymd(p['startDate'])}
                        if p.get('endDate'):
                            r['end_date'] = _ymd(p['endDate'])
                        if p.get('closed'):
                            r['closed'] = True
                        else:
                            r.update(open=_hm(p.get('openTime')), close=_hm(p.get('closeTime')))
                        rows.append(r)
                    rev['special_hours'] = rows
                elif k == 'categories':
                    rev['additional_categories'] = [x['name'] for x in (v or {}).get('additionalCategories', [])
                                                    if x.get('name')]
                else:
                    notes.append(f'{k} is not put back by execute (locked field): restore it by hand')
        elif op.get('kind') == 'attributes':
            rev.setdefault('attributes', {}).update({k: _attr_back(a) for k, a in (b or {}).items()})
        else:
            notes.append(f"{op.get('kind')} is not undone by execute")
    return c.get('location', ''), rev, notes


def _gbp_undo(ch, out_dir):
    """Propose the reverse of one applied Business Profile change. Sends nothing."""
    from . import gbp_write
    loc, rev, notes = reverse_changes(ch['change_file'])
    if not rev:
        raise ValueError('nothing to put back' + (f": {'; '.join(notes)}" if notes else ''))
    res = gbp_write.propose(loc or ch.get('location'), rev, out_dir=str(out_dir))
    if not res.get('checked'):
        raise RuntimeError(res.get('reason') or 'the reverse proposal failed')
    return {'change_id': res['change_id'], 'change_file': res['change_file'], 'preview': res.get('preview', ''),
            'changes': rev, 'notes': notes}
