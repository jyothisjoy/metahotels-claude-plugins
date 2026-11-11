# Steps 7 and 8: propagate, regress, and a CDN switch during the work

## 7. Propagate and regress
Commands run from the site folder; `$S` is the skill's `scripts/` folder.
- **Purge All at most once per batch**, then re-warm: `bash $S/warm.sh <label>` (every URL in `audit/urls.txt`,
  1.5 s apart; status codes, database errors, cache hits and the markers each page carries, including the site
  plugin's from site.json `markers`).
- Gevora's DB dropped for ~30s right after a purge-all, and cold pages can take 30s+. Monitor for a minute after purging.
- Uploading, replacing or updating a plugin (the site plugin, metahotels-core) purges the whole LiteSpeed cache. Re-warm
  after every upload the user reports, then verify. Also check `/sitemap_index.xml` answers 200 with XML: on Khalidia
  (2026-10-14, after metahotels-core 2.9.8.9 and a MetaHotels Settings save) Rank Math's sitemap URLs fell out of the
  rewrite rules and returned 404, and `sweep.js` silently swept only the homepage. Fix: open
  `wp-admin/options-permalink.php` (rebuilds the rules, saves nothing), then LiteSpeed "Purge 404" (`purge_error404`).
  `python -I $S/sitemap-urls.py` stops with an error in that state.
- `sweep.js` can die partway when headless Chrome crashes ("Navigating frame was detached"). Don't rerun everything:
  take the paths from the finished `m <path>` lines of the output, join them into one exclude regex of the form
  `^https://site(/done-1/|/done-2/|...)$`, pass it as the third argument (with `MSYS_NO_PATHCONV=1`), then concatenate
  the two outputs and compare with the baseline sweep.
- Besides the sweep, run on the homepage and one inner page: `scripts/checks/coldcheck.js` (fresh browser per run:
  carousels, sticky bar, nothing hidden above the fold), `scripts/checks/regress.js` (menus, sticky bar, booking calendar,
  mobile menu and bar, chat, video) and `scripts/checks/interaction.js` (what loads before and after the first input, JS errors).
  `regress.js` finds ElementsKit and Elementor menus and sticky containers by itself; set site.json `selectors` when a
  site differs (references/site-setup.md). After any tested LiteSpeed option is reverted: `bash $S/state.sh`.
- Regression: `node $S/sweep.js https://site 60`, plus manual or headless checks of:
  - desktop dropdown hover and sticky header
  - booking widget renders (calendar opens, guests selector, prices)
  - carousels initialized
  - popup opens and its form + reCAPTCHA are present
  - mobile hamburger menu and mobile booking bar
  - visual screenshots desktop/mobile
- Known test noise:
  - Mirai shows a full-screen cookie modal to new visitors, which blocks hover tests; dismiss it or wait.
  - `position:fixed` elements have `offsetParent === null`.
  - Background-video `play()` AbortError.

## 8. If the site moves behind a CDN during the work (QUIC.cloud on Nassima)
The owner changes DNS/CDN, not us. When it happens:
- Symptom first seen from here: `curl` status `000` on every URL partway through a re-warm, `x-qc-cache` / `x-qc-pop`
  response headers, and a new IP in `nslookup`.
- Check the certificate for **both** the bare domain and `www`:
  `echo | openssl s_client -connect <host>:443 -servername <host> 2>/dev/null | openssl x509 -noout -subject -ext subjectAltName -dates`.
  On Nassima the first certificate was the CDN's default, the second covered only `www`, the third only the bare domain.
  Tell the owner which name is missing; a redirecting `www` still fails before it can redirect.
- Check the origin is healthy without the CDN: `curl --resolve <host>:443:<origin-ip> https://<host>/`.
- Don't measure, re-warm or sweep until the main address has a valid certificate.
- Afterwards: re-read the static cache headers (JS gained a 1-year `cache-control` on Nassima), re-warm (purges also
  clear the edge; the first fetch shows `x-qc-cache: miss`), and state in the report that earlier numbers were measured
  against the origin. From a test location near the origin the CDN changed nothing measurable.
- Page hits no longer reach PHP, so WP-cron queues stall (see step 6).

