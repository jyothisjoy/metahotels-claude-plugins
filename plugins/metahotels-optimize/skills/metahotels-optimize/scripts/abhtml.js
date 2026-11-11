// usage: node abhtml.js <label> <url> <rules.json|-> [runs] [--fast] [--desktop] [--shifts] [--shot=file.png] [--probe="js expr"] [--wait=ms]
// A/B an HTML change against the LIVE page before touching the site: fetches the document, applies the
// find/replace rules to it, serves the result through request interception, and measures like throttle.js
// (mobile, Slow 4G + 4x CPU, cold cache). Pass "-" as rules for the control run (same interception path, no edits),
// so control and variant are comparable. Also reports the LCP element and when booking/3p scripts started.
// rules.json: [{"find": "literal or regex source", "regex": false, "flags": "s", "replace": "..."}]; every rule must match.
// --fast = no network/CPU throttle (functional checks). --probe is evaluated in the page at the end.
// --block=regex aborts matching requests (what would the page cost without script X?). --cpu=N sets the CPU slowdown
// (overrides the default 4x; works with --fast).
// --shifts prints every layout shift >= 0.01 with the rects (x,y,w,h) of the elements that moved.
const puppeteer = require('puppeteer-core');
const fs = require('fs');
const args = process.argv.slice(2);
const opt = (n) => { const a = args.find((x) => x.startsWith('--' + n)); return a ? (a.includes('=') ? a.slice(a.indexOf('=') + 1) : true) : null; };
const [label, url, rulesFile, runsArg] = args.filter((a) => !a.startsWith('--'));
if (!url || !rulesFile) { console.error('usage: node abhtml.js <label> <url> <rules.json|-> [runs] [--fast] [--desktop] [--shot=f.png] [--probe=expr] [--wait=ms]'); process.exit(1); }
const runs = +(runsArg || 3);
const rules = rulesFile === '-' ? [] : JSON.parse(fs.readFileSync(rulesFile, 'utf8'));
const desktop = !!opt('desktop');
const BLOCK = opt('block') ? new RegExp(opt('block')) : null;
const UA = desktop
  ? 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36'
  : 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1';

// --vary: LiteSpeed Guest Mode serves a first copy that reloads itself after guest.vary.php sets _lscache_vary.
// Without the cookie the rules are applied to that guest copy and the reload measures the unmodified page. With
// --vary the cookie is fetched once, the normal copy is fetched with it, and each test browser gets it too.
let VARY = null;
async function getVary() {
  const u = new URL(url);
  const r = await fetch(u.origin + '/wp-content/plugins/litespeed-cache/guest.vary.php', { method: 'POST', headers: { 'user-agent': UA } });
  const m = /_lscache_vary=([^;]+)/.exec(r.headers.get('set-cookie') || '');
  if (!m) { console.error('--vary: no _lscache_vary cookie from guest.vary.php'); process.exit(2); }
  return { name: '_lscache_vary', value: m[1], domain: u.hostname, path: '/' };
}

async function buildHtml() {
  if (opt('vary')) VARY = await getVary();
  const hdr = { 'user-agent': UA };
  if (VARY) hdr.cookie = VARY.name + '=' + VARY.value;
  let html = await (await fetch(url, { headers: hdr })).text();
  for (const r of rules) {
    const before = html;
    html = r.regex ? html.replace(new RegExp(r.find, r.flags || ''), () => r.replace) : html.split(r.find).join(r.replace);
    if (html === before) { console.error('RULE DID NOT MATCH: ' + r.find.slice(0, 80)); process.exit(2); }
  }
  return html;
}

