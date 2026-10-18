"""The same list as a Google Doc: the agency copies from Docs, and PDFs break their formatting.

Builds Docs-friendly HTML from the list JSON (inline styles; boxes as one-cell tables, which Google
Docs keeps) and uploads it to Google Drive with conversion to a Google Doc. Docs go into an app
folder "MetaHotels SEO Lists / <hotel>" in the signed-in account's Drive (share that folder with the
agency once). Re-rendering the same list replaces the Doc's content, so its link stays the same
(mapping in <Reports>/google-docs.json).

Needs the Drive "files created by this app" permission (drive.file) in the Google sign-in, which
hotel-seo-auth asks for. Without it, upload the .docx written next to the PDF to Drive and open it
with Google Docs (a .docs.html file is written instead when there is no .docx).
"""
import html
import json
import re
from pathlib import Path

from . import paths, pdf

DRIVE_SCOPE = 'https://www.googleapis.com/auth/drive.file'
CONFIG = paths.GOOGLE_DIR / 'docs.json'
ROOT_FOLDER = 'MetaHotels SEO Lists'
DOC_MIME = 'application/vnd.google-apps.document'
FOLDER_MIME = 'application/vnd.google-apps.folder'

NAVY, RED, GOLD, GREEN, MUTED = '#12355b', '#b42318', '#a46a00', '#1a7f37', '#5b6470'
FONT = 'font-family:Arial,sans-serif;font-size:10pt'
STATUS_COLOR = {'st-done': GREEN, 'st-partly': GOLD, 'st-open': RED}


def _rich(text):
    """pdf.rich() with its classes turned into inline styles Google Docs keeps."""
    s = str(pdf.rich(text))
    s = s.replace('<span class="confirm">', f'<span style="color:{RED};font-weight:bold">')
    s = s.replace('<span class="hold">', f'<span style="color:{GOLD};font-weight:bold">')
    s = s.replace('<span class="linkto">', f'<span style="color:{MUTED};font-size:9pt">')
    s = s.replace('<code>', '<span style="font-family:Consolas,\'Courier New\',monospace;background-color:#eef1f5">')
    return s.replace('</code>', '</span>')


def _box(inner, bg, border):
    return (f'<table style="border-collapse:collapse;width:100%;margin:6pt 0"><tr>'
            f'<td style="background-color:{bg};border:1px solid {border};padding:6pt 8pt;{FONT}">{inner}</td>'
            f'</tr></table>')


def _table(columns, rows, header=True):
    out = ['<table style="border-collapse:collapse;width:100%;margin:6pt 0">']
    if header and columns:
        out.append('<tr>' + ''.join(f'<td style="background-color:{NAVY};color:#ffffff;font-weight:bold;'
                                    f'border:1px solid #d6dbe1;padding:4pt 6pt;{FONT}">{html.escape(str(c))}</td>'
                                    for c in columns) + '</tr>')
    for row in rows:
        cells = []
        for c in row:
            color = STATUS_COLOR.get(pdf.status_class(c), '')
            style = f'border:1px solid #d6dbe1;padding:4pt 6pt;{FONT}' + (f';color:{color};font-weight:bold' if color else '')
            cells.append(f'<td style="{style}">{_rich(c)}</td>')
        out.append('<tr>' + ''.join(cells) + '</tr>')
    return ''.join(out) + '</table>'


def _code(text):
    lines = html.escape(str(text)).split('\n')
    lines = [re.sub(r'^( +)', lambda m: '&nbsp;' * len(m.group(1)), ln) for ln in lines]
    return _box('<span style="font-family:Consolas,\'Courier New\',monospace;font-size:9pt">'
                + '<br>'.join(lines) + '</span>', '#eef1f5', '#d6dbe1')


