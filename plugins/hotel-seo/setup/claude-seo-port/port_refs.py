import re, shutil, sys, pathlib
SRC = pathlib.Path(sys.argv[1]); DST = pathlib.Path(sys.argv[2])
copies = {
 'seo': [SRC/'skills/seo/references'/f for f in ['quality-gates.md','eeat-framework.md','eeat-scoring-guide.md','cwv-thresholds.md','schema-types.md','local-schema-types.md','local-schema-multilocation.md','local-search-behavior.md','local-seo-signals.md','maps-api-endpoints.md','maps-free-apis.md','maps-gbp-checklist.md','maps-geo-grid.md','backlink-quality.md','free-backlink-sources.md','thinking-framework.md','thinking-framework-validate-act.md']],
 'technical': [SRC/'skills/seo-technical/SKILL.md', SRC/'skills/seo-technical/references/stack-cve-exposure.md'],
 'content': [SRC/'skills/seo-content/SKILL.md'],
 'schema': [SRC/'skills/seo-schema/SKILL.md', SRC/'skills/seo-schema/references/deprecated-types-2024-2026.md'],
 'sitemap': [SRC/'skills/seo-sitemap/SKILL.md'],
 'geo': [SRC/'skills/seo-geo/SKILL.md', SRC/'skills/seo-geo/references/google-ai-optimization-guide.md', SRC/'skills/seo-geo/references/llmstxt-evidence.md'],
 'agentic': [SRC/'skills/seo-agentic/SKILL.md'] + sorted((SRC/'skills/seo-agentic/references').glob('*.md')),
 'local': [SRC/'skills/seo-local/SKILL.md'],
 'maps': [SRC/'skills/seo-maps/SKILL.md'],
 'backlinks': [SRC/'skills/seo-backlinks/SKILL.md'],
 'flow': [SRC/'skills/seo-flow/SKILL.md', SRC/'skills/seo-flow/references/flow-framework.md', SRC/'skills/seo-flow/references/bibliography.md'],
}
REF_MAP = {'skills/seo/references/': 'skills/hotel-seo/references/claude-seo/seo/',
           'skills/seo-technical/references/': 'skills/hotel-seo/references/claude-seo/technical/',
           'skills/seo-geo/references/': 'skills/hotel-seo/references/claude-seo/geo/',
           'skills/seo-agentic/references/': 'skills/hotel-seo/references/claude-seo/agentic/',
           'skills/seo-schema/references/': 'skills/hotel-seo/references/claude-seo/schema/',
           'skills/seo-flow/references/': 'skills/hotel-seo/references/claude-seo/flow/'}

def cmd(m):
    script, args = m.group(1), m.group(2).strip()
    parts = re.findall(r'"[^"]*"|\'[^\']*\'|\S+', args) if args else []
    return 'seo_check("%s", [%s])' % (script, ', '.join('"%s"' % p.strip('"\'') for p in parts))

def rewrite(text):
    text = re.sub(r'"?\$\{CLAUDE_PLUGIN_ROOT\}/scripts/claude-seo"?\s+run\s+([a-z_]+\.py)([^\n`|]*)', cmd, text)
    text = re.sub(r'(?<![\w/])\.?/?scripts/claude-seo\s+run\s+([a-z_]+\.py)([^\n`|]*)', cmd, text)
    for a, b in REF_MAP.items():
        text = text.replace('${CLAUDE_PLUGIN_ROOT}/' + a, '${CLAUDE_PLUGIN_ROOT}/' + b)
    text = text.replace('${CLAUDE_PLUGIN_ROOT}/schema/templates.json',
                        '${CLAUDE_PLUGIN_ROOT}/server/hotel_seo_tools/vendor/claude_seo/schema/templates.json')
    return text

HEADER = ('<!-- Ported from claude-seo v2.5.0 (MIT, (c) 2026 agricidaniel), {src}. Commands rewritten for hotel-seo: '
          'claude-seo scripts run through the seo_check MCP tool; hotel rules in ../../hotel-addendum.md win where they differ. -->\n')
for folder, files in copies.items():
    d = DST / folder
    d.mkdir(parents=True, exist_ok=True)
    for f in files:
        name = 'skill.md' if f.name == 'SKILL.md' else f.name
        out = HEADER.format(src=f.relative_to(SRC).as_posix()) + rewrite(f.read_text(encoding='utf-8'))
        (d / name).write_text(out, encoding='utf-8')
pd = DST / 'flow' / 'prompts'
psrc = SRC / 'skills/seo-flow/references/prompts'
for f in psrc.rglob('*.md'):
    rel = f.relative_to(psrc)
    (pd / rel.parent).mkdir(parents=True, exist_ok=True)
    (pd / rel).write_text('<!-- FLOW framework prompt, (c) Daniel Agrici, CC BY 4.0: github.com/AgriciDaniel/flow. Unchanged. -->\n'
                          + f.read_text(encoding='utf-8'), encoding='utf-8')
shutil.copy(SRC / 'skills/seo-flow/references/flow-prompts.lock', DST / 'flow' / 'flow-prompts.lock')
print('done')
