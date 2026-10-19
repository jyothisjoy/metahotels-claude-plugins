# Audit check registry — hotel-seo

**Registry version 1.1 (19 Oct 2026; 1.1 removed the Core Web Vitals checks and booking attribution by landing page).** The fixed list of what a hotel audit looks at, how each check is decided, and where its result goes. Built from the MetaHotels audit specification and mapped onto this plugin's tools.

The playbook says *how we work*; this file says *what must be checked, every run, and how a result is recorded*. Where they differ, the playbook's ground rules win (direct bookings first, copy-paste ready, numbers from code, [CONFIRM] for unverified facts, severity rule).

---

## 0. How to use this registry

1. **You don't decide which checks exist.** Every run walks every check below. A new kind of check gets an ID here and a version bump (section 9). Don't add ad-hoc criteria to a list.
2. **Every check ends in exactly one result:**

   | Result | Meaning |
   |---|---|
   | `finding` | The check found an issue or an opportunity, with evidence. |
   | `no_issue` | The check ran on the data it needs and found nothing. |
   | `insufficient_data` | The source is connected but the sample is too small to judge (thresholds in section 3). |
   | `not_available` | The source isn't connected or doesn't expose the field (e.g. backlinks, competitor data). |
   | `not_applicable` | The check doesn't apply to this hotel (e.g. hreflang on a one-language site, breadcrumbs on a site without them). |

   **Missing data is never a pass.** `not_available` and `insufficient_data` are reported as such, never as `no_issue`.
3. **Two layers per finding, kept apart:**
   - the **observed condition** (what the tool shows: "canonical of /rooms/ is https://hotel.com/room/, which returns 404")
   - the **inferred impact** (what it probably means: "Google indexes neither address"). Impact always comes with a confidence.
4. **Evidence first.** A finding is `verified` only with evidence from the source the check names (section 4). No evidence → `unverified` and it doesn't go on a list.
5. **One finding per root cause.** A template defect on 200 pages is one finding with a URL group, not 200 findings (Atana: 24 card H1s on the homepage and one on every room page were one item). Deduplicate by check ID + root cause + URL group.
6. **Record it.** Every run writes the findings register and the coverage table (section 5).

**Mode codes used in the tables:**
- **A** — computed by a tool; quote the tool's number (`audit_site` → `findings.json` field, unless another tool is named).
- **C** — Claude checks it with a tool (Search Console / GA4 MCP, `inspect_pages`, `read_crawl_file`, `booking_engine_snapshot`…) and records what it looked at.
- **H** — needs input from the hotel or the user (information sheet, confirmation, export).
- **N** — no connected source in this plugin today: result is `not_available` unless the user supplies data.

**List codes:** **Pri** = Priority, **NtH** = Nice-to-Have, **Web** = Web Team, **Hotel** = question for the hotel contact, **Notes** = run notes only (no agency action). "Pri*" means Priority when it touches the homepage, rooms, offers, contact or the booking path (severity rule), otherwise the list after the slash.

---

## 1. Decision rules

### 1.1 Severity (how bad the problem is)

| Severity | Use for |
|---|---|
| **critical** | Important pages blocked from Google (noindex, robots, canonical to an error), sitewide server errors, a broken booking path, defacement or spam posts being created now, site-control routes open without login. |
| **high** | Key-page problems that cost rankings or bookings: canonicals to redirects, dead booking links, a Book Now opening another hotel, wrong phone or city on key pages, invalid Hotel schema, expired offers still live, material traffic loss. |
| **medium** | Content gaps, weak internal links, snippets below their potential, template improvements, links through redirects. |
| **low** | Minor metadata, cosmetic copy, speculative opportunities with thin evidence. |

Severity and **opportunity** are separate: an indexing defect is a problem to fix (`finding_type: issue`); a promising search is an opportunity to pursue (`finding_type: opportunity`). Opportunities carry an opportunity score (1.3), not a severity above medium.

### 1.2 Priority level (P0–P3) and which list it goes on

| Level | Meaning | List |
|---|---|---|
| **P0 — critical** | Fix today. Indexing blocked on key pages, sitewide errors, broken canonicalisation after a move, broken booking journey, active security problem. | Pri (security: top of Web, and raised in the finish message) |
| **P1 — high** | Material traffic or booking loss, significant technical issue, broken high-value page, credible high-value conversion opportunity. | Pri |
| **P2 — medium** | Content gaps, internal links, snippets, template improvements with a reasonable expected benefit. | NtH (Pri* if on a key page) |
| **P3 — low** | Minor or speculative. | Notes, or NtH if it takes under 5 minutes |

**Overrides, in this order:**
1. Security, indexing blockers and sitewide failures are P0 whatever the score.
2. The playbook severity rule: anything on the homepage, room pages, offers, contact or the booking path goes on the **Priority list**, however small (it keeps its P-level for ordering).
3. Owner beats level: analytics, speed, templates, theme code, server config, security and hidden broken files go on the **Web Team list** at any level.
4. Anything that depends on a hotel fact is held **[waiting for hotel …]** or tagged **[CONFIRM]**; it never goes out as a fact.

### 1.3 Task score (orders items within a level)

Rate each from 1 to 5 and write the four numbers in the register, so the order can be reproduced:
- **Impact** — expected effect on direct bookings (revenue at stake, page importance, season).
- **Confidence** — strength of the evidence (5 = verified on the live site from two sources; 1 = a hint).
- **Reach** — number and importance of pages affected (a template = high reach).
- **Effort** — work for the agency or web team (1 = minutes, 5 = days).

