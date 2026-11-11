// usage: node measure.js <label> <url> [runs]
// Logged-out, cold-cache homepage measurement (desktop + mobile). Writes runs/<host>/<label>/*.json.
// Pipe stdout into summarize.py for a one-line-per-run summary.
// Logged-out, cold-cache measurement of a page on desktop + mobile profiles.
const puppeteer = require('puppeteer-core');
const fs = require('fs');
const path = require('path');

const label = process.argv[2] || 'run';
const url = process.argv[3];
if (!url) { console.error('usage: node measure.js <label> <url> [runs]'); process.exit(1); }
const runs = +(process.argv[4] || 1);
const outDir = path.join(process.env.PERF_RUNS || path.resolve('runs'), new URL(url).host, label);
fs.mkdirSync(outDir, { recursive: true });

const profiles = {
  desktop: { viewport: { width: 1440, height: 900 }, ua: null },
  mobile: {
    viewport: { width: 390, height: 844, isMobile: true, hasTouch: true, deviceScaleFactor: 3 },
    ua: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
  },
};

function typeOf(r) {
  const u = r.url.split('?')[0];
  if (r.type === 'Font' || /\.(woff2?|ttf|otf|eot)$/i.test(u)) return 'font';
  if (r.type === 'Stylesheet' || /\.css$/i.test(u)) return 'css';
  if (r.type === 'Script' || /\.m?js$/i.test(u)) return 'js';
  if (r.type === 'Image' || /\.(png|jpe?g|webp|gif|svg|avif|ico)$/i.test(u)) return 'img';
  if (r.type === 'Document') return 'doc';
  if (r.type === 'XHR' || r.type === 'Fetch') return 'xhr';
  return (r.type || 'other').toLowerCase();
}

