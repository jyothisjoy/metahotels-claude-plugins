# LibreCrawl: crawls, Custom Search and redirect tests

LibreCrawl (open source, replaces Screaming Frog) is installed by `/hotel-seo init` in `~/.metahotels-seo/librecrawl`, pinned to a tested version. It runs in local mode (no login) on **http://127.0.0.1:5057**, reachable only from this machine, and the `hotel-seo-tools` MCP server starts it on demand. Logs: `~/.metahotels-seo/logs/librecrawl.log`. Crawl history: `~/.metahotels-seo/librecrawl/data/`.

To look at a crawl in the browser GUI: `librecrawl_control("start")`, then open http://127.0.0.1:5057.

## Tools

| Tool | Use |
|---|---|
| `crawl_site(url, out_dir, js=false)` | Crawl with the hotel settings and write the files below. Returns a job; poll `job_status`. 10–30 min for a hotel site. |
| `job_status(job_id)` | Wait for a crawl, search or redirect test. If the server restarted mid-crawl, use `list_crawls` + `export_crawl`. |
| `list_crawls()` / `export_crawl(crawl_id, out_dir)` | Saved crawls; re-write the files for one. |
| `read_crawl_file(path, columns, where, contains, offset, limit)` | Read CSV rows with filters, e.g. `where={"is_internal": "True"}` on `inlinks_4xx.csv`. Also reads `overview.md`. |
| `custom_search(crawl_dir, terms, case_sensitive, text_only)` | Count terms on every 200 page; writes `custom_search.csv`. Raw HTML by default; `text_only` for visible text; `case_sensitive` for names that are also ordinary words ("Royal M" otherwise matches "royal marriage hall"). |
| `test_redirects(out_dir, pairs=[{source, expected}])` | List-mode redirect test; writes `redirect_test.csv`. PASS = first hop 301, ends on `expected` with a 200. |
| `librecrawl_control(status/start/stop)` | Troubleshooting. |

## Crawl settings

| Setting | Value | Why |
|---|---|---|
| concurrency / delay | 2 / 1 s | About 2 URLs/s, polite on shared hotel hosting (same as the old Screaming Frog setup) |
| max depth | 10 | The default of 3 misses deep blog pages. 10 is the most LibreCrawl accepts: anything higher and the whole settings save is rejected. Al Bahar's deepest page was at depth 9 |
| max URLs | 5000 | |
| robots.txt, sitemap discovery | on | |
| external links | not crawled, but their status is checked | Dead links to other hotels' sites show up in `inlinks_4xx.csv` |
| PageSpeed, JavaScript | off | Speed goes to the Web Team list; turn JS on (`js=true`) only if the plain crawl misses content |

## Files per crawl

| File | Old Screaming Frog export | What's in it |
|---|---|---|
| `internal_all.csv` | Internal → All | Status (redirects show their first 3xx hop), final URL, indexability and reason, title and meta with lengths, H1, canonical, meta robots, word count, response time, depth, inlinks, lang, og:site_name |
| `canonicals.csv` | Canonicals → All | 200 pages: canonical and self / canonicalised / missing |
| `directives.csv` | Directives → All | Meta robots, noindex, nofollow |
| `structured_data.csv` | Structured Data → All | JSON-LD block count, `@type` list, raw JSON-LD; microdata count |
| `hreflang.csv` | Hreflang → All | Pages with hreflang tags |
| `inlinks_4xx.csv` | 4xx Inlinks | Every link to a 4xx/5xx or unreachable (status 0) target: source, target, anchor, placement (navigation / footer / body / image), internal or external |
| `inlinks_3xx.csv` | 3xx Inlinks | Every link to a redirecting URL, with where it ends up |
| `images_missing_alt.csv` | Images Missing Alt Text Inlinks | Page, image src, alt missing or empty |
| `issues.csv` | none | LibreCrawl's checks: title/meta length, duplicates, thin content, slow pages |
| `overview.md` | Crawl Overview | Counts by status, indexability and issue |
| `custom_search.csv`, `redirect_test.csv` | Custom Search, All Redirects | From the tools above |
| `crawl.json` | none | The raw crawl |

## Gotchas

- **Redirects come back as 200** in LibreCrawl's own data: a redirecting URL is stored with the final page's status and content. The files above already report the first hop (Al Bahar: 41 redirects vs 39 in Screaming Frog).
- **No structured data validation.** JSON-LD is extracted, not checked: validate the homepage and one inner page with Google's Rich Results Test.
- **No X-Robots-Tag headers.** Directives cover the meta robots tag only; check headers (`curl -I`) when a page is unexpectedly missing from Google.
- **Status 0** means no response (timeout, DNS, SSL). At Al Bahar these were dead links to other hotel groups' sites.
- **Duplicate Content and Thin Content** are noisy on Elementor sites (the shared header and footer dominate each page). Hints, not list items.
- **Issue exclusions** (Settings → Issues in the GUI) hide `/wp-admin/`, `/wp-content/` and similar from `issues.csv` only; the other CSVs are built from the raw data.

## Appendix: the raw API (troubleshooting only)

Base `http://127.0.0.1:5057/api`, JSON bodies, session cookie (local mode logs any cookie-less request in as `local` admin). Main endpoints: `POST /save_settings` (merges keys), `POST /start_crawl {"url"}` → `crawl_id`, `GET /crawl_status?stats_only=1` (poll), `GET /crawl_status` (full `urls`, `links`, `issues`), `GET /crawls/list`, `GET /crawls/<id>`, `POST /stop_crawl`. A crawl belongs to the session that started it; `/crawls/<id>` works from any session but drops `redirected_to`.
