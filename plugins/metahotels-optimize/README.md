# metahotels-optimize

A Claude Code plugin for the complete performance pass on MetaHotels hotel websites (WordPress + Elementor +
LiteSpeed Cache, Mirai booking engine): setup, site onboarding, audit, baseline, site-wide image re-encode, root
causes, LiteSpeed and site-plugin batches, regression checks and the owner report. Mobile PageSpeed and real
throttled-phone loading come first; the booking engine is never changed.

## Install

In Claude Code:

```
/plugin marketplace add jyothisjoy/metahotels-seo
/plugin install metahotels-optimize@metahotels
```

(It ships in the `metahotels` marketplace of `jyothisjoy/metahotels-seo`, next to hotel-seo. From a local clone
instead: `/plugin marketplace add C:\path\to\metahotels-seo`.) Restart Claude Code if the
command does not show up, then set up once:

```
/metahotels-optimize:optimize --init [work-folder]
```

`--init` checks the prerequisites (Python 3.10+, Node 18+, bash and curl, Chrome; optionally PHP, Pillow ≥ 11.3,
fonttools), installs the tools' Node dependencies, and creates the work folder: `metahotels.json`, `.env` with an
empty `PAGESPEED_API_KEY=`, and the two cross-site documents. Put your PageSpeed Insights API key in that `.env`
yourself, then `/metahotels-optimize:optimize --init --test-key` confirms it works. Run `--init` again after every
plugin update (the update replaces the plugin folder, including its Node dependencies).

## Use

```
/metahotels-optimize:optimize https://example-hotel.com              onboard the site, then run the pass
/metahotels-optimize:optimize example-hotel.com --check              onboarding only: what is set, what is missing
/metahotels-optimize:optimize example-hotel.com --omit-report        no report file and no cross-site entry for this site
```

Onboarding creates `<work-folder>/<site>/site.json`, checks the site, its sitemap, the MCP access (the site needs the
**Meta MCP** WordPress plugin and an entry in Claude Code for it), and the PageSpeed key, then asks you for whatever
is missing: the MCP entry (it prints the `claude mcp add` command for you to run in your own terminal, so the
application password never enters the chat), the Mirai booking link per hotel, CDN plans, and the wp-admin login in
Chrome (the Claude in Chrome extension is used for LiteSpeed and Elementor settings).

The skill also loads by itself when you ask for part of a pass, e.g. "compress the images on Gewan" or "why did
Shams' mobile score drop".

## What is inside

```
.claude-plugin/        plugin.json and marketplace.json (this repo is its own marketplace)
commands/optimize.md   /metahotels-optimize:optimize: --init, onboarding, --omit-report, --check
skills/metahotels-optimize/
  SKILL.md             hard rules, the owner's standing decisions, the steps of a pass
  references/          the playbook in parts (audit, links, images, known patterns, testing, LiteSpeed results,
                       propagation, report, setup) and an index of every tool
  scripts/             about 80 tools (Node, Python, bash); init.py and site-init.py for setup and onboarding
  assets/              site-plugin template, five real site plugins as worked examples, report skeleton, site.json example
evals/                 test prompts for the skill (not shipped in the skill)
```

No credentials are stored in the plugin: the tools read the MCP entry from your own `~/.claude.json` and the
PageSpeed key from the work folder's `.env`.

## Maintaining

The playbook grows with every pass. Put a new pattern, result or tool change in the matching file under
`skills/metahotels-optimize/references/`, regenerate the tool index with
`python -I skills/metahotels-optimize/scripts/make-tools-index.py`, and bump `version` in both
`.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json` so installs pick up the update
(`/plugin marketplace update metahotels`).
