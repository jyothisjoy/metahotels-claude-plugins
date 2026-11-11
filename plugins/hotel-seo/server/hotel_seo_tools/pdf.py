"""Render a document (Audit Report, Build Plan, Web Team List, Group Summary, Execute Report, Re-check) to an A4 PDF.

The document JSON comes from report.py (audit, web team, group) or Claude (Build Plan, Re-check edits);
this module owns the look, so every hotel's PDFs match (Playbook section 8).

Text fields accept a small markdown subset:
  **bold**   *italic*   __underlined link words__   `exact text to paste`
  [CONFIRM] or [CONFIRM with hotel which] (red)   [waiting for hotel details] (orange)
  [→ /accommodation/] (where the words before it link to)
and newlines become line breaks.
"""
import html
import json
import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from . import paths

TEMPLATES = Path(__file__).resolve().parent / 'templates'
REQUIRED = ('hotel', 'title', 'date', 'sections')
STATUS = {'done': 'st-done', 'ok': 'st-done', 'partly': 'st-partly', 'partial': 'st-partly', 'open': 'st-open',
          'manual': 'st-partly', 'waiting': 'st-partly', 'fix': 'st-open'}
BLOCKS = ('p', 'ol', 'ul', 'table', 'code', 'warning', 'note', 'paste', 'h3')
TITLES = ('Audit Report', 'Build Plan', 'Web Team List', 'Group Summary', 'Execute Report', 'Re-check',
          'Monthly Report', 'Group Monthly Summary', 'Agency Fix List')
MONTHLY = ('Monthly Report', 'Group Monthly Summary')   # client look: monthly.html.j2
DEFAULT_COLUMNS = ['#', 'Task', 'Time']
DEFAULT_FOOTER = ('**When done:** purge the page cache and tell MetaHotels what changed. Every finding is re-checked '
                  'on the live site (/hotel-seo recheck); fixes can also be applied with /hotel-seo execute in approved '
                  'batches.')


def rich(text):
    if text is None:
        return Markup('')
    if isinstance(text, (int, float)):
        return Markup(html.escape(str(text)))
    s = html.escape(str(text), quote=False)
    codes = []

    def stash(m):
        codes.append(m.group(1))
        return f'\x00{len(codes) - 1}\x00'
    s = re.sub(r'`([^`]+)`', stash, s)
    s = re.sub(r'\[→\s*([^\]]+?)\s*\]', lambda m: f'<span class="linkto">[→ <code>{m.group(1)}</code>]</span>', s)
    s = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', s)
    s = re.sub(r'__(.+?)__', r'<u>\1</u>', s)
    s = re.sub(r'(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])', r'<em>\1</em>', s)
    s = re.sub(r'\[CONFIRM[^\]]*\]', lambda m: f'<span class="confirm">{m.group(0)}</span>', s)
    s = re.sub(r'\[waiting[^\]]*\]', lambda m: f'<span class="hold">{m.group(0)}</span>', s, flags=re.I)
    s = s.replace('\n', '<br>')
    s = re.sub(r'\x00(\d+)\x00', lambda m: f'<code>{codes[int(m.group(1))]}</code>', s)
    return Markup(s)


def status_class(cell):
    return STATUS.get(str(cell).strip().lower(), '') if isinstance(cell, str) else ''


def load(doc_or_path):
    if isinstance(doc_or_path, dict):
        return doc_or_path
    p = paths.resolve(doc_or_path)
    return json.loads(p.read_text(encoding='utf-8'))


