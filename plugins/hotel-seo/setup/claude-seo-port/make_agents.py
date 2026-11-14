"""Generate plugins/hotel-seo/agents/*.md from claude-seo's agents (MIT) + hotel-seo specifics."""
import re
import sys
from pathlib import Path

SRC = Path(sys.argv[1])          # claude-seo-main
DST = Path(sys.argv[2])          # plugins/hotel-seo/agents
DST.mkdir(parents=True, exist_ok=True)
P = 'mcp__plugin_hotel-seo_hotel-seo-tools__'
REF = '${CLAUDE_PLUGIN_ROOT}/skills/hotel-seo/references'
CS = REF + '/claude-seo'

COMMON_TOOLS = ['Read', 'Write', 'Grep', 'Glob', P + 'seo_check', P + 'read_crawl_file', P + 'job_status',
                P + 'validate_agent_output']

AGENTS = {
    'seo-technical': dict(model='sonnet', turns=50, scope='site', web=False,
                          extra=[P + 'inspect_pages', P + 'site_mcp_read', P + 'test_redirects'],
                          title='Technical SEO Lead', refs=[f'{CS}/technical/skill.md', f'{CS}/seo/cwv-thresholds.md',
                                                            f'{CS}/technical/stack-cve-exposure.md']),
    'seo-sitemap': dict(model='sonnet', turns=30, scope='site', web=False, extra=[P + 'site_mcp_read'],
                        title='Sitemap Architect', refs=[f'{CS}/sitemap/skill.md', f'{CS}/seo/quality-gates.md']),
    'seo-performance': dict(model='sonnet', turns=35, scope='site', web=False, extra=[P + 'inspect_pages'],
                            title='Performance Engineer', refs=[f'{CS}/seo/cwv-thresholds.md']),
    'seo-agentic': dict(model='sonnet', turns=35, scope='site', web=False, extra=[],
                        title='Agent Readiness Analyst', refs=[f'{CS}/agentic/skill.md', f'{CS}/agentic/access-policy.md',
                                                               f'{CS}/agentic/lighthouse-agentic-category.md',
                                                               f'{CS}/agentic/vendor-matrix.md',
                                                               f'{CS}/agentic/discovery-and-markdown.md',
                                                               f'{CS}/agentic/agent-friendly-pages.md',
                                                               f'{CS}/agentic/webmcp.md']),
    'seo-backlinks': dict(model='sonnet', turns=40, scope='site', web=False, extra=[P + 'bing_report'],
                          title='Link Analyst', refs=[f'{CS}/backlinks/skill.md', f'{CS}/seo/backlink-quality.md',
                                                      f'{CS}/seo/free-backlink-sources.md']),
    'seo-content': dict(model='opus', turns=60, scope='hotel', web=False,
                        extra=[P + 'inspect_pages', P + 'download_images', P + 'site_mcp_read'],
                        title='Content Editor', refs=[f'{CS}/content/skill.md', f'{CS}/seo/eeat-framework.md',
                                                      f'{CS}/seo/eeat-scoring-guide.md', f'{CS}/seo/quality-gates.md']),
    'seo-schema': dict(model='sonnet', turns=35, scope='hotel', web=False, extra=[P + 'site_mcp_read'],
                       title='Structured Data Engineer', refs=[f'{CS}/schema/skill.md', f'{CS}/seo/schema-types.md',
                                                               f'{CS}/schema/deprecated-types-2024-2026.md',
                                                               f'{CS}/seo/local-schema-types.md',
                                                               f'{CS}/seo/local-schema-multilocation.md']),
    'seo-geo': dict(model='opus', turns=35, scope='hotel', web=True, extra=[],
                    title='AI Search Analyst', refs=[f'{CS}/geo/skill.md', f'{CS}/geo/google-ai-optimization-guide.md',
                                                     f'{CS}/geo/llmstxt-evidence.md']),
    'seo-local': dict(model='sonnet', turns=32, scope='hotel', web=True, extra=[P + 'geo_lookup'],
                      title='Local SEO Specialist', refs=[f'{CS}/local/skill.md', f'{CS}/seo/local-seo-signals.md',
                                                          f'{CS}/seo/local-search-behavior.md',
                                                          f'{CS}/seo/local-schema-types.md']),
    'seo-maps': dict(model='sonnet', turns=40, scope='hotel', web=True, extra=[P + 'geo_lookup', P + 'nearby_places'],
                     title='Maps Analyst', refs=[f'{CS}/maps/skill.md', f'{CS}/seo/maps-gbp-checklist.md',
                                                 f'{CS}/seo/maps-free-apis.md', f'{CS}/seo/maps-geo-grid.md',
                                                 f'{CS}/seo/local-seo-signals.md']),
    'seo-flow': dict(model='sonnet', turns=20, scope='hotel', web=True, extra=[],
                     title='FLOW Strategist', refs=[f'{CS}/flow/skill.md', f'{CS}/flow/flow-framework.md',
                                                    f'{CS}/flow/prompts/README.md']),
}

