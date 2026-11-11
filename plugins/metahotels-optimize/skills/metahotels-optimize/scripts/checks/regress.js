// usage (from the site folder): node <skill>/scripts/checks/regress.js <url> [desktop|mobile]
// Interaction checks after a performance batch (first written for Gevora, 2026-10-12): the timed popup and its form,
// the booking engine's cookie prompt, hero slideshow, desktop menu + dropdown + sticky bar, mobile menu toggle and
// mobile booking bar, the visible Mirai finder and its calendar, carousels, accordion, reCAPTCHA, JS errors.
// Read-only (opens widgets, submits nothing). Screenshots go to ./shots.
// Selectors default to ElementsKit or Elementor's own nav menu and sticky containers; override any of them in
// site.json "selectors": menu, menuParent, submenu, burger, mobileMenu, mobileMenuClose, sticky, mobileBar, hero.
const puppeteer = require('puppeteer-core');
const SHOTS = require('./_lib').shots();
const { CHROME, sel } = require('./_lib');
const url = process.argv[2];
const only = process.argv[3];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const S = {
  menu: sel('menu', '.elementskit-navbar-nav, .elementor-nav-menu--main > ul.elementor-nav-menu'),
  menuParent: sel('menuParent', 'li.menu-item-has-children'),
  submenu: sel('submenu', '.elementskit-dropdown, ul.sub-menu'),
  burger: sel('burger', '.elementskit-menu-hamburger, .elementor-menu-toggle'),
  mobileMenu: sel('mobileMenu', '.elementskit-menu-container, nav.elementor-nav-menu--dropdown'),
  mobileMenuClose: sel('mobileMenuClose', '.elementskit-menu-close, .elementor-menu-toggle'),
  sticky: sel('sticky', '[data-settings*=\'"sticky":"top"\']'),
  mobileBar: sel('mobileBar', '[data-settings*=\'"sticky":"bottom"\']'),
  hero: sel('hero', '[data-elementor-type="wp-page"] > .elementor-element:first-child, [data-elementor-type="wp-post"] > .elementor-element:first-child'),
};
(async () => {
  for (const vp of ['desktop', 'mobile']) {
    if (only && only !== vp) continue;
    const b = await puppeteer.launch({ executablePath: CHROME, headless: 'new' });
    const p = await b.newPage();
    const errs = [];
    p.on('pageerror', (e) => errs.push(String(e.message).slice(0, 120)));
    if (vp === 'mobile') {
      await p.setViewport({ width: 390, height: 844, isMobile: true, hasTouch: true });
      await p.setUserAgent('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1');
    } else await p.setViewport({ width: 1440, height: 900 });
    // LiteSpeed Guest Mode: LS_VARY=<_lscache_vary value> tests the normal copy instead of the guest copy that reloads.
    if (process.env.LS_VARY) await p.setCookie({ name: '_lscache_vary', value: process.env.LS_VARY, domain: new URL(url).hostname, path: '/' });
    await p.goto(url, { waitUntil: 'load', timeout: 120000 });
    const out = {};
    // Two overlays cover the page for a new visitor: a timed popup and the booking engine's cookie prompt. Wait up to
    // 22 s for the popup, close it, answer the prompt (Reject), go back to the top.
    let popupSeen = false;
    for (let i = 0; i < 44 && !popupSeen; i++) { await sleep(500); popupSeen = await p.evaluate(() => { const d = document.querySelector('.elementor-popup-modal'); return !!(d && getComputedStyle(d).display !== 'none'); }); }
    await sleep(1200);
    out.popupOpened = popupSeen + ' scrollYAfterPopup=' + await p.evaluate(() => Math.round(scrollY));
    out.popupForm = await p.evaluate(() => { const d = document.querySelector('.elementor-popup-modal'); return d ? 'inputs=' + d.querySelectorAll('input:not([type=hidden])').length + ' submit=' + d.querySelectorAll('button[type=submit],input[type=submit]').length : 'no popup'; });
    await p.screenshot({ path: SHOTS + '/regress-' + vp + '-popup.png' });
    await p.evaluate(() => { const c = document.querySelector('.elementor-popup-modal .dialog-close-button'); if (c) c.click(); });
    await sleep(700);
    const rej = await p.evaluate(() => { const find = (root) => { for (const e of root.querySelectorAll('*')) { if (e.shadowRoot) { const r = find(e.shadowRoot); if (r) return r; } if (!e.children.length && /^\s*Reject\s*$/i.test(e.textContent || '') && e.getBoundingClientRect().width > 0) return e; } return null; }; const b = find(document); if (!b) return null; const r = b.getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; });
    if (rej) { if (vp === 'mobile') await p.touchscreen.tap(rej.x, rej.y); else await p.mouse.click(rej.x, rej.y); await sleep(1200); }
    out.cookiePrompt = rej ? 'rejected, still shown=' + await p.evaluate(() => /Cookies preferences/.test(document.body.innerText)) : 'none';
    await p.evaluate(() => window.scrollTo({ top: 0, behavior: 'instant' }));
    await sleep(1200);
    out.hero = await p.evaluate(() => { const s = document.querySelector('.elementor-background-slideshow'); if (!s) return 'no slideshow'; const a = s.querySelector('.swiper-slide-active .elementor-background-slideshow__slide__image'); return 'slides=' + s.querySelectorAll('.swiper-slide').length + ' init=' + s.classList.contains('swiper-initialized') + ' activeBg=' + (a ? getComputedStyle(a).backgroundImage.slice(-30) : 'none'); });
    const visFinder = async () => p.evaluateHandle(() => [...document.querySelectorAll('[data-mirai-component="finder"]')].find((e) => { const r = e.getBoundingClientRect(); return r.width > 50 && r.height > 20 && !e.closest('.elementor-sticky__spacer') && r.top >= 0 && r.top < innerHeight; }) || null);
    out.finders = await p.evaluate(() => [...document.querySelectorAll('[data-mirai-component="finder"]')].map((e) => { const r = e.getBoundingClientRect(); return Math.round(r.width) + 'x' + Math.round(r.height) + (e.closest('.elementor-sticky__spacer') ? ' spacer' : ''); }).join(' | '));
    if (vp === 'desktop') {
      out.menu = await p.evaluate((S) => { const n = [...document.querySelectorAll(S.menu)].find((x) => x.getBoundingClientRect().width > 0); if (!n) return 'menu not found: ' + S.menu; const r = n.getBoundingClientRect(); return 'w=' + Math.round(r.width) + ' h=' + Math.round(r.height) + ' links=' + n.querySelectorAll('a').length + ' subs=' + n.querySelectorAll(S.submenu).length; }, S);
      const item = await p.evaluateHandle((S) => [...document.querySelectorAll(S.menu)].flatMap((n) => [...n.querySelectorAll(':scope > ' + S.menuParent)]).find((li) => li.getBoundingClientRect().width > 0) || null, S);
      if (item.asElement()) {
        await item.asElement().hover(); await sleep(700);
        out.dropdown = await p.evaluate((li, S) => { const s = li.querySelector(S.submenu); if (!s) return 'no submenu'; const r = s.getBoundingClientRect(); const cs = getComputedStyle(s); return 'h=' + Math.round(r.height) + ' opacity=' + cs.opacity + ' vis=' + cs.visibility + ' items=' + s.children.length; }, item, S);
      } else out.dropdown = 'no menu item with children';
      await p.mouse.move(700, 600);
      await p.evaluate(() => window.scrollTo(0, 1200)); await sleep(900);
      out.stickyAfterScroll = await p.evaluate((S) => { const e = [...document.querySelectorAll(S.sticky)].find((x) => !x.classList.contains('elementor-sticky__spacer') && x.getBoundingClientRect().width > 0); if (!e) return 'no sticky element: ' + S.sticky; const r = e.getBoundingClientRect(); return 'top=' + Math.round(r.top) + ' pos=' + getComputedStyle(e).position + ' active=' + e.classList.contains('elementor-sticky--active'); }, S);
      await p.evaluate(() => window.scrollTo(0, 0)); await sleep(700);
    } else {
      const burger = await p.evaluateHandle((S) => [...document.querySelectorAll(S.burger)].find((e) => e.getBoundingClientRect().width > 0) || null, S);

      if (burger.asElement()) {
        await burger.asElement().tap(); await sleep(900);
        out.mobileMenu = await p.evaluate((S) => { const open = [...document.querySelectorAll(S.mobileMenu)].filter((d) => { const r = d.getBoundingClientRect(); return r.width > 0 && r.height > 0 && r.left >= 0 && r.left < innerWidth; }); return 'open=' + (open.length > 0) + ' links=' + open.reduce((a, d) => a + d.querySelectorAll('a').length, 0); }, S);
        out.mobileMenuCloseBtn = await p.evaluate((S) => { const c = [...document.querySelectorAll(S.mobileMenuClose)].find((e) => e.getBoundingClientRect().width > 0); if (!c) return 'not visible'; c.click(); return 'clicked'; }, S); await sleep(700);
        out.mobileMenuClosed = await p.evaluate((S) => [...document.querySelectorAll(S.mobileMenu)].every((d) => { const r = d.getBoundingClientRect(); return r.left < 0 || r.width === 0 || r.height === 0 || r.left >= innerWidth; }), S);
      } else out.mobileMenu = 'toggle not found: ' + S.burger;

      out.mobileBar = await p.evaluate((S) => [...document.querySelectorAll(S.mobileBar)].filter((e) => !e.classList.contains('elementor-sticky__spacer')).map((e) => { const r = e.getBoundingClientRect(); return Math.round(r.height) + 'px ' + getComputedStyle(e).position + ' disp=' + getComputedStyle(e).display; }).join(' | ') || 'none: ' + S.mobileBar, S);
    }
    await p.screenshot({ path: SHOTS + '/regress-' + vp + '-top.png' });
    const f = await visFinder();
    if (f.asElement()) {
      out.finder = await p.evaluate((e) => { const r = e.getBoundingClientRect(); return Math.round(r.width) + 'x' + Math.round(r.height) + ' text=' + (e.innerText || '').replace(/\s+/g, ' ').slice(0, 60); }, f);
      const box = await f.asElement().boundingBox();
      if (vp === 'mobile') await p.touchscreen.tap(box.x + 60, box.y + 24); else await p.mouse.click(box.x + 60, box.y + box.height / 2);
      await sleep(2500);
      out.calendar = await p.evaluate(() => { const t = document.body.innerText; const months = (t.match(/\b(January|February|March|April|May|June|July|August|September|October|November|December)\b/g) || []).length; const dlg = document.querySelectorAll('[role="dialog"], [data-role="calendar"], [class*="calendar" i]').length; return 'monthNames=' + months + ' calendarEls=' + dlg; });
      await p.screenshot({ path: SHOTS + '/regress-' + vp + '-calendar.png' });
      await p.keyboard.press('Escape');
    } else out.finder = 'no visible finder';
    out.swipers = await p.evaluate(() => document.querySelectorAll('.swiper-initialized').length + '/' + document.querySelectorAll('.swiper').length);
    out.accordion = await p.evaluate(() => { const d = [...document.querySelectorAll('.e-n-accordion-item')].filter((x) => x.getBoundingClientRect().width > 0); if (d.length < 2) return 'items=' + d.length; const was = d[1].open; d[1].querySelector('summary').click(); return 'items=' + d.length + ' toggled=' + (d[1].open !== was); });
    out.popup = await p.evaluate(() => document.querySelectorAll('.elementor-popup-modal').length + ' modal(s), recaptchaBadge=' + document.querySelectorAll('.grecaptcha-badge').length + ' grecaptcha=' + typeof window.grecaptcha);
    out.heroBackground = await p.evaluate((S) => getComputedStyle(document.querySelector(S.hero) || document.body).backgroundImage.slice(0, 60), S);
    out.scrollY = await p.evaluate(() => Math.round(scrollY));
    out.errors = errs;
    console.log(vp, JSON.stringify(out));
    await b.close();
  }
})();
