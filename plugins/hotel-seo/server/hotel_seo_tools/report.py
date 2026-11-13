"""Audit report assembly: core checks (audit_site, booking engine, facts) + the 11 agents' findings -> one Audit
Report, one Web Team List per hotel and a Group Summary. Every score is computed here, in code.

Where things live (group_dir = <domain>/; see group.hotel_dir / site_dir):
  Group site:
    group/audit-<date>/findings/<agent>.json          per-site agents (technical, sitemap, performance, agentic, backlinks)
    hotels/<slug>/audit-<date>/findings/<agent>.json  per-hotel agents (content, schema, local, maps, geo, flow-*)
    hotels/<slug>/audit-<date>/audit-report.json, web-team.json, audit-data.json   written here
    group/audit-<date>/group-summary.json             written by build_group()
  Single-hotel site: all of it in audit-<date>/ directly under <domain>/; no Group Summary.

Scoring (user decision): claude-seo's seven categories scaled to 85% + "Booking path & facts" at 15%.
Category score = sum of severity weights of passed checks / sum over measured checks (Critical 4, High 3,
Medium 2, Low 1, Info 0); not_measured checks are left out; a category with nothing measured drops out and the
remaining weights are rescaled. Local, Maps, Backlinks, GEO, Lighthouse agentic X/N and Agent-UX are shown next to
the Health Score, not in it.

Trust rules (binding, in code):
  - An agent's findings and checks are used only when <run>/agent-status.json (written by validate_agent_output)
    says it validated (complete / partial) and the file has not changed since. Anything else (invalid, not
    assessed, missing record, edited after validation, broken JSON) is left out and the agent shows as
    "not assessed: <reason>"; expected agents with no output show as "not assessed: did not run".
  - Coverage: the share of the weighted categories backed by measured checks. Below COVERAGE_MIN the Health Score
    is "not scored" (the rescaled number is kept as health_raw, never shown as the score).
  - One failing Critical check from BOOKING_PATH_CRITICAL caps the Health Score at HEALTH_CAP; two or more distinct
    ones make it "Blocked" (no number).
"""
import csv
import hashlib
import json
import re
from collections import defaultdict
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from . import group as grp, paths

WEIGHTS = {'Booking path & facts': 15, 'Technical': 18.7, 'Content': 19.55, 'On-Page': 17, 'Schema': 8.5,
           'Performance': 8.5, 'AI Search': 8.5, 'Images': 4.25}
SEPARATE = ['Local', 'Maps', 'Backlinks']
SEV_RANK = {'Critical': 0, 'High': 1, 'Medium': 2, 'Low': 3, 'Info': 4}
SEV_WEIGHT = {'Critical': 4, 'High': 3, 'Medium': 2, 'Low': 1, 'Info': 0}
CRITICAL_TYPES = {'home', 'rooms', 'offers', 'contact', 'booking'}
SITE_AGENTS = ['seo-technical', 'seo-sitemap', 'seo-performance', 'seo-agentic', 'seo-backlinks']
HOTEL_AGENTS = ['seo-content', 'seo-schema', 'seo-local', 'seo-maps', 'seo-geo', 'seo-flow-find', 'seo-flow-local',
                'seo-flow-optimize', 'seo-flow-win']
# Agents that add checks to each category (code checks come first, from audit_site / crawl / booking engine).
CATEGORY_AGENTS = {'Booking path & facts': [], 'Technical': ['seo-technical', 'seo-sitemap'],
                   'Content': ['seo-content'], 'On-Page': ['seo-content'], 'Schema': ['seo-schema'],
                   'Performance': ['seo-performance'], 'AI Search': ['seo-geo', 'seo-agentic'],
                   'Images': ['seo-content'], 'Local': ['seo-local'], 'Maps': ['seo-maps'],
                   'Backlinks': ['seo-backlinks']}
CHAPTER_ORDER = ['Booking path & facts', 'Technical', 'Content', 'On-Page', 'Schema', 'Performance', 'AI Search',
                 'Images', 'Local', 'Maps', 'Backlinks']
# Agent statuses in agent-status.json whose output may reach the client.
VALID_AGENT_STATUSES = ('complete', 'partial')
# Health Score is "not scored" when its measured checks cover less than this share (%) of the category weights.
COVERAGE_MIN = 70
# One failing check below caps the Health Score at HEALTH_CAP; two or more distinct ones -> "Blocked".
# value True = it counts only when a key page (CRITICAL_TYPES) is affected. Critical checks of the core table that
# break the way guests reach the booking engine: dead / wrong-hotel book links, key pages out of Google.
HEALTH_CAP = 59
BOOKING_PATH_CRITICAL = {
    'core:booking_link_dead': False,
    'core:booking_link_other_hotel': False,
    'core:noindex_on_key_page': False,          # key pages by definition
    'core:canonical_broken': True,              # only when it hits the home, room, offer, contact or booking page
}

