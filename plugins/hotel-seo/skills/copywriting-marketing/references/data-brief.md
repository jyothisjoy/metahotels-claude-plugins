# Data brief (part A of every campaign brief)

Agora: "Proclamations are found in research, not written." This file turns that into a fixed data pull. Every number carries **source + snapshot date**. Every line is labelled **verified this session**, **inherited** (from a stored file, with its date) or **inference** (CLAUDE.md).

## Start here: where the data lives
- `6_Campaigns/Connector_Coverage_Map.md` lists each hotel's Ads account, Search Console property, GA4 property and Mirai ID. Look the IDs up here first, then pull live.
- `6_Campaigns/ads_history/Tracking_Quality_<date>.md` says which campaigns' conversions can be trusted. Check the hotel's row before row 7. A contaminated campaign's step one is the goal fix, not new copy.
- `6_Campaigns/Ad_Swipe_File.md` holds scored angles across hotels, plus the home runs, retired angles and watch list.
- `6_Campaigns/ads_history/Learnings_<date>.md` collects the cross-hotel patterns. It's a snapshot: re-pull the hotel's own campaigns before relying on it.

## The pull: run what's available, name what isn't

| # | Data | Tool | Pull | What it gives the copy |
|---|---|---|---|---|
| 1 | Search demand in the guest's words | Search Console (`hotel-seo-gsc`: `get_search_by_page_query`, `get_advanced_search_analytics`) | Top 50 queries, 90 days, with impressions, CTR, position; filter non-brand | Headline language; angles with demand that the site misses (high impressions, low CTR) |
| 2 | Keyword volume and ideas | `hotel-seo-tools`: `keyword_volumes`, `keyword_ideas` | Seed from #1 and from the Big Idea candidates | Size of each angle; long-tail ad groups |
| 3 | Site behaviour | GA4 (`hotel-seo-ga4`: `run_report`, `run_funnel_report`) | Landing pages × source/medium × conversions, 90 days; booking-funnel drop-off | Which page an ad should land on; where the funnel leaks (fix before spending) |
| 4 | Who actually books | Mirai (`hotel-seo-tools`: `mirai_reservations`) | Bookings by country, lead time, length of stay, room type, rate plan, device; 12 months | The reader (who), the timing (when), the offer (what they buy) |
| 5 | Price truth | `rate_parity` + the daily parity file | Today's direct vs OTA rate | Whether "best rate direct" or a price claim is true **today** |
| 6 | Booking path | `booking_engine_snapshot` | The engine page an ad lands on | Message match; friction |
| 7 | Google Ads history | `google-ads` MCP (`search_search`, GAQL) | Search terms report, ad and asset performance, impression share, budget use (avg daily spend ÷ budget) | Winning hooks; negatives; whether a campaign is capped (CLAUDE.md rule 3) |
| 8 | Guest voice | Google reviews (`GbpReviews_MetaHotels.js` → hub sheet), plus Booking and TripAdvisor read in the browser | Last 50 reviews: repeated praise and complaints, verbatim | Proof lines, objections to answer, damaging admissions |
| 9 | Meta results | See "Meta data" below | Ad-level results, 90 days | Hooks and formats that work on Meta |
| 10 | Competitor ads | Meta Ad Library (public); Google Ads Transparency Centre (public) | Ads from 3–5 direct competitors and the main OTAs | Market sophistication: which claims are tired |
| 12 | **Differentiator inventory (mandatory)** | The hotel's own site: homepage, FAQ, policies, feature pages (pets, kids, long stay, dining, location), read in full; plus the ad history (#9) | 5–10 things a nearby competitor can't truthfully say (e.g. a pet-friendly floor; 10 minutes to DXB; washer-dryer suites; free cancellation until 2pm on arrival day), each with its page and date. Cross with #8 and #9: which one already pulled response? | **Why this hotel over the next one.** No Big Idea without it |
| 11 | SEO overview | The upgraded `hotel-seo` skill, once released | Its whole-site summary | Replace or extend rows 1–3 when it's available |

