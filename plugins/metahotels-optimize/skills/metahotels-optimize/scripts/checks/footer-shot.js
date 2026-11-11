// usage: node footer-shot.js <label> <url> [<url> ...]
// Screenshot of the footer logo widget (OVA logo) on a phone and on desktop, with the natural size of each of its
// images (0x0 = the file did not load). Used before and after pointing the mobile/sticky logo at a file that exists.
const puppeteer = require('puppeteer-core');
const SHOTS = require('./_lib').shots();
const [label, ...urls] = process.argv.slice(2);
(async () => {
  const b = await puppeteer.launch({ executablePath: require('./_lib').CHROME, headless: 'new' });
  for (const url of urls) {
    for (const mobile of [true, false]) {
      const p = await b.newPage();
      await p.setViewport(mobile ? { width: 390, height: 844, isMobile: true, hasTouch: true, deviceScaleFactor: 2 } : { width: 1440, height: 900 });
      await p.setRequestInterception(true);
      p.on('request', (r) => (/directchat|recaptcha|mirai|wonderpush|brevo/.test(r.url()) ? r.abort() : r.continue()));
      const failed = [];
      p.on('response', (r) => { if (r.status() >= 400 && /logo/i.test(r.url())) failed.push(r.status() + ' ' + r.url().split('/').pop()); });
      await p.goto(url, { waitUntil: 'load', timeout: 120000 }).catch(() => {});
      const info = await p.evaluate(async () => {
        const w = document.querySelector('.elementor-location-footer .elementor-widget-ova_logo');
        if (!w) return null;
        w.scrollIntoView({ block: 'center' });
        await new Promise((r) => setTimeout(r, 1500));
        return [...w.querySelectorAll('img')].map((i) => {
          const r = i.getBoundingClientRect();
          return (i.className || '-') + ' ' + i.currentSrc.split('/').pop() + ' natural ' + i.naturalWidth + 'x' + i.naturalHeight + ' shown ' + Math.round(r.width) + 'x' + Math.round(r.height);
        });
      });
      const name = label + '-' + url.replace(/https?:\/\/[^/]+/, '').replace(/[^a-z0-9]+/gi, '_') + (mobile ? '-m' : '-d') + '.png';
      const el = await p.$('.elementor-location-footer .elementor-widget-ova_logo');
      const box = el ? await el.boundingBox() : null;
      if (box && box.width > 0 && box.height > 0) await el.screenshot({ path: SHOTS + '/' + name });
      console.log((mobile ? 'mobile ' : 'desktop') + ' ' + url + ' | ' + (info ? info.join(' | ') : 'no ova_logo in footer') + ' | failed: ' + JSON.stringify(failed) + (box && box.width > 0 ? ' | ' + name : ' | widget not displayed'));
      await p.close();
    }
  }
  await b.close();
})();
