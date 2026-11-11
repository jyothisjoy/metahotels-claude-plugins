#!/bin/bash
# usage (from the site folder): bash <skill>/scripts/warm.sh <label>
# Re-warm after every Purge All and every plugin upload (both empty the whole LiteSpeed cache): fetches every URL
# in audit/urls.txt once, 1.5 s apart, saves the HTML to audit/pages-<label>/ (crawl.sh layout: <n>.html, <n>.h,
# index.tsv) and prints status codes, database errors, slow pages, cache hits and the pages carrying each marker
# (markers.py, plus the site plugin's markers from site.json). A database error pauses 20 s: Gevora's database
# dropped for about 30 s right after a Purge All.
label=${1:-warm}
# pwd -W gives a Windows path in Git Bash, which Python and Node accept even with MSYS_NO_PATHCONV=1
S="$(cd "$(dirname "$0")" && (pwd -W 2>/dev/null || pwd))"
[ -f audit/urls.txt ] || { echo "audit/urls.txt missing: run from the site folder (references/site-setup.md)"; exit 1; }
D="audit/pages-$label"
LOG="audit/$label.log"
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
rm -rf "$D" && mkdir -p "$D" && : > "$LOG" && : > "$D/index.tsv"
i=0
while read -r u; do
  u=$(echo "$u" | tr -d '\r'); [ -z "$u" ] && continue
  i=$((i+1)); f="$D/$i.html"
  r=$(curl -s --compressed --max-time 90 --retry 2 -A "$UA" -D "$D/$i.h" "$u" -o "$f" -w "%{http_code} %{time_total} %{size_download}")
  set -- $r
  c=$(grep -i '^x-litespeed-cache:' "$D/$i.h" | tr -d '\r' | sed 's/.*: //')
  echo "$i $1 $2 $3 $u" >> "$LOG"
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$i" "$1" "$3" "$2" "${c:--}" "$u" >> "$D/index.tsv"
  if grep -q "Error establishing a database connection" "$f"; then echo "DB ERROR $u" >> "$LOG"; sleep 20; fi
  sleep 1.5
done < audit/urls.txt
echo "status: $(awk '$1 ~ /^[0-9]+$/ {print $2}' "$LOG" | sort | uniq -c | tr '\n' ' ')"
echo "db errors: $(grep -c 'DB ERROR' "$LOG")"
awk '$1 ~ /^[0-9]+$/ {s+=$3; n++} END {if (n) print "avg s", s/n}' "$LOG"
awk '$1 ~ /^[0-9]+$/ && $3>6 {print "slow:",$3,$5}' "$LOG" | head -5
echo "x-litespeed-cache hit/miss: $(grep -l -i 'x-litespeed-cache: hit' "$D"/*.h 2>/dev/null | wc -l)/$(grep -l -i 'x-litespeed-cache: miss' "$D"/*.h 2>/dev/null | wc -l)   x-qc-cache hit: $(grep -l -i 'x-qc-cache: hit' "$D"/*.h 2>/dev/null | wc -l)"
python -I "$S/markers.py" "$D"
