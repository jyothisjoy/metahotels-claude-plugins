# Porting claude-seo into hotel-seo

hotel-seo runs 11 agents and 26 scripts taken from claude-seo (MIT, https://github.com/AgriciDaniel/claude-seo).
To update to a newer claude-seo release:

1. Extract the release zip into an empty folder outside this repo.
2. Copy the same script names into `server/hotel_seo_tools/vendor/claude_seo/scripts/` (unchanged), plus
   `data/google-updates.json`, `schema/templates.json` and the matching tests; run
   `uv run python -m pytest hotel_seo_tools/vendor/claude_seo/tests` from `server/`. Update the version in `NOTICE.md`.
3. References: `uv run --project ../../server python port_refs.py <claude-seo-main> ../../skills/hotel-seo/references/claude-seo`
4. Agents: `uv run --project ../../server python make_agents.py <claude-seo-main> ../../agents`
   (hotel-specific sections live in `make_agents.py`; edit them there, not in the generated files).
5. Check `grep -rn "scripts/claude-seo" ../../agents ../../skills` finds nothing, then run a test audit.
