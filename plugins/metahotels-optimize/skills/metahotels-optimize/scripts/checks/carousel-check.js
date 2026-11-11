// usage: node carousel-check.js <url> [desktop|mobile]
// With image lazy-loading on: every carousel on the page (not the background slideshows) is scrolled into view and
// stepped with its "next" arrow (or dragged when it has none); 900 ms after each step the script counts images that
// are inside the carousel's visible box but have not painted. Also reports each carousel's kind and slide count.
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
  await sleep(3000);
  const n = await p.evaluate(() => { window.__car = [...document.querySelectorAll('.swiper')].filter((s) => !s.classList.contains('elementor-background-slideshow') && s.getBoundingClientRect().width > 0); return window.__car.length; });
  const out = [];
  for (let i = 0; i < n; i++) {
    const info = await p.evaluate(async (i) => {
      const s = window.__car[i];
      s.scrollIntoView({ block: 'center', behavior: 'instant' });
      const w = s.closest('.elementor-widget');
      return (w ? w.dataset.widget_type + '#' + w.dataset.id : 'swiper') + ' slides=' + s.querySelectorAll('.swiper-slide:not(.swiper-slide-duplicate)').length + ' init=' + s.classList.contains('swiper-initialized');
    }, i);
    await sleep(1800);
    const missing = () => p.evaluate((i) => {
      const s = window.__car[i], box = s.getBoundingClientRect();
      return [...s.querySelectorAll('img')].filter((im) => { const r = im.getBoundingClientRect(); return r.width > 20 && r.height > 20 && r.right > box.left + 5 && r.left < box.right - 5 && r.right > 0 && r.left < innerWidth && !(im.complete && im.naturalWidth > 1); }).map((im) => (im.currentSrc || im.getAttribute('data-src') || '?').split('/').pop().slice(0, 30));
    }, i);
    const steps = [];
    let m = await missing();
    steps.push(m.length);
    const late = [...m];
    for (let k = 0; k < 6; k++) {
      const moved = await p.evaluate((i) => {
        const s = window.__car[i]; const w = s.closest('.elementor-widget') || s.parentElement;
        const next = w.querySelector('.elementor-swiper-button-next, .swiper-button-next');
        if (next && next.getBoundingClientRect().width > 0) { next.click(); return 'arrow'; }
        if (s.swiper) { s.swiper.slideNext(); return 'api'; }
        return 'none';
      }, i);
      if (moved === 'none') break;
      await sleep(900);
      m = await missing();
      steps.push(m.length);
      late.push(...m);
    }
    out.push(info + ' missingPerStep=' + steps.join(',') + (late.length ? ' LATE: ' + [...new Set(late)].join(',') : ''));
  }
  console.log((mobile ? 'mobile' : 'desktop') + ' carousels=' + n + '\n  ' + out.join('\n  ') + '\n  errors=' + JSON.stringify(errs));
  await b.close();
})();
