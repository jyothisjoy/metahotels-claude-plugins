"""Write the rule files that abhtml.js / simhtml.js / weight.js / floor.js apply to the live HTML, to simulate a
planned change before anything is saved on the site. Each rule changes only what the test browser receives.

Usage (from the site folder): python -I <skill>/scripts/wp/make-rules.py <kind> [options] [-o tests/rules-<x>.json]
Without -o the rules are printed. Written as JSON by this script so regexes keep their backslashes.

kinds (merged from the Abar, Shams and Khalidia generators, 2026-10-12..13):
  noop                                  control: a no-op change, to measure run-to-run noise
  dialog-css   [--ver=4.3.4]            Elementor's popup dialog stylesheet printed with the page, before
                                        elementor-frontend (pattern "popup scrolls the page"). --ver defaults to the
                                        version on elementor-frontend-css in --html (a saved homepage)
  entrance     [--names=fadeInUp,...] [--no-header]
                                        entrance animations of the header and the first section start at first
                                        paint (pattern "header and hero hidden until Elementor's script runs"); the
                                        same CSS metahotels-core's switch and the site plugins print
  no-entrance  --html=<page.html> --ids=<id,id>
                                        remove the entrance animation from these elements (as if set to None)
  chatbot      --html=<page or snippet html>
                                        MetaHotels chat widget loaded on the first interaction after load
  hero         --selector=<css> --image=<url> [--no-preload] [--lazy]
                                        hero slideshow: slide 1 painted from CSS (and preloaded) until the slideshow
                                        shows it; --lazy waits for Swiper's lazy image (slideshow "Lazyload" on)
  preload      --image=<url>            <link rel=preload as=image fetchpriority=high> only
  reserve      --selector=<css> --css="width:637px;min-height:54px" [--media="(min-width:768px)"]
                                        reserve a booking-engine wrapper's settled size (finder CLS)
  drop         --pattern=<regex>        remove every <link>/<script> tag whose URL matches (addon assets test)
  combine      <a.json> <b.json> ...    concatenate rule files
Options taking a page read it with --html; dialog-css also needs the origin (site.json, or --origin=https://...).
"""
import base64  # noqa: F401  (kept for icon-subset data URIs built by hand)
import json
import os
import re
import sys

args = [a for a in sys.argv[1:] if not a.startswith('--') and a != '-o']
opt = {a[2:].split('=', 1)[0]: (a.split('=', 1)[1] if '=' in a else True) for a in sys.argv[1:] if a.startswith('--')}
out = sys.argv[sys.argv.index('-o') + 1] if '-o' in sys.argv else None
if out in args:
    args.remove(out)
if not args:
    sys.exit(__doc__)
kind, rest = args[0], args[1:]


def need(k):
    if k not in opt or opt[k] is True:
        sys.exit('%s needs --%s=...' % (kind, k))
    return opt[k]


def html():
    return open(need('html'), encoding='utf-8', errors='replace', newline='').read()


def origin():
    if opt.get('origin'):
        return opt['origin'].rstrip('/')
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import sitecfg
    return sitecfg.load()['origin']


CHAT_FIND = (r'<script src="(https://storage\.googleapis\.com/hdr_chatbot_uploads/libs/js/v[\d.]+/directchat-widget\.js)">'
             r'</script>\s*<script>\s*(DirectChat\.init\(\{.*?\}\))\s*</script>')
CHAT_REPLACE = """<script>
/* Chat widget: loaded on the visitor's first interaction (scroll, mouse move, tap, click or key press)
   once the page has finished loading, so its 1.4 MB script never holds up the page, the hero
   or the booking engine, and is not downloaded by visitors who leave without interacting. */
(function () {
  var started = false, wanted = false, ready = document.readyState === 'complete';
  function loadChat() {
    if (started || !wanted || !ready) { return; }
    started = true;
    var s = document.createElement('script');
    s.src = '$1';
    s.async = true;
    s.onload = function () {
      $2;
    };
    document.body.appendChild(s);
  }
  function want() { wanted = true; loadChat(); }
  ['scroll', 'mousemove', 'pointerdown', 'touchstart', 'keydown'].forEach(function (ev) {
    window.addEventListener(ev, want, { once: true, passive: true });
  });
  if (!ready) { window.addEventListener('load', function () { ready = true; loadChat(); }); }
})();
</script>"""

SCOPES_FIRST = ['[data-elementor-type="wp-page"]>.elementor-element:first-child ',
                '[data-elementor-type="wp-page"]>.elementor-element:first-child',
                '[data-elementor-type="wp-post"]>.elementor-element:first-child ',
                '[data-elementor-type="wp-post"]>.elementor-element:first-child']


