# Editing and review gates

Source: Agora Books One and Two (notes 14, 15, 16, 17), Agora's own copy-quality system. Run the gates in order. Each one catches what the previous one can't.

## Gate 0: idea and FK (MMF's mandate)
At the top of every draft:
- `Idea: <one sentence>`
- `FK: <score>` (from `scripts/fk_grade.py`; target under 7.5)

If the sentence doesn't impress, stop; the problem is the idea, not the words. If a paragraph is needed to say the idea, there is no idea.

## Gate 1: Peer Review (MMF), self-run as the named reader
Score on gut reaction only (no theory):

| Score | Meaning |
|---|---|
| 1 | Definitely would not read on |
| 2 | Probably would not read on |
| 3 | Would read on, with some scepticism |
| 4 | Would read on with high interest |

1. Score the headline. Below 3.0, write **replacement lines** (not comments), re-score, and keep the best.
2. Score the lead (the first 200–400 words, or the first screen). **Below 2.8, abort it** and write a new lead from a different lead type.
3. At 3.0 or above, move on.

Rules carried over from Agora's human version:
- no criticism;
- no theory;
- only replacement copy;
- scores measure likely response, not quality.

When Saif can, a real Peer Review with 3–5 colleagues on major pieces (a launch email, the Leak Audit, a landing page) beats a self-score. **A self-score is the weakest leg of this system:** the writer grading its own lines is biased. Say so beside the score. For any new campaign, show Saif the top 3 hooks unlabelled (not ranked, writer's favourite not marked) and ask Saif to pick. That pick plus the live test outrank the self-score. The swipe file is the Pro Review the market gives. Agora requires Peer Review **and** Pro Review (about 10 minutes from a proven writer) before anything ships.

## Gate 2: CUB-DF (Palmer, plus Bonner's D and F)
Mark every passage that is:
- **Confusing.** Causes: esoteric detail, too many numbers in one sentence, vague references, too many ideas. Confusing charts and visuals count too. **Fix: cut first, then make it specific, then simplify.**
- **Unbelievable.** Fix by cutting or proving.
  - Vague = unbelievable, so make it specific.
  - Clichés ("pays for itself many times over") remind readers it's an ad; replace them with a sceptic's testimonial.
  - Answer "If this is so good, why haven't I heard of it?" with a plausible, true reason.
  - "I know this sounds hard to believe…" works once, late, and only as a third resort.
- **Boring.**
  - Telling them what they already know (don't tell a cancer patient how bad cancer is).
  - Lingering on dull mechanics.
  - Wandering.
- **Distracting** from the main message.
- **Failing to fulfil** the lead's promise. If the headline promises a quiet beach weekend, the page must deliver it.

## Gate 3: the 12 questions (MMF), for long-form pages and emails
1. Does the lead make clear why to read on **now**?
2. Are the speaker's or brand's **credentials** established?
3. Is the speaker **likeable**?
4. Are the key claims **proven**?
5. Does the emotional excitement carry to the end?
6. Are features expressed as benefits, and as **deeper** benefits?
7. Is there a **false close plus a liquidating benefit**?
8. Is the offer **irresistible** (value equation)?
9. Is there an **immediate-action** element (real)?
10. Is the offer **restated at the end** with more allure?
11. Does the **guarantee or risk reversal** make it a no-brainer (real policy only)?
12. Is the **order or booking step simple**?

## Gate 4: Bonner's basic rules
1. An idea big and unique enough.
2. 80% of the energy on the lead.
3. Every lead either promises a **benefit** or tells a **story** with an implied benefit.
4. Then CUB.

## Gate 5: Ad scorecard (every ad, every platform)
Score each ad (or each RSA / asset group / Meta creative) and show the table in the brief. **Hard gates** must pass; a fail means rewrite, not a warning.

| # | Check | Type | Pass when |
|---|---|---|---|
| 1 | Big Idea in one sentence, it cites the data-brief row it rests on, **and it answers "why this hotel over the next one?" with a differentiator from data brief row 12** | Hard | The insight and the differentiator are named (e.g. "row 12: pet-friendly floor, cats and dogs ≤10 kg; row 9: pet ad = best engagement per AED"). A Big Idea built on a category benefit (staycation, relaxation, luxury, a generic discount) fails |
| 2 | Rule of One: one idea, one reader, one action | Hard | Exactly one CTA; one promise |
| 3 | Hook / headline Peer score as the named reader | Hard | ≥ 3.0 (replacement lines written until it is) |
| 4 | 4 U's on the hook (useful, urgent, unique, ultra-specific) | Soft | ≥ 3 of 4 |
| 5 | Specific, not vague (numbers, names, real details) | Hard | **Swap test, done literally:** replace the hotel's name with a nearby competitor's. If the headline and image text still read as true, FAIL. No line that any hotel could run unchanged. Exception: brand and "official site" lines in an RSA or PMax pool. Evidence: generic CTA and vague-value headlines lost at 3 hotels (swipe file, 24 Oct 2026) |
| 6 | CUB-DF pass | Hard | Nothing confusing, unbelievable or boring left |
| 7 | Reading level | Soft | FK under 7.5 (ads: aim for 6) |
| 8 | Message match: ad → landing page → booking engine, checked live | Hard | The promise and offer appear above the fold on both |
| 9 | Claims: MetaHotels facts from the register; hotel facts dated; prices bookable and parity-safe today | Hard | Every claim has its source beside it |
| 10 | Platform limits and policy (`platform-google.md` / `platform-meta.md`) | Hard | Within limits; no policy flags (superlatives, personal attributes, health) |
| 11 | Hormozi's 12 commandments, quick pass (`channel-playbooks.md`) | Soft | Used where they fit |
| 12 | Swipe file consulted; angle differs from known losers or says why | Soft | Rows cited |
| 13 | Variants differ in one variable; test plan with sample gate; the control named | Hard | Stated |
| 14 | Tracking can read the test: the campaign's primary conversion actions are this hotel's real booking (no other hotels' actions, no map or call or add-to-cart actions as primary, no value = 1) | Hard | The hotel's row in `6_Campaigns/ads_history/Tracking_Quality_<date>.md` is clean, or re-checked live today. If it isn't, the brief's first action is the goal fix (for Saif to apply), and the test plan waits for a clean window |

| 15 | Design (image and video ads) | Hard | Follows `design-standard.md`: the hotel's own story photo, a chosen layout (no default dark gradient), max two typefaces in a set hierarchy, brand colours sampled from the logo and site, the logo integrated in the panel (never on a box), nothing clipped or crowded. The render was viewed before showing. Self-check: would it pass as the hotel's in-house brand creative? |

**Scoring honestly:** a self-run gate drifts to PASS. Gates 1, 5 and 15 are written as tests that can fail; run them as written, and when in doubt score FAIL and fix. On 25 Oct 2026 a generic "A night off" ad was self-scored PASS on #1 and #5 and rejected by Saif on sight.

`Scorecard: PASS` only when every hard gate passed for every ad in the brief.

## The three-pass edit (MMF): most important pass first
1. **Value edit:** is the idea strong, the promise clear, the proof sufficient? Restructure here.
2. **Functional edit (CUB):** flow, logic, clarity, cuts.
3. **Copyedit:** grammar, facts, names, prices, dates, links. Check every price and date against the live source on the day.

## Before-ship clean-up (Zinsser, Strunk & White, Ogilvy)
- Bracket the words doing no work and cut them.
- Replace long words.
- Remove qualifiers ("very", "quite", "a bit").
- Remove superlatives without a source.
- Read it aloud.
- **Ogilvy:** "If you want ACTION, don't write. Go and tell the guy." For B2B, ask whether this should be a call instead.

## Beyond Peer Review (Forde)
If every lead keeps scoring badly, the product or offer is the problem. **Fix the offer, not the copy** (value equation, Sharpe's 10 tests).

## Testing discipline (Agora space-ad rules + CLAUDE.md)
- Change one variable at a time.
- Key every version.
- A challenger must beat the control by **20%+** to be a clear winner (Agora), **and** reach the sample-size gate (CLAUDE.md: no verdict below about 1,000 clicks for paid media).
- Don't change a winner because *you're* bored of it (Halbert #3); the market sees it for the first time.
