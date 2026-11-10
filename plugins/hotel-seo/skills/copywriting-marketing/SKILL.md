---
name: copywriting-marketing
description: Direct-response copywriting and marketing for MetaHotels, built from the Agora Black Book (Big Idea, Rule of One, six lead types, Four-Legged Stool, Peer and CUB reviews) and Hormozi (value equation, offers, hooks, money models, lead magnets, Fast Cash). Use when writing or reviewing marketing copy for a client hotel (ads, landing pages, booking-engine and website copy, email and WhatsApp campaigns, packages and offers, social posts) or the copy for MetaHotels' own B2B pieces (lead magnets, LinkedIn posts, case studies, cold-email sequences, event invites), or when designing a campaign, offer, internal play to a hotel's past guests or residents, guest-retention flow or test plan. Also use for ANY ad or campaign work on any platform, even when the request doesn't mention copy — Google Ads (Search, RSA, Performance Max, YouTube, display), Meta / Facebook / Instagram ads, campaign structure, ad testing, creative briefs, landing pages behind ads, or reviewing why an ad underperforms. Runs a data brief (Search Console, GA4, Mirai, Google Ads, Meta, reviews, parity) before writing. A hotel's paid-media plan of action for a season or quarter, a shoot plan, or reading a test to scale, cut or re-shoot belongs to ads-execution, and this skill writes the copy for each campaign in that plan.
---

# Copywriting and marketing (internal)

> Shipped with the hotel-seo plugin (from the Nov 2026 handoff). Files it names (`6_Campaigns/`, `Sales_Claim_Register.md`, `CLAUDE.md`) live in the MetaHotels workspace: when they aren't in the folder Claude was started in, say which one is missing and ask; never invent its contents. **SEO page copy** (titles, metas, intros, FAQs, room and offer pages, blog posts) follows hotel-seo's `references/content-writing.md`; use this skill's brief, honesty gates and QA gates alongside it for Build-Plan-style page copy and thin-page rewrites.

Copy here is judged by response, not elegance. "It measures likely response, not quality" (Agora Peer Review). Every piece goes through one process: brief, platform, write, then QA gates. The gates are the point. Rules alone get skipped in the flow of writing.

## Routing

| Need | Use |
|---|---|
| Proposal or intro email to a prospect hotel | `outbound-proposal` (this skill can draft the angle; its format and pre-flight win) |
| WhatsApp, nudge or call script to a prospect | `sales-word-tracks` |
| Deck or one-pager | `sales-collateral` |
| Any ad or campaign (Google, Meta, any platform) | **this skill first**: `references/campaign-workflow.md`. Asset counts then follow `google-ads-build-completeness` |
| A hotel's paid-media plan (channels, shoot, test calendar, spend proposal) or a test read-out (scale, cut, re-shoot) | `ads-execution`; each campaign in its plan then comes back here for the brief and copy |
| SEO priority lists, site audits | `hotel-seo` |
| Selling in a meeting: objections, negotiation | `sales-mastery` |
| MetaHotels' own lead gen strategy, pipeline, account management | `sales-systems` (this skill writes the copy for its pieces) |
| Campaigns to a hotel's own guests, members and residents; guest retention | **this skill**: `references/owned-demand.md` |
| Everything else marketing or copy | **this skill** |

**Never set an ads budget.** Ask Saif (memory rule: Gevora = AED 50/day). Paid-media thresholds follow CLAUDE.md: 10:1 ROAS is break-even on MetaHotels-funded accounts, and there is no verdict below about 1,000 clicks.

## Campaign mode: any ad or campaign, any platform
Run `references/campaign-workflow.md` end to end: data brief → swipe file → strategy → angles → platform build → scorecard → publish paused → swipe-file log. The brief lives in `6_Campaigns/briefs/`. A folder hook blocks `ads-publisher` create calls until a brief for that `customer_id` ends `Scorecard: PASS`. Steps 1–5 below run inside step 3–6 of the workflow.

