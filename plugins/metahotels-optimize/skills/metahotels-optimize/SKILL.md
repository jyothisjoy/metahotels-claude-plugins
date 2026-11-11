---
name: metahotels-optimize
description: Complete performance optimization pass for MetaHotels hotel websites (WordPress + Elementor + LiteSpeed Cache, Mirai booking engine, metahotels-core), from audit to owner report. Covers PageSpeed / Core Web Vitals (LCP, CLS, TBT) mobile first, real throttled-phone loading, the site-wide image re-encode, unused addon assets, LiteSpeed options A/B, hero and popup fixes, 404s, redirecting links and "Book now" links, Element Manager cleanup, re-warm and regression checks, and the report plus the cross-site documents. Use it whenever the user asks to speed up, optimize, audit or fix performance, PageSpeed scores, LCP/CLS, page weight, heavy images, broken links or calls to action on a MetaHotels or other Elementor/LiteSpeed hotel site, or names a hotel site (Gevora, Nassima, Abar, Shams, Khalidia, Gewan, a new one) with any of those goals, even for one part only, such as "compress the images on X", "why is the mobile score 40", "test JS defer" or "check the book now buttons".
---

# MetaHotels site optimization pass

A pass takes one hotel site from "audit" to "report": write down the current state, measure a baseline, re-encode
the images, find root causes, fix them one batch at a time with numbers before and after, verify nothing a visitor
uses broke, and report it to the owner. The playbook below was built over seven passes on six live sites
(references/history.md). The owner and client decisions in it are standing instructions: follow them without
asking again, and ask where they say to ask.

## Entry points

- `/metahotels-optimize:optimize --init [work-folder]`: once per machine and work folder. Runs `scripts/init.py`
  (prerequisites, Node dependencies, `metahotels.json`, `.env` with an empty `PAGESPEED_API_KEY=` the user fills
  in, the cross-site documents). `--test-key` checks the key with one PageSpeed call.
- `/metahotels-optimize:optimize <site-url> [--omit-report] [--check]`: onboards the site with `scripts/site-init.py`
  (site folder, `site.json`, site/sitemap/MCP/access/key checks), asks the user for every missing item, then runs
  the pass. `--check` stops after the onboarding.
- When the skill is triggered without the command ("optimize gewanhotels.com", "compress the images on Shams"), do
  the same: find the work folder (`metahotels.json`), run `site-init.py` for the site, ask for what is missing,
  then go to the step asked for. Without a work folder, offer `--init` first.

## Conventions

- **Paths in this skill** (`scripts/`, `references/`, `assets/`) are inside the skill's base directory, shown when the
  skill loads. In commands, `$S` stands for `<base directory>/scripts`.
- **Work folder**: one folder holds every site folder and the two cross-site documents (`optimization-results.md`,
  `score-vs-experience.md`). Ask the user where it is if the session does not start there.
- **Run every tool from the site folder** (`<work folder>/<site>/`). Tools read `site.json` there, write results to
  `audit/`, `images/`, `rollback/`, `runs/`, `shots/`. First time on a machine or a site: references/site-setup.md.
- Tools print their usage when run without arguments, and each file starts with what it does and why.
- **Before the first browser tool** check `scripts/node_modules` exists (a plugin update replaces the folder);
  if not, run `npm ci` in `scripts/`.
- **Check the date before you act on a "local" or "not released" note**: core toggles, plugin versions and LiteSpeed
  behaviour change. Read the installed versions during the audit.

## Hard rules

1. **Audit first, change nothing until the current state is written down**: plugins, theme, LiteSpeed values,
   Elementor settings, Custom Code snippets, homepage asset list, headers, baseline numbers. The report's
   "before" column and every rollback depend on it.
2. **Never change the booking engine** (Mirai or any other): its loader snippets, widgets, CSS/JS delivery or init.
   Measure and document only. When an optimization would touch booking-engine assets, exclude them instead (Mirai:
   LiteSpeed CSS Excludes `static.mirai.com`, `cdn.metahotels.ae`; JS Excludes the loader). Setting the link of our
   own button, or reserving the space of a finder with CSS on our own wrapper widget, is not a booking-engine change.
3. **Image compression is the first change on every site** (owner, 2026-10-14), straight after audit and baseline,
   without asking: new attachments only, originals untouched (references/images.md).
4. **One logical batch at a time.** After each batch: purge, re-warm, retest, keep it only if nothing broke **and**
   there is a measured benefit in real loading or in the PageSpeed score. Keep a rollback file in `rollback/`
   before every write to a snippet, template, element or setting.
5. **Never accept a speed gain that breaks** the booking widget, menus, forms/reCAPTCHA, popups, sliders or the
   mobile layout, including intermittently or only on a cold cache.
