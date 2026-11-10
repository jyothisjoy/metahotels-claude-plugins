# Campaign workflow (any ad or campaign, any platform)

Use this for every ad, ad set, campaign or campaign change: Google Search, PMax, Meta and Instagram, YouTube, display, or a new landing page behind an ad. Copy-only requests (one email, one post) use the main SKILL.md steps without this wrapper.

The order is fixed. A step that's skipped is named in the brief with the reason.

| # | Step | Output | Reference |
|---|---|---|---|
| 1 | **Data brief.** Pull the hotel's live data, with the source and snapshot date on every number. Check the campaign's tracking first (Gate 5 #14). | `6_Campaigns/briefs/Brief_<Hotel>_<Platform>_<DDMon>.md`, part A | `data-brief.md` |
| 2 | **Swipe-file check.** What has already won or lost for this hotel and across hotels (angle, hook, platform)? | Brief part B: three angles to reuse or avoid, each with a cited row | `swipe-file-method.md`, `6_Campaigns/Ad_Swipe_File.md` |
| 3 | **Strategy.** Reader, awareness level, sophistication, one action; Big Idea and the four-legged copy platform; the Big Idea is built on a differentiator from data-brief row 12 ("why this hotel over the next one?") (SKILL.md steps 1 and 3). The Big Idea must cite the data insight it rests on. **Funnel map:** which awareness levels this campaign serves, and whether it *creates* demand (Meta, YouTube, PMax prospecting, owned-list plays) or *captures* it (brand and non-brand Search). Brand Search alone is capture. | Brief part C | `big-idea-platform.md`, `owned-demand.md` |
| 4 | **Angles and variants.** Generate from the Scrambler banks. Start from the swipe file's home runs and avoid retired angles. Name the **control** (the current best ad or asset set) and run 1–2 **challengers** that differ in one variable. If 4 challengers can't beat the control, move the test to the next constraint (landing page, offer, audience). | Brief part D: the test plan with the sample gate | `channel-playbooks.md` |
| 5 | **Platform build.** Write to the platform's real limits and formats. Asset counts follow `google-ads-build-completeness`. | Draft assets | `platform-google.md`, `platform-meta.md` |
| 6 | **Scorecard.** Gate 5 on every ad, plus gates 0–4 on the copy. Below the bar → rewrite, don't present. | Brief part E: scorecard table; the last line `Scorecard: PASS` or `FAIL` | `editing-review-gates.md` |
| 7 | **Publish paused.** Google Search via `ads-publisher` (`check_*` → `create_*`, always PAUSED; Saif enables). PMax and Meta are built by Saif from the brief. **Never set a budget: ask Saif.** | Campaign or ad IDs added to the brief | — |
| 8 | **Measure and log.** At ~1,000 clicks or at campaign end: post-mortem, then add rows to the swipe file (winners *and* losers). Judge on bookings, with stayed revenue from Mirai where the source can be attributed (UTMs). Platform conversions count only when the tracking row is clean. | Swipe-file rows | `swipe-file-method.md` |

## The brief file
- One file per campaign build. The header carries `Hotel:`, `Platform:`, `customer_id:` (Google Ads, digits only) and `Date:` (Dubai time, checked with the CLAUDE.md command).
- The last line is `Scorecard: PASS` only when every hard gate passed. A hook blocks `ads-publisher` create calls unless a brief with that customer ID and `Scorecard: PASS` exists and is under 14 days old.
- Writing `PASS` without running the gates defeats the system. If a gate can't be run (data missing), the line is `FAIL` and the missing item is named.

## Funding check before any threshold
Who funds the spend? MetaHotels-funded → 10:1 ROAS is break-even (CLAUDE.md rule 1). Hotel-funded → the bar doesn't apply; ask the hotel's target. Size any scale-up as monthly outflow and peak float (rule 6).
