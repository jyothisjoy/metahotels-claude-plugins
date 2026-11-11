// usage (from the site folder): node <skill>/scripts/checks/menu-fallback.js <url> --menu=<ul selector> --item=<item selector> --font=<web font family> [--right=<selector>] [--adjust=100,92,88,84,80]
// Finds the size-adjust value at which the desktop menu set in the fallback font (web fonts blocked) is as wide as
// the menu in its web font, so the menu neither wraps to a second row nor moves when the web font arrives
// (pattern "menu font-swap CLS"; Abar 2026-10-12: --menu='#menu-1-c6980a6'
// --item='.elementor-961 .elementor-element.elementor-element-c6980a6 .elementor-nav-menu--main .elementor-item'
// --font=Cormorant --right=.elementor-element-46e9186, result 88%). --right: the column after the menu, to see overlap.
// The CSS it prints is what goes into the nav-menu widget's custom CSS (with selector instead of the element path).
const puppeteer = require('puppeteer-core');
const arg = (n, d) => { const a = process.argv.find((x) => x.startsWith('--' + n + '=')); return a ? a.slice(n.length + 3) : d; };
const url = process.argv[2];
const MENU = arg('menu'), ITEM = arg('item'), FONT = arg('font'), RIGHT = arg('right', '');
if (!MENU || !ITEM || !FONT) { console.error('needs --menu, --item and --font'); process.exit(1); }
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const css = (adj) => '@font-face{font-family:"menu-fallback";src:local("Arial"),local("Helvetica Neue"),local("Helvetica"),local("Roboto");size-adjust:' + adj + '%}' +
  ITEM + '{font-family:"' + FONT + '","menu-fallback",sans-serif;white-space:nowrap}';
(async () => {
  const b = await puppeteer.launch({ executablePath: require('./_lib').CHROME, headless: 'new' });
  const measure = async (blockFonts, adj, width) => {
    const p = await b.newPage();
    await p.setViewport({ width, height: 900 });
    await p.setRequestInterception(true);
    p.on('request', (r) => (blockFonts && /fonts\.gstatic\.com|google-fonts\/fonts/.test(r.url()) ? r.abort() : r.continue()));
    await p.goto(url, { waitUntil: 'domcontentloaded', timeout: 120000 });
    if (adj) await p.addStyleTag({ content: css(adj) });
    await sleep(2500);
    const out = await p.evaluate((MENU, RIGHT) => { const u = document.querySelector(MENU); const r = u.getBoundingClientRect(); const items = [...u.children].map((li) => Math.round(li.getBoundingClientRect().width)); return { w: Math.round(r.width), h: Math.round(r.height), scrollW: u.scrollWidth, sum: items.reduce((a, c) => a + c, 0), right: Math.round(u.lastElementChild.getBoundingClientRect().right), rightCol: RIGHT && document.querySelector(RIGHT) ? Math.round(document.querySelector(RIGHT).getBoundingClientRect().left) : null }; }, MENU, RIGHT);
    await p.close();
    return out;
  };
  console.log('real font, no change   1440:', JSON.stringify(await measure(false, 0, 1440)));
  console.log('fallback, no change    1440:', JSON.stringify(await measure(true, 0, 1440)));
  for (const adj of arg('adjust', '100,92,88,84,80').split(',').map(Number)) console.log('fallback, adjust ' + adj + '%  1440:', JSON.stringify(await measure(true, adj, 1440)));
  console.log('custom CSS for the chosen value n: ' + css('<n>'));
  await b.close();
})();
