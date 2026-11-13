"""The two documents after an execute run (PDF + Word through render_report):

  Execute Report    every change execute made: page, what changed, before -> after, the live re-check result;
                    what is still waiting for the hotel; the undo command.
  Agency Fix List   every SEO finding of the audit that execute did not finish, written for the SEO agency to do by
                    hand: why it matters, every page, step-by-step where to click, the exact text to paste, and how it
                    will be checked. Web Team (developer) items stay in the Web Team List; items waiting for the hotel
                    are listed at the end so nobody changes them yet.

Both are built from execute-<date>/plan.json (+ changes.json) and the audit run it came from (audit-report.json,
build-plan.json, hotel-questions.json).
"""
import json
import re
from datetime import date
from pathlib import Path

from . import group as grp, paths
from .checks import describe

NO_ACTION = re.compile(r'^\*\*Fix:\*\*\s*No (change|copy|action)', re.I)
SEV = {'Critical': 0, 'High': 1, 'Medium': 2, 'Low': 3, 'Info': 4}
HOTEL_REASONS = ('waiting for the hotel', 'the hotel said no', 'the hotel answered', 'on hold', 'price or discount',
                 'no question number')
# skipped for a reason execute itself resolves on a later run (not agency work): listed under "Still to run"
EXECUTE_LATER = ('group-wide', 'runs only in the group batch')


def _short(v, n=300):
    if v is None:
        return '–'
    s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
    return s if len(s) <= n else s[:n] + ' …'


def _latest_plan(hdir):
    plans = sorted(hdir.glob('execute-*/plan.json'))
    if not plans:
        raise FileNotFoundError(f'no execute-<date>/plan.json in {hdir}: run execute first')
    return plans[-1]


def steps_for(a):
    """Where to click and what to paste, for one action the agency does by hand."""
    t = a.get('type')
    if t == 'seo_fields':
        f = a.get('fields') or {}
        out = [f"WordPress → Pages / Posts → open `{a.get('url')}` → Rank Math (Edit Snippet / Advanced):"]
        names = {'title': 'SEO title', 'description': 'Meta description', 'focus_keyword': 'Focus keyword',
                 'canonical': 'Canonical URL (Advanced)', 'robots': 'Robots meta (Advanced)'}
        out += [f"{names.get(k, k)}: `{v if not isinstance(v, (list, dict)) else json.dumps(v)}`" for k, v in f.items()]
        return out
    if t == 'redirect':
        return [f"Rank Math → Redirections (or Tools → Redirection) → Add new: source `{a.get('source')}` → target "
                f"`{a.get('target')}`, type {a.get('code', 301)}" + (' (regex)' if a.get('regex') else '') + '.']
    if t == 'alt_text':
        return [f"Media → Library → open the image `{a.get('image')}` → Alternative Text: `{a.get('alt')}` → Update."]
    if t == 'elementor_text':
        return [f"Open `{a.get('url')}` → Edit with Elementor → the element containing “{a.get('find')}” → set:"] + \
            [f"{k}: `{v}`" for k, v in (a.get('settings') or {}).items()] + ['Update (publish).']
    if t == 'post_content':
        return [f"Open `{a.get('url')}` in the editor and replace the content with the text below, then Update.",
                f"`{a.get('content')}`"]
    if t == 'text_replace':
        return [f"Open `{a.get('url')}` (Elementor or the page editor), find “{a.get('find')}” and change it to "
                f"`{a.get('replace')}`. Update, then purge the page cache."]
    if t == 'schema_snippet':
        from .execute import schema_code
        try:
            code = schema_code(a.get('code'))
        except ValueError as e:
            return [f'The schema block in the audit is not valid ({e}): do not paste it; it is fixed in the next run.']
        return ["Elementor → Custom Code → Add New, location **<head>**, paste the code below exactly as it is "
                "(including the <script> lines; without them the JSON shows on the page), display conditions: "
                + ', '.join(a.get('conditions') or []) + ' → Publish.', f"`{_short(code, 4000)}`"]
    if t == 'rankmath_setting':
        return [f"Rank Math → {a.get('group', 'settings')} → set:"] + \
            [f"{k}: `{v}`" for k, v in (a.get('settings') or {}).items()] + ['Save changes.']
    if t == 'post_status':
        return [f"Pages / Posts → `{a.get('url')}` → set status to **{a.get('status')}**."]
    if t == 'menu':
        return [f"Appearance → Menus → {a.get('menu')} → the item linking to `{a.get('find_url')}` → "
                + ', '.join(f"{k.replace('new_', '')}: `{v}`" for k, v in a.items() if k in ('new_url', 'new_title'))
                + ' → Save menu.']
    if t == 'page_create':
        return [f"Create the new page {a.get('page_id')} exactly as specified in the Build Plan (page specs), publish "
                'it, then add it to the menu and the sitemap.']
    if t == 'chrome':
        return [str(x) for x in (a.get('steps') or [])] or [f"In {a.get('where')}: see the fix above."]
    return [f'{t}: see the fix above.']


