#!/bin/bash
# usage (from the site folder): bash <skill>/scripts/state.sh [urls.txt]
# After a tested LiteSpeed option is reverted: fetch every URL (default audit/urls.txt) and print one line per page
# with the markers of the copy the cache now serves (combined CSS, defer, delay, critical CSS, lazy images, blank
# iframes...). A tested option reaches every page generated while it was on, not only the purged front page, so
# this proves no page kept it. Then Purge All once and re-warm (warm.sh). First used on Abar, 2026-10-12.
# pwd -W gives a Windows path in Git Bash, which Python and Node accept even with MSYS_NO_PATHCONV=1
S="$(cd "$(dirname "$0")" && (pwd -W 2>/dev/null || pwd))"
URLS=${1:-audit/urls.txt}
[ -f "$URLS" ] || { echo "$URLS missing: run from the site folder"; exit 1; }
D="audit/state-$(date +%H%M%S)"
bash "$S/crawl.sh" "$URLS" "$D" > /dev/null
python -I "$S/markers.py" "$D" --per-page
