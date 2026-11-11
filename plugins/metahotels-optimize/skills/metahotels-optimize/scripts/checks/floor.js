// usage: node floor.js <label> <url> [runs] [--block=regex]
// Same conditions as _perf-toolkit/throttle.js (mobile, Slow 4G + 4x CPU, cold cache, the real compressed document),
// with matching requests aborted. Answers "how early could the first paint be if these files did not block it":
// the upper bound for critical CSS, unused-CSS removal, combine or defer, before any of them is switched on.
// (abhtml.js cannot answer this: it serves the document uncompressed through interception, which hides the CSS.)
const puppeteer = require('puppeteer-core');
const args = process.argv.slice(2);
const [label, url, runsArg] = args.filter((a) => !a.startsWith('--'));
const b = args.find((a) => a.startsWith('--block='));
const BLOCK = b ? new RegExp(b.slice(8)) : null;
const runs = +(runsArg || 3);
(async () => {
  const res = [];
  for (let i = 0; i < runs; i++) {
    const br = await puppeteer.launch({ executablePath: require('./_lib').CHROME, headless: 'new' });
    const p = await br.newPage();
    await p.setViewport({ width: 390, height: 844, isMobile: true, hasTouch: true, deviceScaleFactor: 3 });
    await p.setUserAgent('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1');
    const c = await p.target().createCDPSession();
    await c.send('Network.enable');
    await c.send('Network.setCacheDisabled', { cacheDisabled: true });
    await c.send('Network.emulateNetworkConditions', { offline: false, latency: 150, downloadThroughput: (1.6 * 1024 * 1024) / 8, uploadThroughput: (750 * 1024) / 8 });
    await c.send('Emulation.setCPUThrottlingRate', { rate: 4 });
    let blocked = 0;
    if (BLOCK) {
      await p.setRequestInterception(true);
      p.on('request', (r) => { if (BLOCK.test(r.url())) { blocked++; r.abort(); } else r.continue(); });
    }
    await p.evaluateOnNewDocument(() => {
      window.__lcp = 0;
      new PerformanceObserver((l) => { for (const e of l.getEntries()) window.__lcp = e.startTime; }).observe({ type: 'largest-contentful-paint', buffered: true });
    });
    await p.goto(url, { waitUntil: 'load', timeout: 180000 });
    await new Promise((r) => setTimeout(r, 3000));
    const m = await p.evaluate(() => { const n = performance.getEntriesByType('navigation')[0]; return { ttfb: Math.round(n.responseStart), html: Math.round(n.responseEnd), fcp: Math.round((performance.getEntriesByName('first-contentful-paint')[0] || {}).startTime || 0), lcp: Math.round(window.__lcp), dcl: Math.round(n.domContentLoadedEventEnd), load: Math.round(n.loadEventEnd) }; });
    m.blocked = blocked;
    res.push(m);
    await br.close();
  }
  const med = (k) => res.map((r) => r[k]).sort((a, c) => a - c)[Math.floor(res.length / 2)];
  console.log(label.padEnd(34), 'median TTFB', med('ttfb'), 'HTML done', med('html'), 'FCP', med('fcp'), 'LCP', med('lcp'), 'DCL', med('dcl'), 'load', med('load'), '| blocked', res[0].blocked, '| FCP runs', res.map((r) => r.fcp).join(','));
})();
