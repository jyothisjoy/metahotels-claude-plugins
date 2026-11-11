// usage: node popup-open.js <url> <label> [--mobile] [--nocache] [--wait=ms] [--rules=rules.json]
// What happens when the page-load-timer popup opens with no visitor input: does the page scroll by itself, which
// element takes focus, which stylesheets arrive only then, how much layout shift, how many image requests follow.
// Screenshots: <label>-before.png (2 s before the popup is due) and <label>-after.png (end).
const puppeteer = require('puppeteer-core');
const SHOTS = require('./_lib').shots();
const fs = require('fs');
const args = process.argv.slice(2);
const [url, label] = args.filter((a) => !a.startsWith('--'));
const mobile = args.includes('--mobile');
const opt = (n) => { const a = args.find((x) => x.startsWith('--' + n + '=')); return a ? a.slice(n.length + 3) : null; };
const wait = +(opt('wait') || 45000);
const UA = mobile
  ? 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1'
  : 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36';
(async () => {
  let html = null;
  if (opt('rules')) {
    html = await (await fetch(url, { headers: { 'user-agent': UA } })).text();
    for (const r of JSON.parse(fs.readFileSync(opt('rules'), 'utf8'))) {
      const before = html;
      html = r.regex ? html.replace(new RegExp(r.find, r.flags || ''), () => r.replace) : html.split(r.find).join(r.replace);
      if (html === before) { console.error('RULE DID NOT MATCH: ' + r.find.slice(0, 80)); process.exit(2); }
    }
  }
  const b = await puppeteer.launch({ executablePath: require('./_lib').CHROME, headless: 'new' });
  const p = await b.newPage();
  await p.setViewport(mobile ? { width: 390, height: 844, isMobile: true, hasTouch: true, deviceScaleFactor: 2 } : { width: 1440, height: 900 });
  await p.setUserAgent(UA);
  const c = await p.target().createCDPSession();
  await c.send('Network.enable');
  if (args.includes('--nocache')) await c.send('Network.setCacheDisabled', { cacheDisabled: true });
  let imgs = 0, bytes = 0;
  const imgAt = [];
  const t0 = Date.now();
  c.on('Network.requestWillBeSent', (e) => { if (e.type === 'Image') { imgs++; imgAt.push(Date.now() - t0); } });
  c.on('Network.loadingFinished', (e) => { bytes += e.encodedDataLength; });
  if (html) {
    await p.setRequestInterception(true);
    let served = false;
    p.on('request', (rq) => {
      if (!served && rq.isNavigationRequest() && rq.frame() === p.mainFrame()) { served = true; rq.respond({ status: 200, contentType: 'text/html; charset=UTF-8', body: html }); } else rq.continue();
    });
  }
  await p.evaluateOnNewDocument(() => {
    window.__ev = [];
    const log = (s) => window.__ev.push(Math.round(performance.now()) + ' ' + s);
    let lastY = 0, scrolling = false;
    addEventListener('scroll', () => { if (!scrolling) { scrolling = true; log('SCROLL starts at y=' + lastY); } lastY = Math.round(scrollY); }, true);
    addEventListener('scrollend', () => { scrolling = false; log('SCROLL ends at y=' + Math.round(scrollY)); }, true);
    addEventListener('focusin', (e) => { const t = e.target; const r = t.getBoundingClientRect(); log('FOCUS ' + t.tagName + (t.name ? '[name=' + t.name + ']' : '') + '.' + String(t.className).slice(0, 40) + ' top=' + Math.round(r.top) + ' position(of dialog)=' + (t.closest('.dialog-widget') ? getComputedStyle(t.closest('.dialog-widget')).position : 'n/a')); }, true);
    const of = HTMLElement.prototype.focus;
    HTMLElement.prototype.focus = function (o) { log('focus() called on ' + this.tagName + '.' + String(this.className).slice(0, 40) + ' preventScroll=' + !!(o && o.preventScroll)); return of.apply(this, arguments); };
    new MutationObserver((ms) => {
      for (const m of ms) for (const n of m.addedNodes) {
        if (n.nodeType !== 1) continue;
        if (n.tagName === 'LINK' && n.rel === 'stylesheet') { log('STYLESHEET added ' + (n.id || '') + ' ' + n.href.split('/').slice(-2).join('/').split('?')[0]); n.addEventListener('load', () => log('STYLESHEET loaded ' + (n.id || ''))); }
        if (n.classList && n.classList.contains('dialog-widget')) log('DIALOG node added, position=' + getComputedStyle(n).position + ' display=' + getComputedStyle(n).display);
      }
    }).observe(document, { childList: true, subtree: true });
    try {
      new PerformanceObserver((l) => { for (const e of l.getEntries()) if (!e.hadRecentInput && e.value >= 0.005) log('SHIFT ' + e.value.toFixed(4)); }).observe({ type: 'layout-shift', buffered: true });
    } catch (e) {}
  });
  await p.goto(url, { waitUntil: 'load', timeout: 120000 });
  const loadAt = Date.now() - t0;
  let shotBefore = false, opened = 0;
  const end = Date.now() + wait;
  while (Date.now() < end) {
    await new Promise((r) => setTimeout(r, 500));
    const st = await p.evaluate(() => {
      const d = document.querySelector('.elementor-popup-modal');
      return { open: !!(d && getComputedStyle(d).display !== 'none'), y: Math.round(scrollY) };
    }).catch(() => ({ open: false, y: 0 }));
    if (!shotBefore && Date.now() - t0 > loadAt + 3000) { await p.screenshot({ path: SHOTS + '/' + label + '-before.png' }); shotBefore = true; }
    if (st.open && !opened) opened = Date.now() - t0;
    if (opened && Date.now() - t0 > opened + 9000) break;
  }
  await p.screenshot({ path: SHOTS + '/' + label + '-after.png' });
  const r = await p.evaluate(() => ({ ev: window.__ev, y: Math.round(scrollY), h: document.documentElement.scrollHeight, smooth: getComputedStyle(document.documentElement).scrollBehavior }));
  console.log('== ' + label + ' | load ' + (loadAt / 1000).toFixed(1) + ' s | popup open at ' + (opened ? (opened / 1000).toFixed(1) + ' s' : 'NEVER') + ' | final scrollY ' + r.y + ' of ' + r.h + ' | html scroll-behavior ' + r.smooth);
  const before = opened ? imgAt.filter((t) => t < opened - 500).length : imgs;
  console.log('   image requests before the popup: ' + before + ', after: ' + (imgs - before) + ' | total transfer ' + Math.round(bytes / 1024) + ' KB');
  const cut = opened ? opened - 3000 : 0;
  for (const e of r.ev) { const t = +e.split(' ')[0]; if (/SCROLL|FOCUS|focus\(\)|DIALOG/.test(e) || (t > cut && /STYLESHEET|SHIFT/.test(e))) console.log('   ' + e.slice(0, 190)); }
  await b.close();
})();
