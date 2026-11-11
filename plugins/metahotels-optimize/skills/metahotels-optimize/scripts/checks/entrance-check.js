// usage: node entrance-check.js <url> [desktop|mobile] [--rules=rules.json] [--slow] [--label=name]
// Follows the entrance animation of the header row and of the animated elements in the first section of the page:
// samples visibility and opacity every 50 ms from navigation start and prints, per element, when it first became
// visible, when it reached full opacity and whether its opacity ever dropped again (= the animation played twice).
// --slow = Slow 4G + 4x CPU, where the gap between first paint and Elementor's JS is seconds long.
// --rules applies abhtml.js-style rules to the document first.
const puppeteer = require('puppeteer-core');
const SHOTS = require('./_lib').shots();
const fs = require('fs');
const args = process.argv.slice(2);
const [url, prof] = args.filter((a) => !a.startsWith('--'));
const opt = (n) => { const a = args.find((x) => x.startsWith('--' + n + '=')); return a ? a.slice(n.length + 3) : null; };
const mobile = prof === 'mobile';
const slow = args.includes('--slow');
const rules = opt('rules') ? JSON.parse(fs.readFileSync(opt('rules'), 'utf8')) : null;
const label = (opt('label') || (rules ? 'variant' : 'live')) + '-' + (mobile ? 'm' : 'd') + (slow ? '-slow' : '');
const UA = mobile
  ? 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1'
  : 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
(async () => {
  let html = await (await fetch(url, { headers: { 'user-agent': UA } })).text();
  for (const r of rules || []) {
    const before = html;
    html = r.regex ? html.replace(new RegExp(r.find, r.flags || ''), () => r.replace) : html.split(r.find).join(r.replace);
    if (html === before) { console.error('RULE DID NOT MATCH: ' + r.find.slice(0, 80)); process.exit(2); }
  }
  const b = await puppeteer.launch({ executablePath: require('./_lib').CHROME, headless: 'new' });
  const p = await b.newPage();
  await p.setViewport(mobile ? { width: 390, height: 844, isMobile: true, hasTouch: true, deviceScaleFactor: 2 } : { width: 1440, height: 900 });
  await p.setUserAgent(UA);
  const errs = [];
  p.on('pageerror', (e) => errs.push(String(e.message).slice(0, 100)));
  const c = await p.target().createCDPSession();
  await c.send('Network.enable');
  await c.send('Network.setCacheDisabled', { cacheDisabled: true });
  if (slow) {
    await c.send('Network.emulateNetworkConditions', { offline: false, latency: 150, downloadThroughput: (1.6 * 1024 * 1024) / 8, uploadThroughput: (750 * 1024) / 8 });
    await c.send('Emulation.setCPUThrottlingRate', { rate: 4 });
  }
  await p.setRequestInterception(true);
  let served = false;
  p.on('request', (rq) => {
    if (!served && rq.isNavigationRequest() && rq.frame() === p.mainFrame()) { served = true; rq.respond({ status: 200, contentType: 'text/html; charset=UTF-8', body: html }); } else rq.continue();
  });
  await p.evaluateOnNewDocument(() => {
    window.__ent = { samples: {}, fcp: null, lcp: [], init: null };
    new PerformanceObserver((l) => { for (const e of l.getEntries()) if (e.name === 'first-contentful-paint') window.__ent.fcp = Math.round(e.startTime); }).observe({ type: 'paint', buffered: true });
    new PerformanceObserver((l) => { for (const e of l.getEntries()) window.__ent.lcp.push([Math.round(e.startTime), e.element ? e.element.tagName + '.' + String(e.element.className).slice(0, 30) : '?']); }).observe({ type: 'largest-contentful-paint', buffered: true });
    const sel = '.elementor-location-header [data-settings*=\'animation":"\'], [data-elementor-type="wp-page"] > .e-parent:first-child [data-settings*=\'animation":"\'], [data-elementor-type="wp-page"] > .e-parent:first-child[data-settings*=\'animation":"\']';
    setInterval(() => {
      const t = Math.round(performance.now());
      if (window.__ent.init === null && window.elementorFrontend && document.querySelector('.animated')) window.__ent.init = t;
      document.querySelectorAll(sel).forEach((e) => {
        const cs = getComputedStyle(e), id = e.getAttribute('data-id');
        const r = e.getBoundingClientRect();
        (window.__ent.samples[id] = window.__ent.samples[id] || []).push([t, cs.visibility === 'hidden' ? -1 : +(+cs.opacity).toFixed(2), Math.round(r.top), e.className.includes('elementor-invisible') ? 1 : 0]);
      });
    }, 50);
  });
  await p.goto(url, { waitUntil: 'load', timeout: 180000 }).catch((e) => errs.push('goto: ' + e.message.slice(0, 60)));
  await sleep(slow ? 6000 : 4000);
  const d = await p.evaluate(() => window.__ent);
  await p.screenshot({ path: SHOTS + '/entrance-' + label + '.png' });
  console.log(`== ${label} | FCP ${d.fcp} ms | LCP ${d.lcp.map((x) => x[0] + ' ' + x[1]).join(' -> ')} | first .animated seen at ${d.init} ms | errors ${JSON.stringify(errs)}`);
  for (const [id, s] of Object.entries(d.samples)) {
    const firstVis = s.find((x) => x[1] > 0), full = s.find((x) => x[1] >= 1);
    let drops = 0, peak = -1;
    for (const x of s) { if (x[1] > peak) peak = x[1]; else if (peak >= 0.5 && x[1] < peak - 0.3) { drops++; peak = x[1]; } }
    const classGone = s.find((x) => x[3] === 0);
    console.log(`   ${id.padEnd(9)} first visible ${firstVis ? firstVis[0] : 'never'} ms | full opacity ${full ? full[0] : 'never'} ms | elementor-invisible removed ${classGone ? classGone[0] : 'never'} ms | opacity fell back ${drops}x | final ${s[s.length - 1][1]} top ${s[s.length - 1][2]}`);
  }
  await b.close();
})();