GBP_BATCH = 'business-profile'          # execute.GBP_BATCH


def _gbp_section(pl, changes, recheck, done):
    """The Execute Report's Business Profile section: what was sent to the Google profile (before -> after, change
    id, Google's read-back), what is planned but not sent, or why the batch was skipped."""
    sent = [c for c in changes if c.get('via') == 'business_profile']
    planned = [i for i in pl.get('batches', {}).get(GBP_BATCH, []) if i['id'] not in done]
    note = pl.get('business_profile') or {}
    blocks = []
    if sent:
        blocks.append({'table': {'columns': ['What changed', 'Before', 'After', 'Change id', 'On the profile'], 'rows': [
            [c.get('field') or '–', _short(c.get('old')), _short(c.get('new')), c.get('change_id') or '–',
             (recheck.get(c.get('finding')) or {}).get('status') or c.get('read_back') or 'sent'] for c in sent]}})
        blocks.append({'note': '"Pending Google review" is normal: Google checks most profile edits before they show. '
                               'Undo proposes the before values again, for approval like any profile change.'})
    if planned:
        blocks.append({'p': f'**Not sent ({len(planned)}):** the batch was not approved or stopped; '
                            'propose again with execute_gbp_refresh before running it.'})
        blocks.append({'table': {'columns': ['What would change', 'Now', 'After'], 'rows': [
            [i.get('field') or '–', _short(i.get('current')), _short(i.get('new'))] for i in planned]}})
    if note.get('status') == 'skipped':
        blocks.append({'warning': note.get('reason', 'Business Profile batch skipped')})
    if not blocks:
        return None
    return {'title': f'Google Business Profile: {len(sent)} change(s) sent', 'blocks': blocks}


