// usage: node iframe-check.js <url> [desktop|mobile]
// With iframe lazy-loading on: does an embedded map (or any other iframe) actually load when scrolled into view?
// Prints every visible-size iframe with its src state before and after scrolling to it.
const puppeteer = require('puppeteer-core');
const SHOTS = require('./_lib').shots();
const [url, prof] = process.argv.slice(2);
const mobile = prof === 'mobile';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
(async () => {
  const b = await puppeteer.launch({ executablePath: require('./_lib').CHROME, headless: 'new' });
  const p = await b.newPage();
  if (mobile) {
    await p.setViewport({ width: 390, height: 844, isMobile: true, hasTouch: true });
    await p.setUserAgent('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1');
  } else await p.setViewport({ width: 1440, height: 900 });
  const reqs = [];
  p.on('request', (r) => { if (/google\.com\/maps|maps\.google|maps\.gstatic|youtube/.test(r.url())) reqs.push(1); });
  await p.goto(url, { waitUntil: 'load', timeout: 120000 });
  await sleep(4000);
  const read = () => p.evaluate(() => [...document.querySelectorAll('iframe')].map((f) => { const r = f.getBoundingClientRect(); return { w: Math.round(r.width), h: Math.round(r.height), top: Math.round(r.top + scrollY), src: (f.getAttribute('src') || '').slice(0, 40), dataSrc: (f.getAttribute('data-src') || '').slice(0, 40), lazy: f.getAttribute('data-lazyloaded'), cls: f.className.slice(0, 30), disp: getComputedStyle(f).display }; }).filter((x) => x.w > 50 || x.dataSrc));
  const before = await read();
  const mapReqBefore = reqs.length;
  for (const f of before) { await p.evaluate((y) => window.scrollTo(0, Math.max(0, y - 200)), f.top); await sleep(3500); }
  const after = await read();
  await p.screenshot({ path: SHOTS + '/iframe-check-' + (mobile ? 'm' : 'd') + '.png' });
  console.log(mobile ? 'mobile' : 'desktop', JSON.stringify({ before, mapRequestsBeforeScroll: mapReqBefore, after, mapRequestsAfterScroll: reqs.length }));
  await b.close();
})();
