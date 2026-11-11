// usage: node probe.js <url> <desktop|mobile> <rules.json|-> "<js expression>" [--wait=ms] [--scroll=px]
// Loads the page (optionally with abhtml.js-style rules applied to the document), waits, optionally scrolls,
// and prints the JSON result of the expression evaluated in the page. For one-off "what is the state of X" checks.
const puppeteer = require('puppeteer-core');
const fs = require('fs');
const args = process.argv.slice(2);
const [url, prof, rulesFile, expr] = args.filter((a) => !a.startsWith('--'));
const opt = (n) => { const a = args.find((x) => x.startsWith('--' + n + '=')); return a ? a.slice(n.length + 3) : null; };
const mobile = prof === 'mobile';
const UA = mobile
  ? 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1'
  : 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
(async () => {
  let html = null;
  if (rulesFile && rulesFile !== '-') {
    html = await (await fetch(url, { headers: { 'user-agent': UA } })).text();
    for (const r of JSON.parse(fs.readFileSync(rulesFile, 'utf8'))) {
      const before = html;
      html = r.regex ? html.replace(new RegExp(r.find, r.flags || ''), () => r.replace) : html.split(r.find).join(r.replace);
      if (html === before) { console.error('RULE DID NOT MATCH: ' + r.find.slice(0, 80)); process.exit(2); }
    }
  }
  const b = await puppeteer.launch({ executablePath: require('./_lib').CHROME, headless: 'new' });
  const p = await b.newPage();
  await p.setViewport(mobile ? { width: 390, height: 844, isMobile: true, hasTouch: true, deviceScaleFactor: 2 } : { width: 1440, height: 900 });
  await p.setUserAgent(UA);
  const errs = [];
  p.on('pageerror', (e) => errs.push(String(e.message).slice(0, 100)));
  if (html) {
    await p.setRequestInterception(true);
    let served = false;
    p.on('request', (rq) => {
      if (!served && rq.isNavigationRequest() && rq.frame() === p.mainFrame()) { served = true; rq.respond({ status: 200, contentType: 'text/html; charset=UTF-8', body: html }); } else rq.continue();
    });
  }
  await p.goto(url, { waitUntil: 'load', timeout: 120000 });
  await sleep(+(opt('wait') || 4000));
  if (opt('scroll')) { await p.evaluate((y) => window.scrollTo(0, y), +opt('scroll')); await sleep(2500); }
  const out = await p.evaluate(expr);
  console.log(JSON.stringify(out, null, 1), errs.length ? 'ERRORS ' + JSON.stringify(errs) : '');
  if (opt('shot')) await p.screenshot({ path: opt('shot') });
  await b.close();
})();
