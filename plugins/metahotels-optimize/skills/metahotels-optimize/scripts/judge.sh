#!/bin/bash
# usage (from the site folder): bash <skill>/scripts/judge.sh <label> [--lazy] [--vary] [url]   (--vary: Guest Mode sites, throttle.js --vary)
# A/B judge for one state of the site: one LiteSpeed option switched on (save it, purge the front page first), or
# the control with nothing changed. Writes audit/judge-<label>.txt:
#   - three fetches of the page (cache state, TTFB) and the HTML markers of the cached copy (markers.py)
#   - three PageSpeed runs (mobile + desktop) with two throttled-phone sets of 3 runs between them, so the
#     PageSpeed runs are well over 35 s apart (PageSpeed serves a cached result for about 30 s)
#   - the cold-load check (fresh browser per run) on the page and on site.json pages.inner
#   - the interaction test (what loads before and after the first input, JS errors)
#   - with --lazy: late-images and carousel checks on the page and on site.json pages.carousel
# Merged from the Abar, Shams and Khalidia judges (2026-10-12..14). One test browser at a time. No re-warm, sweep or
# MCP save while an option is on: every page generated meanwhile is built with it (playbook, LiteSpeed options).
# pwd -W gives a Windows path in Git Bash, which Python and Node accept even with MSYS_NO_PATHCONV=1
S="$(cd "$(dirname "$0")" && (pwd -W 2>/dev/null || pwd))"
eval "$(python -I "$S/wp/sitecfg.py" --shell)" || exit 1
L="$1"; shift
LAZY=0; U="$SITE_URL"; VARY=""
for a in "$@"; do case "$a" in --lazy) LAZY=1;; --vary) VARY="--vary";; *) U="$a";; esac; done
[ -z "$L" ] && { echo "usage: bash judge.sh <label> [--lazy] [url]"; exit 1; }
mkdir -p audit
OUT="audit/judge-$L.txt"
H="audit/judge-$L.html"
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
export MSYS_NO_PATHCONV=1
{
  echo "##### $L  $U  $(date +%H:%M:%S)"
  for i in 1 2 3; do
    curl -s --retry 2 --max-time 120 --compressed -A "$UA" -D "audit/judge-$L.h" -o "$H" -w "fetch $i: %{http_code} ttfb=%{time_starttransfer} " "$U"
    grep -iE '^(x-litespeed-cache|x-qc-cache):' "audit/judge-$L.h" | tr '\r\n' '  '; echo
    sleep 2
  done
  echo "markers: $(python -I "$S/markers.py" "$H")"
  python -I "$S/psi.py" "$L-1" "$U" "$SITE_PSI_ENV" > /dev/null 2>&1
  echo "--- throttled phone (Slow 4G, 4x CPU)"; node "$S/throttle.js" "$L-1" "$U" 3 $VARY 2>&1 | sed 's/.*| median/median/'
  python -I "$S/psi.py" "$L-2" "$U" "$SITE_PSI_ENV" > /dev/null 2>&1
  node "$S/throttle.js" "$L-2" "$U" 3 $VARY 2>&1 | sed 's/.*| median/median/'
  python -I "$S/psi.py" "$L-3" "$U" "$SITE_PSI_ENV" > /dev/null 2>&1
  echo "--- PageSpeed"; python -I "$S/psi_breakdown.py" "$SITE_HOST" "$L-1" "$L-2" "$L-3" 2>&1 | cut -c1-150
  echo "--- cold check (fresh browser per run)"
  node "$S/checks/coldcheck.js" "$U" 3 2>&1 | cut -c1-300
  [ "$SITE_INNER" != "$U" ] && node "$S/checks/coldcheck.js" "$SITE_INNER" 2 2>&1 | cut -c1-300
  echo "--- interaction"; node "$S/checks/interaction.js" "$U" mobile --label="judge-$L" 2>&1 | cut -c1-700
  if [ "$LAZY" = 1 ]; then
    for p in "$U" "$SITE_CAROUSEL?lz=$(date +%s)"; do
      echo "--- late images $p"; node "$S/checks/late-images.js" "$p" mobile 2>&1 | tail -6 | cut -c1-300
      echo "--- carousels $p"; node "$S/checks/carousel-check.js" "$p" mobile 2>&1 | tail -6 | cut -c1-300
    done
  fi
  echo "##### done $(date +%H:%M:%S)"
} > "$OUT" 2>&1
cut -c1-400 "$OUT"
