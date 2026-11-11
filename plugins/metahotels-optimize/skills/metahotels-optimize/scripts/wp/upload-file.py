"""Upload one local file to the WordPress media library as a new attachment (REST, same credential as wp.py).

Usage: python -I upload-file.py <mcp-server-name> <file> <title> [alt text]
Prints the new attachment id and URL. Nothing existing is touched.
"""
import json
import mimetypes
import os
import sys
import urllib.parse
import urllib.request

server, path, title = sys.argv[1:4]
alt = sys.argv[4] if len(sys.argv) > 4 else ''
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mcpconf  # noqa: E402
cfg = mcpconf.get(server)
root = mcpconf.base(cfg) + '/wp-json/wp/v2/media'
name = os.path.basename(path)
ctype = mimetypes.guess_type(name)[0] or 'application/octet-stream'


def call(url, data, headers):
    req = urllib.request.Request(url, data=data, method='POST', headers=dict(
        {'Authorization': cfg['headers']['Authorization'], 'User-Agent': 'Mozilla/5.0 perf-audit'}, **headers))
    with urllib.request.urlopen(req, timeout=120) as f:
        return json.loads(f.read().decode())


m = call(root, open(path, 'rb').read(), {'Content-Type': ctype, 'Content-Disposition': 'attachment; filename="%s"' % name})
call('%s/%s' % (root, m['id']), json.dumps({'title': title, 'alt_text': alt}).encode(), {'Content-Type': 'application/json'})
print(json.dumps({'id': m['id'], 'url': m['source_url'], 'mime': m['mime_type'], 'bytes': os.path.getsize(path)}))
