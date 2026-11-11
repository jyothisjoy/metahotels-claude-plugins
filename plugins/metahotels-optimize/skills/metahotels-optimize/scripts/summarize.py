# usage: node measure.js <label> <url> [runs] | python summarize.py
# One line per measure.js run: timings, requests by type, third parties, failed requests, console errors, reCAPTCHA
# and repeated booking-engine API calls.
import json,sys
txt=sys.stdin.read();dec=json.JSONDecoder();i=0
while True:
  j=txt.find('{',i)
  if j<0: break
  o,i=dec.raw_decode(txt,j)
  p=o['perf'];t=o['totals']
  print(f"{o['profile']:8} ttfb={p['ttfb']} fcp={p['fcp']} dcl={p['dcl']} load={p['load']} lcp={p['lcp']} cls={p['cls']} tbt~{p['tbtProxy']} | req={t['requests']} 3p={t['thirdParty']} KB={t['totalKB']} css={t['byType'].get('css')} js={t['byType'].get('js')} font={t['byType'].get('font')} | failed={[f[:90] for f in t['failed'] if 'collect' not in f and '.mp4' not in f]} console={o['console']} recaptcha={len(o['recaptcha'])} repeatedApi={o['repeatedApiCalls']}")
