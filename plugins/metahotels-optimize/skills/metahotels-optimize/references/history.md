# Reference runs: what was found on each site

Read this when a symptom looks familiar, to find the site report with the full story, the numbers and the code.
The reports live in the MetaHotels work folder, one folder per site: `<site>/performance-report-<date>.md`, the site
plugin in `<site>/<site>-performance/` (copies in this skill's `assets/plugin-examples/`) and the audit files. If
your work folder does not have them, the summaries here and in references/patterns.md stand on their own.

- **Gevora** (`gevora-prod/performance-report-2026-10-09.md`, `gevora-performance/`): the first pass. Unused addon
  assets (Header Footer Elementor, Gum, ElementsKit) dequeued by a site plugin; booking-engine duplicate calls
  documented; JS Defer and CSS Combine rejected.
- **Nassima Tower** (`nassimatower/performance-report-2026-10-10.md`, `nassimatower-performance/`): a blocking 1.4 MB
  chatbot (DOMContentLoaded 29 s on Slow 4G), hero preload, Jeg Kit icon-font subset, top-bar CLS from the Mirai
  finder, lazy CSS backgrounds, image re-encoding, page weight, lab-score breakdown, and a CDN switch in mid-pass.
- **Abar** (`abarhotels/performance-report-2026-10-12.md`, no site plugin needed): a hero slideshow that never painted
  its first slide (LCP 16.3 s → 3.2 s), loop templates loading full-size images, menu font-swap CLS, reCAPTCHA
  lazy, hidden sections. LiteSpeed lazy images kept; Lazy Load Iframes broke a Google Map.
- **Gevora follow-up** (`gevora-prod/performance-report-2026-10-12.md`): a timed popup that scrolls the page to the
  bottom (CLS up to 1.0, megabytes of images loaded), the booking bar redrawn three times, LiteSpeed lazy-load
  versus carousels (duplicate slides never got their image).
- **Shams** (`shamshotels/performance-report-2026-10-13.md`, `shamshotels-performance/`): multi-property, 347 URLs.
  Header and hero hidden by entrance animations until Elementor's script runs (LCP 7.6–8.4 s → 2.7–2.8 s),
  ElementsKit icon-font subset, CSS Combine breaking the first copy after a CSS regeneration, the first link and
  call-to-action check, the Element Manager housekeeping, R2 hero video sizes, PageSpeed's simulated LCP stuck at 15 s.
- **Khalidia Palace** (`khalidiapalace/performance-report-2026-10-13.md`, `khalidia-performance/`): five languages,
  130 URLs. Homepage never cached because of Polylang's browser-language redirect, hero slideshow painted from CSS by
  the site plugin without a hard-coded URL, deleted logo files requested by the theme's logo widget, top-bar
  reservation per language, Font Awesome subset inlined, "Load Font Awesome 4 Support" removing icons.
  Independent hotel: never link it to group hotels (owner).
- **Gewan** (`gewanhotels/performance-report-2026-10-14.md`, `gewan-performance/`): the first site-wide image
  re-encode (226 Elementor documents, 329 files, 93.9 MB → 29.4 MB; featured and block-editor images too), CSS
  Combine rejected for a later hero, a stubborn dequeue (WP Job Openings Pro Pack). Follow-up of 2026-10-15: every
  redirecting link pointed at its final page (four landed on another hotel's page), self-linking "Read More" hidden,
  hero video from R2 with "Start After Page Load", the first LibreCrawl run.

Cross-site documents in the work folder, each with a PDF built from it: `optimization-results.md` (what was changed
on each site, before and after) and `score-vs-experience.md` (the decisions where a lab number and what visitors get
disagreed). Every pass adds its section to both and rebuilds the PDFs (references/report.md).
