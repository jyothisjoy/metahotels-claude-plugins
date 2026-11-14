"""Alt text for every image of a hotel that has none: a worklist Claude fills after looking at each image.

  worklist(group_dir, slug)      every image without alt on the hotel's pages (crawl images_missing_alt.csv), one row
                                 per underlying image (sizes, -scaled and .webp copies of one file are one row), each
                                 downloaded so it can be looked at, with the pages it is on (title, H1). Writes
                                 <hotel dir>/alt-text/alt-text-<date>.json. Nothing is written to the site.
  batch(file, size)              the next rows still without alt, with their local image files to Read
  fill(file, alts)               saves {row id: alt} (or {"decorative": true} for a spacer / divider / icon)
  check(file)                    lints every alt (one sentence, at most 125 characters, no "image of", no file names,
                                 prices or numbers, the hotel name, no two images alike) and, when clean, writes one
                                 alt_text action per image into the audit report's "Images without alt text" finding,
                                 so /hotel-seo execute applies them in its alt-text batch.

Why a worklist (Nov 2026 run): the agent wrote alt only for images it could tie to a named room or restaurant and left
the rest to the agency. Describing what a photo shows is not an unverified fact: every image gets its own alt, written
after viewing it.
"""
import csv
import json
import re
from datetime import date
from urllib.parse import urlparse

from . import group as grp, paths
from .copylint import ALT_GENERIC_START, ALT_MAX_CHARS

FINDING = 'core-images-missing-alt'
RULES = [
    'Open each image (Read its "file") before writing; never write alt from the file name or the page alone.',
    'One plain sentence, at most 125 characters: what is in the photo + the room, outlet or place when the page shows '
    'which one it is + the hotel name (short form is fine).',
    'Describe only what is visible. No claims the photo does not show (sizes, "luxury", "best", sea view when there '
    'is no sea), no prices or offers, no numbers, no keyword lists, never "image of" / "photo of".',
    'Every image gets its own alt: two different photos never share one.',
    'Logos: "<Hotel name> logo". Text in the image (a banner, a menu): say what it says, briefly.',
    'Only a pure spacer, divider, background texture or icon next to its own text label may be decorative: '
    '{"decorative": true} (it keeps alt="" so screen readers skip it).',
]
FILE_NAME = re.compile(r'\b(?:img|dsc|dji|pxl|screenshot)[_-]?\d{2,}|\.(?:jpe?g|png|webp|gif|avif|svg)\b|\w+_\w+_\w+',
                       re.I)
PRICE = re.compile(r'(?:AED|USD|EUR|SAR|EGP|\$|€)\s?\d|\d\s?(?:AED|USD|EUR|SAR|EGP)\b|\d+\s?%|\b(?:discount|offer|deal)s?\b',
                   re.I)
DIGITS = re.compile(r'\d')


def image_key(src):
    """One key for every copy of one image: query, -1024x683, -scaled, -e1690000000 and .webp / .avif copies made by
    the cache plugin are the same file."""
    p = urlparse(src or '').path.lower()
    p = re.sub(r'\.(?:webp|avif)$', '', p) if re.search(r'\.(?:jpe?g|png|gif)\.(?:webp|avif)$', p) else p
    p = re.sub(r'-\d+x\d+(?=\.\w+$)', '', p)
    p = re.sub(r'-(?:scaled|rotated|e\d{10,})(?=\.\w+$)', '', p)
    return p


def _norm_alt(a):
    return re.sub(r'[^\w]+', ' ', str(a or '').lower()).strip()


def _latest_crawl(group_dir):
    crawls = sorted(p for p in paths.resolve(group_dir).glob('crawl-*') if (p / 'images_missing_alt.csv').exists())
    if not crawls:
        raise FileNotFoundError('no crawl with images_missing_alt.csv: crawl the site first')
    return crawls[-1]


