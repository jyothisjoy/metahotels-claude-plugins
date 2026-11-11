// usage: node coldcheck.js <url> [runs]
// Cold-cache initialisation check: a fresh browser per run (desktop 1440 and mobile 390), no interaction.
// Reports whether Elementor ran its element handlers: carousels initialised, sticky bar active, and the
// above-the-fold entrance-animation elements no longer hidden. Catches load-order races that warm loads hide.
const puppeteer = require('puppeteer-core');
const url = process.argv[2];
const runs = +(process.argv[3] || 5);
(async () => {
  for (const w of [1440, 390]) {
    const res = [];
    for (let i = 0; i < runs; i++) {
      const b = await puppeteer.launch({ executablePath: require('./_lib').CHROME, headless: 'new' });
      const p = await b.newPage();
      if (w === 390) {
        await p.setViewport({ width: 390, height: 844, isMobile: true, hasTouch: true });
        await p.setUserAgent('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1');
      } else await p.setViewport({ width: w, height: 900 });
      const errs = [];
      p.on('pageerror', (e) => errs.push(String(e.message).slice(0, 80)));
      await p.goto(url, { waitUntil: 'load', timeout: 120000 });
      await new Promise((r) => setTimeout(r, 6000));
      const s = await p.evaluate(() => {
        const inView = (e) => { const r = e.getBoundingClientRect(); return r.bottom > 0 && r.top < innerHeight && r.width > 0; };
        const hiddenAbove = [...document.querySelectorAll('.elementor-invisible')].filter((e) => !e.closest('.elementor-sticky__spacer') && !e.classList.contains('elementor-sticky__spacer') && inView(e)).length;
        return document.querySelectorAll('.swiper-initialized').length + '/' + document.querySelectorAll('.swiper').length + ' sticky' + document.querySelectorAll('.elementor-sticky--active').length + ' hiddenInView' + hiddenAbove;
      });
      res.push(s + (errs.length ? ' ERR:' + errs[0] : ''));
      await b.close();
    }
    const bad = res.filter((r) => /^0\/[1-9]/.test(r) || /hiddenInView[1-9]/.test(r) || /ERR/.test(r)).length;
    console.log(w + 'px: ' + (bad ? bad + '/' + runs + ' BAD' : 'all ' + runs + ' ok') + '  [' + res.join(' | ') + ']');
  }
})();
