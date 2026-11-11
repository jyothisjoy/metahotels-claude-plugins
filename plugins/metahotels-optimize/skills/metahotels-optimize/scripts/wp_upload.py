# usage: python -I wp_upload.py <mcp-server-name> <results.json> <uploaded.json>
# Uploads the optimized files listed in results.json (from a site's tools/optimize-images.py) to the WordPress
# media library as NEW attachments through /wp-json/wp/v2/media, copying alt text and title from the original.
# Uses the same application password as wp.py; the credential is never printed. Originals are not touched.
# Writes uploaded.json: [{old_id, old_url, new_id, new_url, before, after}]. Already-uploaded entries are skipped.
import json, os, sys, urllib.request, urllib.parse

server, results, outp = sys.argv[1:4]
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'wp'))
import mcpconf  # noqa: E402
cfg = mcpconf.get(server)
auth = cfg['headers']['Authorization']
root = mcpconf.base(cfg) + '/wp-json/wp/v2/media'
done = json.load(open(outp, encoding='utf-8')) if os.path.exists(outp) else []
have = {d['old_id'] for d in done}

def call(url, data, headers):
    req = urllib.request.Request(url, data=data, method='POST', headers={'Authorization': auth, 'User-Agent': 'Mozilla/5.0 perf-audit', **headers})
    try:
        with urllib.request.urlopen(req, timeout=120) as f:
            return json.loads(f.read().decode())
    except urllib.error.HTTPError as e:
        print('HTTP', e.code, e.read().decode()[:400])
        sys.exit(1)

for r in json.load(open(results, encoding='utf-8')):
    if not r.get('file') or r['id'] in have:
        continue
    name = os.path.basename(r['file'])
    path = os.path.join(os.path.dirname(os.path.abspath(results)), name)
    m = call(root, open(path, 'rb').read(), {'Content-Type': 'image/' + ('webp' if name.endswith('.webp') else 'avif'), 'Content-Disposition': 'attachment; filename="%s"' % name})
    title = r.get('title') or name.rsplit('.', 1)[0]
    call(root + '/' + str(m['id']), json.dumps({'alt_text': r.get('alt', ''), 'title': title}).encode(), {'Content-Type': 'application/json'})
    done.append({'old_id': r['id'], 'old_url': r['url'], 'new_id': m['id'], 'new_url': m['source_url'], 'before': r['before'], 'after': r['after']})
    json.dump(done, open(outp, 'w', encoding='utf-8'), indent=1)
    print(r['id'], '->', m['id'], m['source_url'].rsplit('/', 1)[1], m.get('mime_type'))
print('uploaded', len(done))
