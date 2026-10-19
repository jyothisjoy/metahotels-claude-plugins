---
name: hotel-seo
description: MetaHotels hotel SEO lists. Use when the user gives a hotel website and wants the SEO Priority / Nice-to-Have (Secondary) / Web Team lists, a re-check of the SEO agency's work against those lists, site monitoring, or runs /hotel-seo (init, init --check, <domain>, recheck <domain>, monitor <domain>). Crawls with LibreCrawl, audits in code, pulls Search Console, GA4 and Mirai, and renders copy-paste-ready lists for the agency as PDF, Word and Google Docs.
---

# hotel-seo

Turns one hotel website into three copy-paste-ready fix lists (Priority, Nice-to-Have, Web Team) that the external SEO agency finishes in one working day, then re-checks their work item by item. The goal is **direct bookings**, not SEO scores.

## Commands

| Command | What happens |
|---|---|
| `/hotel-seo init` | One-time setup on this machine (CLI or desktop Code tab only). Safe to re-run. |
| `/hotel-seo init --check` | Health check only. Works everywhere, including desktop chat. |
| `/hotel-seo <domain>` | Full run, start to finish without stopping: crawl + audit + Search Console + GA4 + Mirai → analysis → three lists (PDF, Word and Google Doc each). |
| `/hotel-seo recheck <domain>` | After the agency says "done": every item of the last lists is checked against the live site and the report is re-issued (Done / Partly / Open). |
| `/hotel-seo monitor <domain>` | What changed since the last run: suspicious posts, spam searches, dead booking links, tags, homepage, open MCP routes. `monitor add <domain>` puts it on the daily schedule; `monitor` alone runs every scheduled site. |

No argument: ask for the hotel's website. A bare domain or URL in the message counts as `<domain>`.

## Two rules that make the reports trustworthy

1. **Numbers come from code, words from you.** Every count, page list and status comes from a tool result (`audit_site`, `inspect_pages`, crawl files, Search Console, GA4, Mirai). Never count by hand or estimate; quote the tool's number. If a tool didn't produce a number, don't state one.
2. **Facts need evidence.** `render_lists_pdf` runs a [CONFIRM] guard: sizes and ratings must be on the live site; room service / 24-hour, loyalty tiers, room count, occupancy, distances, check-in/out times, prices and discounts must be in `<domain>/hotel-facts.json` (from the hotel information sheet, the hotel contact, or the live booking engine via `booking_engine_snapshot`). Anything else must say **[CONFIRM]**. Fix what it reports; don't bypass it (`allow_unverified` is only for Re-check lists).

## Tools

Three MCP servers come with this skill. Short names below; in Claude Code they appear prefixed (e.g. `mcp__plugin_hotel-seo_hotel-seo-tools__crawl_site`).

