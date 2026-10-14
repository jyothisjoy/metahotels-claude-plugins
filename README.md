# MetaHotels Claude plugins

Private. Contains the **hotel-seo** plugin: give Claude a hotel website and get the SEO agency's Priority, Nice-to-Have and Web Team lists as PDFs, then re-check the agency's work.

## Install (once per machine, Windows or macOS)

1. In Claude Code (terminal, or the Code tab in the Claude desktop app):
   ```
   /plugin marketplace add <github-org>/metahotels-seo
   /plugin install hotel-seo@metahotels
   ```
   Restart Claude Code when it asks.
2. Run `/hotel-seo init`. It installs `uv` if needed, LibreCrawl, Chromium, the desktop-app setup, and walks you through one Google sign-in as **metahotels.m@gmail.com** (get the password from the team; never put it in this repo). Takes about 5–10 minutes.
3. Desktop chat (optional): upload `~/.metahotels-seo/hotel-seo-skill.zip` in Settings → Capabilities → Skills, then fully quit and reopen the desktop app.
4. Check: `/hotel-seo init --check` shows all OK.

## Use

```
/hotel-seo nassimatower.com          full run: crawl, Search Console, GA4, analysis, three PDFs
/hotel-seo recheck nassimatower.com  after the agency says "done"
/hotel-seo init --check              health check
```

Work is saved in a folder per hotel wherever Claude is started (desktop chat: `~/Documents/MetaHotels SEO`).

## Update

`/plugin marketplace update metahotels`, then `/plugin update hotel-seo`, then `/hotel-seo init` again (it only changes what's needed and refreshes the desktop app copy).

## What's inside

```
plugins/hotel-seo/
  skills/hotel-seo/       SKILL.md (the workflow), references/ (playbook, inputs checklist,
                          LibreCrawl guide, team), templates/lists.schema.json, examples/
  server/                 hotel-seo-tools MCP server (Python, run with uv): crawl, Custom Search,
                          redirect test, PDF rendering, health check, Google launchers
  setup/init.py           /hotel-seo init
  setup/google/           OAuth client for the metahotels-analytics GCP project (repo must stay private)
  .mcp.json               hotel-seo-tools, hotel-seo-gsc, hotel-seo-ga4
```

Machine state lives in `~/.metahotels-seo/` (LibreCrawl, Google tokens, logs, the desktop app's server copy). Delete that folder to start over.

## Changing the method

Edit `plugins/hotel-seo/skills/hotel-seo/references/playbook.md` (add hotel lessons to section 10), bump `version` in `plugins/hotel-seo/.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json`, commit and push. Teammates get it with the update commands above.
