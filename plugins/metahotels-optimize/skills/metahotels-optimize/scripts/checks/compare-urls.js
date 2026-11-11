// usage: node compare-urls.js <urlA> <urlB> [label]
// Pixel-diffs two URLs (desktop + mobile, full page, animations and sliders frozen, third-party noise blocked).
// Meant for "the optimised page" versus "the same page with ?LSCWP_CTRL=before_optm" (LiteSpeed's unoptimised
// output), to prove that an option such as CSS Combine did not change how a page looks. Run A against A first:
// that is the noise floor of the page. Screenshots and the diff go to ./shots/compare-<label>-<viewport>-{a,b,diff}.png.
const puppeteer = require('puppeteer-core');
const SHOTS = require('./_lib').shots();
const fs = require('fs');
const path = require('path');
const { PNG } = require('pngjs');
const pm = require('pixelmatch');
const pixelmatch = pm.default || pm;
const [urlA, urlB, labelArg] = process.argv.slice(2);
const label = labelArg || 'cmp';
const NOISE = /mirai|recaptcha|gstatic|googletagmanager|google-analytics|hdr_chatbot|clarity\.ms|youtube\.com|youtube-nocookie\.com|ytimg\.com|wistia|\.mp4|\.m3u8/;
const UAS = {
  desktop: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36',
  mobile: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
};
async function shot(url, vp, file) {
  const b = await puppeteer.launch({ executablePath: require('./_lib').CHROME, headless: 'new' });
  const p = await b.newPage();
  await p.setViewport(vp === 'mobile' ? { width: 390, height: 844, isMobile: true, hasTouch: true } : { width: 1440, height: 900 });
  await p.setUserAgent(UAS[vp]);
  await p.setRequestInterception(true);
  const errs = [];
  let css = 0, js = 0;
  p.on('request', (r) => {
    if (NOISE.test(r.url())) return r.abort();
    if (r.resourceType() === 'stylesheet') css++;
    if (r.resourceType() === 'script') js++;
    r.continue();
  });
  p.on('pageerror', (e) => errs.push(String((e && e.message) || e).slice(0, 120)));
  await p.goto(url, { waitUntil: 'load', timeout: 120000 });
  await p.addStyleTag({ content: '*{animation:none!important;transition:none!important} .elementor-invisible{visibility:visible!important}' });
  await p.evaluate(async () => { for (let y = 0; y < document.body.scrollHeight; y += 500) { window.scrollTo(0, y); await new Promise((r) => setTimeout(r, 120)); } });
  await new Promise((r) => setTimeout(r, 3000));
  await p.evaluate(() => {
    document.querySelectorAll('.swiper').forEach((s) => { if (s.swiper) { s.swiper.autoplay && s.swiper.autoplay.stop(); s.swiper.slideTo(0, 0); } });
    window.scrollTo(0, 0);
  });
  await new Promise((r) => setTimeout(r, 1500));
  await p.screenshot({ path: file, fullPage: true });
  await b.close();
  return { errs, css, js };
}
(async () => {
  for (const vp of ['desktop', 'mobile']) {
    const fa = path.join(SHOTS, `compare-${label}-${vp}-a.png`), fb = path.join(SHOTS, `compare-${label}-${vp}-b.png`);
    const a = await shot(urlA, vp, fa), b = await shot(urlB, vp, fb);
    const A = PNG.sync.read(fs.readFileSync(fa)), B = PNG.sync.read(fs.readFileSync(fb));
    let diff = `page height differs (${A.height} vs ${B.height})`;
    if (A.width === B.width && A.height === B.height) {
      const d = new PNG({ width: A.width, height: A.height });
      const n = pixelmatch(A.data, B.data, d.data, A.width, A.height, { threshold: 0.15 });
      fs.writeFileSync(path.join(SHOTS, `compare-${label}-${vp}-diff.png`), PNG.sync.write(d));
      diff = `${n} px differ (${((n / (A.width * A.height)) * 100).toFixed(3)}%)`;
    }
    console.log(`${label} ${vp} | A css ${a.css} js ${a.js} errors ${JSON.stringify(a.errs)} | B css ${b.css} js ${b.js} errors ${JSON.stringify(b.errs)} | ${diff}`);
  }
})();
