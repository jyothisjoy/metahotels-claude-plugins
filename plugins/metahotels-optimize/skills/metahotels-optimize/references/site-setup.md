# Setup: once per machine, once per site

`/metahotels-optimize:optimize --init` (`scripts/init.py`) does the machine and work-folder part and lists what is
left; `/metahotels-optimize:optimize <site>` (`scripts/site-init.py`) does the site part and lists what to ask.
The tables below are what they check, for when something fails.

## Once per machine

| Need | How | Used by |
|---|---|---|
| Node.js 18+ | `npm ci` in the skill's `scripts/` folder (puppeteer-core, pngjs, pixelmatch; no browser download); `init.py` does it, and a plugin update removes it | every `.js` tool |
| Chrome or Chromium | found automatically on Windows, macOS and Linux; else set `CHROME_PATH` | headless measurements and checks |
| Python 3.10+ | standard library only for most tools (run them with `python -I`) | `.py` tools |
| Pillow ≥ 11.3 (AVIF), fonttools + brotli | `pip install --user "pillow>=11.3" fonttools brotli`; those two tools run without `-I` | `optimize-images.py`, `build-icon-subset.py` |
| bash and curl | Git Bash on Windows. In Git Bash prefix commands whose arguments start with `/` with `MSYS_NO_PATHCONV=1` | `.sh` tools, `crawl.sh` |
| PHP CLI | on PATH, or `PHP_BIN` (XAMPP's `C:/xampp/php/php.exe` is found too) | `zip-plugin.py` (`php -l`) |
| Claude in Chrome | the extension in a Chrome logged into the site's wp-admin | LiteSpeed and Elementor settings, purges |
| A WordPress MCP server per site | the site runs the **Meta MCP** plugin (route `/wp-json/mcp/wp-content`, writes enabled); Claude Code has an entry for it, named `<site>-content`: `claude mcp add --transport http --scope user <site>-content https://<host>/wp-json/mcp/wp-content --header "Authorization: Basic <base64 of user:application-password>"`, run by the user in their own terminal. `wp.py`, `mcp_call.py`, `wp_upload.py` find the entry by name (user scope, then project scopes; `scripts/wp/mcpconf.py`); the credential never leaves it | content, Elementor data, REST |
| PageSpeed Insights API key | `PAGESPEED_API_KEY=...` in the work folder's `.env` (`init.py` creates it empty); a site folder's own `.env` wins; the `PAGESPEED_API_KEY` environment variable is the last fallback. The user edits the file; the key is never pasted into the chat or printed | `psi.py`, `judge*.sh` |
| LibreCrawl (optional) | `git clone https://github.com/PhialsBasement/LibreCrawl`, `python -m venv .venv`, `.venv/Scripts/pip install -r requirements.txt` (no Docker, no `playwright install`); set `LIBRECRAWL_DIR` | step 1c |
| metahotels-core (optional) | MetaHotels' own plugin, a local clone for generic toggles; ask the user where it is | references/site-plugin.md |

Never put a credential in site.json, a report or the skill: the MCP entry and `.env` hold them.

## The work folder

One folder holds every site and the two cross-site documents. Every tool runs with the **site folder** as its working
directory; the cross-site PDF build runs from the work folder.

```
<work folder>/
  metahotels.json           marks the work folder (init.py)
  .env                      PAGESPEED_API_KEY= (init.py; the user fills it in)
  optimization-results.md   score-vs-experience.md   (+ their PDFs)
  <site>/
    site.json   [.env]
    audit/          urls.txt, pages/ (crawl.sh), elementor/ (saved trees), judge-*.txt, links.json ...
    images/         list.json, originals/, optimized/, uploaded*.json
    rollback/       one file per changed snippet, template, element or setting, written before the change
    runs/<host>/    measure.js and psi.py output
    shots/          screenshots of the checks
    <site>-performance/   the site plugin (and its zip)
    performance-report-YYYY-MM-DD.md
```
A follow-up pass on a site uses `audit-YYYY-MM-DD/` so the first pass's files stay as they were.

## site.json

Copy `assets/site.example.json` into the site folder and fill it in during the audit. Only `host` and `mcp_server`
are required.

| Field | Meaning |
|---|---|
| `host` | `example.com` (no scheme). `origin` defaults to `https://<host>`; set it when the site uses `www.` |
| `mcp_server` | the MCP server entry for the site's content (`<site>-content`) |
| `psi_env` | path of the `.env` with `PAGESPEED_API_KEY` (default: the site folder's `.env` if it holds a key, else the work folder's) |
| `report` | `false` when the owner wants no report for this site (`--omit-report`): no `performance-report-*.md`, no section in the cross-site documents; results stay in `audit/` and are summarised in the chat |
| `post_types` | every post type with featured images or Elementor content: `post`, `page` and the hotel types (`offer`, `hotel_room`, `facility`, `destination`, `restaurant`...). `list-post-types` on the MCP lists them |
| `languages` | Polylang languages, first = default. Check every per-language template (references/testing.md) |
| `pages.inner`, `pages.carousel` | site-relative paths: an inner page with the same header (cold check), a page with carousels (lazy-load checks) |
| `selectors` | overrides for the browser checks when the defaults miss: `menu`, `menuParent`, `submenu`, `burger`, `mobileMenu`, `mobileMenuClose`, `sticky`, `mobileBar`, `hero`, `finderBar`, `finderWidget`, `finderHeading`, `topbarLinks` |
| `markers` | `{"name": "regex"}` the site plugin and fixes print (`<style id="<slug>-perf-entrance">`), counted per page by `markers.py`, `warm.sh`, `judge.sh` |
| `booking_links` | `{"Hotel": "https://reservation.mirai.com/..."}` exactly as the owner gave them, with the date. Never filled from another hotel or built by hand |
| `notes` | anything a later pass must know (CDN, plugins the owner wants kept, independent hotel: no links to group hotels) |

## Starting a site (first hour)

1. From the work folder: `python -I $S/site-init.py <site-url>`. It creates `<site>/`, `site.json` (host, MCP
   entry found by host, post types and languages from the Meta MCP status), checks the site, sitemap, MCP access
   (administrator, writes on) and the PageSpeed key, and writes `audit/onboarding-<date>.json`.
2. Ask the user for each item it lists (AskUserQuestion, most blocking first), record the answers in `site.json`,
   and run it again after the user adds an MCP entry or a key. Confirm the Chrome tab is logged into wp-admin
   (references/access.md).
3. `python -I $S/sitemap-urls.py` → `audit/urls.txt`; `bash $S/crawl.sh audit/urls.txt audit/pages` (background).
4. Ask the owner at the start, once: the Mirai booking link per hotel, whether a CDN or DNS change is planned, and
   which plugins or widgets they rely on that the pages do not show (drafts, seasonal popups). `site-init.py`
   lists these too.
