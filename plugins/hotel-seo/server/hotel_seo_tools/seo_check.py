"""Run a vendored claude-seo script (vendor/claude_seo/scripts) the way claude-seo's own runtime does.

- Only allowlisted scripts run, with this server's Python, as a separate process, with no shell.
- API keys come from apikeys.env() as environment variables; they are scrubbed from everything returned.
- Relative paths in the arguments resolve against the work folder (the process runs there).
- Output: parsed JSON when the script printed JSON, else the text. Large output is saved in full to
  <work>/.seo-check/ and the reply carries the file path plus the start of the output, so nothing is lost.
"""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from . import apikeys, paths

VENDOR = Path(__file__).resolve().parent / 'vendor' / 'claude_seo'
SCRIPTS = VENDOR / 'scripts'

# What each script is for (shown by seo_check_list). Every one is read-only except the generators
# (schema_generate, agentic_fix, content_humanize), which only print to stdout or write a file you name.
ALLOWED = {
    'render_page.py': 'Fetch + optional Chromium render: raw/rendered HTML, extracted text, JSON-LD, SPA status',
    'fetch_page.py': 'SSRF-safe fetch with redirect chain and headers',
    'parse_html.py': 'Parse HTML: title, meta, canonical, headings, images, links, JSON-LD, OG, hreflang',
    'metadata_template.py': 'Templated title/description detection (single pair or --pairs-file)',
    'content_quality.py': 'Filler, AI-pattern, density and repetition scores for page text',
    'content_humanize.py': 'Suggest replacements for AI-typical phrasing (prints only)',
    'content_verify.py': 'Find claims without a citation',
    'sitemap_discovery.py': 'robots.txt sitemaps + common sitemap paths, validated',
    'schema_generate.py': 'Generate JSON-LD for Reservation / LodgingReservation and others (prints only)',
    'pagespeed_check.py': 'PageSpeed Insights v5 + CrUX field data (Google API key)',
    'crux_history.py': 'CrUX History API, up to 25 weeks (Google API key)',
    'lcp_subparts.py': 'CrUX LCP subparts (Google API key)',
    'lighthouse_agentic.py': 'Lighthouse Agentic Browsing X/N via PageSpeed Insights',
    'agentic_check.py': 'AI agent access: robots groups, Content-Signal, llms.txt, Markdown, .well-known, WebMCP',
    'agent_ux_check.py': 'Agent-UX accessibility-tree heuristic (Chromium)',
    'agentic_fix.py': 'Draft robots/llms.txt/ai-catalog changes (prints only)',
    'google_auth.py': 'claude-seo Google credential check (--check)',
    'backlinks_auth.py': 'Backlink source credentials check (--check)',
    'commoncrawl_graph.py': 'Common Crawl domain PageRank / harmonic centrality (large download, cached)',
    'verify_backlinks.py': 'Verify known backlinks still exist',
    'moz_api.py': 'Moz DA/PA, spam score, referring domains, anchors, top pages (Moz key; 1 call / 10 s)',
    'bing_webmaster.py': 'Bing Webmaster inbound links (Bing key)',
    'validate_backlink_report.py': 'Mandatory validator for a backlink report JSON',
    'keywordseverywhere_api.py': 'Keywords Everywhere metrics (key; not configured by hotel-seo)',
    'seo_updates.py': 'Primary-source ledger of confirmed Google updates',
}
INLINE_LIMIT = 60000          # characters returned inline; the full output is always saved when larger
OUT_DIR_NAME = '.seo-check'


def _scrub(text, secrets):
    for s in secrets:
        text = text.replace(s, 'REDACTED')
    # Google API keys that were not stored here (e.g. typed into an argument) are scrubbed by shape too.
    return re.sub(r'AIza[0-9A-Za-z_-]{20,}', 'GOOGLE_API_KEY_REDACTED', text)


def listing():
    return {name: desc for name, desc in ALLOWED.items() if (SCRIPTS / name).exists()}


def run(script, args=None, timeout_s=300):
    """Run one allowlisted script. Returns {'ok', 'exit_code', 'json'|'text', 'stderr', 'elapsed_s', ...}."""
    script = (script or '').strip()
    if not script.endswith('.py'):
        script += '.py'
    if script not in ALLOWED or not (SCRIPTS / script).exists():
        return {'ok': False, 'error': f'{script} is not an allowed claude-seo script',
                'allowed': sorted(listing())}
    args = [str(a) for a in (args or [])]
    secrets = apikeys.secrets()
    if any(s in a for s in secrets for a in args):
        return {'ok': False, 'error': 'An API key was passed as an argument. Keys are injected automatically; '
                                      'remove it from the arguments.'}
    env = dict(os.environ)
    env.update(apikeys.env())
    env.update({'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'})
    env.pop('CLAUDE_SEO_LOCAL_TARGETS', None)      # never allow private / local targets
    work = paths.work_dir()
    work.mkdir(parents=True, exist_ok=True)
    started = time.time()
    try:
        proc = subprocess.run([sys.executable, str(SCRIPTS / script), *args], cwd=str(work), env=env,
                              capture_output=True, text=True, encoding='utf-8', errors='replace',
                              timeout=max(10, int(timeout_s)), shell=False)
    except subprocess.TimeoutExpired:
        return {'ok': False, 'error': f'{script} timed out after {timeout_s} s', 'script': script, 'args': args}
    out = _scrub(proc.stdout or '', secrets)
    err = _scrub(proc.stderr or '', secrets)
    res = {'ok': proc.returncode == 0, 'exit_code': proc.returncode, 'script': script, 'args': args,
           'elapsed_s': round(time.time() - started, 1)}
    if err.strip():
        res['stderr'] = err[-4000:]
    parsed = None
    try:
        parsed = json.loads(out) if out.strip() else None
    except ValueError:
        parsed = None
    if len(out) > INLINE_LIMIT:
        d = work / OUT_DIR_NAME
        d.mkdir(parents=True, exist_ok=True)
        f = d / f"{script[:-3]}-{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}.{'json' if parsed is not None else 'txt'}"
        f.write_text(out, encoding='utf-8')
        res.update({'saved_to': str(f), 'size_chars': len(out),
                    'note': 'Output was large: the full output is in saved_to (read it with read_crawl_file).',
                    'preview': out[:INLINE_LIMIT // 4]})
        if isinstance(parsed, dict):
            res['top_level_keys'] = sorted(parsed)[:60]
        return res
    if parsed is not None:
        res['json'] = parsed
    else:
        res['text'] = out
    return res