## Step 1: Brief (write it at the top of every draft)
- **Who** is reading? One person, described concretely (a Saudi family planning an Eid staycation; a GM of a 120-key independent in Deira).
- **Awareness level:** most, product, solution, problem or unaware (`references/big-idea-platform.md`).
- **Market sophistication:** how many similar claims has this reader already seen? A tired market needs a new mechanism or angle, not a bigger claim.
- **The one action** wanted (Rule of One).
- **Channel and constraints:** character limits, platform policy, rate parity and OTA contract limits on public prices.
- **Funding and goal** (paid media): who funds it and what break-even is (CLAUDE.md).

## Step 2: Research before writing (Halbert #1, #8)
- **Ads and campaigns: the data pull in `references/data-brief.md` is this step.** Search Console, keywords, GA4, Mirai, parity, Google Ads history, reviews, Meta export, competitor ads. Every number with its source and date.
- Review what already worked: the hotel's past campaigns and their numbers, Saif's sent mail, tracker reply patterns. Then review what competitors run.
- Use the customer's own words: reviews on Google, Booking and TripAdvisor; GM interview phrases; questions guests ask the front desk. "Proclamations are found in research, not written."
- Facts about MetaHotels come only from `Sales_Claim_Register.md`. Facts about a client hotel come from the hotel itself (website, rate screen, contract) and are dated.

## Step 3: Copy platform (3–4 lines before any prose)
1. **Big Idea in one sentence.** It passes "important, exciting, beneficial, leads to an inevitable conclusion", **and it answers "why this hotel over the next one?"** with something from the differentiator inventory (`references/data-brief.md` row 12). A category benefit (a night off, luxury, relaxation, a generic discount) is not a Big Idea.
2. **Big Promise:** the benefit, then the deeper benefit, then how the reader will feel or be seen.
3. **Claims**, each with **proof**.
4. **Credibility:** who says so, and why believe them.

Together these are the Four-Legged Stool. If any leg is missing, stop and fix the platform. → `references/big-idea-platform.md`