6. **Target (client, 2026-10-13): fast real loads and good PageSpeed scores, mobile before desktop.** Measure,
   decide and report on mobile first; work the mobile `psi_breakdown.py` list (points lost per metric) from the top.
   Another lab grade (GTmetrix, SpeedVitals) only if the owner names it.
7. **Score versus experience: take a score gain whenever possible.** The only reason to leave one off is a huge
   departure in the visitor's experience, which is any of: something broken (rule 5); a visible change (a blank or
   late hero, images or slides missing or visibly late, a poster where a video played, layout shift above 0.1);
   real throttled-phone first or largest paint slower by more than about 0.5 s or 15%, whichever is larger, over
   three sets of 3 runs each way (a working threshold set here, not by the client: confirm it with the owner the
   first time a case comes near it). Then leave it off and give the owner both sets of numbers. A small real-load
   cost for a clear score gain is accepted and reported next to the gain.
8. **Never guess a booking link.** Every "Book now", "Reserve", "Check availability" must end at the hotel's
   endpoint on `reservation.mirai.com`; the owner gives the link per hotel. Never build one or copy another
   hotel's. Other missing targets (enquiry, brochure, WhatsApp, phone): ask the owner.
9. **State variance honestly.** One PageSpeed run or one throttled set is noise (references/testing.md).

### What needs the owner's approval

