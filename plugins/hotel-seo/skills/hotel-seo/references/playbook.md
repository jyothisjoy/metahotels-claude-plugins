# SEO List Playbook — MetaHotels

How we turn one hotel's data into the **Priority List**, the **Nice-to-Have List** (called Secondary in older notes) and the **Web Team List**, and how we re-check the agency's work.

Built from the Nassima, Abar, Gevora, Khalidia, Al Bahar and Atana work (Oct 2026). The manual Al Bahar and Atana lists of 14 Oct are the reference for structure and depth.

---

## 1. Ground rules

1. **The goal is direct bookings, not SEO scores.** Every item needs a booking reason: credibility, the right page ranking for a money search, a working path to the booking engine, or tracking we can trust.
2. **The SEO team (the external agency, on India time, Mon–Fri) must finish a Priority List in one working day.** Target about 3.5 hours per hotel, because the pace is now **2 hotels a day**.
3. **Every item must be copy-paste ready.** Give the exact title, meta, H1, alt text, button text, redirect rule, schema and FAQ text, so the agency writes nothing themselves. If they'd have to think about it, it isn't finished.
4. **Web team items go on a separate list.** Analytics setup, speed, templates, theme code, security and hidden broken files go to the web team, not the SEO team.
5. **Never change offers or prices from what the site already says.** Take them from the live booking engine (Mirai), confirm with the hotel contact, and mark anything unconfirmed **[CONFIRM]**. Offers can be a "tomorrow" task.
6. **Facts we can't verify stay [CONFIRM]:** airport distance, room count, occupancy, room service (including "24-hour"), check-in and check-out times, cancellation terms, loyalty tiers and benefits, prices and discounts. This holds **even when the site states them**: hotel sites contradict themselves on exactly these. Only facts in the hotel-confirmed `hotel-facts.json` go in without the tag. The PDF renderer enforces this.
7. **Check findings on the live site, including the mobile view,** before putting them on a list. Crawls and AI summaries can be wrong; the Gevora "blank homepage" and the Khalidia "broken logo" both turned out to be false alarms.
8. **Exact alt text only, written after looking at each image.** Never write generic alt text.
9. **Don't suggest removing a YouTube channel or other assets the hotel may want to keep.**
10. **Numbers come from code.** Every count, page list and status in a list comes from a tool (`audit_site`, crawl files, `inspect_pages`, Search Console, GA4, Mirai), with the full count, never a sample ("24 posts named cache, last changed Jul–Oct 2026", not "junk posts"). The model writes the copy, not the numbers.
11. **Treat the site as normal unless something is a red flag.** Don't ask the MetaHotels team for extra checks "just in case". Ask only when the data looks wrong, for example GA4 traffic that clearly belongs to another hotel.

---

## 2. Daily rhythm

Two hotels a day. Who does what and when is in [team.md](team.md).

---

## 3. Analysis: what to look for in each source

### Search Console (last 3 months vs previous)
`audit_site` with `gsc_property` computes the brand share (now vs before), non-brand searches at positions 4–20, pages by impressions, old http/www versions still getting clicks, booking pages in search, Arabic searches, spam queries and the live status of every submitted sitemap. Quote those; use the Search Console MCP for anything else.
- **Brand vs non-brand.** Share of clicks from searches containing the hotel name. Above 80% brand means the site only catches people who already know the hotel, so non-brand pages are the opportunity. *Al Bahar: about 87% brand.*
- **Money searches stuck at position 5–20.** For example "hotels in [area]", "[area] beach resort", "hotel with kitchenette dubai", "hotel near dubai airport" and Arabic versions. Show these as a table of impressions, position and clicks. Each one becomes a title, H1 or intro-text task.
- **Searches that land on the wrong page.** A brand search landing on a blog post, or a dining search landing on the homepage.
- **Versions of the same page.** http/https, www/non-www and trailing slashes all getting impressions. *Al Bahar: the old http://www homepage still gets 1,748 clicks.* This is a red flag and becomes a Priority redirect and canonical fix.
- **Junk pages indexed.** /search/, ?facility= and other parameter pages, tag, author, feed and archive pages, booking-engine step URLs, "X Archive" titles.
- **Page indexing drilldowns:**
  - **404s:** old-site URLs become redirect rules. Use **Regex** where there's a pattern. Leave URLs that belong to other hotels as 404.
  - **Crawled – not indexed:** usually feeds, tags and thin pages, so noindex or remove them.
  - **"Google chose different canonical":** a canonical or duplicate problem.
  - **robots.txt patterns crawled as URLs** (`/*`, `/wp-content/*`): something prints them as links, usually llms.txt or a plugin. Find it and remove the links.
