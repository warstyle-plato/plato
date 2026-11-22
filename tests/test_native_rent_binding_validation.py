"""Missing parcel allocation must not become a guessed registration horizon."""
from datetime import date

import pytest

import developaid_land_rent as rent
import office_workbook as ow
from test_native_land_rent_books import settings
from xlsx_eval import Evaluator


OBJECTS = [{"key": "offices", "title": "Офис"},
           {"key": "standalone_retail", "title": "Торговый центр"}]


def unallocated():
    items, missing = rent.planning_exposures({}, date(2029, 1, 1),
        housing=False, housing_area=None, objects=[
            {"id": item["key"], "object_key": item["key"], "name": item["title"],
             "total_area": None, "commissioning": "2029-01-01", "lease_exit": "2034-01-01",
             "policy": "income_horizon"} for item in OBJECTS])
    assert missing
    return items


def test_unallocated_mixed_area_is_an_actionable_error_not_a_three_month_cutoff():
    items = unallocated()
    with pytest.raises(ValueError, match="укажите площади и состав объектов в ТЭП") as error:
        ow._rent_object_bindings(items, OBJECTS)
    text = str(error.value)
    assert "Офис" in text and "Торговый центр" in text
    assert "unallocated" not in text and "object_key" not in text


def test_accessory_keeps_its_explicit_canonical_parent_binding():
    # An exposure ID is not its owning object. No name/prefix guess is used.
    items = [{"id": "accessory-parking", "object_key": "offices", "share": .2}]
    assert ow._rent_object_bindings(items, OBJECTS)["offices"] is OBJECTS[0]


def test_known_area_multiple_objects_keep_their_explicit_bindings():
    items = [{"id": "office-land", "object_key": "offices", "share": .4},
             {"id": "retail-land", "object_key": "standalone_retail", "share": .6}]
    assert ow._rent_object_bindings(items, OBJECTS) == {item["key"]: item for item in OBJECTS}


def test_native_entry_point_refuses_unmapped_owner_before_writing_calendar(monkeypatch):
    book = ow._Book(36, date(2027, 1, 1))
    book.paths = (ow.PROJECT_PATH,)
    book.register("in.start", "Вводные", 4, "C")
    spec = {"land_rent_inputs": {"land_right": "lease", "land_rent_mode": "manual"},
            "land_rent": {"land_exposures": unallocated()}}

    def unexpected(*args, **kwargs):
        pytest.fail("Календарь с придуманной границей аренды не должен быть создан")

    monkeypatch.setattr(ow.land_rent_book, "add", unexpected)
    with pytest.raises(ValueError, match="Невозможно распределить аренду"):
        ow._rent_calendars(book, {}, spec, OBJECTS)
    assert not book.rent_calendars


def live_area_book(single=False):
    start = date(2027, 1, 1)
    book = ow._Book(36, start)
    inputs = book.wb.create_sheet('Вводные')
    inputs['A3'], inputs['B3'], inputs['C3'] = 5000, 10000, start
    book.register('in.start', inputs.title, 3, 'C')
    objects, exposures = [], []
    for column, key, share in [('A', 'offices', 1 if single else 1/3),
                                ('B', 'standalone_retail', 2/3)]:
        if single and column == 'B':
            continue
        inputs[f'{column}4'], inputs[f'{column}5'], inputs[f'{column}6'] = start, 12, 35
        code = column.lower()
        objects.append({'key':key,'code':code,'title':key,'nonres':True,'strategy':'income'})
        exposures.append({'id':key,'object_key':key,'share':share,'total_area':inputs[f'{column}3'].value,
            'commissioning':'2028-01-01','lease_exit':'2030-01-01','retained':True,'policy':'income_horizon'})
        for name, row in [('total_area',3),('start',4),('months',5)]:
            book.register(f'in.{code}.{name}',inputs.title,row,column)
        book.register(f'{code}r.horizon',inputs.title,6,column)
    dates = book.wb.create_sheet(ow.TIME_SHEET)
    for index in range(book.n):
        year, month = divmod(start.year*12 + start.month-1 + index,12)
        dates.cell(ow.DATE_ROW,ow.FIRST_COL+index,date(year,month+1,1))
    path = dict(code='r',key='income',label='Аренда',strategy='income',
                object_keys={o['key'] for o in objects},result_key='office_paths')
    book.paths=(path,)
    book.groups=[dict(current='income',paths=[path])]
    terms=settings()
    rental=rent.build(terms,start,date(2028,1,1),date(2030,1,1),exposures=exposures)
    spec={'land_rent_inputs':terms,'land_rent':rental}
    ow._rent_calendars(book,{'office_paths':{'paths':[dict(key='income',land_rent=rental)]}},spec,objects)
    book.resolve()
    return book,inputs,book.rent_calendars['r'][0]


def test_cleared_live_area_is_unknown_but_an_explicit_zero_stays_known():
    book,inputs,calendar=live_area_book()
    row=calendar.layout['exposure_rows']['offices']['metadata']
    before=Evaluator(book.wb)
    assert before.cell(calendar.sheet_name,f'B{row}') == pytest.approx(1/3)
    assert before.cell(calendar.sheet_name,'I20') == 'Заданы'
    inputs['A3']=None
    unknown=Evaluator(book.wb)
    assert unknown.cell(calendar.sheet_name,f'B{row}') == ''
    assert unknown.cell(calendar.sheet_name,'I20') == 'Не полны'
    assert unknown.cell(calendar.sheet_name,'L13')
    inputs['A3']=0
    known_zero=Evaluator(book.wb)
    assert known_zero.cell(calendar.sheet_name,f'B{row}') == 0
    assert known_zero.cell(calendar.sheet_name,'I20') == 'Заданы'


def test_single_canonical_owner_needs_no_new_area_confirmation():
    book,inputs,calendar=live_area_book(single=True)
    row=calendar.layout['exposure_rows']['offices']['metadata']
    inputs['A3']=None
    evaluator=Evaluator(book.wb)
    assert evaluator.cell(calendar.sheet_name,f'B{row}') == 1
    assert evaluator.cell(calendar.sheet_name,'I20') == 'Заданы'