HOTEL = {}
HOTEL['seo-technical'] = """
## Hotel-seo specifics

Scope: the whole group site, once. Tag each finding with the hotel whose pages it touches (`hotel` = slug), or
`group` when it is site-wide.

1. **Start from the code.** Read `findings.md` and `findings.json` (audit_site) and `partition.json`. Restate these core
   checks with exact fixes (set `check` to the id and list exactly its URLs): `canonical_broken`, `canonical_other`,
   `canonical_missing`, `noindex_on_key_page`, `booking_page_indexable`, `junk_page`, `link_broken`. Use
   `replace_pairs.csv` and `inlinks_3xx.csv` for links through redirects.
2. **Indexing.** Read `<crawl>/indexing/` (index_status: Google's state per URL, chosen canonical) and the Search
   Console part of findings.json (old http / www versions with clicks, booking pages in search).
3. **Headers and server.** `seo_check("fetch_page.py", [url, "--json"])` on the homepage, each hotel's main page and one
   room page: HTTPS, redirects (max one hop), security headers, `X-Powered-By` / PHP version (stack-cve-exposure.md).
   Header / server items are `owner: "web"`.
4. **Rendering and mobile.** `seo_check("render_page.py", [url, "--mode", "always", "--json"])` on one page per template
   (home, a hotel page, a room page, an offer, a blog post): raw vs rendered content, canonical / robots / JSON-LD
   present in raw HTML. `inspect_pages` (mobile) for viewport, tap targets, horizontal scroll, pop-ups over the booking
   button.
5. **robots.txt and AI crawlers:** access per crawler with what it governs (training vs search). seo-geo reports
   citability; you report access and blocking mistakes.
6. **Rank Math settings (read-only).** If the site is in `sites.csv`: `site_mcp_read(site, "seo-get-settings",
   {"group": "titles"})` and `{"group": "sitemap"}`, and `seo-get-posts` with `filter` (`robots_override`,
   `canonical_override`, `noindex`) to give exact setting changes. These become `rankmath_setting` actions (group-wide)
   or `seo_fields` actions per post.
7. Security findings from audit_site (suspicious posts, open MCP / REST routes, public users, leftover llms.txt,
   spam searches) are already in the report (Critical, Web Team): don't repeat them. Add only security problems
   audit_site did not report (headers, mixed content, exposed files), `owner: "web"`.
8. Redirect fixes: `redirect` actions (301; regex for patterns such as `^/bookingstep1`); test proposed rules with
   `test_redirects` when the targets exist.
"""
HOTEL['seo-sitemap'] = """
## Hotel-seo specifics

Scope: the whole group site, once.

1. `seo_check("sitemap_discovery.py", [site, "--json"])`; then for every sitemap in `found` and `declared`: XML valid,
   URL count and size limits, every URL's status (use the crawl's statuses; `fetch_page.py` for URLs the crawl did
   not see), noindexed URLs in the sitemap (`directives.csv`), redirected URLs, `lastmod` sanity.
2. **Crawl vs sitemap:** indexable 200 pages missing from the sitemap (by hotel), and sitemap URLs that are 404 /
   redirect / noindex. Post types listed vs post types that should be (pages, rooms, offers, posts; not facilities,
   tags, authors, attachments) — see findings.json `report.sitemaps`.
3. **Search Console and Bing:** submitted sitemaps and their live status (findings.json `gsc.submitted_sitemaps`),
   Bing sitemaps (`<crawl>/bing*` if bing_report ran). Removing dead submissions / submitting `sitemap_index.xml` are
   `chrome` actions (`where`: `search-console` / `bing-webmaster`).
4. **Quality gates:** apply the location-page gates only to programmatic city / area pages, not to the hotels of the
   group (each hotel is a real place).
5. Sitemap settings changes (include / exclude post types) are `rankmath_setting` actions on the `sitemap` group
   (group-wide). Read the current values with `site_mcp_read(site, "seo-get-settings", {"group": "sitemap"})`.
"""
HOTEL['seo-performance'] = """
## Hotel-seo specifics

Scope: the whole group site, once; report per template and per hotel.

1. `seo_check("pagespeed_check.py", [url, "--strategy", "both", "--json"])` on: the homepage, each hotel's main page,
   one room page and one offer page per hotel. Field data (CrUX) first; lab only as fallback, labelled as lab.
2. `seo_check("crux_history.py", [origin, "--origin", "--form-factor", "PHONE", "--json"])` for the 25-week trend;
   `seo_check("lcp_subparts.py", [url, "--json"])` on the homepage when CrUX has it.
3. The LCP element and the hero image (size, format, `fetchpriority`, lazy-loading) from `render_page.py`
   (`--mode always`) and `inspect_pages`; third-party scripts (GTM containers, chat widgets, booking widgets).
4. Speed engineering is `owner: "web"` (Web Team List). Image replacement / compression of specific files can be
   `owner: "seo"` when it is a media-library job.
5. `scores.performance` = 0-100 with pass / fail per metric (LCP, INP, CLS) at the 75th percentile. Never FID.
"""
HOTEL['seo-agentic'] = """
## Hotel-seo specifics

Scope: the whole group site, once. Agents that book hotels (AI Mode and others) must be able to reach a hotel's
rooms, offers and the booking button.

1. `seo_check("lighthouse_agentic.py", [site, "--strategy", "both", "--json"])`,
   `seo_check("agentic_check.py", [site, "--json"])` (no `--ua-matrix` unless the user authorised it),
   `seo_check("agent_ux_check.py", [url, "--json"])` on the homepage and one hotel page with its Book Now button.
2. Map priorities to severity: P0 → High (Critical only when the booking button is unreachable for agents), P1 →
   Medium, P2 → Low, P3 → Info. Category `AI Search`.
3. `scores.lighthouse_agentic` = `{"score": "X/N", ...}` (never a percentage); `scores.agent_ux` separate.
4. robots.txt / llms.txt / server changes are `owner: "web"`; use `seo_check("agentic_fix.py", ...)` output as the
   paste-ready draft in `blocks`.
"""
HOTEL['seo-backlinks'] = """
## Hotel-seo specifics

Scope: the group domain, once (backlinks are per domain). Note links that point at a specific hotel's pages.

1. Credentials: `seo_check("backlinks_auth.py", ["--check", "--json"])`. Bing data comes from hotel-seo's
   `bing_report(site, out_dir)` (already set up on this machine), not bing_webmaster.py.
2. Common Crawl: `seo_check("commoncrawl_graph.py", [domain, "--json"], background=true)` then `job_status`.
3. Moz (when the key is set): `moz_api.py metrics / domains / anchors / pages` for the domain (1 call per 10 s).
4. Links from sister hotels or an old operator's site are worth naming (playbook lesson).
5. Save the collected data and run `seo_check("validate_backlink_report.py", ["--report", <file>, "--json"])` before
   finishing; fix what it reports. `scores.backlinks` is "insufficient data" unless 4 of the 7 factors have data.
6. Backlink work is outreach, not site edits: `owner: "seo"`, `actions: []`.
"""
HOTEL['seo-content'] = """
## Hotel-seo specifics

Scope: ONE hotel (`hotel:<slug>`) — its pages from `partition.json`. Model: Opus. You write the copy the hotel's
pages should carry; facts follow the [CONFIRM] rule.

1. **Start from the code.** `content-scan.json` (every page: words vs floor, content quality, templated metadata),
   `findings.json` issues for this hotel's URLs, `keyword-map.json` (the non-brand cluster each page should target).
2. **Every key page** (home, rooms index, each room, offers, dining, spa, meetings, location / getting here, contact):
   E-E-A-T, readability, depth vs floor, keyword alignment (the page's cluster in title, H1 and first 100 words),
   freshness, AI-generated-quality markers. Read the page text with `read_crawl_file(<crawl>/site_text.json)` (filter
   by URL) and render it when needed.
3. **On-Page rewrites for every page that needs one:** exact new title (≤ ~60 chars), meta (≤155), H1 — as findings
   that restate the core checks (`title_missing`, `title_too_long`, `meta_missing`, `meta_too_long`, `h1_missing`,
   `h1_multiple`) with `seo_fields` actions (title, description) and `elementor_text` actions for H1s (set `template:
   true` when the heading comes from a shared card / loop template). Read current Rank Math values with
   `site_mcp_read(site, "seo-get-posts", {"post_ids": [...]})` when the site is in sites.csv.
4. **Credibility copy:** restate `phone_country_code`, `other_city_in_heading`, `out_of_season_wording`,
   `old_year_in_title`, `page_empty` with the exact replacement text (verify each on the live page first: the phone
   check catches WhatsApp and booking numbers, so confirm which are wrong).
5. **Thin pages:** for each page below its floor, write the paste-ready copy to add (in `blocks` → `paste`).
6. **Images:** don't write per-image alt actions here: the orchestrator writes alt for **every** image without alt
   (`alt_text_worklist` after the report is assembled). Report the finding's pattern (which templates / widgets
   leave alt empty, logos, sliders) and the duplicate-alt cases you see. Never generic alt text.
7. **Blog → booking:** the busiest posts with no room / booking link get the booking paragraph (`paste`) with the
   standard booking link.
8. `scores.content_quality` 0-100 and the E-E-A-T breakdown in the `.md`; checks per page in `checks`.
"""
HOTEL['seo-schema'] = """
## Hotel-seo specifics

Scope: ONE hotel. Every JSON-LD block on its pages must be accounted for.

1. From `findings.json` → `report.schema.blocks` (every distinct block, its pages, flags) and `jsonld_invalid` issues.
   Validate the blocks on this hotel's pages with `seo_check("render_page.py", [url, "--mode", "always",
   "--json-ld-output", <file>, "--json"])` (raw vs rendered).
2. For each block: Keep / Fix / Delete / Homepage-only, with the reason (self-written reviews, duplicate LocalBusiness
   with another name, Organization duplicates, OTA links in sameAs, invalid JSON, deprecated types).
3. Write the corrected **Hotel** block for this hotel (hotel-addendum.md field list; facts only from the facts file or
   the live site; [CONFIRM] otherwise), plus Organization / WebSite / BreadcrumbList as needed. Give it as a `code`
   block and as a `schema_snippet` action with `conditions` naming the page, e.g. `["page:<hotel main page URL>"]`
   (execute turns that into the Elementor display condition). `code` is the JSON-LD object or the complete
   `<script type="application/ld+json">...</script>` block and nothing else: valid JSON, with "@context". Execute
   refuses anything else, because Elementor Custom Code prints the code as it is (bare JSON shows on the page as
   text). Schema never goes in page copy, `post_content`, `elementor_text` or `text_replace`. Existing snippets: `site_mcp_read(site,
   "elementor-list-custom-code", {})` to find the one to replace (`replace_snippet_id`).
4. Restate `jsonld_invalid` with the exact fixed block. FAQPage is Info only; never HowTo / SpecialAnnouncement.
"""
HOTEL['seo-geo'] = """
## Hotel-seo specifics

Scope: ONE hotel. Model: Opus. Guests ask AI assistants "best hotel near X with Y" — and AI Mode can now book hotels
through partners, so being citable and reachable matters for direct bookings.

1. robots.txt access per AI crawler, by what it governs (training vs search vs user-triggered). robots.txt is
   site-wide: report it with `hotel: "group"` (it is merged once across hotels).
2. Citability of the hotel's key pages from `extracted_text` (render_page): self-contained answer blocks, direct
   answers in the first 40–60 words, question headings, specific facts (only confirmed facts).
3. Questions to answer: the informational clusters in `keyword-map.json` (getting from the airport, things to do
   near the hotel, parking, check-in...). Write the paste-ready answer blocks (`paste`) for the pages they belong on.
4. llms.txt status (optional for Google; report, don't over-weight). Brand / entity signals (Wikipedia, Reddit,
   YouTube, Tripadvisor) via WebFetch where reachable — say what you could not check.
5. `scores.geo` 0-100 with the five dimensions in the `.md`. Category `AI Search`.
"""
HOTEL['seo-local'] = """
## Hotel-seo specifics

Scope: ONE hotel (brick-and-mortar). Hotels are not one of claude-seo's six verticals: use hotel-addendum.md for the
vertical (category, citations, schema).

1. **NAP table** (one row per source): the hotel's contact page, its JSON-LD, Booking.com (facts file, source
   "Booking.com"), the booking engine (facts file), and the Google Maps link / embed on the site. Every mismatch is a
   finding (name = Critical, address = High, phone = Medium), with the exact correction [CONFIRM] where needed.
2. GBP signals on the page (Maps embed, place link, reviews widget), review signals (score / count on Booking.com,
   self-written `aggregateRating` → schema agent), local on-page (city / area in titles and H1s, a location / getting
   here page, `tel:` link).
3. Citations: check presence (WebFetch) on Tripadvisor, Booking.com, Expedia / Hotels.com, Bing Places, Apple — say
   which could not be checked.
4. `scores.local` 0-100 with claude-seo's dimension breakdown in the `.md`. Category `Local`. Business Profile fixes
   are `gbp` actions (`owner: "seo"`; `field` website / phone / regular_hours / special_hours /
   additional_categories / attributes, `value` as gbp_propose takes it, confirmed facts only; never name, address or
   primary category): execute's business-profile batch, made by MetaHotels after approval. **No description:** Google
   doesn't allow a business description on hotel profiles; never propose or list one.
"""
HOTEL['seo-maps'] = """
## Hotel-seo specifics

Scope: ONE hotel. Tier 0 (no DataForSEO): no geo-grid — redistribute its weight as claude-seo says.

1. `geo_lookup` the hotel's address (facts file / schema) and compare with the schema `geo` and the Maps link
   (distance in metres; > 50 m is a finding).
2. `nearby_places(lat, lon, 3000, ["hotel"])` for the competitor landscape (count, names, stars where OSM has them) and
   `["airport", "metro_station", "mall", "beach", "attraction", "venue"]` for the landmarks the location page should
   mention (distances are approximate — label them, and [CONFIRM] before they go into copy).
3. The GBP checklist from visible data (maps-gbp-checklist.md), including the booking link field.
4. Cross-platform presence (Bing, Apple, OpenStreetMap — is the hotel a named node / way near its coordinates?).
5. `scores.maps` 0-100 (Tier 0 weights). Category `Maps`. Profile fixes are `gbp` actions
   (as in seo-local: field + value; never name, address or primary category), for execute's business-profile batch.
"""
HOTEL['seo-flow'] = """
## Hotel-seo specifics

Scope: ONE hotel and ONE stage per call (`find`, `local`, `optimize` or `win`; the orchestrator runs all four). Your
output feeds the **Build Plan** (pages, copy, priorities); it is not scored.

1. Read the prompt files of your stage (`prompts/<stage>/`); for `optimize` pick the 2–3 that fit this hotel's signals.
   At most 5 prompts.
2. Fill each prompt with this hotel's evidence: facts file, keyword map (real volumes), the hotel's pages
   (`read_crawl_file` on site_text.json), audit findings. Never invent numbers; say which evidence is missing.
3. Write `<run_dir>/findings/seo-flow-<stage>.md` and `.json`:
   `{"agent": "seo-flow", "scope": "hotel:<slug>", "stage": "<stage>", "status": "complete", "credit": "Framework and
   prompts © Daniel Agrici, CC BY 4.0: github.com/AgriciDaniel/flow", "prompts_applied": [{"file", "why"}],
   "outputs": [{"prompt", "result", "evidence_needed", "build_plan_items": ["..."]}]}`.
4. The credit line "Framework and prompts © Daniel Agrici, CC BY 4.0: github.com/AgriciDaniel/flow" goes at the top of
   the `.md` and in the JSON.
5. Validate with `validate_agent_output(run_dir, "seo-flow-<stage>", scope, crawl_dir, group_dir)`.
"""