# audit_site check -> (category, base severity, finding title, generic fix, re-check builder)
CORE = {
    'canonical_broken': ('Technical', 'Critical', 'Canonical points to a redirect or a missing page',
                         'Rank Math → (page) → Advanced → Canonical URL: empty it so the page is canonical to itself. '
                         'Then Search Console → URL Inspection → Request indexing.', 'canonical_self'),
    'canonical_other': ('Technical', 'Medium', 'Canonical points to another page',
                        'Check each page: if it is a real page, empty the canonical override (self-canonical); if it '
                        'is a duplicate, 301 it to the canonical URL instead.', 'canonical_self'),
    'canonical_missing': ('Technical', 'Low', 'No canonical tag',
                          'Turn on Rank Math for this post type (Titles & Meta) so every page prints a self-canonical.',
                          'canonical_self'),
    'noindex_on_key_page': ('Technical', 'Critical', 'Key page set to noindex',
                            'Rank Math → (page) → Advanced → Robots: clear "noindex" (leave the post type default).',
                            'noindex_false'),
    'booking_page_indexable': ('Technical', 'High', 'Booking-engine / account page can be indexed',
                               'Noindex these pages (Rank Math → Advanced → Robots: noindex) or block the booking step '
                               'URLs in robots.txt.', 'noindex_true'),
    'junk_page': ('Technical', 'Medium', 'Page created by mistake',
                  'Unpublish the page and 301 it to the closest real page.', 'status_404_or_redirect'),
    'link_broken': ('Technical', 'High', 'Broken links', 'Replace or remove each broken link (table below).',
                    'link_absent'),
    'h1_missing': ('On-Page', 'Medium', 'Page has no H1', 'Give the page one H1 that says what it is.', 'h1_count'),
    'h1_multiple': ('On-Page', 'Medium', 'Several H1s on a page',
                    'Keep one H1; change card / widget headings to H2 or H3 (one template change when they come '
                    'from a loop or card widget).', 'h1_count'),
    'title_missing': ('On-Page', 'High', 'Page has no title', 'Write a title (Rank Math → General → Title).',
                      'title_present'),
    'title_too_long': ('On-Page', 'Low', 'Title longer than 62 characters',
                       'Shorten to about 60 characters: [Keyword phrase] | [Hotel name].', 'title_max'),
    'meta_missing': ('On-Page', 'Medium', 'No meta description',
                     'Write a meta description of 155 characters or fewer: location + one product fact + Book direct.',
                     'meta_present'),
    'meta_too_long': ('On-Page', 'Low', 'Meta description longer than 155 characters',
                      'Shorten to 155 characters or fewer.', 'meta_max'),
    'jsonld_invalid': ('Schema', 'High', 'Invalid JSON-LD (Google ignores the whole block)',
                       'Fix the JSON syntax of the block (or replace it with the corrected block in the Schema '
                       'chapter).', 'jsonld_valid'),
    'booking_link_dead': ('Booking path & facts', 'Critical', 'Dead booking links',
                          'Replace each with the standard booking link https://<domain>/search/?idtokenprovider=<id>'
                          '&lang=en&currency=AED.', 'link_absent'),
    'booking_link_outdated': ('Booking path & facts', 'High', 'Outdated booking links (old step, past dates, '
                              'other currency)', 'Replace with the standard booking link (no dates, AED).',
                              'link_absent'),
    'booking_link_other_hotel': ('Booking path & facts', 'Critical', "Book links open another hotel's booking "
                                 'engine', "Change the idtokenprovider to this hotel's Mirai ID.", 'link_absent'),
    'old_year_in_title': ('Content', 'Low', 'Old year in title / H1 / URL', 'Remove or update the year (keep URLs).',
                          None),
    'out_of_season_wording': ('Content', 'Medium', 'Out-of-season wording', 'Replace with season-neutral wording.',
                              None),
    'other_city_in_heading': ('Content', 'High', 'Another city named in a heading',
                              "Change the heading to the hotel's own city / area.", None),
    'page_empty': ('Content', 'Medium', 'Empty or near-empty page', 'Add the real content or unpublish and 301.',
                   None),
    'phone_country_code': ('Content', 'High', 'Phone number with an odd country code',
                           "Use the hotel's real number with the right country code.", None),
    # v2.0.0 audit checks (AI search access, hreflang, snippets, offer markup, metas)
    'ai_search_bot_blocked': ('AI Search', 'Critical', 'robots.txt blocks an AI search crawler',
                              'Allow the search crawler in robots.txt (OAI-SearchBot, PerplexityBot, Claude-SearchBot, '
                              'Bingbot...): a blocked search crawler hides the whole site from that search. Training '
                              'crawlers (GPTBot, ClaudeBot, Google-Extended) are the owner\'s choice.', None),
    'snippet_blocked': ('AI Search', 'Medium', 'Page blocks search snippets (nosnippet / max-snippet)',
                        'Remove nosnippet / data-nosnippet or raise max-snippet (-1): it also keeps the page out of '
                        'AI Overviews and AI Mode.', None),
    'hreflang_no_return': ('Technical', 'Medium', "hreflang pair that doesn't link back",
                           'Each language version must list the other (and itself); Google ignores one-way pairs. '
                           'Polylang: link the EN and AR versions of the page (the language columns in Pages) so '
                           'both print the pair.', 'hreflang_ok'),
    'hreflang_bad_target': ('Technical', 'Medium', 'hreflang points to a redirect, 404, noindex or non-canonical page',
                            'Point each hreflang at the final, indexable, self-canonical URL of that language version.',
                            'hreflang_ok'),
    'hreflang_invalid_code': ('Technical', 'Medium', 'Invalid hreflang language code',
                              'Use ISO 639-1 language (+ optional ISO 3166-1 region) codes: en-GB not en-UK, ja not jp.',
                              'hreflang_ok'),
    'arabic_page_untranslated': ('Content', 'High', 'Arabic page (lang=ar) with no Arabic title, meta or H1',
                                 'Write the Arabic title, meta description and H1 (native Arabic, not machine '
                                 'translation), or noindex the page until it is translated.', None),
    'offer_schema_expired': ('Schema', 'Medium', 'Offer markup past its end date (validThrough / priceValidUntil)',
                             'Update the dates to the live offer, or remove the Offer markup when the offer has ended.',
                             None),
    'meta_equals_title': ('On-Page', 'Low', 'Meta description repeats the title',
                          'Write a meta description of 155 characters or fewer that adds what the title does not: '
                          'location, one product fact, Book direct.', None),
    # site_checks.py (registry 1.7): link graph, hreflang sets, boilerplate, link previews, headings, anchors, URL
    # variants. Each issue carries its own re-check (issue['recheck']); the last field names its type.
    'orphan_key_page': ('Technical', 'High', 'Room, offer, dining, spa or meeting page that no page links to (orphan)',
                        "Link each page from its section page (Rooms, Offers, Dining...) and the hotel's menu or main "
                        "page, with the page's name as the anchor. If it is out of date, unpublish it and 301 it to "
                        'the section page instead.', 'inlinked'),
    'orphan_page': ('Technical', 'Medium', 'Page that no page links to (orphan: found only in the sitemap or WordPress)',
                    'Link it from the most relevant page with a descriptive anchor; if nobody needs it, unpublish it '
                    'and 301 it to the closest live page (it then drops out of the sitemap).', 'inlinked'),
    'key_page_too_deep': ('Technical', 'Medium', "Key page more than 3 clicks from the hotel's main page",
                          "Link the page from the hotel's main page or its section page (menu, a card on the Rooms / "
                          "Offers page) so it is at most 3 clicks from the hotel's main page.", 'click_depth'),
    'hreflang_incomplete': ('Technical', 'Medium', 'EN/AR hreflang set incomplete (missing language version, '
                            'self-reference or x-default)',
                            'Polylang → Pages: link the English and Arabic versions of each page (the language '
                            'columns); Polylang then prints the same set on both, each listing itself. Create the '
                            'missing translation where a key page has none (written in Arabic, not machine-translated). '
                            'Give the home page an x-default that points to the English home.', 'hreflang_ok'),
    'boilerplate_shared': ('Content', 'Medium', 'Same sentences on many room / offer / area pages (name-swapped copy)',
                           'Rewrite the listed sentences on each page with what is specific to that room, offer or '
                           'place (size, view, bed, inclusions, distance: content-writing.md). Shared facts such as '
                           'check-in times or policies go on one page that the others link to.', 'text_absent'),
    'link_preview_missing': ('On-Page', 'Medium', 'No link preview (og:title / og:image): WhatsApp and social shares '
                             'show no picture or title',
                             'Rank Math → (page) → Social: set the title and image (1200 × 630, a JPG or WebP that '
                             'loads); set a default in Rank Math → Titles & Meta → Global Meta → OpenGraph Thumbnail. '
                             'Paste the URL into WhatsApp to check the preview.', 'og_present'),
    'heading_level_skipped': ('On-Page', 'Low', 'Heading levels skipped (e.g. H2 straight to H4)',
                              "In Elementor, change the heading widget's HTML tag so levels go down one step at a time "
                              '(H2 → H3 → H4); the look comes from the widget style, not the tag.', 'heading_levels'),
    'heading_empty': ('On-Page', 'Low', 'Empty headings (heading tags with no text)',
                      'Delete the empty Elementor heading widgets, or set their HTML tag to div / p when they only hold '
                      'spacing or an icon.', 'heading_levels'),
    'generic_anchor_text': ('On-Page', 'Low', 'Internal links with generic text ("Read more", "Click here")',
                            'Change the link / button text to say where it goes ("Deluxe King Room", "See the '
                            'Ramadan offer"); on Elementor loop cards, take the button text from the post title.',
                            'generic_anchors_max'),
    'url_variant_duplicate': ('Technical', 'Medium', 'Same page answers at a case or trailing-slash variant (no '
                              'redirect or canonical)',
                              'Redirect each variant with a 301 to the main address (one rule: lowercase, one '
                              'trailing-slash style) and keep the self-canonical on the main page.', 'variant_resolved'),
}
# core checks the Web Team fixes (server or theme work, registry rule 1.2.3); the rest go to the SEO agency
# hreflang is printed by the theme / Polylang settings, not per post: a developer item, never agency or execute work
WEB_OWNED = {'url_variant_duplicate', 'hreflang_no_return', 'hreflang_bad_target', 'hreflang_invalid_code',
             'hreflang_incomplete'}


