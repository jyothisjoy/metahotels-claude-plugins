"""The Best Rate calendar (parity + bookings CSV) in the monthly report: shown for the month when imported, left out
silently when not."""
from hotel_seo_tools import monthly, parity_calendar

HEADER = 'Date,Weekday,Hotel,Parity Status,Bookings,Day Type\n'
HOTEL = 'Royal M Hotel by Gewan Abu Dhabi'


def _csv(tmp_path, month, statuses):
    """statuses: one (status, bookings) per day from the 1st."""
    lines = [HEADER]
    for i, (st, b) in enumerate(statuses, start=1):
        lines.append(f'{month}-{i:02d},Mon,{HOTEL},{st},{b},x\n')
    f = tmp_path / f'disparity-calendar-royal-m-{month}.csv'
    f.write_text(''.join(lines), encoding='utf-8')
    return f


def _ctx(hotel_dir):
    return {'hotel_dir': hotel_dir, 'hotel': {'name': HOTEL}}


def test_block_for_imported_month(tmp_path):
    hdir = tmp_path / 'hotel'
    oct_days = [('Best Rates/Corrected', 2)] * 18 + [('Disparity Email Sent', 1)] * 6 + [('No record', 0)] * 7
    sep_days = [('Best Rates/Corrected', 3)] * 25 + [('Disparity Email Sent', 0)] * 5
    files = [_csv(tmp_path, '2026-10', oct_days), _csv(tmp_path, '2026-09', sep_days)]
    parity_calendar.import_calendars([str(f) for f in files], str(hdir / 'parity'))

    block = monthly._calendar_block(_ctx(hdir), '2026-10', 'October 2026', 'September 2026')
    assert block and 'Best Rate calendar' in block['title']
    rows = {r[0]: r for r in block['table']['rows']}
    assert rows['Official site had the best rate'][1:3] == ['18', '36']
    assert rows['An OTA was cheaper (disparity)'][1:3] == ['6', '6']
    assert rows['Not checked (no record)'][1] == '7'
    assert '6 of 24 checked days' in block['text']
    assert 'September 2026: OTA cheaper on 5 of 30 checked days' in block['text']
    assert 'not that the price caused them' in block['text']


def test_no_calendar_or_other_month_is_left_out(tmp_path):
    hdir = tmp_path / 'hotel'
    assert monthly._calendar_block(_ctx(hdir), '2026-10', 'October 2026', 'September 2026') is None
    _csv(tmp_path, '2026-08', [('Best Rates/Corrected', 1)] * 31)
    parity_calendar.import_calendars([str(tmp_path / 'disparity-calendar-royal-m-2026-08.csv')], str(hdir / 'parity'))
    assert monthly._calendar_block(_ctx(hdir), '2026-10', 'October 2026', 'September 2026') is None


def test_january_compares_with_december():
    assert monthly._prev_month_start('2026-01') == '2025-12-01'
    assert monthly._prev_month_start('2026-10') == '2026-09-01'
