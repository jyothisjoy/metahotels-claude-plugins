// usage: node simblock.js <url> <patterns.txt>
// Proves a dequeue is safe BEFORE writing/uploading a plugin: loads <url> twice (normal, and with every request
// matching a regex in patterns.txt aborted), freezes animations/sliders, takes full-page screenshots on desktop
// and mobile, and pixel-diffs them. 0 px difference + no new JS errors = safe to dequeue those handles.
// Tip: append ?LSCWP_CTRL=before_optm to the URL on LiteSpeed sites so asset URLs are the original (unminified) ones.
// patterns.txt: one JS regex per line, e.g.  gum-elementor-addon\/+js\/
const puppeteer = require('puppeteer-core');
const fs = require('fs');
const path = require('path');
const { PNG } = require('pngjs');
const pixelmatch = require('pixelmatch');
const [url, patFile] = process.argv.slice(2);
if (!url || !patFile) { console.error('usage: node simblock.js <url> <patterns.txt>'); process.exit(1); }
const BLOCK = fs.readFileSync(patFile, 'utf8').split(/\r?\n/).map((l) => l.trim()).filter((l) => l && !l.startsWith('#')).map((l) => new RegExp(l));
// Third parties that make screenshots non-deterministic (booking engines, chat, analytics, reviews). Extend per site.
const NOISE = /mirai|recaptcha|gstatic|googletagmanager|google-analytics|trustindex|thehotelsnetwork|\.mp4/;
const outDir = path.join(process.env.PERF_RUNS || path.resolve('runs'), new URL(url).host, 'simblock');
fs.mkdirSync(outDir, { recursive: true });

async function run(block, vp) {
  const b = await puppeteer.launch({ executablePath: require('./checks/_lib').CHROME, headless: 'new' });
  const p = await b.newPage();
  if (vp === 'mobile') {
    await p.setViewport({ width: 390, height: 844, isMobile: true, hasTouch: true });
    await p.setUserAgent('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1');
  } else await p.setViewport({ width: 1440, height: 900 });
  await p.setRequestInterception(true);
  let blocked = 0;
  const errs = [];
  p.on('request', (r) => {
    if (block && BLOCK.some((re) => re.test(r.url()))) { blocked++; r.abort(); }
    else if (NOISE.test(r.url())) r.abort();
    else r.continue();
  });
  p.on('pageerror', (e) => errs.push(String((e && e.message) || e).slice(0, 160)));
  await p.goto(url, { waitUntil: 'load', timeout: 90000 });
  await p.addStyleTag({ content: '*{animation:none!important;transition:none!important} .elementor-invisible{visibility:visible!important}' });
  await new Promise((r) => setTimeout(r, 3000));
  await p.evaluate(() => {
    document.querySelectorAll('.swiper').forEach((s) => { if (s.swiper) { s.swiper.autoplay && s.swiper.autoplay.stop(); s.swiper.slideTo(0, 0); } });
    window.scrollTo(0, 0);
  });
  await new Promise((r) => setTimeout(r, 1000));
  const shot = path.join(outDir, `${vp}-${block ? 'blocked' : 'normal'}.png`);
  await p.screenshot({ path: shot, fullPage: true });
  await b.close();
  return { blocked, errs, shot };
}

(async () => {
  for (const vp of ['desktop', 'mobile']) {
    const a = await run(false, vp);
    const bb = await run(true, vp);
    const A = PNG.sync.read(fs.readFileSync(a.shot));
    const B = PNG.sync.read(fs.readFileSync(bb.shot));
    let diff = `page height differs (${A.height} vs ${B.height})`;
    if (A.width === B.width && A.height === B.height) {
      const d = new PNG({ width: A.width, height: A.height });
      const n = pixelmatch(A.data, B.data, d.data, A.width, A.height, { threshold: 0.15 });
      fs.writeFileSync(path.join(outDir, `${vp}-diff.png`), PNG.sync.write(d));
      diff = `${n} px differ (${((100 * n) / (A.width * A.height)).toFixed(3)}%)`;
    }
    console.log(vp, '| blocked requests:', bb.blocked, '| errors normal:', JSON.stringify(a.errs), 'blocked:', JSON.stringify(bb.errs), '|', diff);
  }
})();