def _sev_max(a, b):
    return a if SEV_RANK[a] <= SEV_RANK[b] else b


def floor(sev, page_types, check=''):
    """Severity floor: key pages and the booking path are never below High."""
    if page_types & CRITICAL_TYPES and SEV_RANK[sev] > SEV_RANK['High']:
        return 'High'
    return sev


def _recheck(kind, url, detail=''):
    if kind in ('canonical_self', 'title_present', 'meta_present', 'jsonld_valid'):
        return {'type': kind, 'url': url}
    if kind == 'title_max':
        return {'type': 'title_max', 'url': url, 'expected': 62}
    if kind == 'meta_max':
        return {'type': 'meta_max', 'url': url, 'expected': 155}
    if kind == 'h1_count':
        return {'type': 'h1_count', 'url': url, 'expected': 1}
    if kind == 'noindex_false':
        return {'type': 'noindex', 'url': url, 'expected': False}
    if kind == 'noindex_true':
        return {'type': 'noindex', 'url': url, 'expected': True}
    if kind == 'link_absent':
        m = re.search(r'->\s*(\S+)', detail or '')
        return {'type': 'link_absent', 'url': url, 'href': m.group(1)} if m else None
    return None


def core_findings(crawl_dir, reg, slug):
    """audit_site issues for one hotel (or 'group'), one finding per check listing every URL."""
    f = paths.resolve(crawl_dir) / 'findings.json'
    if not f.exists():
        return [], []
    fj = json.loads(f.read_text(encoding='utf-8'))
    by_check = defaultdict(list)
    for i in fj.get('issues', []):
        owner = grp.hotel_for(i['url'], reg) if reg else slug
        if owner == slug:
            by_check[i['check']].append(i)
    findings, checks = [], []
    for check, (cat, sev, title, fix, rk) in CORE.items():
        items = by_check.get(check, [])
        if check == 'link_broken' and any('[sitewide]' in i['detail'] for i in items):
            sev = 'Critical'
        types = ({i['page_type'] for i in items} | {_page_type_guess(i['url'], reg) for i in items}) if items else set()
        checks.append({'id': f'core:{check}', 'category': cat, 'title': title,
                       'result': 'fail' if items else 'pass', 'severity': sev, 'source': 'audit_site',
                       'key_page': bool(types & CRITICAL_TYPES)})
        if not items:
            continue
        sev = floor(sev, types)
        urls = sorted({i['url'] for i in items})
        rows = [[i['url'], i['detail']] for i in sorted(items, key=lambda x: x['url'])]
        # an issue's own re-check (site_checks, hreflang) wins over the one built from its detail; one per page
        rchecks = [c for c in (i.get('recheck') or (_recheck(rk, i['url'], i['detail']) if rk else None)
                               for i in items) if c]
        rchecks = list({json.dumps(c, sort_keys=True): c for c in rchecks}.values())
        findings.append({
            'id': f'core-{check}', 'check': check, 'category': cat, 'title': title, 'severity': sev,
            'hotel': slug, 'owner': 'web' if check in WEB_OWNED else 'seo', 'count': len(items), 'pages': urls,
            'evidence': {'summary': f'{len(items)} occurrence(s) on {len(urls)} page(s)', 'tool': 'audit_site'},
            'fix': fix, 'blocks': [{'table': {'columns': ['Page', 'What audit_site found'], 'rows': rows}}],
            'checks': rchecks, 'actions': []})
    # images missing alt (crawl file), per hotel
    alt = paths.resolve(crawl_dir) / 'images_missing_alt.csv'
    if alt.exists():
        with open(alt, encoding='utf-8-sig', newline='') as fh:
            rows = [r for r in csv.DictReader(fh) if (grp.hotel_for(r['page_url'], reg) if reg else slug) == slug]
        checks.append({'id': 'core:images_missing_alt', 'category': 'Images', 'title': 'Images without alt text',
                       'result': 'fail' if rows else 'pass', 'severity': 'Medium', 'source': 'crawl'})
        if rows:
            findings.append({
                'id': 'core-images-missing-alt', 'check': 'images_missing_alt', 'category': 'Images',
                'title': 'Images without alt text', 'severity': 'Medium', 'hotel': slug, 'owner': 'seo',
                'count': len(rows), 'pages': sorted({r['page_url'] for r in rows}),
                'evidence': {'summary': f"{len(rows)} image(s) on {len({r['page_url'] for r in rows})} page(s) "
                                        'have no or empty alt text', 'tool': 'LibreCrawl crawl'},
                'fix': 'Write alt text for each image after looking at it (seo-content gives the exact text).',
                'blocks': [{'table': {'columns': ['Page', 'Image', 'Alt'],
                                      'rows': [[r['page_url'], r['image_src'], r['alt_state']] for r in rows]}}],
                'checks': [{'type': 'alt_present', 'url': r['page_url'], 'image': r['image_src'].rsplit('/', 1)[-1]}
                           for r in rows], 'actions': []})
    # security -> Web Team (site-wide, reported on the group, and on a one-hotel site)
    if slug == 'group' or (reg and len(reg.get('hotels', [])) == 1):
        for n, s in enumerate(fj.get('security', [])):
            findings.append({'id': f'core-security-{n + 1}', 'check': 'security', 'category': 'Technical',
                             'subcategory': 'Security', 'title': 'Security: ' + s.split(':')[0][:90],
                             'severity': 'Critical', 'hotel': slug, 'owner': 'web', 'count': 1, 'pages': [],
                             'evidence': {'summary': s, 'tool': 'audit_site (WordPress REST, Search Console)'},
                             'fix': 'Find what creates the posts / opens the route, check admin users, run a malware '
                                    'scan, rotate passwords; remove leftovers named above.', 'checks': [],
                             'actions': []})
        checks.append({'id': 'core:security', 'category': 'Technical', 'title': 'No security red flags',
                       'result': 'fail' if fj.get('security') else 'pass', 'severity': 'Critical',
                       'source': 'audit_site'})
    return findings, checks


