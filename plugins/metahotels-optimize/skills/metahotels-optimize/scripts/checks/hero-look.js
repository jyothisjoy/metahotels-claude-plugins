// usage (from the site folder): node <skill>/scripts/checks/hero-look.js <url> <label> [rules.json] [--hero=<selector>]
// Does the CSS-painted first slide look the same as the slideshow's first slide? Unthrottled, desktop and mobile:
//   <label>-<d|m>-static.png  rules applied, JavaScript off  -> only the static CSS background can paint
//   <label>-<d|m>-slide.png   live page, taken as soon as the slideshow's active slide has its image
// Prints the mean absolute pixel difference of the two (0-255) for the top 60% of the viewport.
// --hero (or site.json selectors.hero): the container that holds the background slideshow.
const puppeteer = require('puppeteer-core');
const SHOTS = require('./_lib').shots();
const fs = require('fs');
const { PNG } = require('pngjs');
const [url, label, rulesFile] = process.argv.slice(2).filter((a) => !a.startsWith('--'));
const heroArg = process.argv.find((a) => a.startsWith('--hero='));
const HERO = heroArg ? heroArg.slice(7) : require('./_lib').sel('hero', '[data-elementor-type="wp-page"] > .elementor-element:first-child');
(async () => {
  for (const prof of ['d', 'm']) {
    const mobile = prof === 'm';
    const UA = mobile
      ? 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1'
      : 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36';
    let html = await (await fetch(url, { headers: { 'user-agent': UA } })).text();
    if (rulesFile) for (const r of JSON.parse(fs.readFileSync(rulesFile, 'utf8'))) {
      const before = html;
      html = html.split(r.find).join(r.replace);
      if (html === before) { console.error('RULE DID NOT MATCH'); process.exit(2); }
    }
    const b = await puppeteer.launch({ executablePath: require('./_lib').CHROME, headless: 'new' });
    const vp = mobile ? { width: 390, height: 844, isMobile: true, hasTouch: true } : { width: 1440, height: 900 };
    // static: JS off
    let p = await b.newPage();
    await p.setViewport(vp); await p.setUserAgent(UA);
    await p.setJavaScriptEnabled(false);
    await p.setRequestInterception(true);
    let served = false;
    p.on('request', (rq) => { if (!served && rq.isNavigationRequest()) { served = true; rq.respond({ status: 200, contentType: 'text/html; charset=UTF-8', body: html }); } else rq.continue(); });
    await p.goto(url, { waitUntil: 'networkidle2', timeout: 90000 });
    const f1 = SHOTS + '/' + label + '-' + prof + '-static.png';
    await p.screenshot({ path: f1 });
    await p.close();
    // slide: live page
    p = await b.newPage();
    await p.setViewport(vp); await p.setUserAgent(UA);
    await p.setJavaScriptEnabled(false); // same no-JS render of text/header as the static shot...
    await p.setJavaScriptEnabled(true);  // ...is not possible with the slideshow, so JS stays on here
    await p.goto(url, { waitUntil: 'domcontentloaded', timeout: 90000 });
    await p.waitForSelector(HERO + ' > .elementor-background-slideshow .swiper-slide-active .elementor-background-slideshow__slide__image', { timeout: 60000 });
    await p.waitForFunction((h) => { const a = document.querySelector(h + ' > .elementor-background-slideshow .swiper-slide-active'); return a && (!a.querySelector('.swiper-lazy') || a.querySelector('.swiper-lazy-loaded')); }, { timeout: 60000 }, HERO);
    await new Promise((r) => setTimeout(r, 400));
    const f2 = SHOTS + '/' + label + '-' + prof + '-slide.png';
    await p.screenshot({ path: f2 });
    await b.close();
    const a = PNG.sync.read(fs.readFileSync(f1)), c = PNG.sync.read(fs.readFileSync(f2));
    let sum = 0, n = 0, big = 0;
    const y0 = Math.round(a.height * (mobile ? 0.12 : 0.2)), y1 = Math.round(a.height * 0.6);
    for (let y = y0; y < y1; y++) for (let x = 0; x < a.width; x++) {
      const i = (y * a.width + x) * 4;
      const d = (Math.abs(a.data[i] - c.data[i]) + Math.abs(a.data[i + 1] - c.data[i + 1]) + Math.abs(a.data[i + 2] - c.data[i + 2])) / 3;
      sum += d; n++; if (d > 24) big++;
    }
    console.log(label + ' ' + prof + ': mean abs diff ' + (sum / n).toFixed(2) + ' / 255, pixels differing by more than 24: ' + (100 * big / n).toFixed(1) + '% (rows ' + y0 + '-' + y1 + ')');
  }
})();
