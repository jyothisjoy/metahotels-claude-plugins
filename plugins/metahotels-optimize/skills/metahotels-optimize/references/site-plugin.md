# The site plugin and metahotels-core: where code goes, and the worked examples

## Where code goes

- **Elementor first.** Custom CSS on our own widget or container (finder reservation, hero static slide, menu
  fallback font) or a widget setting (`image_size`) needs no upload and no release. Keep a rollback file per changed
  element (`rollback/`), and remember the custom CSS is per template: translated templates need it too.
- **Site-specific code** goes in a small plugin `<site>/<site>-performance/<site>-performance.php`, which the user
  uploads. Start from `assets/plugin-template/site-performance.php` (self-healing dequeue groups) and copy the
  techniques below from the examples. Prefix every function with the site slug, guard every feature with a filter so
  one can be switched off without an upload of a new version, print a marker (`<style id="<slug>-perf-...">`) that
  `warm.sh` can count (site.json `markers`), and `python -I <skill>/scripts/zip-plugin.py <dir>` (php -l, forward
  slashes). Bump the plugin's version on each upload; uploading purges the whole LiteSpeed cache.
- **Generic code** goes in `metahotels-core` (MetaHotels' own plugin; ask the user where their local clone is) as an
  opt-in toggle, default OFF. Don't commit or bump its version: the owner releases it. Until a release is live, the
  site plugin can carry the same code, guarded so it switches itself off when core's toggle is on.

## metahotels-core toggles proven on these sites

| Toggle (option name) | What it does | Pattern |
|---|---|---|
| Preload Hero Background Image (`metahotels_enable_hero_preload`, 2.9.8.6+; video fallback 2.9.8.8) | `<link rel=preload as=image>` for the first section's background, slideshow or video poster. Filters `metahotels_hero_preload_enabled` / `metahotels_hero_preload_images` | LCP is a background image |
| Load reCAPTCHA only when a form is shown (`metahotels_brevo_recaptcha_lazy`) | reCAPTCHA (~354 KB) loads when a Brevo form is in view or opened, not on every page | reCAPTCHA everywhere |
| Load Popup Styles With the Page (`metahotels_enable_popup_dialog_css`, local 2026-10-12) | prints Elementor's `dialog.min.css` before `elementor-frontend` | popup CLS and self-scroll |
| Start Header and Hero Animations at First Paint (`metahotels_enable_entrance_first_paint`, local 2026-10-13) | the entrance-animation CSS of `make-rules.py entrance` | header and hero hidden until JS |
| Video Background (R2) › Start After Page Load (`vbg_after_load`, released 2.9.8.9) | poster painted from CSS at first paint, video requested after `load` | hero video, PageSpeed LCP 15 s |

Check the installed version (`wp.py <server> GET "/wp-json/wp/v2/plugins?context=edit"`) before relying on one:
"local" means built but not released when last checked. The settings page holds API-key fields; a re-post of that
form was refused once and allowed once (references/access.md): when in doubt, the switches are the user's to tick.

## Worked examples (`assets/plugin-examples/`)

| Technique | File and function | Notes |
|---|---|---|
| Dequeue unused addon assets, self-healing (a widget that renders re-adds its assets) | `gevora-performance.php` `gevora_perf_groups()` / `gevora_perf_dequeue()`; `shamshotels-performance.php`; `khalidia-performance.php` `kph_perf_need()` | prove each group with `simblock.js` (0 px diff) first |
| Dequeue that another plugin re-enqueues late (WP Job Openings Pro Pack) | `gewan-performance.php` `gewan_perf_jobs_*()` | `PHP_INT_MAX` at `wp_enqueue_scripts`, again at `wp_print_styles` and `wp_print_footer_scripts` 1; `gewan_perf_jobs_heal()` re-adds them on a page with the shortcode |
| Job-page styles kept in `<head>` only where a listing shows | `khalidia-performance.php` `kph_perf_jobs_page()` | decided before `<head>` is printed |
| Popup dialog CSS with the page | `gevora_perf_dialog_css()`, `shams_perf_dialog_css()`, `kph_perf_dialog_css()`, `gewan_perf_dialog_css()` | switches itself off when core's toggle is on |
| Lazy CSS backgrounds below the fold | `nassimatower-performance.php` `nassima_perf_lazy_bg_*()`; `gewan_perf_lazy_bg_*()` | gated on a JS-set class; near-viewport and video/slideshow elements revealed synchronously; list in JS Deferred Excludes if JS Defer is ever on |
| Icon-font subset (`@font-face` + `unicode-range`, full font as fallback) | `nassima_perf_icon_subset()` (Jeg Kit), `shams_perf_icon_subset()` (ElementsKit), `kph_perf_fa_subset()` (Font Awesome, inlined data URI) | build with `scripts/wp/build-icon-subset.py --font=`; guard on the source font's byte size |
| Hero preload for a page core does not cover | `nassima_perf_hero_enabled()` / `nassima_perf_hero_images()` | via core's filters |
| Hero slideshow's first slide painted from CSS, read from Elementor data (no hard-coded URL) | `kph_perf_hero_slide()`, `kph_perf_hero_preload()`, `kph_perf_hero_css()`, `kph_perf_hero_template_css()` | waits for Swiper's lazy image; skips Ken Burns "out"; belongs in core next to the hero preload |
| Entrance animations at first paint | `shams_perf_entrance_css()`, `kph_perf_entrance_selector()` / `kph_perf_entrance_css()` | header + first section only; respects reduced motion |
| First content image below a full-height hero: lazy, no `fetchpriority=high` | `kph_perf_content_img_lazy()` | `wp_content_img_tag` at priority 20 |
| Stretched sections and the mobile booking bar reserved from first paint | `gewan_perf_layout_css()` | patterns.md, "Layout shift" |
| Per-hotel link on a button inside a loop item shared by several hotels | `gewan_perf_hotel_facilities_url()` / `gewan_perf_facilities_link()` | filters `elementor/widget/render_content` for that widget id |

The examples are real plugins from finished passes (Gevora 1.1.0, Nassima 1.1.0, Shams 1.0.0, Khalidia 1.1.0, Gewan
1.0.1). Copy a technique, not a file: element ids, handles and constants are the original site's.
