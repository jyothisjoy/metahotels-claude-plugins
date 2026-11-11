# {Site name}: performance pass, {YYYY-MM-DD}

{One paragraph: what the site is (hotels, languages, number of sitemap URLs, CDN or not), what was found, what changed,
and the headline before → after on a throttled phone and in PageSpeed mobile. Say what is live and what is not yet
(a zip not uploaded, a metahotels-core release pending), with the date it was checked.}

Measurement conditions: throttled phone = Slow 4G + 4x CPU, median of 3 runs per set (`throttle.js`); PageSpeed =
the API, mobile first, runs 35 s or more apart; weight = no scroll and no input (`weight.js`). State the variance.

## 1. Issues found
## 2. Changes applied
{For each: issue, root cause, action, files/settings (with element and document ids), benefit (numbers), risk,
verification.}
## 3. Not applied (with test evidence)
## 4. LiteSpeed settings before → after
## 5. Scripts removed, deferred or delayed
## 6. Booking-engine duplicate calls
{Document only: the booking engine is never changed.}
## 7. reCAPTCHA
## 8. 404s and calls to action without a link
{Assets and pages; each finding with the widget or menu item that owns it; what was fixed; what the owner must give
(booking links per hotel, other targets).}
## 9. Addon assets removed, and widgets switched off in Element Manager
## 10. Fonts
## 11. Cache headers
## 12. Recommendations
{Including every option that needs the owner's approval (UCSS, JS Delay, first-interaction loading, QUIC.cloud quota),
each with its expected score gain and its cost for visitors.}
## 13. Before/after table
| Measure | Before | After |
|---|---|---|
| Throttled phone first paint (mobile) | | |
| Throttled phone largest paint (mobile) | | |
| Throttled phone DOMContentLoaded (mobile) | | |
| Layout shift (mobile / desktop) | | |
| PageSpeed mobile (every run) | | |
| PageSpeed desktop (every run) | | |
## 14. Rollback steps
{Every rollback file in rollback/, every new attachment id, every setting with its old value.}
## 15. Page weight
{No scroll and no input, desktop and mobile; and a full session with scrolling.}
## 16. Lab score breakdown
{Points lost per metric (psi_breakdown.py) and what the blocking time is made of (abhtml.js --block table).}
## 17. Score versus visitor experience
{Each case where a test-tool number and what a visitor gets disagreed: both sets of numbers and the decision. "No
such case on this site" when there was none.}
