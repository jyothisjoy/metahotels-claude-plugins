"""Trustworthy client reports: only validated agents reach the Audit Report, and the Health Score shows its
coverage, the booking-path cap and "Blocked"."""
import json

import pytest

from hotel_seo_tools import group, pdf, preflight, report

SITE = 'https://ex-hotel.com/'
RUN = '2026-11-11'


@pytest.fixture
def site(tmp_path, monkeypatch):
    """A single-hotel site with a crawl (no audit_site issues) and an empty audit run folder."""
    monkeypatch.setenv('HOTEL_SEO_HOME', str(tmp_path))
    monkeypatch.chdir(tmp_path)
    group.save('ex-hotel.com', {'name': 'Ex Hotel', 'site': SITE}, [{'slug': 'ex', 'name': 'Ex Hotel', 'paths': ['/']}])
    d = tmp_path / 'ex-hotel.com'
    crawl = d / 'crawl-2026-11-10'
    crawl.mkdir()
    urls = [SITE, SITE + 'rooms/', SITE + 'contact/']
    (crawl / 'crawl.json').write_text(json.dumps({'urls': [{'url': u} for u in urls], 'links': []}), encoding='utf-8')
    (crawl / 'findings.json').write_text(json.dumps({'issues': [], 'pages': {}}), encoding='utf-8')
    run = d / f'audit-{RUN}'
    (run / 'findings').mkdir(parents=True)
    return {'dir': d, 'crawl': str(crawl), 'run': run}


def _agent_file(run, agent, title, checks=True, category='Technical'):
    data = {'agent': agent, 'scope': 'site', 'status': 'complete', 'coverage': {'checked': [SITE]},
            'checks': [{'id': f'{agent}:x', 'category': category, 'title': 'x', 'result': 'pass',
                        'severity': 'Medium'}] if checks else [],
            'findings': [{'id': f'{agent}-1', 'category': category, 'title': title, 'severity': 'Medium',
                          'hotel': 'group', 'evidence': {'summary': '1 page', 'tool': 'test'}, 'pages': [SITE],
                          'fix': 'Fix it.', 'owner': 'seo', 'checks': [], 'actions': []}]}
    (run / 'findings' / f'{agent}.json').write_text(json.dumps(data), encoding='utf-8')
    (run / 'findings' / f'{agent}.md').write_text(f'# {agent}\n', encoding='utf-8')


def _validate(site, agent, attempt=1):
    res = preflight.validate(str(site['run']), agent, 'site', site['crawl'], 'ex-hotel.com')
    preflight.record(str(site['run']), agent, res, attempt)
    return res


def _built(site):
    report.build('ex-hotel.com', 'ex', RUN)
    return json.loads((site['run'] / 'audit-report.json').read_text(encoding='utf-8'))


def _titles(rep):
    return {s['title'] for s in rep['sections']}


def test_valid_agent_kept_invalid_and_unvalidated_excluded(site):
    _agent_file(site['run'], 'seo-technical', 'Valid technical finding')
    _agent_file(site['run'], 'seo-performance', 'Finding from a failed agent', checks=False, category='Performance')
    _agent_file(site['run'], 'seo-sitemap', 'Finding nobody validated')
    assert _validate(site, 'seo-technical')['valid']
    assert not _validate(site, 'seo-performance')['valid']          # no checks: fails the contract
    assert not _validate(site, 'seo-performance', attempt=2)['valid']
    rep = _built(site)
    assert 'Valid technical finding' in _titles(rep)
    assert 'Finding from a failed agent' not in _titles(rep)
    assert 'Finding nobody validated' not in _titles(rep)
    st = rep['agent_status']
    assert st['seo-technical'] == 'complete'
    assert st['seo-performance'].startswith('not assessed: failed validation twice')
    assert st['seo-sitemap'] == 'not assessed: output not validated (no validate_agent_output record)'
    assert st['seo-content'] == 'not assessed: did not run'
    # the excluded agent's checks are not scored either
    srcs = {c['name']: c['basis'] for c in rep['scores']['categories']}
    assert 'seo-sitemap' not in srcs['Technical'].split(';')[0]
    # and the status table in the rendered document says so
    pdf.normalize(rep)
    scores_sec = next(s for s in rep['sections'] if s['title'] == 'Scores')
    status_rows = [b['table']['rows'] for b in scores_sec['blocks'] if 'table' in b][-1]
    assert ['seo-performance', st['seo-performance']] in status_rows


