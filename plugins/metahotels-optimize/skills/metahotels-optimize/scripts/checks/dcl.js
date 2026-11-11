// usage: node dcl.js <url> [runs] [--rules=rules.json] [--block=regex]
// Throttled phone (Slow 4G + 4x CPU), cold cache. Splits DOMContentLoaded into "scripts downloaded and parsed"
// (domInteractive, domContentLoadedEventStart) and "ready handlers ran" (domContentLoadedEventEnd), and lists the
// long tasks around it, so a late DCL can be put down to the network or to script work.
const puppeteer = require('puppeteer-core');
const fs = require('fs');
const args = process.argv.slice(2);
const pos = args.filter((a) => !a.startsWith('--'));
const url = pos[0], runs = +(pos[1] || 1);
const opt = (n) => { const a = args.find((x) => x.startsWith('--' + n + '=')); return a ? a.slice(n.length + 3) : null; };
const BLOCK = opt('block') ? new RegExp(opt('block')) : null;
const UA = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1';
(async () => {
  let html = null;
  if (opt('rules')) {
    html = await (await fetch(url, { headers: { 'user-agent': UA } })).text();
    for (const r of JSON.parse(fs.readFileSync(opt('rules'), 'utf8'))) {
      const before = html;
      html = r.regex ? html.replace(new RegExp(r.find, r.flags || ''), () => r.replace) : html.split(r.find).join(r.replace);
      if (html === before) { console.error('RULE DID NOT MATCH: ' + r.find.slice(0, 80)); process.exit(2); }
    }
  }
  for (let i = 0; i < runs; i++) {
    const b = await puppeteer.launch({ executablePath: require('./_lib').CHROME, headless: 'new' });
    const p = await b.newPage();
    await p.setViewport({ width: 390, height: 844, isMobile: true, hasTouch: true, deviceScaleFactor: 3 });
    await p.setUserAgent(UA);
    const c = await p.target().createCDPSession();
    await c.send('Network.enable');
    await c.send('Network.setCacheDisabled', { cacheDisabled: true });
    await c.send('Network.emulateNetworkConditions', { offline: false, latency: 150, downloadThroughput: (1.6 * 1024 * 1024) / 8, uploadThroughput: (750 * 1024) / 8 });
    await c.send('Emulation.setCPUThrottlingRate', { rate: 4 });
    if (html || BLOCK) {
      await p.setRequestInterception(true);
      let served = false;
      p.on('request', (rq) => {
        if (html && !served && rq.isNavigationRequest() && rq.frame() === p.mainFrame()) { served = true; rq.respond({ status: 200, contentType: 'text/html; charset=UTF-8', body: html }); } else if (BLOCK && BLOCK.test(rq.url())) rq.abort(); else rq.continue();
      });
    }
    await p.evaluateOnNewDocument(() => {
      window.__lt = [];
      try { new PerformanceObserver((l) => { for (const e of l.getEntries()) window.__lt.push([Math.round(e.startTime), Math.round(e.duration)]); }).observe({ type: 'longtask', buffered: true }); } catch (e) {}
    });
    await p.goto(url, { waitUntil: 'load', timeout: 240000 });
    const r = await p.evaluate(() => { const n = performance.getEntriesByType('navigation')[0]; const f = performance.getEntriesByName('first-contentful-paint')[0]; return { fcp: f ? Math.round(f.startTime) : 0, interactive: Math.round(n.domInteractive), dclStart: Math.round(n.domContentLoadedEventStart), dclEnd: Math.round(n.domContentLoadedEventEnd), load: Math.round(n.loadEventStart), lt: window.__lt }; });
    const around = r.lt.filter(([s, d]) => s < r.dclEnd + 200);
    console.log('run ' + (i + 1) + ': FCP ' + r.fcp + ' | domInteractive ' + r.interactive + ' | DCL start ' + r.dclStart + ' end ' + r.dclEnd + ' (handlers ' + (r.dclEnd - r.dclStart) + ' ms) | load ' + r.load + ' | long tasks up to DCL end (start+duration, total ' + around.reduce((a, x) => a + x[1], 0) + ' ms): ' + around.map(([s, d]) => s + '+' + d).join(' '));
    await b.close();
  }
})();