def _block(b):
    (kind, val), = b.items()
    if kind == 'p':
        return f'<p style="{FONT}">{_rich(val)}</p>'
    if kind in ('ol', 'ul'):
        return f'<{kind}>' + ''.join(f'<li style="{FONT}">{_rich(li)}</li>' for li in val) + f'</{kind}>'
    if kind == 'table':
        return _table(val.get('columns', []), val.get('rows', []))
    if kind == 'code':
        return _code(val)
    if kind == 'warning':
        return _box(_rich(val), '#fdf1f0', '#e8a39c')
    if kind == 'paste':
        return _box(_rich(val), '#eef7ef', '#b9dcbf')
    if kind == 'note':
        return _box(_rich(val), '#f5f7fa', NAVY)
    if kind == 'h3':
        return f'<h3 style="color:{NAVY};font-family:Arial,sans-serif">{_rich(val)}</h3>'
    return ''


def build_html(doc):
    doc = pdf.validate(doc)
    H = [f'<html><head><meta charset="utf-8"><title>{html.escape(doc["hotel"])}</title></head><body>',
         f'<h1 style="color:{NAVY};font-family:Arial,sans-serif">{html.escape(doc["hotel"])}: {html.escape(doc["name"])} — {html.escape(doc["date"])}</h1>']
    if doc.get('subtitle'):
        H.append(f'<p style="{FONT};color:{MUTED}">{_rich(doc["subtitle"])}</p>')
    if doc.get('lead'):
        H.append(_box(_rich(doc['lead']), '#eef7ef', '#b9dcbf'))
    sm = doc.get('summary')
    if sm:
        rows = list(sm.get('rows', []))
        if sm.get('finish'):
            rows.append(['', f"**Finish:** {sm['finish']}"] + [''] * (len(sm['columns']) - 2))
        H.append(_table(sm['columns'], rows, header=sm.get('show_header', True)))
    for w in doc.get('warnings_top', []):
        H.append(_box(_rich(w), '#fdf1f0', '#e8a39c'))
    if doc.get('working'):
        H.append(f'<h2 style="color:{NAVY};font-family:Arial,sans-serif">What\'s already working (no action)</h2>')
        H.append(_table(['Item', 'Status', 'Note'], doc['working']))
    for p in doc.get('intro', []):
        H.append(f'<p style="{FONT}">{_rich(p)}</p>')
    for s in doc['sections']:
        title = (f"{s['number']}. " if s.get('number') else '') + str(pdf.rich(s['title']))
        hold = f' <span style="color:{GOLD}">[{html.escape(s["hold"])}]</span>' if s.get('hold') else ''
        time_ = f' <span style="color:{MUTED};font-weight:normal">· {html.escape(str(s["time"]))}</span>' if s.get('time') else ''
        H.append(f'<h2 style="color:{NAVY};font-family:Arial,sans-serif">{title}{hold}{time_}</h2>')
        if s.get('why'):
            H.append(f'<p style="{FONT};font-style:italic;color:{MUTED}">{_rich(s["why"])}</p>')
        H.extend(_block(b) for b in s.get('blocks', []))
    for w in doc.get('warnings_end', []):
        H.append(_box(_rich(w), '#fdf1f0', '#e8a39c'))
    if doc.get('footer'):
        H.append(f'<p style="{FONT}">{_rich(doc["footer"])}</p>')
    return '\n'.join(H) + '</body></html>'


# ---------------------------------------------------------------- Drive

def _session():
    if not paths.GSC_TOKEN.exists():
        return None, 'no Google sign-in on this machine (run /hotel-seo init)'
    info = json.loads(paths.GSC_TOKEN.read_text())
    if DRIVE_SCOPE not in (info.get('scopes') or []):
        return None, ('the Google sign-in on this machine has no Docs permission yet: run hotel-seo-auth again '
                      '(one consent screen) to allow "files created by this app"')
    from google.auth.transport.requests import AuthorizedSession
    from google.oauth2.credentials import Credentials
    return AuthorizedSession(Credentials.from_authorized_user_info(info, info['scopes'])), ''


