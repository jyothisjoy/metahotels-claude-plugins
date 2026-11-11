# SEO List Inputs Checklist

What a full run uses (per hotel of a group), who gets it, and what to call it when it's missing. In the run summary, list anything missing under **Missing inputs** using the names below in bold.

Anyone on the MetaHotels team can do every "From you" item except the hotel facts. Drop the files into the hotel's folder (`<domain>/`) before the run, or attach them in desktop chat. If they arrive later, re-run `/hotel-seo <domain>`: it builds on the last run.

---

## Once per machine

- [ ] `/hotel-seo init` from Claude Code (CLI or the desktop app's Code tab): installs LibreCrawl and Chromium, sets up the desktop app, and signs Google in as metahotels.m@gmail.com.
- [ ] Desktop chat users: upload `~/.metahotels-seo/hotel-seo-skill.zip` (Settings → Capabilities → Skills) and restart the app.
- [ ] API keys for the agents in the work folder `.env`: `PAGESPEED_API_KEY` or `GOOGLE_API_KEY` (PageSpeed Insights + Chrome UX Report
      APIs, project metahotels-analytics; the Google sign-in does not cover these), `MOZ_API` (free plan),
      `GEOAPIFY_KEY` (free), `SERPER_API` (serper.dev; monthly report rankings).
- [ ] `sites.csv` in the work folder root (the exported site sheet: Website Name, App name, User name, App Password,
      Content endpoint) — needed for `/hotel-seo execute` and the read-only site checks. Never commit it.
- [ ] `/hotel-seo init --check` shows all OK.

## A. Full report: Audit Report, Build Plan and Web Team List (per hotel)

### 1. Basics. Claude finds these, then asks once (intake)
- **Website URL**: from the command.
- **Hotels of the group**: Claude detects them from the crawl (sections of the group site, booking-engine IDs, Hotel
  schema) and asks you to confirm names, URL paths and cities.
- **Booking.com URL of each hotel** (asked in the same message). Claude reads the page with Claude in Chrome; facts
  count as confirmed only where the hotel's booking engine agrees. Missing: **Booking.com URL**.
- **Mirai hotel ID**: from `<domain>/hotel.json` of an earlier run, else `idtokenprovider=` in the site's booking links.
- **History** (previous management company, recent rebuild, sister hotels on the same domain): from the site, Search Console and the crawl. Tell Claude if you already know it.

### 2. Search Console
**Claude pulls through the MCP:** performance for the last 3 months and the previous 3 (queries, pages, countries, devices, search appearance, dates), sitemaps (status and discovered pages), URL Inspection where the crawl and the live page disagree.

**Claude also pulls** (no exports needed any more):
- Page indexing states for every crawled and sitemap URL (`index_status`, URL Inspection API, 2,000 URLs a day per site).
- Incoming links and Bing sitemaps from Bing Webmaster Tools (`bing_report`, when the Bing key is set up).

**From you, only when relevant:**
- [ ] **Old-URL 404 list**: Indexing → Pages → Not found (404) → Export, only for sites with many old or spam URLs Google still remembers (they're not in any crawl or sitemap). Claude passes them to `index_status`.
- [ ] **Manual actions / Security issues**: screenshot only if Search Console emailed an alert.

If the hotel's property isn't visible to metahotels.m@gmail.com, that is **Search Console access**: add the account as a user on the property.

### 3. GA4
**Claude pulls through the MCP, last 90 days:** events (`purchase` count and revenue, refunds), traffic acquisition by session source / medium with revenue, users and sessions by country, hostname × sessions when the numbers look off.

If the property isn't visible to metahotels.m@gmail.com, that is **GA4 access**: add the account as a Viewer.

### 3b. Rate parity
**Claude pulls** the daily Magic Parity feed (`rate_parity`) when the machine has the parity connection (`hotel-seo-parity-login`). Otherwise list **Rate parity** under Missing inputs.

### 3a. Keyword Planner (non-brand keyword map, per hotel)
**Claude builds it in code** (`build_keyword_map`): candidate searches from the hotel's facts and location (places,
nearby landmarks, type, stars, facilities, rooms, audiences), Keyword Planner ideas from those seeds and from 3–5
competitor hotels' pages, volumes for the hotel's city, country and feeder markets, brand searches filtered out,
clusters with one target page each and their status in Search Console.

**From you, only if `init --check` shows Google Ads not set up:**
- [ ] **Keyword Planner CSVs**: Keyword Planner → Discover new keywords (hotel URL + 5–10 area phrases) → Download keyword ideas → CSV. One file per language and location: English and Arabic, the hotel's country and worldwide. Put them in `<domain>/keywords/` as downloaded; don't open and re-save them. Claude reads them with `import_keyword_csv`, which keeps Arabic in order.

### 4. Mirai
**Claude pulls through the Mirai API** (`mirai_reservations`) when the work folder's `.env` has `MIRAI_USER` and `MIRAI_PASS` (one login covers every MetaHotels hotel on Mirai): bookings, cancellations, revenue, ADR, seasonality by stay month, offers and room types sold by name, club sign-ups, channel source, promo codes, guest countries, and what's on the books for the coming months.

**From you, only if the API isn't set up** (2 min):
- [ ] **Mirai reservations export**: switch the property view to the hotel → Reservations → booking date **1 Mar 2026 → today** → Export Excel. Name it anything; put it in `<domain>/`.

Claude reads the live booking engine itself with `booking_engine_snapshot`: rooms, offers, member rate, cancellation terms and prices for 3 sample stays.

### 5. Crawl. Claude runs it
`crawl_site` with LibreCrawl, which starts by itself. Nothing to export. See [librecrawl.md](librecrawl.md).

### 6. Live site
Claude checks desktop and mobile with Claude in Chrome when it's connected (approve the site when asked), otherwise by fetching pages.

---

## B. Hotel facts (from the hotel contact)

**Hotel information sheet:** the run asks for it right after the crawl starts. Attach the hotel's filled-in sheet or give its path (or a Google Sheets link shared "anyone with the link"); Claude reads .xlsx / .csv / Sheets in code with `import_facts_sheet` into `hotel-facts.json`, and other formats by hand. Say *none* and the run carries on with [CONFIRM] for those facts.

Needed before anything marked **[CONFIRM]** goes live. The run ends with the exact questions as a plain list.
- Current offers: name, discount, booking and stay dates, conditions, whether they stack with the member rate
- Loyalty / member benefits
- Room count, max occupancy per room type (adults + children)
- Distances (airport, metro, landmarks), check-in and check-out, cancellation policy
- Services the site contradicts itself on (room service, breakfast, transfers, parking)

---

## C. Re-check (after the agency says "done")

**Claude does:** the re-crawl and audit, every item's checks against the live site (`recheck_list`: titles, metas, H1s, redirects, removed text and links, schema, alt text), Search Console sitemaps, and the re-issued report.

**From you:**
- [ ] **Agency change list**: their WhatsApp messages, pasted or screenshotted
- [ ] **Bing sitemap screenshot**: only if the Bing key isn't set up (`bing_report` reads it otherwise)

---

## D. Standing access

- [ ] The Google sign-in includes Docs (`init --check` → Google Docs output OK); otherwise lists come as PDF plus a `.docs.html` file.
- [ ] metahotels.m@gmail.com has Search Console and GA4 access for every hotel on the rollout list (`init --check` shows how many properties it sees).
- [ ] `MIRAI_USER` and `MIRAI_PASS` (Mirai XML API) in the `.env` of the work folder on each machine, or the Mirai masterkey (individual hotel views) for the reservations export.
- [ ] Each site's row in `sites.csv` logs in (`sites_csv_status`, `site_mcp_status`): a 401 means the user name or
      application password is wrong; a 403 "not authorized" means that user may not use MCP on the site.
