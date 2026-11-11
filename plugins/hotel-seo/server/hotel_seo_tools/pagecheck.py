"""Render pages in headless Chromium, desktop and mobile, and record what guests and Google see.

Per page and viewport: tags that actually fire (GTM, GA4, Google Ads, Meta pixel) from network
requests, rendered title / meta / H1s / canonical / JSON-LD types, pop-ups or overlays covering
the screen, consent banner, console errors, and a screenshot. Raw-HTML crawls miss tags and
content injected at runtime; this doesn't.
"""
import json
import re
from urllib.parse import parse_qs, urlparse

from . import paths

MOBILE = {'viewport': {'width': 390, 'height': 844}, 'device_scale_factor': 2, 'is_mobile': True,
          'has_touch': True,
          'user_agent': ('Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 '
                         '(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1')}
DESKTOP = {'viewport': {'width': 1366, 'height': 900},
           'user_agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                          '(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36')}  # 'HeadlessChrome' is often served no tags

OVERLAY_JS = """() => {
  const vw = innerWidth, vh = innerHeight, out = [];
  for (const el of document.querySelectorAll('body *')) {
    const cs = getComputedStyle(el);
    if (!['fixed', 'sticky'].includes(cs.position) || cs.display === 'none' || cs.visibility === 'hidden'
        || parseFloat(cs.opacity) < 0.1) continue;
    const r = el.getBoundingClientRect();
    const cover = Math.max(0, Math.min(r.right, vw) - Math.max(r.left, 0)) *
                  Math.max(0, Math.min(r.bottom, vh) - Math.max(r.top, 0)) / (vw * vh);
    const text = (el.innerText || '').replace(/\\s+/g, ' ').trim();
    if (cover > 0.25 && text) out.push({cover: Math.round(cover * 100), text: text.slice(0, 160)});
  }
  return out.slice(0, 5);
}"""

PAGE_JS = """() => ({
  title: document.title,
  meta: (document.querySelector('meta[name="description" i]') || {}).content || '',
  canonical: (document.querySelector('link[rel="canonical"]') || {}).href || '',
  h1: [...document.querySelectorAll('h1')].filter(h => h.offsetParent !== null)
        .map(h => h.innerText.replace(/\\s+/g, ' ').trim()),
  h1_hidden: [...document.querySelectorAll('h1')].filter(h => h.offsetParent === null).length,
  jsonld: [...document.querySelectorAll('script[type="application/ld+json"]')].map(s => s.textContent),
  consent: !!document.querySelector('[id*="cookie" i], [class*="cookie" i], [id*="consent" i], [class*="consent" i]'),
  consent_mode: (window.dataLayer || []).filter(e => e && e[0] === 'consent')
        .map(e => ({command: e[1], params: e[2] || {}})).slice(0, 6),
  history_added: history.length - (window.__hsStart || history.length),
  push_states: (window.__hsPush || []).slice(0, 10),
})"""

# Back-button hijacking (Google spam policy, enforced since 15 Jun 2026): scripts that add history entries
# so Back doesn't leave the site. We never click, so any pushState during load and scrolling is the page's own.
HISTORY_JS = """(() => {
  window.__hsPush = []; window.__hsStart = history.length;
  const wrap = name => { const orig = history[name].bind(history);
    history[name] = function (state, title, url) {
      if (name === 'pushState') window.__hsPush.push(String(url || location.href));
      return orig(state, title, url); }; };
  wrap('pushState');
})();"""


def _tags(requests_seen):
    tags = {'gtm': set(), 'ga4': set(), 'google_ads': set(), 'meta_pixel': False, 'ga4_hits': 0}
    for u in requests_seen:
        p = urlparse(u)
        q = parse_qs(p.query)
        if 'googletagmanager.com' in p.netloc and p.path.endswith('/gtm.js'):
            tags['gtm'].update(q.get('id', []))
        if 'googletagmanager.com' in p.netloc and p.path.endswith('/gtag/js'):
            for i in q.get('id', []):
                (tags['ga4'] if i.startswith('G-') else tags['google_ads']).add(i)
        if re.search(r'google-analytics\.com|analytics\.google\.com', p.netloc) and '/collect' in p.path:
            tags['ga4_hits'] += 1
            tags['ga4'].update(q.get('tid', []))
        if 'facebook.com' in p.netloc and p.path.startswith('/tr'):
            tags['meta_pixel'] = True
    return {k: sorted(v) if isinstance(v, set) else v for k, v in tags.items()}


def _consent_states(requests_seen):
    out = set()
    for u in requests_seen:
        p = urlparse(u)
        if re.search(r'google-analytics\.com|analytics\.google\.com|googletagmanager\.com', p.netloc):
            out.update(parse_qs(p.query).get('gcs', []))
    return sorted(out)


def _jsonld_types(blocks):
    types = []
    for raw in blocks:
        try:
            data = json.loads(raw)
        except ValueError:
            types.append('INVALID-JSON')
            continue
        nodes = data.get('@graph', [data]) if isinstance(data, dict) else data if isinstance(data, list) else []
        for n in nodes:
            if isinstance(n, dict):
                t = n.get('@type')
                types.extend(t if isinstance(t, list) else [t] if t else [])
    return types


def inspect(urls, out_dir, viewports=('desktop', 'mobile'), wait_ms=4000):
    from playwright.sync_api import sync_playwright
    out_dir = paths.resolve(out_dir)
    shots = out_dir / 'screenshots'
    shots.mkdir(parents=True, exist_ok=True)
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for vp in viewports:
            ctx = browser.new_context(**(MOBILE if vp == 'mobile' else DESKTOP))
            ctx.add_init_script(HISTORY_JS)
            for url in urls:
                page = ctx.new_page()
                seen, errors = [], []
                page.on('request', lambda req, seen=seen: seen.append(req.url))
                page.on('console', lambda m, errors=errors: errors.append(m.text) if m.type == 'error' else None)
                row = {'url': url, 'viewport': vp}
                try:
                    resp = page.goto(url, wait_until='domcontentloaded', timeout=45000)
                    row['status'] = resp.status if resp else 0
                    try:
                        page.wait_for_load_state('networkidle', timeout=15000)
                    except Exception:  # noqa: BLE001 - busy pages never go idle; carry on
                        pass
                    # Many cache plugins delay scripts (tags included) until the visitor
                    # interacts, so act like one: move, scroll down and back up.
                    page.mouse.move(200, 300)
                    page.mouse.move(400, 500)
                    page.mouse.wheel(0, 1200)
                    page.wait_for_timeout(800)
                    page.mouse.wheel(0, -1200)
                    page.keyboard.press('Tab')
                    page.wait_for_timeout(wait_ms)
                    info = page.evaluate(PAGE_JS)
                    row.update({
                        'final_url': page.url,
                        'title': info['title'], 'meta_description': info['meta'], 'canonical': info['canonical'],
                        'h1_visible': info['h1'], 'h1_hidden_count': info['h1_hidden'],
                        'jsonld_types': _jsonld_types(info['jsonld']),
                        'consent_banner': info['consent'],
                        # gtag('consent', 'default' / 'update', ...) calls, and the consent state GA4 hits
                        # carried (gcs G1xx: G100 = all denied, G111 = granted). No consent call at all on an
                        # EEA-facing site = no Consent Mode v2.
                        'consent_mode': info['consent_mode'],
                        'ga4_consent_states': _consent_states(seen),
                        # entries added to the history without a click: the back-button hijacking signal
                        'history_entries_added': max(0, info['history_added']),
                        'push_states_without_click': info['push_states'],
                        'overlays': page.evaluate(OVERLAY_JS),
                        'tags_fired': _tags(seen),
                        'console_errors': len(errors),
                    })
                    name = re.sub(r'[^a-z0-9]+', '-', urlparse(url).path.lower()).strip('-') or 'home'
                    shot = shots / f'{name}-{vp}.png'
                    page.screenshot(path=str(shot), full_page=False)
                    row['screenshot'] = str(shot)
                except Exception as e:  # noqa: BLE001
                    row['error'] = str(e)[:300]
                page.close()
                results.append(row)
            ctx.close()
        browser.close()
    (out_dir / 'inspect.json').write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding='utf-8')
    return {'pages': len(urls), 'file': str(out_dir / 'inspect.json'), 'results': results}
