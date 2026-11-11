// usage: node lazy-check.js <url> [desktop|mobile]
// With image lazy-loading on: are images there when the visitor gets to them? Scrolls the page in viewport steps
// and, 700 ms after each step, counts <img> in view that have not painted. Then goes to every carousel, lets it
// autoplay and steps it with its "next" arrow, counting slides in view whose image is still missing.
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
  const errs = [];
  p.on('pageerror', (e) => errs.push(String(e.message).slice(0, 100)));
  await p.goto(url, { waitUntil: 'load', timeout: 120000 });
  await sleep(4000);
  const missing = () => p.evaluate(() => [...document.images].filter((i) => { const r = i.getBoundingClientRect(); return r.width > 20 && r.height > 20 && r.bottom > 0 && r.top < innerHeight && r.right > 0 && r.left < innerWidth && getComputedStyle(i).visibility !== 'hidden' && !(i.complete && i.naturalWidth > 1); }).map((i) => (i.getAttribute('data-src') || i.currentSrc || i.src).split('/').pop().slice(0, 40)));
  const height = await p.evaluate(() => document.documentElement.scrollHeight);
  const step = mobile ? 700 : 750;
  let stops = 0, late = [];
  for (let y = 0; y < height; y += step) {
    await p.evaluate((v) => window.scrollTo(0, v), y);
    await sleep(700);
    const m = await missing();
    stops++;
    if (m.length) late.push('y=' + y + ': ' + m.join(','));
  }
  const cars = await p.evaluate(() => [...document.querySelectorAll('.elementor-widget-loop-carousel, .elementor-widget-media-carousel, .bk-testi2-sec, .elementor-widget-go-testimonial')].filter((e) => e.getBoundingClientRect().height > 50).map((e) => e.getAttribute('data-id') || e.className.split(' ')[0]));
  const carOut = [];
  const widgets = await p.$$('.elementor-widget-loop-carousel, .elementor-widget-media-carousel');
  for (const w of widgets) {
    const box = await w.boundingBox();
    if (!box || box.height < 50) continue;
    await p.evaluate((e) => e.scrollIntoView({ block: 'center' }), w);
    await sleep(1200);
    const first = (await missing()).length;
    await sleep(6500); // one autoplay step
    const afterAuto = (await missing()).length;
    let afterNext = 0;
    const next = await w.$('.elementor-swiper-button-next');
    if (next) for (let i = 0; i < 4; i++) { await next.evaluate((e) => e.click()); await sleep(900); afterNext += (await missing()).length; }
    carOut.push((await w.evaluate((e) => e.getAttribute('data-id'))) + ' arrive=' + first + ' autoplay=' + afterAuto + ' next4=' + afterNext);
  }
  const still = await p.evaluate(() => [...document.images].filter((i) => i.hasAttribute('data-src') && !i.getAttribute('data-lazyloaded') === false).length);
  console.log(mobile ? 'mobile' : 'desktop', JSON.stringify({ scrollStops: stops, stopsWithMissingImages: late.length, late: late.slice(0, 6), carousels: carOut, errors: errs }));
  await b.close();
})();