def booking_findings(hotel_dir, slug):
    """Booking engine vs site (booking_engine.json) and Booking.com vs engine (facts-conflicts.json)."""
    findings, checks = [], []
    hd = paths.resolve(hotel_dir)
    snaps = sorted(hd.rglob('booking_engine.json'), key=lambda p: p.stat().st_mtime)
    if snaps:
        be = json.loads(snaps[-1].read_text(encoding='utf-8'))
        cmp = be.get('website_vs_engine') or {}
        summ = be.get('summary') or {}
        engine_member = set(summ.get('member_discount_pct') or [])
        size_bad = [r for r in cmp.get('rooms', []) if r.get('site_page') and r.get('engine_size')
                    and r.get('size_on_page') is False and r.get('sizes_on_page')]
        member_bad = [m for m in cmp.get('member_discount_on_site', []) if engine_member and m['pct'] not in engine_member]
        groups = [
            ('offers_without_page', 'Packages the booking engine sells with no page on the site', 'Medium',
             'Create a page per package (the Build Plan has the copy): what the engine sells is the confirmed fact.',
             cmp.get('offers_without_page') or [], lambda x: [x.get('rate', ''), x.get('discount_range', '')],
             ['Package / rate on the engine', 'Discount'], lambda x: None),
            ('offer_pages_without_rate', 'Offer pages for offers the booking engine no longer sells', 'High',
             'Unpublish each expired offer page and 301 it to /offers/ (dining and spa offers excepted).',
             cmp.get('offer_pages_without_rate') or [], lambda x: [x], ['Offer page'], lambda x: x),
            ('room_size_mismatch', 'Room sizes on the site differ from the booking engine', 'High',
             'Use the booking-engine sizes on the room pages: the engine /search page is right unless the hotel '
             'says otherwise in the Rooms sheet (execute makes the change in the booking-path batch).',
             size_bad, lambda x: [x['room'], x.get('engine_size', ''), ', '.join(x.get('sizes_on_page') or []),
                                  x.get('site_page', '')], ['Room', 'Engine', 'On the page', 'Page'],
             lambda x: x.get('site_page')),
            ('member_discount_mismatch', 'Member discount on the site differs from the booking engine', 'High',
             'Align the loyalty / member wording with the engine (the engine is right). Execute never changes a '
             'discount: change the wording by hand.', member_bad,
             lambda x: [x['url'], f"{x['pct']}%", ', '.join(f'{p}%' for p in sorted(engine_member)), x['context']],
             ['Page', 'Site says', 'Engine gives', 'Context'], lambda x: x['url']),
        ]
        for key, title, sev, fix, items, row, cols, url_of in groups:
            checks.append({'id': f'booking:{key}', 'category': 'Booking path & facts', 'title': title,
                           'result': 'fail' if items else 'pass', 'severity': sev, 'source': 'booking_engine_snapshot'})
            if not items:
                continue
            urls = sorted({u for u in (url_of(x) for x in items) if u})
            f = {'id': f'booking-{key}', 'check': key, 'category': 'Booking path & facts', 'title': title,
                 'severity': sev, 'hotel': slug, 'owner': 'seo', 'count': len(items), 'pages': urls,
                 'evidence': {'summary': f'{len(items)} item(s), booking engine read on {be.get("checked", "")}',
                              'tool': 'booking_engine_snapshot'},
                 'fix': fix, 'blocks': [{'table': {'columns': cols, 'rows': [row(x) for x in items]}}],
                 'checks': [{'type': 'status', 'url': u, 'expected': 301} for u in urls]
                 if key == 'offer_pages_without_rate' else [], 'actions': []}
            # no hold: the booking engine is the source of truth (the hotel overrides it only in the Rooms sheet)
            findings.append(f)
    cf = hd / 'facts-conflicts.json'
    if cf.exists():
        conf = json.loads(cf.read_text(encoding='utf-8')).get('conflicts', [])
        real = [c for c in conf if c.get('kind') != 'cancellation_wording']
        checks.append({'id': 'facts:bookingcom_vs_engine', 'category': 'Booking path & facts',
                       'title': 'Booking.com agrees with the booking engine', 'result': 'fail' if real else 'pass',
                       'severity': 'High', 'source': 'crosscheck_facts'})
        if conf:
            findings.append({'id': 'facts-bookingcom-conflicts', 'check': 'facts_conflict',
                             'category': 'Booking path & facts', 'title': 'Booking.com and the booking engine disagree',
                             'severity': 'High' if real else 'Low', 'hotel': slug, 'owner': 'seo',
                             'count': len(conf), 'pages': [],
                             'evidence': {'summary': (f'{len(real)} room fact conflict(s)' if real else
                                                      'Room sizes and occupancy agree') +
                                                     '; cancellation wording to compare by hand',
                                          'tool': 'crosscheck_facts'},
                             'fix': 'The booking engine is right: correct Booking.com (extranet) to the booking engine '
                                    'value. The site already follows the engine.',
                             'blocks': [{'table': {'columns': ['What', 'Booking engine', 'Booking.com'],
                                                   'rows': [[c.get('kind', '') + (': ' + c.get('room_engine', '')
                                                                                  if c.get('room_engine') else ''),
                                                             str(c.get('engine')), str(c.get('bookingcom'))]
                                                            for c in conf]}}],
                             'checks': [], 'actions': [{'type': 'chrome', 'where': 'Booking.com extranet', 'steps': [
                                 'admin.booking.com, signed in for this property (never type a password)',
                                 'Property → Property page / Rooms: for each row below set the Booking.com value to '
                                 'the booking engine value'] + [
                                 f"{c.get('kind', '')}{(': ' + c['room_bookingcom']) if c.get('room_bookingcom') else ''}"
                                 f" → {c.get('engine')}" for c in real] + ['Save each room.']}] if real else []})
    return findings, checks


