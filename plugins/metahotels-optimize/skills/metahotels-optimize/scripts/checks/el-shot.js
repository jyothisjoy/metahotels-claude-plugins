// usage: node el-shot.js <label> <url> <css-selector> [--wait=ms]
// Screenshot of one element on desktop (1440) and on a phone (390), after scrolling it into view and waiting.
// Writes el-<label>-d.png and el-<label>-m.png and prints the element's size and the requests that failed.
// Used for before/after pairs of a single section (compare the pairs with shamshotels/tests/diffbox.js).
const puppeteer = require('puppeteer-core');
const SHOTS = require('./_lib').shots();
const args = process.argv.slice(2);
const [label, url, selector] = args.filter((a) => !a.startsWith('--'));
const w = args.find((a) => a.startsWith('--wait='));
const wait = w ? +w.slice(7) : 3000;
(async () => {
  const b = await puppeteer.launch({ executablePath: require('./_lib').CHROME, headless: 'new' });
  for (const mobile of [false, true]) {
    const p = await b.newPage();
    await p.setViewport(mobile ? { width: 390, height: 844, isMobile: true, hasTouch: true, deviceScaleFactor: 2 } : { width: 1440, height: 900 });
    await p.setRequestInterception(true);
    p.on('request', (r) => (/directchat|recaptcha|wonderpush/.test(r.url()) ? r.abort() : r.continue()));
    const failed = [];
    p.on('response', (r) => { if (r.status() >= 400) failed.push(r.status() + ' ' + r.url().split('/').pop().slice(0, 50)); });
    await p.goto(url, { waitUntil: 'load', timeout: 120000 }).catch(() => {});
    // No animation, popup or cookie layer in the picture.
    await p.addStyleTag({ content: '*{animation:none!important;transition:none!important}.elementor-invisible{visibility:visible!important}.dialog-widget,[data-mirai-component="cookieBanner"],.be-mobile{display:none!important}' });
    const el = await p.$(selector);
    if (!el) { console.log((mobile ? 'mobile ' : 'desktop') + ' selector not found'); await p.close(); continue; }
    await el.evaluate((e) => e.scrollIntoView({ block: 'center' }));
    await new Promise((r) => setTimeout(r, wait));
    const box = await el.boundingBox();
    const name = 'el-' + label + (mobile ? '-m' : '-d') + '.png';
    await el.screenshot({ path: SHOTS + '/' + name });
    console.log((mobile ? 'mobile ' : 'desktop') + ' ' + Math.round(box.width) + 'x' + Math.round(box.height) + ' | failed: ' + JSON.stringify(failed) + ' | ' + name);
    await p.close();
  }
  await b.close();
})();
