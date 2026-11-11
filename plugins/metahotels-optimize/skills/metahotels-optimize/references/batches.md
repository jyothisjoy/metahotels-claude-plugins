# Steps 4, 5 and 5b: safe LiteSpeed batch, site plugin, Element Manager

Commands run from the site folder; `$S` is the skill's `scripts/` folder. LiteSpeed and Elementor settings are
changed with the snippets in references/access.md (read all settings first, re-post the whole form, re-read and diff).

## 4. Safe batch (default ON, low risk), then test
- LiteSpeed: **CSS Minify**, **JS Minify**, **Remove WP Emoji**, **Browser Cache** (record whether it actually changes headers).
- LiteSpeed **JS Excludes**: every third-party script host that appears as `<script src>` in the HTML (see patterns).
- LiteSpeed **CSS Excludes**: the booking engine's external CSS hosts. Minify with the default "Combine External and Inline" **downloads and localizes external CSS**, freezing unversioned third-party files. Add `fonts.googleapis.com` too when a theme links Google Fonts itself (see patterns).
- Elementor: **Load Google Fonts Locally**.
- After saving: purge **front page only**, re-fetch twice (the first fetch builds the cache), check `x-litespeed-cache: hit`, then test
  (`bash $S/judge-live.sh after-safe`, `node $S/checks/regress.js https://site/`), then Purge All and re-warm.

## 5. Site plugin for unused addon assets
1. From `sweep.js`: which addon widgets are used anywhere. Check templates too (`elementor-hf`, `elementskit_template`, popups).
2. Write a patterns file of the asset URLs to drop and run `node $S/simblock.js "https://site/?LSCWP_CTRL=before_optm" patterns.txt`. Require **0 px diff** desktop + mobile and no new JS errors.
3. Copy `assets/plugin-template/site-performance.php` to `<site>/<site>-performance/<site>-performance.php`, rename the
   prefix, and keep only the proven groups. Other proven techniques (popup dialog CSS, lazy CSS backgrounds, icon-font
   subsets, entrance CSS, hero slide, fetchpriority fix, late dequeues) are copied from `assets/plugin-examples/`
   (references/site-plugin.md). `python -I $S/zip-plugin.py <site>/<site>-performance` runs `php -l` and zips with
   forward slashes; hand the zip to the user to upload. The upload purges the whole cache: re-warm, then retest once
   it's active (check the plugin list via `wp.py`, and the plugin's markers on every page with `warm.sh`).

## 5b. Elementor Element Manager: switch off unused widgets (every site, owner's standing request)
Elementor › Element Manager in wp-admin (the user's Chrome tab; it is a React screen, so use its own controls).
1. Press "Scan Element Usage" first: the usage column is stored per document and can be stale.
2. Write the widgets that are already switched off to `<site>/rollback/element-manager-YYYY-MM-DD.txt` before
   changing anything, then add the ones you switch off.
3. Switch off only widgets with usage 0 **and** absent from the `sweep.js` widget inventory. A switched-off widget
   stops rendering wherever it is placed, so also check what the sweep cannot see: popups, header/footer and loop
   templates, drafts and the owner's backup pages. When unsure, leave it on.
4. Leave on anything the owner is likely to reach for next (form, popup and gallery widgets on a site that is still
   being built). The widget disappears from the editor panel, so list what was switched off in report section 9 and
   tell the owner where to switch it back on.
5. Save, purge, then `sweep.js` against the baseline: same widget inventory, no new errors, no empty sections.
- This is housekeeping at the owner's request, not a speed fix: Elementor already loads widget CSS only on pages
  that use the widget, so expect no change in the front-end numbers and do not claim one. Keep it if nothing broke.
- First run: Shams, 2026-10-13 (`shamshotels/rollback/element-manager-2026-10-13.txt`). How the screen is driven
  from `javascript_tool` on `admin.php?page=elementor-element-manager`:
  - The table rows are `#wpbody-content table tbody tr` with cells Element, Status (a checkbox), Usage, Plugin.
    Click the button whose text is "Scan Element Usage" and read the Usage cells about 9 s later.
  - Toggle one checkbox per call with `.click()`; nine clicks in one call timed out (the clicks had still been
    applied: re-read before repeating). "Save Changes" opens a confirmation dialog whose "Save" button must be
    clicked too; navigating away before that raises "Leave site?". Reload and re-read to verify.
  - **The scan under-reports.** On Shams it showed no usage for ElementsKit's Nav Menu (the header menu on 343
    pages), Shortcode (the popup form), Post Title and Post Excerpt. Decide from the rendered inventory
    (`inventory.py` over every sitemap page), never from the scan alone, and never use "Deactivate Unused
    Elements". Tell the owner not to press it either.
  - Result there: 110 of 149 were already off; nine more Gum and ElementsKit widgets switched off; no change in any
    front-end number.

