"""Site credentials (sites.csv) and the MCP client for each hotel website's WordPress MCP endpoint.

sites.csv lives in the root of the work folder (the folder Claude was started in; desktop app:
~/Documents/MetaHotels SEO). Columns, as exported from the team sheet:
    Website Name, App name, User name, App Password, Content endpoint
The endpoint is the full MCP URL, e.g. https://hotel.com/wp-json/mcp/wp-content. Rows are matched to a site by
host. The file holds passwords: it is never committed, and nothing here ever returns or logs a password.

Read tools can be called directly with `call(site, tool, args)`. Write tools are refused here: they run only through
execute.py, inside a batch the user approved (see execute.run_batch), via `call(..., _write_ok=True)`.
"""
import asyncio
import base64
import csv
import io
import os
import re
from pathlib import Path
from urllib.parse import urlparse

from . import paths

FILE_NAME = 'sites.csv'
USER_AGENT = 'hotel-seo-mcp-client/0.9 (MetaHotels; +https://claude.com/claude-code)'
ENDPOINT_RE = re.compile(r'^https://[^/\s]+/wp-json/mcp/[A-Za-z0-9_-]+/?$')
# Tools that only read. Anything else on a site's MCP server is treated as a write.
READ_PREFIXES = ('get-', 'list-', 'seo-get-', 'elementor-get-', 'elementor-list-', 'polylang-get-',
                 'polylang-list-', 'redirects-list', 'discover-abilities', 'get-ability-info')
# Read-only tools whose names don't start with a read prefix. Nov 2026: find-text and resolve-url were treated as
# writes, so execute's read-only planning pass could not call them and parked every text fix it needed them for.
READ_NAMES = {'content-integrations-status', 'get-site-settings', 'find-text', 'resolve-url'}


def csv_path():
    override = os.environ.get('HOTEL_SEO_SITES_CSV')
    return Path(override).expanduser() if override else paths.work_dir() / FILE_NAME


def _host(u):
    u = (u or '').strip()
    if u and '//' not in u:
        u = 'https://' + u
    return urlparse(u).netloc.lower().removeprefix('www.')


def _read_text(p):
    raw = p.read_bytes()
    for enc in ('utf-8-sig', 'cp1252', 'latin-1'):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode('utf-8', errors='replace')


def load():
    """All rows as dicts: name, app_name, user, password, endpoint, host, problems[]. Raises if the file is missing."""
    p = csv_path()
    if not p.exists():
        raise FileNotFoundError(f'{FILE_NAME} not found in the work folder ({p.parent}). Put the exported site '
                                'sheet there as sites.csv (columns: Website Name, App name, User name, App Password, '
                                'Content endpoint).')
    rows = []
    reader = csv.reader(io.StringIO(_read_text(p)))
    header = [h.strip().lower() for h in next(reader, [])]

    def col(r, *names):
        for n in names:
            if n in header:
                i = header.index(n)
                return (r[i] if i < len(r) else '').strip()
        return ''
    for r in reader:
        if not any(c.strip() for c in r):
            continue
        row = {'name': col(r, 'website name'), 'app_name': col(r, 'app name'), 'user': col(r, 'user name'),
               'password': col(r, 'app password'), 'endpoint': col(r, 'content endpoint')}
        row['host'] = _host(row['endpoint'])
        probs = []
        if not ENDPOINT_RE.match(row['endpoint']):
            probs.append('endpoint is not a full https://<host>/wp-json/mcp/<server> URL')
        if not row['user']:
            probs.append('user name missing')
        if not row['password']:
            probs.append('app password missing')
        row['problems'] = probs
        rows.append(row)
    return rows


def public(row):
    """A row without its password, for anything shown to Claude or the user."""
    return {'name': row['name'], 'host': row['host'], 'endpoint': row['endpoint'], 'user_set': bool(row['user']),
            'password_set': bool(row['password']), 'problems': row['problems']}


def summary():
    """Every row, without secrets: which are complete and which are not."""
    try:
        rows = load()
    except FileNotFoundError as e:
        return {'file': str(csv_path()), 'found': False, 'reason': str(e)}
    return {'file': str(csv_path()), 'found': True, 'rows': len(rows),
            'complete': sum(1 for r in rows if not r['problems']),
            'duplicate_hosts': sorted({r['host'] for r in rows if sum(x['host'] == r['host'] for x in rows) > 1}),
            'incomplete': [{'name': r['name'], 'problems': r['problems']} for r in rows if r['problems']]}


def find_all(site):
    """Every row for a site URL, host or website name (a site can appear twice in the sheet)."""
    rows = load()
    h = _host(site)
    hits = [r for r in rows if h and r['host'] == h]
    if not hits:
        s = (site or '').strip().lower()
        hits = [r for r in rows if s and r['name'].strip().lower() == s]
    return hits


def find(site):
    """The first row for a site, or None."""
    hits = find_all(site)
    return hits[0] if hits else None


def _candidates(site):
    hits = find_all(site)
    if not hits:
        raise LookupError(f'no row for {site} in {FILE_NAME}')
    ok = [r for r in hits if not r['problems']]
    if not ok:
        raise ValueError(f'{FILE_NAME} row "{hits[0]["name"]}" is incomplete: ' + '; '.join(hits[0]['problems']))
    return ok


def _require(site):
    return _candidates(site)[0]


