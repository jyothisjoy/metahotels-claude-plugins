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
              'rankmath_setting': 'group', 'text_replace': 'elementor-text', 'elementor_widget': 'elementor-text',
              'phone_link': 'elementor-text', 'heading_level': 'elementor-text', 'link_text': 'elementor-text',
              'insert_text': 'elementor-text'}
NEEDS_TOOL = {'seo_fields': 'seo-update-posts', 'redirect': 'redirects-create', 'alt_text': 'update-media',
              'elementor_text': 'elementor-update-element', 'schema_snippet': 'elementor-set-custom-code',
              'rankmath_setting': 'seo-update-settings', 'post_status': 'set-post-status',
              'post_content': 'update-post', 'menu': 'update-menu-item', 'page_create': 'create-post',
              'elementor_widget': 'elementor-update-element', 'phone_link': 'find-text',
              'heading_level': 'elementor-update-element', 'link_text': 'elementor-update-element',
              'insert_text': 'elementor-insert-element'}
PRICE = re.compile(r'(?:AED|USD|EUR|SAR|EGP|\$|€)\s?\d|\d\s?(?:AED|USD|EUR|SAR|EGP|dirhams?)\b|\d+\s?%\s*(?:off|discount)'
                   r'|\b(?:discount|save)\s+\d+\s?%', re.I)

# ---------------------------------------------------------------- schema code and the JSON-LD guard
# Elementor Custom Code prints its code word for word. Bare JSON (no <script type="application/ld+json">) lands in the
# page as text: Nov 2026, a schema batch dumped the JSON-LD on the live site. Every schema write goes through
# schema_code(); page text, widget text and replacements never carry JSON-LD (no_jsonld()).
LD_SCRIPT = re.compile(r'<script\b[^>]*\btype\s*=\s*["\']?application/ld\+json["\']?[^>]*>(.*?)</script\s*>',
                       re.I | re.S)
JSONLD_TEXT = re.compile(r'application/ld\+json|"@context"\s*:|"@type"\s*:\s*"|https?://schema\.org["\']?\s*[,}]', re.I)


def schema_code(code):
    """The snippet code for one or more JSON-LD blocks: each block parsed, checked and written back as
    <script type="application/ld+json">...</script> ("</" escaped so a value can't close the tag). Accepts a JSON-LD
    object or list, a JSON string, or <script type="application/ld+json"> blocks. ValueError for invalid JSON, HTML or
    text outside the blocks (it would print on the page), or JSON without "@context"."""
    if isinstance(code, (dict, list)):
        datas = [code]
    else:
        s = str(code or '').strip()
        if not s:
            raise ValueError('the schema code is empty')
        blocks = LD_SCRIPT.findall(s)
        if blocks:
            rest = re.sub(r'<!--.*?-->', '', LD_SCRIPT.sub('', s), flags=re.S).strip()
            if rest:
                raise ValueError('text outside the <script type="application/ld+json"> block would print on the '
                                 f'page: {rest[:80]!r}')
        elif s.startswith('<'):
            raise ValueError('the schema code is HTML, not JSON-LD in <script type="application/ld+json">: '
                             f'{s[:80]!r}')
        else:
            blocks = [s]
        datas = []
        for b in blocks:
            try:
                datas.append(json.loads(b))
            except ValueError as e:
                raise ValueError(f'invalid JSON-LD ({e}): Google ignores the block and nothing is written') from e
    out = []
    for d in datas:
        nodes = d if isinstance(d, list) else [d]
        if not nodes or not all(isinstance(n, dict) for n in nodes):
            raise ValueError('JSON-LD must be an object or a list of objects')
        if not all('@context' in n for n in nodes):
            raise ValueError('a JSON-LD block has no "@context" (https://schema.org)')
        body = json.dumps(d, ensure_ascii=False, indent=1).replace('</', '<\\/').replace('<!--', '<\\!--')
        out.append(f'<script type="application/ld+json">\n{body}\n</script>')
    return '\n'.join(out)


def no_jsonld(value, where):
    """ValueError when page text (content, widget settings, a replacement) carries JSON-LD: it would show as text."""
    def strings(v):
        if isinstance(v, str):
            yield v
        elif isinstance(v, dict):
            for x in v.values():
                yield from strings(x)
        elif isinstance(v, list):
            for x in v:
                yield from strings(x)
    if any(JSONLD_TEXT.search(t) for t in strings(value)):
        raise ValueError(f'{where} contains JSON-LD (schema): it would print as text on the page. Schema goes in a '
                         'schema_snippet action (Elementor Custom Code), never in page text')


def _schema_checks(urls):
    """Re-checks after a schema write: every block parses and no JSON-LD shows as page text."""
    out = []
    for u in urls:
        out += [{'type': 'jsonld_valid', 'url': u},
                {'type': 'text_absent', 'url': u, 'text': '"@context"', 'scope': 'visible'},
                {'type': 'text_absent', 'url': u, 'text': 'schema.org', 'scope': 'visible'}]
    return out


def _norm(u):
    p = urlparse(u if '//' in u else 'https://x' + u)
    return (p.path or '/').rstrip('/') + '/'


def _payload_text(a):
    return json.dumps({k: v for k, v in a.items() if k not in ('type',)}, ensure_ascii=False)


def _new_text(a):
    """The text an action writes (not the text it looks for): what the price guard checks."""
    t = a.get('type')
    if t == 'text_replace':
        return str(a.get('replace') or '')
    if t in ('elementor_text', 'elementor_widget'):
        return json.dumps(a.get('settings') or {}, ensure_ascii=False)
    if t == 'post_content':
        return str(a.get('content') or '')
    if t == 'seo_fields':
        return json.dumps(a.get('fields') or {}, ensure_ascii=False)
    if t in ('phone_link', 'heading_level'):
        return ''
    if t == 'link_text':
        return str(a.get('new_text') or '')
    if t == 'insert_text':
        return str(a.get('html') or a.get('text') or '')
    return _payload_text(a)


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
        self.single = True          # set by plan(): a single-hotel site (shared templates are this hotel's)
        self.hotel_paths = []       # set by plan() on a group site: the hotel's URL paths

    def owns(self, url):
        """Whether a page belongs to the hotel being run (always on a single-hotel site)."""
        if self.single or not self.hotel_paths:
            return True
        p = _norm(url or '/')
        p = re.sub(r'^/[a-z]{2}(?:-[a-z]{2})?/', '/', p)          # /ar/..., /en-gb/...
        return any(p.startswith('/' + h.strip('/') + '/') for h in self.hotel_paths if h.strip('/'))

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
    a = dict((item or {}).get('answer') or {})
    if (item or {}).get('sheet') == 'Rooms':
        # the booking engine's values are always right: they replace the hotel's answer where the engine has one
        eng = {k: v for k, v in (('size_m2', qm._first_num(item.get('engine_size'))),
                                 ('max_adults', qm._first_num(item.get('engine_guests')))) if v is not None}
        if 'max_adults' in eng:
            a.pop('max_children', None)
        a.update(eng)
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