- **Sitemaps.** Is it submitted? Remove dead or "Couldn't fetch" sitemaps. Is the discovered page count sensible?
- **Countries.** Growing feeder markets, such as Russia, the UK and Germany, can justify a later language or content angle.
- **Links.** The top linked pages and the sites linking to the hotel. Look for links from sister hotels or the old group site.
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
- Known IDs are in [team.md](team.md); otherwise find the ID in the site's booking links.

### LibreCrawl crawl and audit (Claude runs both)
Claude crawls with the `crawl_site` tool into `<domain>/crawl-<date>/`; LibreCrawl starts by itself. [librecrawl.md](librecrawl.md) covers the files, settings and gotchas. Then `audit_site` turns it into `findings.md` (read it first) and `findings.json` (every URL). Its sections map to list items:

| findings.md section | Becomes |
|---|---|
| SEO plugin and sitemaps | Priority: turn the plugin back on, sitemap settings; Search Console sitemaps |
| Canonicals that block indexing | Priority, first item: a canonical to a redirect or 404 means Google indexes neither address (*Atana: 9 blog posts, about 16,000 impressions*) |
| Titles (suffix, WordPress defaults) | Priority titles item: the title **template** per post type first, then the per-page table |
| Indexing (account pages, archives, thin groups, empty, odd slugs) | Priority noindex item; expired and junk pages item |
| Schema (every distinct block) | Priority schema item: a table of every block with Delete / Keep / Homepage only |
| Links (broken, sitewide, booking) | Priority: dead or outdated booking links and sitewide broken links. Nice-to-Have: links through redirects, using `replace_pairs.csv` |
| Copy consistency | Priority quick fixes (wrong phone code, another city in a heading, empty page, company login as author); Nice-to-Have (seasonal wording, prices in FAQs, distances → [CONFIRM]) |
| Blog → booking | Nice-to-Have: the booking paragraph on the busiest posts |
| Languages | Nice-to-Have, for information: browser-side translation isn't indexed; Arabic search demand |

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
- **Speed:** goes on the Web Team list only. LibreCrawl's PageSpeed is off for hotel crawls; `response_time_ms` shows slow server responses.

### Live booking engine (always)
Open the hotel's search URL (team.md) for a date in the next weeks. Note offers and their percentages, the member discount and what it includes, cancellation options, and packages on sale. Compare with the site:
- An offer on the site that the engine no longer sells (an expired "Summer Offer") → Priority expired pages.
- A package the engine sells with no page on the site → Nice-to-Have new page, held **[waiting for hotel details]**.
- A loyalty page that disagrees with the engine's member benefits → Nice-to-Have, held **[waiting for hotel confirmation]**.
- Matches go in the "already working" table.

Discounts and benefits read on the engine go into `hotel-facts.json` with source "booking engine, <date>".

### Live site check (browser, desktop and mobile)
- Visible footer and menu: wrong hotel names, dead links, the membership/loyalty link.
- Site name in the share preview and the browser title (`og:site_name`).
- Pop-ups and offers against the booking engine.
- Facts that disagree across pages (distance, room count, occupancy, room service, cancellation).
- Hidden broken images vs visible ones. Only visible problems go to the SEO team.
- WordPress REST API `/wp-json/wp/v2/media` (`alt_text`) shows whether alt text was saved in the Media Library. If it was saved but doesn't show on the page, the cause is the cache or widget-level alt text.

---

## 4. Priority List: standard items (in this order)

Order by risk to credibility and rankings first, then by the money-search gain. Leave out anything that doesn't apply. Items are **lettered** (A, B, B2, C…). Each item gets:
- a time;
- an italic line saying what is wrong now, with real numbers;
- exact steps (Rank Math / WordPress paths) with exact text;
- a **"Check:"** line the agency can verify themselves (e.g. "homepage, /rooms/ and any room page each have exactly one H1");
- `checks` that prove it's done (see the list schema).

