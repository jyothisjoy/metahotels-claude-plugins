# usage: python -I wp.py <mcp-server-name> <METHOD> </wp-json/path> [json-body]
# Calls the site's WP REST API with the same Basic-auth application password the MCP server uses
# (the server entry in ~/.claude.json, user or project scope: wp/mcpconf.py). The credential is never printed.
# In Git Bash, prefix with MSYS_NO_PATHCONV=1 or the /wp-json path gets rewritten to a Windows path.
# Examples:
#   python -I wp.py <site>-content GET "/wp-json/wp/v2/plugins?context=edit"
#   python -I wp.py <site>-content GET "/wp-json/wp/v2/elementor_snippet/2178?context=edit"   (Elementor Custom Code: meta._elementor_code)
import json, os, sys, urllib.request, urllib.parse

server, method, path = sys.argv[1], sys.argv[2], sys.argv[3]
body = sys.argv[4].encode() if len(sys.argv) > 4 else None
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'wp'))
import mcpconf  # noqa: E402
cfg = mcpconf.get(server)
auth = cfg['headers']['Authorization']
req = urllib.request.Request(mcpconf.base(cfg) + path, data=body, method=method,
                             headers={'Authorization': auth, 'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0 perf-audit'})
try:
    with urllib.request.urlopen(req, timeout=60) as f:
        print(f.read().decode())
except urllib.error.HTTPError as e:
    print('HTTP', e.code, e.read().decode()[:2000])