def _agent_files(d):
    out = {}
    fd = paths.resolve(d) / 'findings'
    if fd.exists():
        for f in fd.glob('*.json'):
            if f.stem.startswith('seo-flow'):
                continue                    # FLOW output feeds the Build Plan; it is not scored
            try:
                data = json.loads(f.read_text(encoding='utf-8'))
                out[f.stem] = data if isinstance(data, dict) else {'_invalid': 'not a JSON object'}
            except ValueError as e:
                out[f.stem] = {'_invalid': str(e)}
            out[f.stem]['_sha256'] = file_sha256(f)
    return out


def file_sha256(f):
    return hashlib.sha256(Path(f).read_bytes()).hexdigest()


def _status_record(*run_dirs):
    """<run>/agent-status.json (validate_agent_output) of each run folder, later folders winning."""
    rec = {}
    for d in run_dirs:
        f = paths.resolve(d) / 'agent-status.json'
        if f.exists():
            try:
                rec.update(json.loads(f.read_text(encoding='utf-8')))
            except ValueError:
                pass
    return rec


def gate(name, data, rec):
    """None when this agent's output may be used in the report; else why it is "not assessed"."""
    if '_invalid' in data:
        return 'invalid JSON: ' + data['_invalid'][:120]
    r = rec.get(name)
    if not isinstance(r, dict):
        return 'output not validated (no validate_agent_output record)'
    if r.get('status') not in VALID_AGENT_STATUSES:
        err = (r.get('errors') or [''])[0]
        return (f"failed validation{' twice' if (r.get('attempt') or 1) >= 2 else ''}"
                + (f': {str(err)[:160]}' if err else f" ({r.get('status')})"))
    if r.get('sha256') and data.get('_sha256') and r['sha256'] != data['_sha256']:
        return 'findings file changed after validation (validate it again)'
    return None


def _preflight_notes(group_dir, slug):
    """{agent: note} for agents agent_preflight marked blocked (latest preflight file)."""
    found = sorted(paths.resolve(group_dir).glob('agent-preflight-*.json'))
    if not found:
        return {}
    try:
        pf = json.loads(found[-1].read_text(encoding='utf-8'))
    except ValueError:
        return {}
    out = {}
    for k, v in {**(pf.get('site_agents') or {}), **((pf.get('hotels') or {}).get(slug) or {})}.items():
        if isinstance(v, dict) and v.get('status') == 'blocked':
            out[k] = v.get('note') or 'blocked in preflight'
    return out


def gated_agents(agents, rec, expected=(), blocked=None):
    """Split agent files into (usable {name: data}, status {name: str}). Excluded and absent agents are
    "not assessed: <reason>"."""
    usable, status = {}, {}
    for name, data in agents.items():
        why = gate(name, data, rec)
        if why:
            status[name] = 'not assessed: ' + why
        else:
            usable[name] = data
            status[name] = rec[name]['status']
    for name in expected:
        if name not in status:
            status[name] = 'not assessed: ' + ((blocked or {}).get(name) and
                                               'blocked in preflight: ' + blocked[name] or 'did not run')
    return usable, status


def _belongs(finding, slug, reg):
    """Per-site agent findings go to the hotels whose pages they name; site-wide ones (no pages) to 'group'."""
    if finding.get('hotel') and finding['hotel'] != 'group':
        return finding['hotel'] == slug
    pages = finding.get('pages') or []
    if not pages:
        return slug == 'group' or (reg and len(reg['hotels']) == 1)
    return any(grp.hotel_for(u, reg) == slug for u in pages) if reg else True


def merge(core, agent_findings):
    """Agents restating a core check replace the generic core finding when they cover the same URLs."""
    by_check = {f['check']: f for f in core if f.get('check')}
    out = [f for f in core]
    for a in agent_findings:
        c = by_check.get(a.get('check'))
        if c and set(a.get('pages') or []) >= set(c['pages']):
            a = dict(a)
            a['severity'] = _sev_max(a['severity'], c['severity'])
            a.setdefault('count', c['count'])
            out = [x for x in out if x is not c]
        out.append(a)
    seen, uniq = set(), []
    for f in out:
        key = (f.get('check') or f['id'], tuple(sorted(f.get('pages') or [])), f['title'] if not f.get('pages') else '')
        if key in seen:
            continue
        seen.add(key)
        uniq.append(f)
    return uniq


def _basis(name, sources, ran):
    """Plain note on what a category's score rests on, naming the agents that did not run or were left out."""
    want = CATEGORY_AGENTS.get(name, [])
    ran = ran or {}
    missing = [a for a in want if a not in ran or str(ran[a]) == 'not assessed: did not run']
    failed = [f'{a} ({ran[a]})' for a in want if a in ran and a not in missing
              and ran[a] not in VALID_AGENT_STATUSES]
    code = sorted(s for s in sources if not s.startswith('seo-'))
    agents = sorted(s for s in sources if s.startswith('seo-'))
    if not sources:
        why = ([f"{', '.join(missing)} did not run"] if missing else []) + failed
        return 'not assessed: ' + ('; '.join(why) or 'no checks measured')
    parts = []
    if code:
        parts.append('code checks (' + ', '.join(code) + ')')
    if agents:
        parts.append(', '.join(agents))
    note = ' + '.join(parts)
    if missing:
        note += f"; {', '.join(missing)} did not run"
    if failed:
        note += '; ' + ', '.join(failed)
    if (missing or failed) and not agents:
        note += ', so this score covers the code checks only'
    return note


