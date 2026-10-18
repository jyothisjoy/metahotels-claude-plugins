"""Files people hand over, read in code so nothing is retyped or garbled.

Hotel information sheet (.xlsx / .csv / a Google Sheets link shared "anyone with the link"):
every filled field becomes a fact in <domain>/hotel-facts.json with source "hotel info sheet, <date>",
so the [CONFIRM] guard accepts it. Rows are read as "field | value" (a row with one filled cell is a
heading that prefixes the rows under it, e.g. "Rooms" then "Deluxe King | 32 m2").

Keyword Planner exports (the CSV from Keyword Planner → Download keyword ideas, UTF-16 tab-separated):
read straight from the file, so Arabic keywords keep their order (copy-pasting reversed them).
"""
import csv
import io
import json
import re
from datetime import date
from pathlib import Path

import requests

from . import paths

ARABIC = re.compile(r'[؀-ۿ]')


def _sheet_rows(src):
    if re.match(r'https?://docs\.google\.com/spreadsheets/d/', src):
        sid = re.search(r'/d/([\w-]+)', src).group(1)
        gid = re.search(r'gid=(\d+)', src)
        url = f'https://docs.google.com/spreadsheets/d/{sid}/export?format=csv' + (f'&gid={gid.group(1)}' if gid else '')
        r = requests.get(url, timeout=60)
        if r.status_code != 200 or 'text/csv' not in r.headers.get('content-type', ''):
            raise ValueError('The Google Sheet is not shared "anyone with the link can view": share it that way, '
                             'or download it as .xlsx and give the file.')
        return [list(csv.reader(io.StringIO(r.content.decode('utf-8-sig'))))]
    p = paths.resolve(src)
    if p.suffix.lower() in ('.xlsx', '.xlsm'):
        from openpyxl import load_workbook
        wb = load_workbook(p, data_only=True, read_only=True)
        return [[['' if c is None else str(c) for c in row] for row in ws.iter_rows(values_only=True)]
                for ws in wb.worksheets]
    if p.suffix.lower() == '.csv':
        return [list(csv.reader(io.StringIO(p.read_bytes().decode('utf-8-sig', errors='replace'))))]
    raise ValueError(f'{p.suffix} sheets are not read in code: read the file yourself and add the facts, '
                     'or save it as .xlsx / .csv.')


def facts_sheet(src, facts_file, filled_on=''):
    sheets = _sheet_rows(src)
    source = f"hotel info sheet, {filled_on or date.today().strftime('%d %b %Y').lstrip('0')}"
    found = []
    for rows in sheets:
        heading = ''
        for row in rows:
            cells = [re.sub(r'\s+', ' ', c).strip() for c in row]
            filled = [c for c in cells if c]
            if not filled:
                continue
            if len(filled) == 1:
                heading = filled[0].rstrip(':')
                continue
            field, value = filled[0].rstrip(':'), ' / '.join(filled[1:])
            if field.lower() in ('field', 'item', 'question') and value.lower() in ('value', 'answer', 'details'):
                continue
            if re.fullmatch(r'(n/?a|-|tbc|tbd|none)', value, re.I):
                continue
            found.append(f"{heading} – {field}: {value}" if heading else f"{field}: {value}")
    fp = paths.resolve(facts_file)
    data = json.loads(fp.read_text(encoding='utf-8')) if fp.exists() else {'facts': []}
    have = {x.get('fact') for x in data['facts']}
    added = [f for f in found if f not in have]
    data['facts'].extend({'fact': f, 'source': source} for f in added)
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding='utf-8')
    return {'facts_read': len(found), 'added': len(added), 'already_there': len(found) - len(added),
            'source': source, 'facts_file': str(fp), 'facts': found,
            'next': 'Compare these with the site and the booking engine: where they disagree the sheet wins for '
                    'the copy, and the difference is a credibility fix.'}


def _num(v):
    if re.search(r'\d\s*[KkMm]\b|\d\s*[–-]\s*\d', str(v or '')):
        return str(v).strip()          # "1K – 10K": Keyword Planner shows ranges to accounts without spend
    v = re.sub(r'[^\d.]', '', str(v or ''))
    try:
        return float(v) if '.' in v else int(v) if v else None
    except ValueError:
        return None


def _read_text(p):
    raw = p.read_bytes()
    for enc in ('utf-16', 'utf-8-sig'):
        try:
            text = raw.decode(enc)
            if '\t' in text or ',' in text:
                return text
        except UnicodeDecodeError:
            continue
    return raw.decode('utf-8', errors='replace')


def keyword_csv(files, out_dir, label=''):
    rows = {}
    for f in files:
        p = paths.resolve(f)
        lines = _read_text(p).splitlines()
        start = next((i for i, ln in enumerate(lines) if ln.lower().startswith('keyword')
                      and 'monthly' in ln.lower()), None)
        if start is None:
            raise ValueError(f'{p.name}: no "Keyword ... Avg. monthly searches" header; is it a Keyword Planner export?')
        delim = '\t' if '\t' in lines[start] else ','
        reader = csv.DictReader(io.StringIO('\n'.join(lines[start:])), delimiter=delim)
        for r in reader:
            kw = (r.get('Keyword') or '').strip()
            if not kw:
                continue
            month_cols = {k.replace('Searches: ', ''): _num(v) for k, v in r.items() if k and k.startswith('Searches: ')}
            row = rows.setdefault(kw, {
                'keyword': kw, 'script': 'arabic' if ARABIC.search(kw) else 'latin',
                'avg_monthly_searches': _num(r.get('Avg. monthly searches')), 'competition': r.get('Competition', ''),
                'competition_index': _num(r.get('Competition (indexed value)')),
                'bid_low': _num(r.get('Top of page bid (low range)')),
                'bid_high': _num(r.get('Top of page bid (high range)')), 'currency': r.get('Currency', ''),
                'three_month_change': r.get('Three month change', ''), 'yoy_change': r.get('YoY change', ''),
                'monthly': month_cols, 'files': []})
            row['files'].append(p.name)
    out = paths.resolve(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stamp = date.today().isoformat()
    name = f"keywords-planner{'-' + re.sub(r'[^a-z0-9]+', '-', label.lower()) if label else ''}-{stamp}"
    def size(v):
        if isinstance(v, str):         # a range: sort by its lower end
            m = re.match(r'([\d.]+)\s*([KkMm]?)', v)
            return float(m.group(1)) * {'k': 1e3, 'm': 1e6}.get(m.group(2).lower(), 1) if m else 0
        return v or 0
    ordered = sorted(rows.values(), key=lambda x: -size(x['avg_monthly_searches']))
    with open(out / f'{name}.csv', 'w', newline='', encoding='utf-8-sig') as fh:
        w = csv.writer(fh)
        w.writerow(['keyword', 'script', 'avg_monthly_searches', 'competition', 'bid_low', 'bid_high', 'currency',
                    'three_month_change', 'yoy_change', 'files'])
        for x in ordered:
            w.writerow([x['keyword'], x['script'], x['avg_monthly_searches'], x['competition'], x['bid_low'],
                        x['bid_high'], x['currency'], x['three_month_change'], x['yoy_change'], ' + '.join(x['files'])])
    (out / f'{name}.json').write_text(json.dumps(ordered, indent=1, ensure_ascii=False), encoding='utf-8')
    return {'keywords': len(ordered), 'arabic': sum(1 for x in ordered if x['script'] == 'arabic'),
            'files_read': [Path(f).name for f in files], 'csv': str(out / f'{name}.csv'),
            'top': [{k: x[k] for k in ('keyword', 'avg_monthly_searches', 'competition')} for x in ordered[:25]]}