def plan(group_dir, slug, only=None, ignore_unanswered=False):
    """Dry run for one hotel ('group' = the group batch: site-wide actions of a group site). On a single-hotel site
    site-wide actions are part of the hotel's own plan (batch "site-settings"). Returns batches with current -> new."""
    reg = grp.load(group_dir)
    single = grp.is_single(reg)
    if single and slug == 'group':
        slug = reg['hotels'][0]['slug']
    site = reg['group']['site']
    s = Site(site)
    s.single = bool(single)
    if not single and slug != 'group':
        s.hotel_paths = list(next((h for h in reg['hotels'] if h['slug'] == slug), {}).get('paths') or [])
    hdir = grp.site_dir(group_dir, reg) if slug == 'group' else grp.hotel_dir(group_dir, slug, reg)
    run = _latest(hdir, 'audit-')
    if not run:
        raise FileNotFoundError(f'no audit for {slug}: run the audit first')
    report = json.loads((run / ('group-summary.json' if slug == 'group' else 'audit-report.json')).read_text(
        encoding='utf-8'))
    build = run / 'build-plan.json'
    pages_spec = json.loads(build.read_text(encoding='utf-8')).get('pages', []) if build.exists() else []
    from . import questions as qm
    qstate = None
    if slug != 'group':
        qstate = qm.status(group_dir, slug)
        if qstate.get('filled_not_imported') and qstate.get('sheet'):
            # the hotel's answers are in the newest sheet but were never imported: take them in first
            imp = qm.import_answers(group_dir, slug, qstate['sheet'])
            qstate = dict(qm.status(group_dir, slug), imported_now=imp.get('answered', 0))
        if qstate.get('exists') and qstate.get('questions') and not qstate.get('answered') and not ignore_unanswered:
            waiting = _waiting_on_hotel(report, pages_spec)
            return {'needs_decision': True, 'questions': qstate, 'waiting_on_hotel': waiting,
                    'next': (f"The Questions for the Hotel sheet ({qstate['questions']} question(s)"
                             + (f", {qstate['sheet']}" if qstate.get('sheet') else '') + ') has no answers yet, and '
                             f"{waiting['findings']} finding(s) / {waiting['pages']} new page(s) wait on it. Ask the "
                             'user: did the hotel send the sheet back (then import_hotel_answers with that file and '
                             'plan again), or continue without it? Only on "continue": execute_plan(domain, slug, '
                             'ignore_unanswered=true): everything else is planned, and what waits on the hotel stays '
                             'skipped and listed. Nothing has been planned or written.')}
    qdata = qm.load(group_dir, slug) if slug != 'group' else None
    answers = {i['id']: i for i in (qdata or {}).get('items', [])}
    hold_qs = {i.get('finding_id'): i['id'] for i in answers.values() if i.get('type') == 'hold'}
    rooms_answered = any(i['sheet'] == 'Rooms' and i.get('answer') for i in answers.values())
    rewording = []
    planned, skipped, gbp_acts = [], [], []
    seen_actions = {}
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
            new_text = _new_text(a)
            if PRICE.search(new_text):
                skipped.append({'finding': fid, 'action': a['type'], 'act': a,
                                'reason': 'writes a price or discount: never changed by execute'})
                continue
            if PRICE.search(text):
                # the old text has a price and the new one doesn't (e.g. "400–1600 AED" taken out of an FAQ answer,
                # which the copy standard forbids): execute may remove a price, never write or change one
                item['note'] = 'removes a price from the page (no price is written)'
            key = json.dumps({k: v for k, v in a.items() if k not in ('pages', 'finds', 'why')}, sort_keys=True,
                             ensure_ascii=False)
            if a['type'] != 'gbp' and key in seen_actions:
                # the same change asked for by two findings (Nov 2026: "29 m² -> 20 m²" came from three agents): run it
                # once; the others follow its result instead of failing as "not found any more"
                skipped.append({'finding': fid, 'action': a['type'], 'act': a, 'same_as': seen_actions[key],
                                'reason': f"same change as {seen_actions[key]['finding']} ({seen_actions[key]['id']})"})
                continue
            seen_actions[key] = {'finding': fid, 'id': item['id']}
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
            elif a['type'] == 'redirect' and not _redirects_writable(s):
                item.update(batch='chrome', via='chrome',
                            note='the site has no redirect manager the MCP can write (neither the Redirection plugin '
                                 'nor Rank Math → Redirections is on, or Meta MCP is older than 1.7, which added Rank '
                                 'Math): add it in Rank Math → Redirections with Claude in Chrome')
            else:
                item['batch'] = 'booking-path' if sec.get('category') == 'Booking path & facts' and a['type'] != 'chrome' \
                    else (('site-settings' if single else 'group') if group_wide else TYPE_BATCH.get(a['type'], 'chrome'))
            try:
                res = _resolve(s, a, pages_spec)
            except Exception as e:  # noqa: BLE001
                skipped.append({'finding': fid, 'action': a['type'], 'act': a, 'reason': f'could not resolve: {str(e)[:200]}'})
                continue
            if a['type'] == 'schema_snippet':
                item['checks'] = list(item['checks']) + _schema_checks(res.pop('check_urls', []))
            for k, part in enumerate(_split(res)):
                it = dict(item, **part)
                if part.get('batch_override'):
                    it['batch'] = it.pop('batch_override')
                if 'checks_extra' in it:
                    it['checks'] = list(it['checks']) + it.pop('checks_extra')
                if k:
                    n += 1
                    it['id'] = f'a{n}'
                it['validation'] = _validate_calls(s, it.get('calls') or [])
                if it['validation'].get('ok') is False:
                    skipped.append({'finding': fid, 'action': a['type'], 'act': a,
                                    'reason': 'the site rejected it in a dry run: ' + it['validation'].get('error', '')})
                    continue
                _note_translations(s, it)
                planned.append(it)
    if qdata:
        for c in _expand_corrections(qm.corrections(group_dir, slug), s):
            n += 1
            pages = c.get('pages') or [c['url']]
            finds = c.get('finds') or {}
            by_engine = c.get('source') == 'booking engine'      # no sheet answer: the site follows the engine
            item = {'id': f'a{n}', 'finding': c.get('finding') or f"hotel-answer-{c['question']}", 'title': c['why'],
                    'category': 'Booking path & facts' if by_engine else 'Hotel answers', 'action': c,
                    'batch': 'booking-path' if by_engine else 'hotel-answers',
                    'checks': [x for p in pages for x in (
                        {'type': 'text_present', 'url': p, 'text': c['replace']},
                        {'type': 'text_absent', 'url': p, 'text': finds.get(p, c['find'])})]}
            try:
                res = _resolve(s, c, pages_spec)
            except Exception as e:  # noqa: BLE001
                skipped.append({'finding': item['finding'], 'action': 'text_replace', 'page': c['url'],
                                'find': c['find'], 'replace': c['replace'],
                                'reason': f'could not change it through MCP: {str(e)[:200]}'})
                continue
            for k, part in enumerate(_split(res)):
                it = dict(item, **part)
                if part.get('batch_override'):
                    it['batch'] = it.pop('batch_override')
                if k:
                    n += 1
                    it['id'] = f'a{n}'
                it['validation'] = _validate_calls(s, it.get('calls') or [])
                if it['validation'].get('ok') is False:
                    skipped.append({'finding': item['finding'], 'action': 'text_replace', 'page': c['url'],
                                    'find': c['find'], 'replace': c['replace'],
                                    'reason': 'the site rejected it in a dry run: ' + it['validation'].get('error', '')})
                    continue
                _note_translations(s, it)
                planned.append(it)
    if slug != 'group' and not any(x['action'].get('field') == 'website' for x in gbp_acts):
        hotel = next((h for h in reg['hotels'] if h['slug'] == slug), {})
        hotel_url = site.rstrip('/') + ('/' if single else '/' + ((hotel.get('paths') or ['/'])[0]).lstrip('/'))
        gbp_acts += [x for x in _gbp_report_actions(hdir, hotel_url)
                     if not only or x['finding'] in only or x['category'] in only]
    replies = None
    if slug != 'group':
        from . import gbp_reviews
        sheet = gbp_reviews.latest_sheet(hdir)
        if sheet and (not only or 'gbp-review-replies' in only or 'Local' in only):
            try:
                replies = gbp_reviews.read_sheet(sheet)
            except Exception as e:  # noqa: BLE001 - a broken sheet: say so, plan the rest
                replies = {'xlsx': str(sheet), 'replies': [], 'problems': [f'the review sheet could not be read: {e}']}
    gbp_items, gbp_skipped, gbp_note, n = _gbp_plan(group_dir, slug, hdir, gbp_acts, n, replies)
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
           'units': prefs.get('units'), **({'business_profile': gbp_note} if gbp_note else {}),
           **({'questions': qstate} if qstate and qstate.get('exists') else {}),
           **({'questions_ignored': True} if ignore_unanswered else {})}
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
            **({'questions': qstate} if qstate and qstate.get('exists') else {}),
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