## Gates the data must pass before it informs a decision
- **Freshness:** the data's own timestamp covers the period (CLAUDE.md feed-freshness). Stale → say so; don't reason from it.
- **Sample size:** no verdict on an ad, angle or audience below ~1,000 clicks (rule 2). Below that, call it "a lead to test", not a finding.
- **Metric sanity:** compute value-per-conversion on every line. A uniform value (e.g. exactly 1.00) or the same value across different hotels means a broken value parameter or cross-contamination; it can't reach a decision (rule 4).
- **Timezones:** API timestamps are UTC; add 4 hours for Dubai time.
- **Hotel names:** full-string matching only across sources (no prefix joins).

## Output: part A of the brief (one page)
1. **Who books** (from #4): the top 2–3 segments with their share of bookings.
2. **What they search** (from #1–2): the top non-brand intents with volume.
3. **What they say** (from #8): 5 verbatim phrases, each with source and date.
4. **Where it leaks** (from #3, #6): the single biggest funnel problem.
5. **What's already been tried** (from #7, #9): winners and losers with sample size.
6. **Market sophistication** (from #10): claims competitors already make.
7. **Price truth today** (from #5).
8. **What only this hotel has** (from #12): the differentiator list, best first, with any past response it earned.
9. **Insight → angle:** 3 candidate angles, each citing the rows it comes from. **At least two are built on a differentiator from item 8.** An angle any hotel could run ("a night off", "luxury stay", "10% off") can be a control, never the main bet.
10. **Gaps:** every source that couldn't be pulled, and why.

## Meta data
**First choice: the `meta-ads` MCP** (Meta's official server, connected 25 Oct 2026 with read-only OAuth). Ad account IDs are in `6_Campaigns/Connector_Coverage_Map.md`.
- Campaigns, ad sets and ads: `ads_get_ad_entities`. Copy and hooks: `ads_get_creatives`, `ads_get_ad_preview`.
- Results: the `ads_insights_*` tools (ad level, 90 days for row 9). Freshness is read from the date range in the result, not assumed.
- Tracking (Gate 5 #14 for Meta): `ads_get_datasets`, `ads_get_dataset_quality`, `ads_get_customconversions`. A pixel or dataset that doesn't record this hotel's real bookings means the goal fix comes first, as on Google.
- Competitor creatives (row 10): `ads_library_search`.
- Meta's own benchmark and opportunity tools (`ads_insights_industry_benchmark`, `ads_insights_performance_vs_peers`, `ads_get_opportunity_score`) are vendor figures. Label them as Meta's; they are never targets, like the optimisation score on Google.
- **Every Meta write tool is denied** in `.claude/settings.json` (create, update, activate, delete, pixel, boost). Meta campaigns are built by Saif from the brief. Opening any write tool needs Saif's decision and a brief-gate hook first.

Fallbacks, if `meta-ads` is disconnected:
1. **Supermetrics** Facebook Ads source (`data_source_discovery(filter="facebook")`); it was `NOT_AUTHENTICATED` on 24 Oct 2026.
2. **Ads Manager CSV export** to `6_Campaigns/meta_exports/<Hotel>_<DDMon>.csv`, ad level, last 90 days: ad name, primary text, headline, format, placement; impressions, reach, frequency, amount spent; link clicks, CTR (link), CPC (link), CPM; landing page views, purchases and purchase value (if tracked); 3-second video plays and ThruPlays. Read the `Reporting starts` / `Reporting ends` columns for freshness, not the file date.
3. **GA4 as the cross-check** in every case: Meta traffic with UTMs shows as source `facebook` / `instagram`, and bookings come from Mirai. This is the only view comparable to Google Ads, and it needs UTMs on every Meta ad (a gate in `platform-meta.md`).