def score_all(checks, ran=None):
    """Category scores + the Health Score with its coverage, cap and status.
    ran = {agent: status} (from gated_agents); used only for the 'basis' note.
    Returns {'health', 'health_raw', 'health_status', 'health_label', 'health_note', 'coverage',
    'booking_path_fails', 'categories'}. health is the number to show (None when not scored or Blocked)."""
    by_cat = defaultdict(lambda: {'passed': 0, 'failed': 0, 'not_measured': 0, 'w_pass': 0, 'w_all': 0, 'w_nm': 0,
                                  'sources': set()})
    for c in checks:
        b = by_cat[c['category']]
        b['sources'].add(c.get('source') or 'code')
        w = SEV_WEIGHT.get(c['severity'], 1)
        if c['result'] == 'not_measured':
            b['not_measured'] += 1
            b['w_nm'] += w
            continue
        b['w_all'] += w
        if c['result'] == 'pass':
            b['passed'] += 1
            b['w_pass'] += w
        else:
            b['failed'] += 1
    cats = []
    for name in list(WEIGHTS) + SEPARATE:
        b = by_cat.get(name)
        score = round(100 * b['w_pass'] / b['w_all']) if b and b['w_all'] else None
        cov = round(100 * b['w_all'] / (b['w_all'] + b['w_nm'])) if score is not None else 0
        cats.append({'name': name, 'weight': WEIGHTS.get(name), 'score': score,
                     'passed': b['passed'] if b else 0, 'failed': b['failed'] if b else 0,
                     'not_measured': b['not_measured'] if b else 0, 'coverage': cov,
                     'basis': _basis(name, b['sources'] if b and b['w_all'] else set(), ran)})
    scored = [c for c in cats if c['weight'] and c['score'] is not None]
    tw = sum(c['weight'] for c in scored)
    raw = round(sum(c['score'] * c['weight'] for c in scored) / tw) if tw else None
    coverage = round(sum(c['weight'] * c['coverage'] for c in cats if c['weight']) / sum(WEIGHTS.values()))
    fails, seen = [], set()
    for c in checks:
        if (c.get('id') in BOOKING_PATH_CRITICAL and c.get('id') not in seen and c['result'] == 'fail'
                and c['severity'] == 'Critical' and (not BOOKING_PATH_CRITICAL[c['id']] or c.get('key_page'))):
            seen.add(c['id'])
            fails.append(c.get('title') or c['id'])
    cov_txt = f'score covers {coverage}% of weighted checks'
    if raw is None:
        status, health, note = 'not scored', None, 'no weighted checks were measured'
    elif len(fails) >= 2:
        status, health = 'blocked', None
        note = (f'Blocked: {len(fails)} Critical booking-path checks fail ({"; ".join(fails)}); '
                f'no score is given until they are fixed')
    elif coverage < COVERAGE_MIN:
        status, health = 'not scored', None
        note = f'not scored: only {coverage}% of weighted checks were measured (minimum {COVERAGE_MIN}%)'
        if fails:
            note += f'; a Critical booking-path check also fails ({fails[0]})'
    elif fails:
        status, health = 'capped', min(raw, HEALTH_CAP)
        note = f'capped at {HEALTH_CAP}: a Critical booking-path check fails ({fails[0]})'
    else:
        status, health, note = 'scored', raw, ''
    label = {'blocked': 'Blocked', 'not scored': 'not scored'}.get(status, f'{health}/100')
    return {'health': health, 'health_raw': raw, 'health_status': status, 'health_label': label,
            'health_note': '; '.join(x for x in (note, cov_txt) if x), 'coverage': coverage,
            'booking_path_fails': fails, 'categories': cats}


def scores(checks, ran=None):
    """(Health Score to show or None, categories). score_all has the coverage, cap and status."""
    s = score_all(checks, ran)
    return s['health'], s['categories']


def health_fields(s):
    """The score_all fields a report's "scores" object carries next to health and categories."""
    return {k: s[k] for k in ('health_raw', 'health_status', 'health_label', 'health_note', 'coverage',
                              'booking_path_fails')}


def _section(f, n):
    # Evidence is our own data (counts, tools), so it goes in the "why" line, which the [CONFIRM] guard skips.
    why = f"{f['evidence']['summary']} (source: {f['evidence']['tool']})"
    blocks = []
    pages = f.get('pages') or []
    if pages:
        shown = pages[:25]
        blocks.append({'ul': shown})
        if len(pages) > 25:
            blocks.append({'note': f'{len(pages)} pages in total: the first 25 are shown; the full list is in the '
                                   f'URL list CSV next to this report ({f["id"]}).'})
    blocks.extend(f.get('blocks') or [])
    blocks.append({'paste' if any(k in f['fix'] for k in ('`', '"')) else 'p': '**Fix:** ' + f['fix']})
    if f.get('where'):
        blocks.append({'note': '**Where:** ' + f['where']})
    if f.get('checks'):
        from .checks import describe
        blocks.append({'note': '**Check:** ' + '; '.join(describe(c) for c in f['checks'][:6]) +
                               (f' (+{len(f["checks"]) - 6} more)' if len(f['checks']) > 6 else '')})
    sec = {'number': n, 'title': f['title'], 'severity': f['severity'], 'category': f['category'], 'why': why,
           'blocks': blocks, 'checks': f.get('checks', []), 'actions': f.get('actions', []),
           'owner': f['owner'], 'finding_id': f['id'], 'pages_all': pages}
    if f.get('hold'):
        sec['hold'] = f['hold']
    return sec


def keyword_sections(hdir, hotel, slug):
    """The Audit Report's "Keywords we chose, and why" chapter, from keywords/keyword-map.json. Every cluster is
    listed (no limit). The tables are our own data (Keyword Planner, Search Console, OpenStreetMap distances), so the
    [CONFIRM] guard skips them (code_data)."""
    from . import keyword_map as km
    f = hdir / 'keywords' / 'keyword-map.json'
    if not f.exists():
        return [{'chapter': 'Keywords we chose, and why', 'chapter_label': 'Keywords we chose, and why',
                 'title': 'Keywords we chose, and why', 'blocks': []},
                {'title': 'Keyword map not built', 'code_data': True,
                 'blocks': [{'p': 'The keyword map was not built in this run (no Keyword Planner access or it failed), '
                                  'so no target searches are chosen yet.'}]}]
    m = json.loads(f.read_text(encoding='utf-8'))
    cl = m.get('clusters', [])
    market = (m.get('markets') or [''])[0]
    status_word = {'ranks': 'page 1', 'shows but low': 'shows, low', 'invisible': 'not shown', 'no page': 'no page'}
    rows = []
    for n, c in enumerate(cl, 1):
        why = c.get('why') or km.explain(c, city=m.get('city', ''), market=market, slug=slug)
        why = [w for w in why if not w[:1].isdigit() and not w.startswith('Booking intent')]
        others = [k for k in c.get('keywords', []) if k != c['primary_keyword']]
        today = status_word.get(c.get('status'), c.get('status', ''))
        if c.get('gsc_position'):
            today += f" (position {c['gsc_position']})"
        page = c.get('target_page') or 'new page (Build Plan)'
        rows.append([n, f"**{c['primary_keyword']}**" + (f" + {len(others)} similar" if others else ''),
                     f"{c.get('volume', 0):,}", f"`{urlparse(page).path or page}`" if c.get('target_page') else page,
                     today, ' '.join(why)])
    ex = m.get('excluded_summary') or {}
    kept = sum(len(c.get('keywords', [])) for c in cl)
    how = [
        f"**Brand searches need no work.** People already looking for {hotel['name']} by name find it; the work is "
        'being found by guests who have no hotel in mind yet. Brand searches were used only to filter them out.',
        f"**Where the searches came from:** {', '.join(m.get('sources') or ['Keyword Planner'])}. Searches were "
        "built from what the hotel is and where it is (its area, nearby landmarks, room types, facilities), then "
        'expanded with Keyword Planner ideas' + (' and competitor sites' if any('competitor' in s for c in cl
                                                                                 for s in c.get('sources', [])) else '')
        + ', and Search Console added the searches the hotel already shows for.',
        f"**Kept:** {kept:,} searches with real demand, grouped into {len(cl)} groups; each group has one page that "
        f"should rank for it. Monthly searches are Keyword Planner averages for {market or 'the hotel city'}"
        + (f" ({', '.join(m.get('markets', [])[1:])} also checked)" if len(m.get('markets', [])) > 1 else '') + '.',
    ]
    if ex:
        how.append(f"**Left out:** {sum(v['count'] for v in ex.values()):,} searches (reasons below).")
    secs = [{'chapter': 'Keywords we chose, and why', 'chapter_label': 'Keywords we chose, and why',
             'title': 'Keywords we chose, and why', 'blocks': []},
            {'title': 'How the keywords were chosen', 'code_data': True, 'blocks': [{'p': x} for x in how]},
            {'title': f'Target searches ({len(cl)} groups)', 'code_data': True,
             'blocks': [{'table': {'columns': ['#', 'Search (group)', 'Searches / month', 'Page that should rank',
                                               'Today', 'Why'], 'rows': rows}},
                        {'note': '"Today" is the Search Console average position over 16 months for the hotel\'s '
                                 'pages; "not shown" = the page exists but Google does not show it for these searches; '
                                 '"no page" = the Build Plan adds one. Every search in each group: '
                                 f"`{f.with_name('keyword-map-keywords.csv').name}`."}]}]
    if ex:
        secs.append({'title': 'Searches left out, and why', 'code_data': True,
                     'blocks': [{'table': {'columns': ['Why it was left out', 'Searches', 'Examples'],
                                           'rows': [[r[:1].upper() + r[1:], f"{v['count']:,}", ', '.join(v['examples'])]
                                                    for r, v in ex.items()]}},
                                {'note': f"Every search left out, with its reason: "
                                         f"`{Path(m.get('excluded_file', 'keyword-map-excluded.csv')).name}`."}]})
    else:
        secs.append({'title': 'Searches left out', 'code_data': True,
                     'blocks': [{'p': 'This keyword map was built before reasons were recorded; rebuild it '
                                      '(build_keyword_map) to list what was left out and why.'}]})
    return secs