(async () => {
  const html = await buildHtml();
  const res = [];
  for (let i = 0; i < runs; i++) {
    const b = await puppeteer.launch({ executablePath: require('./checks/_lib').CHROME, headless: 'new' });
    const p = await b.newPage();
    await p.setViewport(desktop ? { width: 1440, height: 900 } : { width: 390, height: 844, isMobile: true, hasTouch: true, deviceScaleFactor: 3 });
    await p.setUserAgent(UA);
    const errors = [];
    p.on('pageerror', (e) => errors.push(String(e.message || e).slice(0, 140)));
    const c = await p.target().createCDPSession();
    await c.send('Network.enable');
    await c.send('Network.setCacheDisabled', { cacheDisabled: true });
    if (!opt('fast')) {
      await c.send('Network.emulateNetworkConditions', { offline: false, latency: 150, downloadThroughput: (1.6 * 1024 * 1024) / 8, uploadThroughput: (750 * 1024) / 8 });
      await c.send('Emulation.setCPUThrottlingRate', { rate: 4 });
    }
    if (opt('cpu')) await c.send('Emulation.setCPUThrottlingRate', { rate: +opt('cpu') });
    await p.setRequestInterception(true);
    let served = false;
    p.on('request', (rq) => {
      if (!served && rq.isNavigationRequest() && rq.frame() === p.mainFrame()) {
        served = true;
        rq.respond({ status: 200, contentType: 'text/html; charset=UTF-8', body: html });
      } else if (BLOCK && BLOCK.test(rq.url())) rq.abort();
      else rq.continue();
    });
    await p.evaluateOnNewDocument(() => {
      window.__lcp = { t: 0 };
      new PerformanceObserver((l) => {
        for (const e of l.getEntries()) {
          const el = e.element;
          window.__lcp = { t: e.startTime, size: e.size, url: (e.url || '').split('/').pop().slice(0, 50), el: el ? el.tagName + (el.id ? '#' + el.id : '') + '.' + String(el.className).slice(0, 40) : '' };
        }
      }).observe({ type: 'largest-contentful-paint', buffered: true });
      window.__long = [];
      new PerformanceObserver((l) => { for (const e of l.getEntries()) window.__long.push([e.startTime, e.duration]); }).observe({ type: 'longtask', buffered: true });
      window.__cls = 0;
      window.__shifts = [];
      const desc = (n) => { const e = n && (n.nodeType === 1 ? n : n.parentElement); if (!e) return '(gone)'; return e.tagName + (e.id ? '#' + e.id : '') + '.' + String(e.className && e.className.baseVal !== undefined ? e.className.baseVal : e.className).replace(/\s+/g, '.').slice(0, 60) + (e.getAttribute('data-mirai-component') ? '[mirai=' + e.getAttribute('data-mirai-component') + ']' : ''); };
      const rect = (r) => [r.x, r.y, r.width, r.height].map(Math.round).join(',');
      new PerformanceObserver((l) => {
        for (const e of l.getEntries()) {
          if (e.hadRecentInput) continue;
          window.__cls += e.value;
          window.__shifts.push({ t: Math.round(e.startTime), v: +e.value.toFixed(4), src: (e.sources || []).map((s) => desc(s.node) + ' ' + rect(s.previousRect) + ' -> ' + rect(s.currentRect)) });
        }
      }).observe({ type: 'layout-shift', buffered: true });
    });
    if (VARY) await p.setCookie(VARY);
    await p.goto(url, { waitUntil: 'load', timeout: 240000 });
    await new Promise((r) => setTimeout(r, +(opt('wait') || 3000)));
    const probe = opt('probe');
    const m = await p.evaluate((probe) => {
      const nav = performance.getEntriesByType('navigation')[0];
      const start = (re) => { const e = performance.getEntriesByType('resource').find((x) => re.test(x.name)); return e ? Math.round(e.startTime) : null; };
      let pr; try { pr = probe ? (0, eval)(probe) : undefined; } catch (e) { pr = 'ERR ' + e.message; }
      const fcpT = (performance.getEntriesByName('first-contentful-paint')[0] || {}).startTime || 0;
      return {
        tbt: Math.round(window.__long.filter((x) => x[0] >= fcpT).reduce((a, x) => a + Math.max(0, x[1] - 50), 0)), longest: Math.round(Math.max(0, ...window.__long.map((x) => x[1]))),
        fcp: Math.round((performance.getEntriesByName('first-contentful-paint')[0] || {}).startTime || 0),
        lcp: Math.round(window.__lcp.t), lcpEl: window.__lcp.el + ' ' + (window.__lcp.url || ''),
        dcl: Math.round(nav.domContentLoadedEventEnd), load: Math.round(nav.loadEventEnd), cls: +window.__cls.toFixed(4),
        mirai: start(/static\.mirai\.com\/core\/index\.js/), chat: start(/directchat-widget\.js/), probe: pr,
        shifts: window.__shifts.filter((x) => x.v >= 0.01),
      };
    }, probe);
    m.errors = errors;
    const shifts = m.shifts; delete m.shifts;
    if (opt('shifts')) for (const x of shifts) console.log('   shift', x.t + 'ms', x.v, '\n      ' + x.src.join('\n      '));
    if (opt('shot') && i === 0) await p.screenshot({ path: opt('shot') });
    res.push(m);
    console.log(label, i + 1, JSON.stringify(m));
    await b.close();
  }
  const med = (k) => res.map((r) => r[k]).sort((a, b) => a - b)[Math.floor(res.length / 2)];
  console.log(label, '| median FCP', med('fcp'), 'LCP', med('lcp'), 'DCL', med('dcl'), 'load', med('load'), 'CLS', med('cls'), 'TBT', med('tbt'), 'miraiStart', med('mirai'));
})();
