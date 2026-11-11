// usage: node images.js <url> [desktop|mobile] [--scroll]
// Image audit: every image the page downloads WITHOUT scrolling (what lazy-loading should have prevented),
// with its transfer size, intrinsic size, the size it is displayed at, where it sits on the page and which
// Elementor element/widget uses it (img tag or CSS background). With --scroll it also lists what loads later.
// Use it to decide what to lazy-load and what to resize/recompress.
const puppeteer = require('puppeteer-core');
const args = process.argv.slice(2);
const [url, prof] = args.filter((a) => !a.startsWith('--'));
if (!url) { console.error('usage: node images.js <url> [desktop|mobile] [--scroll]'); process.exit(1); }
const mobile = prof === 'mobile';
(async () => {
  const b = await puppeteer.launch({ executablePath: require('./checks/_lib').CHROME, headless: 'new' });
  const p = await b.newPage();
  if (mobile) {
    await p.setViewport({ width: 390, height: 844, isMobile: true, hasTouch: true, deviceScaleFactor: 3 });
    await p.setUserAgent('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1');
  } else await p.setViewport({ width: 1440, height: 900 });
  const c = await p.target().createCDPSession();
  await c.send('Network.enable');
  const req = {};
  c.on('Network.responseReceived', (e) => { if (e.type === 'Image' || /^image\//.test(e.response.mimeType)) req[e.requestId] = { url: e.response.url, t: e.timestamp }; });
  c.on('Network.loadingFinished', (e) => { if (req[e.requestId]) req[e.requestId].bytes = e.encodedDataLength; });
  await p.goto(url, { waitUntil: 'load', timeout: 120000 });
  await new Promise((r) => setTimeout(r, 7000));
  const describe = async (list) => p.evaluate(async (urls) => {
    const out = {};
    const els = [...document.querySelectorAll('*')];
    const bg = new Map();
    for (const e of els) {
      const s = getComputedStyle(e).backgroundImage;
      if (s && s !== 'none') for (const m of s.matchAll(/url\("?([^")]+)"?\)/g)) { if (!bg.has(m[1])) bg.set(m[1], []); bg.get(m[1]).push(e); }
    }
    for (const u of urls) {
      const uses = [];
      for (const img of document.images) if ((img.currentSrc || img.src) === u) uses.push({ kind: 'img', e: img, nat: img.naturalWidth + 'x' + img.naturalHeight, lazy: img.loading === 'lazy' || img.hasAttribute('data-lazyloaded') });
      for (const e of bg.get(u) || []) uses.push({ kind: 'bg', e });
      let nat = uses.find((x) => x.nat) ? uses.find((x) => x.nat).nat : '';
      if (!nat) { try { const im = new Image(); im.src = u; await im.decode(); nat = im.naturalWidth + 'x' + im.naturalHeight; } catch (e) { nat = '?'; } }
      out[u] = { nat, uses: uses.slice(0, 3).map((x) => {
        const r = x.e.getBoundingClientRect(); const w = x.e.closest('[data-widget_type]'); const el = x.e.closest('[data-id]');
        const pop = x.e.closest('[data-elementor-type]');
        return x.kind + ' ' + Math.round(r.width) + 'x' + Math.round(r.height) + ' @y=' + Math.round(r.top + scrollY) + (x.lazy ? ' lazy' : '') + ' ' + (w ? w.dataset.widget_type : 'container') + '#' + (el ? el.dataset.id : '') + (pop ? ' in ' + pop.dataset.elementorType + ':' + pop.dataset.elementorId : '') + (x.e.closest('.swiper-slide') ? ' slide' : '') + (getComputedStyle(x.e).display === 'none' || r.width === 0 ? ' HIDDEN' : '');
      }), count: uses.length };
    }
    return out;
  }, list);
  const initial = Object.values(req).filter((r) => r.bytes !== undefined && !/^data:/.test(r.url));
  const info = await describe(initial.map((r) => r.url));
  const dpr = mobile ? 3 : 1;
  const show = (rows, title) => {
    console.log('\n== ' + title + ': ' + rows.length + ' images, ' + Math.round(rows.reduce((a, r) => a + r.bytes, 0) / 1024) + ' KB (viewport ' + (mobile ? '390x844 @3x' : '1440x900') + ')');
    for (const r of rows.sort((a, b) => b.bytes - a.bytes)) {
      const i = info[r.url] || { nat: '', uses: [] };
      console.log(String(Math.round(r.bytes / 1024)).padStart(5) + ' KB  ' + String(i.nat).padEnd(10) + ' ' + r.url.replace(/^https?:\/\/[^/]+/, '').split('?')[0].slice(-62).padEnd(62) + ' | ' + (i.uses.length ? i.uses.join(' ; ') + (i.count > 3 ? ' (+' + (i.count - 3) + ')' : '') : 'no element uses it now'));
    }
  };
  show(initial, 'Loaded WITHOUT scrolling');
  if (args.includes('--scroll')) {
    const seen = new Set(initial.map((r) => r.url));
    await p.evaluate(async () => { for (let y = 0; y < document.body.scrollHeight; y += 500) { window.scrollTo(0, y); await new Promise((r) => setTimeout(r, 200)); } });
    await new Promise((r) => setTimeout(r, 4000));
    const later = Object.values(req).filter((r) => r.bytes !== undefined && !seen.has(r.url) && !/^data:/.test(r.url));
    Object.assign(info, await describe(later.map((r) => r.url)));
    show(later, 'Loaded only after scrolling');
  }
  console.log('\n(page height ' + await p.evaluate(() => document.body.scrollHeight) + ' px, device pixel ratio ' + dpr + ')');
  await b.close();
})();