async function measure(profileName, run) {
  const p = profiles[profileName];
  const browser = await puppeteer.launch({
    executablePath: require('./checks/_lib').CHROME,
    headless: 'new',
    args: ['--no-first-run', '--disable-extensions'],
  });
  const page = await browser.newPage();
  await page.setViewport(p.viewport);
  if (p.ua) await page.setUserAgent(p.ua);
  const cdp = await page.target().createCDPSession();
  await cdp.send('Network.enable');
  await cdp.send('Network.setCacheDisabled', { cacheDisabled: true });
  await cdp.send('Network.clearBrowserCache');

  const reqs = new Map();
  cdp.on('Network.requestWillBeSent', (e) => {
    reqs.set(e.requestId, { url: e.request.url, method: e.request.method, type: e.type, t: e.timestamp, initiator: e.initiator && e.initiator.type });
  });
  cdp.on('Network.responseReceived', (e) => {
    const r = reqs.get(e.requestId); if (!r) return;
    const h = e.response.headers;
    r.status = e.response.status; r.type = e.type; r.protocol = e.response.protocol;
    r.headers = {};
    for (const k of Object.keys(h)) {
      const lk = k.toLowerCase();
      if (['cache-control', 'expires', 'etag', 'last-modified', 'content-encoding', 'x-litespeed-cache', 'x-qc-cache', 'cf-cache-status', 'x-cache', 'age', 'content-type', 'server'].includes(lk)) r.headers[lk] = h[k];
    }
  });
  cdp.on('Network.loadingFinished', (e) => { const r = reqs.get(e.requestId); if (r) r.size = e.encodedDataLength; });
  cdp.on('Network.loadingFailed', (e) => { const r = reqs.get(e.requestId); if (r) { r.failed = e.errorText; } });

  const consoleMsgs = [];
  page.on('console', (m) => { if (['error', 'warning', 'warn'].includes(m.type())) consoleMsgs.push(m.type() + ': ' + m.text().slice(0, 300)); });
  page.on('pageerror', (e) => consoleMsgs.push('pageerror: ' + String(e.message).slice(0, 300)));

  await page.evaluateOnNewDocument(() => {
    window.__perf = { lcp: 0, cls: 0, longTasks: [] };
    new PerformanceObserver((l) => { for (const e of l.getEntries()) window.__perf.lcp = e.startTime; }).observe({ type: 'largest-contentful-paint', buffered: true });
    new PerformanceObserver((l) => { for (const e of l.getEntries()) if (!e.hadRecentInput) window.__perf.cls += e.value; }).observe({ type: 'layout-shift', buffered: true });
    new PerformanceObserver((l) => { for (const e of l.getEntries()) window.__perf.longTasks.push([e.startTime, e.duration]); }).observe({ type: 'longtask', buffered: true });
  });

  const t0 = Date.now();
  await page.goto(url, { waitUntil: 'load', timeout: 90000 });
  await new Promise((r) => setTimeout(r, 12000)); // Mirai loads after window.load
  const perf = await page.evaluate(() => {
    const n = performance.getEntriesByType('navigation')[0];
    const fcp = (performance.getEntriesByName('first-contentful-paint')[0] || {}).startTime || 0;
    const tbt = window.__perf.longTasks.filter(([s]) => s >= fcp).reduce((a, [, d]) => a + Math.max(0, d - 50), 0);
    return {
      ttfb: Math.round(n.responseStart), fcp: Math.round(fcp), dcl: Math.round(n.domContentLoadedEventEnd), load: Math.round(n.loadEventEnd),
      lcp: Math.round(window.__perf.lcp), cls: +window.__perf.cls.toFixed(4), tbtProxy: Math.round(tbt),
      longTasks: window.__perf.longTasks.length,
      // Booking-engine widgets (Mirai uses data-mirai-component); adjust the selector per site.
      bookingWidgets: [...document.querySelectorAll('[data-mirai-component]')].map((e) => e.getAttribute('data-mirai-component') + ':' + (e.offsetParent !== null ? 'visible' : 'hidden') + ':' + e.childElementCount),
      grecaptcha: typeof grecaptcha !== 'undefined',
    };
  });
  // scroll to trigger lazy content, then wait
  await page.evaluate(async () => { for (let y = 0; y < document.body.scrollHeight; y += 600) { window.scrollTo(0, y); await new Promise((r) => setTimeout(r, 150)); } });
  await new Promise((r) => setTimeout(r, 4000));
  await browser.close();

  const list = [...reqs.values()].filter((r) => !r.url.startsWith('data:'));
  const host = new URL(url).host;
  const sum = (arr) => arr.reduce((a, r) => a + (r.size || 0), 0);
  const byType = {};
  for (const r of list) { const t = typeOf(r); byType[t] = byType[t] || { n: 0, kb: 0 }; byType[t].n++; byType[t].kb += (r.size || 0) / 1024; }
  for (const t in byType) byType[t].kb = Math.round(byType[t].kb);
  // Repeated API calls (XHR/fetch) grouped by host+path — this is how duplicated widget
  // initialisation shows up (e.g. Mirai getCurrencyInfo x18).
  const apiCalls = {};
  for (const r of list.filter((r) => ['xhr', 'Fetch', 'XHR'].includes(r.type) || /api|json/.test(r.url))) { const u = new URL(r.url); const k = u.host + u.pathname.replace(/\/\d{6}\.json$/, '/MMYYYY.json'); apiCalls[k] = (apiCalls[k] || 0) + 1; }
  const repeatedApiCalls = Object.fromEntries(Object.entries(apiCalls).filter(([, n]) => n > 1));
  const result = {
    profile: profileName, run, url, wall: Date.now() - t0, perf,
    totals: {
      requests: list.length, thirdParty: list.filter((r) => !r.url.includes(host)).length,
      failed: list.filter((r) => r.failed || (r.status >= 400)).map((r) => (r.status || r.failed) + ' ' + r.url),
      totalKB: Math.round(sum(list) / 1024), byType,
    },
    repeatedApiCalls,
    recaptcha: list.filter((r) => /recaptcha|gstatic\.com\/recaptcha/.test(r.url)).map((r) => r.url.split('?')[0]),
    console: consoleMsgs,
  };
  fs.writeFileSync(path.join(outDir, `${profileName}-${run}.json`), JSON.stringify({ result, requests: list }, null, 1));
  return result;
}

(async () => {
  for (let i = 1; i <= runs; i++) {
    for (const prof of ['desktop', 'mobile']) {
      const r = await measure(prof, i);
      console.log(JSON.stringify(r, null, 1));
    }
  }
})();
