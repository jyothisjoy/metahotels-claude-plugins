// usage: node recaptcha-lazy.js <url> [desktop|mobile] [waitMs]
// Checks metahotels-core's "Load reCAPTCHA only when a form is shown": counts reCAPTCHA requests at load, after
// the first interaction, and once the page-load popup (30 s) with the Brevo form has opened. Submits nothing.
const puppeteer = require('puppeteer-core');
const [url, prof, waitArg] = process.argv.slice(2);
const mobile = prof === 'mobile';
const wait = +(waitArg || 36000);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
(async () => {
  const b = await puppeteer.launch({ executablePath: require('./_lib').CHROME, headless: 'new' });
  const p = await b.newPage();
  if (mobile) {
    await p.setViewport({ width: 390, height: 844, isMobile: true, hasTouch: true });
    await p.setUserAgent('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1');
  } else await p.setViewport({ width: 1440, height: 900 });
  const errs = [], rc = [];
  p.on('pageerror', (e) => errs.push(String(e.message).slice(0, 120)));
  p.on('request', (r) => { if (/recaptcha/.test(r.url())) rc.push(r.url().split('?')[0].split('/').slice(2, 6).join('/')); });
  const state = () => p.evaluate(() => {
    const m = document.querySelector('.elementor-popup-modal');
    const open = !!m && getComputedStyle(m).display !== 'none';
    const forms = [...document.querySelectorAll('form')].filter((f) => f.getBoundingClientRect().width > 0).length;
    return 'popupOpen=' + open + ' visibleForms=' + forms + ' grecaptcha=' + typeof window.grecaptcha + ' execute=' + (window.grecaptcha ? typeof window.grecaptcha.execute : '-') + ' badge=' + document.querySelectorAll('.grecaptcha-badge').length;
  });
  await p.goto(url, { waitUntil: 'load', timeout: 120000 });
  await sleep(6000);
  const atLoad = rc.length + ' req | ' + (await state());
  if (mobile) await p.touchscreen.tap(200, 300); else await p.mouse.move(400, 500, { steps: 5 });
  await sleep(4000);
  const afterInput = rc.length + ' req | ' + (await state());
  await sleep(wait - 10000);
  const afterPopup = rc.length + ' req | ' + (await state());
  // focus the first field of the popup form: the SDK must be there (or arrive) before a visitor can submit
  const focused = await p.evaluate(() => { const i = document.querySelector('.elementor-popup-modal form input:not([type=hidden])'); if (!i) return false; i.focus(); i.dispatchEvent(new Event('focusin', { bubbles: true })); return true; });
  await sleep(4000);
  const afterFocus = rc.length + ' req | ' + (await state());
  console.log(mobile ? 'mobile' : 'desktop', JSON.stringify({ atLoad, afterInput, afterPopup, fieldFocused: focused, afterFocus, hosts: [...new Set(rc)].slice(0, 4), errors: errs }));
  await b.close();
})();