def _folder(s, name, parent=None):
    q = f"name = '{name.replace(chr(39), chr(92) + chr(39))}' and mimeType = '{FOLDER_MIME}' and trashed = false"
    if parent:
        q += f" and '{parent}' in parents"
    r = s.get('https://www.googleapis.com/drive/v3/files', params={'q': q, 'fields': 'files(id)', 'spaces': 'drive'},
              timeout=30)
    r.raise_for_status()
    found = r.json().get('files', [])
    if found:
        return found[0]['id']
    meta = {'name': name, 'mimeType': FOLDER_MIME, **({'parents': [parent]} if parent else {})}
    r = s.post('https://www.googleapis.com/drive/v3/files', json=meta, params={'fields': 'id'}, timeout=30)
    r.raise_for_status()
    return r.json()['id']


def _upload(s, method, url, meta, body):
    boundary = 'hotelseo' + str(abs(hash(url)))[:12]
    payload = (f'--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{json.dumps(meta)}\r\n'
               f'--{boundary}\r\nContent-Type: text/html; charset=UTF-8\r\n\r\n').encode() + body.encode('utf-8') \
        + f'\r\n--{boundary}--'.encode()
    r = s.request(method, url, params={'uploadType': 'multipart', 'fields': 'id,webViewLink'}, data=payload,
                  headers={'Content-Type': f'multipart/related; boundary={boundary}'}, timeout=120)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


def _fallback(body, pdf_file, docx_file, why):
    """No Doc: point at the Word file (Drive opens it in Google Docs), else write a .docs.html."""
    if docx_file:
        local = docx_file
    else:
        local = Path(pdf_file).with_suffix('.docs.html')
        local.write_text(body, encoding='utf-8')
    return {'published': False, 'reason': why, 'file': str(local),
            'next': 'Upload this file to Google Drive and open it with Google Docs, or fix the sign-in and '
                    'render again.'}


def publish(doc, out_dir, pdf_file, folder_id='', docx_file=''):
    body = build_html(doc)
    name = Path(pdf_file).stem
    s, why = _session()
    if s is None:
        return _fallback(body, pdf_file, docx_file, why)
    out = paths.resolve(out_dir)
    mapping_file = out / 'google-docs.json'
    mapping = json.loads(mapping_file.read_text(encoding='utf-8')) if mapping_file.exists() else {}
    try:
        if not folder_id:
            cfg = json.loads(CONFIG.read_text()) if CONFIG.exists() else {}
            if not cfg.get('root_folder_id'):
                cfg['root_folder_id'] = _folder(s, ROOT_FOLDER)
                CONFIG.write_text(json.dumps(cfg, indent=2))
            folder_id = _folder(s, doc.get('short_name') or doc['hotel'], cfg['root_folder_id'])
        res, updated = None, False
        key = re.sub(r'^\d+ - ', '', name)            # same list, new file number: still the same Doc
        if mapping.get(key):
            res = _upload(s, 'PATCH', f"https://www.googleapis.com/upload/drive/v3/files/{mapping[key]}",
                          {'name': name}, body)
            updated = res is not None
        if res is None:
            res = _upload(s, 'POST', 'https://www.googleapis.com/upload/drive/v3/files',
                          {'name': name, 'mimeType': DOC_MIME, 'parents': [folder_id]}, body)
        mapping[key] = res['id']
        mapping_file.write_text(json.dumps(mapping, indent=1), encoding='utf-8')
    except Exception as e:  # noqa: BLE001 - the PDF is done; report and leave a file to import
        return _fallback(body, pdf_file, docx_file, f'{type(e).__name__}: {str(e)[:300]}')
    return {'published': True, 'updated': updated, 'url': res.get('webViewLink')
            or f"https://docs.google.com/document/d/{res['id']}/edit",
            'folder': f'https://drive.google.com/drive/folders/{folder_id}',
            'note': 'Private to the signed-in account: share the hotel folder with the agency once.'}