def _doc(title, hotel_name, site, findings, health, cats, extra=None):
    findings = sorted(findings, key=lambda f: (CHAPTER_ORDER.index(f['category']) if f['category'] in CHAPTER_ORDER
                                               else 99, SEV_RANK.get(f['severity'], 9), -len(f.get('pages') or [])))
    sections, n = [], 0
    current = None
    for f in findings:
        if f['category'] != current:
            current = f['category']
            cat = next((c for c in cats if c['name'] == current), None)
            sections.append({'chapter': current, 'chapter_score': cat['score'] if cat else None,
                             'title': current, 'blocks': []})
        n += 1
        sections.append(_section(f, n))
    doc = {'hotel': hotel_name, 'site': site, 'title': title, 'date': date.today().strftime('%d %b').lstrip('0'),
           'file_number': 'auto', 'sections': sections,
           'scores': {'health': health, 'categories': cats}}
    doc.update(extra or {})
    return doc


def parity_calendar_block(hotel_dir, hotel_name):
    """The Disparity / Best Rate calendar (import_parity_calendar into <hotel dir>/parity/) as the Audit Report's
    `parity` block and lead lines. When the files cover several hotels, only this hotel's months are used (matched
    on its name); none matching -> all of them. None when no calendar was imported."""
    from . import parity_calendar
    months, src = parity_calendar.stored_months(hotel_dir, hotel_name)
    if not months:
        return None
    out = parity_calendar.report_block(months)
    out['parity']['note'] += f" Source: {src.parent.name}/{src.name}."
    return out


def build(group_dir, slug, run_date=None):
    """Assemble one hotel's Audit Report + Web Team List (+ audit-data.json). Returns paths and scores.
    run_date defaults to the hotel's latest audit-<date> folder (a run can cross midnight)."""
    reg = grp.load(group_dir)
    if not reg:
        raise FileNotFoundError('no site.json: run detect_hotels + save_group first')
    run_date = run_date or _latest_run(grp.hotel_dir(group_dir, slug, reg))
    hotel = next((h for h in reg['hotels'] if h['slug'] == slug), None)
    if not hotel:
        raise LookupError(f'no hotel {slug}')
    gd = paths.resolve(group_dir)
    hdir = grp.hotel_dir(group_dir, slug, reg)
    hrun = hdir / f'audit-{run_date}'
    grun = grp.site_dir(group_dir, reg) / f'audit-{run_date}'      # the same folder on a single-hotel site
    crawl_dir = _latest(gd, 'crawl-')
    core, core_checks = core_findings(crawl_dir, reg, slug) if crawl_dir else ([], [])
    bf, bchecks = booking_findings(hdir, slug)
    agents = {**{k: v for k, v in _agent_files(grun).items()}, **_agent_files(hrun)}
    # only agents that passed validate_agent_output reach the report; the rest are "not assessed" (with the reason)
    agents, status = gated_agents(agents, _status_record(grun, hrun),
                                  SITE_AGENTS + [a for a in HOTEL_AGENTS if not a.startswith('seo-flow')],
                                  _preflight_notes(group_dir, slug))
    a_findings, a_checks, separate, what_works = [], [], {}, defaultdict(list)
    for name, data in agents.items():
        is_site = data.get('scope') == 'site'
        for f in data.get('findings', []):
            if not is_site or _belongs(f, slug, reg):
                f = dict(f)
                types = {_page_type_guess(u, reg) for u in f.get('pages') or []}
                f['severity'] = floor(f['severity'], types)
                if f.get('hold') or f['category'] == 'Web Team':
                    f['owner'] = 'web' if f['category'] == 'Web Team' else f.get('owner', 'seo')
                a_findings.append(f)
        a_checks += [dict(c, source=name) for c in data.get('checks', [])]
        for k, v in (data.get('scores') or {}).items():
            separate[k] = v
        for w in data.get('what_works') or []:
            what_works[name].append(w)
    findings = merge(core + bf, a_findings)
    checks = core_checks + bchecks + a_checks
    sa = score_all(checks, status)
    health, cats = sa['health'], sa['categories']
    seo = [f for f in findings if f['owner'] == 'seo']
    web = [f for f in findings if f['owner'] == 'web']
    counts = {s: sum(1 for f in seo if f['severity'] == s) for s in SEV_RANK}
    extra = {'short_name': hotel['name'], 'hotel_slug': slug, 'separate_scores': separate,
             'agent_status': status, 'what_works': dict(what_works), 'counts': counts,
             'subtitle': f"Full audit of {hotel['name']} ({', '.join(hotel['paths'])}) · Health Score "
                         f"{sa['health_label']} ({sa['coverage']}% of weighted checks) · {len(seo)} findings "
                         f"({counts['Critical']} Critical, {counts['High']} High)"}
    hrun.mkdir(parents=True, exist_ok=True)
    report = _doc('Audit Report', hotel['name'], reg['group']['site'], seo, health, cats, extra)
    report['scores'].update(health_fields(sa))
    report['sections'] += keyword_sections(hdir, hotel, slug)
    pc = parity_calendar_block(hdir, hotel['name'])
    if pc:
        report['parity'] = pc['parity']
        report['warnings_top'] = report.get('warnings_top', []) + pc['lead_lines']
    web_doc =_doc('Web Team List', hotel['name'], reg['group']['site'], web, None, cats,
                   {'short_name': hotel['name'], 'hotel_slug': slug,
                    'subtitle': f'Developer items for {hotel["name"]}: {len(web)} finding(s)' +
                                ('.' if grp.is_single(reg) else '; site-wide items are in the Group Summary.')})
    web_doc.pop('scores', None)
    (hrun / 'audit-report.json').write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding='utf-8')
    (hrun / 'web-team.json').write_text(json.dumps(web_doc, indent=1, ensure_ascii=False), encoding='utf-8')
    envelope = {'summary': {'health_score': health, 'business_type': 'hotel', 'counts': counts, **health_fields(sa)},
                'categories': [dict(c, findings=[{k: f[k] for k in ('title', 'severity', 'fix')} | {
                    'description': f['evidence']['summary']} for f in seo if f['category'] == c['name']],
                                    what_works=[]) for c in cats],
                'separate_scores': separate, 'agent_status': status}
    (hrun / 'audit-data.json').write_text(json.dumps(envelope, indent=1, ensure_ascii=False), encoding='utf-8')
    return {'hotel': slug, 'health': health, 'health_label': sa['health_label'], 'health_note': sa['health_note'],
            'coverage': sa['coverage'], 'categories': {c['name']: c['score'] for c in cats},
            'findings': len(seo), 'web_team': len(web), 'counts': counts, 'agent_status': status,
            'files': {'audit_report': str(hrun / 'audit-report.json'), 'web_team': str(hrun / 'web-team.json'),
                      'audit_data': str(hrun / 'audit-data.json')}}