DROP = ('## Persistence Contract', '## Audit Persistence', '## DataForSEO Integration', '## Cross-Skill Delegation',
        '## Fetching pages', '## Pre-Delivery Review')


def cmd(m):
    script, args = m.group(1), m.group(2).strip()
    parts = re.findall(r'"[^"]*"|\'[^\']*\'|\S+', args) if args else []
    return 'seo_check("%s", [%s])' % (script, ', '.join('"%s"' % p.strip('"\'') for p in parts))


def rewrite(text):
    text = re.sub(r'"?\$\{CLAUDE_PLUGIN_ROOT\}/scripts/claude-seo"?\s+run\s+([a-z_]+\.py)([^\n`|]*)', cmd, text)
    for a, b in {'skills/seo/references/': 'skills/hotel-seo/references/claude-seo/seo/',
                 'skills/seo-technical/references/': 'skills/hotel-seo/references/claude-seo/technical/',
                 'skills/seo-geo/references/': 'skills/hotel-seo/references/claude-seo/geo/',
                 'skills/seo-agentic/references/': 'skills/hotel-seo/references/claude-seo/agentic/',
                 'skills/seo-schema/references/': 'skills/hotel-seo/references/claude-seo/schema/',
                 'skills/seo-flow/references/': 'skills/hotel-seo/references/claude-seo/flow/'}.items():
        text = text.replace('${CLAUDE_PLUGIN_ROOT}/' + a, '${CLAUDE_PLUGIN_ROOT}/' + b)
    text = text.replace('${CLAUDE_PLUGIN_ROOT}/schema/templates.json',
                        '${CLAUDE_PLUGIN_ROOT}/server/hotel_seo_tools/vendor/claude_seo/schema/templates.json')
    return text


