# Step 1b: 404s, redirects and calls to action (and the LibreCrawl cross-check)

Every site, alongside the audit (owner's standing request, 2026-10-13). Commands run from the site folder; `$S` is
the skill's `scripts/` folder.

```
python -I $S/sitemap-urls.py                                   # audit/urls.txt (stops if the sitemap is broken)
bash $S/crawl.sh audit/urls.txt audit/pages                    # every sitemap URL saved once, logged out
python -I $S/links.py audit/pages https://site --check --json=audit/links.json > audit/links.txt
# Elementor trees of every document the pages print (also the rollback): see references/images.md step 1
python -I $S/wp/link-scan.py audit/elementor                   # buttons with an empty or "#" link in the saved trees
python -I $S/wp/link-scan.py audit/elementor "<regex>"         # every link value matching, with widget and section
```

## 1b. 404s and calls to action
Two checks that run alongside the audit. Find from the rendered pages first, then make a second pass with the MCP
to locate each finding in the content.

**404s, assets and pages**
1. Assets: the failed requests `sweep.js` reports for every sitemap URL (stylesheets, scripts, images, fonts), plus
   `curl -sI` on anything it lists to confirm the status.
2. Pages: collect every `<a href>` from every sitemap page and check each distinct internal target once
   (`curl -s -o /dev/null -w "%{http_code}"`, `--retry 2`, re-fetch any `000`). Also record sitemap URLs that
   redirect and links that only work through a redirect.
3. MCP pass: `get-menu` for every menu, `elementor-get-data` for the page, header, footer, popup and loop
   templates that hold a broken link or image, so each finding is reported with the widget or menu item ID that
   owns it. Custom post types that are not in REST: `list-posts` with `post_type`.
4. Fix through the MCP only when the right target is certain (a renamed slug, a moved image), with a rollback
   file first. Otherwise list it for the owner. Do not create redirects without asking.

**Calls to action without a link**
1. From the rendered pages: buttons and button-styled links (`.elementor-button`, icon boxes, image boxes, call to
   action and banner widgets, menu items) whose `href` is missing, empty, `#` or the page itself.
2. MCP pass: the same widgets in the Elementor data with an empty `link.url`, including the templates the sweep
   cannot open by URL (popups, header and footer, loop items, the mobile bottom bar) and button fields on offer and
   room post types.
3. Not a finding: a dropdown parent in a menu, a popup trigger, an in-page anchor whose target ID exists on the
   page, and anything rendered by the booking engine itself (`data-mirai-component`), which has no `href` by design.
4. **Hotels: every "Book now" (and "Reserve", "Check availability") must end at the hotel's booking endpoint on
   `reservation.mirai.com`.** List each one with where it points now. The owner gives the correct link per hotel:
   ask for it, never build or guess a Mirai URL, and never copy one from another hotel.
5. Setting the link on our own button, menu item or template is not a booking-engine change. The engine's loader
   snippets, widgets and assets stay untouched (Hard rules).
6. Other missing targets (enquiry, brochure, WhatsApp, phone): ask the owner; do not point a button at a page of
   your choosing.
- **Links that only work through a redirect: point them at the final page (owner, Gewan, 2026-10-15), no need to
  ask.** `scripts/wp/fix-links.py` (rules per old path, dry run first, every target checked for 200,
  rollback per element) rewrites `url` fields and `href`s inside HTML settings across every saved Elementor tree;
  menus through `get-menu` / `update-menu-item`; block-editor content through `update-post`. Before applying, open
  each redirect's target and check it belongs to the same hotel: on Gewan four did not (a group footer's "Contact"
  landing on one hotel's contact page, two Gewan Palace footer rooms landing on Cairo and Fujairah rooms, a dining
  link landing on the hotel's home page while its dining page exists). Use the right page instead, or remove an
  item for something the hotel does not have. Also compare the same widget ID across sibling hotel pages: it
  showed a White Beach button pointing at Cairo's facilities page.
- A "Read More" in a hotel footer that links to the hotel's About page is a self-link only on that page: hide it
  there with custom CSS on the button (`body.page-id-<id> selector{display:none}`,
  `scripts/wp/hide-self-readmore.py`) instead of removing it.
- A button in a loop item shared by several hotels cannot hold a per-hotel link; the site plugin filters
  `elementor/widget/render_content` for that widget ID (`gewan_perf_facilities_link()`).
- Rank Math's canonical (`rank_math_canonical_url`) is protected from the MCP; Rank Math's own REST endpoint
  `POST /wp-json/rankmath/v1/updateMeta` (`objectType`, `objectID`, `meta`) through `wp.py` writes it. A page whose
  canonical points at an old redirecting address is also left out of the sitemap.
- Report both checks in section 8, with the ID of the widget or menu item for every finding and what was fixed.
- Toolkit (first run: Shams, 2026-10-13): `crawl.sh` saves every sitemap URL once, then `links.py --check` checks
  each distinct internal target once and lists broken links, links that only work through a redirect, calls to
  action without a link and every "book" link by target, each with the Elementor document and widget id that owns
  it, and links with a malformed scheme (`ttps://…`, which the browser cannot open; added after Gewan, where only
  LibreCrawl found one).
- `fix-links.py <rules.json>`: build the rules from `links.json` "redirects" (old path → the final page you opened
  and checked), plus "extra" (one widget's link), "remove" (icon-list items for things the hotel does not have) and
  "nolink" (a post-info date linking to a day archive). Its docstring has the format; Gewan's rules are kept in it
  as an example. `hide-self-readmore.py <items.json>` takes footer template, widget, About page id and URL.
- A booking link to the site's own results page with a `lang=` query can 404 for the second language (Shams:
  `/search/?lang=ar…` on 14 Arabic pages while `lang=en` works; Polylang treats `lang` as its own parameter).
  Check both languages. A check-in date hard-coded in such a link goes stale: list it for the owner.

## 1c. LibreCrawl: link-following crawl alongside step 1b (first run: Gewan, 2026-10-15)
[LibreCrawl](https://github.com/PhialsBasement/LibreCrawl) (MIT, Python/Flask) crawls from the homepage by following
links and lists per-URL issues. Nice to have, not required: `links.py` and the MCP pass stay the source of record.
Installed once per machine (references/site-setup.md): a git clone with a Python venv in `.venv`, no Docker, no
browsers; point `LIBRECRAWL_DIR` at the clone.
```
"$LIBRECRAWL_DIR/.venv/Scripts/python.exe" $S/librecrawl-serve.py      # run_in_background; 127.0.0.1:5000 only, local mode
python -I $S/librecrawl.py crawl https://site/ audit/librecrawl-<date>.json --depth=10 > audit/librecrawl-<date>.txt
python -I $S/librecrawl.py compare audit/librecrawl-<date>.json audit/links.json audit/pages/index.tsv
```
Stop the server afterwards (TaskStop on the background task; check port 5000 is closed): it has no login in local
mode, and `librecrawl-serve.py` exists because its own `main.py` always listens on every network interface.
Update with `git pull` in the clone. Re-check every LibreCrawl finding with `curl` before it goes in the report.
What it added on Gewan (`gewanhotels/audit/librecrawl-2026-10-15-findings.md`; 1,145 URLs incl. images, 14 min):
- **Pages outside the sitemap.** It opened 48 HTML pages the sitemap does not list (old blog posts, offers, jobs,
  a hotel's second slug) and found 404 links on them that `links.py` never saw: a deleted offer, 4 old
  `bookingstep1.en.html` booking links, a literal `/url` href.
- **A malformed href** (`ttps://…`) on a sitemap page: `links.py` skips any scheme other than http/https.
- **External links** (one dead), and indexing faults: canonicals that redirect back to the page, a canonical with a
  trailing `%20`, two hotel slugs whose canonicals point at each other, pages without H1 or meta description.
What it gets wrong or misses (don't report these from it without a `curl` check):
- **Redirects:** it follows them and records the final URL, so the 28 redirecting links `links.py` listed were absent.
- **Load artifacts:** 503s on four pages (200 on re-check) and "slow response" on every uncached page; its own
  crawl is the load. Facebook links show 400 (Facebook refuses its HEAD checks). "Noindex" repeats each 404 page.
- No widget IDs, no calls to action without a link, no booking-link list, no speed numbers (its PageSpeed option
  tests three pages; `psi.py` stays). Keep JavaScript rendering off: it would run the booking engine on every
  `/search/` URL it follows.
When: once per site in step 1b, after `links.py`, then `compare`; and in step 7 to diff statuses, canonicals and
noindex per URL against the first crawl. Run it like a re-warm: never while a LiteSpeed test option is on or a
measurement runs (every crawled page is regenerated), and not straight after a Purge All.

