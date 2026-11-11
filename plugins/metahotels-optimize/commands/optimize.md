---
description: MetaHotels site performance pass. --init sets up this machine and the work folder; <site> onboards the site (asks for anything missing) and runs the pass.
argument-hint: --init [work-folder] [--test-key] | <site-url> [--omit-report] [--check]
---

# MetaHotels optimization

Arguments: `$ARGUMENTS`

Tools: `${CLAUDE_PLUGIN_ROOT}/skills/metahotels-optimize/scripts` (below: `$S`). Load the
`metahotels-optimize:metahotels-optimize` skill first (Skill tool; if it is not listed, read
`${CLAUDE_PLUGIN_ROOT}/skills/metahotels-optimize/SKILL.md`): its hard rules apply to every mode.

Pick the mode from the arguments:

## No arguments, or `--help`

Print the usage in a few lines (the modes below), then whether the current folder is inside a work folder
(`metahotels.json` here or above) and which site folders it holds (folders with a `site.json`). Stop.

## `--init [work-folder] [--test-key]`

Sets up this machine and a work folder. Nothing on any website is touched.

1. The work folder is the folder given, else the current folder. If the current folder is not empty and has no
   `metahotels.json`, ask the user (AskUserQuestion) whether to use it or another path, before creating anything.
2. Run `python -I "$S/init.py" "<work-folder>"` (add `--test-key` when given). It checks the prerequisites,
   installs the Node dependencies, and creates `metahotels.json`, `.env` with an empty `PAGESPEED_API_KEY=`,
   and the two cross-site documents when they are missing. It never overwrites a file or a key.
3. Show the user the result as a short table, then the "still to do" list:
   - **PageSpeed key**: tell them the exact `.env` path and that they put the key in themselves (Google Cloud
     console › enable "PageSpeed Insights API" › Credentials › API key). Do not ask them to paste it into the chat.
     When they say it is in, run `python -I "$S/init.py" "<work-folder>" --no-npm --test-key` and report the result.
   - **Optional Python packages** (Pillow ≥ 11.3 for the image re-encode, fonttools for icon-font subsets): ask
     whether to install them now (`pip install --user ...`); install only on a yes.
   - Any **required** prerequisite that failed: say what to install; do not try to install system software.
4. End with the next step: `/metahotels-optimize:optimize <site-url>`.

## `<site-url> [--omit-report] [--check]`

1. **Work folder.** If no `metahotels.json` is found here or above, say so and offer to run `--init` here first.
   Run every following command from the work folder, then from the site folder.
2. **Onboarding.** Run `python -I "$S/site-init.py" "<site-url>"` (from the work folder). It creates the site
   folder and `site.json`, checks the site, sitemap, MCP entry and access, the PageSpeed key, and prints a numbered
   list "to ask the user".
3. **Ask for every missing item** with AskUserQuestion, at most four questions per call, the most blocking first
   (MCP access, then the PageSpeed key, then the owner's answers). Rules:
   - **MCP entry missing**: show the user the `claude mcp add ...` command the check printed and tell them to run it
     in their own terminal (it carries the application password; never ask for the password in the chat). When they
     say it is done, run `site-init.py` again. If they cannot add it, offer a measure-only pass (no content changes:
     steps 1, 2, 3 and the report) and record that in `site.json` `notes`.
   - **Booking links**: ask for the Mirai link per hotel; store exactly what they give in `site.json`
     `booking_links` with the date. "I don't know yet" is a valid answer: record it and list every "Book now"
     link for the owner in the report instead. Never build or copy one.
   - **Owner context** (CDN/DNS plans, plugins and pages they rely on): store the answers in `site.json` `notes`.
   - **Chrome**: ask them to confirm Chrome with Claude in Chrome is logged into the site's wp-admin; check it
     yourself with the claude-in-chrome tools (`tabs_context_mcp`, then a read of `/wp-admin/` that does not land on
     `wp-login.php`).
   - Answers the user skips stay open: list them at the end, do not invent values.
4. **Report option.** With `--omit-report`, set `"report": false` in `site.json` and tell the user what that means:
   no `performance-report-*.md` for this site and no section in the two cross-site documents; results are still
   saved in `audit/` and summarised in the chat. Without the flag, keep any value already in `site.json` (a
   later run does not switch the report back on by itself; `"report": true` does) and otherwise ask once, as part
   of the onboarding questions.
5. With `--check`, stop here: print the onboarding status and the open items.
6. Otherwise **run the pass** from step 1 of the skill (audit), in the site folder, following SKILL.md. Before the
   first browser tool, check `$S/node_modules` exists; if not, run `npm ci` in `$S` (a plugin update removes it).