def body_of(md):
    fm_end = md.index('\n---', 3)
    body = md[fm_end + 4:]
    parts = re.split(r'(?m)^(## .+)$', body)
    out = parts[0]
    for i in range(1, len(parts), 2):
        head, txt = parts[i], parts[i + 1]
        if head.startswith(DROP):
            continue
        out += head + txt
    return rewrite(out).strip()


FIXES = [
    ('- If no sources return data, report: "No backlink data available. Run `/seo backlinks setup`."',
     '- If no sources return data, report: "No backlink data available" and name the missing keys (MOZ_API in the work folder .env, hotel-seo-bing-login).'),
    ('- If all free sources fail, suggest DataForSEO extension: `./extensions/dataforseo/install.sh`',
     '- DataForSEO is not set up in hotel-seo: report what the free sources could not cover.'),
    ('1. Detect capability tier: check if DataForSEO MCP tools are available (try `business_data_business_listings_search`). If available = Tier 1. If not = Tier 0 (free APIs only).',
     '1. Capability tier: hotel-seo runs **Tier 0** (free APIs only; DataForSEO is not set up). Use `geo_lookup` and `nearby_places` for Nominatim / Overpass / Geoapify.'),
]


def fix(text):
    for a, b in FIXES:
        text = text.replace(a, b)
    text = chr(10).join(l for l in text.split(chr(10)) if not l.strip().startswith('npx lighthouse'))
    return text


