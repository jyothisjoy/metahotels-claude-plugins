"""The same list as a Word file (.docx), written next to the PDF.

Built from the list JSON with python-docx, in the PDF's look: navy headings and table headers,
coloured statuses, green / red / grey boxes as one-cell shaded tables, monospace copy boxes, and
"Page X of Y" in the footer. Numbered steps are typed as "1." text (not Word auto-numbering) so
they paste into WordPress and WhatsApp unchanged and don't continue from the list before.
"""
import re
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm, Pt, RGBColor

from . import pdf

NAVY, RED, GOLD, GREEN, MUTED = '12355b', 'b42318', 'a46a00', '1a7f37', '5b6470'
BORDER = 'd6dbe1'
STATUS_COLOR = {'st-done': GREEN, 'st-partly': GOLD, 'st-open': RED}
BOXES = {'warning': ('fdf1f0', 'e8a39c'), 'paste': ('eef7ef', 'b9dcbf'), 'lead': ('eef7ef', 'b9dcbf'),
         'note': ('f5f7fa', NAVY), 'code': ('eef1f5', BORDER)}
MONO = 'Consolas'
CONTENT_MM = 210 - 2 * 16              # A4 width minus the side margins set in build()

TOKEN = re.compile(r'`(?P<code>[^`]+)`'
                   r'|\*\*(?P<bold>.+?)\*\*'
                   r'|__(?P<under>.+?)__'
                   r'|(?<![\w*])\*(?!\s)(?P<em>.+?)(?<!\s)\*(?![\w*])'
                   r'|(?P<confirm>\[CONFIRM[^\]]*\])'
                   r'|(?P<hold>\[waiting[^\]]*\])'
                   r'|\[→\s*(?P<linkto>[^\]]+?)\s*\]', re.I)


def _runs(text, fmt=None):
    """The list markdown subset (see pdf.py) as (text, format) pieces."""
    fmt = fmt or {}
    text = '' if text is None else str(text)
    pos = 0
    for m in TOKEN.finditer(text):
        if m.start() > pos:
            yield text[pos:m.start()], fmt
        kind = m.lastgroup
        val = m.group(kind)
        if kind == 'code':
            yield val, {**fmt, 'mono': True, 'shade': 'eef1f5'}
        elif kind == 'bold':
            yield from _runs(val, {**fmt, 'bold': True})
        elif kind == 'under':
            yield from _runs(val, {**fmt, 'underline': True})
        elif kind == 'em':
            yield from _runs(val, {**fmt, 'italic': True})
        elif kind == 'confirm':
            yield val, {**fmt, 'bold': True, 'color': RED}
        elif kind == 'hold':
            yield val, {**fmt, 'bold': True, 'color': GOLD}
        elif kind == 'linkto':
            yield '[→ ', {**fmt, 'color': MUTED, 'size': 9}
            yield val, {**fmt, 'color': MUTED, 'size': 9, 'mono': True}
            yield ']', {**fmt, 'color': MUTED, 'size': 9}
        pos = m.end()
    if pos < len(text):
        yield text[pos:], fmt


def _shade(el, fill):
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'), fill)
    el.append(shd)


def _add(par, text, base=None):
    """Append rich text to a paragraph; newlines become line breaks."""
    for piece, fmt in _runs(text, base):
        for i, line in enumerate(piece.split('\n')):
            if i:
                par.add_run().add_break()
            if not line:
                continue
            r = par.add_run(line)
            r.bold = fmt.get('bold') or None
            r.italic = fmt.get('italic') or None
            r.underline = fmt.get('underline') or None
            if fmt.get('color'):
                r.font.color.rgb = RGBColor.from_string(fmt['color'])
            if fmt.get('size'):
                r.font.size = Pt(fmt['size'])
            if fmt.get('mono'):
                r.font.name = MONO
                r.element.rPr.rFonts.set(qn('w:eastAsia'), MONO)
            if fmt.get('shade'):
                _shade(r.element.get_or_add_rPr(), fmt['shade'])
    return par