def test_file_changed_after_validation_is_excluded(site):
    _agent_file(site['run'], 'seo-technical', 'Original finding')
    assert _validate(site, 'seo-technical')['valid']
    _agent_file(site['run'], 'seo-technical', 'Edited after validation')
    rep = _built(site)
    assert 'Edited after validation' not in _titles(rep)
    assert 'changed after validation' in rep['agent_status']['seo-technical']


def _checks(**cats):
    """One passing Medium check per named weighted category (value = how many), all measured."""
    out = []
    for cat in report.WEIGHTS:
        for i in range(cats.get(cat, 1)):
            out.append({'id': f'{cat}:{i}', 'category': cat, 'result': 'pass', 'severity': 'Medium'})
    return out


def _core(check, result='fail', key_page=False):
    cat, sev = report.CORE[check][:2]
    return {'id': f'core:{check}', 'category': cat, 'title': report.CORE[check][2], 'result': result,
            'severity': sev, 'key_page': key_page, 'source': 'audit_site'}


def test_full_coverage_scored():
    s = report.score_all(_checks())
    assert s['coverage'] == 100 and s['health_status'] == 'scored' and s['health'] == s['health_raw'] == 100
    assert s['health_label'] == '100/100' and 'covers 100%' in s['health_note']


def test_low_coverage_not_scored():
    checks = [c for c in _checks() if c['category'] in ('Technical', 'Content', 'Booking path & facts')]
    checks += [{'id': 'onpage:nm', 'category': 'On-Page', 'result': 'not_measured', 'severity': 'High'}]
    s = report.score_all(checks)
    assert s['coverage'] < report.COVERAGE_MIN
    assert s['health'] is None and s['health_status'] == 'not scored' and s['health_label'] == 'not scored'
    assert s['health_raw'] == 100                       # still computed, never shown as the score
    assert f"{s['coverage']}%" in s['health_note']
    assert report.scores(checks)[0] is None


def test_one_booking_path_critical_caps_at_59():
    s = report.score_all(_checks(Technical=40) + [_core('booking_link_dead')])
    assert s['health_raw'] > report.HEALTH_CAP
    assert s['health'] == report.HEALTH_CAP and s['health_status'] == 'capped'
    assert 'Dead booking links' in s['health_note']


def test_two_booking_path_criticals_blocked():
    s = report.score_all(_checks(Technical=40) + [_core('booking_link_dead'), _core('booking_link_other_hotel')])
    assert s['health'] is None and s['health_status'] == 'blocked' and s['health_label'] == 'Blocked'
    assert len(s['booking_path_fails']) == 2


def test_same_check_twice_is_one_failure_and_canonical_needs_a_key_page():
    s = report.score_all(_checks(Technical=40) + [_core('booking_link_dead'), _core('booking_link_dead'),
                                                  _core('canonical_broken', key_page=False)])
    assert s['health_status'] == 'capped'
    s = report.score_all(_checks(Technical=40) + [_core('booking_link_dead'), _core('canonical_broken', key_page=True)])
    assert s['health_status'] == 'blocked'


def test_booking_path_ids_exist_in_the_check_table():
    for cid in report.BOOKING_PATH_CRITICAL:
        name = cid.split(':', 1)[1]
        assert report.CORE[name][1] == 'Critical'


def test_cap_reaches_the_rendered_report(site):
    (site['dir'] / 'crawl-2026-11-10' / 'findings.json').write_text(json.dumps({'issues': [
        {'url': SITE, 'check': 'booking_link_dead', 'detail': 'Book now -> https://old.example/book', 'page_type': 'home'}],
        'pages': {}}), encoding='utf-8')
    _agent_file(site['run'], 'seo-technical', 'Valid technical finding')
    _validate(site, 'seo-technical')
    rep = _built(site)
    sc = rep['scores']
    assert sc['coverage'] >= report.COVERAGE_MIN          # Performance (agent) and Images (no crawl file) missing
    assert sc['health_status'] == 'capped' and sc['health'] == report.HEALTH_CAP < sc['health_raw']
    assert 'covers' in sc['health_note'] and 'Dead booking links' in sc['health_note']
    pdf.normalize(rep)
    assert sc['health_label'] in rep['lead'] and 'covers' in rep['lead']