`score = round(((impact × 0.4 + confidence × 0.3 + reach × 0.3) × 20) / (1 + effort × 0.15))`

This is an ordering tool for our lists, not a Google ranking formula. Within a list, sort by P-level, then score. The playbook's standard item order (canonicals → plugin → titles → schema → credibility → links …) still decides the letters when scores are close.

### 1.4 Approval

Lists are instructions that MetaHotels sends; nothing is changed on a site by Claude. Items that change **redirects, canonicals, robots rules, noindex on more than a handful of pages, or bulk content** must show their evidence in the item (the URLs and what the live site shows now), so MetaHotels can approve them by sending the list.

---

## 2. Rules that apply to every check

1. **Purpose before verdict.** A blocked or noindexed URL is only a problem if the page is meant to rank (account, search, checkout and thank-you pages *should* be noindex).
2. **A canonical is a signal, not a command.** Report what the page declares and what Google chose (`index_status`) separately.
3. **Average position is an average** across users, places and days, not a fixed rank. Say so when quoting it to the hotel.
4. **Keyword Planner volume is an estimate**, not a traffic forecast. Never promise rankings or traffic.
5. **No keyword density targets.** Ever.
6. **Correlation isn't causation.** A rise after a change doesn't prove the change caused it (season, price, availability, parity).
7. **Hotel facts come from the source of truth:** `hotel-facts.json` (information sheet, hotel contact, booking engine with date). The site is not confirmation of itself (playbook ground rule 6).
8. **Never invent:** referring domains, backlink counts, competitor rankings, distances, amenities, prices, review scores. If there's no source: `not_available`.
9. **Multi-hotel domains:** every metric and ID is resolved to this hotel at page level (`hotel_path`) before it's attributed.
10. **Times from APIs are UTC** unless labelled; convert before saying "changed today".

---

## 3. Thresholds (starting values; tune per hotel and note changes in the run notes)

