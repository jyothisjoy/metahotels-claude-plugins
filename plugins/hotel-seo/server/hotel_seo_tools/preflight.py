"""Agent checks: before every run (agent_preflight) and after each agent (validate_agent_output).

Status per agent and scope:
  OK        everything it needs answered
  degraded  it runs with a named gap (printed in its report chapter)
  blocked   it cannot run: its categories show "not assessed: <reason>" and the Health Score is rescaled without them
After a run: complete / partial (turn budget hit, partial file validates) / not assessed (failed twice).
Everything is written to <run>/agent-status.json, which the report cover and the run notes show.
"""
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

from . import apikeys, geo, group as grp, keywords, paths, seo_check

AGENTS = {
    'seo-technical': {'scope': 'site', 'model': 'sonnet', 'categories': ['Technical']},
    'seo-sitemap': {'scope': 'site', 'model': 'sonnet', 'categories': ['Technical']},
    'seo-performance': {'scope': 'site', 'model': 'sonnet', 'categories': ['Performance']},
    'seo-agentic': {'scope': 'site', 'model': 'sonnet', 'categories': ['AI Search']},
    'seo-backlinks': {'scope': 'site', 'model': 'sonnet', 'categories': ['Backlinks']},
    'seo-content': {'scope': 'hotel', 'model': 'opus', 'categories': ['Content', 'On-Page', 'Images']},
    'seo-schema': {'scope': 'hotel', 'model': 'sonnet', 'categories': ['Schema']},
    'seo-local': {'scope': 'hotel', 'model': 'sonnet', 'categories': ['Local', 'Booking path & facts']},
    'seo-maps': {'scope': 'hotel', 'model': 'sonnet', 'categories': ['Maps']},
    'seo-geo': {'scope': 'hotel', 'model': 'opus', 'categories': ['AI Search']},
    'seo-flow': {'scope': 'hotel', 'model': 'sonnet', 'categories': [], 'stages': ['find', 'local', 'optimize', 'win']},
}
SCHEMA_FILE = paths.PLUGIN_DIR / 'skills' / 'hotel-seo' / 'templates' / 'report.schema.json'
FLOW_PROMPTS = paths.PLUGIN_DIR / 'skills' / 'hotel-seo' / 'references' / 'claude-seo' / 'flow' / 'prompts'
FLOW_CREDIT = 'Framework and prompts © Daniel Agrici, CC BY 4.0'


def _run(script, args, timeout=180):
    r = seo_check.run(script, args, timeout_s=timeout)
    data = r.get('json')
    if data is None and r.get('saved_to'):
        try:
            data = json.loads(Path(r['saved_to']).read_text(encoding='utf-8'))
        except (OSError, ValueError):
            data = None
    return r, data


def _status(ok, degraded=None, note=''):
    return {'status': 'OK' if ok and not degraded else ('degraded' if ok else 'blocked'),
            'note': degraded or note}


