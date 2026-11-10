"""Disparity / Best Rate calendar: the monthly CSV export from MetaHotels' parity monitoring, one row per day.

    Date,Weekday,Hotel,Parity Status,Bookings,Day Type
    2026-08-03,Mon,Gewan Palace New Alamein,Best Rates/Corrected,4,"Parity, with bookings"

import_calendars(files, out_dir) reads one or more of them (any hotels, any months), counts everything in code and
writes parity-calendar.json / parity-calendar.md, plus a ready `parity` block for the Priority list and the lead /
"already working" lines. Status words are matched loosely ("Best Rates/Corrected", "Parity", "Disparity", "Lose",
"No record"); any status it doesn't know is reported, never guessed.

Parity is a revenue-team matter: never an agency item and never a price change on the site. Bookings by day type is
context, not proof that parity caused bookings (registry rule 6), and small samples say so.
"""
import csv
import json
import re
from collections import Counter, defaultdict
from datetime import date

from . import paths

DISPARITY = re.compile(r'disparit|\blos[se]|\bloss\b|undercut|not corrected|uncorrected|open disparity|ota cheaper', re.I)
BEST = re.compile(r'best rate|\bparity\b|corrected|\bmeet\b|\bbeat\b|\bwin\b|in parity', re.I)
NO_RECORD = re.compile(r'no record|no data|not checked|^\s*(?:n/?a|-)?\s*$', re.I)
DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
MIN_DAYS = 5            # below this many days of a type, a bookings-per-day comparison isn't made


def _status(text):
    t = str(text or '')
    if NO_RECORD.search(t):
        return 'no_record'
    if DISPARITY.search(t):            # before BEST: "Disparity" contains "parity"
        return 'disparity'
    if BEST.search(t):
        return 'best'
    return 'other'


def _int(v):
    try:
        return int(float(str(v).strip() or 0))
    except ValueError:
        return 0


def _col(header, *names):
    low = [h.strip().lower() for h in header]
    for n in names:
        if n in low:
            return low.index(n)
    return None


def read(file):
    p = paths.resolve(file)
    with open(p, encoding='utf-8-sig', newline='') as fh:
        rows = list(csv.reader(fh))
    if not rows:
        return []
    h = rows[0]
    ci = {'date': _col(h, 'date'), 'weekday': _col(h, 'weekday', 'day'), 'hotel': _col(h, 'hotel', 'property'),
          'status': _col(h, 'parity status', 'status', 'parity'), 'bookings': _col(h, 'bookings', 'reservations'),
          'type': _col(h, 'day type', 'type')}
    if ci['date'] is None or ci['status'] is None:
        raise ValueError(f'{p.name}: needs at least "Date" and "Parity Status" columns; found {h}')
    out = []
    for r in rows[1:]:
        if not r or not r[ci['date']].strip():
            continue
        g = lambda k: r[ci[k]].strip() if ci[k] is not None and ci[k] < len(r) else ''
        d = date.fromisoformat(g('date')[:10])
        out.append({'date': d.isoformat(), 'weekday': g('weekday') or DAYS[d.weekday()], 'hotel': g('hotel'),
                    'status_text': g('status'), 'status': _status(g('status')), 'bookings': _int(g('bookings')),
                    'day_type': g('type'), 'file': p.name})
    return out


def _runs(days):
    """Longest run of consecutive dates."""
    best = cur = 0
    prev = None
    for d in sorted(date.fromisoformat(x) for x in days):
        cur = cur + 1 if prev and (d - prev).days == 1 else 1
        best = max(best, cur)
        prev = d
    return best


def summarise(rows):
    by = defaultdict(list)
    for r in rows:
        by[(r['hotel'], r['date'][:7])].append(r)
    months = []
    for (hotel, month), rs in sorted(by.items()):
        c = Counter(r['status'] for r in rs)
        bk = defaultdict(int)
        for r in rs:
            bk[r['status']] += r['bookings']
        recorded = c['best'] + c['disparity']
        nr_days = [r['weekday'] for r in rs if r['status'] == 'no_record']
        nr_pattern = ''
        if nr_days:
            wd = Counter(nr_days)
            all_of = [d for d in wd if wd[d] == sum(1 for r in rs if r['weekday'] == d)]
            if all_of and sum(wd[d] for d in all_of) == len(nr_days):
                nr_pattern = 'every ' + ' and '.join(all_of)
        per_day = {}
        for k in ('best', 'disparity'):
            per_day[k] = round(bk[k] / c[k], 2) if c[k] >= MIN_DAYS else None
        months.append({
            'hotel': hotel, 'month': month, 'days': len(rs), 'best_rate_days': c['best'],
            'disparity_days': c['disparity'], 'no_record_days': c['no_record'], 'unknown_status_days': c['other'],
            'unknown_statuses': sorted({r['status_text'] for r in rs if r['status'] == 'other'}),
            'disparity_pct_of_recorded': round(100 * c['disparity'] / recorded, 1) if recorded else None,
            'disparity_dates': [r['date'] for r in rs if r['status'] == 'disparity'],
            'longest_disparity_run_days': _runs([r['date'] for r in rs if r['status'] == 'disparity']),
            'no_record_pattern': nr_pattern, 'no_record_dates': [r['date'] for r in rs if r['status'] == 'no_record'],
            'bookings': sum(r['bookings'] for r in rs), 'bookings_on': dict(bk),
            'bookings_per_day': per_day,
            'comparison_note': ('' if per_day['best'] is not None and per_day['disparity'] is not None else
                                f'too few days of one type (under {MIN_DAYS}) to compare bookings per day'),
        })
    return months