| Rule | Starting threshold |
|---|---|
| High impressions, low CTR (G01) | ≥ 500 impressions in the window **and** CTR clearly below other queries at a similar position on the same site (compare against the site's own CTR for that position band, not a global table). |
| Ranking improvement candidate (G02) | Average position 4–15 (the audit lists 4–20; prioritise 4–15), ≥ 100 impressions in 90 days (≥ 30 for Arabic or niche markets), relevant to a bookable product. |
| Declining clicks (G03) | ≥ 20% fewer clicks **and** ≥ 50 clicks lost vs the comparable period (same months last year when there's a year of data; else the previous 90 days with seasonality noted). |
| Falling impressions (G04) | ≥ 25% and ≥ 2,000 impressions lost. |
| Possible cannibalisation (G11, O07) | Two or more URLs each with ≥ 20% of a query's impressions, or the top page for the query changing between periods. |
| GA4 high traffic, low conversion (A02) | ≥ 200 organic sessions in 90 days and a key-event rate under half the site's organic average. |
| Low traffic, high conversion (A03) | ≥ 3 conversions and a conversion rate at least double the site's organic average. |
| Sample-size floor | Below 30 clicks, 100 sessions or 5 bookings in a segment: `insufficient_data` for rate comparisons. A drop from 2 clicks to 0 is not a finding. |
| Thin content (O10) | A hint, not a rule: median content words per page group (`report.page_groups.thin_groups`) plus a look at what the page is for. Word count alone never decides it. |
| Slow server (P01) | `response_time_ms` in `internal_all.csv` over 1,500 ms on key pages, or over 800 ms median across the site. |

---

## 4. The registry

### 4.1 Technical SEO and crawlability (T)

| ID | Check | How in this plugin | Mode | Sev | List |
|---|---|---|---|---|---|
| T01 | **Status codes:** unexpected 4xx/5xx, redirect loops, soft-404s | `internal_all.csv` status (first hop for redirects); `findings.json` `pages_failed`; `report.page_groups.empty_pages` (says "No content available", "page not found") = soft-404 candidates | A | crit/high | Pri* / NtH |
| T02 | **Indexability** of pages meant to rank: meta robots, X-Robots-Tag, robots.txt, canonical | issues `noindex_on_key_page`; `pages[].robots`, `x_robots_tag`; `report.sitemaps.robots_txt.disallow`; account pages that *should* be noindex: `report.account_pages` / `booking_page_indexable` | A | crit | Pri |
| T03 | **Canonical correctness:** absolute, resolves 200, indexable, the preferred URL; conflicting signals | `report.canonical_targets` (`canonical_broken` = to a redirect/404, Priority; `canonical_other`), `canonical_missing`; what Google chose: `index_status` ("Google chose different canonical") | A + C | high | Pri |
| T04 | **Redirects:** chains, loops, irrelevant targets, http/https, www/non-www, trailing slash | `inlinks_3xx.csv`, `report.links.redirected_targets`; `gsc.host_variant_pages` (old versions still getting clicks); `test_redirects` for a list of old URLs | A + C | high | Pri (sitewide 301s: Web if the server must do it) |
| T05 | **XML sitemap:** URLs return 200, are canonical, no redirects / noindex / errors; post types sensible | `report.sitemaps` (status, entries, `includes`), `gsc.submitted_sitemaps` (live status, errors, last read); `index_status` for sitemap URL states | A | high | Pri |
| T06 | **robots.txt:** syntax, Sitemap line, nothing important or needed CSS/JS blocked | `report.sitemaps.robots_txt` (status, sitemap lines, disallow); compare disallow rules with key pages and `/wp-content/` assets | A + C | crit | Pri / Web |
| T07 | **Internal link crawlability:** key pages without crawlable links, links to broken targets, JS-only navigation | `report.links.broken_targets`; orphan check via `report.coverage.added_examples` (pages only found in sitemaps / WordPress); `inspect_pages` for menus that only exist after JS | A + C | high | Pri* / NtH |
| T08 | **Duplicate URLs:** parameters, slash / case / protocol / host variants, tracking parameters | `gsc.host_variant_pages`; `index_status` duplicates; `internal_all.csv` URLs with `?` parameters; `pages_by_impressions` with parameter URLs | A + C | med/high | Pri (if indexed) / NtH |
| T09 | **Pagination, filters, calendars:** room/offer filters, sort parameters, date URLs creating endless URLs | `report.archives_indexable` (`/page/N/`, date archives), `?facility=` and `/search/?` URLs in `gsc.booking_and_account_pages` | A | med | Pri (noindex item G) |
| T10 | **Rendering:** content, links, title, canonical or schema missing or different after JavaScript | `inspect_pages` (rendered H1s, JSON-LD, tags) vs raw `pages[]`; `tags_rendered` vs `tags_in_raw_html` | C | high | Pri / Web |
| T11 | **Broken assets:** missing images, CSS, JS, fonts; blocked resources | `inlinks_4xx.csv` (assets), `inspect_pages` screenshots; visible problems only go to the agency, hidden ones to Web (playbook) | A + C | med/high | Pri* / Web |
| T12 | **HTTPS:** valid certificate, no mixed content, http → https 301 | `gsc.host_variant_pages` (http still getting clicks), `test_redirects` on `http://` and `http://www.`; mixed content: `custom_search` for `src="http://` | C | high | Pri / Web |
| T13 | **Index discrepancy:** key pages excluded, "discovered / crawled – not indexed", indexed despite noindex | `index_status` grouped states vs the crawl's indexable pages | A | high | Pri |
| T14 | **URL discovery completeness:** sitemap vs crawl vs GSC landing pages; orphans | `report.coverage` (pages the crawl missed), `gsc.pages_by_impressions` URLs not in the crawl, 404 export (H) for URLs only Google remembers | A + H | med/high | Pri (redirect item I) |

### 4.2 On-page SEO and content quality (O)

| ID | Check | How in this plugin | Mode | Sev | List |
|---|---|---|---|---|---|
| O01 | **Title:** missing, empty, duplicate, misleading, too long, stuffed suffix, WordPress default | issues `title_missing`, `title_too_long`; `report.titles` (suffixes, `stuffed`, `default_wordpress_titles`, `duplicate_titles`) | A | high on key pages | Pri (title template first) |
| O02 | **Meta description:** missing, duplicate, irrelevant on key pages | issues `meta_missing`, `meta_too_long`; `report.titles.meta_description_coverage`; SEO plugin printing (`seo_plugin_output_pages`) | A | med/high | Pri* / NtH |
| O03 | **H1:** missing, doesn't describe the page, or several H1s that **compete** | issues `h1_missing`, `h1_multiple`. Two sensible H1s alone aren't an error (P3); H1s from cards/widgets (template) or conflicting H1s are an item | A + C | high (template) / low | Pri (B2) / NtH (blog) |
| O04 | **Heading hierarchy:** headings that don't describe sections or jump confusingly | `inspect_pages` rendered headings on key pages | C | low | NtH |
| O05 | **Search intent:** does the page satisfy the queries that land on it? | Search Console query + page (`get_search_by_page_query`) vs the page's content | C | med | NtH / Pri* |
| O06 | **Topic relevance:** the page clearly covers its target query cluster | K01 mapping vs title / H1 / intro | C | med | Pri* (titles) / NtH |
| O07 | **Cannibalisation:** pages competing for the same intent | Search Console query + page, threshold in section 3; see G11 | C | med | NtH |
| O08 | **Completeness:** information guests need for the page type is missing (rooms: size, beds, view, occupancy, inclusions; offers: dates, terms) | site text vs `booking_engine_snapshot` and `hotel-facts.json` | C + H | med | NtH (held for hotel details) |
| O09 | **Duplicate content** across pages meant to be distinct | LibreCrawl duplicate hints (noisy on Elementor: hints only), `report.page_groups` | A + C | med | NtH |
| O10 | **Thin or empty content** relative to purpose (not word count alone) | `report.page_groups` (`thin_groups`, `empty_pages`, `junk_slugs`) + a look at each group's purpose | A + C | med (empty key page: high) | Pri (H) / NtH |
| O11 | **Alt text** on meaningful images (decorative images: empty alt is right) | `images_missing_alt.csv`, `wordpress.media.missing_alt_text`; alt written only after viewing each image | A + C | med | Pri (J) |
| O12 | **Image relevance:** the photo shows the room / facility / place described | `inspect_pages` screenshots; view the images | C | med | NtH / Hotel |
| O13 | **Internal anchor text:** generic ("click here", "View more"), misleading or broken | `inlinks` anchors, `report.links.broken_targets[].anchors` | A + C | low/med | NtH |
| O14 | **Freshness:** outdated time-sensitive details, contradictions with current hotel info | issues `old_year_in_title`, `out_of_season_wording`; `report.prices_in_text`; `report.distance_conflicts` | A | med | NtH (Pri* on key pages) |
| O15 | **Conversion content:** CTAs, room details, amenities, policies, location, booking path | `report.blog_booking_links`, `pages[].links_booking` / `links_rooms`; `inspect_pages` mobile screenshots for visible CTAs | A + C | med/high | Pri* / NtH |
| O16 | **Language and localisation:** lang attribute, mixed languages, locale pages, hreflang, canonicals per language | `report.translation` (client-side plugin, hreflang pages), `hreflang.csv`, `gsc.arabic_queries` | A | med | NtH (information) |
| O17 | **Trust and accuracy:** unsupported claims, invented amenities, inconsistent contacts, misleading promotions | `render_lists_pdf` [CONFIRM] guard; `report.phones`, `other_city`, schema self-reviews (`report.schema` flags), `custom_search` for old-operator text | A + C | high | Pri (D) |
| O18 | **Structured presentation:** key facts in clear headings, lists, tables | `inspect_pages` on room and offer pages | C | low | NtH |

**Keyword recommendation workflow (for every page you propose to change):**
1. Its current Search Console query cluster (query + page).
2. New opportunities from `keyword_ideas` / `keyword_volumes`.
3. Intent: hotel discovery, location, room, amenity, offer, brand, informational.
4. Improve this page, or is a new page justified (C02/C03)?
5. Does another URL already serve this intent (O07/G11)? Then that URL is the target.
6. The exact element to change: title, H1, intro paragraph, FAQ, internal link, page structure.
7. The expected benefit and how it will be measured (V09 window).

### 4.3 Search Console opportunity engine (G)

Windows: last 90 days vs the previous 90 (the audit's default) and the same 90 days last year when there's a year of data. Query + page for anything that names a page.

| ID | Pattern | How in this plugin | Mode | Type | List |
|---|---|---|---|---|---|
| G01 | High impressions, low CTR | GSC MCP query + page; threshold section 3. Look at title, snippet, intent, SERP features before recommending a rewrite | C | opportunity | Pri* (titles/metas) / NtH |
| G02 | Queries at positions 4–15 | `gsc.money_queries_pos_4_20` (with `top_page`) | A | opportunity | Pri* (titles/H1) / NtH (intros) |
| G03 | Falling clicks | `gsc.now` vs `gsc.before`; `compare_search_periods`; check rankings, CTR, season, technical issues, demand (Keyword Planner trend) | A + C | issue | Pri if a key page / Notes |
| G04 | Falling impressions | as G03, plus indexing (`index_status`) and lost query coverage | A + C | issue | Pri / Notes |
| G05 | Impressions up, clicks flat | period comparison by query; snippet and intent alignment | C | opportunity | NtH |
| G06 | Clicks and impressions up | pages that grew: protect them (don't change their titles), copy what worked to similar pages | C | opportunity | Notes / "already working" |
| G07 | Brand vs non-brand | `gsc.brand_terms` (+ source), `now.brand_click_share_pct`; check the terms before quoting | A | context | Lead / Notes |
| G08 | Location searches (area, landmark, airport, beach) | `money_queries_pos_4_20`, GSC queries filtered by area terms; K06 | A + C | opportunity | NtH (area intros) / Pri* |
| G09 | Amenity searches for **verified** facilities | GSC queries with pool, parking, breakfast, kitchenette, Wi-Fi… only if the facility is confirmed | C + H | opportunity | NtH |
| G10 | Query lands on the wrong page | query + page: brand search on a blog post, dining search on the homepage | C | issue | Pri* / NtH |
| G11 | Several URLs for one query | query + page; real cannibalisation vs normal variation (threshold section 3) | C | issue | NtH |
| G12 | Device differences | GSC by device: CTR, position, landing pages | C | context | Notes / Web |
| G13 | Country / market gaps | GSC by country vs GA4 and Mirai guest countries | C | opportunity | NtH (language angle) |
| G14 | New relevant queries | queries in the current window absent from the previous one | C | opportunity | NtH |
| G15 | Lost queries | queries with sustained declines, traced to their pages | C | issue | Pri* / NtH |
| G16 | Brand SERP problems | brand queries landing on wrong URLs, junk pages (`gsc.booking_and_account_pages`), sister hotels (`gsc.sister_hotel_queries_dropped`) | A + C | issue | Pri |

### 4.4 Keyword Planner research and content gaps (K)

| ID | Check | How in this plugin | Mode | List |
|---|---|---|---|---|
| K01 | Keyword cluster → best existing page | `keyword_volumes` + query + page | C | feeds titles / intros |
| K02 | Commercial keywords with no suitable page | `keyword_ideas` vs the crawl's pages | C | NtH (new page, held) |
| K03 | Volume, location, language, trend recorded | `keyword_volumes` (12 months, competition, bids); CSV fallback `import_keyword_csv` | A | register |
| K04 | Reject irrelevant high-volume terms | relevance to the hotel's services, location, guests | C | — |
| K05 | Intent: transactional, commercial, informational, navigational, mixed | per cluster | C | register |
| K06 | Local modifiers: city, area, landmark, airport, beach, attraction | `keyword_ideas` seeds with area terms | C | NtH |
| K07 | Room / facility terms mapped to pages (verified offerings only) | room types from `booking_engine_snapshot` / Mirai room names | C + H | NtH |
| K08 | Long-tail queries for detailed content | `keyword_ideas`, GSC long queries | C | NtH |
| K09 | Seasonal demand vs organic and booking patterns | Keyword Planner monthly volumes vs GSC months vs `mirai_reservations` stay months | C | Lead timing |
| K10 | Check cannibalisation before proposing a new URL | O07 / G11 | C | — |
| K11 | Competitor coverage | **N** (no SERP or competitor source); only if the user supplies competitor pages | N | — |
| K12 | Opportunity score | section 1.3, using demand, relevance, current visibility, booking evidence, effort | C | register |

**Keyword opportunity record** (in the register, `finding_type: opportunity`): cluster; country, location, language; intent; average monthly searches (or "not available"); current ranking URL and GSC metrics; target URL or proposed page type; why; the suggested title / content change; competing internal URLs; impact, confidence, effort.

### 4.5 Internal linking and site architecture (L)

Link recommendations always name the **source URL, the destination URL and the anchor text**. "Improve internal linking" is never an item.

| ID | Check | How in this plugin | Mode | Sev | List |
|---|---|---|---|---|---|
| L01 | Orphan pages (indexable, no internal links): link, redirect or remove | `report.coverage.added_examples` (found only in sitemaps / WordPress), crawl inlink counts | A + C | med | NtH / Pri (H, junk) |
| L02 | Key commercial pages too deep | crawl depth in `internal_all.csv` for rooms / offers | A | med | NtH |
| L03 | Homepage links to rooms, offers, location, facilities | homepage links in the crawl | A + C | med | Pri* |
| L04 | Contextual links from articles to commercial pages | `report.blog_booking_links` (posts linking to neither rooms nor booking, by impressions) | A | med | NtH (blog → booking paragraph) |
| L05 | Generic anchors | anchors in `inlinks` files | A + C | low | NtH |
| L06 | Broken internal links, links through redirects | `report.links.broken_targets`, `redirected_targets`, `replace_pairs.csv` | A | high (sitewide) / med | Pri (E, F) / NtH (1) |
| L07 | Confusing link patterns (not every high count) | mega-menus, duplicated footer blocks seen in `inspect_pages` | C | low | Web / NtH |
| L08 | Logical links between rooms, facilities, offers, attractions | crawl link graph between page types | C | low | NtH |
| L09 | High-value pages receive relevant internal links | inlinks to the pages with the most impressions / bookings | A + C | med | NtH |
| L10 | Breadcrumbs: hierarchy and target URLs | visible breadcrumbs (`inspect_pages`) vs BreadcrumbList schema | C | low | NtH / `not_applicable` |
| L11 | Archive / tag / author / search / filter bloat | `report.archives_indexable`, `page_groups.thin_groups`, `account_pages` | A | med | Pri (G) |
| L12 | Link equity lost in moves or menu changes | old URLs in GSC / 404 export without redirects; `bing_report` linked pages that now 404 | A + C + H | high | Pri (I) |

### 4.6 Performance (P)

What this plugin can see: `response_time_ms` per URL in the crawl, response headers, page weight, and `inspect_pages` (rendered page, mobile screenshots, tags that fire). Every speed item goes on the **Web Team list**, and only with a diagnosis behind it (playbook ground rule 4).

| ID | Check | How in this plugin | Mode | List |
|---|---|---|---|---|
| P01 | Server response time, caching, redirects on the way to a page | `response_time_ms` in `internal_all.csv`, threshold section 3 | A | Web |
| P02 | Oversized images, wrong formats | crawl image sizes; `inspect_pages` | C | Web |
| P03 | Hero images / videos too heavy; mobile gets right-sized media | `inspect_pages` mobile | C | Web |
| P04 | JavaScript payload, third-party dependencies | `tags_rendered` (tag count), `inspect_pages` | C | Web |
| P05 | Cache headers, Brotli / gzip, CDN | response headers (`curl -I` on key pages) | C | Web |
| P06 | Lazy loading: hero image not lazy, below-fold images lazy | `inspect_pages` HTML (`loading="lazy"` on the first image) | C | Web |
| P07 | Mobile usability: viewport, overflow, tap targets, readability | `inspect_pages` mobile screenshots | C | Pri* (visible on key pages) / Web |
| P08 | Third-party scripts: chat, tracking, booking engine, maps | `tags_rendered`, `inspect_pages` | C | Web |
| P09 | Slow pages grouped by template | `response_time_ms` by page type | A | Web |
| P10 | Regression before / after releases, mobile and desktop separately | `monitor_site` history; V08 | A | Web |

### 4.7 Hotel-specific SEO (H)

**A. Property information consistency**

| ID | Check | How in this plugin | Mode | Sev | List |
|---|---|---|---|---|---|
| H01 | Name, address, phone, website, brand the same everywhere | `report.phones` (tel: links), `report.schema` blocks (name, street, locality, geo, conflicts), `custom_search` for old names | A + C | high | Pri (D) |
| H02 | Homepage and location pages describe the real area | `findings.hotel_city` (with source and warning), `report.other_city` | A | high | Pri (D) |
| H03 | Published amenities vs the source of truth | site text vs `hotel-facts.json` and `booking_engine_snapshot`; [CONFIRM] guard | A + H | high | Pri (D) / Hotel |
| H04 | Room types: accurate descriptions and working booking paths | `booking_engine_snapshot` (rooms, sizes, occupancy) vs room pages; booking links per room page | A | high | Pri |
| H05 | Room names, alt text, captions and photos match the room type | `inspect_pages`, viewing images | C | med | Pri (J) / NtH |
| H06 | Policies: cancellation, check-in/out, children, parking | engine cancellation terms vs site; check-in/out only from `hotel-facts.json` | A + H | high | Pri (D) / Hotel |
| H07 | Phone / email links, maps, directions work | tel: / mailto: links, `report.links` for map links | A | med | Pri* |
| H08 | Hotel schema: right type, identity, address, matches visible content | `report.schema` (blocks, flags, conflicts), `jsonld_invalid` issues | A | high | Pri (C) |
| H09 | Local visibility: map links, linked business profiles | schema `hasMap` / `sameAs`; Google Business Profile itself is **N** | A / N | med | Pri (C) |
| H10 | Brand and brand + location searches land on the right pages | `gsc` brand queries with `top_page`; G16 | A + C | high | Pri |

**B. Room pages and booking intent**

| ID | Check | How in this plugin | Mode | Sev | List |
|---|---|---|---|---|---|
| H11 | Room types without their own indexable page where demand justifies one | engine room list vs room pages; GSC / Keyword Planner demand per room type | C | med | NtH (held) |
| H12 | Room descriptions that don't say what differs | room page texts in `site_text.json` | C | med | NtH |
| H13 | Clear working booking path on room and offer pages | `pages[].links_booking`, `inspect_pages` mobile | A + C | high | Pri |
| H14 | Booking links: right hotel, dates, room, language | issues `booking_link_other_hotel`, `booking_link_outdated`, `booking_link_dead`; `booking_links.hotels` (own ID and its source, `pages_by_id`) | A | crit/high | Pri (E) |
| H15 | Offers and prices on the site vs the engine | `booking_engine_snapshot` comparison; `report.prices_in_text` | A | high | Pri (H) / NtH (5) |
| H16 | Unavailable rooms shown as bookable | engine "rooms not available" vs site | A | med | Hotel / NtH |
| H17 | Expired offers, stale pages and links | engine "offer pages with nothing on sale"; `out_of_season_wording` | A | high | Pri (H) |
| H18 | Booking journey on mobile: broken links, redirects, blocked steps | `inspect_pages` mobile on the booking link; `booking_engine_snapshot` | C | crit | Pri |

**C. Destination and attraction content**

| ID | Check | How in this plugin | Mode | Sev | List |
|---|---|---|---|---|---|
| H19 | Relevant attractions, landmarks, districts, beaches, transport hubs covered | site text vs G08 / K06 searches | C | med | NtH |
| H20 | Area landing pages only when demand and unique content justify them | K02 + C03 | C | med | NtH (held) |
| H21 | Distances and travel times: verified, never invented | `report.distance_conflicts`; [CONFIRM] guard (distances need `hotel-facts.json`) | A + H | high | NtH (5) / Hotel |
| H22 | Directions from airports and hubs | site text | C | low | NtH |
| H23 | Information for business, family, long-stay guests | site text vs Mirai segments (children in bookings, length of stay) | C | low | NtH |
| H24 | Near-identical attraction pages for keyword variants | `report.page_groups`, duplicate hints | A + C | med | Pri (G, merge) / NtH |

**D. Structured data and search appearance**

| ID | Check | How in this plugin | Mode | Sev | List |
|---|---|---|---|---|---|
| H25 | Lodging schema type matches the business; properties accurate | `report.schema` blocks; copy standards (playbook 4) | A | high | Pri (C) |
| H26 | Organization identity: logo, canonical site, one entity | `report.schema` (Organization duplicates, conflicts) | A | med | Pri (C) |
| H27 | Breadcrumb schema matches visible breadcrumbs | `inspect_pages` | C | low | NtH |
| H28 | Article schema on posts: author, headline, dates | `pages[].jsonld_types` on posts; `wordpress.post_authors` (company login as author) | A | low | NtH / Pri (D, author) |
| H29 | Offer / price markup matches current visible info | schema `priceRange` / offers vs engine; no priceRange unless confirmed | A + H | med | Pri (C) |
| H30 | Malformed JSON-LD, conflicting entities, bad URLs, markup ≠ content | issues `jsonld_invalid`; `report.schema.conflicts`; self-written reviews | A | high | Pri (C) |

Structured data must describe the page truthfully. It doesn't guarantee rich results or rankings; never promise either.

### 4.8 GA4 traffic quality and conversion (A)

Run the **measurement integrity checks (A09–A11 and the cross-domain checks) first.** If they fail, record a measurement integrity issue (Web Team) and don't base content recommendations on GA4 conversion data.

| ID | Check | How in this plugin | Mode | List |
|---|---|---|---|---|
| A01 | Organic landing pages by sessions, engagement, key events | GA4 MCP `run_report` (landingPage × sessionDefaultChannelGroup = Organic Search) | C | Notes / priorities |
| A02 | High organic traffic, low conversion | threshold section 3 | C | NtH (conversion content) |
| A03 | Low traffic, high conversion | threshold section 3 | C | Pri* / NtH (visibility) |
| A04 | Engagement changes | engagement rate, engaged sessions by period | C | Notes |
| A05 | Exits before the next step (not every exit is bad) | GA4 path / exits where available | C | Notes |
| A06 | Booking CTA events tracked (availability, room, booking button) | GA4 events list | C | Web |
| A07 | Funnel: landing → engine → search → room → checkout → reservation | GA4 `run_funnel_report` where the events exist; else `not_available` | C / N | Web / Notes |
| A08 | Mobile vs desktop conversion | GA4 by device | C | Notes / Web |
| A09 | Source / medium separated correctly | GA4 traffic acquisition | C | Web |
| A10 | Referral contamination, cross-domain breaks | sessions with source = booking engine / payment gateway / Wi-Fi portal | C | Web |
| A11 | Conversion tracking integrity: missing, doubled or implausible events; value and currency | `purchase` count and revenue vs Mirai bookings and revenue for the same dates; key events = purchase only | C | Web |
| A12 | Organic decline: visibility (GSC) vs measurement vs on-site behaviour | GA4 organic sessions vs GSC clicks, same dates | C | Notes |
| A13 | New vs returning (when samples allow) | GA4 | C | Notes |
| A14 | Informational pages that lead to commercial pages or bookings | GA4 path where available | C | Notes |

**GA4 / Mirai cross-domain checks** (booking finishes on the Mirai domain): sessions survive the jump (the engine doesn't show as a referral source); `purchase` fires once per booking; revenue and currency match Mirai. Any failure → **measurement integrity issue** on the Web Team list.

### 4.9 Mirai reservations and revenue (M)

Activate a check only when `mirai_reservations` exposes the fields. Bookings are analysed by hotel, room type, offer, stay month, booking window, channel and guest country. Never say a specific page produced a specific booking.

| ID | Check | How in this plugin | Mode | List |
|---|---|---|---|---|
| M01 | Booking conversion rate with a defined denominator | only via GA4 (purchases ÷ engine sessions); state the definition | C / N | Notes |
| M02 | Average booking value, by room type, offer and channel | `mirai_reservations` (ADR, revenue per room type and offer) | A | Notes |
| M03 | Room types that sell, and their pages | `mirai_reservations` revenue per room type | A | Pri* / NtH (room pages that sell get attention first) |
| M04 | Offer performance vs organic visibility | revenue per offer name vs offer pages' impressions; packages sold with no page | A + C | NtH (new page, held) |
| M05 | Abandonment (starts vs completed) | **N** in Mirai; GA4 `begin_checkout` vs `purchase` if tracked | N / C | Notes |
| M06 | Mobile completion gap | **N** in Mirai; GA4 by device | N / C | Notes |
| M07 | Market / language performance | Mirai guest country vs GSC / GA4 countries | A + C | Notes / NtH |
| M08 | Stay-date seasonality | Mirai by stay month (`by="checkin"`) vs search demand | A | Lead timing |
| M09 | Lead-time patterns vs content | Mirai booking window | A | NtH (e.g. same-day stays: "tonight" wording) |
| M10 | Cancellations and net revenue | Mirai cancellation rate; always quote it next to bookings | A | Notes / Lead |
| M11 | Organic vs other channels (consistent definitions) | Mirai channel field + GA4 channel revenue; state windows | A + C | Notes |
| M12 | Booking-engine failures blocking progress | `booking_engine_snapshot` errors, H18 | A + C | Pri |
| M13 | Prioritise pages by booking evidence, not search volume alone | inputs to the score (1.3) | C | ordering |

**Attribution words are not interchangeable:** organic sessions (GA4) · booking-engine sessions · booking starts · confirmed reservations · gross reservation value (before cancellations) · net value (after) · channel revenue (by Mirai channel or GA4 channel, window stated). Name which one every figure is.

### 4.10 Backlinks, authority and external visibility (B)

| ID | Check | How in this plugin | Mode | List |
|---|---|---|---|---|
| B01 | Outbound links returning errors | `report.links.broken_targets` (external) | A | NtH |
| B02 | Important pages lacking contextual internal links | L09 | A + C | NtH |
| B03 | Backlink loss to important pages | `bing_report` (Bing's linked pages and linking sites) when set up, compared with the last saved report; otherwise **N** | A / N | Pri (redirect lost targets) |
| B04 | Referring-domain quality (spam patterns, not every weak link) | `bing_report` linking sites; never "disavow everything" | C / N | Notes |
| B05 | Unlinked brand mentions | **N** | N | — |
| B06 | Competitor link opportunities | **N** | N | — |
| B07 | Search competitors for non-brand queries | **N** (no SERP source); the user's own live searches only if supplied | N | — |
| B08 | Link profile changes over time | saved `bing_report` snapshots | A / N | Notes |

Never invent referring domains, backlink counts, competitor rankings or link opportunities.

### 4.11 Content strategy (C)

| ID | Check | How in this plugin | Mode | List |
|---|---|---|---|---|
| C01 | Query clusters not covered | K02, G14 | C | NtH |
| C02 | Improve an existing URL first when it serves the intent | O07 / G11 / K01 | C | — |
| C03 | New page only when demand, intent and unique content justify it | K02 + hotel facts; held **[waiting for hotel details]** | C + H | NtH |
| C04 | Content brief: intent, cluster, audience, headings, facts needed, internal links | in the NtH item itself (copy-paste ready) | C | NtH |
| C05 | FAQs only for real guest questions | GSC question queries, hotel contact questions; answers [CONFIRM] until confirmed | C + H | NtH (7) |
| C06 | Seasonal updates from demand and booking patterns | K09, M08 | C | NtH |
| C07 | Outdated offers, dates, policies, rates, facilities, attractions | O14, H15, H17 | A | Pri* / NtH |
| C08 | Consolidate overlapping pages | O07, H24 → 301 and merge | C | Pri (G) / NtH |
| C09 | Content decay: find the reason before rewriting | G03 / G15 per page | C | NtH |
| C10 | Hotel claims vs the approved source | [CONFIRM] guard, `hotel-facts.json` | A | all lists |
| C11 | Links between informational and commercial pages | L04 | A | NtH |
| C12 | Track visibility, traffic, bookings after publishing | V09 / V10 | C | register |

No near-identical city or attraction pages just because Keyword Planner lists many similar terms: each new page needs its own purpose and enough unique, accurate content.

### 4.12 Change verification and regression detection (V)

**Two statuses per item, never merged:** the **implementation status** (is the change live? provable the same day from HTML) and the **outcome status** (did search or bookings move? only after Google has re-crawled and a fair window has passed, usually 4–8 weeks, and never proven causal).

| ID | Check | How in this plugin | Mode |
|---|---|---|---|
| V01 | Baseline: title, meta, headings, canonical, indexability, schema per page | the crawl's `findings.json` (keep it; it's `baseline_crawl_dir` for the re-check) | A |
| V02 | Change history: proposed change, URL, date, status | list JSON + findings register statuses | A |
| V03 | Post-change crawl verifies the intended change | `recheck_list` (one check per URL / row) | A |
| V04 | Regressions: broken links, invalid schema, wrong canonicals, noindex | re-crawl `audit_site` + `recheck_list` `changes_not_on_any_item` | A |
| V05 | Sitemap after URL changes | `report.sitemaps` on the re-crawl, Search Console sitemaps | A |
| V06 | Redirect destinations and final URLs | `redirect` checks, `test_redirects` | A |
| V07 | Indexing follow-up after re-crawl time | `index_status` 2–4 weeks later | A |
| V08 | Performance before / after (comparable data) | `monitor_site`, P01 | A |
| V09 | Clicks, impressions, CTR, position over fair windows | Search Console, same-length windows, season noted | C |
| V10 | Bookings / revenue for the hotel over the same windows (season, price and parity noted) | Mirai + GA4 | C |
| V11 | Rollback when a change caused a verified regression | re-check finish message, at the very top | C |
| V12 | Close only when implementation **and** verification are met | register status rules (section 5) | A |

---

## 5. The findings register and coverage table (written every run)

**Files:** `<domain>/findings-register-<date>.json` (format: [../templates/findings-register.schema.json](../templates/findings-register.schema.json)) and a **coverage table** in `run-notes-<date>.md`.

**Coverage table:** one line per check ID with its result (`finding` / `no_issue` / `insufficient_data` / `not_available` / `not_applicable`) and a few words on why. Group by section; it's fine to collapse runs of identical results ("B05–B07: not_available — no mention, competitor or search-result data"). Every ID in section 4 appears.

**Each finding record has:**
- `check_id` — the rule that produced it (one of the IDs above; a finding without one doesn't exist).
- `category`, `finding_type` (`issue` / `opportunity` / `measurement_integrity`), `title`.
- `affected_urls` (or a URL group with its pattern and count for template findings).
- `evidence[]` — `source` (tool and field, e.g. `audit_site:report.canonical_targets`), `observed_value`, `expected_value`.
- `verification_status` — `verified` (seen in the named source, and on the live site where the check needs it), `probable`, `unverified`, `not_applicable`.
- `severity` and `priority` (P0–P3), `score` with its four inputs.
- `impact` — `type`, `business_relevance`, `confidence` (0–1), and the observed condition kept apart from the inferred impact.
- `recommended_action` — `action_type`, `target_url`, exact instructions (or the list section that carries the copy-paste text), `requires_approval` (true for redirects, canonicals, robots, bulk noindex, bulk content).
- `success_criteria[]` — written so the list's `checks` can test them.
- `list` and `list_section` — where it went (e.g. "Priority, C"), or `not_listed` with a reason.
- `status` — `open` → `approved` (on a list MetaHotels sent) → `in_progress` → `implemented` (re-check Done) → `verified` (outcome window passed, outcome recorded) / `monitoring`; or `rejected` (with reason).
- `baseline_captured_at`, `implemented_at`, `verified_at`.

**Rules:**
- Only `verified` findings go on a list. `probable` ones go in the run notes as questions; `unverified` ones are checked or dropped.
- "No issue found" and "insufficient data" are proper answers. Don't make up an item to fill a section.
- `presend_check`'s `not_on_any_list` must be empty, or every remaining URL has a `not_listed` reason in the register.
- On a re-check, update the same records (don't create new ones): `implemented` when the item's checks pass, back to `open` when they fail, new records only for new problems.

---

## 6. Order of work in a full run

1. **Data collection** (SKILL.md steps 2–4b): crawl, Search Console, Keyword Planner, GA4, parity, Mirai, rendered pages, audit, booking engine, indexing, Bing.
2. **Normalise and validate:** one hotel only (`hotel_path`), right city, right GA4 property (hostname), Mirai ID covered by the login, date windows aligned (90 vs 90; same months last year), times in the hotel's zone. Run the measurement integrity checks (A09–A11, cross-domain).
3. **Deterministic checks:** walk sections 4.1–4.12 in order and give each ID its result.
4. **Interpretation:** root cause, business impact, the fix, confidence. Group template defects.
5. **Prioritise:** sections 1.1–1.3, then place each finding on its list.
6. **Write the lists** with one check per URL and row (SKILL.md step 6), pre-send, render.
7. **Record:** register + coverage table; finish message names the checks that couldn't run because a source is missing.

---

## 7. What the finish message adds

- **Not checked (no data):** the check groups that came out `not_available`, and what would unlock them (e.g. "backlinks: run hotel-seo-bing-login").
- **Measurement integrity:** any A09–A11 / cross-domain failure in one line, so nobody reads the GA4 numbers as reliable.

---

## 8. Phases (what is automated today)

- **Phase 1, automated now:** crawlability, indexability, canonicals, broken URLs, metadata, sitemaps, schema, booking links (T, O01–O03, O10–O11, O14, H01–H08, H13–H17, H25–H30, L06, L11).
- **Phase 2, Claude with tools:** Search Console opportunities, keyword-to-page mapping, content gaps, internal links (G, K, L, C).
- **Phase 3, Claude with tools:** GA4 funnel and integrity, Mirai revenue by room / offer / season / channel (A, M).
- **Phase 4, automated now:** change verification, regressions, monitoring (V via `recheck_list`, `baseline_crawl_dir`, `monitor_site`, `index_status`).

## 9. Changing the registry

Add or change a check only here: give it the next free ID in its section, fill every column, bump the registry version at the top, add the lesson to the playbook's section 10 if a hotel taught it, and bump the plugin version so the team gets it.