def _cell_style(cell, fill=None, border=BORDER):
    tcPr = cell._tc.get_or_add_tcPr()
    if fill:
        _shade(tcPr, fill)
    borders = OxmlElement('w:tcBorders')
    for side in ('top', 'left', 'bottom', 'right'):
        b = OxmlElement(f'w:{side}')
        b.set(qn('w:val'), 'single')
        b.set(qn('w:sz'), '6')
        b.set(qn('w:color'), border)
        borders.append(b)
    tcPr.append(borders)
    mar = OxmlElement('w:tcMar')
    for side, w in (('top', 60), ('bottom', 60), ('left', 110), ('right', 110)):
        m = OxmlElement(f'w:{side}')
        m.set(qn('w:w'), str(w))
        m.set(qn('w:type'), 'dxa')
        mar.append(m)
    tcPr.append(mar)


def _spacer(d):
    p = d.add_paragraph()
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.line_spacing = Pt(4)


def _box(d, text, kind):
    fill, border = BOXES[kind]
    t = d.add_table(rows=1, cols=1)
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    cell = t.cell(0, 0)
    _cell_style(cell, fill, border)
    p = cell.paragraphs[0]
    if kind == 'code':
        lines = str(text).split('\n')
        for i, line in enumerate(lines):
            if i:
                p.add_run().add_break()
            r = p.add_run(line)
            r.font.name = MONO
            r.font.size = Pt(9)
            r.element.rPr.rFonts.set(qn('w:eastAsia'), MONO)
    else:
        _add(p, text)
    _spacer(d)


def _table(d, columns, rows, header=True):
    ncols = max([len(columns)] + [len(r) for r in rows]) if (columns or rows) else 1
    show = header and columns
    t = d.add_table(rows=(1 if show else 0) + len(rows), cols=ncols)
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = False
    widths = _widths([columns if show else []] + [list(r) for r in rows], ncols)
    for row in t.rows:
        for j, cell in enumerate(row.cells):
            cell.width = widths[j]
    r0 = 0
    if show:
        for j in range(ncols):
            cell = t.cell(0, j)
            _cell_style(cell, NAVY)
            _add(cell.paragraphs[0], columns[j] if j < len(columns) else '',
                 {'bold': True, 'color': 'ffffff'})
        _repeat_header(t.rows[0])
        r0 = 1
    for i, row in enumerate(rows):
        for j in range(ncols):
            val = row[j] if j < len(row) else ''
            cell = t.cell(r0 + i, j)
            _cell_style(cell)
            color = STATUS_COLOR.get(pdf.status_class(val))
            _add(cell.paragraphs[0], val, {'bold': True, 'color': color} if color else None)
    _spacer(d)


def _widths(rows, ncols):
    """Share the text width by each column's longest line (capped), so "#" and "Time" stay narrow."""
    need, word = [4] * ncols, [4] * ncols
    for r in rows:
        for j, v in enumerate(r[:ncols]):
            longest = max((len(x) for x in str(v).split('\n')), default=0)
            need[j] = max(need[j], min(longest, 45))
            word[j] = max(word[j], min(max((len(x) for x in str(v).split()), default=0) + 2, 20))
    total = sum(need)
    w = [CONTENT_MM * n / total for n in need]
    floor = [n * 1.9 + 4 for n in word]     # ~1.9 mm a character at 10 pt + cell padding: no word split
    short = sum(max(f - x, 0) for f, x in zip(floor, w))
    if short:
        spare = sum(x for f, x in zip(floor, w) if x > f)
        w = [f if x <= f else x - short * x / spare for f, x in zip(floor, w)]
    return [Mm(x) for x in w]


def _repeat_header(row):
    trPr = row._tr.get_or_add_trPr()
    h = OxmlElement('w:tblHeader')
    h.set(qn('w:val'), 'true')
    trPr.append(h)


def _heading(d, text, size, level, extra=None):
    p = d.add_paragraph()
    p.paragraph_format.space_before = Pt(10 if level > 1 else 0)
    p.paragraph_format.space_after = Pt(4)
    p.paragraph_format.keep_with_next = True
    _add(p, text, {'bold': True, 'color': NAVY, 'size': size})
    for t, fmt in extra or []:
        _add(p, t, {'size': size, **fmt})
    p.style = d.styles[f'Heading {level}']
    for r in p.runs:                       # the Heading styles' own font and colour, overridden
        r.font.name = 'Arial'
    return p


