# Swipe file: learn across every hotel

The live file is `6_Campaigns/Ad_Swipe_File.md` (data, outside the skill so it can grow). This page is how to use it.

## Why
Hormozi finds "home runs" (angles that win in nearly every market) by testing across many gyms, then hands them to every client (note 24, ch 3 and 22). MetaHotels runs ads for many hotels, so the same compounding is available. A new campaign starts from proven angles instead of a blank page.

## When to add rows
- **Post-mortem trigger:** an ad or campaign passes ~1,000 clicks, or ends, whichever comes first. Below 1,000 clicks the row is logged as `inconclusive`, never as a win or a loss.
- Add **losers too**. Knowing what fails is half the value.
- Data comes from the live source on the day (Google Ads MCP, the Meta export, GA4, Mirai) with the snapshot date. Never from memory or an old report.

## Columns
`Date | Hotel | Platform | Campaign/ad ID | Angle tag | Hook / headline (verbatim) | Big Idea | Audience | Spend | Clicks | CTR | Conv | Value/conv | Bookings (Mirai) | Verdict | Sample OK? | Source + snapshot | Notes`

- **Angle tag** uses the Scrambler banks: `duration`, `benefit`, `status`, `curiosity`, `against-fear`, `challenge`, `event`, `family`, `couples`, `value`, `proof`, `local`, plus `brand` (the hotel name or "official site") and `cta` (a generic action line). `value` with no number is noted as "vague" in Notes, because the 24 Oct 2026 backfill showed numbered and vague value claims behave in opposite ways.
- **Value/conv** is computed, and checked for the uniform-value and cross-contamination faults (CLAUDE.md rule 4).
- **Verdict:** `winner` (beat its control by 20%+ on the chosen metric, with the sample gate passed), `loser`, or `inconclusive`.

## Controls
Each hotel × platform has one **control**: the best-performing ad or asset set so far, marked `control` in Notes. New work is a challenger against it. It becomes the new control only when it beats the control by 20%+ and passes the sample gate. Don't retire a control because *we're* bored of it (Halbert: the market sees it for the first time).

## Reading it before a new campaign (workflow step 2)
1. Filter by the same hotel, then by the same segment or angle at other hotels.
2. **Home run** = an angle tag with winners at ≥2 of 3 hotels where it was tried, each with a passed sample gate. Start the new test from it.
3. **Retire** an angle after losers at 3+ hotels, unless the brief names why this hotel differs.
4. Name the rows used in brief part B. "From the swipe file" with no row cited doesn't count.

## Hygiene
- Hotel names in full (no prefixes).
- Facts in hooks that came from the claim register keep their register reference.
- Review the file monthly: merge duplicates, update home runs.
