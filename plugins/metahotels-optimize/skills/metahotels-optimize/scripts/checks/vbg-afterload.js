// usage: node vbg-afterload.js <url> [desktop|mobile] [--patched=path/to/vbg.js] [--after-load] [--preload] [--slow]
// When does the hero video file start downloading, relative to first paint, largest paint and the load event?
// Uses LiteSpeed's unoptimised output (?LSCWP_CTRL=before_optm) so metahotels-core's vbg.js is a separate file.
// --patched serves a local copy of vbg.js (and the vbg.css next to it) instead of the live ones; --after-load adds
// "afterLoad":true to the section's data-vbg and the poster CSS variable, which is what the "Start After Page
// Load" switch prints; --preload adds the hero preload for the poster. --slow = Slow 4G + 4x CPU.
const puppeteer = require('puppeteer-core');
const fs = require('fs');
const args = process.argv.slice(2);
const [url, prof] = args.filter((a) => !a.startsWith('--'));
const opt = (n) => { const a = args.find((x) => x.startsWith('--' + n + '=')); return a ? a.slice(n.length + 3) : null; };
const mobile = prof === 'mobile';
const slow = args.includes('--slow');
const afterLoad = args.includes('--after-load');
const patched = opt('patched') ? fs.readFileSync(opt('patched'), 'utf8') : null;
const patchedCss = opt('patched') ? fs.readFileSync(opt('patched').replace(/vbg\.js$/, 'vbg.css'), 'utf8') : null;
const UA = mobile
  ? 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1'
  : 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
(async () => {
  const target = url + (url.includes('?') ? '&' : '?') + 'LSCWP_CTRL=before_optm';
  let html = await (await fetch(target, { headers: { 'user-agent': UA } })).text();
  if (afterLoad) {
    const before = html;
    html = html.replace(/data-vbg="\{/, 'data-vbg="{&quot;afterLoad&quot;:true,');
    if (html === before) { console.error('no data-vbg on the page'); process.exit(2); }
    // What the PHP side prints with the switch on: the poster as a CSS variable on the section, and (hero
    // preload switched on) a preload for it.
    const poster = (html.match(/&quot;poster&quot;:&quot;([^&]*)&quot;/) || [])[1];
    if (poster) {
      const posterUrl = poster.split('\\/').join('/');
      html = html.replace(/(<div class="[^"]*has-vbg[^"]*")/, '$1 style="--vbg-poster:url(&quot;' + posterUrl + '&quot;);"');
      if (args.includes('--preload')) html = html.replace('<meta name="viewport"', '<link rel="preload" as="image" href="' + posterUrl + '" fetchpriority="high">\n<meta name="viewport"');
    }
  }
  const b = await puppeteer.launch({ executablePath: require('./_lib').CHROME, headless: 'new' });
  const p = await b.newPage();
  await p.setViewport(mobile ? { width: 390, height: 844, isMobile: true, hasTouch: true, deviceScaleFactor: 2 } : { width: 1440, height: 900 });
  await p.setUserAgent(UA);
  const errs = [];
  p.on('pageerror', (e) => errs.push(String(e.message).slice(0, 80)));
  const c = await p.target().createCDPSession();
  await c.send('Network.enable');
  await c.send('Network.setCacheDisabled', { cacheDisabled: true });
  if (slow) {
    await c.send('Network.emulateNetworkConditions', { offline: false, latency: 150, downloadThroughput: (1.6 * 1024 * 1024) / 8, uploadThroughput: (750 * 1024) / 8 });
    await c.send('Emulation.setCPUThrottlingRate', { rate: 4 });
  }
  await p.setRequestInterception(true);
  let served = false, swapped = 0, t0 = 0, videoAt = null, posterAt = null;
  p.on('request', (rq) => {
    const u = rq.url();
    if (/cdn-cgi\/media\/mode=video/.test(u) && videoAt === null) videoAt = Date.now() - t0;
    if (/cdn-cgi\/media\/mode=frame/.test(u) && posterAt === null) posterAt = Date.now() - t0;
    if (!served && rq.isNavigationRequest() && rq.frame() === p.mainFrame()) { served = true; t0 = Date.now(); return rq.respond({ status: 200, contentType: 'text/html; charset=UTF-8', body: html }); }
    if (patched && /metahotels-core\/.*\/vbg\.js/.test(u)) { swapped++; return rq.respond({ status: 200, contentType: 'application/javascript; charset=UTF-8', body: patched }); }
    if (patchedCss && /metahotels-core\/.*\/vbg\.css/.test(u)) { swapped++; return rq.respond({ status: 200, contentType: 'text/css; charset=UTF-8', body: patchedCss }); }
    rq.continue();
  });
  await p.evaluateOnNewDocument(() => {
    window.__m = { fcp: null, lcp: [], posterBg: null };
    new PerformanceObserver((l) => { for (const e of l.getEntries()) if (e.name === 'first-contentful-paint') window.__m.fcp = Math.round(e.startTime); }).observe({ type: 'paint', buffered: true });
    new PerformanceObserver((l) => { for (const e of l.getEntries()) window.__m.lcp.push([Math.round(e.startTime), e.element ? e.element.tagName + '.' + String(e.element.className).slice(0, 24) : '?']); }).observe({ type: 'largest-contentful-paint', buffered: true });
  });
  await p.goto(target, { waitUntil: 'load', timeout: 180000 }).catch((e) => errs.push('goto ' + e.message.slice(0, 50)));
  await sleep(slow ? 12000 : 6000);
  const st = await p.evaluate(() => {
    const v = document.querySelector('.vbg-layer video');
    const nav = performance.getEntriesByType('navigation')[0];
    const sec = document.querySelector('.has-vbg');
    const posterRes = performance.getEntriesByType('resource').filter((e) => /mode=frame/.test(e.name)).map((e) => Math.round(e.startTime) + '-' + Math.round(e.responseEnd))[0];
    return { fcp: window.__m.fcp, lcp: window.__m.lcp, loadEvent: Math.round(nav.loadEventStart), dcl: Math.round(nav.domContentLoadedEventEnd), posterRes, sectionBg: sec ? getComputedStyle(sec).backgroundImage.slice(0, 40) : null, video: v ? { playing: !v.paused, t: Math.round(v.currentTime * 10) / 10, readyState: v.readyState, hasSrc: !!v.currentSrc } : null, layer: (document.querySelector('.vbg-layer') || {}).className };
  });
  console.log(`${mobile ? 'mobile' : 'desktop'}${slow ? ' slow' : ''} | patched files served ${swapped} | afterLoad ${afterLoad} | FCP ${st.fcp} | LCP ${st.lcp.map((x) => x.join(' ')).join(' -> ')} | DCL ${st.dcl} | load ${st.loadEvent} | poster fetched ${st.posterRes} ms | VIDEO requested at ~${videoAt} ms | section background "${st.sectionBg}" | end: ${JSON.stringify(st.video)} layer "${st.layer}" | errors ${JSON.stringify(errs)}`);
  await b.close();
})();