def preflight(group_dir, crawl_dir, slugs=None, progress=None):
    """Probe every agent's inputs for the site and each hotel. Writes <group>/agent-preflight-<date>.json."""
    reg = grp.load(group_dir)
    if not reg:
        raise FileNotFoundError('no site.json: run detect_hotels + save_group first')
    site = reg['group']['site'].rstrip('/') + '/'
    cd = paths.resolve(crawl_dir)
    findings_ok = (cd / 'findings.json').exists()
    site_text_ok = (cd / 'site_text.json').exists()
    out = {'site': site, 'checked': time.strftime('%Y-%m-%d %H:%M'), 'site_agents': {}, 'hotels': {}, 'common': {}}

    def common():
        r, d = _run('render_page.py', [site, '--mode', 'auto', '--json'], 120)
        ok = r.get('ok') and isinstance(d, dict) and not d.get('error') and (d.get('status_code') or 0) < 400
        return _status(ok, note='' if ok else f"homepage did not render: {(d or {}).get('error') or r.get('error') or r.get('stderr', '')[:200]}")

    def technical():
        r, d = _run('sitemap_discovery.py', [site, '--json'], 120)
        if not findings_ok:
            return _status(False, note='audit_site has not run on this crawl (no findings.json)')
        gap = '' if (d or {}).get('found') else 'no valid sitemap found (reported as a finding, not a gap)'
        return _status(True, None, gap)

    def sitemap():
        r, d = _run('sitemap_discovery.py', [site, '--json'], 120)
        if not r.get('ok') and not d:
            return _status(False, note='robots.txt and every sitemap path unreachable')
        return _status(True, None if (d or {}).get('found') else None,
                       'sitemaps found: ' + str(len((d or {}).get('found') or [])))

    def performance():
        key = apikeys.get('google')
        r, d = _run('pagespeed_check.py', [site, '--strategy', 'mobile', '--json'], 240)
        if not r.get('ok') or not d or (isinstance(d, dict) and d.get('error') and not d.get('lab_data')):
            return _status(False, note='PageSpeed Insights unreachable: ' + str((d or {}).get('error') or
                                                                                r.get('stderr', ''))[:200])
        gap = None
        if not key:
            gap = ('no Google API key: lab data from keyless PSI only (add PAGESPEED_API_KEY or GOOGLE_API_KEY to '
                   'the work folder .env)')
        elif not apikeys.google_apis(key)['crux'][0]:
            gap = ('Chrome UX Report API is not enabled for the Google key: lab data only, no real-user Core Web '
                   'Vitals (enable "Chrome UX Report API" in the key\'s Cloud project)')
        else:
            r2, d2 = _run('crux_history.py', [site, '--form-factor', 'PHONE', '--json'], 120)
            if not d2 or (isinstance(d2, dict) and d2.get('error')):
                gap = 'CrUX has no field data for this site (low traffic): lab data only'
        return _status(True, gap)

    def geo_agent():
        import requests
        try:
            rr = requests.get(site + 'robots.txt', timeout=30, headers={'User-Agent': 'Mozilla/5.0'})
            ok = rr.status_code < 500
        except requests.RequestException:
            ok = False
        return _status(ok, None, '' if ok else 'robots.txt unreachable')

    def agentic():
        gaps = []
        r, d = _run('agentic_check.py', [site, '--json'], 180)
        if not r.get('ok') and not d:
            return _status(False, note='agentic_check failed: ' + r.get('stderr', '')[:200])
        r2, d2 = _run('agent_ux_check.py', [site, '--json'], 180)
        if not d2 or (isinstance(d2, dict) and d2.get('error')):
            gaps.append('Agent-UX heuristic unavailable (Chromium render failed)')
        r3, d3 = _run('lighthouse_agentic.py', [site, '--strategy', 'mobile', '--json'], 240)
        if not d3 or (isinstance(d3, dict) and d3.get('error')):
            gaps.append('Lighthouse Agentic Browsing X/N unavailable (PSI quota or no key)')
        return _status(True, '; '.join(gaps) or None)

    def backlinks():
        gaps = []
        mz, why = apikeys.test('moz') if apikeys.get('moz') else (False, 'no Moz key')
        from . import bing
        bok = bing.configured()[0]
        if not mz:
            gaps.append(f'Moz unavailable ({why}): backlink score will be "insufficient data"')
        if not bok:
            gaps.append('no Bing Webmaster key')
        if not mz and not bok:
            gaps.append('Common Crawl only (domain-level, confidence 0.50)')
        return _status(True, '; '.join(gaps) or None)

    site_probes = {'common': common, 'seo-technical': technical, 'seo-sitemap': sitemap,
                   'seo-performance': performance, 'seo-agentic': agentic, 'seo-backlinks': backlinks}
    with ThreadPoolExecutor(6) as ex:
        futs = {k: ex.submit(fn) for k, fn in site_probes.items()}
        res = {k: _safe(f) for k, f in futs.items()}
    out['common'] = res.pop('common')
    out['site_agents'] = res
    if out['common']['status'] == 'blocked':
        for k in out['site_agents']:
            out['site_agents'][k] = {'status': 'blocked', 'note': out['common']['note']}
    kw_ok, kw_why = keywords.configured()
    out['keyword_layer'] = _status(True, None if kw_ok else f'Keyword Planner not set up ({kw_why}): CSV fallback / '
                                                          'Search Console only')
    for h in reg['hotels']:
        if slugs and h['slug'] not in slugs:
            continue
        hd = grp.hotel_dir(group_dir, h['slug'], reg)
        facts_f = hd / 'hotel-facts.json'
        facts = json.loads(facts_f.read_text(encoding='utf-8')).get('facts', []) if facts_f.exists() else []
        has_bc = any(str(x.get('source', '')).startswith('Booking.com') for x in facts)
        has_engine = bool(list(hd.rglob('booking_engine.json')))
        hr = {}
        hr['seo-content'] = _status(site_text_ok, None, '' if site_text_ok else 'site_text.json missing (audit_site)')
        hr['seo-schema'] = _status(findings_ok and SCHEMA_FILE.exists(), None,
                                   '' if findings_ok else 'findings.json missing (audit_site)')
        gaps = []
        if not h.get('booking_com_url') or not has_bc:
            gaps.append('no Booking.com facts: NAP comparison uses site + schema only')
        if not has_engine:
            gaps.append('no booking-engine snapshot yet')
        hr['seo-local'] = _status(True, '; '.join(gaps) or None)
        try:
            loc = geo.geocode(next((x.get('value') for x in facts if x.get('kind') == 'address'), '')
                              or f"{h['name']}, {h.get('city', '')}")
            if not loc.get('found'):
                hr['seo-maps'] = _status(False, note='the hotel address could not be geocoded')
            else:
                g = apikeys.get('geoapify')
                gok = apikeys.test('geoapify')[0] if g else False
                hr['seo-maps'] = _status(True, 'Tier 0 (no DataForSEO: no geo-grid, by design)' +
                                         ('' if gok else '; Geoapify key missing/invalid: OpenStreetMap only'))
        except Exception as e:  # noqa: BLE001
            hr['seo-maps'] = _status(False, note=f'geocoding failed: {e}')
        hr['seo-geo'] = _status(site_text_ok, None, '' if site_text_ok else 'site_text.json missing')
        km = (hd / 'keywords' / 'keyword-map.json').exists()
        prompts_ok = all((FLOW_PROMPTS / s).exists() for s in AGENTS['seo-flow']['stages'])
        hr['seo-flow'] = _status(prompts_ok, None if km else 'no keyword map yet: Find stage runs without volumes',
                                 '' if prompts_ok else 'FLOW prompt files missing')
        out['hotels'][h['slug']] = hr
    f = paths.resolve(group_dir) / f'agent-preflight-{date.today().isoformat()}.json'
    f.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding='utf-8')
    out['file'] = str(f)
    return out


