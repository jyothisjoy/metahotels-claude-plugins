// usage: node weight.js <url> [desktop|mobile] [rules.json] [--wait=ms]
// Page weight as a "load the page and wait" tool sees it (GTmetrix, PageSpeed, speedvitals): no scrolling, no
// mouse or touch input. Prints transfer size by type and by host and the 12 largest files.
// Optional rules.json (same format as abhtml.js) applies an HTML change first, to predict the effect of a change.
const puppeteer = require('puppeteer-core');
const fs = require('fs');
const args = process.argv.slice(2);
const pos = args.filter((a) => !a.startsWith('--'));
const url = pos[0];
if (!url) { console.error('usage: node weight.js <url> [desktop|mobile] [rules.json] [--wait=ms]'); process.exit(1); }
const mobile = pos[1] === 'mobile';
const rules = pos[2] ? JSON.parse(fs.readFileSync(pos[2], 'utf8')) : null;
const waitArg = args.find((a) => a.startsWith('--wait='));
const UA = mobile ? 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1'
  : 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36';
(async () => {
  let html = null;
  if (rules) {
    html = await (await fetch(url, { headers: { 'user-agent': UA } })).text();
    for (const r of rules) {
      const before = html;
      html = r.regex ? html.replace(new RegExp(r.find, r.flags || ''), () => r.replace) : html.split(r.find).join(r.replace);
      if (html === before) { console.error('RULE DID NOT MATCH: ' + r.find.slice(0, 80)); process.exit(2); }
    }
  }
  const b = await puppeteer.launch({ executablePath: require('./checks/_lib').CHROME, headless: 'new' });
  const p = await b.newPage();
  await p.setViewport(mobile ? { width: 390, height: 844, isMobile: true, hasTouch: true, deviceScaleFactor: 3 } : { width: 1440, height: 900 });
  await p.setUserAgent(UA);
  const c = await p.target().createCDPSession();
  await c.send('Network.enable');
  const req = {};
  c.on('Network.responseReceived', (e) => { req[e.requestId] = { url: e.response.url, type: e.type, bytes: 0 }; });
  c.on('Network.dataReceived', (e) => { if (req[e.requestId]) req[e.requestId].bytes += e.encodedDataLength; });
  c.on('Network.loadingFinished', (e) => { if (req[e.requestId] && e.encodedDataLength) req[e.requestId].bytes = e.encodedDataLength; });
  if (html) {
    await p.setRequestInterception(true);
    let served = false;
    p.on('request', (rq) => {
      if (!served && rq.isNavigationRequest() && rq.frame() === p.mainFrame()) { served = true; rq.respond({ status: 200, contentType: 'text/html; charset=UTF-8', body: html }); } else rq.continue();
    });
  }
  await p.goto(url, { waitUntil: 'load', timeout: 120000 });
  await new Promise((r) => setTimeout(r, waitArg ? +waitArg.slice(7) : 12000));
  const R = Object.values(req).filter((r) => !/^data:/.test(r.url));
  const kb = (n) => Math.round(n / 1024);
  const sum = (f) => { const o = {}; for (const r of R) { const k = f(r); o[k] = (o[k] || 0) + r.bytes; } return Object.entries(o).sort((a, b) => b[1] - a[1]); };
  console.log((mobile ? 'mobile' : 'desktop') + (rules ? ' +rules' : '') + ': ' + R.length + ' requests, ' + kb(R.reduce((a, r) => a + r.bytes, 0)) + ' KB transferred (no scroll, no input)' + (html ? ' [the document is counted uncompressed here: subtract the difference from a run without rules]' : ''));
  console.log('  by type: ' + sum((r) => r.type).map(([k, v]) => k + ' ' + kb(v)).join(', '));
  console.log('  by host: ' + sum((r) => new URL(r.url).host).slice(0, 8).map(([k, v]) => k + ' ' + kb(v)).join(', '));
  for (const r of R.sort((a, b) => b.bytes - a.bytes).slice(0, 12)) console.log('  ' + String(kb(r.bytes)).padStart(5) + ' KB ' + r.type.padEnd(10) + r.url.split('?')[0].slice(-80));
  await b.close();
})();