def explain(err):
    """Plain-language reason for a connection failure (no secrets)."""
    t = str(err)
    if '401' in t:
        return ('login rejected (401): the user name or application password in sites.csv is wrong or was revoked. '
                'Create a new application password for that user in WordPress and update the row.')
    if '403' in t:
        return ('WordPress refused (403 "not authorized"): the login reaches the site but this user may not use MCP '
                'there. Check the user role / the MCP plugin settings, or a security plugin blocking REST requests.')
    if '405' in t or '404' in t:
        return ('no MCP endpoint at this URL (404/405): the MCP plugin is not installed or the site is not '
                'WordPress. Check the Content endpoint column.')
    return t[:300]


def short(tool):
    """'mcp-adapter-seo-update-posts' -> 'seo-update-posts'."""
    return re.sub(r'^mcp-adapter-', '', tool or '')


def is_read_tool(tool):
    t = short(tool)
    return t in READ_NAMES or t.startswith(READ_PREFIXES)


async def _session_do(row, fn):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
    token = base64.b64encode(f"{row['user']}:{row['password']}".encode()).decode()
    # LiteSpeed firewalls on several hotel sites return 403 to the default python-httpx / python-requests
    # user agents, so the client names itself.
    headers = {'Authorization': f'Basic {token}', 'User-Agent': USER_AGENT}
    async with streamablehttp_client(row['endpoint'], headers=headers, timeout=60) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await fn(session)


def _leaf(e):
    while isinstance(e, BaseExceptionGroup) and e.exceptions:
        e = e.exceptions[0]
    return e


def _run(coro):
    # Called from worker threads (server._off_loop), so a fresh event loop is fine.
    try:
        return asyncio.run(coro)
    except BaseExceptionGroup as g:
        raise _leaf(g) from None


def _scrub(text, row):
    text = str(text)
    for s in (row.get('password'), base64.b64encode(f"{row['user']}:{row['password']}".encode()).decode()):
        if s:
            text = text.replace(s, 'REDACTED')
    return text


_WORKING_ROW = {}       # host -> endpoint of the row that last connected (duplicate rows)


def _with_session(site, fn):
    """Run fn(session) with the first row of `site` that logs in. Returns (row, result)."""
    rows = _candidates(site)
    pref = _WORKING_ROW.get(rows[0]['host'])
    rows.sort(key=lambda r: r['endpoint'] + r['user'] != pref)
    last = None
    for row in rows:
        try:
            res = _run(_session_do(row, fn))
            _WORKING_ROW[row['host']] = row['endpoint'] + row['user']
            return row, res
        except (PermissionError, LookupError):
            raise
        except Exception as e:  # noqa: BLE001 - try the next duplicate row on login errors only
            last = (row, e)
            if not any(code in str(e) for code in ('401', '403')):
                break
    row, e = last
    raise RuntimeError(_scrub(f'{type(e).__name__}: {e}', row)) from None


def tools(site):
    """[{name, short, read_only, description, input_schema}] for the site's MCP server."""
    async def fn(session):
        res = await session.list_tools()
        return [{'name': t.name, 'short': short(t.name), 'read_only': is_read_tool(t.name),
                 'description': (t.description or '')[:500], 'input_schema': t.inputSchema} for t in res.tools]
    return _with_session(site, fn)[1]


def status(site):
    """Connect, list tools, and read content-integrations-status when the site has it."""
    try:
        rows = _candidates(site)
    except (LookupError, ValueError, FileNotFoundError) as e:
        return {'site': site, 'connected': False, 'reason': str(e)}
    try:
        ts = tools(site)
    except RuntimeError as e:
        return {'site': site, 'row': rows[0]['name'], 'connected': False, 'reason': explain(e),
                'detail': str(e)[:300]}
    names = [t['short'] for t in ts]
    out = {'site': site, 'row': rows[0]['name'], 'connected': True, 'tools': len(ts),
           'write_tools': sorted(t['short'] for t in ts if not t['read_only']),
           'read_tools': sorted(t['short'] for t in ts if t['read_only'])}
    if 'content-integrations-status' in names:
        try:
            out['integrations'] = call(site, 'content-integrations-status', {}).get('structured')
        except Exception as e:  # noqa: BLE001
            out['integrations_error'] = str(e)[:300]
    elif 'discover-abilities' in names:
        out['note'] = 'Abilities server: tools are reached through discover-abilities / execute-ability.'
    return out


def call(site, tool, args=None, _write_ok=False):
    """Call one tool on the site's MCP server. Write tools are refused unless execute.py passes _write_ok."""
    if not is_read_tool(tool) and not _write_ok:
        raise PermissionError(f'{short(tool)} changes the site. Writes only run through /hotel-seo execute, inside '
                              'a batch the user approved.')

    async def fn(session):
        listed = await session.list_tools()
        by_short = {short(t.name): t.name for t in listed.tools}
        name = tool if tool in {t.name for t in listed.tools} else by_short.get(short(tool))
        if not name:
            raise LookupError(f'{short(tool)} is not available on this site')
        res = await session.call_tool(name, args or {})
        parts = [getattr(c, 'text', None) or str(c) for c in res.content]
        return {'is_error': bool(res.isError), 'structured': getattr(res, 'structuredContent', None),
                'text': '\n'.join(parts)}
    row, out = _with_session(site, fn)
    out['text'] = _scrub(out['text'], row)
    if out['structured'] is None:
        import json
        try:
            out['structured'] = json.loads(out['text'])
        except ValueError:
            pass
    return out
