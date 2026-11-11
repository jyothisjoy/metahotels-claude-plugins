# Hotel addendum (every agent loads this; it wins over claude-seo's generic rules)

claude-seo has no hotel vertical. These are MetaHotels' rules for hotel sites, from the playbook and the hotels
already audited. Where they differ from a claude-seo reference, **this file wins**.

## Ground rules

1. **The goal is direct bookings, not scores.** Every finding says why it matters for bookings: credibility, the right
   page ranking for a money search, a working path to the booking engine, or tracking that can be trusted.
2. **Copy-paste ready.** Give the exact title, meta, H1, alt text, button text, redirect rule, schema and copy. If the
   agency or execute would have to think about it, it isn't finished.
3. **Never change offers or prices** from what the site already says. Prices, discounts, offers and member benefits
   come from the live booking engine and the hotel; anything unconfirmed is marked **[CONFIRM]**.
4. **Facts we can't verify stay [CONFIRM]:** airport distance, room count, occupancy, room service (including
   "24-hour"), check-in and check-out times, cancellation terms, loyalty tiers and benefits, prices and discounts —
   even when the site states them. Confirmed sources (in `hotel-facts.json`): the hotel information sheet, the hotel
   contact, the live booking engine, and Booking.com **only where the booking engine agrees** (source
   "Booking.com + booking engine, <date>"). Booking.com alone is not confirmation.
5. **Check findings on the live site, desktop and mobile,** before reporting them (inspect_pages, render_page).
   Crawls and summaries can be wrong (the Gevora "blank homepage" and the Khalidia "broken logo" were false alarms).
6. **Alt text only after looking at each image** (download_images, then read the image). Never generic alt text.
7. **Numbers come from code**, full counts, never samples ("24 posts named cache, last changed Jul–Oct 2026").
8. **Don't suggest removing a YouTube channel or other assets the hotel may want to keep.**
9. **Treat the site as normal unless something is a red flag.**
10. **Web-team work** (analytics setup, speed engineering, templates / theme code, server headers, security) has
    `owner: "web"` and goes to the Web Team List.

## Copy standards (override claude-seo's length rules)

- **Title:** about 60 characters (hard limit 62–66). Pattern `[Keyword phrase] | [Hotel name]`; the homepage ends with
  "Official Site". The keyword phrase comes from the hotel's keyword map (non-brand cluster for that page).
- **Meta description:** 155 characters or fewer, with the location / landmark, one concrete product fact (sizes,
  kitchenette, view) and "Book direct" or the member benefit (only if confirmed).
- **H1:** exactly one per page, saying what the page is ("Rooms & Suites with Kitchenette in Deira, Dubai").
- **Alt text:** what is in the photo plus the hotel name ("King bed and Sheikh Zayed Road view in the Superior Room at
  Gevora Hotel Dubai"). No "image of".
- **Buttons:** "View Deluxe King Room", not "View More"; booking buttons say "Book now" / "Check availability".
- **Topical-coverage floors** (not ranking rules): home 500 words, room page 300, offer 300, location / getting-here
  500, dining / spa / meetings 300, blog 800. `content_scan` reports pages below them.

## The booking path

- Standard booking link for every "Book now" fix and blog paragraph:
  `https://<domain>/search/?idtokenprovider=<mirai_id>&lang=en&currency=AED` — no dates, no other currency (old links
  with a 2023 check-in date or `currency=INR` are what break).
- On a group site each hotel's pages must open **its own** Mirai ID; shared group pages may open any group hotel.
- Expired offers: an offer page the booking engine no longer sells is unpublished and 301'd to /offers/ (dining and
  spa offers excepted). Packages the engine sells with no page become new pages in the Build Plan (held for the hotel).

## Hotel schema (seo-schema, seo-local)

- One `Hotel` (or `LodgingBusiness` / `Resort`) block per hotel, on that hotel's homepage / main page, with: name,
  alternateName (Arabic too), url, description, logo, image[], telephone, email, address (PostalAddress), geo (5+
  decimals), hasMap, checkinTime / checkoutTime (confirmed only), starRating (Rating, if official), amenityFeature[]
  (LocationFeatureSpecification), petsAllowed, containsPlace (HotelRoom / Suite with bed, occupancy, floorSize only
  where confirmed), sameAs (Google Maps and the hotel's own socials — **not OTAs**). No priceRange or numberOfRooms
  unless confirmed. On a group site: an `Organization` for the group with `subOrganization` / each Hotel with
  `parentOrganization` and its own `@id`.
- Offers / packages: `Offer` or `AggregateOffer` only with confirmed prices; else describe without prices.
- `LodgingReservation` is for booking confirmation emails, not pages.
- Delete self-written `Review` / `AggregateRating`, duplicate LocalBusiness / Product blocks with other names,
  Organization duplicates. **FAQPage**: rich results were retired on 7 May 2026 — an existing block is Info only,
  don't add new ones for Google; never recommend HowTo or SpecialAnnouncement.

## Local and maps (seo-local, seo-maps)

- Business type: brick-and-mortar hotel. Citations that matter for hotels: Google Business Profile, Tripadvisor,
  Booking.com, Expedia / Hotels.com, Agoda, Bing Places, Apple Business Connect, Facebook — instead of Yelp / BBB.
- NAP must match across the hotel's page, its schema, its Google Business Profile, Booking.com and the booking engine.
- GBP for hotels: category "Hotel" (or "Resort hotel" / "Serviced apartment" when that is what it is), hotel class,
  amenities attributes, check-in / check-out, the booking link (field 19 of the checklist) pointing to the standard
  Mirai link with UTM parameters, photos per room type, owner replies to reviews.
- Business Profile fixes are `gbp` actions; MetaHotels makes them through execute's business-profile batch (each a
  gbp_propose change the user approves). Never the name, address or primary category from a finding.

## Rank Math / WordPress paths

- Page title / meta / canonical / robots: Rank Math box on the page → General / Advanced.
- Title templates per post type: Rank Math → Titles & Meta → (post type).
- Sitemap: Rank Math → Sitemap Settings. Redirects: Rank Math → Redirections, or the Redirection plugin when active.
- Elementor: headings in loop / card templates are changed once in the template (Templates → Theme Builder / Loop).
- Cache: LiteSpeed → Purge All after every batch.

## Lessons learned (from the playbook)
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
