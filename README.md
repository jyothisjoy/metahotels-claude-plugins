# MetaHotels Claude plugins

Private. Contains the **hotel-seo** plugin: give Claude a hotel website and get the SEO agency's Priority, Nice-to-Have and Web Team lists as PDFs and Google Docs, then re-check the agency's work against them.

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
3. **Google Ads Keyword Planner (deferred for now).** Until then, put Keyword Planner CSV exports in `<domain>/keywords/`. Later, if the team has Google Ads API access, type the command Claude gives you (`hotel-seo-ads-login`) and enter the manager account ID and developer token yourself, then sign in again with Ads included (Claude gives you the command).
4. **Rate parity and Bing (optional).** `hotel-seo-parity-login` (Azure connection of the parity feed; `--from-env <magicparity>\.env` reads it from the Magic Parity project) and `hotel-seo-bing-login` (Bing Webmaster API key). Claude gives you the exact commands.
4b. **Mirai (optional).** If the team has Mirai XML API credentials, type the command Claude gives you after init (starting with `!`) and enter them yourself. Claude never sees the password.
5. **Desktop chat (optional).** Upload `~/.metahotels-seo/hotel-seo-skill.zip` in Settings → Capabilities → Skills, then fully quit and reopen the desktop app. Desktop chat has no `/plugin` command; this zip and the setup from step 2 are how it gets the skill and tools.
6. **Check:** `/hotel-seo init --check` shows all OK.

## Use

```
/hotel-seo atanahotel.com            full run: crawl, audit, Search Console, GA4, keywords, booking engine,
                                     Mirai, three PDFs (asks once for the hotel information sheet)
/hotel-seo recheck atanahotel.com    after the agency says "done": every item checked on the live site
/hotel-seo monitor atanahotel.com    what changed since the last run (posts, spam searches, booking links, tags)
/hotel-seo monitor add atanahotel.com   add it to the daily monitor run
/hotel-seo init --check              health check
```

Work is saved in a folder per hotel (`<domain>/`) wherever Claude is started (desktop chat: `~/Documents/MetaHotels SEO`). PDFs are named like `25 - Atana Priority SEO List (14 Oct).pdf`, with running file numbers across hotels.

### What a re-check adds

`recheck_list` only re-checks the points on the lists already sent and marks each one Done, Partly, Open, Manual or Waiting (waiting on the hotel). It never adds points itself.

`/hotel-seo recheck` also crawls and audits the site again. Claude then adds new lettered sections to the Re-check list for:

- **New Priority-type problems found by the new crawl.** For example, a key page now set to noindex, a title on the wrong page, new broken booking links or new spam posts. Anything the agency's changes broke goes at the very top.
- **The hotel's confirmed corrections** (offers, occupancy), once the hotel has answered the [CONFIRM] questions.

Notes from the agency's WhatsApp messages (for example "redirects being reviewed tomorrow") go on the existing points as context, not as new tasks.

New Nice-to-Have and Web Team problems are not added during a re-check. They wait for the next full `/hotel-seo <domain>` run. Urgent security problems are the exception: the daily monitor reports those to the MetaHotels team the same day.

Nothing compares the new audit with the old one automatically. Claude decides what is new and Priority-level, so read new points before sending, in case one was left off the earlier list on purpose.

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
| Lists come as PDF only, with a `.docs.html` file | The Google sign-in has no Docs permission yet: run `/hotel-seo init` again and approve the consent screen. |
| Start over on a machine | Delete `~/.metahotels-seo/` and run `/hotel-seo init` again. |

## What's inside

```
plugins/hotel-seo/
  skills/hotel-seo/       SKILL.md (the workflow), references/ (playbook, inputs checklist,
                          LibreCrawl guide, team and message templates),
                          templates/lists.schema.json, examples/
  server/                 hotel-seo-tools MCP server (Python, run with uv): crawl, site audit,
                          rendered-page checks, booking engine snapshot, Keyword Planner, rate parity,
                          URL Inspection (indexing), Bing links and sitemaps,
                          Custom Search, redirect test, Mirai bookings,
                          PDF rendering with the [CONFIRM] guard, recheck, health check,
                          Google launchers
  setup/init.py           /hotel-seo init
  setup/google/           OAuth client for the metahotels-analytics GCP project (repo must stay private)
  .mcp.json               hotel-seo-tools, hotel-seo-gsc, hotel-seo-ga4
```

Machine state lives in `~/.metahotels-seo/` (LibreCrawl, Google tokens, Google Ads and Mirai credentials, logs, the desktop app's server copy). It never goes into this repo.

## Changing the method

Edit `plugins/hotel-seo/skills/hotel-seo/references/playbook.md` (add hotel lessons to section 10), bump `version` in both `plugins/hotel-seo/.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json`, commit and push. Teammates get it with the update commands above.
