# usage: python -I psi_breakdown.py <host> <label> [label ...]
# Reads the PageSpeed JSON that psi.py saved (runs/<host>/psi-<label>-<strategy>.json).
#   one label    -> where the score is lost: points per metric, script time per file, third parties, long tasks
#   many labels  -> one line per run, to compare states (PSI mobile is bimodal: compare like with like)
# PageSpeed serves a cached result for ~30 s, so leave 35 s between psi.py runs or two "runs" are the same run.
import json, os, sys

host, labels = sys.argv[1], sys.argv[2:]
base = os.path.join(os.environ.get('PERF_RUNS') or os.path.abspath('runs'), host)

def load(label, strat):
    d = json.load(open(os.path.join(base, 'psi-%s-%s.json' % (label, strat)), encoding='utf-8'))
    return d.get('lighthouseResult', d)

def val(a, k):
    return (a.get(k) or {}).get('displayValue', '').replace(' ', '')

def items(a, k):
    return ((a.get(k) or {}).get('details') or {}).get('items') or []

if len(labels) > 1:
    for label in labels:
        for strat in ('mobile', 'desktop'):
            try:
                lh = load(label, strat)
            except Exception as e:
                print(label, strat, 'not found'); continue
            a = lh['audits']
            rb = items(a, 'render-blocking-resources') or items(a, 'render-blocking-insight')
            print(label.ljust(10), strat.ljust(8), 'score', str(round(lh['categories']['performance']['score'] * 100)).rjust(3),
                  '| FCP', val(a, 'first-contentful-paint'), 'LCP', val(a, 'largest-contentful-paint'), 'TBT', val(a, 'total-blocking-time'),
                  'CLS', val(a, 'cumulative-layout-shift'), 'SI', val(a, 'speed-index'), '| render-blocking', len(rb),
                  '| weight', round((a.get('total-byte-weight') or {}).get('numericValue', 0) / 1024), 'KB', lh.get('fetchTime', '')[11:19])
    sys.exit()

for strat in ('desktop', 'mobile'):
    lh = load(labels[0], strat); a = lh['audits']
    print('=====', strat, '| Lighthouse', lh.get('lighthouseVersion'), '| score', round(lh['categories']['performance']['score'] * 100))
    for ref in lh['categories']['performance']['auditRefs']:
        if ref.get('weight'):
            x = a[ref['id']]; sc = x.get('score') or 0
            print('  %-26s weight %2d  %-9s -> points lost %4.1f' % (ref['id'], ref['weight'], x.get('displayValue', '').replace(' ', ''), ref['weight'] * (1 - sc)))
    m = (items(a, 'metrics') or [{}])[0]
    print('  observed in the trace: FCP', m.get('observedFirstContentfulPaint'), 'LCP', m.get('observedLargestContentfulPaint'), 'DCL', m.get('observedDomContentLoaded'), 'load', m.get('observedLoad'))
    print('  script time by file (total ms / scripting ms):')
    for it in sorted(items(a, 'bootup-time'), key=lambda x: -x.get('total', 0))[:8]:
        print('    %6d / %6d  %s' % (it.get('total', 0), it.get('scripting', 0), str(it.get('url', ''))[:90]))
    print('  main thread:', {it['groupLabel']: round(it['duration']) for it in items(a, 'mainthread-work-breakdown')})
    tp = items(a, 'third-party-summary') or items(a, 'third-parties-insight')
    print('  third parties (main-thread ms, KB):')
    for it in sorted(tp, key=lambda x: -(x.get('mainThreadTime') or 0))[:8]:
        ent = it.get('entity'); ent = ent.get('text') if isinstance(ent, dict) else ent
        print('    %-26s %6d ms %6d KB' % (str(ent)[:26], it.get('mainThreadTime', 0), round((it.get('transferSize') or 0) / 1024)))
    lt = sorted(items(a, 'long-tasks'), key=lambda x: -x['duration'])
    print('  long tasks:', len(lt), [(round(x['duration']), str(x.get('url', ''))[-45:]) for x in lt[:6]])