DRY_RUN_TOOLS = {'seo-update-posts', 'seo-update-settings', 'replace-text'}


def _waiting_on_hotel(report, pages_spec):
    """How much of the audit waits on the hotel's answers: findings with a [CONFIRM ...] marker or a hold, and Build
    Plan pages held for the hotel."""
    n = sum(1 for sec in report.get('sections', [])
            if sec.get('hold') or '[CONFIRM' in json.dumps(sec.get('actions') or [], ensure_ascii=False))
    pages = sum(1 for p in pages_spec if p.get('hold') or '[CONFIRM' in json.dumps(p, ensure_ascii=False))
    return {'findings': n, 'pages': pages}


def _split(res):
    """_resolve gives one plan item, or several under "parts" (e.g. a shared template on a group site)."""
    return res['parts'] if 'parts' in res else [res]


def _expand_corrections(corr, s):
    """A phone correction covering several pages ("pages") is one replace-text item; a site without replace-text
    gets one item per page, as before."""
    if 'replace-text' in s.tools and 'find-text' in s.tools:
        return corr
    out = []
    for c in corr:
        if not c.get('pages'):
            out.append(c)
            continue
        for p in c['pages']:
            out.append({k: v for k, v in c.items() if k not in ('pages', 'finds', 'sitewide', 'match_mode')}
                       | {'url': p, 'find': (c.get('finds') or {}).get(p, c['find'])})
    return out


