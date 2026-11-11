// usage: node mirai-dup.js <url> <desktop|mobile> <variant> [runs]
// MEASUREMENT ONLY. Nothing on the site is changed: the page HTML is modified inside this headless browser to
// see what the duplicate Mirai components cost.
// variants: control | one-bar (drop the second, identical .be-mobile block) | no-clone (also keep Mirai out of
//           Elementor's hidden sticky clone) | single (also drop the finder that is hidden on this viewport)
const puppeteer = require('puppeteer-core');
const [url, prof, variant, runsArg] = process.argv.slice(2);
const mobile = prof === 'mobile';
const runs = +(runsArg || 3);
const UA = mobile ? 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1'
  : 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36';
const BAR = /<div class="be-mobile">\s*<p>\s*BEST RATES GUARANTEED\s*<\/p>\s*<div data-mirai-component="finder" data-width="fit-parent"><\/div>\s*<\/div>/g;

function transform(html) {
  if (variant === 'control') return html;
  const bars = html.match(BAR) || [];
  if (bars.length !== 2) throw new Error('expected 2 .be-mobile blocks, found ' + bars.length);
  let n = 0;
  html = html.replace(BAR, (m) => (++n === 2 ? '' : m)); // keep the first (it sits next to the Mirai loader)
  if (variant === 'one-bar') return html;
  const strip = "<script>window.addEventListener('load',function(){document.querySelectorAll('.elementor-sticky__spacer [data-mirai-component]').forEach(function(e){e.removeAttribute('data-mirai-component')})});</script>";
  html = html.replace(/<head[^>]*>/, (m) => m + strip);
  if (variant === 'no-clone') return html;
  if (mobile) {
    // top bar is display:none on mobile: drop its finder
    html = html.replace('<div data-mirai-component="finder"></div>', '');
  } else {
    // the mobile bar is display:none on desktop: drop the remaining one
    html = html.replace(BAR, '');
  }
  return html;
}

(async () => {
  const base = await (await fetch(url, { headers: { 'user-agent': UA } })).text();
  const html = transform(base);
  const out = [];
  for (let i = 0; i < runs; i++) {
    const b = await puppeteer.launch({ executablePath: require('./_lib').CHROME, headless: 'new' });
    const p = await b.newPage();
    await p.setViewport(mobile ? { width: 390, height: 844, isMobile: true, hasTouch: true, deviceScaleFactor: 3 } : { width: 1440, height: 900 });
    await p.setUserAgent(UA);
    const c = await p.target().createCDPSession();
    await c.send('Network.enable');
    await c.send('Network.setCacheDisabled', { cacheDisabled: true });
    if (mobile) await c.send('Emulation.setCPUThrottlingRate', { rate: 4 });
    const req = {};
    c.on('Network.requestWillBeSent', (e) => { req[e.requestId] = { url: e.request.url, method: e.request.method, bytes: 0 }; });
    c.on('Network.loadingFinished', (e) => { if (req[e.requestId]) req[e.requestId].bytes = e.encodedDataLength; });
    await p.setRequestInterception(true);
    let served = false;
    p.on('request', (rq) => { if (!served && rq.isNavigationRequest() && rq.frame() === p.mainFrame()) { served = true; rq.respond({ status: 200, contentType: 'text/html; charset=UTF-8', body: html }); } else rq.continue(); });
    const errors = [];
    p.on('pageerror', (e) => errors.push(String(e.message).slice(0, 100)));
    await p.evaluateOnNewDocument(() => {
      window.__long = [];
      new PerformanceObserver((l) => { for (const e of l.getEntries()) window.__long.push([e.startTime, e.duration]); }).observe({ type: 'longtask', buffered: true });
      window.__ready = null;
      const iv = setInterval(() => {
        const f = [...document.querySelectorAll('[data-mirai-component="finder"]')].find((e) => { const r = e.getBoundingClientRect(); return r.width > 50 && r.height > 20 && !e.closest('.elementor-sticky__spacer') && e.textContent.trim().length > 5; });
        if (f) { window.__ready = performance.now(); clearInterval(iv); }
      }, 50);
    });
    await p.goto(url, { waitUntil: 'load', timeout: 120000 });
    await new Promise((r) => setTimeout(r, 14000));
    const m = await p.evaluate(() => {
      const nav = performance.getEntriesByType('navigation')[0];
      const load = nav.loadEventEnd;
      const comps = [...document.querySelectorAll('[data-mirai-component]')].filter((e) => e.childElementCount > 0);
      const where = (e) => (e.closest('.elementor-sticky__spacer') ? 'sticky-clone' : e.closest('.be-mobile') ? 'mobile-bar' : e.closest('header') ? 'header' : 'other');
      const vis = (e) => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0 && getComputedStyle(e).visibility !== 'hidden' && !e.closest('.elementor-sticky__spacer'); };
      const list = {};
      for (const e of comps) { const k = e.getAttribute('data-mirai-component') + '@' + where(e) + (vis(e) ? '' : '(hidden)'); list[k] = (list[k] || 0) + 1; }
      return {
        load: Math.round(load), finderReady: window.__ready ? Math.round(window.__ready) : null,
        blockingAfterLoad: Math.round(window.__long.filter((x) => x[0] >= load).reduce((a, x) => a + Math.max(0, x[1] - 50), 0)),
        longAfterLoad: Math.round(window.__long.filter((x) => x[0] >= load).reduce((a, x) => a + x[1], 0)),
        domNodes: document.querySelectorAll('*').length, mounted: list,
      };
    });
    const R = Object.values(req);
    const mirai = R.filter((r) => /mirai\.com/.test(r.url));
    const by = {};
    for (const r of mirai) { if (r.method === 'OPTIONS') { by.preflight = (by.preflight || 0) + 1; continue; } const k = r.url.replace(/^https:\/\//, '').split('?')[0].replace(/\/\d{6}\.json$/, '/MMYYYY.json').replace(/\/\d{6,}/g, '/ID'); by[k] = (by[k] || 0) + 1; }
    m.miraiRequests = mirai.length; m.miraiKB = Math.round(mirai.reduce((a, r) => a + r.bytes, 0) / 1024);
    m.api = Object.fromEntries(Object.entries(by).filter(([k, v]) => v > 1 || /getCurrencyInfo|index-price/.test(k)).sort((a, b) => b[1] - a[1]).slice(0, 9));
    m.totalRequests = R.length; m.errors = errors;
    out.push(m);
    await b.close();
  }
  const med = (k) => out.map((r) => r[k]).sort((a, b) => a - b)[Math.floor(out.length / 2)];
  console.log(prof, variant, JSON.stringify({ mounted: out[0].mounted, api: out[0].api, errors: out[0].errors }));
  console.log(prof, variant, 'median of ' + runs + ': miraiRequests', med('miraiRequests'), 'miraiKB', med('miraiKB'), 'totalRequests', med('totalRequests'), 'load', med('load'), 'finderReady', med('finderReady'), 'blockingAfterLoad', med('blockingAfterLoad'), 'longTasksAfterLoad', med('longAfterLoad'), 'domNodes', med('domNodes'));
})();