- **hotel-seo-tools**:
  - `crawl_site`, `job_status`, `list_crawls`, `export_crawl`, `read_crawl_file`: LibreCrawl crawl and its files ([references/librecrawl.md](references/librecrawl.md)).
  - `audit_site(crawl_dir, gsc_property, hotel_city, mirai_id)`: all counts in code, over every page (pages the crawl missed are added from the sitemaps and the WordPress API). Renders the homepage for the tags that actually fire (`tags_rendered`: the only source for tracking statements). Probes MCP / site-control REST routes (OPEN or requires login) and flags a leftover `llms.txt`. Per page: H1s, titles, metas, canonicals, robots, every JSON-LD block. Site-wide: canonicals that point to a redirect or 404, title suffixes and WordPress default titles, SEO plugin active and printing, robots.txt and sitemaps, Search Console's submitted sitemaps, indexable booking/account pages and archives, thin page groups, empty and junk pages, self-written reviews and conflicting hotel blocks, broken and redirected links grouped with a sitewide flag, dead or outdated booking links, phone codes, distance conflicts, prices in text, out-of-season wording, old years, another city in headings, blog posts with no booking link, browser-side translation. WordPress: plugins, exposed REST namespaces, public users, post authors, suspicious/backdated posts with trend, defacement text. Search Console: brand share now vs before, non-brand searches at positions 4–20, pages by impressions, old http/www versions, booking pages in search, Arabic and spam searches. Writes `findings.json` / `findings.md` / `site_text.json` / `replace_pairs.csv`.
  - `inspect_pages(urls, out_dir)`: renders pages desktop + mobile in Chromium: tags that actually fire, visible H1s, pop-ups, JSON-LD, screenshots.
  - `custom_search`, `test_redirects`: Custom Search and list-mode redirect test.
  - `booking_engine_snapshot(site, hotel_id, out_dir, crawl_dir, facts_file)`: a browser session on the live Mirai engine for 3 sample stays: rooms, offers, member discount, boards, cancellation terms, prices, the price calendar, and the website compared with it (room sizes, offers sold with no page, offer pages with nothing on sale). Adds the engine's facts to `hotel-facts.json`.
  - `keyword_volumes(keywords_list, out_dir, countries, language)` and `keyword_ideas(out_dir, seeds, url, countries, language)`: Google Ads Keyword Planner through the API (average monthly searches, 12 months of volumes, competition, bid range). Needs Google Ads set up in `health_check`; otherwise fall back to `import_keyword_csv`.
  - `import_keyword_csv(files, out_dir, label)`: Keyword Planner CSV exports read in code (Arabic keeps its order). Fallback when the API isn't set up on this machine.
  - `import_facts_sheet(sheet, facts_file, filled_on)`: the hotel information sheet (.xlsx, .csv or a shared Google Sheets link) into `hotel-facts.json`.
  - `rate_parity(mirai_id, days, source)`: the daily Magic Parity feed (behind the 6am leak report): Beat / Meet / Lose of the hotel's site against each OTA, by device, guest country and lead time, worst losses with screenshots.
  - `index_status(gsc_property, site, out_dir, crawl_dir)`: URL Inspection for every crawled and sitemap URL, grouped like Search Console's Page indexing report (2,000 a day per property; cached, rerun to continue).
  - `bing_report(site, out_dir)`: Bing Webmaster incoming links (pages, counts, linking sites, anchors) and Bing sitemap status.
  - `mirai_reservations(hotel_id, date_from, date_to, by, out_dir)`: bookings from the Mirai XML API (credentials: `MIRAI_USER` / `MIRAI_PASS` in the `.env` of the work folder). `by="booking"` = bookings made in the range (default 1 Mar → today); `by="checkin"` = arrivals (default the next 90 days: what's on the books). Bookings, cancellation rate, revenue, ADR, seasonality by stay month, revenue per **offer name** and **room type**, club sign-ups, promo codes, channel, guest country. No guest personal data is kept. Says so if credentials aren't set up; then use the Excel export. One call per 3 minutes, so the first long range takes several minutes: start it early and do other work.
  - `render_lists_pdf`: JSON list → PDF, **Word (.docx) and Google Doc** (same link and file number on every re-render), with the [CONFIRM] guard and a severity warning for Priority-type pages on the other lists.
  - `presend_check(list_json, crawl_dir)`: live diff before sending; drops items already fixed, marks partly done ones.
  - `recheck_list`: runs each item's `checks` against the live site.
  - `monitor_site(site, gsc_property, add_to_schedule)`: changes since the last run, with alerts.
  - `health_check`, `librecrawl_control`.
- **hotel-seo-gsc**: Search Console. Read-only use only: never add, delete or submit anything.
- **hotel-seo-ga4**: Google Analytics 4.

Long jobs return `state: running` and a `job_id`: keep calling `job_status(job_id)` until `done`, and do other work in between. If a tool is missing, run `health_check` (or ask the user to run `/hotel-seo init`) instead of working around it.

**Where files go.** Relative paths resolve against the folder Claude was started in (CLI / Code tab), or `~/Documents/MetaHotels SEO` in desktop chat. Per hotel:

```
<domain>/
  hotel.json                  IDs found: GA4 property, GSC property, Mirai ID, names
  hotel-facts.json            confirmed facts with source: {"facts": [{"fact": "...", "source": "..."}]}
                              (offers, discounts and member benefits read on the live booking engine
                              may go in with source "booking engine, <date>")
  crawl-<YYYY-MM-DD>/         crawl files + findings.json / findings.md / site_text.json + inspect/
  lists/<list>-<date>.json    the lists you write (they carry the checks recheck runs)
  Reports/                    the PDFs and Word files ("25 - Al Bahar Priority SEO List (14 Oct)", "27 - Al Bahar Priority Re-check 2 (21 Oct)")
  recheck-<YYYY-MM-DD>/       recheck crawl, results and re-issued lists
  run-notes-<date>.md         key numbers, decisions, missing inputs
```

**Desktop chat** has no shell or file access: read files with `read_crawl_file`, pass list content to `render_lists_pdf` as `data`, and take exports from files the user attaches.

## /hotel-seo init

Requires a shell (CLI or Code tab). In desktop chat, run `health_check` and tell the user to run init from Claude Code. The plugin root is two folders above this skill's base directory (`<plugin>/skills/hotel-seo` → `<plugin>`).

1. **uv.** If `uv --version` fails, install it: Windows `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`, macOS `curl -LsSf https://astral.sh/uv/install.sh | sh`. Then use the full path it prints (usually `~/.local/bin/uv`) for this session.
2. **Install everything except Google:** `uv run --quiet --project "<plugin>/server" python "<plugin>/setup/init.py" --skip-google` (timeout 10 min; set `PYTHONUTF8=1` on Windows). Installs LibreCrawl (pinned, localhost only, port 5057), Chromium, the desktop-app server copy and config, and the skill zip.
3. **Google sign-in** (one consent screen for GA4, Search Console, Google Docs output and Google Ads Keyword Planner; Docs only touches files the plugin creates). First save the Ads account IDs: `uv run --quiet --project "<plugin>/server" hotel-seo-ads-login --manager 437-179-3247` (nothing secret). Then start `uv run --quiet --project "<plugin>/server" hotel-seo-auth --with-ads` **in the background**; it opens the browser. Tell the user: sign in as **metahotels.m@gmail.com** and allow every permission; if Google says the app isn't verified, click **Advanced → Go to MetaHotels SEO**, then Continue. Google may ask the account to verify it's you (passkey or password) for the Ads permission. Continue when the background task finishes. If no browser opened, rerun with `--no-browser` and give the user the `AUTH_URL` it prints.
4. **Keyword Planner access (already done; for troubleshooting).** No developer token: Google retired them on 9 Sep 2026. Access comes from the `metahotels-analytics` Cloud project, which has **Basic** Google Ads API access (granted 19 Oct 2026; Explorer would block Keyword Planner), and metahotels.m@gmail.com has Read only access to the **MetaHotels Manager** Ads account (437-179-3247). An access-level error from `keyword_volumes` means one of those changed.
5. **Rate parity feed (optional).** On a machine that has the Magic Parity project, ask the user to run `! uv run --quiet --project "<plugin>/server" hotel-seo-parity-login --from-env "<path to magicparity>\.env"`; otherwise plain `hotel-seo-parity-login`, which asks for the Azure connection string (hidden). Never read or type it yourself.
5b. **Bing Webmaster (optional).** Ask the user to run `! uv run --quiet --project "<plugin>/server" hotel-seo-bing-login` and paste the API key from Bing Webmaster Tools → Settings → API access (hidden).
5c. **Mirai API.** The tools read `MIRAI_USER` and `MIRAI_PASS` from the `.env` file in the work folder (the folder Claude was started in; desktop chat: `~/Documents/MetaHotels SEO`). If `health_check` says they're missing, ask the user to add both lines to that `.env` themselves (the values come from the team). Never ask for, read, print or type the values yourself, and never put the `.env` in a git repo. (`hotel-seo-mirai-login` still works as a fallback that stores them in `~/.metahotels-seo/mirai.json`.)
6. **Check:** step 2's command with `--check` instead of `--skip-google`. All rows OK (LibreCrawl running = INFO is fine).
7. Tell the user what was set up and the desktop-app steps init printed (upload `~/.metahotels-seo/hotel-seo-skill.zip` in Settings → Capabilities → Skills, then quit and reopen). In Claude Code, `/mcp` reconnects `hotel-seo-gsc` and `hotel-seo-ga4` if they started before the sign-in.

Never commit, print or paste token files, the Mirai credentials or the Google password.

## /hotel-seo <domain>: full run

Fully automatic except for one question: the **hotel information sheet** (step 2a). Otherwise **do not stop to ask questions.** Anything you can't get becomes **[CONFIRM]** or a line in "Missing inputs". Read [references/playbook.md](references/playbook.md) first; it is the method. [references/team.md](references/team.md) has known IDs and the message templates.

1. **Set up.** Normalise the domain (no scheme, no `www.`), create `<domain>/`, read `hotel.json`, `hotel-facts.json` and the latest `run-notes-*.md` if they exist. Look for files the user dropped in (Mirai reservations export, Search Console indexing drilldowns, Links export; see [references/inputs-checklist.md](references/inputs-checklist.md)).
2. **Start the crawl** (slowest step): `crawl_site("https://<domain>/", "<domain>/crawl-<date>")`. If the homepage redirects to another host, crawl the final host.
2a. **Ask for the hotel information sheet** right after the crawl has started (the crawl keeps running): "Do you have the hotel information sheet for <hotel>? Attach it, give its path or a Google Sheets link, or say *none*." Skip the question if `<domain>/hotel-facts.json` already has facts with source "hotel info sheet" or a sheet is already in `<domain>/`. When it arrives, save a copy in `<domain>/` and run `import_facts_sheet(sheet, "<domain>/hotel-facts.json", filled_on=<date it was filled in>)` (.xlsx / .csv / Sheets link); for PDF or Word sheets read every field yourself and add each fact with source "hotel info sheet, <date>". Where the sheet and the site or booking engine disagree, the sheet wins for the copy and the disagreement becomes a credibility fix. *None* → carry on; hotel facts stay [CONFIRM].
3. **While it runs:**
   - **Search Console**: property (prefer `sc-domain:<domain>`). Last 3 months vs the previous 3: queries, pages, countries, devices; sitemaps.
   - **Keyword Planner**: once Search Console is in, `keyword_volumes(<the non-brand money searches and the title/H1 phrases you plan>, "<domain>/keywords", countries=[<hotel's country>], language="en")`, plus `language="ar"` for the Arabic searches; `keyword_ideas(out_dir, seeds=[area + "hotel", room types, 5–10 phrases], url="https://<domain>/")` for searches the site doesn't rank for yet. Add feeder markets (e.g. GB, SA, RU, DE) when Search Console or GA4 show them. Use the volumes to choose title and H1 phrases and to rank the money searches; quote them in the "why" lines (e.g. "hotels in fujairah": <N> searches a month, Keyword Planner, UAE). If `health_check` shows Google Ads not set up, fall back to CSV exports in `<domain>/keywords/` with `import_keyword_csv`; none → **Keyword Planner** under Missing inputs and rank by Search Console impressions instead.
   - **GA4**: the property whose name or stream matches; check the hostname if numbers look like another site's. Last 90 days: events (purchase count + revenue, refunds), source / medium with revenue, country.
   - **Rate parity**: `rate_parity(mirai_id=<id>, days=7)`, and `source="gha"` for Google Hotel Ads. If the site Loses on 20%+ of priced checks, parity is the first Priority item (lead box): page fixes won't win a booking the OTAs sell cheaper. Name the OTAs, devices and markets where it loses; never change prices on the site, it's a revenue team action.
   - **Mirai bookings**: start it early (it's slow on a first run): `mirai_reservations(<id>, out_dir="<domain>/mirai")` (ID from `team.md` or the site's booking links), and `by="checkin"` for what's on the books for the coming months. Else the Excel export, else "Missing inputs". If it warns that the login doesn't cover the hotel, the Mirai ID is wrong or the hotel isn't on this login: say so under Missing inputs. Use it for the lead box timing (peak stay months and their revenue), seasonality (by stay month), offers sold by name (packages with no web page, expired offer pages that still sell), room types that sell, club sign-ups (the member-rate message), families (kids' content), promo codes and guest countries.
   - **Rendered pages**: `inspect_pages` on 2–3 room pages, offers, contact and one blog post (the audit renders the homepage). Use rendered tags only (`tags_rendered` / `inspect_pages`), never the raw-HTML IDs, for any tracking statement, and look at the mobile screenshots.
