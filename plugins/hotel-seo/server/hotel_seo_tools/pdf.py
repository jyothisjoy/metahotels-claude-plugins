"""Render a list (Priority, Nice-to-Have, Web Team, Re-check) from JSON to an A4 PDF.

Claude writes the content as JSON following skills/hotel-seo/templates/lists.schema.json;
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
TITLES = ('Priority SEO List', 'Nice-to-Have SEO List', 'Secondary SEO List', 'Web Team List', 'Re-check')
DEFAULT_COLUMNS = ['#', 'Task', 'Time']
DEFAULT_FOOTER = ('**When done:** LiteSpeed → Purge All → send MetaHotels the change list (mark items done only '
                  'once they are live). We will re-crawl and check every item.')
A4_CONTENT_PX = (297 - 14 - 16) / 25.4 * 96      # printable height per page at 96 dpi (list.css @page margins)


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


ESCAPED = re.compile(r'\\u[0-9a-fA-F]{4}')


def escaped_text(doc):
    r"""Visible text holding a literal \uXXXX: Arabic (or any non-Latin text) that was escaped twice
    and would print as codes (one hotel's Arabic came out this way)."""
    hits = []

    def walk(v, where):
        if isinstance(v, str):
            m = ESCAPED.search(v)
            if m:
                hits.append(f'{where}: ...{v[max(0, m.start() - 20):m.end() + 20]}...')
        elif isinstance(v, dict):
            for k, x in v.items():
                if k != 'checks':
                    walk(x, f'{where}.{k}' if where else k)
        elif isinstance(v, list):
            for i, x in enumerate(v):
                walk(x, f'{where}[{i}]')
    walk(doc, '')
    return hits


def validate(doc):
    bad = escaped_text(doc)
    if bad:
        raise ValueError(r'Literal \uXXXX escapes in the list text (they would print as codes, not letters): '
                         + '; '.join(bad[:5]) + '. Write the real characters (save the JSON as UTF-8).')
    missing = [k for k in REQUIRED if not doc.get(k)]
    if missing:
        raise ValueError(f'List JSON is missing: {", ".join(missing)}')
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
    if doc['title'] != 'Re-check':
        doc.setdefault('footer', DEFAULT_FOOTER)
    doc['name'] = list_name(doc)
    return doc


def build_html(doc):
    env = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=select_autoescape(['j2', 'html']))
    env.filters['rich'] = rich
    env.filters['status_class'] = status_class
    css = (TEMPLATES / 'list.css').read_text(encoding='utf-8')
    return env.get_template('list.html.j2').render(doc=doc, css=Markup(css))


def short_list(title):
    """"Priority SEO List" -> "Priority", "Web Team List" -> "Web Team"."""
    return re.sub(r'\s*(SEO )?List$', '', title or '').strip()


def list_name(doc):
    """The list's name in headers and file names: "Priority SEO List", "Priority Re-check 2",
    "Priority Open Items after Re-check 2"."""
    if doc['title'] == 'Re-check':
        n = doc.get('recheck_round')
        return ' '.join(x for x in (short_list(doc.get('against')), 'Re-check', str(n) if n else '') if x)
    if doc.get('open_items_after'):
        return f"{short_list(doc['title'])} Open Items after Re-check {doc['open_items_after']}"
    return doc['title']


def next_file_number():
    """Running file number across all hotels in the work folder: highest "NN - ..." PDF + 1."""
    nums = [int(m.group(1)) for f in paths.work_dir().glob('*/Reports/*.pdf')
            for m in [re.match(r'(\d+) - ', f.name)] if m]
    return max(nums, default=0) + 1


def file_name(doc, out_dir=None):
    """"25 - Al Bahar Priority SEO List (14 Oct).pdf", "27 - Al Bahar Priority Re-check 2 (21 Oct).pdf":
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
        page.set_viewport_size({'width': 794 - 2 * 49, 'height': 1000})   # A4 width minus 13 mm margins
        height = page.evaluate('document.documentElement.scrollHeight')
        # bottom of the last real content (sections, end warnings), not the "When done" footer line
        content_bottom = page.evaluate(
            "Math.max(0, ...[...document.querySelectorAll('section, .warning, .working, .summary, .lead')]"
            ".map(e => e.getBoundingClientRect().bottom + window.scrollY))")
        pdf = page.pdf(format='A4', print_background=True, prefer_css_page_size=True,
                       display_header_footer=True, header_template='<div></div>', footer_template=footer)
        browser.close()
    out.write_bytes(pdf)
    if keep_html:
        out.with_suffix('.html').write_text(page_html, encoding='utf-8')
    pages = len(re.findall(rb'/Type\s*/Page[^s]', pdf))
    result = {'file': str(out), 'pages': pages, 'sections': len(doc['sections']),
              'file_number': doc.get('file_number')}
    last_fill = (height % A4_CONTENT_PX) / A4_CONTENT_PX
    content_pages = int(content_bottom // A4_CONTENT_PX) + 1 if content_bottom else pages
    if pages > 1 and content_pages < pages:
        # e.g. a 5th page holding only the 214-character footer, which the fill check missed
        result['warning'] = (f'The last page holds no list content, only the footer (content ends on page '
                             f'{content_pages} of {pages}): tighten wording so the footer fits on the page before.')
    elif pages > 1 and 0 < last_fill < 0.15:
        result['warning'] = (f'The last page is nearly empty (about {round(last_fill * 100)}% used): tighten '
                             'wording or merge a short section so the list ends on the page before.')
    return result
