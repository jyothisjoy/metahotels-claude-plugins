// usage: node interaction.js <url> [desktop|mobile] [--rules=rules.json] [--label=name]
// What loads before and after the visitor's first interaction (first written for Shams, 2026-10-13): chat widget, reCAPTCHA,
// booking engine, tags, hero video. Also reports JS errors, so a delayed script whose inline init was not delayed
// shows up here, and whether the chat widget really mounted after the interaction.
// --rules applies abhtml.js-style find/replace rules to the document first (test a change before it is live).
// Screenshots: interaction-<label>-<profile>-before.png / -after.png in ./shots.
const puppeteer = require('puppeteer-core');
const SHOTS = require('./_lib').shots();
const fs = require('fs');
const args = process.argv.slice(2);
const [url, prof] = args.filter((a) => !a.startsWith('--'));
const opt = (n) => { const a = args.find((x) => x.startsWith('--' + n + '=')); return a ? a.slice(n.length + 3) : null; };
const mobile = prof === 'mobile';
const label = (opt('label') || 'live') + '-' + (mobile ? 'mobile' : 'desktop');
const rules = opt('rules') ? JSON.parse(fs.readFileSync(opt('rules'), 'utf8')) : null;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const UA = mobile
  ? 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1'
  : 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36';
(async () => {
  let html = null;
  if (rules) {
    html = await (await fetch(url, { headers: { 'user-agent': UA } })).text();
    for (const r of rules) {
      const before = html;
      html = r.regex ? html.replace(new RegExp(r.find, r.flags || ''), () => r.replace) : html.split(r.find).join(r.replace);
      if (html === before) { console.error('RULE DID NOT MATCH: ' + r.find.slice(0, 80)); process.exit(2); }
    }
  }
  const b = await puppeteer.launch({ executablePath: require('./_lib').CHROME, headless: 'new' });
  const p = await b.newPage();
  await p.setViewport(mobile ? { width: 390, height: 844, isMobile: true, hasTouch: true } : { width: 1440, height: 900 });
  await p.setUserAgent(UA);
  const errs = [], reqs = [];
  p.on('pageerror', (e) => errs.push(String(e.message).slice(0, 120)));
  if (html) {
    await p.setRequestInterception(true);
    let served = false;
    p.on('request', (rq) => {
      reqs.push(rq.url());
      if (!served && rq.isNavigationRequest() && rq.frame() === p.mainFrame()) {
        served = true;
        rq.respond({ status: 200, contentType: 'text/html; charset=UTF-8', body: html });
      } else rq.continue();
    });
  } else p.on('request', (r) => reqs.push(r.url()));
  const groups = { chat: /hdr_chatbot/, recaptcha: /recaptcha/, mirai: /static\.mirai\.com\/core\/index\.js/, gtm: /googletagmanager/, clarity: /clarity\.ms/, youtube: /youtube\.com|ytimg\.com/, wistia: /wistia\.(com|net)/, iconFont: /elementskit\.woff|jkiticon\.woff|fa-solid-900\.woff/ };
  const count = () => Object.fromEntries(Object.entries(groups).map(([k, re]) => [k, reqs.filter((u) => re.test(u)).length]));
  const state = () => p.evaluate(() => ({
    chat: typeof window.DirectChat,
    grecaptcha: typeof window.grecaptcha,
    // The chat widget mounts its own host element(s) directly under <body>; Mirai's components are excluded.
    chatNodes: [...document.querySelectorAll('body *')].filter((e) => (e.shadowRoot || /directchat|dc-widget|hdr-chat/i.test((e.id || '') + ' ' + (e.className && e.className.baseVal === undefined ? e.className : ''))) && !e.closest('[data-mirai-component]')).length,
    finders: document.querySelectorAll('[data-mirai-component="finder"]').length,
    findersRendered: [...document.querySelectorAll('[data-mirai-component="finder"]')].filter((e) => e.children.length > 0).length,
    elementor: typeof window.elementorFrontend,
  }));
  const t0 = Date.now();
  await p.goto(url, { waitUntil: 'load', timeout: 120000 });
  const loadMs = Date.now() - t0;
  await sleep(9000);
  const before = count(), stBefore = await state(), total = reqs.length;
  await p.screenshot({ path: SHOTS + '/interaction-' + label + '-before.png' });
  if (mobile) await p.touchscreen.tap(200, 400); else await p.mouse.move(400, 500, { steps: 5 });
  await sleep(9000);
  const after = count(), stAfter = await state();
  await p.screenshot({ path: SHOTS + '/interaction-' + label + '-after.png' });
  console.log(label, JSON.stringify({ loadMs, requestsBeforeInput: total, beforeInput: before, stateBefore: stBefore, afterInput: after, stateAfter: stAfter, requestsAfterInput: reqs.length, errors: errs }));
  await b.close();
})();