def _validate_calls(s, calls):
    """Ask the site to validate changes without saving them, where the tool has dry_run."""
    checked = []
    for tool, args in calls:
        if tool in DRY_RUN_TOOLS:
            try:
                res = s.write(tool, dict(args, dry_run=True))
                errs = res.get('errors') or res.get('failed') or {}
                if errs or res.get('success') is False:
                    return {'ok': False, 'error': json.dumps(errs or res, ensure_ascii=False)[:300]}
                if tool == 'replace-text' and not (res.get('would_replace') or res.get('total_matches')):
                    return {'ok': False, 'error': f'"{args.get("find")}" was not found any more (already changed?)'}
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
        for v in a.get('variants') or []:
            if mid:
                break
            mid, alt = _media(s.site, v)
        if not mid and 'find-text' in s.tools and 'replace-text' in s.tools:
            # not a Media Library image: an <img> written into a text / HTML widget or the post content gets its alt
            # in the tag itself (update-media can't reach it, and the page would keep alt="")
            inline = _alt_inline(s, a)
            if inline:
                return inline
        item = {'id': mid} if mid else {'url': a['image']}
        return {'page': a['image'], 'field': 'alt', 'current': alt, 'new': a['alt'],
                'calls': [['update-media', {'items': [dict({'attachment_id': mid} if mid else {'url': a['image']},
                                                            alt_text=a['alt'])]}]],
                'undo': [['update-media', {'items': [dict({'attachment_id': mid} if mid else {'url': a['image']},
                                                           alt_text=alt or '')]}]] if alt is not None else None,
                'media': item}
    if t == 'post_content':
        no_jsonld(a['content'], 'the page content')
        pid = s.post_id(a['url'])
        cur = s.read('get-post', {'post_id': pid, 'include_elementor': True})
        post = cur.get('post') or cur
        if (post.get('elementor') or {}).get('element_count'):
            return _elementor_body(s, a, pid)
        old = post.get('content', '')
        return {'page': a['url'], 'post_id': pid, 'field': 'content', 'current': old[:300], 'new': a['content'][:300],
                'calls': [['update-post', {'post_id': pid, 'content': a['content']}]],
                'undo': [['update-post', {'post_id': pid, 'content': old}]]}
    if t == 'elementor_text':
        no_jsonld(a['settings'], 'the Elementor settings')
        pid = s.post_id(a['url'])
        st = s.read('elementor-get-structure', {'post_id': pid, 'search': a['find'][:60], 'include_settings': True})
        els = st.get('elements') or []
        where, shared = pid, None
        if not els and 'find-text' in s.tools:
            # not on the page itself: a header / footer / global widget template (find-text searches them all)
            where, el_id, shared = _find_element(s, a['find'])
            st = s.read('elementor-get-structure', {'post_id': where, 'search': a['find'][:60],
                                                    'include_settings': True})
            els = [e for e in st.get('elements') or [] if e.get('id') == el_id]
        if len(els) != 1:
            raise LookupError(f'"{a["find"][:60]}" matches {len(els)} Elementor elements on {a["url"]}: needs one')
        el = els[0]
        settings = _rendered_settings(el, a['settings'])
        old = {k: (el.get('settings') or {}).get(k) for k in settings}
        out = {'page': a['url'] if not shared else f"{shared['title']} (template, shows on many pages)",
               'post_id': where, 'field': 'elementor ' + ', '.join(settings), 'current': old,
               'new': settings, 'calls': [['elementor-update-element', {'post_id': where, 'element_id': el['id'],
                                                                         'settings': settings}]],
               'undo': [['elementor-update-element', {'post_id': where, 'element_id': el['id'], 'settings': old}]]}
        if shared:
            out['shared'] = shared['shared']
            if not s.single:
                out['batch_override'] = 'group'
        return out
    if t == 'schema_snippet':
        cur = None
        if a.get('replace_snippet_id'):
            cur = s.read('elementor-get-custom-code', {'post_id': a['replace_snippet_id']})
        code = schema_code(a['code'])
        conds, check_urls = [], []
        for c in a['conditions']:
            if str(c).startswith('page:'):
                url = c.split(':', 1)[1]
                check_urls.append(url)
                if _norm(url) == '/':
                    conds.append('include/singular/front_page')
                else:
                    try:
                        pid = s.post_id(url)
                        conds.append(f"include/singular/{s.types.get(_norm(url), 'page')}/{pid}")
                    except LookupError:
                        # an Arabic / Russian room page the REST lookup can't place (Nov 2026: 8 AR/RU room schema
                        # snippets parked): Meta MCP 1.6+ resolves a page URL in a condition itself, against the
                        # post's own permalink, and refuses one that matches no page
                        conds.append('include:' + url)
            else:
                conds.append(c)
                if 'general' in str(c):
                    check_urls.append('/')
        args = {'title': a['title'], 'code': code, 'conditions': conds, 'status': 'publish',
                'location': 'elementor_head'}
        if a.get('replace_snippet_id'):
            args['post_id'] = a['replace_snippet_id']
        old = (cur or {}).get('snippet') or cur
        return {'page': ', '.join(a['conditions']), 'field': 'schema snippet', 'current': (old or {}).get('code', '')[:200]
                if isinstance(old, dict) else None, 'new': code[:200],
                'calls': [['elementor-set-custom-code', args]], 'check_urls': check_urls or ['/'],
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
        content = spec.get('content_html') or _copy_html(spec.get('copy', ''))
        no_jsonld(content, f"the copy of page {a['page_id']}")
        jsonld = schema_code(spec['jsonld']) if spec.get('jsonld') else None
        return {'page': spec.get('url'), 'field': 'new page', 'current': None,
                'new': {k: spec.get(k) for k in ('title', 'url', 'seo_title', 'meta_description')},
                'calls': [['create-post', {'post_type': spec.get('post_type', 'page'), 'title': spec['title'],
                                           'slug': spec['url'].strip('/').split('/')[-1],
                                           'content': content, 'status': 'publish'}]],
                'then': {'seo_fields': {k: spec[k] for k in ('seo_title', 'meta_description') if spec.get(k)},
                         'schema': jsonld}, 'undo': 'draft-created',
                **({'checks_extra': _schema_checks([spec['url']])} if jsonld else {})}
    if t == 'text_replace':
        no_jsonld(a['replace'], 'the replacement text')
        if 'replace-text' in s.tools and 'find-text' in s.tools:
            return _resolve_replace_text(s, a)
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
    if t == 'elementor_widget':
        return _resolve_widget(s, a)
    if t == 'heading_level':
        return _resolve_heading(s, a)
    if t == 'link_text':
        return _resolve_link_text(s, a)
    if t == 'insert_text':
        return _resolve_insert(s, a)
    if t == 'phone_link':
        return _resolve_phone_link(s, a)
    if t == 'chrome':
        return {'page': a['where'], 'field': 'Claude in Chrome', 'current': None, 'new': a['steps'], 'calls': [],
                'via': 'chrome', 'undo': 'manual: reverse the steps by hand'}
    raise ValueError(f'unknown action type {t}')


def _match_setting(m):
    """The setting a find-text match is in: "editor", "icon_list.2.text", "link.url". Meta MCP names it "setting"."""
    return str(m.get('setting') or m.get('path') or '')


def _find_posts(s, args):
    """find-text, following the cursor: every post with a match."""
    posts, after = [], 0
    for _ in range(20):
        res = s.read('find-text', dict(args, limit=200, **({'after_id': after} if after else {})))
        posts += res.get('posts') or []
        if not res.get('more'):
            break
        after = res.get('next_after_id') or 0
    return posts, res.get('notes') or []


def _find_element(s, find):
    """(post id, element id, shared summary or None) of the one Elementor element anywhere on the site (pages and
    templates) whose text contains find; LookupError when there is none or more than one."""
    posts, _ = _find_posts(s, {'find': find, 'fields': ['elementor']})
    hits = {(p['post_id'], m.get('element_id')): p for p in posts for m in p.get('matches') or []
            if m.get('field') == 'elementor' and m.get('element_id')}
    if len(hits) != 1:
        where = ', '.join(f"{p.get('title')} ({p.get('post_type')})" for p in {k[0]: v for k, v in hits.items()}.values())
        raise LookupError(f'"{find[:60]}" is in {len(hits)} Elementor elements on the site'
                          + (f' ({where[:200]})' if where else '') + ': needs exactly one')
    (pid, el_id), p = next(iter(hits.items()))
    return pid, el_id, ({'title': p.get('title'), 'shared': p['shared']} if p.get('shared') else None)


def _resolve_replace_text(s, a):
    """A text replacement through find-text / replace-text: the text is found wherever it is stored (page fields,
    Elementor widgets, header / footer / global templates, Custom Code, menus) and replaced only in the posts this
    hotel owns. A page-specific fix (url) changes that page and the shared templates that print the text on it; a
    site-wide one ("sitewide" / "pages", e.g. a phone number) every page of the hotel. On a group site shared
    templates show on other hotels' pages too: they become a separate item in the group batch."""
    mode = 'phone' if a.get('match_mode') == 'phone' else 'exact'
    base = {'find': a['find'], 'match_mode': mode}
    if a.get('language'):
        base['language'] = a['language']
    sitewide = bool(a.get('sitewide') or a.get('pages'))
    page_pid = None if sitewide else s.post_id(a['url'])
    posts, notes = _find_posts(s, base)
    own, shared, other = [], [], []
    for p in posts:
        if p.get('shared'):
            shared.append(p)
        elif (page_pid is not None and p['post_id'] == page_pid) or (page_pid is None and s.owns(p.get('url', ''))):
            own.append(p)
        else:
            other.append(p)
    if not own and not shared:
        raise LookupError(f'"{a["find"]}" was not found in any editable text of this hotel\'s pages'
                          + (f' (only on {len(other)} other page(s))' if other else '')
                          + (f": {'; '.join(notes)[:200]}" if notes else '')
                          + ' (it may come from the booking engine or an image)')

    def where(ps):
        return [f"{p.get('title') or p.get('post_type')}: " + ', '.join(sorted({
            _match_setting(m) or m.get('field', '') for m in p.get('matches') or []}))[:120] for p in ps]

    def item(ps, label):
        ids = sorted({int(p['post_id']) for p in ps})
        args = dict(base, replace=a['replace'], post_ids=ids, max_posts=min(200, max(len(ids), 1)))
        undo = dict(base, find=a['replace'], replace=a['find'], post_ids=ids, max_posts=args['max_posts'])
        if mode == 'phone':
            undo['match_mode'] = 'phone'
        return {'page': label, 'post_ids': ids, 'field': 'text' + (' (phone, every format)' if mode == 'phone' else ''),
                'current': {'find': a['find'], 'found_in': where(ps)}, 'new': a['replace'],
                'calls': [['replace-text', args]],
                # a deletion (empty replacement) has nothing to search for again: put it back by hand
                'undo': [['replace-text', undo]] if a['replace'] else f'manual: add back "{a["find"]}"',
                **({'post_id': ids[0]} if len(ids) == 1 else {}), **({'notes': notes} if notes else {})}
    label = 'every page of the hotel' if sitewide else a['url']
    if s.single or not shared:
        it = item(own + shared, label)
        if shared:
            it['shared'] = [p.get('title') for p in shared]
        if other:
            it['left_alone'] = f'{len(other)} other page(s) with the same text (not this hotel / not this page)'
        return it
    parts = [item(own, label)] if own else []
    parts.append(dict(item(shared, 'shared templates / snippets / menus: ' + ', '.join(
        p.get('title') or '' for p in shared)[:160]), batch_override='group',
        shared=[{'title': p.get('title'), 'conditions': p.get('conditions'), 'why': p.get('shared')} for p in shared]))
    return {'parts': parts}


TEXT_TYPES = {'text_replace', 'elementor_text', 'post_content', 'elementor_widget'}


def _note_translations(s, it):
    """A page's text changed in one language: its Polylang translations (Arabic, Russian...) keep the old wording
    until someone writes theirs natively (/hotel-seo write), so the item lists them and the Execute Report shows them
    as still to do: not a find / replace in another language, and not agency work."""
    if it['action'].get('type') not in TEXT_TYPES or not it.get('post_id') or it.get('batch') == 'group':
        return
    if 'polylang-get-post-translations' not in s.tools:
        return
    cache = s.__dict__.setdefault('_translations', {})
    pid = int(it['post_id'])
    if pid not in cache:
        try:
            tr = s.read('polylang-get-post-translations', {'post_id': pid}).get('translations') or {}
        except Exception:  # noqa: BLE001 - only a note
            tr = {}
        cache[pid] = {lang: t.get('link') for lang, t in tr.items() if isinstance(t, dict) and int(t.get('id') or 0) != pid}
    if cache[pid]:
        it['translations'] = cache[pid]


# the setting that holds a widget's heading tag
HEADING_KEY = {'heading': 'header_size', 'theme-page-title': 'header_size', 'theme-post-title': 'header_size',
               'woocommerce-product-title': 'header_size', 'icon-box': 'title_size', 'image-box': 'title_size',
               'call-to-action': 'title_tag', 'animated-headline': 'tag', 'flip-box': 'title_html_tag'}
HEADING_DEFAULT = {'header_size': 'h2', 'title_size': 'h3', 'title_tag': 'h2', 'tag': 'h3', 'title_html_tag': 'h3'}


def _element_by_text(s, pid, find, url):
    """(post id, element, shared summary or None) of the one Elementor element showing `find`: on the page, else in
    the template that prints it (find-text)."""
    st = s.read('elementor-get-structure', {'post_id': pid, 'search': find[:60], 'include_settings': True})
    els = st.get('elements') or []
    if len(els) == 1:
        return pid, els[0], None
    if not els and 'find-text' in s.tools:
        where, el_id, shared = _find_element(s, find)
        st = s.read('elementor-get-structure', {'post_id': where, 'search': find[:60], 'include_settings': True})
        els = [e for e in st.get('elements') or [] if e.get('id') == el_id]
        if len(els) == 1:
            return where, els[0], shared
    raise LookupError(f'"{find[:60]}" matches {len(els)} Elementor elements on {url}: needs one')


def _resolve_heading(s, a):
    """A heading's tag one step below the heading before it (H1 -> H2, not H3), set on the widget's own tag setting:
    the look comes from the widget style, so nothing changes visually. {"type": "heading_level", "url", "find":
    heading text, "level": 2}."""
    pid = s.post_id(a['url'])
    where, el, shared = _element_by_text(s, pid, a['find'], a['url'])
    wtype = el.get('widget_type') or el.get('widgetType') or ''
    sett = el.get('settings') or {}
    key = HEADING_KEY.get(wtype) or ('header_size' if 'header_size' in sett else None)
    if not key:
        raise LookupError(f'"{a["find"][:60]}" is in a {wtype or "widget"} with no heading-tag setting')
    level = int(a['level'])
    if not 1 <= level <= 6:
        raise ValueError(f'level {level} is not a heading level')
    old = sett.get(key) or HEADING_DEFAULT.get(key, 'h2')
    new = {key: f'h{level}'}
    out = {'page': a['url'] if not shared else f"{shared['title']} (template, shows on many pages)",
           'post_id': where, 'field': f'heading tag ({wtype})', 'current': {key: old}, 'new': new,
           'calls': [['elementor-update-element', {'post_id': where, 'element_id': el['id'], 'settings': new}]],
           'undo': [['elementor-update-element', {'post_id': where, 'element_id': el['id'], 'settings': {key: old}}]]}
    if shared and not s.single:
        out['batch_override'] = 'group'
    return out


def _links_in(settings):
    """[(path, url)] of every link setting in an element's settings (link, button link, repeater rows)."""
    out = []

    def walk(v, path, key):
        if isinstance(v, dict):
            if 'link' in key.lower() and isinstance(v.get('url'), str) and v['url']:
                out.append((path, v['url']))
            for k, x in v.items():
                walk(x, f'{path}.{k}' if path else k, str(k))
        elif isinstance(v, list):
            for i, x in enumerate(v):
                walk(x, f'{path}.{i}', key)
    walk(settings or {}, '', '')
    return out


def _resolve_link_text(s, a):
    """Generic link text ("view more", "read more") renamed after the page it opens. On the page: the button / box /
    link widget whose link goes to `href` and whose text is `find` gets `new_text`. In a loop-card template (one
    button for every card): the button shows each card's own post title (Elementor's Post Title dynamic tag), so
    every card says where it goes. {"type": "link_text", "url", "href", "find": "view more", "new_text"}."""
    pid = s.post_id(a['url'])
    want = _norm(a['href'])
    st = s.read('elementor-get-structure', {'post_id': pid, 'include_settings': True})
    calls, undo = [], []
    for el in st.get('elements') or []:
        sett = el.get('settings') or {}
        if not any(_norm(u) == want for _, u in _links_in(sett)):
            continue
        for k in TEXT_KEYS:
            if isinstance(sett.get(k), str) and re.sub(r'<[^>]+>', '', sett[k]).strip().lower() == a['find'].strip().lower():
                calls.append(['elementor-update-element', {'post_id': pid, 'element_id': el['id'],
                                                           'settings': {k: a['new_text']}}])
                undo.append(['elementor-update-element', {'post_id': pid, 'element_id': el['id'],
                                                          'settings': {k: sett[k]}}])
                break
    if calls:
        return {'page': a['url'], 'post_id': pid, 'field': 'link text', 'current': a['find'], 'new': a['new_text'],
                'calls': calls, 'undo': undo}
    if 'find-text' not in s.tools:
        raise LookupError(f'no link to {a["href"]} with the text "{a["find"]}" on {a["url"]}')
    # not on the page: a loop / card template prints it
    posts, _ = _find_posts(s, {'find': a['find'], 'fields': ['elementor']})
    loops = [p for p in posts if p.get('template_type') in ('loop-item', 'loop') or 'loop' in str(p.get('title', '')).lower()]
    for p in loops:
        tid = int(p['post_id'])
        tst = {e.get('id'): e for e in s.read('elementor-get-structure', {'post_id': tid, 'include_settings': True})
               .get('elements') or []}
        for m in p.get('matches') or []:
            el = tst.get(m.get('element_id')) or {}
            key = _match_setting(m).split('.')[0]
            if key not in TEXT_KEYS:
                continue
            dyn = dict((el.get('settings') or {}).get('__dynamic__') or {})
            if key in dyn:
                continue
            tag = ElementorTag.post_title()
            calls.append(['elementor-update-element', {'post_id': tid, 'element_id': el['id'],
                                                       'settings': {'__dynamic__': dict(dyn, **{key: tag})}}])
            undo.append(['elementor-update-element', {'post_id': tid, 'element_id': el['id'],
                                                      'settings': {'__dynamic__': dyn or {}}}])
        if calls:
            out = {'page': f"{p.get('title')} (loop card template)", 'post_id': tid,
                   'field': 'button text = each card\'s post title', 'current': a['find'], 'new': '(post title)',
                   'calls': calls, 'undo': undo, 'shared': [p.get('title')]}
            if not s.single:
                out['batch_override'] = 'group'
            return out
    raise LookupError(f'no link to {a["href"]} with the text "{a["find"]}" on {a["url"]} or in a loop template')


class ElementorTag:
    """Elementor dynamic-tag values (the "__dynamic__" settings Elementor Pro stores)."""

    @staticmethod
    def post_title():
        import secrets
        return f'[elementor-tag id="{secrets.token_hex(4)[:7]}" name="post-title" settings="%7B%7D"]'


def _resolve_insert(s, a):
    """Text the page doesn't have yet (an intro under the H1, a lead paragraph, a new section): a text-editor widget
    inserted after the page's H1, or before / after the element showing `anchor` (elementor-insert-element, Meta MCP
    1.7). On a page not built with Elementor the text goes at the top of the post content. Skipped when its first
    words are already on the page. {"type": "insert_text", "url", "html" (or "text"), "anchor": optional text of the
    element to insert next to, "position": "after" (default) | "before"}."""
    html_in = a.get('html') or _copy_html(a.get('text') or '')
    no_jsonld(html_in, 'the new text')
    pid = s.post_id(a['url'])
    probe = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', html_in)).strip()[:50]
    if probe and 'find-text' in s.tools:
        have = s.read('find-text', {'find': probe, 'post_ids': [pid], 'fields': ['content', 'elementor']})
        if have.get('total_matches') or have.get('posts'):
            raise LookupError('the text is already on the page')
    cur = s.read('get-post', {'post_id': pid, 'include_elementor': True})
    post = cur.get('post') or cur
    if not (post.get('elementor') or {}).get('element_count'):
        old = post.get('content', '') or ''
        return {'page': a['url'], 'post_id': pid, 'field': 'new text (top of the content)', 'current': None,
                'new': html_in[:300], 'calls': [['update-post', {'post_id': pid, 'content': html_in + '\n' + old}]],
                'undo': [['update-post', {'post_id': pid, 'content': old}]]}
    st = s.read('elementor-get-structure', {'post_id': pid, 'include_settings': True})
    els = st.get('elements') or []
    position = a.get('position') or 'after'
    if a.get('anchor'):
        anchor = [e for e in els if a['anchor'].lower() in json.dumps(e.get('settings') or {}, ensure_ascii=False).lower()
                  and (e.get('el_type') or e.get('elType')) == 'widget']
        if len(anchor) != 1:
            raise LookupError(f'"{a["anchor"][:60]}" is in {len(anchor)} widgets on {a["url"]}: needs one')
        args = {'anchor_id': anchor[0]['id'], 'position': position}
        where = f'{position} "{a["anchor"][:40]}"'
    else:
        h1 = [e for e in els if (e.get('widget_type') or e.get('widgetType')) in HEADING_KEY
              and str((e.get('settings') or {}).get(HEADING_KEY[e.get('widget_type') or e.get('widgetType')], '')) == 'h1']
        if h1:
            args, where = {'anchor_id': h1[0]['id'], 'position': 'after'}, 'under the H1'
        else:
            args, where = {'position': 'page_start'}, 'at the top of the page content (the H1 comes from the template)'
    call = dict(args, post_id=pid, element={'widgetType': 'text-editor', 'settings': {'editor': html_in}})
    return {'page': a['url'], 'post_id': pid, 'field': f'new text {where}', 'current': None, 'new': html_in[:300],
            'calls': [['elementor-insert-element', call]], 'undo': 'delete-inserted'}


def _resolve_widget(s, a):
    """Settings of one Elementor widget chosen by its type on the page (e.g. the Google Maps widget, whose location is
    its "address" setting, not a URL in the page text: Nov 2026, replace-text could not move the contact-page map).
    {"type": "elementor_widget", "url", "widget_type": "google_maps", "settings": {"address": "25.5719418,
    56.3435306"}, "find": optional text to pick one when the page has several}."""
    no_jsonld(a['settings'], 'the Elementor settings')
    pid = s.post_id(a['url'])
    st = s.read('elementor-get-structure', {'post_id': pid, 'include_settings': True})
    want = str(a.get('widget_type') or '').replace('-', '_')
    els = [e for e in st.get('elements') or []
           if str(e.get('widget_type') or e.get('widgetType') or '').replace('-', '_') == want]
    if a.get('find') and len(els) > 1:
        els = [e for e in els if a['find'].lower() in json.dumps(e.get('settings') or {}, ensure_ascii=False).lower()]
    if len(els) != 1:
        raise LookupError(f"{len(els)} {a.get('widget_type')} widgets on {a['url']}: needs exactly one"
                          + ('' if a.get('find') else ' (give "find": text from its current settings)'))
    el = els[0]
    old = {k: (el.get('settings') or {}).get(k) for k in a['settings']}
    return {'page': a['url'], 'post_id': pid, 'field': f"{a.get('widget_type')} " + ', '.join(a['settings']),
            'current': old, 'new': a['settings'],
            'calls': [['elementor-update-element', {'post_id': pid, 'element_id': el['id'], 'settings': a['settings']}]],
            'undo': [['elementor-update-element', {'post_id': pid, 'element_id': el['id'], 'settings': old}]]}


PHONE_RUN = re.compile(r'(?<![\w/:=])\+?\d[\d\s().\- ]{6,}\d(?![\w/])')
HTML_SPLIT = re.compile(r'(<a\b[^>]*>.*?</a>|<[^>]+>)', re.I | re.S)
RICH_KEYS = {'editor', 'html', 'description', 'description_text'}


def _digits9(v):
    d = re.sub(r'\D', '', str(v or ''))
    return d[-9:] if len(d) >= 7 else ''


def tel_href(phone):
    d = re.sub(r'\D', '', str(phone or ''))
    return 'tel:' + ('+' + d.lstrip('0') if str(phone).strip().startswith(('+', '00')) else d)


def link_phone(html_text, phone):
    """The text with each written-out occurrence of the phone number wrapped in <a href="tel:...">; numbers already
    inside a link, a tag or an attribute are left alone."""
    want, href, n = _digits9(phone), tel_href(phone), 0
    parts = HTML_SPLIT.split(html_text or '')
    for i, part in enumerate(parts):
        if i % 2:                                 # a tag or a whole <a>...</a>: never touched
            continue

        def wrap(m):
            nonlocal n
            if _digits9(m.group(0)) != want:
                return m.group(0)
            n += 1
            return f'<a href="{href}">{m.group(0)}</a>'
        parts[i] = PHONE_RUN.sub(wrap, part)
    return ''.join(parts), n


def _resolve_phone_link(s, a):
    """Make the hotel's phone number a tel: link wherever it is written out as plain text: rich-text widgets (text
    editor, HTML) get the <a href="tel:"> wrapped round the number; a heading, button or icon-list row that shows the
    number gets its own link set to tel: when it has none. Never Custom Code (the Hotel schema's "telephone" must stay
    plain JSON: Nov 2026, a blind sitewide wrap would have broken the JSON-LD), menus or titles.
    {"type": "phone_link", "phone": "+971 7 228 2222", "url": optional page (default every page of the hotel)}."""
    phone = a['phone']
    href = tel_href(phone)
    page_pid = s.post_id(a['url']) if a.get('url') else None
    posts, notes = _find_posts(s, {'find': phone, 'match_mode': 'phone', 'fields': ['elementor', 'content']})
    calls, undo, ids, left, structs = [], [], set(), [], {}
    for p in posts:
        pid = int(p['post_id'])
        if page_pid is not None and pid != page_pid and not p.get('shared'):
            continue
        if not (s.single or p.get('shared') or s.owns(p.get('url', ''))):
            continue
        if p.get('shared') and not s.single:
            left.append(f"{p.get('title')} (shared template on a group site: group batch)")
            continue
        matches = p.get('matches') or []
        if any(m.get('field') == 'content' for m in matches) and not any(m.get('field') == 'elementor' for m in matches):
            cur = s.read('get-post', {'post_id': pid, 'include_elementor': False})
            content = (cur.get('post') or cur).get('content', '') or ''
            new, n = link_phone(content, phone)
            if n:
                calls.append(['update-post', {'post_id': pid, 'content': new}])
                undo.append(['update-post', {'post_id': pid, 'content': content}])
                ids.add(pid)
            continue
        by_el = {}
        for m in matches:
            if m.get('field') == 'elementor' and m.get('element_id'):
                by_el.setdefault(m['element_id'], []).append(m)
        if by_el and pid not in structs:
            structs[pid] = {e.get('id'): e for e in s.read('elementor-get-structure', {
                'post_id': pid, 'include_settings': True}).get('elements') or []}
        for el_id, ms in by_el.items():
            el = structs.get(pid, {}).get(el_id) or {}
            sett = el.get('settings') or {}
            wtype = el.get('widget_type') or el.get('widgetType') or ''
            new = {}
            for m in ms:
                path = _match_setting(m)
                top = path.split('.')[0]
                if top in RICH_KEYS and isinstance(sett.get(top), str):
                    val, n = link_phone(new.get(top, sett[top]), phone)
                    if n:
                        new[top] = val
                elif wtype in ('heading', 'button') and top in ('title', 'text') and \
                        not (sett.get('link') or {}).get('url'):
                    new['link'] = dict(sett.get('link') or {}, url=href)
                elif re.fullmatch(r'(icon_list|social_icon_list)\.\d+\.text', path):
                    key, row = top, int(path.split('.')[1])
                    rows = [dict(r) for r in (new.get(key) or sett.get(key) or [])]
                    if row < len(rows) and not (rows[row].get('link') or {}).get('url'):
                        rows[row]['link'] = dict(rows[row].get('link') or {}, url=href)
                        new[key] = rows
                elif path.endswith('url') or path.endswith('link'):
                    continue                     # already a link (tel:, WhatsApp): nothing to do
                else:
                    left.append(f"{p.get('title')}: {wtype or 'widget'} {path}")
            if new:
                calls.append(['elementor-update-element', {'post_id': pid, 'element_id': el_id, 'settings': new}])
                undo.append(['elementor-update-element', {'post_id': pid, 'element_id': el_id,
                                                          'settings': {k: sett.get(k) for k in new}}])
                ids.add(pid)
    if not calls:
        raise LookupError(f'"{phone}" is not written out as plain text anywhere this tool can link it'
                          + (f" ({'; '.join(left)[:200]})" if left else '') + (f": {'; '.join(notes)[:150]}" if notes else ''))
    out = {'page': a.get('url') or 'every page of the hotel', 'field': f'phone as a {href} link',
           'current': phone, 'new': href, 'calls': calls, 'undo': undo, 'post_ids': sorted(ids)}
    if left:
        out['left_alone'] = left
    return out


IMG_TAG = re.compile(r'<img\b[^>]*>', re.I)


def _with_alt(tag, alt):
    """The <img> tag with alt set (an empty or missing alt replaced)."""
    val = html.escape(alt, quote=True)
    if re.search(r'\balt\s*=\s*"[^"]*"', tag, re.I):
        return re.sub(r'\balt\s*=\s*"[^"]*"', f'alt="{val}"', tag, count=1, flags=re.I)
    if re.search(r"\balt\s*=\s*'[^']*'", tag, re.I):
        return re.sub(r"\balt\s*=\s*'[^']*'", f'alt="{val}"', tag, count=1, flags=re.I)
    return re.sub(r'^<img\b', f'<img alt="{val}"', tag, count=1, flags=re.I)


def _setting_at(settings, path):
    cur = settings
    for part in str(path or '').split('.'):
        if isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        elif isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def _alt_inline(s, a):
    """replace-text calls that put the alt into the <img> tags of this image written in post content or an Elementor
    text / HTML setting (pages and templates). None when the image is not in any editable text."""
    name = urlparse(a['image']).path.rsplit('/', 1)[-1]
    stem = re.sub(r'(?:-\d+x\d+)?\.\w+$', '', re.sub(r'\.(?:webp|avif)$', '', name))
    if len(stem) < 4:
        return None
    posts, _ = _find_posts(s, {'find': stem, 'fields': ['content', 'elementor']})
    tags = {}                                   # old tag -> post ids
    for p in posts:
        if not (s.single or p.get('shared') or s.owns(p.get('url', ''))):
            continue
        texts = []
        for m in p.get('matches') or []:
            if m.get('field') == 'content':
                cur = s.read('get-post', {'post_id': p['post_id'], 'include_elementor': False})
                texts.append((cur.get('post') or cur).get('content', ''))
            elif m.get('field') == 'elementor' and m.get('element_id'):
                st = s.read('elementor-get-structure', {'post_id': p['post_id'], 'include_settings': True})
                el = next((e for e in st.get('elements') or [] if e.get('id') == m['element_id']), None)
                v = _setting_at((el or {}).get('settings') or {}, _match_setting(m))
                if isinstance(v, str):
                    texts.append(v)
        for text in texts:
            for tag in IMG_TAG.findall(text or ''):
                if stem in tag and not re.search(r'\balt\s*=\s*["\'][^"\']+["\']', tag, re.I):
                    tags.setdefault(tag, set()).add(int(p['post_id']))
    if not tags:
        return None
    calls, undo, ids = [], [], set()
    for tag, pids in tags.items():
        new = _with_alt(tag, a['alt'])
        base = {'match_mode': 'exact', 'post_ids': sorted(pids), 'max_posts': min(200, len(pids))}
        calls.append(['replace-text', dict(base, find=tag, replace=new)])
        undo.append(['replace-text', dict(base, find=new, replace=tag)])
        ids |= pids
    return {'page': a['image'], 'field': 'alt (in the <img> tag)', 'current': '', 'new': a['alt'],
            'calls': calls, 'undo': undo, 'post_ids': sorted(ids)}


def _elementor_body(s, a, pid):
    """New body copy for a page built with Elementor: update-post would save text the page never shows. The copy goes
    into the page's one text-editor widget; with none or several, say which one with an elementor_text action."""
    st = s.read('elementor-get-structure', {'post_id': pid, 'include_settings': True})
    eds = [e for e in st.get('elements') or [] if (e.get('widget_type') or e.get('widgetType')) == 'text-editor']
    if len(eds) != 1:
        raise LookupError(f"{a['url']} is built with Elementor and has {len(eds)} text widgets: the copy can't go in "
                          'post content (the page would not show it). Give an elementor_text action with find = the '
                          'current text of the widget to change')
    el = eds[0]
    old = (el.get('settings') or {}).get('editor')
    new = a['content'] if a['content'].lstrip().startswith('<') else _copy_html(a['content'])
    return {'page': a['url'], 'post_id': pid, 'field': 'elementor text (page body)', 'current': (old or '')[:300],
            'new': new[:300], 'calls': [['elementor-update-element', {'post_id': pid, 'element_id': el['id'],
                                                                       'settings': {'editor': new}}]],
            'undo': [['elementor-update-element', {'post_id': pid, 'element_id': el['id'],
                                                   'settings': {'editor': old or ''}}]]}


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
    todo = [it for it in items if it.get('via') != 'chrome' and it['id'] not in pl.get('done', [])]
    sent, refused = _send_media_chunks(s, todo) if batch == 'alt-text' else ({}, {})
    media_failed = []
    try:
        for it in todo:
            before[it['id']] = {'current': it.get('current'), 'undo': it.get('undo'), 'action': it['action']}
            before_f.write_text(json.dumps(before, indent=1, ensure_ascii=False), encoding='utf-8')
            try:
                if it['id'] in refused:
                    raise RuntimeError(refused[it['id']])
                results = sent.get(it['id'])
                if results is None:
                    results = [_write_call(s, tool, args) for tool, args in it['calls']]
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
                if it['action']['type'] == 'insert_text':
                    it['inserted'] = [[args.get('post_id'), r.get('element_id')] for (tool, args), r in
                                      zip(it['calls'], results) if tool == 'elementor-insert-element' and r.get('element_id')]
                if it['action']['type'] == 'redirect':
                    # "created" is a list of rules ({"id": ...}); meta-mcp 1.7 also returns "ids". Either way undo
                    # needs the ids to delete what this run created (Redirection or Rank Math, the same tool).
                    it['created_ids'] = _created_ids(results)
                    it['redirect_provider'] = next((r.get('provider') for r in results if r.get('provider')), '')
                if it.get('post_id'):
                    post_ids.add(it['post_id'])
                post_ids.update(it.get('post_ids') or [])
                changes.append({'id': it['id'], 'finding': it['finding'], 'page': it.get('page'),
                                'field': it.get('field'), 'old': it.get('current'), 'new': it.get('new'),
                                'at': time.strftime('%Y-%m-%d %H:%M:%S'), 'created_post_id': it.get('created_post_id'),
                                'created_ids': it.get('created_ids'),
                                **({'inserted': it['inserted']} if it.get('inserted') else {}),
                                **({'redirect_provider': it['redirect_provider']} if it.get('redirect_provider') else {})})
                changes_f.write_text(json.dumps(changes, indent=1, ensure_ascii=False), encoding='utf-8')
                pl.setdefault('done', []).append(it['id'])
                done.append(it['id'])
            except Exception as e:  # noqa: BLE001 - stop the batch at the first error
                if batch == 'alt-text':
                    # one image the site can't find doesn't hold up the other 700: logged, and listed for the agency
                    media_failed.append({'id': it['id'], 'finding': it['finding'], 'image': it.get('page'),
                                         'error': str(e)[:300]})
                    before.pop(it['id'], None)
                    before_f.write_text(json.dumps(before, indent=1, ensure_ascii=False), encoding='utf-8')
                    continue
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
    known = {f['id'] for f in pl.get('failed', [])}
    pl.setdefault('failed', []).extend(dict(m, batch=batch) for m in media_failed if m['id'] not in known)
    pf.write_text(json.dumps(pl, indent=1, ensure_ascii=False), encoding='utf-8')
    return {'batch': batch, 'done': len(done), 'of': len(items), 'failed': failed, 'cache_purged': purge,
            **({'images_refused': len(media_failed), 'images_refused_examples': media_failed[:10],
                'note': 'The site could not find these images in the Media Library or in editable text (a slider, '
                        'the theme or another site): they are on the Agency Fix List with their alt text.'}
               if media_failed else {}),
            'recheck': rechecked, 'changes_file': str(changes_f), 'before_file': str(before_f),
            'undo': f'undo_execute("{plan_file}")'}


MEDIA_CHUNK = 50


def _redirects_writable(s):
    """Whether redirects-create can store a rule here: the Redirection plugin, or Rank Math's Redirections module
    (Meta MCP 1.7+ reports it as site_tools.rank_math_redirections). Unknown (an older status format): assume yes."""
    st = (s.integrations or {}).get('site_tools') if isinstance(s.integrations, dict) else None
    if not isinstance(st, dict) or 'redirection' not in st:
        return True
    if (st.get('redirection') or {}).get('active'):
        return True
    return bool((st.get('rank_math_redirections') or {}).get('active'))


def _created_ids(results):
    """The ids of the redirect rules a redirects-create call made."""
    ids = []
    for r in results:
        for x in (r.get('ids') or []) + [c.get('id') for c in r.get('created') or [] if isinstance(c, dict)]:
            if isinstance(x, int) and x not in ids:
                ids.append(x)
    return ids


def _write_call(s, tool, args):
    """One write. replace-text: report per-post failures as an error, and call again while it says more posts remain
    (changed posts no longer match, so the same call picks up the rest)."""
    res = s.write(tool, args)
    if tool == 'update-media' and res.get('failed'):
        bad = [r for r in res.get('results') or [] if isinstance(r, dict) and r.get('success') is False]
        raise RuntimeError('update-media: ' + '; '.join(str(r.get('error')) for r in bad[:3]) if bad else
                           f"update-media: {res.get('failed')} image(s) refused")
    if tool != 'replace-text':
        return res
    for _ in range(20):
        if res.get('failed'):
            raise RuntimeError('replace-text: ' + json.dumps(res['failed'], ensure_ascii=False)[:300])
        if not res.get('more'):
            return res
        res = s.write(tool, args)
    return res


def _send_media_chunks(s, items):
    """Alt text for many images: one update-media call per 50 images instead of one per image. update-media answers
    per image (results[] in the order sent; an image it can't find is "success": false there while the call succeeds).
    Returns {item id: [result]} for the images written and {item id: error} for those refused; a chunk whose call
    fails outright is left out, so its items run one by one."""
    single = [it for it in items if len(it.get('calls') or []) == 1 and it['calls'][0][0] == 'update-media'
              and len(it['calls'][0][1].get('items') or []) == 1]
    out, errors = {}, {}
    for i in range(0, len(single), MEDIA_CHUNK):
        chunk = single[i:i + MEDIA_CHUNK]
        try:
            res = s.write('update-media', {'items': [it['calls'][0][1]['items'][0] for it in chunk]})
        except Exception:  # noqa: BLE001 - fall back to one call per image
            continue
        if res.get('success') is False:
            continue
        results = res.get('results')
        if not isinstance(results, list) or len(results) != len(chunk):
            if not res.get('failed'):
                out.update({it['id']: [res] for it in chunk})
            continue
        for it, r in zip(chunk, results):
            if isinstance(r, dict) and r.get('success') is False:
                errors[it['id']] = f"update-media: {r.get('error') or 'refused'}"
            else:
                out[it['id']] = [r]
    return out, errors


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
    # only a text value is moved to the key the widget renders; "header_size": "h2" and other options never are
    if k in have or not isinstance(v, str) or (k not in TEXT_KEYS and k not in WIDGET_TEXT_KEY.values()):
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
                    _write_call(s, tool, args)
            elif u == 'delete-created' and ch.get('created_ids'):
                s.write('redirects-delete', {'ids': ch['created_ids'], 'confirm': True,
                                             **({'provider': ch['redirect_provider']} if ch.get('redirect_provider') else {})})
            elif u == 'delete-inserted' and ch.get('inserted'):
                for pid, el_id in ch['inserted']:
                    s.write('elementor-update-element', {'post_id': pid, 'element_id': el_id, 'operation': 'delete'})
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
              'additional_categories': 'extra categories', 'attributes': 'amenities (attributes)',
              'review_replies': 'review replies (review sheet)'}
