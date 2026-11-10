# Third-party SEO tool warnings: what matters

From the Abar run (handoff, Nov 2026). Hotels and agencies forward Semrush, Ahrefs or Ubersuggest site-audit reports. Those
tools score everything they can measure, and many warnings have nothing to do with how Google ranks a hotel. Use this
table with `/hotel-seo check`: triage every warning as **fix**, **fix if cheap** or **no action**, and explain the
no-action ones too, so the client learns which warnings to ignore. Write them as "already in good shape", never as
"your tool is wrong", and never as criticism of whoever built the site.

**Check every warning on the live site before calling it noise.** The tool can be right about this site even when the
warning type is usually noise. Where our own tools cover it, quote ours (`audit_site`, `site_consistency_check`).

| Warning | Verdict | Why / client wording |
|---|---|---|
| Internal links with nofollow | **Fix** | It tells Google not to pass value to your own pages. Usually one Elementor link setting (Abar homepage, Nov 2026: the Contact and Gallery links). `site_consistency_check` reports them (INTERNAL-NOFOLLOW). |
| Low word count / thin content on a page that should rank | **Fix** (copy) | A page meant to rank needs enough real content to answer the search: write it to [content-writing.md](content-writing.md), facts only from confirmed sources, and with the client's approval first where `hotel.json` says so. Never a word-count target. |
| Low word count on a utility page (thank-you, login, booking steps) | No action | Those pages aren't meant to rank (they should be noindex: registry T02). |
| Broken internal links (4xx) | **Fix** | Re-tested live first: crawl-time timeouts and blocks are often false alarms (`audit_site` lists them under "load fine now"). |
| Duplicate / missing title or meta description | **Fix** | Each page needs its own. |
| Title too long / meta too long | Fix if cheap | Google truncates on screen; it doesn't penalise. Titles ≤ 60, metas ≤ 155 characters. |
| Missing / multiple H1 | **Fix** | One H1 per page that says what the page is. |
| Missing alt text | Fix if cheap | Helps image search and accessibility; written after viewing each image. |
| Redirect chains / temporary (302) redirects | **Fix** | Point links at the final URL; 301 for permanent moves. |
| Orphan pages (no internal links in) | **Fix** | Google finds and values pages through links: link it, redirect it or remove it (registry L01). |
| Duplicate FAQ / structured data on several pages | **Fix** | Keep each FAQ on the page it belongs to (`site_consistency_check` FAQ-DUPLICATE / FAQ-MULTI). |
| Unminified JS/CSS | No action | "The effect on speed is negligible." Caching and compression already do most of the work. Say "negligible", not "no effect". |
| Low text-to-HTML ratio | No action | "It compares the amount of visible text with the page's code. Google doesn't use it, and it doesn't measure speed or quality, so there's nothing to fix." |
| Too many on-page links | No action | Usually menus and footers. Not a ranking problem at hotel-site scale. |
| Large DOM / page size, slow pages | Performance plugin | Act only if Core Web Vitals (real-user data) fail; that work is metahotels-optimize's, not this list's. |
| Sitemap not listed in robots.txt | Fix if cheap | One line; Search Console already has the sitemap. |
| Missing hreflang | Only on multilingual sites | Fix on sites with /ar/, /de/ … versions (registry T15); no action on English-only sites. |
| llms.txt missing | No action | Optional; Google Search ignores it (registry rule 12). |
| AMP / "uncached JavaScript" / "low readability" score | No action | Not ranking factors for a hotel site. |
| "Domain authority", "authority score", "toxic score" | No action (context) | Each tool's own estimate, not something Google uses. Never "disavow everything". |
| "Submit to Google with the Indexing API" | No action | The Indexing API is only for job postings and livestreams. Request indexing in Search Console (`<recheck>-indexing-requests.md`). |

## Why keyword tools disagree on volume

Clients compare our numbers with their tool's. Explain the difference once; don't argue over it.

- **Keyword Planner** (Google, what we use) shows Google's own figures. It groups close variants and brand variants
  together and, without ad spend, shows rounded figures. Abar's brand showed 6,600 here and 390 in Semrush.
- **Semrush / Ahrefs** estimate volume from clickstream panels and their own models. They are usually lower for small
  local and brand searches, and they count each spelling separately.
- **Search Console impressions** are what actually happened for this site, and the most reliable of the three. Use them
  to sanity-check both (mind the impressions anomaly of 13 May 2025 – 27 Apr 2026: registry rule 11).

Client wording: "The tools measure it differently. Google's own planner groups similar searches together, while Semrush
estimates each one separately, so for smaller local searches the numbers can differ a lot. Search Console shows what
actually happened on your site, and that's what we report against."
