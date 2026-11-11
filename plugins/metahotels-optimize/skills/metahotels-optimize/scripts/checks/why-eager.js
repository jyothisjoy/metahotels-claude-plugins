// usage (from the site folder): node <skill>/scripts/checks/why-eager.js <url> [--mobile] [--watch=<regex of image file names>]
// Why do below-the-fold images load without scrolling? Samples page height, scroll position, how many top-level
// containers Elementor has "lazy-loaded" and how many image requests have started, every 250 ms of a cold load.
// --watch: below-the-fold images to time (first request and initiator), e.g. --watch='hero-2|gallery-0[1-3]'.
// First written for Gevora (2026-10-12): the timed popup scrolled the page to the footer (pattern "popup scroll").
const puppeteer = require('puppeteer-core');
const url = process.argv[2];
const mobile = process.argv.includes('--mobile');
const watchArg = process.argv.find((a) => a.startsWith('--watch='));
const WATCH = watchArg ? new RegExp(watchArg.slice(8)) : null;
(async () => {
  const b = await puppeteer.launch({ executablePath: require('./_lib').CHROME, headless: 'new' });
  const p = await b.newPage();
  if (mobile) {
    await p.setViewport({ width: 390, height: 844, isMobile: true, hasTouch: true, deviceScaleFactor: 3 });
    await p.setUserAgent('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1');
  } else await p.setViewport({ width: 1440, height: 900 });
  const c = await p.target().createCDPSession();
  await c.send('Network.enable');
  if (!process.argv.includes('--cache')) await c.send('Network.setCacheDisabled', { cacheDisabled: true });
  let imgs = 0, t0 = Date.now();
  const firstSeen = {};
  c.on('Network.requestWillBeSent', (e) => {
    if (e.type === 'Image') {
      imgs++;
      const n = e.request.url.split('/').pop().split('?')[0];
      if (WATCH && WATCH.test(n) && !firstSeen[n]) firstSeen[n] = ((Date.now() - t0) / 1000).toFixed(1) + ' s  initiator ' + e.initiator.type + (e.initiator.url ? ' ' + e.initiator.url.split('/').pop().slice(0, 40) : '');
    }
  });
  await p.evaluateOnNewDocument(() => {
    window.__scrolls = [];
    addEventListener('scroll', () => window.__scrolls.push(Math.round(performance.now()) + ':' + Math.round(scrollY)), true);
  });
  p.goto(url, { waitUntil: 'load', timeout: 120000 }).catch(() => {});
  let last = '';
  for (let i = 0; i < 120; i++) {
    await new Promise((r) => setTimeout(r, 250));
    const s = await p.evaluate(() => {
      if (!document.body) return null;
      const tops = [...document.querySelectorAll('.e-con.e-parent')];
      return {
        h: document.documentElement.scrollHeight, y: Math.round(scrollY), rs: document.readyState,
        tops: tops.length, lazyloaded: tops.filter((e) => e.classList.contains('e-lazyloaded')).length,
        vh: innerHeight, css: [...document.styleSheets].length,
      };
    }).catch(() => null);
    if (!s) continue;
    const line = JSON.stringify(s) + ' imgReq ' + imgs;
    if (line !== last) { console.log(((Date.now() - t0) / 1000).toFixed(1) + ' s ' + line); last = line; }
  }
  console.log('scroll events:', (await p.evaluate(() => window.__scrolls.slice(0, 12).join(' '))) || 'none');
  console.log('first request of sample below-the-fold images:');
  for (const [k, v] of Object.entries(firstSeen)) console.log('  ' + k.padEnd(34) + v);
  await b.close();
})();