## Step 4: Write
- **Headline / hook / subject:** generate 10+. Score each on the 4 U's and pick by awareness level. → `references/headlines-leads-hooks.md`
- **Lead:** choose one of the six lead types by awareness level. The lead is 80% of the work.
- **Body:** prove every claim (Power of Three), go feature → benefit → deeper benefit, give a reason why, and be specific. → `references/body-proof-close.md`
- **Offer:** value equation, Sharpe's 10 tests, a M-A-G-I-C name, real urgency only. → `references/offers-money-models.md`
- **Close:** restate the offer so it gains allure, add risk reversal (only what's real), one simple action, and a P.S.
- **Visual design** (image ads, social creatives, any rendered asset): `references/design-standard.md`. Render with a saved script and look at it before showing.
- **Channel mechanics:** email sequences, booking-recapture, pre-arrival bounceback, ads (hook/meat/CTA, Scrambler banks, the 12 commandments), social, lead magnets. → `references/channel-playbooks.md`
- **Owned demand:** internal plays to past guests and residents, the guest life cycle, retention. → `references/owned-demand.md`
- **Going deeper** (the full distilled notes, the raw sources, known gaps): `references/source-map.md`.

## Step 5: QA gates. Run all of them and show the results with the draft
1. **One-sentence idea + FK score** at the top of the draft (MMF's rule). Compute FK with `python -I "${CLAUDE_SKILL_DIR}/scripts/fk_grade.py" <file>`. Target under 7.5. Arabic copy is exempt; check it by reading aloud.
2. **Rule of One:** one idea, one emotion, one story, one action. Count the CTAs; there must be exactly one.
3. **Peer score (self-run, honest):** rate the headline and lead 1.0–4.0 *as the named reader*. Below 3.0, rewrite. Below 2.8, start a new lead. Give replacement lines, not commentary.
4. **CUB-DF:** mark anything Confusing, Unbelievable, Boring, Distracting, or that fails to Fulfil the lead's promise. Fix by cutting first.
5. **The 12 questions** (long-form only): why now, credentials, likeable, proof, emotion sustained, deeper benefits, false close, irresistible offer, immediate action, offer restated, guarantee, simple order step. → `references/editing-review-gates.md`
6. **Honesty gates** (below).
7. **Ads only: Gate 5 scorecard** (`references/editing-review-gates.md`). Every ad is scored; any hard-gate fail → rewrite before showing. The brief's last line records `Scorecard: PASS` or `FAIL`.

## Honesty gates (non-negotiable)
- **Scarcity and urgency must be real**: actual room inventory, a real booking window, a real event date, a real capacity cap. No "only 2 left" unless it's live inventory. No "someone backed out". No fake countdowns.
- **Prices and discounts** must match the live rate and respect the hotel's **rate parity and OTA contracts**. Member or loyalty rates and packages are the usual compliant routes, but check them per hotel; this is contractual. "From AED X" must be bookable.
- **No invented testimonials, reviews, ratings, statistics or awards.** Quote reviews verbatim with source and date. Use "rated 4.6 on Google" only with a dated check.
- **MetaHotels results**: register rows only, and only in the format the register allows (no revenue figures in spoken or WhatsApp copy).
- **Platform policy**: ad copy follows Google and Meta rules (no unverifiable superlatives such as "#1" or "best" without support; restricted claims). Category: platform-policy.
- **Superlatives** ("best", "only", "first", "largest") need a source. Otherwise cut them. Ogilvy: superlatives make readers discount everything else.
- **No incentivised or required reviews** on Google, TripAdvisor or Booking (category: platform-policy).
- **No inflated "was" prices** or reference prices that never existed (category: regulatory, consumer protection).
- **No silencing guests** (turning comments off, deleting fair complaints) in hotel channels (category: reputational).
- Sources with aggressive tactics (Fast Cash "backed out" emails, Pavlish health claims, Halbert's "bribe", Gym Launch fake anchors) are used for *structure*, never for claim level.

## Output
- Every draft starts with the brief, the copy platform, the one-sentence idea and the FK score. Then the copy. Then the gate results: Peer score, CUB fixes made, 12 questions where relevant.
- Give 2–3 variants that differ in **one** variable (headline or lead type or offer), with a test plan. The test plan states the sample needed before a verdict (CLAUDE.md: no verdict below about 1,000 clicks; for email, a meaningful send size). Change one thing at a time.
- Copy for a client hotel: `Copy_<Hotel>_<Channel>_<DDMon>.md` (or `.html` if it's paste-ready).
- MetaHotels B2B pieces: `Marketing_<Topic>_<DDMon>.md`.

## Pre-flight check: run before showing the draft
- [ ] The brief names one reader, an awareness level and one action.
- [ ] The copy platform has all four legs, and every claim has its proof beside it.
- [ ] The FK script was run, and the score is shown (under 7.5, or the reason it can't be).
- [ ] Exactly one CTA. One idea.
- [ ] Peer score ≥ 3.0 for the headline and lead (self-rated as the reader), with the score shown.
- [ ] CUB-DF pass done; anything unbelievable has been cut or proven.
- [ ] Every scarcity or urgency line is real and sourced (inventory, date, cap).
- [ ] Prices checked against the live rate and parity constraints; MetaHotels facts checked against the register.
- [ ] No superlative without a source; no invented review, statistic or testimonial.
- [ ] Variants differ in one variable; the test plan states the sample size before any verdict.
- [ ] The differentiator inventory was done from the hotel's own site, and the Big Idea uses one item from it. Swap test run: with a competitor's name in place, the ad stops being true.
- [ ] Visual assets follow `design-standard.md` (Gate 5 #15) and the render was viewed before showing.
- [ ] Ads: tracking row checked (Gate 5 #14); data brief done with sources and dates; swipe-file rows cited and the control named; Gate 5 scorecard shown; brief ends `Scorecard: PASS` only if every hard gate passed.
- [ ] Ads: never set a budget (ask Saif); publish paused only.
