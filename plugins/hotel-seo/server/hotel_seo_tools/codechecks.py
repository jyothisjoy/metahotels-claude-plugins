"""Checks that run in code over EVERY page of a hotel (full coverage), for the agents to cite instead of sampling:
  - content_quality.py on each page's visible text (filler, AI patterns, density, repetition, overall 0-100)
  - word count against the hotel page-type floors (hotel-addendum.md)
  - metadata_template.py on all title/description pairs of the hotel (templated metadata, shared CTA phrases)
Writes <out_dir>/content-scan.json; seo-content and seo-geo read it.
"""
import json
import re
import tempfile
from pathlib import Path

from . import group as grp, paths, seo_check
from .audit import page_type

# Topical-coverage floors for hotel page types (not ranking rules; see hotel-addendum.md)
FLOORS = {'home': 500, 'rooms': 300, 'offers': 300, 'contact': 150, 'location': 500, 'dining': 300, 'spa': 300,
          'meetings': 300, 'blog': 800, 'other': 250}


def _path(url):
    from urllib.parse import urlparse
    return (urlparse(url).path or '/').rstrip('/') + '/'


def _type(url, host):
    p = url.lower()
    if re.search(r'/(location|getting-here|directions|area|neighbourhood|neighborhood|surroundings|nearby)', p):
        return 'location'
    if re.search(r'/(dining|restaurant|bar|cafe)', p):
        return 'dining'
    if re.search(r'/(spa|wellness)', p):
        return 'spa'
    if re.search(r'/(meeting|event|wedding|conference)', p):
        return 'meetings'
    if re.search(r'/(blog|news|article)', p):
        return 'blog'
    t = page_type(url, host)
    return t if t in FLOORS else 'other'


def content_scan(crawl_dir, out_dir, group_dir='', slug='', progress=None):
    cd = paths.resolve(crawl_dir)
    texts = json.loads((cd / 'site_text.json').read_text(encoding='utf-8'))
    fj = json.loads((cd / 'findings.json').read_text(encoding='utf-8'))
    pages = fj.get('pages', {})
    reg = grp.load(group_dir) if group_dir else None
    urls = [u for u in texts if not reg or not slug or grp.hotel_for(u, reg) == slug]
    host = re.sub(r'^www\.', '', re.sub(r'^https?://', '', fj.get('site', '')).split('/')[0])
    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, u in enumerate(urls):
            text = texts[u]
            p = pages.get(u, {})
            words = p.get('content_words') or len(text.split())
            t = _type(u, host)
            if reg and any(_path(u) == pre for h in reg.get('hotels', []) for pre in h.get('paths', [])):
                t = 'home'                       # a group hotel's main page is that hotel's homepage
            row = {'url': u, 'page_type': t, 'content_words': words, 'floor': FLOORS[t],
                   'below_floor': words < FLOORS[t], 'title': p.get('title', ''),
                   'meta_description': p.get('meta_description', '')}
            if len(text.split()) >= 60:
                f = Path(tmp) / f'p{i}.txt'
                f.write_text(text, encoding='utf-8')
                r = seo_check.run('content_quality.py', [str(f), '--json', '--threshold', '0'], timeout_s=60)
                d = r.get('json') or {}
                row.update({k: d.get(k) for k in ('overall_quality', 'filler_score', 'ai_pattern_score',
                                                   'information_density', 'repetition_score', 'flags') if k in d})
            rows.append(row)
        pairs = [{'url': r['url'], 'title': r['title'], 'description': r['meta_description']} for r in rows
                 if r['title'] or r['meta_description']]
        pf = Path(tmp) / 'pairs.json'
        pf.write_text(json.dumps(pairs), encoding='utf-8')
        mt = seo_check.run('metadata_template.py', ['--pairs-file', str(pf), '--json'], timeout_s=120)
    meta = mt.get('json') or {}
    out = {'scope': f'hotel:{slug}' if slug else 'site', 'pages': len(rows),
           'below_floor': [{'url': r['url'], 'page_type': r['page_type'], 'words': r['content_words'],
                            'floor': r['floor']} for r in rows if r['below_floor']],
           'low_quality': [{'url': r['url'], 'overall_quality': r.get('overall_quality'), 'flags': r.get('flags')}
                           for r in rows if (r.get('overall_quality') is not None and r['overall_quality'] < 60)],
           'metadata_template': {k: meta.get(k) for k in ('site_risk', 'templated_ratio', 'shared_cta_phrases')
                                 if k in meta},
           'metadata_pages_flagged': [p for p in (meta.get('pages') or []) if p.get('templated') or
                                      p.get('severity') in ('high', 'medium')],
           'rows': rows,
           'source': 'codechecks.content_scan: content_quality.py + metadata_template.py (claude-seo, MIT) on every page'}
    od = paths.resolve(out_dir)
    od.mkdir(parents=True, exist_ok=True)
    (od / 'content-scan.json').write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding='utf-8')
    return {'file': str(od / 'content-scan.json'), 'pages': len(rows), 'below_floor': len(out['below_floor']),
            'low_quality': len(out['low_quality']), 'metadata_template': out['metadata_template'],
            'metadata_pages_flagged': len(out['metadata_pages_flagged'])}