def desc_of(md):
    m = re.search(r'(?m)^description:\s*(.+)$', md)
    return m.group(1).strip().strip('"') if m else ''


for name, cfg in AGENTS.items():
    src = (SRC / 'agents' / f'{name}.md').read_text(encoding='utf-8')
    tools = list(COMMON_TOOLS) + cfg['extra'] + (['WebFetch'] if cfg['web'] else [])
    if name == 'seo-flow':
        tools = ['Read', 'Write', 'Grep', 'Glob', 'WebFetch', P + 'read_crawl_file', P + 'validate_agent_output']
    refs = '\n'.join(f'- `{r}`' for r in cfg['refs'])
    scope_line = ('per site: the whole group domain, once' if cfg['scope'] == 'site'
                  else 'per hotel: one hotel of the group per call')
    out = f"""---
name: {name}
description: "{cfg['title']} for hotel-seo ({scope_line}). {desc_of(src)} Ported from claude-seo (MIT) with hotel rules; started by /hotel-seo with an input block, writes findings/{name}.json."
model: {cfg['model']}
maxTurns: {cfg['turns']}
tools: {', '.join(tools)}
---

<!-- Ported from claude-seo v2.5.0 agents/{name}.md (MIT, (c) 2026 agricidaniel). Adapted for hotel-seo: scripts run
through the seo_check tool, hotel rules from hotel-addendum.md win, output follows agent-contract.md. -->

# {cfg['title']} ({name}) — hotel-seo

You run {scope_line} during a hotel-seo audit.

## Before you start (read these first)

- `{REF}/agent-contract.md` — inputs, the output files and the rules your output is validated against.
- `{REF}/hotel-addendum.md` — MetaHotels' hotel rules; they win over the claude-seo references below.
{refs}

Scripts: every `seo_check("<script>.py", [args])` below is the hotel-seo MCP tool `seo_check` with those arguments.
Pages: render with `seo_check("render_page.py", [url, "--mode", "auto", "--json"])` (`--mode always` for JS-built
pages); large output is saved to a file you read with `read_crawl_file`. Never fetch with your own HTTP code.

## Method (claude-seo)

{fix(body_of(src))}
{HOTEL[name]}
## Output and finish

Follow `agent-contract.md` exactly:
1. Write `<run_dir>/findings/{name}{'-<stage>' if name == 'seo-flow' else ''}.json` (`"status": "partial"`) and
   `.md` after your first pass; overwrite both at the end (`"status": "complete"`).
2. Every check you ran in `checks`; every page in `coverage`; every affected URL in each finding; exact fixes;
   re-check `checks` and execute `actions` per finding (owner `seo`).
3. Call `validate_agent_output` and fix every error until it returns `valid: true`. Then reply with one line: the
   number of findings by severity and anything you could not assess.
"""
    (DST / f'{name}.md').write_text(out, encoding='utf-8')
    print('wrote', name, len(out))
