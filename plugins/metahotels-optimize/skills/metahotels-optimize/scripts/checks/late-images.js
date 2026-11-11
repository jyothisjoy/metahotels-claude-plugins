// usage: node late-images.js <url> [desktop|mobile]
// Follow-up to lazy-check.js: scrolls the page in viewport steps and, at each stop, reports images in view that
// have not painted after 0.7 s and again after 4 s, with what kind of element they are (lazy state, carousel slide,
// Swiper duplicate). "after 4 s" > 0 means the image never arrives, not that it is merely slow.
const puppeteer = require('puppeteer-core');
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
  await p.goto(url, { waitUntil: 'load', timeout: 120000 });
  await sleep(4000);
  const missing = () => p.evaluate(() => [...document.images].filter((i) => { const r = i.getBoundingClientRect(); return r.width > 20 && r.height > 20 && r.bottom > 0 && r.top < innerHeight && r.right > 0 && r.left < innerWidth && !(i.complete && i.naturalWidth > 1); }).map((i) => {
    const sl = i.closest('.swiper-slide'); const w = i.closest('.elementor-widget');
    return (i.getAttribute('data-src') || i.currentSrc || i.src || '?').split('/').pop().slice(0, 34) + ' [' + (w ? w.dataset.widget_type + '#' + w.dataset.id : '-') + (sl ? ' slide' + (sl.classList.contains('swiper-slide-duplicate') ? ' DUPLICATE' : '') : '') + ' lazyloaded=' + i.getAttribute('data-lazyloaded') + ' ll-status=' + i.getAttribute('data-ll-status') + ' srcIsPlaceholder=' + /^data:/.test(i.getAttribute('src') || '') + ' class=' + i.className.slice(0, 40) + ']';
  }));
  const height = await p.evaluate(() => document.documentElement.scrollHeight);
  let never = 0, slow = 0;
  for (let y = 0; y < height; y += mobile ? 700 : 750) {
    await p.evaluate((v) => window.scrollTo({ top: v, behavior: 'instant' }), y);
    await sleep(700);
    const a = await missing();
    if (!a.length) continue;
    await sleep(3300);
    const c = await missing();
    slow += a.length - c.length; never += c.length;
    console.log('y=' + y + ': not painted after 0.7 s: ' + a.length + ', after 4 s: ' + c.length);
    for (const x of (c.length ? c : a).slice(0, 4)) console.log('     ' + x);
  }
  console.log((mobile ? 'mobile' : 'desktop') + ' total: slow (arrived within 4 s) ' + slow + ', never arrived ' + never);
  await b.close();
})();
