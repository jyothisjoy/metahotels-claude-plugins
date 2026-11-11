#!/bin/bash
# usage: bash crawl.sh <urls.txt> <out-dir>
# Fetches every URL once (logged out, 1 s apart), saves the HTML as <out-dir>/<n>.html and writes
# <out-dir>/index.tsv: n, status, x-litespeed-cache, bytes, seconds, url. A status 000 is retried by curl.
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
urls=$1
out=$2
mkdir -p "$out"
: > "$out/index.tsv"
n=0
while read -r u; do
  [ -z "$u" ] && continue
  n=$((n + 1))
  res=$(curl -s --retry 2 --max-time 90 --compressed -A "$UA" -D "$out/$n.h" -o "$out/$n.html" -w "%{http_code}\t%{size_download}\t%{time_total}" "$u")
  ls=$(grep -i '^x-litespeed-cache:' "$out/$n.h" | tr -d '\r' | sed 's/.*: //')
  printf "%s\t%s\t%s\t%s\n" "$n" "$res" "${ls:--}" "$u" >> "$out/index.tsv"
  rm -f "$out/$n.h"
  sleep 1.5
done < "$urls"
echo "crawled $n" > "$out/done.txt"