def worklist(group_dir, slug, crawl_dir='', download=True):
    reg = grp.load(group_dir)
    hotel = next((h for h in reg['hotels'] if h['slug'] == slug), None)
    if not hotel:
        raise LookupError(f'no hotel {slug} in {group_dir}')
    hdir = grp.hotel_dir(group_dir, slug, reg)
    crawl = paths.resolve(crawl_dir) if crawl_dir else _latest_crawl(group_dir)
    with open(crawl / 'images_missing_alt.csv', encoding='utf-8-sig', newline='') as fh:
        rows = [r for r in csv.DictReader(fh) if grp.is_single(reg) or grp.hotel_for(r['page_url'], reg) == slug]
    pages = {}
    fj = crawl / 'findings.json'
    if fj.exists():
        pages = json.loads(fj.read_text(encoding='utf-8')).get('pages', {})
    out_dir = hdir / 'alt-text'
    f = out_dir / f'alt-text-{date.today().isoformat()}.json'
    old = {}
    if f.exists():       # a second call the same day keeps the alt already written
        old = {r['key']: r for r in json.loads(f.read_text(encoding='utf-8')).get('images', [])}
    groups = {}
    for r in rows:
        src = r['image_src'].strip()
        if not src or src.startswith('data:'):
            continue
        g = groups.setdefault(image_key(src), {'srcs': [], 'pages': []})
        if src not in g['srcs']:
            g['srcs'].append(src)
        if r['page_url'] not in g['pages']:
            g['pages'].append(r['page_url'])
    images = []
    for n, (key, g) in enumerate(sorted(groups.items(), key=lambda kv: (-len(kv[1]['pages']), kv[0])), 1):
        ctx = []
        for u in g['pages'][:4]:
            p = pages.get(u) or {}
            ctx.append({'page': u, 'title': p.get('title', ''), 'h1': (p.get('h1') or [''])[0] if p.get('h1') else ''})
        prev = old.get(key, {})
        images.append({'id': f'I{n}', 'key': key, 'image': g['srcs'][0], 'variants': g['srcs'][1:],
                       'pages': g['pages'], 'context': ctx, 'file': prev.get('file', ''),
                       'file_name_hint': re.sub(r'[-_]+', ' ', key.rsplit('/', 1)[-1].rsplit('.', 1)[0]),
                       'alt': prev.get('alt', ''), 'decorative': bool(prev.get('decorative'))})
    failed = {}
    if download:
        from .server import download_images
        todo = [i['image'] for i in images if not i['file']]
        for k in range(0, len(todo), 40):
            res = download_images(todo[k:k + 40], str(out_dir / 'images'))
            failed.update(res['failed'])
            for i in images:
                if i['image'] in res['saved']:
                    i['file'] = res['saved'][i['image']]
    for i in images:
        if not i['file'] and i['image'] in failed:
            i['download_error'] = failed[i['image']]
    doc = {'hotel': hotel['name'], 'slug': slug, 'group_dir': str(group_dir), 'site': reg['group']['site'],
           'crawl': str(crawl),
           'created': date.today().isoformat(), 'max_chars': ALT_MAX_CHARS, 'rules': RULES, 'images': images}
    out_dir.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding='utf-8')
    return {'file': str(f), 'images': len(images), 'image_tags': len(rows), 'downloaded': sum(1 for i in images if i['file']),
            'download_failed': len(failed), 'remaining': sum(1 for i in images if not _done(i)),
            'next': f'alt_text_batch("{f}") gives the next images to look at; write each alt and save them with '
                    'alt_text_fill; repeat until remaining is 0, then alt_text_check.'}


def _done(i):
    return bool(str(i.get('alt') or '').strip()) or bool(i.get('decorative'))


def _load(file):
    f = paths.resolve(file)
    return f, json.loads(f.read_text(encoding='utf-8'))


def batch(file, size=20):
    """The next rows without alt: id, local image file (Read it), the pages it is on, the file-name hint."""
    _, d = _load(file)
    todo = [i for i in d['images'] if not _done(i)]
    rows = [{k: i.get(k) for k in ('id', 'file', 'image', 'context', 'file_name_hint', 'download_error')}
            for i in todo[:max(1, min(int(size), 60))]]
    return {'hotel': d['hotel'], 'rules': d['rules'], 'remaining': len(todo), 'images': rows,
            'next': ('Read each "file", write one alt per image by the rules, then alt_text_fill(file, {id: alt}). '
                     'An image whose download failed: open its "image" URL with Claude in Chrome to look at it.')
            if rows else 'Every image has its alt: alt_text_check(file).'}


def fill(file, alts):
    """Save alt text: {"I1": "Twin room with ... at Example Hotel", "I7": {"decorative": true}}."""
    f, d = _load(file)
    by = {i['id']: i for i in d['images']}
    saved, unknown = [], []
    for k, v in (alts or {}).items():
        if k not in by:
            unknown.append(k)
            continue
        if isinstance(v, dict):
            by[k]['decorative'] = bool(v.get('decorative'))
            by[k]['alt'] = '' if by[k]['decorative'] else str(v.get('alt') or '').strip()
        else:
            by[k]['alt'], by[k]['decorative'] = str(v or '').strip(), False
        saved.append(k)
    f.write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding='utf-8')
    return {'saved': len(saved), 'unknown_ids': unknown, 'remaining': sum(1 for i in d['images'] if not _done(i))}


