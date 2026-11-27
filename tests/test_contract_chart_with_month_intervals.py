"""Public structural fixtures only: four metadata columns, month headers and gray bars."""
import pytest

import developaid_contract_documents as documents
from tests.test_contract_documents_are_read_from_their_tables import _page, _text, pymupdf

BOUNDS = (25, 65, 295, 335, 375) + tuple(375+50*i for i in range(1, 8))
MONTHS = (('декабрь 2027', ('21-31',)),
          ('январь 2028', ('1-10', '11-20', '21-31')),
          ('февраль 2028', ('1-10', '11-20', '21-29')))
GRAY = (.65, .65, .65)
FIRST = (('7', 'Участок А', '', '', ()),
         ('7.1', 'Панель П-6', 'м2', '37,25', ((0, 2),)),
         ('7.2', 'Проём П-9 без срока', 'шт', '0', ()),
         ('7.3', 'Проём П-10 без срока', 'шт', '4', ()))
SECOND = (('8.1', 'Профиль М-5', 'м', '12,5', ((3, 4),)),
          ('8.2', 'Блок М-8', 'м3', '2,75', ((6, 6),)))


def _body(page, top, rows, *, gray=True):
    bottom = top+24*len(rows)
    for x in BOUNDS + (180,):  # A rule through the name is not a metadata column.
        page.draw_line((x, top), (x, bottom), width=.5)
    for i, (code, name, unit, quantity, bars) in enumerate(rows):
        y = top+24*i
        # Explicit white fills with staffing text must never become bars.
        page.draw_rect(pymupdf.Rect(BOUNDS[4], y, BOUNDS[-1], y+24), color=None, fill=(1, 1, 1))
        for first, last in bars:
            page.draw_rect(pymupdf.Rect(BOUNDS[4+first], y, BOUNDS[5+last], y+24),
                           color=None, fill=GRAY if gray else (1, 1, 1))
        for col, text in enumerate((code, name, unit, quantity)):
            _text(page, BOUNDS[col]+2, y+14, text)
        if quantity:
            _text(page, BOUNDS[4+(bars[0][0] if bars else 5)]+2, y+14, '2-4 чел')
    for i in range(len(rows)+1):
        page.draw_line((BOUNDS[0], top+24*i), (BOUNDS[-1], top+24*i), width=.5)


def pdf(months=MONTHS, *, missing=None, gray=True, segmented=False, quantity='37,25'):
    document = pymupdf.open()
    page = _page(document)
    _text(page, 25, 30, 'График производства работ')
    top, bottom = 60, 100
    for x in BOUNDS + (180, 790):  # A signature border outside the table.
        page.draw_line((x, top), (x, bottom+200), width=.5)
    for y in (top, bottom):
        for left, right in (zip(BOUNDS, BOUNDS[1:]) if segmented else [(BOUNDS[0], BOUNDS[-1])]):
            page.draw_line((left, y), (right, y), width=.5)
    page.draw_line((BOUNDS[4], top+20), (BOUNDS[-1], top+20), width=.5)
    for col, text in enumerate(('№ п/п', 'Наименование работ', 'Ед. изм.', 'Кол-во')):
        _text(page, BOUNDS[col]+2, top+14, text)
    col = 4
    for month, intervals in months:
        _text(page, (BOUNDS[col]+BOUNDS[col+len(intervals)])/2-24, top+12, month)
        for interval in intervals:
            if col-4 != missing:
                _text(page, BOUNDS[col]+4, bottom-5, interval)
            col += 1
    first = list(FIRST)
    first[1] = (*first[1][:3], quantity, first[1][4])
    _body(page, bottom, first, gray=gray)
    _body(_page(document), 40, SECOND, gray=gray)
    return document.tobytes()


