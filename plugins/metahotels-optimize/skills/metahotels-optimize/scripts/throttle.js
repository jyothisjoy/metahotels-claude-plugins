// usage: node throttle.js <label> <url> [runs] [--vary]
// --vary: LiteSpeed Guest Mode sites: set the _lscache_vary cookie first (from guest.vary.php), so the normal copy is
// measured; without it the guest copy can reload itself inside the measuring window and the run reads 0.
// Mobile, ~Slow 4G (150ms RTT, 1.6 Mbps) + 4x CPU, cold cache. Prints each run and the median FCP/LCP/DCL.
// Use this (not PageSpeed mobile) to decide whether a setting helps: PSI mobile lab can swing FCP 2s -> 11s
// between identical runs on sites with many render-blocking files.
const puppeteer = require('puppeteer-core');
const argv = process.argv.slice(2);
const [label, url, runsArg] = argv.filter((a) => !a.startsWith('--'));
const VARY_ON = argv.includes('--vary');
const UA = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1';
async function getVary() {
  const u = new URL(url);
  const r = await fetch(u.origin + '/wp-content/plugins/litespeed-cache/guest.vary.php', { method: 'POST', headers: { 'user-agent': UA } });
  const m = /_lscache_vary=([^;]+)/.exec(r.headers.get('set-cookie') || '');
  if (!m) { console.error('--vary: no _lscache_vary cookie'); process.exit(2); }
  return { name: '_lscache_vary', value: m[1], domain: u.hostname, path: '/' };
}
if (!url) { console.error('usage: node throttle.js <label> <url> [runs]'); process.exit(1); }
const runs = +(runsArg || 3);
(async () => {
  const res = [];
  for (let i = 0; i < runs; i++) {
    const b = await puppeteer.launch({ executablePath: require('./checks/_lib').CHROME, headless: 'new' });
    const p = await b.newPage();
    await p.setViewport({ width: 390, height: 844, isMobile: true, hasTouch: true, deviceScaleFactor: 3 });
    await p.setUserAgent('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1');
    const c = await p.target().createCDPSession();
    await c.send('Network.enable');
    await c.send('Network.setCacheDisabled', { cacheDisabled: true });
    await c.send('Network.emulateNetworkConditions', { offline: false, latency: 150, downloadThroughput: (1.6 * 1024 * 1024) / 8, uploadThroughput: (750 * 1024) / 8 });
    await c.send('Emulation.setCPUThrottlingRate', { rate: 4 });
    await p.evaluateOnNewDocument(() => {
      window.__lcp = 0;
      new PerformanceObserver((l) => { for (const e of l.getEntries()) window.__lcp = e.startTime; }).observe({ type: 'largest-contentful-paint', buffered: true });
    });
    if (VARY_ON) await p.setCookie(await getVary());
    await p.goto(url, { waitUntil: 'load', timeout: 180000 });
    await new Promise((r) => setTimeout(r, 3000));
    res.push(await p.evaluate(() => ({
      fcp: Math.round((performance.getEntriesByName('first-contentful-paint')[0] || {}).startTime || 0),
      lcp: Math.round(window.__lcp),
      dcl: Math.round(performance.getEntriesByType('navigation')[0].domContentLoadedEventEnd),
      css: performance.getEntriesByType('resource').filter((e) => e.initiatorType === 'link' && /\.css/.test(e.name)).length,
    })));
    await b.close();
  }
  const med = (k) => res.map((r) => r[k]).sort((a, b) => a - b)[Math.floor(res.length / 2)];
  console.log(label, JSON.stringify(res), '| median FCP', med('fcp'), 'LCP', med('lcp'), 'DCL', med('dcl'));
})();
