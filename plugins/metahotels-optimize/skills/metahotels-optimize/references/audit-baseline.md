# Steps 1 and 2: audit and baseline

Read at the start of a pass. Nothing on the site changes during these steps. Commands run from the site folder;
`$S` is the skill's `scripts/` folder. Save every output under `audit/` (or `audit-<date>/` on a follow-up pass), so
the report quotes files, not memory.

## 1. Audit (read-only)

1. `mcp-adapter-content-integrations-status`. Plugins and theme:
   `MSYS_NO_PATHCONV=1 python -I $S/wp.py <server> GET "/wp-json/wp/v2/plugins?context=edit"` and
   `/wp-json/wp/v2/themes?status=active`.
2. Homepage HTML: `curl -s -D audit/home.h --compressed https://site/ -o audit/home.html`. List every
   `<link rel=stylesheet>` and `<script src>` with its `id` (handle), note `x-litespeed-cache` (and `x-qc-cache`
   behind QUIC.cloud), and grep for booking-engine markup (`data-mirai-component`), `recaptcha`,
   `fonts.googleapis`, `/elementor-pro/`. `python -I $S/markers.py audit/home.html` gives the usual markers at once.
3. LiteSpeed values: read all settings pages with the snippet in references/access.md (`litespeed-cache`,
   `litespeed-page_optm`, `litespeed-cdn`, `litespeed-general`) and the Object tab status text (Redis/Memcached
   extension available?). Save them to `audit/litespeed-before.txt`: section 4 of the report needs before → after.
4. Elementor settings (`admin.php?page=elementor-settings`): `elementor_local_google_fonts`,
   `elementor_font_display`, `elementor_optimized_image_loading`, `elementor_optimized_gutenberg_loading`,
   `elementor_lazy_load_background_images`, experiments (`e_font_icon_svg` etc.).
5. Elementor Custom Code snippets via REST (`/wp-json/wp/v2/elementor_snippet?context=edit`). This is where
   booking-engine loaders, the chat widget, GA/GTM and verification tags live. Save each one before any change.
6. Static headers: `curl -sI` a CSS, a JS, an image and a font. Check `cache-control`, `expires`,
   `content-encoding`, CDN headers.
7. Field data: CrUX from the PSI response (`loadingExperience`). This is what matters to real users.
8. Page weight and images: `node $S/weight.js https://site/` (what a no-scroll, no-input test tool counts) and
   `node $S/images.js https://site/ desktop --scroll` (what loads without scrolling, at what size, in which widget).
9. Where the lab score is lost: `python -I $S/psi_breakdown.py <host> <label>` (points per metric, script time per
   file, third parties). The mobile list sets the order of work (SKILL.md, "Mobile first").
10. Site-wide inventory: `python -I $S/sitemap-urls.py` (writes `audit/urls.txt`), `bash $S/crawl.sh audit/urls.txt
    audit/pages`, then `python -I $S/wp/inventory.py audit/pages` (widget types, stylesheet and script handles,
    Elementor documents, feature flags per page), `python -I $S/wp/usage.py audit/pages` (which global libraries
    any page needs) and `python -I $S/wp/entrance.py audit/pages` (entrance animations in the first section).
11. Broken assets, broken pages and calls to action without a link: step 1b (references/links-and-ctas.md).

## 2. Baseline (before any change)

```
node $S/measure.js before https://site/ 2 | python $S/summarize.py   # desktop+mobile, requests/CSS/JS/3p/failed/console, repeated API calls
node $S/throttle.js before https://site/ 3                           # Slow-4G + 4x CPU median FCP/LCP (decision metric for mobile)
python -I $S/psi.py before-1 https://site/                           # three runs, 35 s apart (before-2, before-3): mobile is the priority and very noisy
node $S/sweep.js https://site 60                                     # every sitemap URL: errors + widget types used site-wide
node $S/weight.js https://site/ desktop ; node $S/weight.js https://site/ mobile   # page weight with no scroll and no input
python -I $S/psi_breakdown.py <host> before-1 before-2 before-3      # points lost per metric, script time per file
```
Or in one go: `bash $S/judge-live.sh before` (three throttled sets with a PageSpeed run after each, the breakdown
at the end; `audit/judge-before.txt`). Results land in `runs/<host>/` in the site folder.

`sweep.js` takes an optional third argument, a regex of URLs to skip (prefix the command with `MSYS_NO_PATHCONV=1`
in Git Bash or `"/blog/"` is rewritten to a Windows path). A page that waits on a slow third-party script makes the
sweep take ~20 s per URL; 115 URLs took 45 min before the Nassima chatbot fix and about 20 min after. Run it in the
background and save its output (`audit/before-sweep.txt`): every later sweep is compared with it.
Also: an Elementor `data-widget_type` inventory (from `sweep.js`) and CLS attribution (LayoutShift sources:
`node $S/abhtml.js control https://site/ - 3 --shifts`; see references/patterns.md).
Measure the homepage and at least one inner page per template (rooms, a hotel page on a multi-property site).
