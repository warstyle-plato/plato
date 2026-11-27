"""A synthetic dated-column chart: labels, bars and continuation are source evidence."""
import pytest

import developaid_contract_documents as documents
from tests.test_contract_documents_are_read_from_their_tables import _page, _text, pymupdf

BOUNDS = (30, 60, 300, 345, 390, 430, 470, 510, 550)
BLUE = (.77, .85, .94)


def _body(page, top, rows):
    bottom = top + 40 * len(rows)
    for x in BOUNDS:
        page.draw_line((x, top), (x, bottom), width=.5)
    # A stray vertical through the name is not a new column.
    page.draw_line((190, top), (190, bottom), width=.5)
    for i, (code, name, bars) in enumerate(rows):
        y = top + i * 40
        for first, last in bars:
            # The source fill reaches 0.55 pt beyond its table border.
            page.draw_rect(pymupdf.Rect(BOUNDS[4+first]+.42, y+.42,
                                        BOUNDS[5+last]+.55, y+40+.55), color=None, fill=BLUE)
        for col, text in enumerate((code, name, 'м3', '12')):
            _text(page, BOUNDS[col]+2, y+12, text)
    for i in range(len(rows)+1):
        y=top+i*40
        page.draw_line((BOUNDS[0], y), (BOUNDS[-1], y), width=.5)


def pdf(marks=('10.05.26', '20.05.26', '30.05.26', '10.06.26'),segmented=False):
    document = pymupdf.open()
    page = _page(document)
    _text(page, 30, 25, 'Приложение № 2 к Договору подряда № 8-ТСТ от 01.05.2026')
    _text(page, 30, 40, 'График производства работ')
    top, bottom = 60, 135
    for x in BOUNDS:
        page.draw_line((x, top), (x, bottom), width=.5)
    # The same phantom rule also crosses the header, plus an outside signature border.
    page.draw_line((190, top), (190, bottom), width=.5)
    page.draw_line((600, top), (600, bottom+200), width=.5)
    for y in (top, bottom):
        if segmented:
            for left,right in zip(BOUNDS,BOUNDS[1:]):
                page.draw_line((left,y),(right,y),width=.5)
        else:
            page.draw_line((BOUNDS[0], y), (BOUNDS[-1], y), width=.5)
    for col, text in enumerate(('№ п/п', 'Наименование', 'Ед. изм.', 'Объём')):
        _text(page, BOUNDS[col]+2, top+16, text)
    for i, mark in enumerate(marks):
        page.insert_text((BOUNDS[4+i]+20, bottom-5), mark, fontsize=7, fontname='cyr', rotate=90)
    # Printed column ordinals must not become work1 with name2.
    numbers_bottom = bottom+16
    for i in range(len(BOUNDS)-1):
        _text(page, BOUNDS[i]+2, bottom+11, str(i+1))
        page.draw_line((BOUNDS[i], bottom), (BOUNDS[i], numbers_bottom), width=.5)
    page.draw_line((BOUNDS[0], numbers_bottom), (BOUNDS[-1], numbers_bottom), width=.5)
    _body(page, numbers_bottom, [('1.1', 'Кладка тестовая А', ((0,0),(2,3)))])
    # The following page has no title, calendar or column header.
    _body(_page(document), 40, [('1.2', 'Кладка тестовая Б', ((1,3),))])
    return document.tobytes()


def test_dated_columns_keep_rotated_labels_complete_names_and_continuation():
    got = documents.read(pdf())
    schedule = got['schedule']
    assert schedule is not None and schedule['pages'] == [1,2]
    assert [line['code'] for line in schedule['lines']] == ['1.1','1.2']
    first,last = schedule['lines']
    assert first['name'] == 'Кладка тестовая А' and last['name'] == 'Кладка тестовая Б'
    assert (first['start'],first['finish']) == ('2026-05-10','2026-06-10')
    assert (last['start'],last['finish']) == ('2026-05-20','2026-06-10')
    assert all(line['date_precision'] == 'chart_marks' for line in schedule['lines'])
    assert schedule['assumption'] == documents.CHART_DATES_ASSUMPTION
    assert documents.CHART_DATES_ASSUMPTION in schedule['warnings']
    assert all(not line['corrected'] for line in schedule['lines'])


def test_full_years_are_read_without_reinterpreting_the_labels_as_period_ends():
    schedule = documents.read(pdf(('10.05.2026','20.05.2026','30.05.2026','10.06.2026')))['schedule']
    assert schedule['lines'][0]['start'] == '2026-05-10'
    assert schedule['lines'][1]['finish'] == '2026-06-10'


