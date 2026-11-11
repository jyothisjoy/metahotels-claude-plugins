# Audit Playbook — MetaHotels

How we turn a hotel website — or a hotel group's website, hotel by hotel — into a full **Audit Report**, a
ground-up **Build Plan** and a **Web Team List**, how we re-check fixes, and how fixes are applied (execute).

Built from the Nassima, Abar, Gevora, Khalidia, Al Bahar, Atana and Rose Hotels work (Oct 2026). The 11 specialist
agents come from claude-seo (MIT); `hotel-addendum.md` holds the hotel rules every agent follows and
`agent-contract.md` the output contract.

---

## 1. Ground rules

1. **The goal is direct bookings, not SEO scores.** Every finding says why it matters for bookings: credibility, the right page ranking for a money search, a working path to the booking engine, or tracking we can trust.
2. **No time, page or item limits.** Every issue found goes in, with every affected page and URL. Nothing is cut, merged away or shortened to fit a day, an hour budget or a page count.
3. **Every fix must be copy-paste ready.** The exact title, meta, H1, alt text, button text, redirect rule, schema and page copy, so the agency (or execute) writes nothing themselves.
4. **Web team items go on the separate Web Team List.** Analytics setup, speed engineering, templates, theme code, server headers, security and hidden broken files.
5. **Never change offers or prices from what the site already says.** Take them from the live booking engine (Mirai), confirm with the hotel contact, and mark anything unconfirmed **[CONFIRM]**. Execute never changes them.
6. **Facts we can't verify stay [CONFIRM]:** airport distance, room count, occupancy, room service (including "24-hour"), check-in and check-out times, cancellation terms, loyalty tiers and benefits, prices and discounts — **even when the site states them**. Confirmed sources in `hotel-facts.json`: the hotel information sheet, the hotel contact, the live booking engine, and Booking.com **only where the booking engine agrees**. The renderer enforces this.
7. **Check findings on the live site, including the mobile view.** Crawls and AI summaries can be wrong; the Gevora "blank homepage" and the Khalidia "broken logo" both turned out to be false alarms.
8. **Exact alt text only, written after looking at each image.**
9. **Don't suggest removing a YouTube channel or other assets the hotel may want to keep.**
10. **Numbers come from code.** Every count, page list, score and status comes from a tool, with the full count, never a sample. The model writes the copy, not the numbers.
11. **Treat the site as normal unless something is a red flag.**
12. **Each hotel of a group is tracked separately**: its own facts, keyword map, findings, reports, re-checks and execute runs. Site-wide problems appear once, in the Group Summary.

---

## 2. Analysis: what to look for in each source

