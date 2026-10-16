# MetaHotels Claude plugins

Private. Contains the **hotel-seo** plugin (v0.4.0): give Claude a hotel website and get the SEO agency's **Priority**, **Nice-to-Have** and **Web Team** lists as PDFs, then re-check the agency's work against them item by item. The goal is direct bookings, not SEO scores.

- [What it does](#what-it-does)
- [Before you start](#before-you-start-once-per-person)
- [Install](#install-once-per-machine-windows-or-macos)
- [Optional connections](#optional-connections)
- [Use](#use)
- [What a run produces](#what-a-run-produces)
- [Tools](#tools)
- [Update](#update)
- [Troubleshooting](#troubleshooting)
- [Security](#security)
- [What's inside](#whats-inside)
- [Changing the method](#changing-the-method)
- [Status and open items](#status-and-open-items)

---

## What it does

`/hotel-seo <domain>` runs start to finish and asks only one question (the hotel information sheet):

1. **Crawls** the site with LibreCrawl (installed and started automatically, localhost only).
2. **Asks for the hotel information sheet** while the crawl runs; its facts become "confirmed" for the lists. Answer *none* to carry on.
3. **Pulls data:** Search Console, GA4, rate parity (Magic Parity feed), Mirai bookings, Keyword Planner volumes, whichever are set up.
4. **Audits in code:** every count comes from a script, never from the model (titles, H1s, canonicals, schema, broken and redirected links, booking links, sitemaps, indexing, security signs, copy conflicts).
5. **Reads the live booking engine** in a browser for 3 sample stays and compares it with the website (rooms, offers, member discount, prices).
6. **Checks indexing** URL by URL with Google's URL Inspection API, and incoming links and Bing sitemaps with Bing Webmaster Tools.
7. **Writes the three lists** as copy-paste-ready text (exact titles, metas, H1s, redirects, schema), with a **[CONFIRM] guard** that refuses unverified hotel facts.
8. **Renders PDFs** in the team's format: `25 - Atana Priority SEO List (14 Oct).pdf`.

`/hotel-seo recheck <domain>` re-crawls, runs every list item's stored checks against the live site, marks each **Done / Partly / Open / Waiting**, and re-issues the report plus a list of only the open items.

---

## Before you start (once per person)

1. **Repo access.** Ask the repo owner to add your GitHub account as a collaborator on `jyothisjoy/metahotels-seo`.
2. **GitHub login on your computer.** Claude installs the plugin with a normal `git clone`, so your git must be able to reach the private repo. Easiest: install the [GitHub CLI](https://cli.github.com/) and run `gh auth login` (GitHub.com → HTTPS → log in with a browser). Git Credential Manager (comes with Git for Windows) or an SSH key also work.
   Test: `git clone https://github.com/jyothisjoy/metahotels-seo.git` should work without errors (delete the folder afterwards).
3. **Claude Code**, in the terminal or the Code tab of the Claude desktop app.
4. **The shared Google account** password for **metahotels.m@gmail.com**, or the device that holds its passkey (ask the team; never put it in this repo).

---

## Install (once per machine, Windows or macOS)

1. **Add the plugin** in Claude Code (terminal, or the desktop app's Code tab):
   ```
   /plugin marketplace add jyothisjoy/metahotels-seo
   /plugin install hotel-seo@metahotels
   ```
   This opens the plugin dialog. If the `/plugin` menu doesn't appear in the Code tab, run the same in a terminal; the terminal and the Code tab share the same plugins:
   ```
   claude plugin marketplace add jyothisjoy/metahotels-seo
   claude plugin install hotel-seo@metahotels
   ```
   **From a cloned folder instead:** `claude plugin marketplace add "C:\path\to\metahotels-seo"`, then the same install line. Update later with `git pull` in that folder. Keep the folder where it is.

   Then start a new Claude Code session.
2. **Run `/hotel-seo init`.** It installs `uv` if needed, LibreCrawl (pinned version, 127.0.0.1:5057), Chromium, the desktop-app setup and the skill zip, then runs the **Google sign-in** for GA4 and Search Console. About 5–10 minutes.
   - Sign in as **metahotels.m@gmail.com**. If the browser asks for a passkey on another device, use the Chrome profile that is already signed in to that account, or **Try another way** → password.
   - "Google hasn't verified this app" → **Advanced → Go to Google Analytics MCP** → Continue.
   - If init says "Google sign-in: skipped", it isn't finished: ask Claude to run the sign-in step, or run `uv run --quiet --project "<plugin>/server" hotel-seo-auth` yourself.
3. **Optional connections:** see the next section. Each takes a minute and the run works without them.
4. **Desktop chat (optional).** Upload `~/.metahotels-seo/hotel-seo-skill.zip` in Settings → Capabilities → Skills, then fully quit and reopen the desktop app. Desktop chat has no `/plugin` command; this zip plus the setup from step 2 is how it gets the skill and tools.
5. **Check:** `/hotel-seo init --check`. Required rows must be OK; optional connections show "optional, not set up" until you add them.

---

## Optional connections

Each one is a one-off command per machine. Credentials are typed by **you** into a hidden prompt and stored only in `~/.metahotels-seo/`; Claude never asks for, sees or types them. `<plugin>` is the plugin folder (Claude prints the exact command).

| Connection | What it adds | What you need | Command |
|---|---|---|---|
| **Rate parity feed** | Beat / Meet / Lose of the hotel's own site vs each OTA (by OTA, device, guest country, lead time, worst losses with screenshots) from the daily Magic Parity files; names the hotel behind any Mirai ID | The Azure storage connection of the parity feed (the Magic Parity project's `.env` has it) | `uv run --quiet --project "<plugin>/server" hotel-seo-parity-login --from-env "D:\react\magicparity\.env"` (or without `--from-env` to paste it) |
| **Bing Webmaster** | Incoming links (replaces the Search Console Links export) and Bing sitemap status (replaces the Bing screenshot) | API key: Bing Webmaster Tools → Settings → API access | `uv run --quiet --project "<plugin>/server" hotel-seo-bing-login` |
| **Mirai bookings** | Bookings, revenue, ADR, seasonality, channels, offers sold (replaces the Mirai Excel export) | Mirai XML API credentials from integrations@mirai.com | `uv run --quiet --project "<plugin>/server" hotel-seo-mirai-login` |
| **Google Ads Keyword Planner** | Monthly search volumes, competition and bid ranges in English and Arabic for UAE, Egypt, feeder markets or worldwide (replaces the Keyword Planner CSVs) | Manager account **582-679-1252** with **Explorer** access or higher, client account **511-058-4835**, the developer token, and a Google sign-in that includes Ads | 1. `uv run --quiet --project "<plugin>/server" hotel-seo-ads-login` 2. `uv run --quiet --project "<plugin>/server" hotel-seo-auth --with-ads` |

Notes:
- **Keyword Planner:** Google may ask metahotels.m@gmail.com to "verify it's you" for the Ads permission (passkey or password). Test access returns no real data: check Google Cloud → Google Ads API → Access levels shows Explorer or higher.
- **Search Console and GA4** need no extra setup beyond init; the account must have access to each hotel's property (see the inputs checklist).

---

## Use

```
/hotel-seo atanahotel.com            full run (asks once for the hotel information sheet)
/hotel-seo recheck atanahotel.com    after the agency says "done": every item checked on the live site
/hotel-seo init                      set up or repair this machine (safe to re-run)
/hotel-seo init --check              health check (works in desktop chat too)
```

A bare domain or URL in a message also starts a run. Work is saved in a folder per hotel (`<domain>/`) wherever Claude is started (desktop chat: `~/Documents/MetaHotels SEO`).

**What to have ready** (all optional; anything missing is listed under "Missing inputs" and the related facts stay [CONFIRM]):
- The **hotel information sheet** (attach it or give its path when asked).
- For sites with many old or spam URLs: the Search Console **Not found (404)** export, so those URLs get inspected too.
- For a re-check: the agency's **WhatsApp change list**.

The full list is in [`inputs-checklist.md`](plugins/hotel-seo/skills/hotel-seo/references/inputs-checklist.md).

---

## What a run produces

```
<domain>/
  hotel.json                  IDs found: GA4 property, Search Console property, Mirai ID, names
  hotel-facts.json            confirmed facts with their source (info sheet, hotel contact, booking engine)
  crawl-<date>/               crawl files, findings.md / findings.json (the audit), replace_pairs.csv,
                              booking-engine/ (booking_engine.md, screenshots), indexing/ (index_status.csv),
                              bing.json, inspect/ (rendered desktop + mobile pages)
  keywords/                   Keyword Planner CSV/JSON (when set up)
  lists/                      the list JSON files (they carry the checks the re-check runs)
  Reports/                    the PDFs
  recheck-<date>/             re-check crawl, results, re-issued lists
  run-notes-<date>.md         key numbers and their source, decisions, missing inputs, [CONFIRM] questions
```

The finish message gives the PDF paths, the top 3 Priority items, missing inputs, and the hotel-contact and agency messages ready to paste.

**List format** (matches the team's manual lists): running file numbers across hotels; Priority items lettered A, B, C… with a green "biggest issue" box and a "What's already working" table; Nice-to-Have items numbered, with orange **[waiting for hotel details]** holds; red **[CONFIRM]** for unverified facts; green boxes for text to paste; a "Check:" line per item; footer "When done: LiteSpeed → Purge All → send MetaHotels the change list".

---

## Tools

Three MCP servers come with the plugin: **hotel-seo-tools** (below), **hotel-seo-gsc** (Search Console, read-only use) and **hotel-seo-ga4** (Google Analytics 4).

| Tool | Does | Needs |
|---|---|---|
| `crawl_site`, `job_status`, `list_crawls`, `export_crawl`, `read_crawl_file` | LibreCrawl crawl (depth 10, 2 threads) and its files | init |
| `audit_site` | Every count in code: titles (suffixes, WordPress defaults), metas, H1s, canonicals that block indexing, schema blocks (self-written reviews, conflicting hotel blocks, OTA sameAs), SEO plugin and sitemaps, indexable booking/account pages and archives, thin and empty pages, broken and redirected links (sitewide flag, replace pairs), dead or outdated booking links, **Book Now links that open another hotel**, phone codes, distance conflicts, prices in text, out-of-season wording, other cities in headings, blog posts with no booking link, translation plugin, WordPress security signs (suspicious posts, exposed REST routes, public users, defacement text), Search Console brand share and money searches | init (+ Search Console sign-in, parity feed for hotel names) |
| `inspect_pages` | Renders pages desktop + mobile: tags that actually fire, visible H1s, pop-ups, JSON-LD, screenshots | init |
| `booking_engine_snapshot` | Live Mirai engine for 3 stays: rooms, offers, member discount, boards, cancellation, prices, price calendar; compared with the website; adds facts to `hotel-facts.json` | init |
| `rate_parity` | Beat / Meet / Lose vs OTAs from the daily parity feed (website or Google Hotel Ads) | parity feed |
| `index_status` | URL Inspection for every crawled and sitemap URL, grouped like Search Console's Page indexing report (2,000 URLs a day per site; cached, rerun to continue) | Search Console sign-in |
| `bing_report` | Incoming links, linking sites, anchors and Bing sitemap status | Bing key |
| `keyword_ideas`, `keyword_volumes` | Keyword Planner ideas and volumes | Google Ads |
| `mirai_reservations` | Bookings from the Mirai XML API | Mirai credentials |
| `custom_search`, `test_redirects` | Search page text for terms; test redirect lists (PASS/FAIL) | init |
| `render_lists_pdf` | List JSON → PDF with the [CONFIRM] guard and a near-empty-last-page warning | init |
| `recheck_list` | Runs each item's checks against the live site → Done / Partly / Open / Waiting | init |
| `health_check`, `librecrawl_control` | Setup status; start/stop LibreCrawl | — |

---

## Update

```
/plugin marketplace update metahotels
/plugin update hotel-seo
/hotel-seo init
```
`init` only changes what's needed and refreshes the desktop app's copy. Desktop chat users upload the new skill zip again. From a cloned folder: `git pull` first.

Automatic background updates of a private plugin need a `GITHUB_TOKEN` (or `GH_TOKEN`) environment variable with read access to this repo. Without it, run the commands above yourself.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| "Repository not found" or an authentication error on `marketplace add` | You're not a collaborator yet, or git isn't logged in: run `gh auth login`, then try again. |
| `/plugin marketplace add` fails on a fresh clone | The repo root must contain `.claude-plugin/marketplace.json`; pull the latest version. |
| `git` or `uv` not found in the desktop app | Fully quit and reopen the app after installing them. |
| `/hotel-seo` tools missing | Start a new session; then `/hotel-seo init --check`. |
| init finished with "Google sign-in: skipped" | Run the sign-in step: `uv run --quiet --project "<plugin>/server" hotel-seo-auth`, then `/mcp` → reconnect hotel-seo-gsc and hotel-seo-ga4. |
| Google keeps asking for a passkey (QR code) | Open the sign-in link in the Chrome profile already signed in as metahotels.m@gmail.com, or press Cancel on the Windows dialog → **Try another way** → password. |
| Google says "This app isn't verified" | Click **Advanced → Go to Google Analytics MCP**, then Continue. |
| A login command fails with "Access is denied" on a file | The plugin's servers are running and lock its environment: quit Claude Code and run the command again. |
| `index_status` says URLs are left | Google allows 2,000 inspections a day per site; run it again tomorrow (results are cached). |
| Keyword Planner returns nothing | The Google Ads API access level is still Test; it needs Explorer or higher. |
| LibreCrawl won't start | `/hotel-seo init --check`; logs in `~/.metahotels-seo/logs/librecrawl.log`. Port 5057 must be free. |
| Start over on a machine | Delete `~/.metahotels-seo/` and run `/hotel-seo init` again. |

---

## Security

- Credentials live only in `~/.metahotels-seo/` on each machine (`google/`, `ads.json`, `parity.json`, `bing.json`, `mirai.json`) and are typed by the person, never by Claude. `.gitignore` keeps them out of this repo.
- `setup/google/client_secret.json` (the OAuth app of the `metahotels-analytics` Google Cloud project) is in the repo, so **the repo must stay private**.
- LibreCrawl runs in local mode without a login, so it only listens on 127.0.0.1.
- Search Console is used read-only: the plugin never adds, deletes or submits anything there.
- The booking engine snapshot only reads prices; it never selects a room or starts a booking.

---

## What's inside

```
.claude-plugin/marketplace.json   marketplace "metahotels"
plugins/hotel-seo/
  .claude-plugin/plugin.json      plugin manifest (version)
  .mcp.json                       hotel-seo-tools, hotel-seo-gsc, hotel-seo-ga4
  skills/hotel-seo/
    SKILL.md                      the workflow (init, full run, recheck)
    references/                   playbook.md (the method), inputs-checklist.md, librecrawl.md,
                                  team.md (people by role, Mirai IDs, booking link, message templates)
    templates/lists.schema.json   the list format Claude writes
    examples/                     a sample Priority list
  server/                         Python MCP server (run with uv)
    hotel_seo_tools/              crawl, audit, analysis, pagecheck, booking_engine, parity, indexing,
                                  bing, keywords, mirai, pdf (+ templates), checks, facts, health,
                                  google_auth, launch, paths
  setup/init.py                   /hotel-seo init
  setup/google/                   OAuth client (private repo only)
```

Machine state lives in `~/.metahotels-seo/` (LibreCrawl, sign-ins and keys, caches for parity files and URL inspections, logs, the desktop app's server copy). It never goes into this repo.

---

## Changing the method

Edit `plugins/hotel-seo/skills/hotel-seo/references/playbook.md` (add hotel lessons to section 10) or `team.md` (people, IDs, templates), bump `version` in both `plugins/hotel-seo/.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json`, commit and push. Teammates get it with the update commands above.

---

## Status and open items

| Area | Status |
|---|---|
| Crawl, audit, PDFs, recheck, booking engine snapshot, rendered pages | Working, tested on Al Bahar and Atana |
| Rate parity | Working (tested on Al Bahar and the Gewan hotels); each machine needs `hotel-seo-parity-login` |
| URL Inspection (indexing) | Working (tested on Atana) |
| Bing Webmaster | Built; untested until a Bing API key is added |
| Mirai bookings | Built; waiting for Mirai XML API credentials |
| Keyword Planner | Built; waiting for Explorer access and the Google "verify it's you" step |
| Hotel information sheet | The run asks for it; field mapping waits for the team's standard sheet |
| Google Business Profile, Hotel Center, Search Console alert emails | Not built: need profile/account access and Google API approval |
| macOS | Not yet tested on a Mac |