def test_printed_intervals_preserve_metadata_order_bars_and_continuation_across_years():
    schedule = documents.read(pdf())['schedule']
    assert schedule['pages'] == [1, 2]
    assert schedule['assumption'] == documents.CHART_INTERVALS_ASSUMPTION
    assert documents.CHART_INTERVALS_ASSUMPTION in schedule['warnings']
    lines = schedule['lines']
    assert [(x['code'], x['name'], x['unit'], x['quantity'], x['page']) for x in lines] == [
        ('7', 'Участок А', None, None, 1), ('7.1', 'Панель П-6', 'м2', 37.25, 1),
        ('7.2', 'Проём П-9 без срока', 'шт', 0, 1), ('7.3', 'Проём П-10 без срока', 'шт', 4, 1),
        ('8.1', 'Профиль М-5', 'м', 12.5, 2), ('8.2', 'Блок М-8', 'м3', 2.75, 2)]
    assert [(x['start'], x['finish']) for x in lines] == [
        ('2027-12-21', '2028-01-20'), ('2027-12-21', '2028-01-20'), (None, None), (None, None),
        ('2028-01-21', '2028-02-10'), ('2028-02-21', '2028-02-29')]
    assert lines[0]['dates_from'] == {'start': 'works', 'finish': 'works'}
    assert lines[1]['bar'] == {'start': '2027-12-21', 'finish': '2028-01-20'}
    assert all(x['date_precision'] == 'chart_intervals' and not x['corrected'] for x in lines)
    assert all(x['cells'] == {'start': None, 'finish': None} for x in lines)
    assert any('у строки 7.2' in w and 'нет дат' in w for w in schedule['warnings'])


def test_staffing_text_and_white_calendar_fills_do_not_supply_dates():
    lines = documents.read(pdf(gray=False))['schedule']['lines']
    assert len(lines) == 6
    assert all(x['start'] is None and x['finish'] is None and x['bar'] is None for x in lines)


@pytest.mark.parametrize('missing', [0, 3, 6])
@pytest.mark.parametrize('segmented', [False, True])
def test_missing_interval_does_not_remove_a_calendar_column_or_fabricate_dates(missing, segmented):
    schedule = documents.read(pdf(missing=missing, segmented=segmented))['schedule']
    assert len(schedule['lines']) == 6
    assert all(x['start'] is None and x['finish'] is None for x in schedule['lines'])
    assert any('нет недели в шапке' in w for w in schedule['warnings'])


@pytest.mark.parametrize('months', [
    (MONTHS[0], ('январь', MONTHS[1][1]), MONTHS[2]),  # No borrowing another label's year.
    (('декабрь 2029', MONTHS[0][1]), MONTHS[1], MONTHS[2]),  # Years go backwards.
    (MONTHS[0], MONTHS[1], ('февраль 2028', ('1-10', '20-11', '21-29'))),
    (MONTHS[0], MONTHS[1], ('февраль 2028', ('1-10', '11-20', '21-30'))),
    (MONTHS[0], MONTHS[1], ('февраль 2028', ('1-10', '11-20', '21-29 1-5'))),
])
def test_incomplete_reversed_or_impossible_calendar_preserves_rows_without_dates(months):
    schedule = documents.read(pdf(months=months))['schedule']
    assert len(schedule['lines']) == 6
    assert all(x['start'] is None and x['finish'] is None for x in schedule['lines'])
    assert any('Сроки полос не прочитаны' in w for w in schedule['warnings'])


def test_unread_printed_quantity_is_preserved_with_its_page_instead_of_becoming_zero():
    schedule = documents.read(pdf(quantity='н/д'))['schedule']
    line = schedule['lines'][1]
    assert line['quantity'] is None and line['quantity_text'] == 'н/д'
    assert any('Стр. 1: у строки 7.1 количество «н/д» не прочитано' in w
               for w in schedule['warnings'])


def test_kept_reader12_unrecognized_chart_is_reread_from_its_same_pdf(monkeypatch, tmp_path):
    import hashlib
    import json
    import developaid_contract_files as files
    import developaid_monitor as monitor
    monkeypatch.setattr(monitor, '_SNAPSHOT_DIR', tmp_path/'monitor')
    row = {'id': 'c'*64, 'contract': '8-ТСТ', 'contract_date': '2027-12-01'}
    raw = pdf()
    saved = files.store('Учебный', row, 'Учебный график.pdf', raw)
    folder = files._directory('Учебный', row['id'])
    path = folder/(saved['sha256']+'.json')
    old = json.loads(path.read_text())
    old.update(reader=12, schedule=None, warnings=['Таблица графика не найдена.'])
    path.write_text(json.dumps(old, ensure_ascii=False))
    listed = files.listing('Учебный', row['id'], '2028-01-15')
    current, = listed['documents']
    assert current['reader'] == documents.READER_VERSION > 12
    assert len(current['schedule']['lines']) == 6
    assert current['schedule']['lines'][1]['start'] == '2027-12-21'
    assert current['schedule']['lines'][2]['start'] is None
    assert current['sha256'] == hashlib.sha256(raw).hexdigest()
    assert (folder/(saved['sha256']+'.pdf')).read_bytes() == raw
    assert not files._choices(folder)
    assert json.loads(path.read_text())['reader'] == documents.READER_VERSION