### Search Console (last 3 months vs previous)
`audit_site` with `gsc_property` computes the brand share (now vs before), non-brand searches at positions 4–20, pages by impressions, old http/www versions still getting clicks, booking pages in search, Arabic searches, spam queries and the live status of every submitted sitemap. Quote those; use the Search Console MCP for anything else.
- **Brand vs non-brand.** Hotel traffic is almost all brand searches, which need no work. Non-brand demand comes from the keyword map (Keyword Planner + the hotel's facts and location + competitor URLs); Search Console only says where the site already shows up. *Al Bahar: about 87% brand.*
- **Money searches stuck at position 5–20.** For example "hotels in [area]", "[area] beach resort", "hotel with kitchenette dubai", "hotel near dubai airport" and Arabic versions. They join the keyword map with their impressions and position; each becomes a title, H1 or copy fix on its target page.
- **Searches that land on the wrong page.** A brand search landing on a blog post, or a dining search landing on the homepage.
- **Versions of the same page.** http/https, www/non-www and trailing slashes all getting impressions. *Al Bahar: the old http://www homepage still gets 1,748 clicks.* This is a red flag: a Critical redirect and canonical fix.
- **Junk pages indexed.** /search/, ?facility= and other parameter pages, tag, author, feed and archive pages, booking-engine step URLs, "X Archive" titles.
- **Page indexing:** `index_status` gives every crawled and sitemap URL's state (Google limits it to 2,000 URLs a day per site; rerun to continue). Old URLs only Google remembers need the 404 export or the server's access logs.
- **Page indexing drilldowns:**
  - **404s:** old-site URLs become redirect rules. Use **Regex** where there's a pattern. Leave URLs that belong to other hotels as 404.
  - **Crawled – not indexed:** usually feeds, tags and thin pages, so noindex or remove them.
  - **"Google chose different canonical":** a canonical or duplicate problem.
  - **robots.txt patterns crawled as URLs** (`/*`, `/wp-content/*`): something prints them as links, usually llms.txt or a plugin. Find it and remove the links.
- **Sitemaps.** Is it submitted? Remove dead or "Couldn't fetch" sitemaps. Is the discovered page count sensible?
- **Countries.** Growing feeder markets, such as Russia, the UK and Germany, can justify a later language or content angle.
- **Links.** `bing_report`: the top linked pages and the sites linking to the hotel. Look for links from sister hotels or the old group site.
- **Manual actions / Security.** Only matters if there's an issue.

### GA4 (standard reports, last 90 days)
- **Events:** Is `purchase` firing with revenue? Are refunds tracked? *Al Bahar: 140 purchases, AED 131,925. Khalidia: no working tracking.*
- **Traffic acquisition (source / medium):** revenue by channel. Organic revenue is the SEO business case. Look for:
  - **Unwanted referrals** (payment gateways, guest-Wi-Fi portals such as `ezxcess.antlabs.com`) → Web Team.
  - **Key events misconfigured**, for example 95% of sessions counted as conversions → Web Team.
- **Country:** cross-check with Search Console.
- **Red flag only: the property tracks another site.** *Khalidia's GA4 was 99.9% gloria-hotels.com data.* Run the Hostname check only when the numbers look off.

### Mirai (reservations, 1 Mar → today)
- Monthly direct bookings, revenue, ADR, length of stay, booking window, rate plans, guest country.
- **UTM blank on all bookings** means attribution is broken → Web Team.
- **Live booking engine check:** search URL `/search/?idtokenprovider=<id>&checkin=dd/mm/yyyy&nights=n&currency=AED&lang=en`. Note:
  - Offers live today and their percentages
  - Member rate
  - Rooms not available
  - Cancellation terms
  Compare these with what the website and pop-ups claim. Any mismatch becomes a question for the hotel contact.
- The Mirai ID is in `<domain>/hotel.json` after the first run; otherwise find it as `idtokenprovider=` in the site's booking links.

### LibreCrawl crawl and audit (Claude runs both)
Claude crawls with the `crawl_site` tool into `<domain>/crawl-<date>/`; LibreCrawl starts by itself. [librecrawl.md](librecrawl.md) covers the files, settings and gotchas. Then `audit_site` turns it into `findings.md` (read it first) and `findings.json` (every URL). Its sections map to list items:

| findings.md section | Report category (agent that builds on it) |
|---|---|
| SEO plugin and sitemaps | Technical + sitemap (seo-technical, seo-sitemap) |
| Canonicals that block indexing | Technical → Indexability, Critical (*Atana: 9 blog posts, about 16,000 impressions*) |
| Titles (suffix, WordPress defaults) | On-Page: the title **template** per post type first, then per page (seo-content) |
| Indexing (account pages, archives, thin groups, empty, odd slugs) | Technical → Indexability; Content → Thin |
| Schema (every distinct block) | Schema: every block Keep / Fix / Delete / Homepage only (seo-schema) |
| Links (broken, sitewide, booking) | Booking path & facts (booking links), Technical → Links (`replace_pairs.csv`) |
| Copy consistency | Content → Credibility (phones also in Local) |
| Blog → booking | Content: the booking paragraph on the busiest posts |
| Languages | Technical → International; keyword map (Arabic demand) |

The crawl files are for detail:
- **`internal_all.csv`:** status codes, titles, metas and H1s (missing, duplicate, wrong hotel, misspelled), word count, indexability. Redirecting URLs show their first 3xx hop and final URL.
- **`canonicals.csv`:** pages pointing to the wrong URL. *Khalidia: 36 pages pointed to /blog/, and the language homepages pointed to the English one.*
- **`directives.csv`:** noindex on the right pages, and nothing important accidentally noindexed. Meta robots only, so check headers with `curl -I` if a page is missing from Google.
- **`structured_data.csv`:** Hotel schema present only on the homepage, no Article schema on normal pages, no self-serving review markup. LibreCrawl lists the JSON-LD but doesn't validate it, so run the homepage and one inner page through Google's Rich Results Test.
- **Custom Search (`custom_search` tool):** leftover text from a previous operator or another hotel (old group names, other hotels' names, false claims). Only search when there's a known risk. Use `case_sensitive` for names that are also ordinary words.
- **`inlinks_4xx.csv` and `inlinks_3xx.csv`:** broken menu and footer links (the `placement` column says navigation, footer or body), redirect chains, dead links to other sites.
- **`images_missing_alt.csv`:** feeds the exact alt text table, written after viewing each image.
- **`hreflang.csv`:** for multi-language sites only.
- **`issues.csv` / `overview.md`:** LibreCrawl's own checks (title and meta length, slow pages). Duplicate Content and Thin Content are noisy on Elementor sites, so treat them as hints, not list items.
- **Speed:** seo-performance measures it (PageSpeed Insights + CrUX field data); engineering fixes go to the Web Team List. `response_time_ms` shows slow server responses.

### Live booking engine (always)
`booking_engine_snapshot` opens the hotel's search page in a browser for 3 sample stays and reads the engine's own data: offers and their discounts, the member discount, cancellation options, rooms with size and occupancy, and the price calendar. It also renders the site's room, offer and loyalty pages and compares them. Use `booking_engine.md`:
- An offer on the site that the engine no longer sells (an expired "Summer Offer") → Booking path & facts, High.
- A package the engine sells with no page on the site → a new page in the Build Plan, held **[waiting for hotel details]**.
- A loyalty page that disagrees with the engine's member benefits → Booking path & facts, held **[waiting for hotel confirmation]**.
- Matches go in "what works" for the Booking path chapter.

Discounts and benefits read on the engine go into `hotel-facts.json` with source "booking engine, <date>".

### Live site check (browser, desktop and mobile)
- Visible footer and menu: wrong hotel names, dead links, the membership/loyalty link.
- Site name in the share preview and the browser title (`og:site_name`).
- Pop-ups and offers against the booking engine.
- Facts that disagree across pages (distance, room count, occupancy, room service, cancellation).
- Hidden broken images vs visible ones. Only visible problems go to the SEO team.
- WordPress REST API `/wp-json/wp/v2/media` (`alt_text`) shows whether alt text was saved in the Media Library. If it was saved but doesn't show on the page, the cause is the cache or widget-level alt text.

---

## 3. Audit Report standards

**Categories and score.** Booking path & facts 15%, Technical 18.7%, Content 19.55%, On-Page 17%, Schema 8.5%,
Performance 8.5%, AI Search 8.5%, Images 4.25% (claude-seo's weights scaled to 85%). A category score is the share of
its checks that pass, weighted by severity (Critical 4, High 3, Medium 2, Low 1) — computed in code. Local, Maps and
Backlinks are scored separately; Lighthouse Agentic Browsing is reported as X/N.

**Severity.** Critical (blocks indexing, sends guests to the wrong place, security / penalty risk), High (significant
ranking or booking impact), Medium (optimisation), Low (polish), Info (awareness only). **Floor:** anything on the
homepage, room pages, offers, contact or the booking path is at least High; a canonical that blocks indexing, a
sitewide broken link and a dead or wrong-hotel booking link are Critical.

**Every finding has:** a severity, evidence with numbers and the tool that produced them, **every** affected URL
(25 shown, all in the linked sheet), the exact fix and where to make it (Rank Math path), the owner (SEO or web),
the machine checks re-check runs, and the execute actions.

**Executive summary:** rate parity first when the site loses on 20%+ of priced checks (a revenue action, outside the
score); then direct bookings and revenue (Mirai), organic revenue (GA4), non-brand visibility, the finding counts, every
Critical and High finding in one line, and what works.

**Typical findings, by category** (from the hotels audited so far):

| Category | Typical findings |
|---|---|
| Booking path & facts | Book Now opening another hotel's engine (*Rose Hotels: four hotels' room pages opened Rose Garden Bur Dubai*), dead / outdated booking links, expired offer pages, packages with no page, Booking.com vs engine vs site conflicts |
| Technical | canonicals to redirects / 404s, SEO plugin off, noindex on key pages, indexable booking / account pages, sitewide broken links, redirect chains, security (spam posts, open MCP routes, spam searches) |
| Content | other hotels' text, another city in headings, wrong phone codes, empty / thin pages, out-of-season wording, prices in FAQs, blog posts with no booking link |
| On-Page | title templates and suffixes, missing / long titles and metas, several H1s from card widgets |
| Schema | invalid JSON-LD, self-written reviews, duplicate LocalBusiness blocks, the corrected Hotel block per hotel |
| Performance | LCP hero images, render-blocking scripts, CrUX field data trend |
| AI Search | AI crawler access, citability of key pages, llms.txt leftovers, agent access to the booking button |
| Images | missing alt text (written after viewing each image) |

### Copy standards
- **Title:** about 60 characters or fewer (hard limit 62–66). Pattern: `[Keyword phrase] | [Hotel name]`. The homepage ends with "Official Site". The keyword phrase comes from the page's cluster in the keyword map.
- **Meta description:** 155 characters or fewer, with the location and landmark, one concrete product fact (sizes, kitchenette, view) and "Book direct" or the member benefit.
- **H1:** one per page, saying what the page is (for example "Rooms & Suites with Kitchenette in Deira, Dubai").
- **Hotel schema fields:** see hotel-addendum.md.
- **Alt text:** what's in the photo plus the hotel name ("King bed and Sheikh Zayed Road view in the Superior Room at Gevora Hotel Dubai"). No "image of".
- **Button text:** "View Deluxe King Room", not "View More".

---

## 4. Build Plan standards

The target site for each hotel, ground up:
1. **Structure:** every page a hotel site should have (home, rooms index, each room type, offers and each live package,
   dining, spa / pool, meetings, location / getting here, gallery, contact, FAQ, guides), marked exists / fix / missing,
   each with its keyword cluster and monthly searches.
2. **Page specs:** URL, SEO title, meta, H1, **full paste-ready copy** (confirmed facts only; [CONFIRM] otherwise),
   sections, JSON-LD, internal links in and out, the booking button with the standard booking link, images and alt needs.
3. **Content plan:** guides from the informational clusters ("things to do near X", "getting from the airport"), with
   briefs (FLOW Find / Win).
4. **Local and AI search:** Google Business Profile changes for the hotel to make, citations, answer blocks, AI access.
5. **Tracking plan** (also on the Web Team List): GA4 purchase with revenue, consent mode, UTM to the booking engine.
6. **Steps in dependency order** (blockers first: indexing and booking path), no dates.
7. **Baseline** for the next run: Health Score and category scores, non-brand impressions and clicks, CWV, indexed
   pages, direct bookings.

---

## 5. Web Team List

Developer items, per hotel; site-wide ones once in the Group Summary:
1. **Security first:** suspicious or backdated posts (full count, by month, latest date), spam search terms, REST / MCP routes that answer without login, leftover llms.txt, public user lists. Immediate steps: find what creates the posts, check admin users, malware scan, rotate passwords.
2. **GA4 setup:** correct property and stream, Consent Mode v2, Mirai `purchase` events with revenue, unwanted referrals (payment gateway, Wi-Fi portal), key events = `purchase` only, internal traffic filters.
3. **UTM / attribution** from site to booking engine.
4. **Performance engineering** with PageSpeed / CrUX evidence: LCP, page weight, Elementor bloat, image formats, caching and CDN.
5. **Template / theme fixes** the SEO side can't do: canonical in the theme, sitewide redirects, headers.
6. **Hidden broken assets** (old logos, dead scripts).

Execute never applies Web Team items.

---

## 6. Re-check (after fixes are done)

`/hotel-seo recheck <domain>` checks every finding of the latest Audit Report (and Web Team List) against the live
site with the checks stored on each finding: Done / Partly / Open / Manual / Waiting. The re-crawl's audit adds new
Critical and High problems (anything the changes broke goes at the very top). The open-items document re-issues only
what is unfinished.

**Before sending any report**, `presend_check` drops findings already fixed live since the crawl and marks partly
done ones.

---

## 7. Execute (apply the fixes)

`/hotel-seo execute` applies the `seo` findings through the site's WordPress MCP (logins from `sites.csv`) and Claude in
Chrome where no tool exists (wp-admin screens, Search Console, Bing Webmaster):
- dry run first (current → new for every change, validated by the site where the tool allows);
- batches approved one at a time: booking-path, SEO fields, redirects, Elementor text, schema, alt text, post status,
  menus, new pages, Chrome steps, and group-wide settings last (they affect every hotel);
- before-values saved, stop at the first error, cache purged, every finding re-checked live; `--undo` restores;
- never: prices, offers, discounts, member benefits, [CONFIRM] or held items, Web Team items, deletions, users,
  plugins / themes, other hotels' pages, Google Business Profile.

---

## 8. Document format

Each document is JSON rendered by `render_report` as PDF, Word and a Google Doc (re-rendering updates the same Doc and
keeps the file number):
- **File names:** "31 - Rose Park Al Barsha Audit Report (24 Oct).pdf", "Build Plan", "Web Team List", "Group Summary",
  "Execute Report"; re-checks "Audit Report Re-check 2" and "Audit Report Open Items after Re-check 2". The running
  number counts across all hotels in the work folder.
- **Audit Report:** cover line with the Health Score, the scores table (categories, separate scores, agent status),
  then one chapter per category (Booking path first) with findings Critical → Info, each with a severity badge.
- **URL lists:** a finding with more than 25 URLs shows 25; every URL is in a CSV next to the report and a Google Sheet.
- **Colours:** red [CONFIRM] for unverified facts, orange "[waiting for …]" for held items.

---

## 9. Lessons learned

- Confirm the crawl is right before reporting. Check Search Console URL Inspection when the crawl and the live page disagree.
- GA4 data can belong to another site. Only check when the numbers look wrong.
- Alt text can be saved in WordPress but not show on the page (cache or widget alt). Check the live HTML, not just the Media Library.
- A useful archive page (/room/ with a decent H1) should be **301-redirected**, not noindexed.
- Old-operator leftovers are common after a hotel changes management company (Gloria → Khalidia): site name, footer, other hotels' text, GA4, old URLs.
- Blog posts returning 404 after a rebuild: list the exact URLs.
- Search Console exports are attachment-heavy. Save files as they arrive and ask for screenshots where a CSV isn't needed.
- Check which SEO plugin is actually live before writing Rank Math steps: look at `/wp-json/` namespaces and whether `/sitemap_index.xml` loads. *Al Bahar (Oct 2026): no SEO plugin was active, every meta description was gone and the submitted sitemap returned 404, so "install Rank Math and import the Yoast data" became the first Critical fix.* If the site already uses the Redirection plugin, keep redirects there and leave Rank Math's Redirections module off.
- Read the JSON-LD in the live HTML of the homepage **and** one inner page. Hand-pasted schema can sit sitewide (Al Bahar had five blocks on every page, one with a self-written 5-star rating). `structured_data.csv` lists the types per page, which makes a sitewide block easy to spot.
- A spam search term in Search Console queries (gambling, pharma) or empty posts with odd titles is a security red flag. It goes at the top of the Web Team list and is raised with the MetaHotels team the same day.
- LibreCrawl stores a redirecting URL with the final page's 200 status and content. Count redirects by the first hop (the helper script does), or every old URL looks like a duplicate live page. *Al Bahar (Oct 2026): 41 redirects, against 39 in the earlier Screaming Frog crawl.*
- LibreCrawl's default depth is 3, which misses deep blog pages. Crawls set it to 10, the most LibreCrawl accepts (it rejects the whole settings save above that); if you crawl from the GUI, raise it in Settings → Crawler first. Al Bahar's deepest page was at depth 9.
- Tracking checks must use the rendered page. *Al Bahar (Oct 2026): the raw HTML has no GTM or GA4, but two GTM containers and a GA4 tag fire at runtime, only after the visitor interacts and only for a normal browser user agent ("HeadlessChrome" gets no tags).* `inspect_pages` handles both.
- Invalid JSON-LD is invisible to Google. *Al Bahar: the sitewide FAQPage block (raw line break inside a string) and the Hotel block (syntax error) don't parse on any of 200 pages, so Google sees no Hotel schema at all.* `audit_site` reports each broken block and the parser error.
- Spam posts come in families with old dates. *Al Bahar: 24 posts titled "cache" and 14 titled "x", all dated 2020-01-01 but last changed between July and October 2026, the latest on 12 Oct.* Report the full count, the trend and the latest date, never "2 junk posts".
- A site's own claims are not confirmation. *Al Bahar: "24-hour in-room dining" (schema) and "3 loyalty tiers" (FAQ) went into a list untagged, and the tiers answer contradicted the Rewards item.* The renderer now blocks these categories unless the hotel confirmed them.
- A canonical pointing to an old address that redirects back blocks both addresses from Google. *Atana (Oct 2026): 9 blog posts kept their pre-/blog/ canonical after the move, together about 16,000 impressions, and one had a typo (/ssuperyacht…).* `audit_site` reports these as `canonical_broken`.
- Card and loop widgets often use H1 for every card. *Atana: 24 H1s on the homepage and a second H1 ("Airport Pickup") on every room page.* One template change fixes them all, so it's one finding, not one per page.
- Old booking-engine links survive in blog posts and old content: `bookingstep1.en.html` with a 2023 date in Indian rupees, now 404. `audit_site` lists them as `booking_link_outdated`. Replace them with the standard booking link and add a Regex redirect for the ones Google still has.
- LibreCrawl's link `placement` (navigation / footer / body) is unreliable on Elementor sites. "Sitewide" in `findings.md` means linked from at least 80% of pages, counted.
- The booking engine sells things the site doesn't show. *Al Bahar: "Stay & Splash" water-sports packages had 6 bookings since July and no page, while the old water-sports offer pages 404.* Check Mirai rate plans against the offer pages on every run.
- A Book Now button can open a sister hotel's booking engine. *Gewan Hotel Cairo (Oct 2026): the Rooms & Suites button opened Gewan Palace, New Alamein.* `audit_site` with `mirai_id` flags every link whose Mirai ID isn't the hotel's and names the hotel it opens.
- Prices written into FAQs go out of date and contradict the booking engine. Replace them with "Rates change by date and room type; you'll see live prices when you check availability."
- Real posts can look backdated: the agency edits old blog posts, so "published 2023, changed this week" alone means nothing. *Al Bahar (18 Oct 2026): 44 genuine posts were edited on 14–15 Oct.* `audit_site` needs a second signal (post ID newer than posts dated long after it, look-alike slugs, empty body) before calling a post suspicious.
- Steps tied to a plugin go stale fast. *Al Bahar: "import the Yoast data into Rank Math" was already done by the time the list went out.* Check the active SEO plugin on the day the list is written (`findings.md`, SEO plugin section) and run `presend_check` before sending.
- A leftover `llms.txt` from a removed SEO plugin keeps describing the site to AI crawlers with stale pages. *Al Bahar: Yoast's llms.txt still served after the switch to Rank Math.* `audit_site` flags it.
- WordPress MCP / abilities plugins expose site control under `/wp-json/` (`mcp`, `wp-abilities`, `elementor-mcp-composer`). Check they require authentication before using them across hotels.
- The Mirai XML API spec and the live API disagree. *Oct 2026: amounts come with a dot (`1306.96`), not the comma the spec shows; reading them the spec's way made revenue 100× too high.* Offer and room names are only in the booking's `distributor` comments. One login covers the whole chain (29 hotels), and cancellations are a big share of daily events (21 of 44 in one day), so always quote the cancellation rate next to bookings. `mirai_reservations` handles all of this.
- Group sites need a per-hotel booking check. *Rose Hotels (Oct 2026): the Book Now buttons on the room pages of Rose Plaza, Rose Park, Rose Executive and Rose Garden Al Barsha all opened Rose Garden Bur Dubai's engine (Mirai 100377547).* `audit_site` with `group_dir` checks each hotel's pages against its own Mirai ID.
- Several hotel sites' LiteSpeed firewalls return 403 to the default python-requests / httpx user agents: the MCP client names itself (`hotel-seo-mcp-client`).