def minimal_pdf(marks=('10.05.26','20.05.26','30.05.26','10.06.26'),merged_headings=False):
    """Two labelled metadata columns; no unit or quantity is present in this form."""
    document = pymupdf.open()
    bounds = (30,70,310,370,430,490,550)
    for page_number in range(2):
        page = _page(document)
        if page_number == 0:
            _text(page,30,30,'График производства работ')
        top,bottom = 60,120
        rows = ([('1.1','Операция А',((0,0),(2,3)),None)] if page_number == 0 else
                [('1.2','Операция Б',((1,3),),None),
                 ('2.1','Необходимое количество ИТР, чел.',(),('1','1','1','1')),
                 ('2.2','Необходимое количество Рабочих, чел.',(),('4','5','6','6'))])
        if merged_headings:
            if page_number == 0:
                rows.insert(0,('1','Раздел с подробным названием работ, продолжающимся в календарной части таблицы',(),None))
            else:
                rows.insert(1,('2','Необходимое количество ИТР и Рабочих на объекте (назначенные по приказу)',(),None))
        for x in bounds+(190,600):
            page.draw_line((x,top),(x,bottom),width=.5)
        _text(page,bounds[0]+2,top+14,'№ п/п')
        _text(page,bounds[1]+2,top+14,'Наименование')
        for i,mark in enumerate(marks):
            page.insert_text((bounds[i+2]+22,bottom-5),mark,fontsize=7,fontname='cyr',rotate=90)
        # Printed ordinals also identify the merged name's right boundary.
        for i in range(len(bounds)-1):
            _text(page,bounds[i]+2,bottom+12,str(i+1))
        body=bottom+20
        for i,(code,name,bars,values) in enumerate(rows):
            y=body+i*40
            merged=merged_headings and code in ('1','2')
            for x in (bounds[0],bounds[1],bounds[-1]) if merged else bounds:
                page.draw_line((x,y),(x,y+40),width=.5)
            if not merged:
                page.draw_line((410,y),(410,y+40),width=.5)
            for start,finish in bars:
                page.draw_rect(pymupdf.Rect(bounds[2+start],y,bounds[3+finish],y+40),color=None,fill=BLUE)
            _text(page,bounds[0]+2,y+14,code)
            _text(page,bounds[1]+2,y+14,name)
            for col,value in enumerate(values or ()):
                _text(page,bounds[col+2]+10,y+14,value)
        for x in bounds:
            page.draw_line((x,bottom),(x,body),width=.5)
        for y in (top,bottom,body,*[body+40*i for i in range(1,len(rows)+1)]):
            page.draw_line((bounds[0],y),(bounds[-1],y),width=.5)
    return document.tobytes()


def test_two_column_metadata_keeps_dates_gaps_and_staffing_without_invented_quantities():
    schedule=documents.read(minimal_pdf())['schedule']
    assert schedule['pages']==[1,2]
    assert [x['code'] for x in schedule['lines']]==['1.1','1.2']
    a,b=schedule['lines']
    assert (a['start'],a['finish'])==('2026-05-10','2026-06-10')
    assert a['segments']==[{'start':'2026-05-10','finish':'2026-05-10'},
                           {'start':'2026-05-30','finish':'2026-06-10'}]
    assert (b['start'],b['finish'])==('2026-05-20','2026-06-10')
    assert all('unit' not in x and 'quantity' not in x for x in (a,b))
    assert schedule['assumption']==documents.CHART_DATES_ASSUMPTION
    assert [(x['category'],[v['value'] for v in x['values']]) for x in schedule['resources']]==[
        ('itr',[1,1,1,1]),('workers',[4,5,6,6])]
    assert all(x['scope'] is None for x in schedule['resources'])


def test_merged_group_titles_are_complete_and_staff_heading_is_not_an_observation():
    schedule=documents.read(minimal_pdf(merged_headings=True))['schedule']
    assert schedule['lines'][0]['name']=='Раздел с подробным названием работ, продолжающимся в календарной части таблицы'
    assert [x['code'] for x in schedule['lines']]==['1','1.1','1.2']
    assert [x['category'] for x in schedule['resources']]==['itr','workers']
    assert schedule['resource_headings'][0]['name'].endswith('(назначенные по приказу)')
    assert not any('Наименование' in x for x in schedule['warnings'])


@pytest.mark.parametrize('marks',[
    ('','20.05.26','30.05.26','10.06.26'),
    ('10.05.26','','30.05.26','10.06.26'),
    ('10.05.26','31.02.26','30.05.26','10.06.26'),
    ('10.05.26','30.05.26','20.05.26','10.06.26'),
])
def test_two_column_metadata_preserves_works_but_does_not_guess_unread_dates(marks):
    schedule=documents.read(minimal_pdf(marks))['schedule']
    works=[x for x in schedule['lines'] if x['code'] in ('1.1','1.2')]
    assert len(works)==2 and all(x['start'] is None and x['finish'] is None for x in works)
    assert any('Сроки полос не прочитаны' in x for x in schedule['warnings'])


@pytest.mark.parametrize('marks,reason', [
    (('10.05.26','31.02.26','30.05.26','10.06.26'),'недопустимая календарная дата'),
    (('10.05.26','30.05.26','20.05.26','10.06.26'),'не возрастают'),
    (('10.05.26','20.05.26','20.05.26','10.06.26'),'не возрастают'),
    (('10.05.26','','30.05.26','10.06.26'),'не прочитана дата'),
    (('','','30.05.26','10.06.26'),'не прочитана дата'),
    (('10.05.26','20.05.26','30.05.26',''),'не прочитана дата'),
    (('','','','10.06.26'),'не прочитана дата'),
])
@pytest.mark.parametrize('segmented',[False,True])
def test_invalid_or_non_monotonic_labels_keep_rows_but_never_fabricate_dates(marks,reason,segmented):
    schedule=documents.read(pdf(marks,segmented))['schedule']
    assert len(schedule['lines']) == 2
    assert [line['code'] for line in schedule['lines']] == ['1.1','1.2']
    assert all(line['start'] is None and line['finish'] is None for line in schedule['lines'])
    assert any(reason in warning for warning in schedule['warnings'])