def lint(alt, hotel_name=''):
    """(problems, warnings) for one alt text."""
    a = str(alt or '').strip()
    probs, warns = [], []
    if not a:
        return ['no alt text'], []
    if len(a) > ALT_MAX_CHARS:
        probs.append(f'{len(a)} characters (at most {ALT_MAX_CHARS})')
    if ALT_GENERIC_START.search(a):
        probs.append(f'starts "{ALT_GENERIC_START.search(a).group(0).strip()}"')
    if FILE_NAME.search(a):
        probs.append(f'looks like a file name ("{FILE_NAME.search(a).group(0)}")')
    if PRICE.search(a):
        probs.append('mentions a price, discount or offer')
    if DIGITS.search(a):
        warns.append('has a number: keep it only if the photo shows it (a sign, a room number on the door)')
    if a.count(',') >= 4:
        probs.append('reads like a keyword list')
    short = re.sub(r'\b(?:hotel|hotels|apartments?|resort|suites?|&|and|the)\b', ' ', hotel_name.lower())
    words = [w for w in re.findall(r'\w{3,}', short)]
    if words and not any(w in a.lower() for w in words):
        warns.append(f'without the hotel name ({hotel_name})')
    return probs, warns


def check(file, apply=True):
    """Lint every alt; when nothing blocks, write the alt_text actions into the latest audit report."""
    f, d = _load(file)
    problems, warnings, seen = [], [], {}
    for i in d['images']:
        if i.get('decorative'):
            continue
        p, w = lint(i.get('alt'), d['hotel'])
        problems += [f"{i['id']} ({i['image'].rsplit('/', 1)[-1]}): {x}" for x in p]
        warnings += [f"{i['id']}: {x}" for x in w]
        k = _norm_alt(i.get('alt'))
        if k and k in seen:
            problems.append(f"{i['id']}: same alt as {seen[k]} (each image needs its own)")
        elif k:
            seen[k] = i['id']
    remaining = [i['id'] for i in d['images'] if not _done(i)]
    out = {'images': len(d['images']), 'remaining': len(remaining), 'problems': problems, 'warnings': warnings,
           'decorative': sum(1 for i in d['images'] if i.get('decorative'))}
    if problems or not apply:
        out['next'] = 'Fix each problem with alt_text_fill and check again.' if problems else ''
        return out
    out.update(_apply(d))
    return out


def _apply(d):
    """alt_text actions (one per image, every copy of it) into the hotel's latest audit-report.json."""
    hdir = grp.hotel_dir(d['group_dir'], d['slug'], grp.load(d['group_dir']))
    runs = sorted(p for p in hdir.glob('audit-*') if (p / 'audit-report.json').exists())
    if not runs:
        return {'applied': False, 'reason': 'no audit-report.json for this hotel: build the audit report first, then '
                                            'alt_text_check again'}
    rf = runs[-1] / 'audit-report.json'
    rep = json.loads(rf.read_text(encoding='utf-8'))
    sec = next((s for s in rep.get('sections', []) if s.get('finding_id') == FINDING), None)
    if not sec:
        return {'applied': False, 'reason': f'the audit report has no "{FINDING}" finding'}
    acts, checks, deco = [], [], []
    for i in d['images']:
        if i.get('decorative'):
            deco.append(i)
            continue
        if not str(i.get('alt') or '').strip():
            continue
        acts.append({'type': 'alt_text', 'image': i['image'], 'alt': i['alt'].strip(), 'variants': i.get('variants', []),
                     'pages': i['pages']})
        checks += [{'type': 'alt_present', 'url': u, 'image': i['image'].rsplit('/', 1)[-1]} for u in i['pages'][:5]]
    keep = [a for a in sec.get('actions') or [] if a.get('type') != 'alt_text']
    sec['actions'] = keep + acts
    sec['checks'] = [c for c in sec.get('checks') or [] if c.get('type') != 'alt_present'] + checks
    sec['blocks'] = [b for b in sec.get('blocks', []) if not (isinstance(b, dict) and b.get('alt_table'))]
    sec['blocks'].append({'alt_table': True, 'table': {'columns': ['Image', 'Alt text', 'Pages'], 'rows': [
        [f"`{a['image'].rsplit('/', 1)[-1]}`", a['alt'], str(len(a['pages']))] for a in acts]}})
    if deco:
        sec['blocks'].append({'alt_table': True, 'note': f'{len(deco)} decorative image(s) keep alt="" on purpose: '
                              + ', '.join(f"`{i['image'].rsplit('/', 1)[-1]}`" for i in deco[:30])})
    rf.write_text(json.dumps(rep, indent=1, ensure_ascii=False), encoding='utf-8')
    return {'applied': True, 'report': str(rf), 'actions': len(acts),
            'next': 'Run /hotel-seo execute (execute_plan): the alt-text batch applies them (50 images per call).'}