4. **When the crawl is done:** `audit_site(crawl_dir, gsc_property, mirai_id=<id>)` (the Mirai ID lets it flag Book Now links that open another hotel), then read `findings.md` first (the playbook's table in section 3 maps each of its sections to a list item), `overview.md`, and `findings.json` / the CSVs with `read_crawl_file` for the URLs behind each count (filter, don't read whole files). `custom_search` only for known risks (old operator, sister hotels, false claims).
4a. **Then the booking engine:** `booking_engine_snapshot(site, <id>, "<domain>/crawl-<date>/booking-engine", crawl_dir, facts_file="<domain>/hotel-facts.json", peak_month=<peak from Mirai/GA4, else 12>)`. Read `booking_engine.md`. Offers sold with no page → Nice-to-Have new page (held for hotel details); offer pages with nothing on sale → Priority expired pages (dining and spa offers excepted); size or discount mismatches → credibility fixes; what matches → the "already working" table.
4b. **Indexing and links:** `index_status(gsc_property, site, "<domain>/crawl-<date>/indexing", crawl_dir)` (add old URLs from any 404 export as `extra_urls`; if it says URLs are left, mention it in the run notes) and `bing_report(site, "<domain>/crawl-<date>")`. These replace the Search Console indexing drilldowns, the Links export and the Bing sitemap screenshot.
5. **Analyse** with the playbook. Apply its severity rule: anything on the homepage, room pages, offers, contact or the booking path goes on the Priority list, and so do canonicals that block indexing and sitewide broken links. Security findings from the audit go at the top of the Web Team list with full counts and trend, and a homepage `noindex` or defacement text is raised in the finish message as urgent. Check every finding on the live site before listing it. Compare the booking engine with the site (offers sold with no page, expired offers, loyalty benefits).
6. **Write the lists** as JSON following [templates/lists.schema.json](templates/lists.schema.json) (see [examples/al-bahar-priority.json](examples/al-bahar-priority.json)): Priority (playbook section 4: lettered items, a `lead` box, a `working` table), Nice-to-Have (section 5: numbered, `hold` for items waiting on the hotel), Web Team (section 6). Use `file_number: "auto"` and the subtitle line with the order across hotels (team.md). Exact copy-paste text for every title, meta, H1, alt text, redirect rule and schema block; prose to paste goes in `paste` blocks. Each item ends with a "Check:" line for the agency. **Every section gets `checks`** that are true once the work is done (expected titles/metas/H1s, H1 count, redirects, status codes, text or links that must be gone or present, schema counts, alt text); use `manual` only for what can't be fetched. Save to `<domain>/lists/`.
6b. **Pre-send diff:** `presend_check(list_json, crawl_dir)` on each list. It writes `<list>-presend.json` without the items already fixed on the live site and with partly done ones marked; render that file. If items were dropped, re-letter and re-read the summary and lead.
7. **Render** each with `render_lists_pdf(out_dir="<domain>/Reports", json_path=<presend file>, crawl_dir=<crawl>, facts_file="<domain>/hotel-facts.json")`. It makes the PDF, the Word file and the Google Doc. If the guard returns unverified phrases, fix them (mark [CONFIRM], correct to what the site says, or remove) and render again. If it returns a `severity_warning`, move those items to the Priority list or give the section a `not_priority_because`. If `google_doc.published` is false, say why in the finish message (usually: sign in again for Docs) and give the `.docx` path (upload it to Drive and open with Google Docs). Priority list target: 3–4 A4 pages; tighten wording before cutting items. If the result has a `warning` about a nearly empty last page, tighten and render again.
8. **Save** `hotel.json` and `run-notes-<date>.md` (key numbers with their source tool, decisions, missing inputs, [CONFIRM] questions).
9. **Finish** with a short message: the Google Doc links (the agency copies from these) and the PDF and Word paths; the top 3 Priority items with their booking reason; **Missing inputs** by their checklist names; the hotel-contact message (fact and offer questions) and the SEO agency message from `team.md`, ready to paste.

