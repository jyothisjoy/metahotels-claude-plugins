# usage: python optimize-images.py <attachments.json> <originals-dir> <optimized-dir>
# Downloads each attachment listed in attachments.json (from image-list.py: id, url, "max" long side, "fmt") and
# re-encodes it: AVIF q50 for backgrounds and slideshows, WebP q80 where WordPress must build crop sizes (image
# widgets, galleries, carousels; this host makes sub-sizes from WebP). Needs Pillow >= 11.3 (AVIF built in); run
# without -I. Writes <optimized-dir>/results.json with sizes after every file (so a stopped run resumes); files that
# do not shrink by at least 30% are skipped. Uploading and repointing Elementor are separate steps.
import json, os, sys, urllib.request
from PIL import Image, ImageOps

src, odir, ddir = sys.argv[1:4]
QUALITY = 50
os.makedirs(odir, exist_ok=True)
os.makedirs(ddir, exist_ok=True)
items = json.load(open(src, encoding='utf-8'))
# Optional 4th argument: results file name, so several processes can work on parts of the list in parallel.
rpath = os.path.join(ddir, sys.argv[4] if len(sys.argv) > 4 else 'results.json')
res = json.load(open(rpath, encoding='utf-8')) if os.path.exists(rpath) else []
done = {r['id'] for r in res}
# Gewan: the same base name exists in two upload folders or with two extensions; add the id to those outputs.
stems = [it['url'].rsplit('/', 1)[1].rsplit('.', 1)[0] for it in items]
clash = {s for s in stems if stems.count(s) > 1}
for it in items:
    if it['id'] in done:
        continue
    name = it.get('name') or it['url'].rsplit('/', 1)[1]
    if 'name' not in it and name.rsplit('.', 1)[0] in clash:
        name = '%d-%s' % (it['id'], name)
    op = os.path.join(odir, name)
    try:
        if not os.path.exists(op):
            req = urllib.request.Request(it['url'], headers={'User-Agent': 'Mozilla/5.0 perf-audit'})
            open(op, 'wb').write(urllib.request.urlopen(req, timeout=90).read())
        before = os.path.getsize(op)
        im = ImageOps.exif_transpose(Image.open(op))
        alpha = im.mode in ('RGBA', 'LA') or (im.mode == 'P' and 'transparency' in im.info)
        im = im.convert('RGBA' if alpha else 'RGB')
        cap = it.get('max', 1600)
        w, h = im.size
        if max(w, h) > cap:
            s = cap / max(w, h)
            im = im.resize((round(w * s), round(h * s)), Image.LANCZOS)
        base = name.rsplit('.', 1)[0]
        if it.get('fmt') == 'webp':
            out = os.path.join(ddir, base + '-opt.webp')
            im.save(out, 'WEBP', quality=80, method=6)
        else:
            out = os.path.join(ddir, base + '-opt.avif')
            im.save(out, 'AVIF', quality=QUALITY, speed=4)
        after = os.path.getsize(out)
    except Exception as e:  # noqa: BLE001
        print(str(it['id']).rjust(5), 'ERROR', str(e)[:80], name, flush=True)
        continue
    keep = after <= before * 0.7
    res.append({'id': it['id'], 'url': it['url'], 'alt': it.get('alt', ''), 'title': it.get('title', ''), 'fmt': it.get('fmt'), 'from': '%dx%d' % (w, h), 'to': '%dx%d' % im.size, 'before': before, 'after': after, 'file': out if keep else None})
    json.dump(res, open(rpath, 'w', encoding='utf-8'), indent=1)
    print(str(it['id']).rjust(5), ('%dx%d' % (w, h)).ljust(10), '->', ('%dx%d' % im.size).ljust(10), str(round(before / 1024)).rjust(4), 'KB ->', str(round(after / 1024)).rjust(4), 'KB', '' if keep else '(skipped: not 30% smaller)', name, flush=True)
kept = [r for r in res if r['file']]
print('total', round(sum(r['before'] for r in kept) / 1024), 'KB ->', round(sum(r['after'] for r in kept) / 1024), 'KB for', len(kept), 'of', len(res), 'files')