def _page_type_guess(url, reg=None):
    """audit.page_type, plus: on a group site each hotel's main page (its path prefix) is that hotel's 'home'."""
    if reg:
        p = (urlparse(url).path or '/').rstrip('/') + '/'
        if any(p == prefix for h in reg.get('hotels', []) for prefix in h.get('paths', [])):
            return 'home'
    from .audit import page_type
    try:
        return page_type(url, urlparse(url).netloc.replace('www.', ''))
    except Exception:  # noqa: BLE001
        return 'other'


def _latest_run(d):
    """Date of the newest audit-<date> folder under d, else today."""
    found = sorted(p.name[len('audit-'):] for p in d.glob('audit-*') if p.is_dir()) if d.exists() else []
    return found[-1] if found else date.today().isoformat()


def _latest(gd, prefix):
    found = sorted((p for p in gd.glob(prefix + '*') if p.is_dir()), key=lambda p: p.name)
    return str(found[-1]) if found else ''


def build_group(group_dir, run_date=None):
    """Group Summary: hotels x scores, site-wide findings once, keyword ownership, agent status per hotel."""
    reg = grp.load(group_dir)
    if not reg:
        raise FileNotFoundError('no site.json: run detect_hotels + save_group first')
    if grp.is_single(reg):
        return {'skipped': True, 'reason': 'single-hotel site: there is no Group Summary; site-wide findings are in '
                                           "the hotel's own Audit Report and Web Team List"}
    run_date = run_date or _latest_run(paths.resolve(group_dir) / 'group')
    gd = paths.resolve(group_dir)
    rows, statuses = [], {}
    for h in reg['hotels']:
        f = gd / 'hotels' / h['slug'] / f'audit-{run_date}' / 'audit-report.json'
        if not f.exists():
            rows.append([h['name'], 'not built', '', '', ''])
            continue
        d = json.loads(f.read_text(encoding='utf-8'))
        cats = {c['name']: c['score'] for c in d['scores']['categories']}
        rows.append([h['name'], d['scores'].get('health_label') or (d['scores']['health'] if d['scores']['health']
                                                                     is not None else 'n/a'),
                     d['counts']['Critical'], d['counts']['High'],
                     ', '.join(f"{k} {v}" for k, v in cats.items() if v is not None and k in WEIGHTS)])
        statuses[h['slug']] = d.get('agent_status', {})
    grun = gd / 'group' / f'audit-{run_date}'
    crawl_dir = _latest(gd, 'crawl-')
    core, core_checks = core_findings(crawl_dir, reg, 'group') if crawl_dir else ([], [])
    gfiles, site_status = gated_agents(_agent_files(grun), _status_record(grun), SITE_AGENTS,
                                       _preflight_notes(group_dir, ''))
    statuses['site-wide'] = site_status
    site_f = []
    for name, data in gfiles.items():
        for f in data.get('findings', []):
            if not f.get('pages') or f.get('hotel') == 'group':
                site_f.append(f)
    findings = merge(core, site_f)
    # the group page covers site-wide work only; per-hotel agents are reported in each hotel's Audit Report
    ran = {**{a: 'complete' for a in HOTEL_AGENTS}, **site_status}
    sa = score_all(core_checks + [dict(c, source=k) for k, d in gfiles.items() for c in d.get('checks', [])], ran)
    health, cats = sa['health'], sa['categories']
    own = []
    for h in reg['hotels']:
        km = gd / 'hotels' / h['slug'] / 'keywords' / 'keyword-map.json'
        if km.exists():
            for c in json.loads(km.read_text(encoding='utf-8')).get('clusters', [])[:15]:
                own.append([h['name'], c['primary_keyword'], c['volume'], c['status'],
                            next((x['name'] for x in reg['hotels'] if x['slug'] == c.get('owned_by')), h['name'])])
    pre = [{'title': 'Hotels', 'blocks': [{'table': {'columns': ['Hotel', 'Health', 'Critical', 'High', 'Categories'],
                                                     'rows': rows}}]}]
    if own:
        pre.append({'title': 'Keyword ownership across hotels (top clusters per hotel)',
                    'blocks': [{'table': {'columns': ['Hotel', 'Cluster', 'Searches / month', 'Status', 'Owned by'],
                                          'rows': own}}]})
    doc = _doc('Group Summary', reg['group'].get('name') or reg['group']['site'], reg['group']['site'],
               findings, health, cats, {'short_name': reg['group'].get('name') or 'Group', 'agent_status': statuses,
                                        'subtitle': f"{len(reg['hotels'])} hotels · site-wide findings appear here "
                                                    'once'})
    doc['scores'].update(health_fields(sa))
    doc['sections'] = pre + doc['sections']
    grun.mkdir(parents=True, exist_ok=True)
    (grun / 'group-summary.json').write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding='utf-8')
    return {'file': str(grun / 'group-summary.json'), 'hotels': len(reg['hotels']), 'site_findings': len(findings),
            'site_health': health, 'site_health_label': sa['health_label'], 'site_health_note': sa['health_note']}
