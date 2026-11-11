"""Rewrite the chatbot Custom Code snippets so the widget loads on the visitor's first interaction.

Usage (from the site folder): python -I <skill>/scripts/wp/chatbot-lazy.py <snippet id> [<id> ...] [--apply] [--restore]
  default   fetch each snippet, save rollback/chatbot-snippet-<id>-original.html (once), write the new code to
            rollback/chatbot-snippet-<id>-lazy.html and print a summary. Nothing is changed on the site.
  --apply   also save the new code to the site (REST, meta._elementor_code) and read it back.
  --restore write rollback/chatbot-snippet-<id>-original.html back to the site.
The script URL and the DirectChat.init({...}) call are copied from each snippet unchanged. Matches the MetaHotels
chat widget (storage.googleapis.com/hdr_chatbot_uploads ... directchat-widget.js); any other snippet is skipped.
"""
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sitecfg  # noqa: E402

SERVER = sitecfg.load()['mcp_server']
rollback = os.path.abspath('rollback')
os.makedirs(rollback, exist_ok=True)
ids = [a for a in sys.argv[1:] if a.isdigit()]
apply = '--apply' in sys.argv
restore = '--restore' in sys.argv

import mcpconf  # noqa: E402
cfg = mcpconf.get(SERVER)
BASE = mcpconf.base(cfg)


def rest(method, path, body=None):
    req = urllib.request.Request(
        BASE + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={'Authorization': cfg['headers']['Authorization'], 'Content-Type': 'application/json',
                 'User-Agent': 'Mozilla/5.0 perf-audit'})
    with urllib.request.urlopen(req, timeout=60) as f:
        return json.loads(f.read().decode())


FIND = re.compile(
    r'<script src="(https://storage\.googleapis\.com/hdr_chatbot_uploads/libs/js/v[\d.]+/directchat-widget\.js)">'
    r'</script>\s*<script>\s*(DirectChat\.init\(\{.*?\}\))\s*</script>', re.S)

TEMPLATE = """<script>
/* Chat widget: loaded on the visitor's first interaction (scroll, mouse move, tap, click or key press)
   once the page has finished loading, so its 1.4 MB script never holds up the page, the hero
   or the booking engine, and is not downloaded by visitors who leave without interacting.
   If this code itself only runs after the load (LiteSpeed Guest Mode holds inline scripts until the
   first interaction), that interaction has already happened, so the widget loads straight away. */
(function () {
  var started = false, ready = document.readyState === 'complete', wanted = ready;
  function loadChat() {
    if (started || !wanted || !ready) { return; }
    started = true;
    var s = document.createElement('script');
    s.src = '%(src)s';
    s.async = true;
    s.onload = function () {
      %(init)s;
    };
    document.body.appendChild(s);
  }
  function want() { wanted = true; loadChat(); }
  ['scroll', 'mousemove', 'pointerdown', 'touchstart', 'keydown'].forEach(function (ev) {
    window.addEventListener(ev, want, { once: true, passive: true });
  });
  if (ready) { loadChat(); } else { window.addEventListener('load', function () { ready = true; loadChat(); }); }
})();
</script>"""


def save(path, text):
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write(text)


for sid in ids:
    path = '/wp-json/wp/v2/elementor_snippet/%s?context=edit' % sid
    orig_file = os.path.join(rollback, 'chatbot-snippet-%s-original.html' % sid)
    if restore:
        code = open(orig_file, encoding='utf-8', newline='').read()
        rest('POST', path, {'meta': {'_elementor_code': code}})
        back = rest('GET', path)['meta']['_elementor_code']
        print(sid, 'restored', 'OK' if back == code else 'MISMATCH')
        continue
    s = rest('GET', path)
    code = s['meta']['_elementor_code']
    title = s['title'].get('raw') or s['title'].get('rendered')
    if 'addEventListener' in code:
        print(sid, title, '| already rewritten, skipped')
        continue
    m = FIND.search(code)
    if not m or code.strip() != m.group(0).strip():
        print(sid, title, '| unexpected content, skipped')
        continue
    if not os.path.exists(orig_file):
        save(orig_file, code)
    init = re.sub(r'\r?\n', '\n    ', m.group(2))
    new = (TEMPLATE % {'src': m.group(1), 'init': init}).replace('\n', '\r\n' if '\r\n' in code else '\n')
    save(os.path.join(rollback, 'chatbot-snippet-%s-lazy.html' % sid), new)
    key = re.search(r'(pid|chainId):\s*"([^"]+)"', m.group(2))
    print(sid, title, '|', s['status'], '|', s['meta'].get('_elementor_location'), '|', m.group(1).split('/')[-2],
          '|', key.group(1), key.group(2), '|', len(code), '->', len(new), 'bytes', end='')
    if apply:
        rest('POST', path, {'meta': {'_elementor_code': new}})
        back = rest('GET', path)
        ok = back['meta']['_elementor_code'] == new and back['status'] == s['status'] \
            and back['meta'].get('_elementor_location') == s['meta'].get('_elementor_location')
        print(' | applied', 'OK' if ok else 'MISMATCH')
    else:
        print(' | dry run')
