// usage: node chat-check.js <url> [desktop|mobile] [--label=name] [--after=ms]
// Does the chat widget load on the first interaction and mount? Loads the page, waits 3 s after load (well before
// the 15 s popup), records the nodes under <body>, taps or moves the mouse, waits 8 s and reports: chat script
// requests before and after, whether DirectChat exists (it is a top-level declaration, so it is tested by name,
// not on window), the nodes the widget added, and JS errors. Screenshots chat-<label>-before/after.png.
const puppeteer = require('puppeteer-core');
const SHOTS = require('./_lib').shots();
const args = process.argv.slice(2);
const [url, prof] = args.filter((a) => !a.startsWith('--'));
const mobile = prof === 'mobile';
const la = args.find((a) => a.startsWith('--label='));
const label = (la ? la.slice(8) : 'live') + (mobile ? '-m' : '-d');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const wa = args.find((a) => a.startsWith('--after='));
const after = wa ? +wa.slice(8) : 8000; // the chat script is 1.4 MB from a slow bucket: it can take 10 s or more to arrive
(async () => {
  const b = await puppeteer.launch({ executablePath: require('./_lib').CHROME, headless: 'new' });
  const p = await b.newPage();
  await p.setViewport(mobile ? { width: 390, height: 844, isMobile: true, hasTouch: true, deviceScaleFactor: 2 } : { width: 1440, height: 900 });
  if (mobile) await p.setUserAgent('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1');
  const chat = [], errs = [];
  p.on('request', (r) => { if (/hdr_chatbot/.test(r.url())) chat.push(r.url().split('/').pop().slice(0, 40)); });
  p.on('pageerror', (e) => errs.push(String(e.message).slice(0, 120)));
  const t0 = Date.now();
  await p.goto(url, { waitUntil: 'load', timeout: 120000 });
  const loadMs = Date.now() - t0;
  await sleep(3000);
  const before = chat.length;
  await p.evaluate(() => { window.__kids = new Set(document.body.children); });
  await p.screenshot({ path: SHOTS + '/chat-' + label + '-before.png' });
  if (mobile) await p.touchscreen.tap(200, 300); else await p.mouse.move(500, 400, { steps: 5 });
  await sleep(after);
  const st = await p.evaluate(() => {
    let dc = 'undefined';
    try { dc = eval('typeof DirectChat'); } catch (e) { dc = 'error ' + e.message; }
    const added = [...document.body.children].filter((e) => !window.__kids.has(e)).map((e) => {
      const r = e.getBoundingClientRect();
      const inner = e.shadowRoot ? e.shadowRoot.querySelectorAll('*').length : e.querySelectorAll('*').length;
      return e.tagName + (e.id ? '#' + e.id : '') + (typeof e.className === 'string' && e.className ? '.' + e.className.split(' ')[0] : '') + (e.shadowRoot ? ' shadow' : '') + ' nodes=' + inner + ' ' + Math.round(r.width) + 'x' + Math.round(r.height);
    });
    return { directChat: dc, added };
  });
  await p.screenshot({ path: SHOTS + '/chat-' + label + '-after.png' });
  console.log(label, JSON.stringify({ loadMs, chatRequestsBeforeInput: before, chatRequestsAfterInput: chat, ...st, errors: errs }));
  await b.close();
})();
