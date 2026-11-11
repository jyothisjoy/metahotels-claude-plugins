#!/bin/bash
# usage (from the site folder): bash <skill>/scripts/judge-live.sh <label> [url]
# One state of the live site, for before/after numbers of a batch: three throttled-phone sets (throttle.js, 3 runs
# each) with a PageSpeed run (mobile + desktop) after each set, so the PageSpeed runs are well over 35 s apart.
# Output: audit/judge-<label>.txt (first used on Gewan, 2026-10-15).
# pwd -W gives a Windows path in Git Bash, which Python and Node accept even with MSYS_NO_PATHCONV=1
S="$(cd "$(dirname "$0")" && (pwd -W 2>/dev/null || pwd))"
eval "$(python -I "$S/wp/sitecfg.py" --shell)" || exit 1
L=$1
U=${2:-$SITE_URL}
[ -z "$L" ] && { echo "usage: bash judge-live.sh <label> [url]"; exit 1; }
mkdir -p audit
OUT="audit/judge-$L.txt"
: > "$OUT"
for s in 1 2 3; do
  node "$S/throttle.js" "$L-s$s" "$U" 3 2>&1 | grep -i median >> "$OUT"
  python -I "$S/psi.py" "$L-$s" "$U" "$SITE_PSI_ENV" 2>&1 | grep -E "mobile|desktop" >> "$OUT"
done
echo "--- PageSpeed breakdown" >> "$OUT"
python -I "$S/psi_breakdown.py" "$SITE_HOST" "$L-1" "$L-2" "$L-3" 2>&1 | cut -c1-150 >> "$OUT"
echo done >> "$OUT"
cat "$OUT"