def _label(month):
    y, m = month.split('-')
    return date(int(y), int(m), 1).strftime('%b %Y')


def report_block(months):
    """The `parity` block for a list JSON, the lead line (when disparity is material) and "already working" rows."""
    rows, working, lead, questions = [], [], [], []
    for m in months:
        name = _label(m['month']) + (f" · {m['hotel']}" if len({x['hotel'] for x in months}) > 1 else '')
        rows.append([name, str(m['best_rate_days']), str(m['disparity_days']), str(m['no_record_days'])
                     + (f" ({m['no_record_pattern']})" if m['no_record_pattern'] else ''),
                     f"{m['bookings']} ({m['bookings_on'].get('best', 0)} on best-rate days, "
                     f"{m['bookings_on'].get('disparity', 0)} on disparity days)"])
        recorded = m['best_rate_days'] + m['disparity_days']
        if recorded and m['disparity_days'] == 0:
            working.append([f"Rate parity, {_label(m['month'])}", 'OK', f"Best rate on all {recorded} recorded days "
                            f"(Best Rate calendar)" + (f"; {m['no_record_days']} days not recorded" if
                                                       m['no_record_days'] else '')])
        if m['disparity_pct_of_recorded'] is not None and m['disparity_pct_of_recorded'] >= 20:
            lead.append(f"In {_label(m['month'])} the website was not the best rate on {m['disparity_days']} of {recorded} "
                        f"recorded days ({m['disparity_pct_of_recorded']}%; longest run {m['longest_disparity_run_days']} "
                        "days, Best Rate calendar). Page fixes won't win a booking the OTAs sell cheaper: this is for "
                        "the revenue team first.")
        if m['no_record_days']:
            questions.append(f"{_label(m['month'])}: {m['no_record_days']} days have no parity record"
                             + (f" ({m['no_record_pattern']})" if m['no_record_pattern'] else '')
                             + ': is the monitoring skipping those days?')
        if m['unknown_status_days']:
            questions.append(f"{_label(m['month'])}: status {m['unknown_statuses']} isn't recognised: what does it mean?")
    block = {'title': 'Rate parity (Best Rate calendar)',
             'columns': ['Month', 'Best rate days', 'Disparity days', 'No record', 'Direct bookings'],
             'rows': rows,
             'note': 'From MetaHotels\' parity monitoring. For information: rates are a revenue-team action, never a '
                     'change on the website. Bookings by day type are context, not proof of cause.'}
    return {'parity': block, 'lead_lines': lead, 'working_rows': working, 'questions_for_metahotels': questions}


def import_calendars(files, out_dir):
    rows = []
    for f in files:
        rows += read(f)
    if not rows:
        raise ValueError('no rows in the calendar file(s)')
    months = summarise(rows)
    out = paths.resolve(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rb = report_block(months)
    result = {'files': [str(paths.resolve(f)) for f in files], 'imported': date.today().isoformat(),
              'months': months, **rb}
    (out / 'parity-calendar.json').write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding='utf-8')
    L = ['# Rate parity: Best Rate calendar', '']
    for m in months:
        L += [f"## {m['hotel']} · {m['month']}", '',
              f"- {m['days']} days: best rate {m['best_rate_days']}, disparity {m['disparity_days']}"
              + (f" ({m['disparity_pct_of_recorded']}% of recorded days, longest run {m['longest_disparity_run_days']})"
                 if m['disparity_days'] else '')
              + f", no record {m['no_record_days']}" + (f" ({m['no_record_pattern']})" if m['no_record_pattern'] else ''),
              f"- Direct bookings {m['bookings']}: {m['bookings_on'].get('best', 0)} on best-rate days, "
              f"{m['bookings_on'].get('disparity', 0)} on disparity days, {m['bookings_on'].get('no_record', 0)} on "
              f"days with no record",
              f"- Bookings per day: best-rate days {m['bookings_per_day']['best']}, disparity days "
              f"{m['bookings_per_day']['disparity']}" + (f" ({m['comparison_note']})" if m['comparison_note'] else ''),
              (f"- Disparity dates: {', '.join(m['disparity_dates'])}" if m['disparity_dates'] else '- No disparity days'),
              ''] + ([f"- UNKNOWN status values (ask what they mean): {m['unknown_statuses']}", ''] if
                     m['unknown_statuses'] else [])
    (out / 'parity-calendar.md').write_text('\n'.join(L), encoding='utf-8')
    return {'files_written': [str(out / 'parity-calendar.json'), str(out / 'parity-calendar.md')], **result}