GBP_LOCKED = {'title', 'name', 'business_name', 'address', 'primary_category'}
GBP_UTM = 'utm_source=google&utm_medium=organic&utm_campaign=gbp'      # the team's link (SKILL.md, Business Profile)
# Nov 2026 run: Google refuses a "from the business" description on hotel (lodging) profiles; it writes its own.
GBP_NO_DESCRIPTION = ("Google doesn't allow a business description on hotel profiles (it writes its own): not "
                      'changed, and not agency work')
# fields the API may refuse for hotels that the dashboard still allows: on refusal they become Claude in Chrome steps
GBP_CHROME_FALLBACK = {'attributes': 'Edit profile → Amenities', 'additional_categories': 'Edit profile → Business '
                       'category → Add another category'}


def _gbp_chrome_steps(key, val):
    if key == 'attributes':
        what = [f'{k}: {v}' for k, v in (val or {}).items()] if isinstance(val, dict) else [str(val)]
    else:
        what = [str(x) for x in (val if isinstance(val, list) else [val])]
    return ['business.google.com (or Google Search → the hotel → Edit profile), signed in as a Manager of the profile',
            GBP_CHROME_FALLBACK[key] + ':'] + [f'set {w}' for w in what] + ['Save. Google may review it before it shows.']


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
    if field == 'description':
        raise ValueError(GBP_NO_DESCRIPTION)
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


