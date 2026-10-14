# MetaHotels Claude plugins

Private. Contains the **hotel-seo** plugin: give Claude a hotel website and get the SEO agency's Priority, Nice-to-Have and Web Team lists as PDFs, then re-check the agency's work against them.

## Before you start (once per person)

1. **Repo access.** Ask the repo owner to add your GitHub account as a collaborator on `jyothisjoy/metahotels-seo`.
2. **GitHub login on your computer.** Claude installs the plugin with a normal `git clone`, so your git must be able to reach the private repo. The easiest way is to install the [GitHub CLI](https://cli.github.com/) and run `gh auth login` (GitHub.com → HTTPS → log in with a browser). Git Credential Manager (comes with Git for Windows) or an SSH key also work.
   Test: `git clone https://github.com/jyothisjoy/metahotels-seo.git` should work without errors (you can delete the folder afterwards).
3. **Claude Code**, in the terminal or the Code tab of the Claude desktop app.

## Install (once per machine, Windows or macOS)

1. In Claude Code (terminal, or the desktop app's Code tab):
   ```
   /plugin marketplace add jyothisjoy/metahotels-seo
   /plugin install hotel-seo@metahotels
   ```
   If the `/plugin` menu doesn't appear in the Code tab, run the same thing in a terminal; the terminal and the Code tab share the same plugins:
   ```
   claude plugin marketplace add jyothisjoy/metahotels-seo
   claude plugin install hotel-seo@metahotels
   ```
   Then start a new Claude Code session.
2. Run `/hotel-seo init`. It installs `uv` if needed, LibreCrawl, Chromium and the desktop-app setup, then walks you through one Google sign-in as **metahotels.m@gmail.com** (get the password from the team; never put it in this repo). Takes about 5–10 minutes.
3. **Mirai (optional).** If the team has Mirai XML API credentials, type the command Claude gives you after init (starting with `!`) and enter them yourself. Claude never sees the password.
4. **Desktop chat (optional).** Upload `~/.metahotels-seo/hotel-seo-skill.zip` in Settings → Capabilities → Skills, then fully quit and reopen the desktop app. Desktop chat has no `/plugin` command; this zip and the setup from step 2 are how it gets the skill and tools.
5. **Check:** `/hotel-seo init --check` shows all OK.

## Use

```
/hotel-seo atanahotel.com            full run: crawl, audit, Search Console, GA4, Mirai, three PDFs
/hotel-seo recheck atanahotel.com    after the agency says "done": every item checked on the live site
/hotel-seo init --check              health check
```

Work is saved in a folder per hotel (`<domain>/`) wherever Claude is started (desktop chat: `~/Documents/MetaHotels SEO`). PDFs are named like `25 - Atana Priority SEO List (14 Oct).pdf`, with running file numbers across hotels.

## Update

```
/plugin marketplace update metahotels
/plugin update hotel-seo
/hotel-seo init
```
`init` only changes what's needed and refreshes the desktop app's copy. Desktop chat users upload the new skill zip again.

Automatic background updates of a private plugin need a `GITHUB_TOKEN` (or `GH_TOKEN`) environment variable with read access to this repo. Without it, run the commands above yourself.

## Troubleshooting

| Problem | Fix |
|---|---|
| "Repository not found" or an authentication error on `marketplace add` | You're not a collaborator yet, or git isn't logged in: run `gh auth login`, then try again. |
| `git` or `uv` not found in the desktop app | Fully quit and reopen the app after installing them. |
| `/hotel-seo` tools missing | Start a new session; then `/hotel-seo init --check`. |
| Google says "This app isn't verified" | Click **Advanced → Go to Google Analytics MCP**, then Continue. |
| Start over on a machine | Delete `~/.metahotels-seo/` and run `/hotel-seo init` again. |

## What's inside

```
plugins/hotel-seo/
  skills/hotel-seo/       SKILL.md (the workflow), references/ (playbook, inputs checklist,
                          LibreCrawl guide, team and message templates),
                          templates/lists.schema.json, examples/
  server/                 hotel-seo-tools MCP server (Python, run with uv): crawl, site audit,
                          rendered-page checks, Custom Search, redirect test, Mirai bookings,
                          PDF rendering with the [CONFIRM] guard, recheck, health check,
                          Google launchers
  setup/init.py           /hotel-seo init
  setup/google/           OAuth client for the metahotels-analytics GCP project (repo must stay private)
  .mcp.json               hotel-seo-tools, hotel-seo-gsc, hotel-seo-ga4
```

Machine state lives in `~/.metahotels-seo/` (LibreCrawl, Google tokens, Mirai credentials, logs, the desktop app's server copy). It never goes into this repo.

## Changing the method

Edit `plugins/hotel-seo/skills/hotel-seo/references/playbook.md` (add hotel lessons to section 10), bump `version` in both `plugins/hotel-seo/.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json`, commit and push. Teammates get it with the update commands above.