def validate(doc):
    missing = [k for k in REQUIRED if not doc.get(k)]
    if missing:
        raise ValueError(f'List JSON is missing: {", ".join(missing)}')
    normalize(doc)
    for i, s in enumerate(doc['sections'], 1):
        if not s.get('title'):
            raise ValueError(f'Section {i} has no title')
        if s.get('why') and s['why'][:1].islower():
            s['why'] = s['why'][0].upper() + s['why'][1:]     # it no longer follows a "Why:" label
        for b in s.get('blocks', []):
            if not isinstance(b, dict) or len(b) != 1 or next(iter(b)) not in BLOCKS:
                raise ValueError(f'Section {i} ({s["title"]}): each block must be one of '
                                 f'{", ".join(BLOCKS)}; got {b!r}')
    if doc['title'] not in TITLES:
        raise ValueError(f'title must be one of {", ".join(TITLES)}; got {doc["title"]!r}')
    summary = doc.get('summary')
    if summary:
        summary.setdefault('columns', DEFAULT_COLUMNS)
        summary['show_header'] = summary['columns'] != DEFAULT_COLUMNS
    doc.setdefault('warnings_top', [])
    doc.setdefault('warnings_end', [])
    if doc['title'] not in ('Re-check',) + MONTHLY:
        doc.setdefault('footer', DEFAULT_FOOTER)
    doc['name'] = list_name(doc)
    return doc


SEV_CLASS = {'critical': 'sev-critical', 'high': 'sev-high', 'medium': 'sev-medium', 'low': 'sev-low',
             'info': 'sev-info'}


def build_plan_page_sections(doc):
    """Build Plan: one section per page spec in doc['pages'] (structure first, then each page's paste-ready spec)."""
    pages = doc.get('pages') or []
    if doc.get('title') != 'Build Plan' or not pages:
        return []
    out = [{'chapter': 'Page specs', 'title': 'Page specs', 'chapter_label': f'Page specs · {len(pages)} pages',
            'blocks': []}]
    for n, p in enumerate(pages, 1):
        blocks = [{'table': {'columns': ['Field', 'Value'], 'rows': [
            ['URL', f"`{p.get('url', '')}`"], ['Status', p.get('status', '')],
            ['Target searches', ', '.join(p.get('keywords') or []) or p.get('cluster', '')],
            ['Searches / month', p.get('volume', '')], ['Title (SEO)', f"`{p.get('seo_title', '')}`"],
            ['Meta description', f"`{p.get('meta_description', '')}`"], ['H1', f"`{p.get('h1') or p.get('title', '')}`"]]}}]
        if p.get('copy'):
            blocks.append({'h3': 'Page copy (paste as is)'})
            blocks.append({'paste': p['copy']})
        if p.get('sections'):
            blocks.append({'ul': [str(x) for x in p['sections']]})
        if p.get('jsonld'):
            blocks.append({'h3': 'Schema (JSON-LD)'})
            blocks.append({'code': p['jsonld'] if isinstance(p['jsonld'], str) else json.dumps(p['jsonld'], indent=1,
                                                                                                 ensure_ascii=False)})
        links = [[f"`{x}`", 'links in'] for x in p.get('links_in') or []] + \
                [[f"`{x}`", 'links out'] for x in p.get('links_out') or []]
        if links:
            blocks.append({'table': {'columns': ['Page', 'Direction'], 'rows': links}})
        if p.get('images'):
            blocks.append({'h3': 'Images'})
            blocks.append({'ul': [str(x) for x in p['images']]})
        if p.get('booking_cta'):
            blocks.append({'note': '**Booking button:** ' + p['booking_cta']})
        out.append({'number': f'P{n}', 'title': p.get('h1') or p.get('title') or p.get('url', ''), 'blocks': blocks,
                    **({'hold': p['hold']} if p.get('hold') else {})})
    return out