**Severity rule:** a problem on the **homepage, room pages, offers, contact or the booking path** (booking links, booking engine, pop-ups that lead to it) always goes on the Priority list, however small. So do canonicals that block indexing and sitewide broken links. `audit_site` tags these as Priority in `findings.json`.

**Top of the list, before the items:**
- **Lead box** (`lead`): the single biggest issue in two or three sentences with real numbers, plus why timing matters. *Al Bahar, from Mirai: "last year November and December were the hotel's two biggest months for direct bookings (AED 216k and 258k)".*
- **"What's already working (no action)"** (`working`): 4–6 rows of things checked and fine, such as redirects, canonicals, booking tracking with GA4 numbers, alt text, and the booking engine's rates and member discount. It stops the agency redoing them and shows the hotel what's right.

| # | Item | Typical time | Notes / where |
|---|---|---|---|
| A | **Canonicals that block indexing / duplicate versions** | 15–40 min | Rank Math → Advanced → Canonical URL: empty it (self). List every post with its wrong canonical, then Search Console → URL Inspection → Request indexing. Sitewide http→https and www→non-www 301 (Web Team if the server can't). |
| A | **SEO plugin off** (when it is) | 30 min | Activate Rank Math (or the plugin that has the data). Sitemap settings: include pages, rooms, offers, posts; exclude facilities, tags, categories, authors. Noindex tag / category / author / date archives. Set the separator. Local SEO name and logo, with its own Local Business schema **off** when we paste a Hotel block. Check: sitemap_index.xml opens and lists only those types. |
| B | **Titles, metas, H1s** | 40–60 min | First the **title template per post type** (Global, Pages, Posts, Rooms, Offers…) as a small table, which fixes keyword-stuffed suffixes on every page at once. Then a table with exact text per main page, writing "keep" where it's fine. |
| B2 | **Several H1s from cards / widgets** | 30 min | Room and facility cards set as H1 (24 on one homepage): change the loop template's heading tag to H3. One change fixes every page. |
| C | **Schema** | 20 min | A table of **every** JSON-LD block found (type, name, what's in it) with an action each. **Delete:** self-written Review / AggregateRating, a duplicate LocalBusiness or Product with another name or location, Organization duplicates. **Keep, with edits:** the Hotel block (remove OTA lines from sameAs, fix the description). **Homepage only:** FAQPage. Check: Rich Results Test on the homepage and a room page. |
| D | **Credibility fixes** | 15–30 min | A table of where → fix for: other hotels' names or text; another city in headings ("Fine Dining in Dubai" on a Fujairah hotel); a wrong phone country code; empty pages ("No Content Available"); the company login shown as blog author; false claims; cancellation wording that contradicts the booking engine. |
| E | **Broken and outdated links** | 20–25 min | Dead "Book" links and old booking-step links first: replace with the standard booking link from team.md, plus a Regex redirect `^bookingstep1` → the rooms page. Then sitewide broken footer links, and broken menu PDFs and files (upload the file **[from the hotel]** or remove the link). A table: page → link text → change to. |
| F | **Footer / menu links through a redirect** | 5 min | Sitewide links only (in `findings.md` as "Sitewide link through a redirect"). In-content ones are Nice-to-Have. |
| G | **Noindex + merge list pages** | 15–20 min | Noindex only the pages that exist: search, checkout, my-booking, sign-in, sign-up, profile, thank-you; thin post types (facility, nearby) as a whole post type; category archives. 301 the archives to the real pages. Don't noindex a good archive page; redirect it. |
| H | **Expired and junk pages** | 10 min | An offer the booking engine no longer sells: unpublish and 301 to /offers/. Pages made by mistake (/nearby/img/): delete and 301. |
| I | **Redirects for old URLs** | 10–30 min | Rank Math → Redirections (or the Redirection plugin if that's the active one), 301. Regex for patterns, Exact for one-offs, "Starts with" to catch /page/2/. A table of source → destination. |
| J | **Alt text** | 30–60 min | An exact table: file name → alt text, after viewing each image. Leave it out when every image already has good alt text, and say so in "already working". |
| K | **Search Console + Bing** | 5–15 min | Remove dead or "Couldn't fetch" sitemaps by full URL, submit sitemap_index.xml (after the plugin item), request indexing for the canonical fixes, import into Bing. |
| — | **Finish** | — | LiteSpeed (or other cache) → Purge All → send MetaHotels the change list (mark items done only once live). |

Letters follow the order used, so a list without a plugin problem starts canonicals at A, and so on.

**Warning box at the end** when offers or facts are involved: "Don't change offers or prices; we'll send the confirmed copy."

### Copy standards
- **Title:** about 60 characters or fewer (hard limit 62–66). Pattern: `[Keyword phrase] | [Hotel name]`. The homepage ends with "Official Site".
- **Meta description:** 155 characters or fewer, with:
  - location and landmark
  - one concrete product fact (sizes, kitchenette, view)
  - "Book direct" or the member benefit
- **H1:** one per page, and it states what the page is (for example "Rooms & Suites with Kitchenette in Deira, Dubai").
- **Hotel schema fields:**
  - name, alternateName (including Arabic), url, description, logo, image[]
  - telephone, email, address, geo, hasMap
  - checkin and checkout times, starRating
  - amenityFeature[]
  - containsPlace (rooms, with floorSize and occupancy only where stated on the site)
  - sameAs (Maps and the hotel's own socials, **not OTAs**)
  - No priceRange unless confirmed. No room count unless confirmed.
- **Alt text:** describes what's in the photo plus the hotel name. For example "King bed and Sheikh Zayed Road view in the Superior Room at Gevora Hotel Dubai". No "image of".
- **Button text:** "View Deluxe King Room", not "View More".

---

## 5. Nice-to-Have List: standard items

Numbered items. Start only after **every** hotel's Priority List is done; the subtitle says so, with the day's file numbers (team.md). Everything is still exact copy-paste text. Items that wait on the hotel carry `hold` (e.g. "waiting for hotel details") and say exactly what is needed.

1. **Internal links through redirects.** Install Better Search Replace, table `wp_posts`, dry run first, then remove the plugin. Give the search → replace pairs from `replace_pairs.csv`, grouping a common pattern (e.g. "add /blog after .com for these slugs") and putting the most general pattern last. Also list links to remove (keep the words): links to other hotels' sites or old articles that now redirect somewhere unrelated.
2. **Blog posts with two H1s:** the full list of posts. Change the first heading block to H2.
3. **Old years in blog titles:** a table of post → new title (keep the URL), with impressions for the busiest.
4. **Blog → booking paragraph** (`paste` block) at the end of the busiest posts that link to neither rooms nor the booking engine. It names the hotel and links a room page and the standard booking link. Mention the member discount only if it's confirmed or read on the engine.
5. **Small copy fixes:**
   - seasonal wording out of season ("Unlock special winter offers…")
   - fixed prices in FAQs (replace with "Rates change by date and room type…")
   - the same landmark at two distances (one figure, **[CONFIRM with hotel which]**)
   - "Hotel Apartments" for a hotel
6. **Area searches:** a homepage intro and a 60–80 word rooms intro that name the area terms the data shows (e.g. Barsha Heights (TECOM), Al Barsha), each once, in normal sentences.
7. **Room listing intro, "Good to know" boxes, FAQ** where the data shows a gap (kitchenette, family, sea view, near the airport). Unconfirmed answers are marked [CONFIRM].
8. **New page for a package the booking engine sells with no page:** URL, title, H1, offer category, button, and the 301s from old deleted offer pages. Held **[waiting for hotel details]**.
9. **Loyalty / Rewards page** when it disagrees with the booking engine: held **[waiting for hotel confirmation]**, no change until then.
10. **Language versions:**
    - Real language pages: the hreflang setup.
    - Browser-side translation only (GTranslate): an information-only item with the Arabic search numbers. MetaHotels decides.

End with: Purge cache → add to your change list.

## 6. Web Team List: standard items

1. **GA4 setup:**
   - correct property and stream
   - Consent Mode v2
   - Mirai `purchase` events with revenue
   - unwanted referrals (payment gateway, Wi-Fi portal)
   - key events = `purchase` only
   - internal and developer traffic filters
2. **UTM / attribution** from site to booking engine.
3. **Template-level fixes** the SEO team can't do: canonical in the theme, sitewide redirects, header and footer templates.
4. **Speed:** LCP, page weight, Elementor bloat, image formats, caching and CDN.
5. **Hidden broken assets** (old logos, dead scripts).
6. **Security, always first when present:** suspicious or backdated posts (full count, by month, latest date), spam search terms in Search Console, exposed REST namespaces (`mcp`, `wp-abilities`, `elementor-mcp-composer`: confirm they require authentication), public user lists. Name the immediate steps: find what creates the posts, check admin users, malware scan, rotate passwords.

---

## 7. Re-check (after the agency says "done")

`/hotel-seo recheck <domain>` checks every item of the lists that were sent against the live site, using the `checks` written into each item.

**Inputs:**
- **Claude:** a re-crawl into `<domain>/recheck-<date>/` with the same settings, `audit_site` on it, and `recheck_list` for each list sent (title, meta, H1, redirect, status, canonical, noindex, text and link removal, alt text and schema checks run automatically).
- **Claude:** Search Console sitemaps through the MCP; `inspect_pages` for anything that needs the rendered page.
- **From the user:** the agency's WhatsApp change list, the Bing Webmaster sitemap screenshot, and the hotel's answers to [CONFIRM] questions if they've arrived.

**Output, in the same style as the morning list:**
1. A short opening that thanks them and states what's live.
2. A **status table** per item: **Done / Partly / Open** plus a one-line note (from `recheck_list`, never by eye).
3. **Lettered sections (A, B, C…)** for each unfinished item, with what the live site shows now and the exact fix still needed.
4. The hotel's confirmed corrections (offers, occupancy) as their own lettered sections.
5. What the agency said on WhatsApp, for example "redirects being reviewed tomorrow" or "Search Console waiting on dev".
6. New Priority-type problems the re-crawl found, as their own lettered sections.

Also re-issue the list with only the unfinished items (the open-items list), so the agency works from one current document.

---

## 8. PDF format

Claude writes each list as JSON ([../templates/lists.schema.json](../templates/lists.schema.json)) and `render_lists_pdf` produces the PDF, so the layout below is built in.

- **File name:** "25 - Al Bahar Priority SEO List (14 Oct).pdf". That is a running file number across hotels (`file_number`; "auto" takes the next free one), then hotel, list, day and month.
- **Header:** "[Hotel]: Priority SEO List — 14 Oct". Sub-line: "From MetaHotels · [site] · from [sources, with the crawl's page count] and live checks on [date] · about [total time] · [the order across hotels]".
- **Lead box** (green): the biggest issue and its timing (Priority only).
- **Item box:** letter or number, task, time, then a "Finish" row.
- **"What's already working (no action)"** table (Priority only).
- **Each section:**
  - a navy bar with the title and time
  - an italic line with real numbers
  - steps with exact text in tables
  - grey boxes for code and paths
  - green boxes for prose to paste (`paste`, with links shown as __words__ [→ /path/])
  - a "Check:" line
- **Colours:** orange "[waiting for …]" for held items, red [CONFIRM] for unverified facts, a red box for the offers hold.
- **Footer:** "When done: LiteSpeed → Purge All → send MetaHotels the change list (mark items done only once they are live). We will re-crawl and check every item."
- **Length:** 3–4 A4 pages for a Priority list, 2–3 for Nice-to-Have. No near-empty last page: the renderer warns, then tighten wording or merge a short section.

## 9. Message templates

In [team.md](team.md).

---

## 10. Lessons learned

- Confirm the crawl is right before reporting. Check Search Console URL Inspection when the crawl and the live page disagree.
- GA4 data can belong to another site. Only check when the numbers look wrong.
- Alt text can be saved in WordPress but not show on the page (cache or widget alt). Check the live HTML, not just the Media Library.
- A useful archive page (/room/ with a decent H1) should be **301-redirected**, not noindexed.
- Old-operator leftovers are common after a hotel changes management company (Gloria → Khalidia): site name, footer, other hotels' text, GA4, old URLs.
- Blog posts returning 404 after a rebuild: list the exact URLs.
- Search Console exports are attachment-heavy. Save files as they arrive and ask for screenshots where a CSV isn't needed.
- Check which SEO plugin is actually live before writing Rank Math steps: look at `/wp-json/` namespaces and whether `/sitemap_index.xml` loads. *Al Bahar (Oct 2026): no SEO plugin was active, every meta description was gone and the submitted sitemap returned 404, so "install Rank Math and import the Yoast data" became Priority item 1.* If the site already uses the Redirection plugin, keep redirects there and leave Rank Math's Redirections module off.
- Read the JSON-LD in the live HTML of the homepage **and** one inner page. Hand-pasted schema can sit sitewide (Al Bahar had five blocks on every page, one with a self-written 5-star rating). `structured_data.csv` lists the types per page, which makes a sitewide block easy to spot.
- A spam search term in Search Console queries (gambling, pharma) or empty posts with odd titles is a security red flag. It goes at the top of the Web Team list and is raised with the MetaHotels team the same day.
- LibreCrawl stores a redirecting URL with the final page's 200 status and content. Count redirects by the first hop (the helper script does), or every old URL looks like a duplicate live page. *Al Bahar (Oct 2026): 41 redirects, against 39 in the earlier Screaming Frog crawl.*
- LibreCrawl's default depth is 3, which misses deep blog pages. Crawls set it to 10, the most LibreCrawl accepts (it rejects the whole settings save above that); if you crawl from the GUI, raise it in Settings → Crawler first. Al Bahar's deepest page was at depth 9.
- Tracking checks must use the rendered page. *Al Bahar (Oct 2026): the raw HTML has no GTM or GA4, but two GTM containers and a GA4 tag fire at runtime, only after the visitor interacts and only for a normal browser user agent ("HeadlessChrome" gets no tags).* `inspect_pages` handles both.
- Invalid JSON-LD is invisible to Google. *Al Bahar: the sitewide FAQPage block (raw line break inside a string) and the Hotel block (syntax error) don't parse on any of 200 pages, so Google sees no Hotel schema at all.* `audit_site` reports each broken block and the parser error.
- Spam posts come in families with old dates. *Al Bahar: 24 posts titled "cache" and 14 titled "x", all dated 2020-01-01 but last changed between July and October 2026, the latest on 12 Oct.* Report the full count, the trend and the latest date, never "2 junk posts".
- A site's own claims are not confirmation. *Al Bahar: "24-hour in-room dining" (schema) and "3 loyalty tiers" (FAQ) went into a list untagged, and the tiers answer contradicted the Rewards item.* The renderer now blocks these categories unless the hotel confirmed them.
- A canonical pointing to an old address that redirects back blocks both addresses from Google. *Atana (Oct 2026): 9 blog posts kept their pre-/blog/ canonical after the move, together about 16,000 impressions, and one had a typo (/ssuperyacht…).* `audit_site` reports these as `canonical_broken`.
- Card and loop widgets often use H1 for every card. *Atana: 24 H1s on the homepage and a second H1 ("Airport Pickup") on every room page.* One template change fixes them all, so it's one Priority item, not one per page.
- Old booking-engine links survive in blog posts and old content: `bookingstep1.en.html` with a 2023 date in Indian rupees, now 404. `audit_site` lists them as `booking_link_outdated`. Replace them with the standard booking link and add a Regex redirect for the ones Google still has.
- LibreCrawl's link `placement` (navigation / footer / body) is unreliable on Elementor sites. "Sitewide" in `findings.md` means linked from at least 80% of pages, counted.
- The booking engine sells things the site doesn't show. *Al Bahar: "Stay & Splash" water-sports packages had 6 bookings since July and no page, while the old water-sports offer pages 404.* Check Mirai rate plans against the offer pages on every run.
- Prices written into FAQs go out of date and contradict the booking engine. Replace them with "Rates change by date and room type; you'll see live prices when you check availability."
- WordPress MCP / abilities plugins expose site control under `/wp-json/` (`mcp`, `wp-abilities`, `elementor-mcp-composer`). Check they require authentication before using them across hotels.
