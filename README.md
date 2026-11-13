# MetaHotels Claude plugins

Private. One marketplace (`metahotels`, repo `jyothisjoy/metahotels-claude-plugins`) with the MetaHotels Claude Code
plugins: **hotel-seo** and **metahotels-optimize**.

**hotel-seo:** give Claude a hotel website — or a hotel group's website — and get, for every
hotel separately, a full **Audit Report**, a ground-up **Build Plan** and a **Web Team List** as PDF, plus a
**Questions for the Hotel** spreadsheet, each run in its own dated folder (`Reports/<YYYY-MM-DD>/`). Then re-check the fixes, or have Claude apply them to the site in
batches you approve (using the hotel's answers), which ends with an **Execute Report** and an **Agency Fix List** for
what's left. Each month, `/hotel-seo monthly` makes the client **Monthly Report**. Between runs, `/hotel-seo monitor`
watches each site for what changed; `/hotel-seo write` writes hotel copy to one standard; `/hotel-seo check` fact-checks
someone else's SEO report; and the Google Business Profile can be read and (after your approval) updated.

The audit runs **11 specialist agents ported from [claude-seo](https://github.com/AgriciDaniel/claude-seo) (MIT)** —
technical, sitemap, performance, agent readiness, backlinks, content (Opus), schema, local, maps, AI search (Opus) and
FLOW — with MetaHotels' hotel rules, on top of hotel-seo's own crawl, audit, Search Console, GA4, Keyword Planner,
Mirai, booking engine and Booking.com data.

The same `metahotels` marketplace also lists **metahotels-optimize** (the site performance pass; its code lives in `plugins/metahotels-optimize` of this repo): `/plugin install metahotels-optimize@metahotels`, then `/metahotels-optimize:optimize --init`.

**Repo renamed** (Nov 2026): `jyothisjoy/metahotels-seo` is now `jyothisjoy/metahotels-claude-plugins`. GitHub
redirects the old name, so existing installs keep updating; to switch for good, run
`/plugin marketplace remove metahotels`, then `/plugin marketplace add jyothisjoy/metahotels-claude-plugins` and
install the plugins again.

## Before you start (once per person)

1. **Repo access.** Ask the repo owner to add your GitHub account as a collaborator on `jyothisjoy/metahotels-claude-plugins`.
2. **GitHub login on your computer.** Claude installs the plugin with a normal `git clone`, so your git must be able to reach the private repo. The easiest way is to install the [GitHub CLI](https://cli.github.com/) and run `gh auth login` (GitHub.com → HTTPS → log in with a browser). Git Credential Manager (comes with Git for Windows) or an SSH key also work.
   Test: `git clone https://github.com/jyothisjoy/metahotels-claude-plugins.git` should work without errors (you can delete the folder afterwards).
3. **Claude Code**, in the terminal or the Code tab of the Claude desktop app.

## Install (once per machine, Windows or macOS)

1. In Claude Code (terminal, or the desktop app's Code tab):
   ```
   /plugin marketplace add jyothisjoy/metahotels-claude-plugins
   /plugin install hotel-seo@metahotels
   /plugin install metahotels-optimize@metahotels     (optional: the performance plugin)
   ```
   If the `/plugin` menu doesn't appear in the Code tab, run the same thing in a terminal:
   ```
   claude plugin marketplace add jyothisjoy/metahotels-claude-plugins
   claude plugin install hotel-seo@metahotels
   ```
   Then start a new Claude Code session.
2. Run `/hotel-seo init`. It installs `uv` if needed, LibreCrawl, Chromium and the desktop-app setup, then walks you through one Google sign-in as **metahotels.m@gmail.com** (get the password from the team; never put it in this repo). It covers GA4, Search Console (read-only), Google Docs output, Google Business Profile and Google Ads Keyword Planner (through the MetaHotels Manager Ads account 437-179-3247; no developer token since Google retired them on 9 Sep 2026). Takes about 5–10 minutes.
3. **API keys for the agents:** add them to the `.env` file in the work folder (the same file as the Mirai login):
   - `PAGESPEED_API_KEY=...` (or `GOOGLE_API_KEY`) — Cloud console, project `metahotels-analytics`: enable **PageSpeed Insights API** and **Chrome UX Report API**, create an API key restricted to those two. Used for Core Web Vitals field data and Lighthouse. The Google sign-in in step 2 does not cover these two APIs, so this key is needed as well.
   - `MOZ_API=...` — moz.com API, free plan. Without it the backlink score is "insufficient data".
   - `GEOAPIFY_KEY=...` — myprojects.geoapify.com, free. Without it maps use OpenStreetMap only.
   - `SERPER_API=...` — serper.dev. Exact Google positions for the monthly report's tracked keywords (about one credit per 10 results checked). Without it the monthly report shows Search Console average positions only.

   `/hotel-seo init --check` shows whether each key works. (`hotel-seo-key-login google|moz|geoapify|serper` still works as a per-machine alternative; the `.env` value wins.)
4. **Site logins for execute:** export the team's site sheet as `sites.csv` (columns Website Name, App name, User name, App Password, Content endpoint) into the folder you start Claude in (desktop chat: `~/Documents/MetaHotels SEO`). It holds application passwords: never commit it (it is in `.gitignore`).
5. **Optional:** rate parity (`hotel-seo-parity-login --from-env <magicparity>\.env`), Bing Webmaster (`hotel-seo-bing-login`), Mirai reservations (`MIRAI_USER=...` and `MIRAI_PASS=...` in a `.env` file in the work folder).
6. **Desktop chat (optional).** Upload `~/.metahotels-seo/hotel-seo-skill.zip` in Settings → Capabilities → Skills, then fully quit and reopen the desktop app. Desktop chat has no subagents; Claude follows the agents' instructions itself, one after another.
7. **Check:** `/hotel-seo init --check` shows all OK.

## Use

```
/hotel-seo rosehotelsgroup.com                 full report for every hotel of the site (asks once: confirm the hotels,
                                               each hotel's Booking.com URL, the hotel information sheet, the
                                               Disparity / Best Rate calendar)
/hotel-seo rosehotelsgroup.com --hotel rose-park-albarsha     one hotel
/hotel-seo recheck rosehotelsgroup.com          every finding re-checked on the live site
/hotel-seo execute rosehotelsgroup.com          apply the fixes through the site's MCP, batch by batch, after your OK
                                               (asks once for the hotel's filled Questions spreadsheet, if it's back)
/hotel-seo execute abarhotels.com --only On-Page              only some fixes (finding ids or an audit category)
/hotel-seo execute --undo <plan file>           put back what an execute run changed
/hotel-seo monthly rosehotelsgroup.com          client Monthly Report per hotel for last month, plus a group page
/hotel-seo monthly abarhotels.com --month 2026-10
/hotel-seo monitor abarhotels.com               what changed since the last run (posts, spam searches, booking links,
                                               tags, noindex / canonical / schema on the key pages, robots.txt)
/hotel-seo monitor add abarhotels.com           add it to the daily monitor run
/hotel-seo write abarhotels.com <what>          one piece of copy (a title, an intro, an FAQ, an offer page, a blog
                                               post, Business Profile text), paste-ready
/hotel-seo check <report or file>               fact-check an agency's or tool's SEO report against Google's own
                                               documentation
/hotel-seo init --check                         health check (install, sign-in, keys, sites.csv)
```

Everything the plugin writes for a website or Business Profile, from a title to a blog post, follows one writing
standard: `plugins/hotel-seo/skills/hotel-seo/references/content-writing.md`. The renderer flags copy that breaks it
(AI-sounding phrases, stock openings, unsourced superlatives, em dashes in paste copy, titles over 62 or metas over 155
characters, invisible characters).

Every full report also checks whether ChatGPT, Perplexity, Claude, Copilot and Google's AI features can reach the site
(robots.txt per crawler, and a firewall test: the homepage and a room / offer page fetched as each AI crawler, with
challenge pages detected), reads Google Images data, and warns when a Search Console comparison falls in Google's
inflated-impressions period (13 May 2025 – 27 Apr 2026).

Work is saved in a folder per site (`<domain>/`) wherever Claude is started (desktop chat: `~/Documents/MetaHotels SEO`),
with `site.json` describing the site. The plugin tells the two kinds of site apart from the page structure:

- **Single hotel** (e.g. abarhotels.com): everything sits directly in `abarhotels.com/` (facts, keyword map, audits,
  `Reports/`, re-checks, execute runs, monthly reports). No group folder and no Group Summary.
- **Hotel group** (e.g. rosehotelsgroup.com with Rose Park, Rose Executive, …): each hotel has its own
  `hotels/<slug>/` folder, and site-wide work plus the Group Summary go in `group/`.

Documents go in the site's `Reports/` folder, numbered across hotels: `31 - Rose Park Al Barsha Audit Report (24 Oct).pdf`,
`Build Plan`, `Web Team List`, `Questions for the Hotel (.xlsx)`, `Execute Report`, `Agency Fix List`, `Monthly Report`
and, for a group only, `Group Summary` and `Group Monthly Summary`.

### What you get per hotel

- **Audit Report:** Health Score (0–100) and 8 category scores computed in code (Booking path & facts 15%, Technical,
  Content, On-Page, Schema, Performance, AI Search, Images), separate Local / Maps / Backlinks scores, and every finding —
  severity, evidence and the tool behind it, every affected URL (25 shown, all in a linked sheet), the exact fix and
  where to make it, and how it will be re-checked. The status of each of the 11 agents is on the cover. It ends with
  **Keywords we chose, and why**: every target search group with its monthly searches, the page that should rank,
  where it stands today and the reason it was chosen (the hotel's area, a landmark and its distance, a facility it has,
  booking intent), plus what was left out and why (brand searches, other hotels, other areas, no searches).
- **Build Plan:** the target site for the hotel — every page it should have (exists / fix / missing) with its keyword
  cluster and monthly searches, full paste-ready copy, schema, internal links, content plan, local and AI-search setup,
  tracking plan, and the steps in order.
- **Web Team List:** security, analytics, performance engineering, templates and server items for the developer.
- **Questions for the Hotel (xlsx):** everything only the hotel can answer, numbered so each gap in the reports points
  at its row (`[CONFIRM Q7]`, `[CONFIRM R2]`): questions per finding, room sizes / guests / beds (what the site, the
  booking engine and Booking.com say), distances, and basic facts not yet confirmed. Send it to the hotel; yellow cells
  to fill.

### Facts and [CONFIRM]

Sizes, distances, times, prices, room counts and similar facts print without **[CONFIRM]** only when confirmed: the
hotel information sheet, the hotel contact, the live booking engine, or Booking.com **where the booking engine agrees**.
Booking.com alone is not confirmation; where Booking.com, the engine and the site disagree, the report says so.

### Execute

`/hotel-seo execute` reads the latest audit, resolves every fix to the site's WordPress MCP tools (Rank Math fields,
redirects, Elementor text, schema snippets, alt text, page status, menus, new pages from the Build Plan) and shows each
batch as a table — page, field, current value, new value — before anything is written. After your OK it saves the old
values, writes, purges the cache and re-checks every fix on the live site; `--undo` puts the old values back. Steps with
no MCP tool (wp-admin screens, Search Console, Bing Webmaster) run with Claude in Chrome in your own logged-in browser.
It never touches prices, offers, discounts, member benefits, Web Team items, deletions or the Google Business Profile.
Group-wide settings (Rank Math templates, shared headers / loops) run in their own batch. A hotel that approves every
change before it goes live (its `hotel.json` setting) gets the change list first: no batch runs until the client's yes
is recorded (who, how, when).

**The hotel's answers.** Execute first asks whether the hotel sent the Questions for the Hotel spreadsheet back. If so,
it reads it: the answers become confirmed facts; a fix marked [CONFIRM] goes ahead only when the hotel answered yes (the
marker is removed); "no" or no answer keeps it out. Where the hotel gave a different detail, Claude rewrites that text
with the answer. Site text that contradicts an answer (a wrong apartment size, a wrong distance) becomes a correction in
its own "hotel-answers" batch, shown for your approval like every other change.

After the run it writes two PDFs: the **Execute Report** (every change: page, before → after, live re-check result,
what waits for the hotel, how to undo, and what is still to run with execute) and the **Agency Fix List** (only the
SEO fixes execute cannot make, step by step with the exact text to paste and where in WordPress, ready to send to
the SEO agency; new pages to create; items that wait for the hotel). Developer items stay in the Web Team List.
Site text (hotel answers, booking-engine room facts, phone numbers) is changed with the site's `find-text` /
`replace-text` tools, so text in Elementor widgets and in header / footer templates is reached too. Schema is
checked and wrapped in `<script type="application/ld+json">` before it is written.

Google review replies come as a **Review Replies** spreadsheet (the plugin's reply, a "Final reply" to edit and
"Send? Yes / No"); replies are posted only from that sheet, after you approve the change id.

### Rate parity (Disparity / Best Rate calendar)

The full report asks for the hotel's Disparity / Best Rate calendar CSVs (`disparity-calendar-<hotel>-<YYYY-MM>.csv`,
one per month, from MetaHotels' parity monitoring). They are counted in code (best-rate, disparity and no-record days,
the no-record pattern such as "every Saturday", the longest disparity run, direct bookings by day type) and the Audit
Report gets a **Rate parity (Best Rate calendar)** table. When the website was not the best rate on 20% or more of the
recorded days, that goes at the top of the report: page fixes won't win a booking the OTAs sell cheaper. Rates are a
revenue-team matter, never a change on the website.

### Monthly Report

`/hotel-seo monthly` makes the client report for a calendar month (run it from the 4th of the next month), compared with
the month before and the same month last year, in the MetaHotels look:

- **Where the hotel stands:** Google visits and engagement (GA4), clicks from people searching the hotel's name, the
  main page's Google position, pages listed in Google, visits from AI assistants, guest countries, and a this month /
  last month / last year table.
- **Keywords:** brand searches, and the hotel's tracked keywords with Search Console position this month and last month,
  the exact Google position from the hotel's city and the map pack (Serper), and the target.
- **AI assistants:** visits from ChatGPT, Perplexity, Gemini, Copilot, Claude and others (GA4).
- **Work done:** every change made through execute, plus work done by hand from the hotel folder's `work-log.csv`, and
  what comes next.
- **Search to booking:** found → searched the name → visited → booked (Mirai), and official site vs the OTAs (rate
  parity).
- **Google Maps:** Business Profile numbers (read in Chrome; needs Manager access for metahotels.m@gmail.com) and the
  hotel's Google Maps position from its own area.

Every number comes from the tools; Claude writes only the short explanations, and a check refuses any number that is
not in the month's data. Anything that couldn't be read (no Mirai ID, no parity login, no Manager access) is listed at
the end of the run. The tracked keywords are confirmed with you the first month and then stay the same so months compare.

### Monitor

`/hotel-seo monitor <domain>` compares the site with the last run: the homepage and the key pages it links to (status,
noindex, canonical, H1, Hotel / Offer / Breadcrumb schema), robots.txt (Googlebot or AI search crawlers newly blocked),
newly dead booking links, new or growing suspicious posts, new WordPress users, REST / MCP routes open without login,
new spam searches in Search Console, and tags that stopped firing. Alerts first, then changes. The first run saves the
baseline. `monitor add <domain>` puts the site on the daily schedule (`hotel-seo-monitor`, run by Windows Task Scheduler
or cron); reports go to the site folder's `monitor/`.

### Business Profile

Claude reads each hotel's Google Business Profile (listing, monthly views / calls / website clicks / direction
requests, search terms, reviews and reply rate, and whether the listing matches the website's schema, phone and
address), its hotel details (check-in/out, breakfast, parking, Wi-Fi, pool, pets…) against the hotel's confirmed
facts, and its photos (missing or stale categories). Changes (description, hours, categories, attributes, hotel
details, review replies, posts, photos) are proposed first with a
now → after preview, and sent to Google only after you approve that preview in a later message. Name, address and main
category are locked unless you ask for exactly that change.

### Write and check

`/hotel-seo write` writes one piece of hotel copy (a title and meta, an intro, an FAQ, a room or offer text, a new page
or blog post, Business Profile text) to the writing standard, with facts only from the hotel's confirmed facts or
marked [CONFIRM]. `/hotel-seo check` reads an agency's or tool's SEO report or advice and says, point by point, what
Google's own documentation supports, what is wrong or outdated, and what doesn't apply to a hotel.

## Update

```
/plugin marketplace update metahotels
/plugin update hotel-seo
/hotel-seo init
```
`init` only changes what's needed and refreshes the desktop app's copy. Desktop chat users upload the new skill zip again.
Automatic background updates of a private plugin need a `GITHUB_TOKEN` (or `GH_TOKEN`) environment variable with read
access to this repo.

**From 0.8 to 0.9:** the Priority / Nice-to-Have lists are replaced by the Audit Report and Build Plan. Add the three
API keys and `sites.csv`.

**From 0.9 / 0.10 to 0.11:** the site's settings file is now `site.json` (an older `group.json` is still read). A
single-hotel site (one hotel on its own domain, like abarhotels.com) is now kept flat in `<domain>/` with no `group/` or
`hotels/` folders and no Group Summary. If an older run created those folders for a single hotel, run the report again:
the new run works in `<domain>/`, and the old `group/` and `hotels/` folders can be deleted afterwards. Add `SERPER_API`
to `.env` for the monthly report's exact Google positions.

**From 2.0.0 to 2.1.0:** the Audit Report / Build Plan / Web Team List and execute through `sites.csv` replace the
Priority / Nice-to-Have lists again. Write, check, monitor, Business Profile, the Disparity / Best Rate calendar and the
AI-crawler firewall test carry over. A daily monitor task you scheduled before keeps working (`hotel-seo-monitor`).
New in 2.1.0:
- **Reports you can trust:** findings from an agent that failed its check stay out ("not assessed"); a broken booking
  path caps the Health Score at 59 (two: "Blocked"); the score shows how much of the site it measured. Older audit runs
  rebuilt with 2.1.0 show their agents as "not assessed" (no status file): run the audit again.
- **Writing:** `copy_check` (title width in pixels, prices in FAQ answers, vague openings, alt and button text, dated
  words, size units, AI-sounding phrases), a source list for local facts (`save_claims`), room-fit lines.
- **Site checks on every page:** pages nothing links to, key pages more than 3 clicks deep, EN/AR hreflang, sentences
  copied across room pages, WhatsApp link previews, skipped headings, "read more" links, case / slash duplicate URLs.
- **Keywords:** Google page 1 recorded (People Also Ask, booking sites vs hotels), rival-first Build Plan order, a
  seasonal "publish by" date. Building the keyword map spends up to 12 Serper credits per hotel per 30 days.
- **Monthly report:** AI-answer panel (ChatGPT, Perplexity, Google AI), a before/after readback of each change against
  similar pages, last month's Google position, the Best Rate calendar (asked for before building), and Business Profile
  numbers straight from Google.
- **Business Profile:** `gbp_link` (once per hotel), hotel amenities and policies (`gbp_amenities`), photo check
  (`gbp_photos`), review replies (`gbp_reviews_pending`), Business Profile fixes as an execute batch, monitor alerts
  when Google or the public edits the listing.
- **Questions for the Hotel:** a Business Profile sheet, name / address / phone conflicts, wrong facts from AI
  assistants and unsourced local claims.

**2.1.1:** the Monthly Report PDF matches the reference design more closely (type sizes and spacing, page count under
each timeline date, two-column lists only when long, check lists in two panels, MetaHotels logo in the page footer).

**2.2.0:**
- **Execute reaches Elementor and templates:** site text (the hotel's answers, the booking engine's room facts, phone
  numbers) is changed with the site's `find-text` / `replace-text` tools, in page widgets and header / footer / global
  templates; one item per wrong phone number in every format and `tel:` link; on a group site, shared templates are
  their own group-batch item. Body copy on an Elementor page goes into its text widget, never post content.
- **Schema can't be dumped on the page:** every snippet is parsed and rewritten as `<script type="application/ld+json">`
  in `<head>`; bare text, HTML or invalid JSON is refused, JSON-LD in page copy is refused, and the schema re-check
  fails if `"@context"` shows as page text.
- **No agency leftovers:** the Agency Fix List keeps only what execute cannot do. Unapproved batches, Chrome steps, group
  items and alt text still to run are in the Execute Report ("Still to run with execute"); hreflang goes to the Web
  Team; Business Profile amenities / categories the API refuses become Chrome steps; no Business Profile description on
  hotel profiles (Google doesn't allow one). Alt text is sent 50 images per call.
- **Review Replies spreadsheet:** the plugin's replies with an editable "Final reply" and "Send? Yes / No"; replies are
  posted only from the sheet (`gbp_review_sheet_import`, or execute's business-profile batch).
- **The booking engine wins conflicts:** its `/search` page beats the site, Booking.com and the hotel's other messages,
  unless the hotel says otherwise in the Questions sheet. Engine-vs-site room facts are fixed by execute, not asked.
- **One dated folder per run** (`Reports/<YYYY-MM-DD>/`), **PDF only** (no Word file, no Google Docs; the sign-in no
  longer asks for Drive).

Run `/hotel-seo init` (or `hotel-seo-auth`) once: the Google sign-in now includes Business Profile by default and tests
each Business Profile API; enable the **My Business Lodging API** on the Cloud project if it says so.

## Troubleshooting

| Problem | Fix |
|---|---|
| "Repository not found" or an authentication error on `marketplace add` | You're not a collaborator yet, or git isn't logged in: run `gh auth login`, then try again. |
| `git` or `uv` not found in the desktop app | Fully quit and reopen the app after installing them. |
| `/hotel-seo` tools missing | Start a new session; then `/hotel-seo init --check`. |
| Google says "This app isn't verified" | Click **Advanced → Go to MetaHotels SEO**, then Continue. |
| An agent shows "degraded" or "not assessed" | The report says why (usually a missing key or an unreachable page); `/hotel-seo init --check` shows the fix. |
| Performance: "Chrome UX Report API is not enabled" | In the Cloud console project of your `PAGESPEED_API_KEY`, enable **Chrome UX Report API** and allow it on the key. |
| Monthly Report marked "provisional" | It was run before the 4th of the next month; Search Console data isn't final yet. Run it again later. |
| Monthly Report: "not checked this month" for Google Maps | Claude in Chrome wasn't available or metahotels.m@gmail.com has no Manager access to that Business Profile. |
| Execute: "login rejected (401)" | The user name or application password in `sites.csv` is wrong or revoked: create a new application password for that user in WordPress. |
| Execute: "WordPress refused (403)" | The login works but that user may not use MCP on the site (role, MCP plugin settings or a security plugin). |
| Business Profile: "not set up on this machine" | Run `/hotel-seo init` again and allow the Business Profile permission; metahotels.m@gmail.com needs Manager access to the profile. |
| Monitor shows "First run" every time | The baseline is saved in `~/.metahotels-seo/monitor/<host>.json`: check that folder is writable. |
| Start over on a machine | Delete `~/.metahotels-seo/` and run `/hotel-seo init` again. |

## What's inside

```
plugins/hotel-seo/
  agents/                 the 11 agents (seo-technical, seo-sitemap, seo-performance, seo-agentic, seo-backlinks,
                          seo-content, seo-schema, seo-local, seo-maps, seo-geo, seo-flow), ported from claude-seo
  skills/hotel-seo/       SKILL.md (the workflow), references/ (playbook, hotel-addendum, agent-contract, inputs
                          checklist, content-writing standard, audit-checks registry, third-party warnings, LibreCrawl
                          guide, claude-seo/ references and FLOW prompts), templates/ (report.schema.json,
                          findings-register.schema.json)
  server/                 hotel-seo-tools MCP server (Python, run with uv): crawl, audit, site kinds (single / group),
                          keyword map, Booking.com facts, maps, agent preflight and validation, report builder and
                          PDF renderer, hotel questions and review replies (xlsx), re-check, site MCP client,
                          execute and its reports, monthly report (GA4, Search Console, Serper, Mirai, parity),
                          monitor, Business Profile, page consistency, Best Rate calendar;
                          vendor/claude_seo/ = 26 claude-seo scripts (MIT) and their tests
  setup/init.py           /hotel-seo init
  setup/claude-seo-port/  how to update the ported agents and scripts from a newer claude-seo
  setup/google/           OAuth client for the metahotels-analytics GCP project (repo must stay private)
  .mcp.json               hotel-seo-tools, hotel-seo-gsc, hotel-seo-ga4
```

Machine state lives in `~/.metahotels-seo/` (LibreCrawl, Google tokens, API keys, Mirai credentials, logs, the desktop
app's copy). Site logins live in `sites.csv` in the work folder. Neither goes into this repo.

## Changing the method

Run the offline tests first (`uv run pytest -q` in `plugins/hotel-seo/server`). Edit
`plugins/hotel-seo/skills/hotel-seo/references/playbook.md` (hotel lessons in "Lessons learned") or
`hotel-addendum.md` (the rules every agent follows); agent-specific hotel instructions are generated from
`setup/claude-seo-port/make_agents.py`. Bump `version` in `plugins/hotel-seo/.claude-plugin/plugin.json`,
`.claude-plugin/marketplace.json` and `server/pyproject.toml`, commit and push. Teammates get it with the update commands.

## Credits

The agents, references and scripts under `agents/`, `references/claude-seo/` and `server/hotel_seo_tools/vendor/claude_seo/`
come from claude-seo by agricidaniel (MIT). The FLOW framework prompts are © Daniel Agrici, CC BY 4.0
(github.com/AgriciDaniel/flow). The AI-phrase lists in `content_quality.py` / `content_humanize.py` draw on Wikipedia's
AI Cleanup catalogue (CC BY-SA 4.0).
