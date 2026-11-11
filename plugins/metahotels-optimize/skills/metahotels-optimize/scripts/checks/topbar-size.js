// usage (from the site folder): node <skill>/scripts/checks/topbar-size.js <url> [--rules=rules.json] [--widths=1025,1280,1440] [--links=<selector>]
// The header's first container (the sticky top bar on these sites) holds a heading, a Mirai finder and the My
// booking / Log in links (--links, else site.json selectors.topbarLinks, else every non-finder Mirai component). Until Mirai renders, the finder is 0x0 and the links are icon-only, so the bar
// grows and the heading moves sideways. For each viewport width this prints the rect of the bar, the heading, the
// finder and the links before Mirai has rendered and after it has settled, and the layout shift in between.
// With --rules the same is measured with a CSS change applied to the HTML: "settled" must equal the run without it.
const puppeteer = require('puppeteer-core');
const fs = require('fs');
const args = process.argv.slice(2);
const url = args.find((a) => !a.startsWith('--'));
const opt = (n) => { const a = args.find((x) => x.startsWith('--' + n + '=')); return a ? a.slice(n.length + 3) : null; };
const widths = (opt('widths') || '768,1024,1025,1100,1199,1200,1280,1366,1440,1920').split(',').map(Number);
const rules = opt('rules') ? JSON.parse(fs.readFileSync(opt('rules'), 'utf8')) : null;
const LINKS = opt('links') || require('./_lib').sel('topbarLinks', '[data-mirai-component]:not([data-mirai-component="finder"])');
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
(async () => {
  let html = null;
  if (rules) {
    html = await (await fetch(url, { headers: { 'user-agent': UA, ...(process.env.LS_VARY ? { cookie: '_lscache_vary=' + process.env.LS_VARY } : {}) } })).text();
    for (const r of rules) {
      const before = html;
      html = r.regex ? html.replace(new RegExp(r.find, r.flags || ''), () => r.replace) : html.split(r.find).join(r.replace);
      if (html === before) { console.error('RULE DID NOT MATCH: ' + r.find.slice(0, 80)); process.exit(2); }
    }
  }
  const b = await puppeteer.launch({ executablePath: require('./_lib').CHROME, headless: 'new' });
  for (const w of widths) {
    const p = await b.newPage();
    await p.setViewport({ width: w, height: 900 });
    await p.setUserAgent(UA);
    await p.setRequestInterception(true);
    let served = false;
    p.on('request', (rq) => {
      if (html && !served && rq.isNavigationRequest() && rq.frame() === p.mainFrame()) { served = true; return rq.respond({ status: 200, contentType: 'text/html; charset=UTF-8', body: html }); }
      if (/directchat|recaptcha|wonderpush/.test(rq.url())) return rq.abort();
      rq.continue();
    });
    await p.evaluateOnNewDocument(() => {
      window.__cls = 0; window.__shifts = [];
      new PerformanceObserver((l) => { for (const e of l.getEntries()) if (!e.hadRecentInput) { window.__cls += e.value; window.__shifts.push([Math.round(e.startTime), +e.value.toFixed(4)]); } }).observe({ type: 'layout-shift', buffered: true });
    });
    const rects = () => p.evaluate((LINKS) => {
      const bar = document.querySelector('.elementor-location-header > .elementor-element');
      const q = (s) => { const e = bar.querySelector(s); if (!e) return 'none'; const r = e.getBoundingClientRect(); return Math.round(r.left) + ',' + Math.round(r.top) + ' ' + Math.round(r.width) + 'x' + Math.round(r.height); };
      const r = bar.getBoundingClientRect();
      return { bar: Math.round(r.width) + 'x' + Math.round(r.height) + (getComputedStyle(bar).display === 'none' ? ' HIDDEN' : ''), heading: q('.elementor-widget-heading'), finder: q('[data-mirai-component="finder"]'), links: q(LINKS), rendered: !!(bar.querySelector('[data-mirai-component="finder"]') || {}).childElementCount };
    }, LINKS);
    // LiteSpeed Guest Mode: LS_VARY=<_lscache_vary value> measures the normal copy instead of the guest copy.
    if (process.env.LS_VARY) await p.setCookie({ name: '_lscache_vary', value: process.env.LS_VARY, domain: new URL(url).hostname, path: '/' });
    await p.goto(url, { waitUntil: 'domcontentloaded', timeout: 120000 }).catch(() => {});
    const before = await rects();
    await p.waitForFunction(() => { const f = document.querySelector('.elementor-location-header [data-mirai-component="finder"]'); return f && f.childElementCount > 0; }, { timeout: 60000 }).catch(() => {});
    await sleep(7000);
    const after = await rects();
    const cls = await p.evaluate(() => ({ cls: +window.__cls.toFixed(4), n: window.__shifts.length }));
    console.log(String(w).padStart(5) + ' | before bar ' + before.bar + ' heading ' + before.heading + ' finder ' + before.finder + ' links ' + before.links);
    console.log('      | settled bar ' + after.bar + ' heading ' + after.heading + ' finder ' + after.finder + ' links ' + after.links + ' | rendered ' + after.rendered + ' | CLS ' + cls.cls + ' in ' + cls.n + ' shifts');
    await p.close();
  }
  await b.close();
})();
