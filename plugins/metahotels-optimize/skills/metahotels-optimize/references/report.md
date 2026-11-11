# Step 9: the report and the two cross-site documents

## 9. Report (`<site>/performance-report-YYYY-MM-DD.md`)
Sections:
1. Issues found
2. Changes applied: for each, issue, root cause, action, files/settings, benefit, risk, verification
3. Not applied (with test evidence)
4. LiteSpeed settings before → after
5. Scripts removed/deferred/delayed
6. Booking-engine duplicate calls
7. reCAPTCHA
8. 404s (assets and pages) and calls to action without a link, each with the widget or menu item that owns it
   (step 1b)
9. Addon assets removed, and the widgets switched off in Elementor's Element Manager (step 5b)
10. Fonts
11. Cache headers
12. Recommendations
13. Before/after table
14. Rollback steps
15. Page weight: no scroll and no input, and a full session with scrolling
16. Lab score breakdown: points lost per metric and what the blocking time is made of
17. Score versus visitor experience: each case where a test-tool number and what a visitor gets disagreed, with both
    sets of numbers and the decision

**Every site, before the pass counts as done:** add the site's section to the two cross-site documents in the
work folder, below the existing ones, update each "Last updated" date, and rebuild their PDFs. Numbers and run counts
come from the site's report, not from memory.

`optimization-results.md` (what was done and the before and after):
- "What was changed": one plain-language line per change that is live, from section 2. Anything built but not
  live yet (a zip not uploaded, a core release pending) is listed as not live, with the date it was checked.
- "Before and after": a `Measure | Before | After` table from sections 13 and 15: throttled-phone first paint,
  largest paint and DOMContentLoaded, layout shift, page weight with no scroll and no input, and every PageSpeed
  run. A result that depends on a fix that is only simulated says so in the cell.
- "Notes": variance, anything not tested, anything measured before a later change.
- Add the site's row to the "At a glance" table at the top, including every PageSpeed mobile run before and after.
  Within a table, mobile rows come before desktop rows.
- A follow-up pass on a site already listed gets its own "What was changed" and "Before and after" pair under
  that site's heading (see Gevora); the earlier pass stays.

`score-vs-experience.md` (section 17 of the report):
- One table row per case: change, what the number said, what a visitor gets, decision.
- Counts: a score gain taken at a real-load cost (state both); a score gain left off because it was a huge
  departure for visitors (say which kind, Hard rules); a change kept although the score stayed flat or fell; a
  measured gain rejected because it broke something a visitor uses.
- Does not count: options that simply showed no difference (they stay in section 3).
- No such case on a site: say so in both places instead of leaving the section out.

Then, from the work folder, `node $S/md-pdf.js --shots=<scratch dir>` rebuilds `optimization-results.pdf` and
`score-vs-experience.pdf`. Look at the page screenshots it saves (no table cut off, the new section present).
Never edit a PDF itself; the Markdown files are the source.

Keep one rollback file per changed snippet or template in `<site>/rollback/` before writing to it.

State measurement variance honestly.

