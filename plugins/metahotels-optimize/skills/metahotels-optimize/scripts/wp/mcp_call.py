"""Call one tool of a site's MCP server and write the result to a file (keeps big Elementor trees out of the chat).

usage: python -I mcp_call.py <mcp-server-name> <tool-name> <arguments.json | inline-json> <out.json>

Uses the URL and Authorization header of the server entry in ~/.claude.json (user or project scope, mcpconf.py);
the credential is never printed.
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

server, tool, args, outp = sys.argv[1:5]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mcpconf  # noqa: E402
cfg = mcpconf.get(server)
url = cfg['url']
base_headers = {
    'Authorization': cfg['headers']['Authorization'],
    'Content-Type': 'application/json',
    'Accept': 'application/json, text/event-stream',
    'User-Agent': 'Mozilla/5.0 perf-audit',
}
arguments = json.load(open(args, encoding='utf-8')) if os.path.exists(args) else json.loads(args)
session = {}


def rpc(payload):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method='POST', headers={**base_headers, **session})
    try:
        with urllib.request.urlopen(req, timeout=180) as f:
            sid = f.headers.get('Mcp-Session-Id')
            if sid:
                session['Mcp-Session-Id'] = sid
            body = f.read().decode('utf-8')
            ctype = f.headers.get('Content-Type', '')
    except urllib.error.HTTPError as e:
        print('HTTP', e.code, e.read().decode('utf-8', 'replace')[:600])
        sys.exit(1)
    if not body.strip():
        return None
    if 'text/event-stream' in ctype:
        data = [line[5:].strip() for line in body.splitlines() if line.startswith('data:')]
        return json.loads(data[-1]) if data else None
    return json.loads(body)


rpc({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-03-26', 'capabilities': {}, 'clientInfo': {'name': 'perf-audit', 'version': '1.0'}}})
rpc({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
res = rpc({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call', 'params': {'name': tool, 'arguments': arguments}})
if not res or 'error' in res:
    print('MCP error', json.dumps(res)[:600])
    sys.exit(1)
result = res['result']
out = result.get('structuredContent')
if out is None:
    text = ''.join(c.get('text', '') for c in result.get('content', []) if c.get('type') == 'text')
    try:
        out = json.loads(text)
    except ValueError:
        out = {'text': text}
json.dump(out, open(outp, 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
print('ok', tool, 'isError=%s' % result.get('isError', False), 'bytes', os.path.getsize(outp), 'keys', list(out.keys())[:8] if isinstance(out, dict) else type(out).__name__)
