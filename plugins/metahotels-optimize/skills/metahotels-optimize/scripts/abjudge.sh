#!/bin/bash
# usage (from the site folder): bash <skill>/scripts/abjudge.sh <out.txt> [--url=<url>] [--wait=4000] [--vary] <rules.json|-> ...
# Simulated A/B before anything is saved: three sets of 3 throttled mobile runs per variant (abhtml.js applies each
# rule file to the live HTML; "-" is the control), variants alternating inside each set so drift hits all of them
# equally. abhtml.js serves the document uncompressed through interception, so compare variants with each other here,
# never with throttle.js numbers (references/testing.md). For "what gates first paint" use checks/floor.js instead.
# Generalised from Gewan's judge-home.sh (2026-10-15).
# pwd -W gives a Windows path in Git Bash, which Python and Node accept even with MSYS_NO_PATHCONV=1
S="$(cd "$(dirname "$0")" && (pwd -W 2>/dev/null || pwd))"
OUT=$1; shift
eval "$(python -I "$S/wp/sitecfg.py" --shell)" || exit 1
U="$SITE_URL"; W=4000; R=(); X=()
for a in "$@"; do
  case "$a" in --url=*) U="${a#--url=}";; --wait=*) W="${a#--wait=}";; --vary) X+=(--vary);; *) R+=("$a");; esac
done
[ ${#R[@]} -eq 0 ] && { echo "usage: bash abjudge.sh <out.txt> [--url=] [--wait=] <rules.json|-> ..."; exit 1; }
: > "$OUT"
for s in 1 2 3; do
  for r in "${R[@]}"; do
    lab=$(basename "$r" .json); [ "$r" = "-" ] && lab=ctrl
    node "$S/abhtml.js" "$lab-s$s" "$U" "$r" 3 --wait="$W" "${X[@]}" 2>&1 | grep median >> "$OUT"
  done
done
echo done >> "$OUT"
cat "$OUT"
