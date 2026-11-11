// Does the Asksuite chat (cdn.asksuite.com/infochat.js) render its bubble? Loads the page, waits for load + 3 s,
// moves the mouse and taps, waits --after ms (default 10000) and reports the Asksuite nodes and requests.
// Usage: node asksuite-check.js <url> [desktop|mobile] [--after=ms]
const puppeteer = require('puppeteer-core');
const { CHROME } = require('./_lib');

(async () => {
  const url = process.argv[2];
  const mobile = process.argv[3] === 'mobile';
  const after = +((process.argv.find((a) => a.startsWith('--after=')) || '--after=10000').split('=')[1]);
  const b = await puppeteer.launch({ executablePath: CHROME, headless: 'new' });
  const p = await b.newPage();
  await p.setViewport(mobile ? { width: 390, height: 844, isMobile: true, hasTouch: true } : { width: 1440, height: 900 });
  const reqs = [];
  p.on('request', (r) => { if (/asksuite/.test(r.url())) reqs.push(r.url().split('?')[0].slice(-60)); });
  await p.goto(url, { waitUntil: 'load', timeout: 90000 });
  await new Promise((r) => setTimeout(r, 3000));
  const before = reqs.length;
  await p.mouse.move(200, 300);
  await p.mouse.move(400, 500);
  if (mobile) { await p.touchscreen.tap(200, 400).catch(() => {}); }
  await p.evaluate(() => window.scrollBy(0, 50));
  await new Promise((r) => setTimeout(r, after));
  const state = await p.evaluate(() => {
    const sel = '.infochat_floatmain, .infochat_custommain, #chatbot, #chatbotmobile, iframe[src*="asksuite"], #botchatbotaskuite';
    return [...document.querySelectorAll(sel)].map((e) => {
      const r = e.getBoundingClientRect();
      const cs = getComputedStyle(e);
      return (e.id ? '#' + e.id : e.className.toString().split(' ')[0]) + ' ' + Math.round(r.width) + 'x' + Math.round(r.height) + ' ' + cs.display + '/' + cs.visibility;
    });
  });
  console.log(JSON.stringify({ mobile, requestsBefore: before, requestsAfter: reqs.length, reqs: [...new Set(reqs)].slice(0, 8), nodes: state }));
  await b.close();
})();
