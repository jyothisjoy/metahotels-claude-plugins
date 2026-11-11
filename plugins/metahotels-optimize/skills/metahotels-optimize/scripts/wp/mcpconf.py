"""Find a WordPress MCP server entry in Claude Code's config, for the tools that call the site's REST API and MCP
server directly (wp.py, mcp_call.py, wp_upload.py, upload-file.py, chatbot-lazy.py, site-init.py).

Entries are read from ~/.claude.json (CLAUDE_CONFIG overrides the path): user scope ("mcpServers") first, then every
project's "mcpServers". The Authorization header is used for requests and never printed.
"""
import json
import os
import sys
import urllib.parse


def _config():
    p = os.environ.get('CLAUDE_CONFIG') or os.path.expanduser('~/.claude.json')
    try:
        return json.load(open(p, encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def entries():
    """[(scope, name, entry)] for every HTTP MCP server with a URL."""
    c = _config()
    out = [('user', n, e) for n, e in (c.get('mcpServers') or {}).items()]
    for proj, v in (c.get('projects') or {}).items():
        out += [('project:' + proj, n, e) for n, e in (v.get('mcpServers') or {}).items()]
    return [x for x in out if isinstance(x[2], dict) and x[2].get('url')]


def get(name):
    """The entry named `name` (user scope wins); exits with a hint when it is missing."""
    for scope, n, e in entries():
        if n == name:
            if not (e.get('headers') or {}).get('Authorization'):
                sys.exit('MCP server %r has no Authorization header: add it with an application password '
                         '(references/site-setup.md)' % name)
            return e
    sys.exit('MCP server %r not found in ~/.claude.json: run the site onboarding (site-init.py) for the command '
             'that adds it' % name)


def by_host(host):
    """[(scope, name, path)] of the entries whose URL is on this host (with or without www)."""
    h = host.lower().removeprefix('www.')
    hits = []
    for scope, n, e in entries():
        u = urllib.parse.urlparse(e['url'])
        if (u.hostname or '').lower().removeprefix('www.') == h:
            hits.append((scope, n, u.path, bool((e.get('headers') or {}).get('Authorization'))))
    return hits


def base(entry):
    """scheme://host of an entry, plus the path before /wp-json (WordPress in a subfolder)."""
    u = urllib.parse.urlparse(entry['url'])
    prefix = u.path.split('/wp-json', 1)[0] if '/wp-json' in u.path else ''
    return '%s://%s%s' % (u.scheme, u.netloc, prefix)