def normalize(doc):
    """Audit Report / Group Summary extras -> plain sections every renderer understands (idempotent):
    a "Scores" section (Health Score, categories, separate scores, agent status) at the top."""
    if doc.get('_normalized'):
        return doc
    doc['_normalized'] = True
    sc = doc.get('scores')
    pre = []
    if sc and sc.get('categories'):
        h = sc.get('health')
        def _row(c):
            na = c.get('score') is None
            return [c['name'], f"{c['weight']}%" if c.get('weight') else 'separate',
                    'not assessed' if na else c['score'],
                    '–' if na else c.get('passed', 0), '–' if na else c.get('failed', 0),
                    c.get('not_measured', 0) or ('–' if na else 0),
                    (c.get('basis') or '').replace('not assessed: ', '')]
        rows = [_row(c) for c in sc['categories']]
        blocks = [{'p': f"**Health Score: {h if h is not None else 'not assessed'}/100**. Weighted average of the "
                        'category scores; a category score is the share of its checks that pass, weighted by '
                        'severity (Critical 4, High 3, Medium 2, Low 1). Categories not assessed are left out and the '
                        'weights rescaled. Local, Maps and Backlinks are shown separately.' +
                        (' Left out of this Health Score: ' + ', '.join(
                            c['name'] for c in sc['categories'] if c.get('weight') and c.get('score') is None) + '.'
                         if any(c.get('weight') and c.get('score') is None for c in sc['categories']) else '')},
                  {'table': {'columns': ['Category', 'Weight', 'Score', 'Checks passed', 'Failed', 'Not measured',
                                         'Based on'],
                             'rows': rows}}]
        sep = doc.get('separate_scores') or {}
        if sep:
            blocks.append({'h3': 'Separate scores'})
            blocks.append({'table': {'columns': ['Score', 'Value', 'Status / note'],
                                     'rows': [[k.replace('_', ' ').title(), str(v.get('score', '')),
                                               ' '.join(str(x) for x in (v.get('status'), v.get('note')) if x)]
                                              for k, v in sep.items()]}})
        st = doc.get('agent_status') or {}
        if st:
            rows = []
            for k, v in st.items():
                if isinstance(v, dict) and not isinstance(v.get('status'), str):
                    rows += [[f'{k}: {a}', (x.get('status') if isinstance(x, dict) else str(x))] for a, x in v.items()]
                else:
                    rows.append([k, v.get('status') if isinstance(v, dict) else str(v)])
            blocks.append({'h3': 'Agent status'})
            blocks.append({'table': {'columns': ['Agent', 'Status'], 'rows': rows}})
        pre.append({'title': 'Scores', 'blocks': blocks, 'generated': True})
    if doc.get('counts') and not doc.get('lead'):
        c = doc['counts']
        doc['lead'] = (f"**Health Score {sc.get('health') if sc else 'n/a'}/100** · {sum(c.values())} findings: "
                       f"{c.get('Critical', 0)} Critical, {c.get('High', 0)} High, {c.get('Medium', 0)} Medium, "
                       f"{c.get('Low', 0)} Low, {c.get('Info', 0)} Info.")
    doc['sections'] = pre + doc['sections'] + build_plan_page_sections(doc)
    for s in doc['sections']:
        if s.get('severity'):
            s['sev_class'] = SEV_CLASS.get(str(s['severity']).lower(), '')
        if s.get('chapter') and not s.get('chapter_label'):
            s['chapter_label'] = (f"{s['chapter']} · score {s['chapter_score']}/100"
                                  if s.get('chapter_score') is not None else f"{s['chapter']} · not assessed")
    return doc


def build_html(doc):
    env = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=select_autoescape(['j2', 'html']))
    env.filters['rich'] = rich
    env.filters['status_class'] = status_class
    if doc.get('title') in MONTHLY:
        import base64
        logo = lambda n: 'data:image/png;base64,' + base64.b64encode((TEMPLATES / 'assets' / n).read_bytes()).decode()
        css = (TEMPLATES / 'monthly.css').read_text(encoding='utf-8')
        return env.get_template('monthly.html.j2').render(doc=doc, css=Markup(css), logo=logo('metahotels-logo.png'),
                                                          logo_on_dark=logo('metahotels-logo-on-dark.png'))
    css = (TEMPLATES / 'list.css').read_text(encoding='utf-8')
    return env.get_template('list.html.j2').render(doc=doc, css=Markup(css))


