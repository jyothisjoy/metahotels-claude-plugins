---
name: hotel-seo
description: MetaHotels hotel SEO lists. Use when the user gives a hotel website and wants the SEO Priority / Nice-to-Have (Secondary) / Web Team lists, a re-check of the SEO agency's work against those lists, or runs /hotel-seo (init, init --check, <domain>, recheck <domain>). Crawls with LibreCrawl, audits in code, pulls Search Console, GA4 and Mirai, and renders copy-paste-ready PDF lists for the agency.
---

# hotel-seo

Turns one hotel website into three copy-paste-ready fix lists (Priority, Nice-to-Have, Web Team) that the external SEO agency finishes in one working day, then re-checks their work item by item. The goal is **direct bookings**, not SEO scores.

## Commands

| Command | What happens |
|---|---|
| `/hotel-seo init` | One-time setup on this machine (CLI or desktop Code tab only). Safe to re-run. |
| `/hotel-seo init --check` | Health check only. Works everywhere, including desktop chat. |
| `/hotel-seo <domain>` | Full run, start to finish without stopping: crawl + audit + Search Console + GA4 + Mirai → analysis → three PDFs. |
| `/hotel-seo recheck <domain>` | After the agency says "done": every item of the last lists is checked against the live site and the report is re-issued (Done / Partly / Open). |

No argument: ask for the hotel's website. A bare domain or URL in the message counts as `<domain>`.

## Two rules that make the reports trustworthy

1. **Numbers come from code, words from you.** Every count, page list and status comes from a tool result (`audit_site`, `inspect_pages`, crawl files, Search Console, GA4, Mirai). Never count by hand or estimate; quote the tool's number. If a tool didn't produce a number, don't state one.
2. **Facts need evidence.** `render_lists_pdf` runs a [CONFIRM] guard: sizes and ratings must be on the live site; room service / 24-hour, loyalty tiers, room count, occupancy, distances, check-in/out times, prices and discounts must be in `<domain>/hotel-facts.json` (hotel-confirmed). Anything else must say **[CONFIRM]**. Fix what it reports; don't bypass it (`allow_unverified` is only for Re-check lists).

## Tools

Three MCP servers come with this skill. Short names below; in Claude Code they appear prefixed (e.g. `mcp__plugin_hotel-seo_hotel-seo-tools__crawl_site`).

