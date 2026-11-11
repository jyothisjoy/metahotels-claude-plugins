// usage: node simhtml.js <url> <rules.json> [--watch=regex] [--vary]
// Visual proof for an HTML-level change (preload tag, inline CSS, font override, rewritten snippet) BEFORE it is
// deployed: loads <url> normally and with the abhtml.js-style find/replace rules applied to the document, freezes
// animations/sliders, takes full-page screenshots on desktop and mobile and pixel-diffs them.
// 0 px difference + no new JS errors = the change is visually safe. --watch counts requests matching the regex in
// each run (e.g. --watch="jkiticon\.woff2" to prove a font is no longer downloaded).
// --vary: LiteSpeed Guest Mode sites: use the _lscache_vary cookie (from guest.vary.php) for the fetch and the
// browser, so the normal copy is shown and the guest copy's self-reload does not drop the rules (see abhtml.js).
// rules.json: [{"find": "literal or regex source", "regex": false, "flags": "s", "replace": "..."}]; every rule must match.
const puppeteer = require('puppeteer-core');
const fs = require('fs');
const path = require('path');
const { PNG } = require('pngjs');
const pixelmatch = require('pixelmatch');
const args = process.argv.slice(2);
const [url, rulesFile] = args.filter((a) => !a.startsWith('--'));
if (!url || !rulesFile) { console.error('usage: node simhtml.js <url> <rules.json> [--watch=regex]'); process.exit(1); }
const watchArg = args.find((a) => a.startsWith('--watch='));
const WATCH = watchArg ? new RegExp(watchArg.slice(8)) : null;
const rules = JSON.parse(fs.readFileSync(rulesFile, 'utf8'));
// Third parties that make screenshots non-deterministic (booking engines, chat, analytics, push). Extend per site.
const NOISE = /mirai|recaptcha|gstatic|googletagmanager|google-analytics|trustindex|thehotelsnetwork|hdr_chatbot|wonderpush|sibautomation|brevo\.com|connect\.facebook\.net|facebook\.com|clarity\.ms|youtube\.com|youtube-nocookie\.com|ytimg\.com|\.mp4/;
const outDir = path.join(process.env.PERF_RUNS || path.resolve('runs'), new URL(url).host, 'simhtml');
fs.mkdirSync(outDir, { recursive: true });
const UAS = {
  desktop: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36',
  mobile: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
};

const VARY_ON = args.includes('--vary');
async function getVary(ua) {
  const u = new URL(url);
  const r = await fetch(u.origin + '/wp-content/plugins/litespeed-cache/guest.vary.php', { method: 'POST', headers: { 'user-agent': ua } });
  const m = /_lscache_vary=([^;]+)/.exec(r.headers.get('set-cookie') || '');
  if (!m) { console.error('--vary: no _lscache_vary cookie from guest.vary.php'); process.exit(2); }
  return { name: '_lscache_vary', value: m[1], domain: u.hostname, path: '/' };
}
let VARY = null;

async function run(variant, vp, base) {
  let html = base;
  if (variant) for (const r of rules) {
    const before = html;
    html = r.regex ? html.replace(new RegExp(r.find, r.flags || ''), () => r.replace) : html.split(r.find).join(r.replace);
    if (html === before) { console.error('RULE DID NOT MATCH: ' + r.find.slice(0, 80)); process.exit(2); }
  }
  const b = await puppeteer.launch({ executablePath: require('./checks/_lib').CHROME, headless: 'new' });
  const p = await b.newPage();
  await p.setViewport(vp === 'mobile' ? { width: 390, height: 844, isMobile: true, hasTouch: true } : { width: 1440, height: 900 });
  await p.setUserAgent(UAS[vp]);
  await p.setRequestInterception(true);
  let watched = 0, served = false;
  const errs = [];
  p.on('request', (r) => {
    if (WATCH && WATCH.test(r.url())) watched++;
    if (!served && r.isNavigationRequest() && r.frame() === p.mainFrame()) { served = true; r.respond({ status: 200, contentType: 'text/html; charset=UTF-8', body: html }); }
    else if (NOISE.test(r.url())) r.abort();
    else r.continue();
  });
  p.on('pageerror', (e) => errs.push(String((e && e.message) || e).slice(0, 160)));
  if (VARY) await p.setCookie(VARY);
  await p.goto(url, { waitUntil: 'load', timeout: 90000 });
  await p.addStyleTag({ content: '*{animation:none!important;transition:none!important} .elementor-invisible{visibility:visible!important}' });
  // scroll through once so lazy images and lazy backgrounds are in their final state in both runs
  await p.evaluate(async () => { for (let y = 0; y < document.body.scrollHeight; y += 500) { window.scrollTo(0, y); await new Promise((r) => setTimeout(r, 120)); } });
  await new Promise((r) => setTimeout(r, 3000));
  await p.evaluate(() => {
    document.querySelectorAll('.swiper').forEach((s) => { if (s.swiper) { s.swiper.autoplay && s.swiper.autoplay.stop(); s.swiper.slideTo(0, 0); } });
    window.scrollTo(0, 0);
  });
  await new Promise((r) => setTimeout(r, 1500));
  const shot = path.join(outDir, `${vp}-${variant ? 'variant' : 'normal'}.png`);
  await p.screenshot({ path: shot, fullPage: true });
  await b.close();
  return { watched, errs, shot };
}

(async () => {
  for (const vp of ['desktop', 'mobile']) {
    VARY = VARY_ON ? await getVary(UAS[vp]) : null;
    const hdr = { 'user-agent': UAS[vp] };
    if (VARY) hdr.cookie = VARY.name + '=' + VARY.value;
    const base = await (await fetch(url, { headers: hdr })).text();
    const a = await run(false, vp, base);
    const bb = await run(true, vp, base);
    const A = PNG.sync.read(fs.readFileSync(a.shot));
    const B = PNG.sync.read(fs.readFileSync(bb.shot));
    let diff = `page height differs (${A.height} vs ${B.height})`;
    if (A.width === B.width && A.height === B.height) {
      const d = new PNG({ width: A.width, height: A.height });
      const n = pixelmatch(A.data, B.data, d.data, A.width, A.height, { threshold: 0.15 });
      fs.writeFileSync(path.join(outDir, `${vp}-diff.png`), PNG.sync.write(d));
      diff = `${n} px differ (${((100 * n) / (A.width * A.height)).toFixed(3)}%)`;
    }
    console.log(vp, WATCH ? `| watched requests normal/variant: ${a.watched}/${bb.watched}` : '', '| errors normal:', JSON.stringify(a.errs), 'variant:', JSON.stringify(bb.errs), '|', diff);
  }
})();