def short_list(title):
    """"Web Team List" -> "Web Team", "Audit Report" -> "Audit Report"."""
    return re.sub(r'\s*(SEO )?List$', '', title or '').strip()


def list_name(doc):
    """The document's name in headers and file names: "Audit Report", "Audit Report Re-check 2",
    "Audit Report Open Items after Re-check 2"."""
    if doc['title'] == 'Re-check':
        n = doc.get('recheck_round')
        return ' '.join(x for x in (short_list(doc.get('against')), 'Re-check', str(n) if n else '') if x)
    is_group_name = str(doc.get('short_name') or doc['hotel']).strip().lower().endswith('group')
    if doc['title'] in ('Group Summary', 'Group Monthly Summary') and is_group_name:
        return doc['title'].replace('Group ', '')
    if doc.get('open_items_after'):
        return f"{short_list(doc['title'])} Open Items after Re-check {doc['open_items_after']}"
    return doc['title']


def next_file_number():
    """Running file number across all hotels in the work folder: highest "NN - ..." PDF or spreadsheet + 1."""
    nums = [int(m.group(1)) for ext in ('pdf', 'xlsx') for f in paths.work_dir().glob(f'**/Reports/*.{ext}')
            for m in [re.match(r'(\d+) - ', f.name)] if m]
    return max(nums, default=0) + 1


def file_name(doc, out_dir=None):
    """"31 - Rose Park Al Barsha Audit Report (24 Oct).pdf", "33 - Rose Park Al Barsha Audit Report Re-check 2 (30 Oct).pdf":
    the way the team numbers its files. "auto" re-uses the number of the same file already in out_dir
    (re-rendering after a fix keeps its number), else takes the next one."""
    short = doc.get('short_name') or doc['hotel']
    name = re.sub(r'[<>:"/\\|?*]', '-',f"{short} {list_name(doc)} ({doc['date']}).pdf")
    num = doc.get('file_number')
    if num == 'auto':
        same = [m.group(1) for f in (Path(out_dir).glob(f'* - {name}') if out_dir else [])
                for m in [re.match(r'(\d+) - ', f.name)] if m]
        num = doc['file_number'] = int(same[0]) if same else next_file_number()
    return f'{num} - {name}' if num not in (None, '') else name


def render(doc_or_path, out_dir, keep_html=False):
    doc = validate(load(doc_or_path))
    page_html = build_html(doc)
    out_dir = paths.resolve(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / file_name(doc, out_dir)

    from playwright.sync_api import sync_playwright
    footer = (f'<div style="font-size:7pt;color:#5b6470;width:100%;padding:0 13mm;display:flex;'
              f'justify-content:space-between;font-family:Segoe UI,Arial,sans-serif">'
              f'<span>{html.escape(doc["hotel"])} · {html.escape(list_name(doc))} · {html.escape(doc["date"])}</span>'
              f'<span>Page <span class="pageNumber"></span> of <span class="totalPages"></span></span></div>')
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content(page_html, wait_until='load')
        page.emulate_media(media='print')
        if doc['title'] in MONTHLY:     # page numbers and footer come from the template's @page rules
            pdf = page.pdf(format='A4', print_background=True, prefer_css_page_size=True)
        else:
            pdf = page.pdf(format='A4', print_background=True, prefer_css_page_size=True,
                           display_header_footer=True, header_template='<div></div>', footer_template=footer)
        browser.close()
    out.write_bytes(pdf)
    if keep_html:
        out.with_suffix('.html').write_text(page_html, encoding='utf-8')
    pages = len(re.findall(rb'/Type\s*/Page[^s]', pdf))
    return {'file': str(out), 'pages': pages, 'sections': len(doc['sections']),
            'file_number': doc.get('file_number')}
