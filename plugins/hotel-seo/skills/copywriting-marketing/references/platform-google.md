# Google Ads: platform playbook

Limits below are from knowledge as of mid-2026 (**inherited**, not verified against Google's help centre this session). Check them at build time; Google changes them. `ads-publisher`'s `check_ad` / `check_campaign` validate the payload before anything is created.

**Asset counts** (how many headlines, sitelinks, images): `google-ads-build-completeness` governs (display-cap rule; 1.5–2× the cap below ~50 conversions/month). This file covers what goes *in* them.

## Search: responsive search ads
- Headlines ≤30 characters (up to 15); descriptions ≤90 (up to 4); display paths ≤15 each.
- **Write headlines as roles, not 15 versions of one line.** Planned spread:
  - 3–4 that carry the **Big Idea / benefit** in the searcher's words (data brief row 1);
  - 2–3 **proof** (review score with a date, a verbatim guest phrase, a fact from the hotel);
  - 2 **offer** (the package, what's included; prices only if bookable and parity-safe);
  - 2 **reason to book direct** (only what's true: member rate, flexible cancellation, perks);
  - 1–2 **call to action that carries the offer or a specific** ("Book Direct, Save 10%", not "Book Your Stay"); 1–2 brand, plus "Official Hotel Website" where it's true.
  - **Evidence (24 Oct 2026 backfill, directional):**
    - numbered offers ("30% Off Direct Booking") and brand/official lines beat the average;
    - generic CTAs ("Book Your Stay", "Your Dubai Stay Awaits") and vague value claims ("Best Rates Guaranteed", "Exclusive Online Rates") got 0–1 conversions on 1,000–4,500 clicks;
    - perks (breakfast, shuttle) did worse as headlines than inside descriptions next to the % off.
    - See `6_Campaigns/Ad_Swipe_File.md`.
  - **Arabic:** where the hotel's brand queries include Arabic (Metropolitan: about 700 Arabic brand clicks), test Arabic assets.
- **Pinning** lowers the rotating pool (see build-completeness). Pin only for policy or meaning (brand in H1, for example).
- Descriptions: one benefit + proof, one offer + CTA. Each must stand alone (any two can show together).
- **Message match:** the ad's promise appears above the fold on the final URL, and the booking engine shows the same offer. Checked live, not assumed.
- **Ad strength** is a vendor metric. Don't write to raise it (CLAUDE.md rule 3 spirit); write to the reader.

## Hotel-specific
- **Brand campaign vs OTAs:** OTAs often bid on the hotel's name. Check the search terms report and auction insights. Whether the hotel's OTA contract restricts the OTA, or the hotel, on brand bidding is **contractual**: read the clause or say it's unread.
- **Non-brand intents** come from the data brief (e.g. "family hotel Sharjah with pool"), one ad group per intent, the headline in the searcher's own words.
- **Dates and events:** event and holiday ad groups (Eid, National Day, F1) go live with the real dates and end on time.
- **Price assets and promotion assets:** real, bookable, dated.

## Performance Max (built by Saif from the brief; ads-publisher builds Search only)
- Headlines ≤30 (3–15); long headlines ≤90 (1–5); descriptions ≤90 (2–5, at least one ≤60); business name ≤25.
- Images: landscape 1.91:1, square 1:1, portrait 4:5; logo 1:1 (and 4:1 landscape).
- **Supply your own video.** Without one, Google auto-generates from the images, usually poorly.
- One asset group per audience or theme from the data brief, not one for everything. Audience signals come from Mirai segments and the customer list where consent allows.
- PMax reporting is thin. Judge it on bookings and stayed revenue (Mirai), not platform conversions alone.

## Extensions copy
- Sitelinks ≤25 characters, descriptions ≤35 each; callouts ≤25; structured snippet values ≤25.
- Each one adds a distinct reason; no repeats of the headlines (build-completeness: the cleanest cut is duplication).

## Policy (category: platform-policy)
- No unsupported superlatives ("best hotel in Dubai"), and no "best rate guaranteed" unless today's parity check proves it (it also lost in the backfill).
- No trademarked terms of others in the ad text.
- Prices and offers shown must be on the landing page.
- Keep capitalisation and punctuation normal (no "FREE!!!").
