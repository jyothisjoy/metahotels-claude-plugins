# Step 6: moderate and high-risk options, A/B with numbers

Read before testing any LiteSpeed option beyond the safe batch. The per-site results are what each
option did on a real MetaHotels site; read them for what the option does, then decide under the
current rule (SKILL.md, "Score versus experience").

## 6. Moderate/high-risk options: A/B with numbers, revert if no gain
- Toggle ON → purge front page → `throttle.js <label> <url> 3` + `psi.py` ×3 + regression → decide. Keep it when real loading or the PageSpeed score is clearly better and it is not a huge departure for visitors (Hard rules); revert otherwise.
- **The results below were decided under the rule in force until 2026-10-12 (real loads first, a score-only gain stays off).** Read them for what each option does, not for the verdict. Under the current rule an option that behaves like Critical CSS on Nassima (about +13 mobile points for +0.1–0.2 s) is kept; one that breaks something (JS Defer including jQuery, Lazy Load Iframes, LiteSpeed lazy-load on Gevora's carousels) is still off.
- Gevora results:
  - **JS Defer** rejected: the hero is an Elementor background slideshow painted by Swiper JS, so defer delays LCP (render delay 1.2 → 2.4s) with no desktop gain.
  - **CSS Combine** rejected: within-noise change, and it bundles external booking CSS.
- Nassima results:
  - **JS Defer** rejected again, although the hero is a CSS background there: FCP 3588 vs 3104 ms, DCL 7.7 s vs 4.9 s.
  - **Preconnect** to the booking CSS hosts: within noise.
  - PSI mobile score did not move (34/52 → 32/35) while real throttled LCP went 10.0 s → 2.8 s: Lighthouse's simulated
    LCP and TBT got worse once the page stopped idling on a blocking script. Report both, trust the real runs.
  - **Critical CSS + async CSS** (QUIC.cloud): PSI mobile about +13 (render-blocking 43 → 7), but real throttled FCP +0.1 s
    and LCP +0.15–0.2 s over three sets each way, because head scripts and the booking CSS still gate paint. Left OFF;
    it is the owner's call whether lab points are worth it. QUIC.cloud free quota was 2 requests/day, 20/month: check
    `admin.php?page=litespeed` ("Sync data from Cloud") **before** enabling, and use per-post-type CCSS plus a few
    `optm-ccss_sep_uri` paths. Pages without CCSS yet show `<!-- QUIC.cloud CCSS in queue -->` and stay unchanged.
  - **JS Defer including jQuery** (on top of CCSS): −0.25 s FCP but Elementor intermittently never initialised on
    cold-cache loads (carousels 0/5, sticky off). Warm loads and `sweep.js` did not show it; `scripts/checks/coldcheck.js`
    (fresh browser per run) did. Always run a cold check after any defer/delay change. Defer also turns every inline
    script into a deferred `data:` URI script, so anything that must run during parsing (for example the site plugin's
    lazy-background flag) has to be listed in JS Deferred Excludes.
  - **JS Delayed Includes** only delays external files, never the inline init next to them, and with one delayed script
    Elementor did not initialise until the first interaction. Don't use it for single scripts.
  - Behind QUIC.cloud CDN, page hits no longer reach PHP, so WP-cron-driven queues stall; use the "Force cron" links on the
    LiteSpeed dashboard.
- Abar results (`abarhotels/audit/round2-litespeed-options.md`, judged with `scripts/judge.sh`):
  - **Lazy Load Images + Add Missing Sizes** kept (logo in Lazy Load Image Excludes): page weight −0.4 MB desktop,
    −0.7 MB mobile, first paint unchanged; `scripts/checks/lazy-check.js` found every image present at each scroll stop and in
    every carousel.
  - **Lazy Load Iframes** broke the contact-page Google Map (see patterns). Off.
  - **JS Defer** (jQuery and the Mirai loader excluded): no difference outside noise. **CSS Combine**: 0.4 s slower
    first paint on the throttled phone. **HTML Minify**: no change (49.7 KB compressed either way).
  - **Critical CSS** (1 QUIC.cloud request, per-post-type + `^/$`): no change in real first paint, unthrottled blocking
    time doubled, PageSpeed mobile 63 and 40 against 41–49. Third site with the same outcome. With Load Google Fonts
    Asynchronously and DNS Preconnect on top: still no change.
  - QUIC.cloud free quota there: 2 page-optimization requests per day, 20 per month.
- Gevora follow-up results (2026-10-12, `gevora-prod/audit-2026-10-12/judge-*.txt`):
  - **Lazy Load Images + Add Missing Sizes** left OFF there, unlike Abar. Homepage: −0.5 MB desktop, −1.0 MB mobile
    and the load event (when the booking engine starts) 22.3 → 17.3 s on the throttled phone, but carousel duplicate
    slides on inner pages never got their image. With `swiper-slide` excluded nothing broke, the gain fell to
    −0.3 / −0.5 MB and 20.4–21.1 s, and heavy below-the-fold images (150–190 KB icons on `/amenities-facilities/`)
    arrived visibly late after scrolling to them: LiteSpeed starts an image at the viewport edge, native
    `loading="lazy"` starts it 1,250 px or more ahead. Worth another test once those images are re-encoded.
  - **HTML Minify**: no change again (292.7 → 278.7 KB uncompressed).
  - On a page where images are already natively lazy, judge image lazy-load on **every page type** with
    `late-images.js` (slow versus never) and `carousel-check.js`, plus `dcl.js` for the load event.
- Shams results (2026-10-13, `shamshotels/audit/judge-*.txt`, judged with `scripts/judge.sh`; no CDN,
  33 render-blocking stylesheets):
  - **Browser Cache**: changed no header on that host (JS and fonts stay without `cache-control`). Switched back off.
  - **JS Defer** (Mirai loader excluded) while the hero heading still waited for Elementor's script: first paint
    2.81–2.99 s against 2.96–3.39 s, but largest paint 9.3–9.9 s against 7.6–8.4 s over three sets. Reverted; to be
    re-tested with the entrance-animation fix live.
  - **CSS Combine** (third-party CSS excluded): first paint 2.70–2.90 s against 2.96–3.39 s over three sets,
    33 stylesheets → 3. But the first copies generated after a plugin upload had broken loop cards (background
    photo not sized to cover) on two of six page types; copies generated after the next purge were pixel-identical
    on 12 page types. The trigger is Elementor regenerating its CSS files while combine is on. A broken copy stays
    cached for the page TTL, so this counts as "broken intermittently": off unless a configuration survives a forced
    regeneration (`scripts/wp/check-bundles.py` checks every page's combined file for every template's CSS;
    `scripts/checks/compare-urls.js <url> <url>?LSCWP_CTRL=before_optm` is the visual check, run A against A first).
    Switched off the same evening.
    "Combine External and Inline" also moves the booking engine's inline CSS-variable block into the bundle.
  - Second round with the site plugin live (`audit/judge2-*.txt`, `scripts/judge.sh`: two throttled sets and three
    PageSpeed runs per option; comparison state paint 2.75–2.86 s, mobile 53 / 56 / 41, desktop 59 / 64 / 64):
    **JS Defer** paint unchanged, DOMContentLoaded 1.8 s later, mobile 52 / 60 / 46; **HTML Minify** 42 / 60 / 34;
    **Lazy Load Images + Add Missing Sizes** 48 / 35 / 45 and 60 KB fewer images; **Font Display** 49 / 55 / 35;
    **DNS Preconnect** 47 / 52 / 51: none is a gain. **Lazy Load Iframes** left the footer Google Map on
    `about:blank` (same 7.9.1 fault as Abar). **JS Combine** threw `wp is not defined` on every load.
    **JS Delay** (tags and Mirai loader in the excludes): mobile 49 / 50 / 38, and no hero poster, video or chat
    until the first input. Only CSS and JS minify stayed on.
  - PageSpeed mobile ran from 34 to 60 on unchanged states that day. See the pattern "PageSpeed mobile LCP stuck
    at 15 s or more" before spending runs on LiteSpeed switches.
  - An Elementor save through the MCP or a plugin upload purges pages but not every custom post type (six room
    pages kept a JS Delay copy for 50 minutes after the option was off). A setting that is on for a test reaches
    every page a visitor or a running re-warm regenerates meanwhile. So: no re-warm, sweep or MCP save while a
    test option is on; after the last test read the settings back, **Purge All**, re-warm, and scan every page for
    leftovers (the marker check in `shamshotels/audit/final-rewarm.txt`: defer, delay, lazy images, lazy iframes,
    combined JS).
  - The wp-admin session expired in the middle of a test (All-In-One Security) with JS Combine on, and the logged-in
    Chrome dropped off the extension once with CSS Combine on. Before each test: confirm the session with a read,
    keep the test to one judge run, and revert in the same call that sets the next option. Test the risky options
    (delay, combine) straight after a fresh login, never last.
- A throttled DOMContentLoaded can sit in a second group (Gevora: 6.5 s or 12.5 s) for several minutes after a
  Purge All and then return: re-run before blaming the change (`scripts/checks/dcl.js` splits download from
  handler time).
- Not attempted without explicit approval: UCSS, JS Delay.
- Decision principles:
  - With HTTP/2/3, don't combine unless a test shows a benefit.
  - Minify is lower risk than combine; defer is lower risk than delay.
  - Scores count (Hard rules): keep a change that raises the PageSpeed score unless it is a huge departure in the
    visitor's experience, and report its real-load cost next to the gain.
  - A score gain needs three PageSpeed runs each way, 35 s apart and from the same group; one run is noise.
  - Three `throttle.js` sets of 3 runs each way are the minimum to call a 0.1–0.2 s difference; one set is noise.