- **hotel-seo-tools**:
  - `crawl_site`, `job_status`, `list_crawls`, `export_crawl`, `read_crawl_file`: LibreCrawl crawl and its files ([references/librecrawl.md](references/librecrawl.md)).
  - `audit_site(crawl_dir, gsc_property, hotel_city)`: all counts in code. Per page: H1s, titles, metas, canonicals, robots, every JSON-LD block. Site-wide: canonicals that point to a redirect or 404, title suffixes and WordPress default titles, SEO plugin active and printing, robots.txt and sitemaps, Search Console's submitted sitemaps, indexable booking/account pages and archives, thin page groups, empty and junk pages, self-written reviews and conflicting hotel blocks, broken and redirected links grouped with a sitewide flag, dead or outdated booking links, phone codes, distance conflicts, prices in text, out-of-season wording, old years, another city in headings, blog posts with no booking link, browser-side translation. WordPress: plugins, exposed REST namespaces, public users, post authors, suspicious/backdated posts with trend, defacement text. Search Console: brand share now vs before, non-brand searches at positions 4–20, pages by impressions, old http/www versions, booking pages in search, Arabic and spam searches. Writes `findings.json` / `findings.md` / `site_text.json` / `replace_pairs.csv`.
  - `inspect_pages(urls, out_dir)`: renders pages desktop + mobile in Chromium: tags that actually fire, visible H1s, pop-ups, JSON-LD, screenshots.
  - `custom_search`, `test_redirects`: Custom Search and list-mode redirect test.
  - `mirai_reservations(hotel_id)`: bookings from the Mirai API (says so if credentials aren't set up; then use the Excel export).
  - `render_lists_pdf`: JSON list → PDF, with the [CONFIRM] guard.
  - `recheck_list`: runs each item's `checks` against the live site.
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
  Reports/                    the PDFs
  recheck-<YYYY-MM-DD>/       recheck crawl, results and re-issued lists
  run-notes-<date>.md         key numbers, decisions, missing inputs
```

**Desktop chat** has no shell or file access: read files with `read_crawl_file`, pass list content to `render_lists_pdf` as `data`, and take exports from files the user attaches.

## /hotel-seo init

Requires a shell (CLI or Code tab). In desktop chat, run `health_check` and tell the user to run init from Claude Code. The plugin root is two folders above this skill's base directory (`<plugin>/skills/hotel-seo` → `<plugin>`).

1. **uv.** If `uv --version` fails, install it: Windows `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`, macOS `curl -LsSf https://astral.sh/uv/install.sh | sh`. Then use the full path it prints (usually `~/.local/bin/uv`) for this session.
2. **Install everything except Google:** `uv run --quiet --project "<plugin>/server" python "<plugin>/setup/init.py" --skip-google` (timeout 10 min; set `PYTHONUTF8=1` on Windows). Installs LibreCrawl (pinned, localhost only, port 5057), Chromium, the desktop-app server copy and config, and the skill zip.
3. **Google sign-in** (one consent screen for GA4 and Search Console). Start `uv run --quiet --project "<plugin>/server" hotel-seo-auth` **in the background**; it opens the browser. Tell the user: sign in as **metahotels.m@gmail.com**; on "Google hasn't verified this app" click **Advanced → Go to Google Analytics MCP**, then Continue. Continue when the background task finishes. If no browser opened, rerun with `--no-browser` and give the user the `AUTH_URL` it prints.
4. **Mirai API (optional).** If the team has Mirai XML API credentials, ask the user to run `! uv run --quiet --project "<plugin>/server" hotel-seo-mirai-login` themselves (it asks for the login and password without showing them). Never ask for, type or store the password yourself.
5. **Check:** step 2's command with `--check` instead of `--skip-google`. All rows OK (LibreCrawl running = INFO is fine).
6. Tell the user what was set up and the desktop-app steps init printed (upload `~/.metahotels-seo/hotel-seo-skill.zip` in Settings → Capabilities → Skills, then quit and reopen). In Claude Code, `/mcp` reconnects `hotel-seo-gsc` and `hotel-seo-ga4` if they started before the sign-in.

Never commit, print or paste token files, the Mirai credentials or the Google password.

## /hotel-seo <domain>: full run

Fully automatic: **do not stop to ask questions.** Anything you can't get becomes **[CONFIRM]** or a line in "Missing inputs". Read [references/playbook.md](references/playbook.md) first; it is the method. [references/team.md](references/team.md) has known IDs and the message templates.

1. **Set up.** Normalise the domain (no scheme, no `www.`), create `<domain>/`, read `hotel.json`, `hotel-facts.json` and the latest `run-notes-*.md` if they exist. Look for files the user dropped in (Mirai reservations export, Search Console indexing drilldowns, Links export; see [references/inputs-checklist.md](references/inputs-checklist.md)).
2. **Start the crawl** (slowest step): `crawl_site("https://<domain>/", "<domain>/crawl-<date>")`. If the homepage redirects to another host, crawl the final host.
3. **While it runs:**
   - **Search Console**: property (prefer `sc-domain:<domain>`). Last 3 months vs the previous 3: queries, pages, countries, devices; sitemaps.
   - **GA4**: the property whose name or stream matches; check the hostname if numbers look like another site's. Last 90 days: events (purchase count + revenue, refunds), source / medium with revenue, country.
   - **Mirai**: `mirai_reservations(<id>)` (ID from `team.md` or the site's booking links), else the Excel export, else "Missing inputs". Use it for seasonality (by stay month), channel mix, packages and offers sold that have no web page. Also check the live booking engine: offers, member rate, cancellation terms vs what the site claims.
   - **Rendered pages**: `inspect_pages` on the homepage, 2–3 room pages, offers, contact and one blog post. Use its tags (not raw HTML) for any tracking statement, and look at the mobile screenshots.
4. **When the crawl is done:** `audit_site(crawl_dir, gsc_property)`, then read `findings.md` first (the playbook's table in section 3 maps each of its sections to a list item), `overview.md`, and `findings.json` / the CSVs with `read_crawl_file` for the URLs behind each count (filter, don't read whole files). `custom_search` only for known risks (old operator, sister hotels, false claims).
5. **Analyse** with the playbook. Apply its severity rule: anything on the homepage, room pages, offers, contact or the booking path goes on the Priority list, and so do canonicals that block indexing and sitewide broken links. Security findings from the audit go at the top of the Web Team list with full counts and trend, and a homepage `noindex` or defacement text is raised in the finish message as urgent. Check every finding on the live site before listing it. Compare the booking engine with the site (offers sold with no page, expired offers, loyalty benefits).
6. **Write the lists** as JSON following [templates/lists.schema.json](templates/lists.schema.json) (see [examples/al-bahar-priority.json](examples/al-bahar-priority.json)): Priority (playbook section 4: lettered items, a `lead` box, a `working` table), Nice-to-Have (section 5: numbered, `hold` for items waiting on the hotel), Web Team (section 6). Use `file_number: "auto"` and the subtitle line with the order across hotels (team.md). Exact copy-paste text for every title, meta, H1, alt text, redirect rule and schema block; prose to paste goes in `paste` blocks. Each item ends with a "Check:" line for the agency. **Every section gets `checks`** that are true once the work is done (expected titles/metas/H1s, H1 count, redirects, status codes, text or links that must be gone or present, schema counts, alt text); use `manual` only for what can't be fetched. Save to `<domain>/lists/`.
7. **Render** each with `render_lists_pdf(out_dir="<domain>/Reports", json_path=..., crawl_dir=<crawl>, facts_file="<domain>/hotel-facts.json")`. If the guard returns unverified phrases, fix them (mark [CONFIRM], correct to what the site says, or remove) and render again. Priority list target: 3–4 A4 pages; tighten wording before cutting items. If the result has a `warning` about a nearly empty last page, tighten and render again.
8. **Save** `hotel.json` and `run-notes-<date>.md` (key numbers with their source tool, decisions, missing inputs, [CONFIRM] questions).
9. **Finish** with a short message: the PDF paths; the top 3 Priority items with their booking reason; **Missing inputs** by their checklist names; the hotel-contact message (fact and offer questions) and the SEO agency message from `team.md`, ready to paste.

## /hotel-seo recheck <domain>

Re-checks the agency's work against the points raised, then re-issues the report. Playbook section 7.

1. Find the latest lists in `<domain>/lists/` (Priority first; Nice-to-Have too if it was sent). Lists made before checks existed: add `checks` to each section from its exact text first.
2. If the user has the agency's change list (WhatsApp) or the hotel's answers to [CONFIRM] questions, take them; add confirmed facts to `hotel-facts.json` with the source. Don't wait for them otherwise.
3. Re-crawl: `crawl_site` into `<domain>/recheck-<date>/crawl`, then `audit_site` on it (new issues, security trend).
4. `recheck_list(list_json, out_dir="<domain>/recheck-<date>", crawl_dir=<recheck crawl>)` for each list. It marks every item Done / Partly / Open / Manual from the live site and writes a Re-check list JSON and an open-items list JSON.
5. Edit the Re-check JSON: a short thank-you that says what's now live, a one-line note per item, the agency's WhatsApp context, and lettered sections with the exact fix still needed. Resolve Manual items with Search Console (sitemaps), `inspect_pages` or the agency's messages where you can. Add the hotel's confirmed corrections as their own lettered sections. Add any new Priority-type problems from the re-crawl audit as new lettered sections.
6. Render the Re-check list (`allow_unverified=true`: it quotes the live site) and the open-items list (with the guard) into `<domain>/Reports/`.
7. Finish with: Done / Partly / Open / Waiting counts, what's still open in one line each, anything the agency's changes broke (a key page now `noindex`, a title pasted onto the wrong page) at the very top, and the agency message ready to paste (fixes go at the top of tomorrow's send).

## Ground rules (full list in playbook section 1)

- Direct bookings first: every item has a booking reason with real numbers.
- Copy-paste ready: the agency writes nothing themselves.
- Never change offers or prices. Unverified facts stay **[CONFIRM]** until the hotel confirms.
- Web team items (analytics, speed, templates, theme code, security, hidden broken files) go on the Web Team list only.
- Alt text only after looking at each image.
- Full counts, never samples; check every finding on the live site, desktop and mobile.

## Keeping the method current

When a hotel teaches something new, add it to the playbook's "Lessons learned" (section 10) in this plugin's repo and bump the plugin version, so the whole team gets it on the next `/plugin update`.