def _block(d, b):
    (kind, val), = b.items()
    if kind == 'p':
        _add(d.add_paragraph(), val)
    elif kind == 'ol':
        for n, li in enumerate(val, 1):
            p = d.add_paragraph()
            p.paragraph_format.left_indent = Mm(7)
            p.paragraph_format.first_line_indent = Mm(-5)
            p.paragraph_format.space_after = Pt(2)
            _add(p, f'{n}.\t' + str(li))
            p.paragraph_format.tab_stops.add_tab_stop(Mm(7))
    elif kind == 'ul':
        for li in val:
            p = d.add_paragraph(style='List Bullet')
            p.paragraph_format.space_after = Pt(2)
            _add(p, li)
    elif kind == 'table':
        _table(d, val.get('columns', []), val.get('rows', []))
    elif kind in ('code', 'warning', 'paste', 'note'):
        _box(d, val, kind)
    elif kind == 'h3':
        _heading(d, val, 11, 3)


def _page_field(par, code):
    r = par.add_run()
    for tag, attr in (('w:fldChar', 'begin'), ('w:instrText', code), ('w:fldChar', 'end')):
        el = OxmlElement(tag)
        if tag == 'w:fldChar':
            el.set(qn('w:fldCharType'), attr)
        else:
            el.set(qn('xml:space'), 'preserve')
            el.text = f' {attr} '
        r._r.append(el)
    return r


def build(doc):
    doc = pdf.validate(doc)
    d = Document()
    sec = d.sections[0]
    sec.page_width, sec.page_height = Mm(210), Mm(297)
    sec.left_margin = sec.right_margin = Mm(16)
    sec.top_margin, sec.bottom_margin = Mm(14), Mm(16)
    normal = d.styles['Normal']
    normal.font.name, normal.font.size = 'Arial', Pt(10)
    normal.element.rPr.rFonts.set(qn('w:eastAsia'), 'Arial')
    normal.paragraph_format.space_after = Pt(5)
    d.core_properties.title = f"{doc['hotel']}: {doc['name']} ({doc['date']})"
    d.core_properties.author = 'MetaHotels'

    foot = sec.footer.paragraphs[0]
    _add(foot, f"{doc['hotel']} · {doc['name']} · {doc['date']}    Page ", {'size': 7, 'color': MUTED})
    _page_field(foot, 'PAGE').font.size = Pt(7)
    _add(foot, ' of ', {'size': 7, 'color': MUTED})
    _page_field(foot, 'NUMPAGES').font.size = Pt(7)

    _heading(d, f"{doc['hotel']}: {doc['name']} — {doc['date']}", 16, 1)
    if doc.get('subtitle'):
        _add(d.add_paragraph(), doc['subtitle'], {'color': MUTED, 'size': 9})
    if doc.get('lead'):
        _box(d, doc['lead'], 'lead')
    sm = doc.get('summary')
    if sm:
        rows = list(sm.get('rows', []))
        if sm.get('finish'):
            rows.append(['', f"**Finish:** {sm['finish']}"] + [''] * (len(sm['columns']) - 2))
        _table(d, sm['columns'], rows, header=sm.get('show_header', True))
    for w in doc.get('warnings_top', []):
        _box(d, w, 'warning')
    if doc.get('working'):
        _heading(d, "What's already working (no action)", 13, 2)
        _table(d, ['Item', 'Status', 'Note'], doc['working'])
    if doc.get('parity'):
        pb = doc['parity']
        _heading(d, pb.get('title') or 'Rate parity (Best Rate calendar)', 13, 2)
        _table(d, pb['columns'], pb['rows'])
        if pb.get('note'):
            _add(d.add_paragraph(), f"*{pb['note']}*")
    for p in doc.get('intro', []):
        _add(d.add_paragraph(), p)
    for s in doc['sections']:
        extra = []
        if s.get('hold'):
            extra.append((f" [{s['hold']}]", {'bold': True, 'color': GOLD}))
        if s.get('time'):
            extra.append((f" · {s['time']}", {'color': MUTED}))
        _heading(d, (f"{s['number']}. " if s.get('number') else '') + str(s['title']), 13, 2, extra)
        if s.get('why'):
            _add(d.add_paragraph(), s['why'], {'italic': True, 'color': MUTED})
        for b in s.get('blocks', []):
            _block(d, b)
    for w in doc.get('warnings_end', []):
        _box(d, w, 'warning')
    if doc.get('footer'):
        _add(d.add_paragraph(), doc['footer'])
    return d


def render(doc, pdf_file):
    """Write <pdf name>.docx next to the PDF."""
    out = Path(pdf_file).with_suffix('.docx')
    build(doc).save(out)
    return str(out)