def _safe(fut):
    try:
        return fut.result()
    except Exception as e:  # noqa: BLE001
        return {'status': 'blocked', 'note': f'probe failed: {type(e).__name__}: {str(e)[:200]}'}


# ---------------------------------------------------------------- after each agent

def _known_urls(crawl_dir, group_dir):
    cd = paths.resolve(crawl_dir)
    urls = set()
    data = json.loads((cd / 'crawl.json').read_text(encoding='utf-8'))
    urls.update(u['url'].rstrip('/') for u in data.get('urls', []))
    urls.update((l.get('target_url') or '').rstrip('/') for l in data.get('links', []))
    fj = cd / 'findings.json'
    if fj.exists():
        f = json.loads(fj.read_text(encoding='utf-8'))
        urls.update(u.rstrip('/') for u in f.get('pages', {}))
        urls.update(str(x).rstrip('/') for x in (f.get('wordpress') or {}).get('content_links', []))
    return urls


def validate(run_dir, agent, scope, crawl_dir, group_dir=''):
    """Validate findings/<agent>.json against the contract. Returns {'valid', 'errors', 'warnings', 'status'}."""
    import jsonschema
    rd = paths.resolve(run_dir)
    f = rd / 'findings' / f'{agent}.json'
    md = rd / 'findings' / f'{agent}.md'
    errors, warnings = [], []
    if not f.exists():
        return {'valid': False, 'errors': [f'{f.name} missing'], 'warnings': [], 'status': 'missing'}
    if not md.exists():
        warnings.append(f'{md.name} missing (readable findings)')
    try:
        data = json.loads(f.read_text(encoding='utf-8'))
    except ValueError as e:
        return {'valid': False, 'errors': [f'invalid JSON: {e}'], 'warnings': warnings, 'status': 'invalid'}
    if agent.startswith('seo-flow'):
        return _validate_flow(f, md, data, scope, warnings)
    schema = json.loads(SCHEMA_FILE.read_text(encoding='utf-8'))
    v = jsonschema.Draft7Validator(schema)
    for e in sorted(v.iter_errors(data), key=lambda e: list(e.path))[:40]:
        errors.append(f"schema: {'/'.join(str(p) for p in e.path) or '(root)'}: {e.message[:200]}")
    if data.get('scope') and data['scope'] != scope:
        errors.append(f"scope is {data.get('scope')!r}, expected {scope!r}")
    if not data.get('checks'):
        errors.append('no checks: every agent reports what it checked (pass / fail / not_measured)')
    # coverage
    cov = data.get('coverage') or {}
    if not cov.get('checked'):
        errors.append('coverage.checked is empty')
    if scope.startswith('hotel:') and group_dir and agent in ('seo-content', 'seo-geo'):
        slug = scope.split(':', 1)[1]
        mine = set(u.rstrip('/') for u in grp.pages_of(crawl_dir, slug))
        key = {u for u in mine if re.search(r'/(rooms?|suites?|offers?|dining|restaurant|spa|meeting|location|'
                                            r'contact|about)|/$', u + '/')}
        accounted = {u.rstrip('/') for u in cov.get('checked', [])} | \
                    {str(x.get('what', '')).rstrip('/') for x in cov.get('not_checked', [])}
        missing = sorted(key - accounted)
        if missing:
            errors.append(f'{len(missing)} key page(s) of the hotel not checked and not explained: ' + ', '.join(missing[:8]))
    if agent == 'seo-schema':
        fj = paths.resolve(crawl_dir) / 'findings.json'
        if fj.exists():
            blocks = (json.loads(fj.read_text(encoding='utf-8')).get('report') or {}).get('schema', {}).get('blocks', [])
            text = json.dumps(data)
            missing = [b.get('type') for b in blocks if b.get('type') and b['type'] not in text]
            if missing:
                errors.append('schema blocks found by audit_site but not covered: ' + ', '.join(sorted(set(missing))[:10]))
    # numbers match code + no invented URLs
    fj = paths.resolve(crawl_dir) / 'findings.json'
    core = json.loads(fj.read_text(encoding='utf-8')).get('issues', []) if fj.exists() else []
    known = _known_urls(crawl_dir, group_dir)
    for i, x in enumerate(data.get('findings', [])):
        pages = x.get('pages') or []
        unknown = [u for u in pages if u.rstrip('/') not in known and u.startswith('http')]
        if unknown:
            errors.append(f"finding {x.get('id')}: {len(unknown)} URL(s) not in the crawl, sitemap or WordPress: "
                          + ', '.join(unknown[:3]))
        if x.get('check') and any(c['check'] == x['check'] for c in core):
            core_urls = {c['url'].rstrip('/') for c in core if c['check'] == x['check']}
            if scope.startswith('hotel:'):
                slug = scope.split(':', 1)[1]
                reg = grp.load(group_dir) if group_dir else None
                if reg:
                    core_urls = {u for u in core_urls if grp.hotel_for(u, reg) == slug}
            got = {u.rstrip('/') for u in pages}
            if core_urls and got and got != core_urls and not got >= core_urls:
                errors.append(f"finding {x.get('id')} restates {x['check']} but lists {len(got)} URLs; audit_site has "
                              f'{len(core_urls)} for this scope: use the full list')
        if x.get('owner') == 'seo' and x.get('actions') is None:
            warnings.append(f"finding {x.get('id')}: no actions (execute cannot apply it)")
    # agent-specific rules
    text = f.read_text(encoding='utf-8') + (md.read_text(encoding='utf-8') if md.exists() else '')
    if agent == 'seo-performance' and re.search(r'\bFID\b|First Input Delay', text):
        errors.append('mentions FID: Core Web Vitals use INP only')
    if agent == 'seo-agentic':
        la = (data.get('scores') or {}).get('lighthouse_agentic', {})
        if la and la.get('score') is not None and not re.fullmatch(r'\d+/\d+', str(la.get('score'))):
            errors.append('Lighthouse Agentic Browsing must be reported as X/N, not a percentage')
    if agent == 'seo-backlinks':
        bl = (data.get('scores') or {}).get('backlinks', {})
        if bl.get('score') not in (None, 'insufficient data') and 'insufficient' not in str(bl.get('status', '')):
            r, d = _run('validate_backlink_report.py', ['--report', str(f), '--json'], 60)
            if d and d.get('status') == 'FAIL':
                errors.append('validate_backlink_report: ' + '; '.join(map(str, d.get('errors', [])))[:300])
    if agent == 'seo-schema' and re.search(r'"@type"\s*:\s*"(HowTo|SpecialAnnouncement)"', text):
        errors.append('recommends a deprecated schema type (HowTo / SpecialAnnouncement)')
    if agent.startswith('seo-flow') and FLOW_CREDIT not in text:
        errors.append('FLOW credit line missing: "' + FLOW_CREDIT + ': github.com/AgriciDaniel/flow"')
    if agent == 'seo-content':
        from . import facts
        facts_file = ''
        if scope.startswith('hotel:') and group_dir:
            facts_file = str(grp.hotel_dir(group_dir, scope.split(':', 1)[1]) / 'hotel-facts.json')
        doc = {'sections': [{'title': x.get('title', ''), 'blocks': [{'p': x.get('fix', '')}]}
                            for x in data.get('findings', [])]}
        g = facts.check(doc, crawl_dir, facts_file)
        if g.get('unverified'):
            errors.append(f"{len(g['unverified'])} unconfirmed fact(s) not marked [CONFIRM], e.g. "
                          + '; '.join(f"{u['phrase']} ({u['section']})" for u in g['unverified'][:4]))
    # secrets
    for s in apikeys.secrets():
        if s in text:
            errors.append('an API key appears in the output')
            break
    if re.search(r'AIza[0-9A-Za-z_-]{20,}', text):
        errors.append('a Google API key appears in the output')
    status = 'complete' if not errors and data.get('status') != 'partial' else (
        'partial' if not errors else 'invalid')
    return {'valid': not errors, 'errors': errors, 'warnings': warnings, 'status': status,
            'findings': len(data.get('findings', [])), 'checks': len(data.get('checks', []))}


