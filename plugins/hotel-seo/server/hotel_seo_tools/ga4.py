"""Google Analytics 4 numbers for the monthly report, read with the Google sign-in from init (analytics.readonly).

The GA4 MCP server (hotel-seo-ga4) is for Claude's own questions; the report's numbers come from here so they are
computed in code, the same way every month.
"""
import json
import re
from urllib.parse import urlparse

from . import paths

DATA = 'https://analyticsdata.googleapis.com/v1beta/'
ADMIN = 'https://analyticsadmin.googleapis.com/v1beta/'

# Sources GA4 records for visits that came from an AI assistant. One list, used everywhere.
AI_SOURCES = {
    'ChatGPT': r'chatgpt|openai',
    'Perplexity': r'perplexity',
    'Gemini': r'gemini\.google|bard\.google',
    'Copilot': r'copilot|bing\.com/chat',
    'Claude': r'claude\.ai|anthropic',
    'DeepSeek': r'deepseek',
    'Meta AI': r'meta\.ai',
    'Grok': r'grok',
    'Mistral': r'mistral|chat\.mistral',
    'You.com': r'(^|\.)you\.com',
    'Phind': r'phind',
}
AI_REGEX = '|'.join(f'({v})' for v in AI_SOURCES.values())


def ai_label(source):
    for name, rx in AI_SOURCES.items():
        if re.search(rx, source or '', re.I):
            return name
    return source


def _session():
    if not paths.GA_CREDENTIALS.exists():
        return None
    from google.auth.transport.requests import AuthorizedSession
    from google.oauth2.credentials import Credentials
    info = json.loads(paths.GA_CREDENTIALS.read_text())
    creds = Credentials.from_authorized_user_info(info, info.get('scopes') or [paths.GA_SCOPE])
    s = AuthorizedSession(creds)
    if info.get('quota_project_id'):
        s.headers['x-goog-user-project'] = info['quota_project_id']
    return s


def _pid(prop):
    p = str(prop or '').strip()
    return p if p.startswith('properties/') else f'properties/{p}'


_FOUND = {}


def find_property(host):
    """GA4 property whose web stream URL is on this host: (property, display name) or (None, reason).
    Remembered for the session: the hotels of a group share one host."""
    key = host.lower().replace('www.', '')
    if key not in _FOUND or _FOUND[key][0] is None:
        _FOUND[key] = _find_property(key)
    return _FOUND[key]


def _find_property(host):
    s = _session()
    if s is None:
        return None, 'no Google sign-in (run hotel-seo-auth)'
    host = host.lower().replace('www.', '')
    r = s.get(ADMIN + 'accountSummaries', params={'pageSize': 200}, timeout=60)
    if r.status_code != 200:
        return None, f'GA4 admin API {r.status_code}: {r.text[:200]}'
    for acc in r.json().get('accountSummaries', []):
        for p in acc.get('propertySummaries', []):
            st = s.get(ADMIN + p['property'] + '/dataStreams', timeout=60)
            for d in (st.json().get('dataStreams', []) if st.status_code == 200 else []):
                uri = (d.get('webStreamData') or {}).get('defaultUri', '')
                if uri and urlparse(uri if '//' in uri else '//' + uri).netloc.lower().replace('www.', '') == host:
                    return p['property'], p.get('displayName', '')
    return None, f'no GA4 web stream for {host} is visible to the signed-in account'


def _filter(prefixes, extra=None):
    """Landing page starts with one of the hotel's path prefixes (and the extra filter, if any)."""
    parts = []
    if prefixes and prefixes != ['/']:
        parts.append({'orGroup': {'expressions': [
            {'filter': {'fieldName': 'landingPage', 'stringFilter': {'matchType': 'BEGINS_WITH', 'value': p}}}
            for p in prefixes]}})
    if extra:
        parts.append(extra)
    if not parts:
        return None
    return parts[0] if len(parts) == 1 else {'andGroup': {'expressions': parts}}


def report(prop, start, end, dims, metrics, prefixes=None, extra=None, limit=10000):
    s = _session()
    if s is None:
        raise RuntimeError('no Google sign-in (run hotel-seo-auth)')
    body = {'dateRanges': [{'startDate': str(start), 'endDate': str(end)}],
            'dimensions': [{'name': d} for d in dims], 'metrics': [{'name': m} for m in metrics],
            'limit': limit}
    f = _filter(prefixes, extra)
    if f:
        body['dimensionFilter'] = f
    r = s.post(DATA + _pid(prop) + ':runReport', json=body, timeout=120)
    if r.status_code != 200:
        raise RuntimeError(f'GA4 {r.status_code}: {r.text[:300]}')
    out = []
    for row in r.json().get('rows', []):
        d = {n: v['value'] for n, v in zip(dims, row.get('dimensionValues', []))}
        for n, v in zip(metrics, row.get('metricValues', [])):
            try:
                d[n] = float(v['value'])
            except (TypeError, ValueError):
                d[n] = 0.0
        out.append(d)
    return out


ORGANIC = {'filter': {'fieldName': 'sessionDefaultChannelGroup',
                      'stringFilter': {'matchType': 'EXACT', 'value': 'Organic Search'}}}
AI_FILTER = {'filter': {'fieldName': 'sessionSource',
                        'stringFilter': {'matchType': 'PARTIAL_REGEXP', 'value': AI_REGEX, 'caseSensitive': False}}}
TOTALS = ['sessions', 'engagedSessions', 'userEngagementDuration', 'keyEvents', 'ecommercePurchases',
          'purchaseRevenue']


def _totals(rows):
    t = {m: sum(r.get(m, 0) for r in rows) for m in TOTALS}
    s = t['sessions']
    return {'sessions': int(s), 'engaged_sessions': int(t['engagedSessions']),
            'engagement_rate_pct': round(100 * t['engagedSessions'] / s, 1) if s else None,
            'avg_engagement_s': round(t['userEngagementDuration'] / s) if s else None,
            'key_events': int(t['keyEvents']), 'purchases': int(t['ecommercePurchases']),
            'purchase_revenue': round(t['purchaseRevenue'], 2)}


def period(prop, start, end, prefixes=None):
    """One period: all visits, Google organic visits, visits from AI assistants (by assistant)."""
    all_rows = report(prop, start, end, [], TOTALS, prefixes)
    org = report(prop, start, end, [], TOTALS, prefixes, ORGANIC)
    ai = report(prop, start, end, ['sessionSource'], TOTALS, prefixes, AI_FILTER)
    by = {}
    for r in ai:
        name = ai_label(r['sessionSource'])
        b = by.setdefault(name, {'assistant': name, 'sources': [], 'sessions': 0, 'engaged_sessions': 0,
                                 'key_events': 0})
        b['sources'].append(r['sessionSource'])
        b['sessions'] += int(r['sessions'])
        b['engaged_sessions'] += int(r['engagedSessions'])
        b['key_events'] += int(r['keyEvents'])
    out = {'from': str(start), 'to': str(end), 'all': _totals(all_rows), 'organic': _totals(org),
           'ai': {**_totals(ai), 'by_assistant': sorted(by.values(), key=lambda x: -x['sessions'])}}
    if not out['all']['sessions']:
        # no visits at all: the property was not collecting then; show "–", never zeros
        out['no_data'] = True
        for k in ('all', 'organic', 'ai'):
            out[k] = {m: None for m in out[k] if m != 'by_assistant'} | (
                {'by_assistant': []} if k == 'ai' else {})
    return out
