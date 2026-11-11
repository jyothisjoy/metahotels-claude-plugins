// usage: node lcp-timeline.js <url> [runs] [--fast] [--desktop] [--wait=ms]
// Prints EVERY largest-contentful-paint candidate (time, size, element, image) of a cold load, not only the last
// one. On a hero slideshow each new slide can become a new candidate, so the "LCP" a lab tool reports is whichever
// slide was on screen when the tool stopped listening. Default: mobile, Slow 4G + 4x CPU (same as throttle.js).
const puppeteer = require('puppeteer-core');
const args = process.argv.slice(2);
const pos = args.filter((a) => !a.startsWith('--'));
const url = pos[0];
const runs = +(pos[1] || 1);
const fast = args.includes('--fast');
const desktop = args.includes('--desktop');
const waitArg = args.find((a) => a.startsWith('--wait='));
const wait = waitArg ? +waitArg.split('=')[1] : 8000;
(async () => {
  for (let i = 0; i < runs; i++) {
    const b = await puppeteer.launch({ executablePath: require('./_lib').CHROME, headless: 'new' });
    const p = await b.newPage();
    if (desktop) await p.setViewport({ width: 1440, height: 900 });
    else {
      await p.setViewport({ width: 390, height: 844, isMobile: true, hasTouch: true, deviceScaleFactor: 3 });
      await p.setUserAgent('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1');
    }
    const c = await p.target().createCDPSession();
    await c.send('Network.enable');
    await c.send('Network.setCacheDisabled', { cacheDisabled: true });
    if (!fast) {
      await c.send('Network.emulateNetworkConditions', { offline: false, latency: 150, downloadThroughput: (1.6 * 1024 * 1024) / 8, uploadThroughput: (750 * 1024) / 8 });
      await c.send('Emulation.setCPUThrottlingRate', { rate: 4 });
    }
    await p.evaluateOnNewDocument(() => {
      window.__lcps = [];
      new PerformanceObserver((l) => {
        for (const e of l.getEntries()) {
          const el = e.element;
          window.__lcps.push({ t: Math.round(e.startTime), size: e.size, el: el ? el.tagName + '.' + String(el.className).split(' ').slice(0, 2).join('.') : '(removed)', url: (e.url || '').split('/').pop().slice(0, 40), text: el && !e.url ? (el.textContent || '').trim().slice(0, 30) : '' });
        }
      }).observe({ type: 'largest-contentful-paint', buffered: true });
    });
    await p.goto(url, { waitUntil: 'load', timeout: 180000 });
    await new Promise((r) => setTimeout(r, wait));
    const out = await p.evaluate(() => ({
      fcp: Math.round((performance.getEntriesByName('first-contentful-paint')[0] || {}).startTime || 0),
      dcl: Math.round(performance.getEntriesByType('navigation')[0].domContentLoadedEventEnd),
      load: Math.round(performance.getEntriesByType('navigation')[0].loadEventEnd),
      lcps: window.__lcps,
    }));
    console.log('run ' + (i + 1) + ': FCP ' + out.fcp + ' DCL ' + out.dcl + ' load ' + out.load);
    for (const e of out.lcps) console.log('   ' + String(e.t).padStart(6) + ' ms  size ' + String(e.size).padStart(7) + '  ' + e.el + '  ' + (e.url || '"' + e.text + '"'));
    await b.close();
  }
})();
