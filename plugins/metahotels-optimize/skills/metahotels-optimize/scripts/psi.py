# usage: python -I psi.py <label> <url> [path-to-.env-with-PAGESPEED_API_KEY]
# Runs PageSpeed Insights (mobile + desktop), prints key metrics + CrUX field data, saves full JSON to runs/<host>/psi-<label>-<strategy>.json.
# Run it at least twice per state; mobile lab results are very noisy. Trust desktop lab + CrUX field data more.
# The key: the given .env, else the site folder's or the work folder's .env (init.py creates it), else the
# PAGESPEED_API_KEY environment variable. The key is never printed.
import json, os, sys, urllib.parse, urllib.request
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'wp'))
import sitecfg  # noqa: E402

label, url = sys.argv[1], sys.argv[2]
env = sys.argv[3] if len(sys.argv) > 3 else sitecfg.psi_env()
key = sitecfg.read_key(env) or os.environ.get('PAGESPEED_API_KEY', '')
if not key:
    sys.exit('No PageSpeed API key: put PAGESPEED_API_KEY=<key> in %s (Google Cloud console, "PageSpeed Insights API" key)' % os.path.abspath(env))
host = urllib.parse.urlparse(url).netloc
out_dir = os.path.join(os.environ.get('PERF_RUNS') or os.path.abspath('runs'), host)
os.makedirs(out_dir, exist_ok=True)
out = {}
for strat in ('mobile', 'desktop'):
    api = 'https://www.googleapis.com/pagespeedonline/v5/runPagespeed?' + urllib.parse.urlencode({'url': url, 'strategy': strat, 'category': 'performance', 'key': key})
    d = json.load(urllib.request.urlopen(api, timeout=180))
    a = d['lighthouseResult']['audits']
    out[strat] = {
        'score': round(d['lighthouseResult']['categories']['performance']['score'] * 100),
        **{k: a[k]['displayValue'] for k in ('first-contentful-paint', 'largest-contentful-paint', 'total-blocking-time', 'cumulative-layout-shift', 'speed-index') if k in a},
        'requests': len(a.get('network-requests', {}).get('details', {}).get('items', [])),
        'field': {m: v.get('percentile') for m, v in d.get('loadingExperience', {}).get('metrics', {}).items()},
    }
    open(os.path.join(out_dir, f'psi-{label}-{strat}.json'), 'w').write(json.dumps(d))
print(json.dumps(out, indent=1))
