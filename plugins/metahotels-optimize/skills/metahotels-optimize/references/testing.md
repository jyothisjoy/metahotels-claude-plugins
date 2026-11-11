# Testing a hypothesis before acting, and measurement traps

Read before simulating a change (abhtml.js, simhtml.js, floor.js) and before reading anything into a
PageSpeed or throttled-phone number.

Verify a hypothesis in headless Chrome before acting (inject or block with `evaluateOnNewDocument` / request interception against the live page):
- `node $S/abhtml.js <label> <url> <rules.json|-> [runs] [--fast] [--desktop] [--shifts] [--shot=f.png] [--probe=expr]`
  applies find/replace rules to the live HTML and measures FCP/LCP (+ LCP element)/DCL/load/CLS/TBT under Slow 4G + 4x CPU.
  `-` is the control. The document itself is served unthrottled, so compare variants with each other, not with `throttle.js`.
  `--shifts` prints each layout shift with the rects of the elements that moved; use `--wait` longer than any popup timer.
- `node $S/simhtml.js <url> <rules.json> [--watch=regex]` pixel-diffs the page with and without the rules (desktop + mobile).
  If one run differs, repeat: a late image in one screenshot looks like a diff.
- `node $S/images.js <url> [desktop|mobile] [--scroll]` lists what loads without scrolling, intrinsic vs displayed size and the
  widget using it. `node $S/weight.js <url> [desktop|mobile] [rules.json]` gives page weight with no scroll and no input, which
  is what GTmetrix-style tools report.
- `simhtml.js` blocks YouTube/analytics as noise; a page with an Elementor Gallery or counters can still differ between two
  unchanged runs, so run a no-op rule (`[{"find":"</head>","replace":" </head>"}]`) as a control before trusting a diff.
- Anything that makes the page initialise sooner also moves everything timed from Elementor's init: check CLS with
  `--shifts` before **and** after, and note that page-load-timer popups will open earlier in the visit.
- `abhtml.js --block=<regex>` aborts matching requests and `--cpu=<n>` sets the CPU slowdown: "what would this page cost
  without script X" for TBT attribution (desktop: `--fast --desktop --cpu=2 --wait=12000`) and for finding what still
  gates first paint (block the remaining render-blocking files one group at a time).
- For "what gates first paint" use `scripts/checks/floor.js` instead (same throttling as `throttle.js`, the real
  compressed document, `--block=`): `abhtml.js` serves the document uncompressed through interception, which on Slow 4G
  takes longer than the stylesheets and hides their cost (Abar: `abhtml.js` showed no effect, `floor.js` 3.0–3.5 s →
  2.3 s without the stylesheets). An aborted file also frees its bandwidth, so the result is an upper bound: critical CSS
  reached none of it on Abar because the asynchronous stylesheets download alongside the files that still block.
- In Git Bash a `--block=` pattern that starts with `/` is rewritten to a Windows path and matches nothing: prefix the
  command with `MSYS_NO_PATHCONV=1` and check the script's "blocked" count.
- A LiteSpeed setting switched on for a test is used for every page generated while it is on, not only the purged front
  page. After reverting, run `scripts/state.sh` (markers per sitemap URL) and Purge All.
- Translated header, footer and page templates share element IDs or look alike: read which template each language's page
  prints (`data-elementor-type="header" data-elementor-id`) before applying per-language values (Khalidia: Spanish and
  Chinese top-bar widths were swapped for 12 minutes).
- Never edit a shell script while it is running (bash reads it by byte offset), make no MCP save while a measurement
  runs (every Elementor save purges the cache), and write PHP or regex text with the Write tool: a heredoc turned
  `\b` into a backspace character inside a plugin file.
- After a page becomes fully cached at the CDN, PageSpeed mobile can get worse while real loads improve (Khalidia:
  simulated first paint 3.5–4.2 s → 10.6–11.4 s): on the test machine the first paint coincides with the hero, so every
  request before it is charged. Compare `observedFirstContentfulPaint` with `firstContentfulPaint` in the `metrics`
  audit before reading anything into the score.
- PageSpeed serves a cached result for about 30 s: leave 35 s between `psi.py` runs. Mobile lab results come in two
  groups whatever is changed (Nassima: FCP ~3.5 s or ~6 s); compare runs from the same group, and use
  `python -I $S/psi_breakdown.py <host> <label1> <label2> ...` to line them up.