## /hotel-seo recheck <domain>

Re-checks the agency's work against the points raised, then re-issues the report. Playbook section 7.

1. Find the latest lists in `<domain>/lists/` (Priority first; Nice-to-Have too if it was sent). Lists made before checks existed: add `checks` to each section from its exact text first.
2. If the user has the agency's change list (WhatsApp) or the hotel's answers to [CONFIRM] questions, take them; add confirmed facts to `hotel-facts.json` with the source. Don't wait for them otherwise.
3. Re-crawl: `crawl_site` into `<domain>/recheck-<date>/crawl`, then `audit_site` on it (new issues, security trend).
4. `recheck_list(list_json, out_dir="<domain>/recheck-<date>", crawl_dir=<recheck crawl>)` for each list. It marks every item Done / Partly / Open / Manual from the live site, numbers the round (the second re-check of a list is round 2) and writes e.g. `priority-recheck-2.json` and `priority-open-items-after-recheck-2.json`. Re-check the latest open-items list if there is one, else the list as sent; either way the round counts on.
5. Edit the Re-check JSON: a short thank-you that says what's now live, a one-line note per item, the agency's WhatsApp context, and lettered sections with the exact fix still needed. Resolve Manual items with Search Console (sitemaps), `bing_report` (Bing sitemaps), `index_status` (indexing), `inspect_pages` or the agency's messages where you can. Add the hotel's confirmed corrections as their own lettered sections. Add any new Priority-type problems from the re-crawl audit as new lettered sections.
6. Render the Re-check list (`allow_unverified=true`: it quotes the live site) and the open-items list (with the guard) into `<domain>/Reports/`. They are named "<NN> - <hotel> Priority Re-check 2 (<date>)" and "<NN> - <hotel> Priority Open Items after Re-check 2 (<date>)".
7. Finish with: Done / Partly / Open / Waiting counts, what's still open in one line each, anything the agency's changes broke (a key page now `noindex`, a title pasted onto the wrong page) at the very top, and the agency message ready to paste (fixes go at the top of tomorrow's send).

## /hotel-seo monitor

- `monitor <domain>`: `monitor_site("https://<domain>", gsc_property)`. The first run saves a baseline. Report alerts first (they need action today; security alerts go to the MetaHotels team the same day), then changes, then the report path.
- `monitor add <domain>`: `monitor_site(..., add_to_schedule=true)`, then offer to schedule the daily run if it isn't yet (needs a shell; ask before creating it). Windows: `schtasks /Create /SC DAILY /ST 07:00 /TN "hotel-seo-monitor" /TR "\"<uv path>\" run --quiet --project \"<plugin>\server\" hotel-seo-monitor"`. macOS: a crontab line `0 7 * * * <uv path> run --quiet --project "<plugin>/server" hotel-seo-monitor`. It runs every site in `~/.metahotels-seo/monitor/sites.json` and writes reports to `~/.metahotels-seo/monitor/reports/`.
- `monitor` with no domain: run every scheduled site and summarise the alerts.

## Ground rules (full list in playbook section 1)

- Direct bookings first: every item has a booking reason with real numbers.
- Copy-paste ready: the agency writes nothing themselves.
- Never change offers or prices. Unverified facts stay **[CONFIRM]** until the hotel confirms.
- Web team items (analytics, speed, templates, theme code, security, hidden broken files) go on the Web Team list only.
- Alt text only after looking at each image.
- Full counts, never samples; check every finding on the live site, desktop and mobile.

## Keeping the method current

When a hotel teaches something new, add it to the playbook's "Lessons learned" (section 10) in this plugin's repo and bump the plugin version, so the whole team gets it on the next `/plugin update`.