| Decide yourself (standing decisions) | Ask first, with the expected gain and the visitor cost |
|---|---|
| The image re-encode (rule 3) | Deactivating or removing plugins |
| LiteSpeed safe batch: CSS/JS minify, emoji, excludes; Elementor "Load Google Fonts Locally" | DNS or CDN changes (the owner makes them), editing `.htaccess` |
| Reserving a booking-engine component's size with CSS on our own wrapper (2026-10-14) | UCSS, JS Delay, anything spending a QUIC.cloud quota (Critical CSS) |
| Pointing links that only work through a redirect at their final page (2026-10-15), after checking each target belongs to the same hotel | Anything that loads only on the first interaction and changes what a non-interacting visitor sees or what gets counted (hero video, pixels, push/marketing SDKs) |
| Loading the chat widget on first interaction | Creating redirects |
| Fixing a link through the MCP when the right target is certain, with a rollback file | Any link target that is not certain; booking links (rule 8) |
| Switching off unused widgets in Element Manager (owner's standing request; references/batches.md) | Changing what the site shows, beyond a fix of something broken |

Propose the "ask first" options in every pass with their expected score gain instead of leaving them out silently.

## The pass

Each step names its reference file. Read the reference before doing the step: it holds the commands, the traps that
cost time on earlier sites, and the per-site evidence.

**0. Setup and onboarding.** `scripts/site-init.py <site>` from the work folder: site folder, `site.json`, and a
numbered list of what to ask (MCP entry, PageSpeed key, booking links per hotel, owner context, the logged-in
Chrome tab, report or not). Ask with AskUserQuestion; never ask for a password or API key in the chat (the user
puts them in `~/.claude.json` via `claude mcp add` and in `.env` themselves). Record the answers in `site.json`.
References: references/site-setup.md, references/access.md.

**1. Audit (read-only)** → references/audit-baseline.md. Plugins and theme, homepage assets and handles, LiteSpeed
and Elementor settings (saved to `audit/`), Custom Code snippets, cache headers, CrUX field data, page weight,
images loaded without scrolling, where the lab score is lost, and a site-wide inventory from every sitemap URL.

**1b. Links and calls to action** → references/links-and-ctas.md. 404s (assets and pages), links that only work
through a redirect, calls to action without a link, every "book" link by target, each with the widget or menu item
that owns it; LibreCrawl as an optional cross-check for pages outside the sitemap and external links.

**2. Baseline** → references/audit-baseline.md. Throttled phone (3 sets), PageSpeed ×3 (35 s apart), sweep of every
sitemap URL, weight desktop and mobile, the lab-score breakdown. Homepage and one inner page per template.
*Checkpoint: the "before" column of the report is complete before anything changes.*

**2b. Image re-encode** → references/images.md. Save every Elementor tree, list the images, AVIF for backgrounds and
slides, WebP where sub-sizes or social previews are needed, upload as new attachments, repoint, featured and
block-editor images, purge, re-warm, check every image URL.

**3. Root causes** → references/patterns.md (43+ known symptom → cause → fix rows, by area) and references/testing.md
(simulate a fix on the live HTML before saving anything: `abhtml.js`, `simhtml.js`, `floor.js`, rules from
`scripts/wp/make-rules.py`). Work the mobile breakdown from the top: the largest lost points first.

**4. Safe batch** → references/batches.md. LiteSpeed minify and excludes, Elementor local fonts; purge the front page,
check `x-litespeed-cache: hit`, test, then Purge All and re-warm.

**5. Site plugin** → references/batches.md, references/site-plugin.md. Unused addon assets (proven with `simblock.js`,
0 px diff), plus the proven techniques the site needs (popup dialog CSS, lazy backgrounds, icon-font subset, entrance
CSS, hero slide). Generic code goes to metahotels-core as an opt-in toggle instead. Zip with `scripts/zip-plugin.py`;
the user uploads; re-warm and verify the markers on every page.

**5b. Element Manager** → references/batches.md. Housekeeping at the owner's request, decided from the rendered
inventory, never from Elementor's scan alone. No speed claim.

**6. Moderate and high-risk options** → references/litespeed-options.md. One option at a time with
`scripts/judge.sh` (markers, three PageSpeed runs, two throttled sets, cold check, interaction, lazy checks); revert
in the same call that sets the next option; read the settings back, Purge All, re-warm and `state.sh` after the last
test. Decide under rule 7.

**7. Propagate and regress** → references/propagate.md. Purge All once per batch, re-warm (`warm.sh`), sweep every
sitemap URL against the baseline, cold check, `regress.js`, `interaction.js`, sitemap still 200. If the site moves
behind a CDN mid-pass, stop measuring until both host names have a valid certificate.

**8. Report** → references/report.md, `assets/report-template.md`. `<site>/performance-report-YYYY-MM-DD.md` with the
17 sections; then the site's section in both cross-site documents and the rebuilt PDFs. Numbers come from the files
in `audit/` and `runs/`, never from memory.
**When `site.json` has `"report": false`** (set by `--omit-report`): write no `performance-report-*.md` and add
nothing to the cross-site documents or their PDFs. Everything else stays: rollback files, `audit/` and `runs/`
outputs, and a summary in the chat with the before → after table, what changed, what was not applied and the
rollback steps, since those are what the user needs to act on.

### Partial requests

When the user asks for one part ("only the images", "why did the score drop", "test JS defer"), still do the parts
of steps 1–2 that part depends on (current settings, a baseline for what you will compare, rollback files), then go
straight to that step's reference. Say what you skipped. Report the result in the same before → after form.

## Working safely on a live site

- **No MCP save, re-warm, sweep or crawl while a measurement runs or a LiteSpeed test option is on**: every
  Elementor save purges pages, and every page generated while a test option is on is built with it.
- **Check the session before each write** in wp-admin (a `fetch` of an expired session returns the login form with
  status 200) and re-read after each write. The password is the user's to type.
- **Uploading or updating any plugin purges the whole cache**: re-warm, check the sitemap still answers 200.
- **Purge All at most once per batch**, then watch for database errors for a minute (one host dropped its database
  for 30 s after a Purge All).
- **Another session may be working on the same site.** Look at recent files in the site folder before starting a
  long measurement, and do not overwrite another pass's audit files: use a dated `audit-YYYY-MM-DD/`.
- **Close your Chrome tab at the end**, and stop any background server you started (LibreCrawl).

## Done means

- [ ] Every change in the report's section 2 is live and verified (or listed as not live, with the date checked).
- [ ] Before/after numbers for mobile and desktop from the same conditions, with run counts and variance.
- [ ] Sweep and regression checks match the baseline (no new errors, same widget inventory, booking calendar opens,
      menus, popups and forms work, carousels initialise, mobile layout intact).
- [ ] Every rollback file and new attachment id is listed in section 14.
- [ ] 404s, redirecting links and calls to action reported with their owning widget or menu item; booking links
      listed per hotel with what the owner must provide.
- [ ] The options that need approval are proposed with their expected gain (section 12).
- [ ] Both cross-site documents updated and their PDFs rebuilt and looked at (skip with `"report": false`; then
      the chat summary carries the before/after table and the rollback steps).
- [ ] LiteSpeed settings read back and equal to the intended final state; no page carries a tested option.

## Reference files

| File | Read when |
|---|---|
| references/site-setup.md | first use on a machine or a site; site.json fields |
| references/access.md | before REST, MCP or Chrome work; LiteSpeed/Elementor snippets; blocked or expired sessions |
| references/audit-baseline.md | steps 1 and 2 |
| references/links-and-ctas.md | step 1b, LibreCrawl, fixing links |
| references/images.md | step 2b |
| references/patterns.md | step 3: any symptom |
| references/testing.md | simulating a fix, reading PageSpeed and throttled numbers |
| references/batches.md | steps 4, 5, 5b |
| references/site-plugin.md | writing the site plugin or a metahotels-core toggle |
| references/litespeed-options.md | step 6: what each LiteSpeed option did on each site |
| references/propagate.md | step 7, a CDN switch |
| references/report.md | step 8 and the cross-site documents |
| references/history.md | which earlier site had the same problem |
| references/tools.md | every tool in `scripts/`, one line each |
