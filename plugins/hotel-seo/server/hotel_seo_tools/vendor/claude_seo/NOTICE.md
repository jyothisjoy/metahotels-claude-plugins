# Vendored from claude-seo

Source: https://github.com/AgriciDaniel/claude-seo, version 2.5.0, commit 6be93f45064ffbadced572b5d5c95f55fd263af0
(taken from the release zip on 23 Oct 2026). License: MIT, see `LICENSE` (Copyright (c) 2026 agricidaniel).

## What is here
- `scripts/`: 26 of claude-seo's Python tools, copied **unchanged**. hotel-seo runs them as separate processes
  through the `seo_check` MCP tool (`hotel_seo_tools/seo_check.py`), never imports them. Each script adds its own
  folder to `sys.path`, so they find each other without edits.
- `data/google-updates.json`: the Google update ledger read by `seo_updates.py`.
- `schema/templates.json`: JSON-LD templates used by the seo-schema agent.
- `tests/`: claude-seo's tests for these scripts (run with `uv run python -m pytest hotel_seo_tools/vendor/claude_seo/tests`).
  Tests for claude-seo's own repository layout and for scripts not vendored here were removed or are skipped in
  `tests/conftest.py`.

## Third-party terms inside the vendored files
- `content_quality.py` and `content_humanize.py`: the AI-phrase lists draw on Wikipedia's "AI Cleanup" catalogue,
  **CC BY-SA 4.0**. Keep the attribution in those files. If the lists are changed and redistributed, the changed
  lists are shared under the same license.
- `content_humanize.py`: its replacement table also credits ivankuznetsov/claude-seo (MIT).
- The agent instructions and reference files ported to `plugins/hotel-seo/agents/` and
  `plugins/hotel-seo/skills/hotel-seo/references/claude-seo/` come from the same repository (MIT). The FLOW framework
  prompts under `references/claude-seo/flow/` are **CC BY 4.0, © Daniel Agrici**: every FLOW output carries the
  credit line "Framework and prompts © Daniel Agrici, CC BY 4.0: github.com/AgriciDaniel/flow".

## Updating
Copy the same file names from a newer claude-seo release, run the tests, and update the version and commit above.
Do not edit the scripts in place: put hotel-specific behaviour in hotel-seo's own modules.