def _validate_flow(f, md, data, scope, warnings):
    """FLOW output feeds the Build Plan; it is not scored. Contract: agent, scope, stage, status, credit,
    prompts_applied[{file, why}], outputs[{prompt, result, evidence_needed, build_plan_items[]}]."""
    errors = []
    for k in ('agent', 'scope', 'stage', 'status', 'prompts_applied', 'outputs'):
        if k not in data:
            errors.append(f'missing {k}')
    if data.get('scope') and data['scope'] != scope:
        errors.append(f"scope is {data.get('scope')!r}, expected {scope!r}")
    if data.get('stage') not in AGENTS['seo-flow']['stages']:
        errors.append(f"stage must be one of {AGENTS['seo-flow']['stages']}")
    if len(data.get('prompts_applied') or []) > 5:
        errors.append('more than 5 prompts applied in one call')
    for p in data.get('prompts_applied') or []:
        if not (FLOW_PROMPTS / data.get('stage', '') / str(p.get('file', ''))).exists():
            errors.append(f"prompt file {p.get('file')} is not in prompts/{data.get('stage')}/")
    text = f.read_text(encoding='utf-8') + (md.read_text(encoding='utf-8') if md.exists() else '')
    if FLOW_CREDIT not in text:
        errors.append('FLOW credit line missing: "' + FLOW_CREDIT + ': github.com/AgriciDaniel/flow"')
    for s in apikeys.secrets():
        if s in text:
            errors.append('an API key appears in the output')
            break
    return {'valid': not errors, 'errors': errors, 'warnings': warnings,
            'status': ('complete' if data.get('status') != 'partial' else 'partial') if not errors else 'invalid',
            'outputs': len(data.get('outputs') or [])}


def record(run_dir, agent, result, attempt):
    """Append an agent's final status to <run>/agent-status.json."""
    rd = paths.resolve(run_dir)
    rd.mkdir(parents=True, exist_ok=True)
    f = rd / 'agent-status.json'
    doc = json.loads(f.read_text(encoding='utf-8')) if f.exists() else {}
    status = result.get('status')
    if not result.get('valid') and attempt >= 2:
        status = 'not assessed'
    doc[agent] = {'status': status, 'attempt': attempt, 'errors': result.get('errors', [])[:10],
                  'warnings': result.get('warnings', [])[:10], 'at': time.strftime('%Y-%m-%d %H:%M')}
    f.write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding='utf-8')
    return doc[agent]