def entrance_css(names, header=True):
    scopes = (['.elementor-location-header '] if header else []) + SCOPES_FIRST

    def sel(suffix):
        return ','.join(s + '.elementor-invisible' + suffix for s in scopes)
    base = ''.join(sel("[data-settings*='animation\":\"%s\"']" % n) + '{visibility:visible;animation-name:%s;animation-duration:1.25s}' % n for n in names)
    base += sel('.animated-slow') + '{animation-duration:2s}' + sel('.animated-fast') + '{animation-duration:.75s}'
    tablet = sel("[data-settings*='animation_tablet\":\"none\"']") + '{animation-name:none}'
    tablet += ''.join(sel("[data-settings*='animation_tablet\":\"%s\"']" % n) + '{animation-name:%s}' % n for n in names)
    mobile = sel("[data-settings*='animation_mobile\":\"none\"']") + '{animation-name:none}'
    mobile += ''.join(sel("[data-settings*='animation_mobile\":\"%s\"']" % n) + '{animation-name:%s}' % n for n in names)
    show = sel("[data-settings*='animation\":\"']") + '{visibility:visible}'
    return ('@media (prefers-reduced-motion:no-preference){' + base + '@media (max-width:1024px){' + tablet
            + '}@media (max-width:767px){' + mobile + '}}@media (prefers-reduced-motion:reduce){' + show + '}')


if kind == 'noop':
    rules = [{'find': '</head>', 'replace': ' </head>'}]
elif kind == 'dialog-css':
    ver = opt.get('ver')
    if not ver:
        # the generator meta tag; elementor-frontend-css carries a cache-busting number when custom breakpoints
        # make Elementor serve uploads/elementor/css/custom-frontend.min.css
        m = re.search(r'<meta name="generator" content="Elementor ([\d.]+)', html())
        ver = m.group(1) if m else sys.exit('no Elementor generator tag in --html; pass --ver=')
    rules = [{'find': "<link(?=[^>]*id='elementor-frontend-css')", 'regex': True,
              'replace': "<link rel='stylesheet' id='perf-e-dialog-css' href='%s/wp-content/plugins/elementor/assets/css/"
                         "conditionals/dialog.min.css?ver=%s' media='all' />\n<link" % (origin(), ver)}]
elif kind == 'entrance':
    names = (opt.get('names') or 'fadeInUp,fadeInDown,slideInDown').split(',')
    rules = [{'find': '</head>', 'replace': '<style id="perf-entrance">' + entrance_css(names, not opt.get('no-header')) + '</style>\n</head>'}]
elif kind == 'no-entrance':
    page = html()
    rules = []
    for eid in need('ids').split(','):
        m = re.search(r'<div class="[^"]*elementor-element-' + eid + r'[^"]*"[^>]*>', page)
        if not m:
            sys.exit('element %s not in the page' % eid)
        tag = m.group(0)
        new = tag.replace(' elementor-invisible', '')
        new = re.sub(r'&quot;animation&quot;:&quot;[a-zA-Z]+&quot;,?', '', new)
        new = re.sub(r'&quot;animation_delay&quot;:\d+,?', '', new)
        new = new.replace(',}', '}').replace(' data-settings="{}"', '')
        rules.append({'find': tag, 'replace': new})
elif kind == 'chatbot':
    m = re.search(CHAT_FIND, html(), re.S)
    if not m:
        sys.exit('the MetaHotels chat widget snippet is not in --html')
    # abhtml.js inserts the replacement literally, so the URL and the init call are copied in here
    rules = [{'find': CHAT_FIND, 'regex': True, 'flags': 's',
              'replace': CHAT_REPLACE.replace('$1', m.group(1)).replace('$2', m.group(2))}]
elif kind in ('hero', 'preload'):
    img = need('image')
    pre = '<link rel="preload" as="image" href="%s" fetchpriority="high">' % img
    if kind == 'preload':
        rules = [{'find': '</title>', 'replace': '</title>' + pre}]
    else:
        h = need('selector')
        active = (h + ':has(> .elementor-background-slideshow .swiper-slide-active .swiper-lazy-loaded),'
                  + h + ':has(> .elementor-background-slideshow .swiper-slide-active:not(:has(.swiper-lazy)))') \
            if opt.get('lazy') else h + ':has(> .elementor-background-slideshow .swiper-slide-active)'
        css = ('%s{background:url("%s") center center/cover no-repeat}%s{animation:perf-hero-static-off 0s 1.5s forwards}'
               '@keyframes perf-hero-static-off{to{background-image:none}}') % (h, img, active)
        rules = [{'find': '</title>', 'replace': '</title>' + ('' if opt.get('no-preload') else pre) + '<style id="perf-hero">' + css + '</style>'}]
elif kind == 'reserve':
    media = opt.get('media') or '(min-width:768px)'
    rules = [{'find': '</title>', 'replace': '</title><style>@media %s{%s{%s}}</style>' % (media, need('selector'), need('css'))}]
elif kind == 'drop':
    rules = [{'find': r'<(?:script|link)\b[^>]*(?:src|href)=["\'][^"\']*(?:%s)[^"\']*["\'][^>]*>(?:</script>)?' % need('pattern'),
              'regex': True, 'flags': 'g', 'replace': ''}]
elif kind == 'combine':
    rules = [r for f in rest for r in json.load(open(f, encoding='utf-8'))]
else:
    sys.exit('unknown kind %r\n\n%s' % (kind, __doc__))

text = json.dumps(rules, indent=1, ensure_ascii=False)
if out:
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    open(out, 'w', encoding='utf-8', newline='\n').write(text + '\n')
    print('wrote', out, len(rules), 'rule(s)')
else:
    print(text)