def build(group_dir, slug, plan_file=''):
    reg = grp.load(group_dir)
    hotel = next((h for h in reg['hotels'] if h['slug'] == slug), None) if slug != 'group' else None
    hdir = grp.site_dir(group_dir, reg) if slug == 'group' else grp.hotel_dir(group_dir, slug, reg)
    pf = paths.resolve(plan_file) if plan_file else _latest_plan(hdir)
    pl = json.loads(pf.read_text(encoding='utf-8'))
    run = Path(pl['source_run'])
    report = json.loads((run / ('group-summary.json' if slug == 'group' else 'audit-report.json')).read_text(
        encoding='utf-8'))
    bp = json.loads((run / 'build-plan.json').read_text(encoding='utf-8')) if (run / 'build-plan.json').exists() else {}
    changes = json.loads((pf.parent / 'changes.json').read_text(encoding='utf-8')) \
        if (pf.parent / 'changes.json').exists() else []
    name = hotel['name'] if hotel else (reg['group'].get('name') or reg['group']['site'])
    site = reg['group']['site']
    items = {it['id']: dict(it, batch=b) for b, its in pl.get('batches', {}).items() for it in its}
    done = set(pl.get('done', []))
    recheck = pl.get('recheck', {})
    approved = {a['batch'] for a in pl.get('approved', [])}
    by_finding = {}
    for it in items.values():
        by_finding.setdefault(it['finding'], []).append(it)
    today = date.today()
    dlabel = f'{today.day} {today.strftime("%b")}'

    # ---- 1. Execute Report: what was changed
    secs, n = [], 0
    for b in [b for b in pl.get('batches', {}) if b != GBP_BATCH]:
        rows =[[c.get('page') or '–', c.get('field') or '–', _short(c.get('old')), _short(c.get('new')),
                 (recheck.get(c.get('finding')) or {}).get('status', 'not re-checked')]
                for c in changes if items.get(c['id'], {}).get('batch') == b]
        if not rows:
            continue
        n += 1
        secs.append({'number': n, 'title': f"{b.replace('-', ' ').capitalize()}: {len(rows)} change(s)",
                     'blocks': [{'table': {'columns': ['Page', 'What changed', 'Before', 'After', 'Live re-check'],
                                           'rows': rows}}]})
    gbp_sec = _gbp_section(pl, changes, recheck, done)
    if gbp_sec:
        n += 1
        secs.append(dict(gbp_sec, number=n))
    waiting =[s for s in pl.get('skipped', []) if any(k in s.get('reason', '') for k in HOTEL_REASONS)]
    if waiting:
        n += 1
        secs.append({'number': n, 'title': f'Waiting for the hotel: {len(waiting)} item(s) not changed',
                     'blocks': [{'table': {'columns': ['Finding', 'Why it was not changed'],
                                           'rows': [[w.get('finding'), w.get('reason')] for w in waiting]}}]})
    if pl.get('rewording'):
        n += 1
        secs.append({'number': n, 'title': 'Hotel answers that need new wording before they can be applied',
                     'blocks': [{'table': {'columns': ['Finding', 'Hotel answer'],
                                           'rows': [[r['title'], json.dumps(r['answers'], ensure_ascii=False)]
                                                    for r in pl['rewording']]}}]})
    statuses = [r.get('status') for r in recheck.values() if r.get('via') != 'business_profile']
    n_gbp = sum(c.get('via') == 'business_profile' for c in changes)
    lead = (f"**{len(changes) - n_gbp} change(s)** made on {site} through the site's content tools"
            + (f" and **{n_gbp}** on the Google Business Profile" if n_gbp else '')
            + f" ({len(approved)} approved batch(es)). Live re-check: {statuses.count('Done')} done, "
            f"{statuses.count('Partly')} partly, {statuses.count('Open')} still open. Everything execute could not do "
            'is in the Agency Fix List.')
    exec_doc = {'title': 'Execute Report', 'hotel': name, 'short_name': name, 'site': site, 'date': dlabel,
                'file_number': 'auto', 'lead': lead, 'sections': secs or [{'title': 'No changes made yet',
                                                                            'blocks': [{'p': 'No batch has been run.'}]}],
                'footer': f'Undo every change of this run: `undo_execute("{pf}")`.',
                'subtitle': f'What was changed on {site}, {dlabel}'}

    # ---- 2. Agency Fix List: every SEO finding not finished by execute
    from . import execute as ex, questions as qm
    qdata = qm.load(group_dir, slug) if slug != 'group' else None
    answers = {i['id']: i for i in (qdata or {}).get('items', [])}
    skipped = {}
    for s_ in pl.get('skipped', []):
        skipped.setdefault(s_.get('finding'), []).append(s_)
    agency, hotel_wait, no_action, still_to_run = [], [], [], []
    for sec in report.get('sections', []):
        if not sec.get('severity') or sec.get('owner') == 'web':
            continue
        fid = sec.get('finding_id')
        if sec.get('actions') and all(a.get('type') == 'gbp' for a in sec['actions']):
            continue        # Business Profile fixes: MetaHotels makes them (Execute Report), never the agency
        its = [i for i in by_finding.get(fid, []) if i.get('batch') != GBP_BATCH]
        sk_all = [x for x in skipped.get(fid, []) if x.get('action') != 'gbp']
        later = [x for x in sk_all if any(k in x.get('reason', '') for k in EXECUTE_LATER)]
        sk = [x for x in sk_all if x not in later]
        # planned but not run yet (batch not approved, Chrome step not done) or group-wide: execute does it on its
        # next run, so it is not handed to the agency (Nov 2026: alt text and group items landed on the agency list)
        pending = [i for i in its if i['id'] not in done]
        if pending or later:
            still_to_run.append([sec.get('title'), ', '.join(sorted({i['batch'] for i in pending}))
                                 + ('; ' if pending and later else '') + ('group run: execute without --hotel'
                                                                          if later else ''),
                                 str(len(pending) + len(later))])
            its = [i for i in its if i['id'] in done]
            if not sk:
                continue
        all_done = its and all(i['id'] in done for i in its) and not sk
        if all_done and (recheck.get(fid) or {}).get('status') in ('Done', 'Manual', None):
            continue
        if all_done:
            # written but the live page doesn't show it: execute's own problem to look into, not the agency's
            still_to_run.append([sec.get('title'), 'written, but the live re-check says '
                                 + str((recheck.get(fid) or {}).get('status')) + ': check the element / template',
                                 str(len(its))])
            continue
        if sk and all(any(k in x.get('reason', '') for k in HOTEL_REASONS) for x in sk) and not its:
            hotel_wait.append([sec.get('title'), '; '.join(x['reason'] for x in sk)])
            continue
        # the finding's own text may still depend on the hotel ([CONFIRM Q14] in the fix / paste boxes)
        sec_text = json.dumps(sec.get('blocks', []), ensure_ascii=False)
        refs = list(dict.fromkeys(ex.QREF.findall(sec_text)))
        states = {q: ex._answer_state(q, answers.get(q), sec_text) for q in refs}
        if any(st in ('waiting', 'no') for st in states.values()):
            hotel_wait.append([sec.get('title'), ', '.join(f'{q} ({st})' for q, st in states.items()
                                                            if st in ('waiting', 'no'))])
            continue
        sec = dict(sec, blocks=ex._strip_confirmed(sec.get('blocks', []), [q for q, st in states.items() if st == 'yes']))
        use = [q for q, st in states.items() if st == 'value']
        fix_text = ' '.join(str(b.get('p') or b.get('paste') or '') for b in sec.get('blocks', [])
                            if str(b.get('p') or b.get('paste') or '').startswith('**Fix:**'))
        where_text = ' '.join(str(b.get('note', '')) for b in sec.get('blocks', []))
        if NO_ACTION.search(fix_text) or 'Where:** Info only' in where_text:
            no_action.append([sec.get('title'), re.sub(r'^\*\*Fix:\*\*\s*', '', fix_text)[:160]])
            continue
        todo = [i for i in its if i['id'] not in done]
        status = ('partly done by execute' if any(i['id'] in done for i in its) else
                  'not done: the batch was not approved' if todo and not any(i['batch'] in approved for i in todo) else
                  'execute could not do it' if sk or todo else 'no automatic fix: do it by hand')
        blocks = []
        pages = sec.get('pages_all') or []
        if pages:
            blocks.append({'p': f"**Pages ({len(pages)}):**"})
            blocks.append({'ul': [f'`{p}`' for p in pages]})
        steps = []
        for i in todo:
            steps += steps_for(i['action'])
        for x in sk:
            if any(k in x.get('reason', '') for k in HOTEL_REASONS):
                continue
            if x.get('act'):
                steps += steps_for(x['act'])
            elif x.get('find'):
                steps += steps_for({'type': 'text_replace', 'url': x.get('page'), 'find': x['find'],
                                    'replace': x.get('replace')})
        for b in sec.get('blocks', []):
            if any(k in b for k in ('paste', 'code', 'table')) or ('p' in b and str(b['p']).startswith('**Fix:**')):
                blocks.append(b)
            elif 'note' in b and str(b['note']).startswith('**Where:**'):
                blocks.append(b)
        if use:
            blocks.append({'warning': "**Use the hotel's answers** (they replace the marked details above): " + '; '.join(
                f"{q}: " + ', '.join(f'{k.replace("_", " ")} {v}' for k, v in (answers[q].get('answer') or {}).items()
                                     if k != 'answered_by') for q in use)})
        steps = list(dict.fromkeys(steps))
        if steps:
            blocks.append({'h3': 'Steps'})
            blocks.append({'ol': steps})
        if sec.get('checks'):
            blocks.append({'note': '**How it will be checked:** ' + '; '.join(describe(c) for c in sec['checks'][:8]) +
                                   (f" (+{len(sec['checks']) - 8} more)" if len(sec['checks']) > 8 else '')})
        reasons = sorted({x.get('reason', '') for x in sk if not any(k in x.get('reason', '') for k in HOTEL_REASONS)})
        why = sec.get('why', '') + (f" Execute: {status}" + (f" ({'; '.join(reasons)})" if reasons else '') + '.')
        agency.append({'title': sec.get('title'), 'severity': sec.get('severity'), 'category': sec.get('category'),
                       'why': why.strip(), 'blocks': blocks, 'checks': sec.get('checks', []),
                       'finding_id': fid, 'pages_all': pages})
    if still_to_run:
        if exec_doc['sections'] and exec_doc['sections'][0].get('title') == 'No changes made yet':
            exec_doc['sections'] = []
        exec_doc['sections'].append({
            'number': len(exec_doc['sections']) + 1,
            'title': f'Still to run with execute: {len(still_to_run)} finding(s)',
            'blocks': [{'p': 'Execute can make these changes itself: they are not on the Agency Fix List. Approve the '
                             'batch (or run the group batch) to finish them.'},
                       {'table': {'columns': ['Finding', 'What is left', 'Items'], 'rows': still_to_run}}]})
    agency.sort(key=lambda x: (x.get('category') or '', SEV.get(x.get('severity'), 9)))
    secs, n, current = [], 0, None
    for a in agency:
        if a['category'] != current:
            current = a['category']
            secs.append({'chapter': current, 'chapter_label': current, 'title': current, 'blocks': []})
        n += 1
        secs.append(dict(a, number=n))
    created = {i['action'].get('page_id') for i in items.values() if i['action'].get('type') == 'page_create'
               and i['id'] in done}
    new_pages = [p for p in bp.get('pages', []) if p.get('status') == 'missing' and p.get('id') not in created]
    if new_pages:
        secs.append({'chapter': 'New pages', 'chapter_label': 'New pages', 'title': 'New pages', 'blocks': []})
        for p in new_pages:
            n += 1
            secs.append({'number': n, 'title': f"Create: {p.get('h1') or p.get('title') or p.get('url')}",
                         'blocks': [{'table': {'columns': ['Field', 'Value'], 'rows': [
                             ['URL', f"`{p.get('url', '')}`"], ['SEO title', f"`{p.get('seo_title', '')}`"],
                             ['Meta description', f"`{p.get('meta_description', '')}`"],
                             ['H1', f"`{p.get('h1') or p.get('title', '')}`"]]}},
                             {'p': f"The full page copy, schema and links are in the Build Plan (page {p.get('id')})."
                                   + (f" **On hold:** {p['hold']}" if p.get('hold') else '')}]})
    if no_action:
        secs.append({'title': 'Checked: no action needed',
                     'blocks': [{'p': 'The audit looked at these and found nothing to change; listed so they are not '
                                      'done twice.'},
                                {'table': {'columns': ['Finding', 'Note'], 'rows': no_action}}]})
    if hotel_wait:
        secs.append({'title': 'Do not change yet: waiting for the hotel',
                     'blocks': [{'p': 'These depend on the hotel\'s answers (Questions for the Hotel). They will be '
                                      'applied once the hotel replies.'},
                                {'table': {'columns': ['Finding', 'Waiting for'], 'rows': hotel_wait}}]})
    agency_doc = {'title': 'Agency Fix List', 'hotel': name, 'short_name': name, 'site': site, 'date': dlabel,
                  'file_number': 'auto', 'sections': secs or [{'title': 'Nothing left',
                                                              'blocks': [{'p': 'Execute finished every SEO fix.'}]}],
                  'lead': f"**{n} item(s)** for the SEO agency to fix by hand on {site}, most important first within "
                          'each chapter. Paste the text exactly as shown; purge the page cache after each change. '
                          'Developer items are in the separate Web Team List.',
                  'subtitle': f'SEO fixes to do by hand on {site}, after the automatic run of {dlabel}',
                  'footer': '**When done:** reply with the list numbers you finished; every item is re-checked on the '
                            'live site (/hotel-seo recheck).'}
    out = pf.parent
    (out / 'execute-report.json').write_text(json.dumps(exec_doc, indent=1, ensure_ascii=False), encoding='utf-8')
    (out / 'agency-fix-list.json').write_text(json.dumps(agency_doc, indent=1, ensure_ascii=False), encoding='utf-8')
    return {'execute_report': str(out / 'execute-report.json'), 'agency_fix_list': str(out / 'agency-fix-list.json'),
            'changes': len(changes), 'agency_items': n, 'waiting_for_hotel': len(hotel_wait),
            'still_to_run': len(still_to_run),
            'out_dir': str(paths.reports_dir(hdir)),
            'next': 'render_report each file to out_dir (PDF).'}
