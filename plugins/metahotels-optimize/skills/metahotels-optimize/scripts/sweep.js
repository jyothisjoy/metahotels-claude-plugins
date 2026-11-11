// usage: node sweep.js <site-origin> [maxUrls] [excludeRegex]      e.g. node sweep.js https://example.com 40 "/blog/"
// excludeRegex skips matching URLs (big blogs: sweep pages first, posts in a second run or sample them).
// Reads wp-sitemap.xml (falls back to sitemap_index.xml), loads every URL logged-out on desktop + mobile,
// and reports JS errors, console errors and failed same-origin requests. Run after every batch of changes.
// Also prints which Elementor widget types each page uses (needed before dequeuing an addon's assets).
const puppeteer = require('puppeteer-core');
const origin = (process.argv[2] || '').replace(/\/$/, '');
const max = +(process.argv[3] || 60);
const exclude = process.argv[4] ? new RegExp(process.argv[4]) : null;
if (!origin) { console.error('usage: node sweep.js <site-origin> [maxUrls]'); process.exit(1); }

async function sitemapUrls() {
  const get = async (u) => { try { const r = await fetch(u); return r.ok ? await r.text() : ''; } catch { return ''; } };
  const locs = (xml) => [...xml.matchAll(/<loc>([^<]+)<\/loc>/g)].map((m) => m[1]);
  let index = await get(origin + '/wp-sitemap.xml');
  if (!index) index = await get(origin + '/sitemap_index.xml');
  const urls = [];
  for (const m of locs(index)) {
    if (/users|taxonomies-post_tag/.test(m)) continue;
    if (/\.xml/.test(m)) urls.push(...locs(await get(m)));
    else urls.push(m);
  }
  return [...new Set([origin + '/', ...urls])].filter((u) => !/\.(jpe?g|png|webp|gif|pdf)$/i.test(u) && !(exclude && exclude.test(u))).slice(0, max);
}

(async () => {
  const urls = await sitemapUrls();
  const b = await puppeteer.launch({ executablePath: require('./checks/_lib').CHROME, headless: 'new' });
  const widgetUse = {};
  for (const url of urls) {
    for (const vp of ['d', 'm']) {
      const p = await b.newPage();
      if (vp === 'm') {
        await p.setViewport({ width: 390, height: 844, isMobile: true, hasTouch: true });
        await p.setUserAgent('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1');
      } else await p.setViewport({ width: 1440, height: 900 });
      const errs = [];
      p.on('pageerror', (e) => errs.push('JS: ' + String((e && e.message) || e).slice(0, 120)));
      p.on('console', (m) => { if (m.type() === 'error' && !/status of 4|ERR_/.test(m.text())) errs.push('console: ' + m.text().slice(0, 120)); });
      p.on('response', (r) => { if (r.status() >= 400 && r.url().startsWith(origin)) errs.push(r.status() + ' ' + r.url().replace(origin, '').slice(0, 100)); });
      try {
        await p.goto(url, { waitUntil: 'load', timeout: 90000 });
        await new Promise((r) => setTimeout(r, 4000));
        const st = await p.evaluate(() => ({
          elementor: typeof elementorFrontend !== 'undefined',
          swipers: document.querySelectorAll('.swiper').length + '/' + document.querySelectorAll('.swiper-initialized').length,
          widgets: [...new Set([...document.querySelectorAll('[data-widget_type]')].map((e) => e.dataset.widget_type))],
        }));
        if (vp === 'd') st.widgets.forEach((w) => { widgetUse[w] = (widgetUse[w] || 0) + 1; });
        console.log(vp, url.replace(origin, '').padEnd(50), 'elementor=' + st.elementor, 'swipers=' + st.swipers, errs.length ? JSON.stringify(errs) : 'ok');
      } catch (e) { console.log(vp, url, 'LOAD FAILED', e.message.slice(0, 100)); }
      await p.close();
    }
  }
  await b.close();
  console.log('\nWidget types used (pages):', JSON.stringify(Object.fromEntries(Object.entries(widgetUse).sort((a, b) => b[1] - a[1]))));
})();
