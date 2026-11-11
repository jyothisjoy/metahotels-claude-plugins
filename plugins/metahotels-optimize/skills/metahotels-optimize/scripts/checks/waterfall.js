// usage: node waterfall.js <url> [--desktop] [--fast] [--min=KB] [--block=regex] [--vary]
// Throttled phone (Slow 4G + 4x CPU, same as throttle.js), cold cache: FCP, DOMContentLoaded and load, and every
// request of at least --min KB (default 25) with start and end time, priority and size. Shows what is competing for
// the connection before DOMContentLoaded.
const puppeteer = require('puppeteer-core');
const args = process.argv.slice(2);
const url = args.find((a) => !a.startsWith('--'));
const opt = (n) => { const a = args.find((x) => x.startsWith('--' + n + '=')); return a ? a.slice(n.length + 3) : null; };
const min = +(opt('min') || 25);
const BLOCK = opt('block') ? new RegExp(opt('block')) : null;
(async () => {
  const b = await puppeteer.launch({ executablePath: require('./_lib').CHROME, headless: 'new' });
  const p = await b.newPage();
  if (args.includes('--desktop')) await p.setViewport({ width: 1440, height: 900 });
  else {
    await p.setViewport({ width: 390, height: 844, isMobile: true, hasTouch: true, deviceScaleFactor: 3 });
    await p.setUserAgent('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1');
  }
  const c = await p.target().createCDPSession();
  await c.send('Network.enable');
  await c.send('Network.setCacheDisabled', { cacheDisabled: true });
  if (!args.includes('--fast')) {
    await c.send('Network.emulateNetworkConditions', { offline: false, latency: 150, downloadThroughput: (1.6 * 1024 * 1024) / 8, uploadThroughput: (750 * 1024) / 8 });
    await c.send('Emulation.setCPUThrottlingRate', { rate: 4 });
  }
  if (args.includes('--vary')) {
    // LiteSpeed Guest Mode: take the _lscache_vary cookie first so the normal copy is measured (as throttle.js --vary).
    const u = new URL(url);
    const r = await fetch(u.origin + '/wp-content/plugins/litespeed-cache/guest.vary.php', { method: 'POST', headers: { 'user-agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1' } });
    const m = /_lscache_vary=([^;]+)/.exec(r.headers.get('set-cookie') || '');
    if (!m) { console.error('--vary: no _lscache_vary cookie'); process.exit(2); }
    await p.setCookie({ name: '_lscache_vary', value: m[1], domain: u.hostname, path: '/' });
  }
  if (BLOCK) { await p.setRequestInterception(true); p.on('request', (rq) => (BLOCK.test(rq.url()) ? rq.abort() : rq.continue())); }
  const req = new Map();
  let t0 = null;
  c.on('Network.requestWillBeSent', (e) => { if (t0 === null) t0 = e.timestamp; req.set(e.requestId, { url: e.request.url, start: e.timestamp - t0, type: e.type, prio: e.request.initialPriority, init: e.initiator.type }); });
  c.on('Network.loadingFinished', (e) => { const r = req.get(e.requestId); if (r) { r.end = e.timestamp - t0; r.kb = e.encodedDataLength / 1024; } });
  await p.goto(url, { waitUntil: 'load', timeout: 240000 });
  const t = await p.evaluate(() => { const n = performance.getEntriesByType('navigation')[0]; const f = performance.getEntriesByName('first-contentful-paint')[0]; return { fcp: f ? f.startTime : 0, dcl: n.domContentLoadedEventEnd, load: n.loadEventStart }; });
  const all = [...req.values()].filter((r) => r.end !== undefined);
  const before = all.filter((r) => r.start * 1000 < t.dcl);
  const sum = (l) => Math.round(l.reduce((a, r) => a + (r.kb || 0), 0));
  const byType = {};
  for (const r of before) byType[r.type] = (byType[r.type] || 0) + (r.kb || 0);
  console.log('FCP ' + (t.fcp / 1000).toFixed(1) + ' s | DCL ' + (t.dcl / 1000).toFixed(1) + ' s | load ' + (t.load / 1000).toFixed(1) + ' s | started before DCL: ' + before.length + ' requests, ' + sum(before) + ' KB (' + Object.entries(byType).sort((a, b2) => b2[1] - a[1]).map(([k, v]) => k + ' ' + Math.round(v)).join(', ') + ')');
  for (const r of before.filter((x) => x.kb >= min).sort((a, b2) => a.start - b2.start)) console.log('  ' + r.start.toFixed(1).padStart(5) + ' -> ' + r.end.toFixed(1).padStart(5) + ' s ' + String(Math.round(r.kb)).padStart(5) + ' KB ' + r.prio.padEnd(8) + r.type.padEnd(11) + r.url.replace(/^https?:\/\//, '').split('?')[0].slice(-72));
  await b.close();
})();