def _gbp_plan(group_dir, slug, hdir, acts, n, replies=None):
    """The business-profile batch: (items, skipped, note, n). One proposal (change id) per field, plus one for the
    review replies marked "Send? = Yes" in the hotel's latest review sheet (gbp_reviews.read_sheet)."""
    from . import gbp
    replies = replies if replies and (replies.get('replies') or replies.get('problems')) else None
    if replies:
        acts = acts + [{'finding': 'gbp-review-replies', 'title': 'Google review replies (review sheet)',
                        'category': 'Local', 'action': {'type': 'gbp', 'field': 'review_replies',
                                                        'value': replies.get('replies'), 'sheet': replies['xlsx']},
                        'sheet_problems': replies.get('problems') or []}]
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
        if x.get('sheet_problems'):
            skipped.append({'finding': x['finding'], 'action': 'gbp', 'act': {'type': 'gbp', 'field': 'review_replies'},
                            'reason': 'the review sheet has problems (nothing from it is posted): '
                                      + '; '.join(x['sheet_problems'])[:400]})
            continue
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
              'checks': [], **({'hotel_confirmed': x['hotel_confirmed']} if x.get('hotel_confirmed') else {}),
              **({'review_sheet': x['action']['sheet']} if x['action'].get('sheet') else {})}
        try:
            items.append(_gbp_propose(it, out_dir))
        except Exception as e:  # noqa: BLE001 - Google's validation or sign-in: skip this field, say why
            if key in GBP_CHROME_FALLBACK:
                # the API refuses it for this profile, the dashboard doesn't: a Chrome step (MetaHotels, not agency)
                items.append(dict(it, batch='chrome', via='chrome', page='Google Business Profile (dashboard)',
                                  field=f'Business Profile: {GBP_FIELDS[key]} (Chrome)', current=None,
                                  new=_gbp_chrome_steps(key, val), undo='manual: reverse the steps by hand',
                                  action={'type': 'chrome', 'where': 'Google Business Profile',
                                          'steps': _gbp_chrome_steps(key, val), 'gbp_field': key},
                                  note=f'the Business Profile API refused it ({str(e)[:160]}): do it in the dashboard'))
                continue
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
        if it.get('review_sheet'):
            from . import gbp_reviews
            try:
                gbp_reviews.mark_sheet(it['review_sheet'], [r['review_id'] for r in it.get('gbp_value') or []],
                                       f"Posted {time.strftime('%Y-%m-%d')}, change {it['change_id']}")
            except Exception:  # noqa: BLE001 - the replies are posted; the sheet note is a convenience
                pass
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
