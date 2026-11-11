// usage (from the site folder): node <skill>/scripts/checks/finder-size.js <url> [rules.json] [--bar=<sel>] [--widget=<sel>] [--heading=<sel>]
// Settled size of a Mirai finder's wrapper widget and of the bar holding it at several viewport widths, before Mirai
// renders and after (rules: abhtml.js format, applied to the live HTML). Used to choose the reserved size for the
// wrapper (pattern "finder CLS"): with the reserve rules applied, "after" must equal the run without them.
// Selectors: --bar/--widget/--heading, else site.json selectors.finderBar / finderWidget / finderHeading, else the
// first header container, the first HTML widget holding a finder, and the first heading in that bar.
// topbar-size.js is the newer, more general version (layout shift per width); this one is quicker.
const puppeteer = require('puppeteer-core');
const url = process.argv[2];
const fs = require('fs');
const { sel } = require('./_lib');
const arg = (n) => { const a = process.argv.find((x) => x.startsWith('--' + n + '=')); return a ? a.slice(n.length + 3) : null; };
const rulesFile = process.argv.slice(3).find((a) => !a.startsWith('--'));
const rules = rulesFile ? JSON.parse(fs.readFileSync(rulesFile, 'utf8')) : null;
const SEL = {
  bar: arg('bar') || sel('finderBar', '.elementor-location-header > .elementor-element'),
  widget: arg('widget') || sel('finderWidget', '.elementor-widget-html:has([data-mirai-component="finder"])'),
  heading: arg('heading') || sel('finderHeading', '.elementor-location-header .elementor-widget-heading'),
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
(async () => {
  const b = await puppeteer.launch({ executablePath: require('./_lib').CHROME, headless: 'new' });
  for (const w of [768, 900, 1024, 1025, 1200, 1366, 1440, 1920]) {
    const p = await b.newPage();
    await p.setViewport({ width: w, height: 900 });
    const read = () => p.evaluate((SEL) => {
      const box = (sel) => { const e = [...document.querySelectorAll(sel)].find((x) => !x.closest('.elementor-sticky__spacer') && !x.classList.contains('elementor-sticky__spacer')); if (!e) return 'none'; const r = e.getBoundingClientRect(); return Math.round(r.width) + 'x' + Math.round(r.height); };
      return 'bar ' + box(SEL.bar) + ' widget ' + box(SEL.widget) + ' finder ' + box(SEL.widget + ' [data-mirai-component="finder"]') + ' heading ' + box(SEL.heading);
    }, SEL);
    if (rules) {
      let html = await (await fetch(url, { headers: { 'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36' } })).text();
      for (const r of rules) { const before = html; html = r.regex ? html.replace(new RegExp(r.find, r.flags || ''), () => r.replace) : html.split(r.find).join(r.replace); if (html === before) { console.error('RULE DID NOT MATCH'); process.exit(2); } }
      await p.setRequestInterception(true);
      let served = false;
      p.on('request', (rq) => { if (!served && rq.isNavigationRequest() && rq.frame() === p.mainFrame()) { served = true; rq.respond({ status: 200, contentType: 'text/html; charset=UTF-8', body: html }); } else rq.continue(); });
    }
    await p.goto(url, { waitUntil: 'domcontentloaded', timeout: 120000 });
    await sleep(1500);
    const before = await read();
    await p.waitForFunction(() => document.readyState === 'complete', { timeout: 120000 });
    await sleep(11000);
    console.log(String(w).padStart(5) + '  before: ' + before + '\n       after:  ' + (await read()));
    await p.close();
  }
  await b.close();
})();
