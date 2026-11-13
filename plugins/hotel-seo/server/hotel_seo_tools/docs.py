"""The full URL list of a long finding as a CSV next to the report (reports are PDF only: no Word, no Google Docs)."""
import re

from . import paths

URL_LIST_LIMIT = 25


def prepare_url_lists(doc, out_dir, file_stem):
    """Findings with more than 25 URLs: the full list goes to '<file_stem> URLs - <finding>.csv' next to the report
    and the finding's note names the file. Returns {finding_id: {...}}."""
    import csv as _csv
    out = paths.resolve(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    made = {}
    for sec in doc.get('sections', []):
        pages = sec.get('pages_all') or []
        if len(pages) <= URL_LIST_LIMIT:
            continue
        fid = re.sub(r'[^A-Za-z0-9_-]+', '-', str(sec.get('finding_id') or sec.get('number')))[:50]
        f = out / f'{file_stem} URLs - {fid}.csv'
        with open(f, 'w', newline='', encoding='utf-8-sig') as fh:
            w = _csv.writer(fh)
            w.writerow(['#', 'URL', 'Finding'])
            for i, u in enumerate(pages, 1):
                w.writerow([i, u, sec.get('title', '')])
        entry = {'csv': str(f), 'count': len(pages)}
        for b in sec.get('blocks', []):
            if 'note' in b and 'URL list CSV' in b['note']:
                b['note'] = (f"{len(pages)} pages in total: the first {URL_LIST_LIMIT} are shown above; every URL is in "
                             f"`{f.name}`.")
        made[fid] = entry
    return made
