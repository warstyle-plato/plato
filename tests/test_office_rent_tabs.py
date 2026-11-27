"""Office exports show one editable land-rent tab, keeping strategy formulas."""
from __future__ import annotations

import io

import openpyxl
import pytest

import native_land_rent_book as native
import office_workbook as ow
from test_native_land_rent_calendar import _project, core


@pytest.fixture(scope='module', params=['lease', 'owned_saved', 'owned_clean'])
def rental_export(request):
    x, t = _project('office')
    x.update(offices_hold_years=1, land_right='lease' if request.param == 'lease' else 'ownership')
    if request.param == 'owned_clean':
        x['land_rent_mode'] = 'unspecified'
    content, _, meta = core.build_project_workbook(x, t, [], {}, project_name='Вкладки аренды земли')
    assert meta['checks'] == ow.PASSED and not meta['missing'], meta
    return request.param, content, meta


def rental_sheets(book):
    return [s for s in book if s.title == native.SHEET
            or s.title.startswith('Аренда ЗУ · ') or s.title.startswith('Аренда оценка · ')]


def test_only_the_editable_land_rent_master_is_visible(rental_export):
    case, content, _ = rental_export
    book = openpyxl.load_workbook(io.BytesIO(content))
    calendars = rental_sheets(book)
    if case == 'owned_clean':
        assert not calendars
        return
    assert len(calendars) >= 5  # All strategy calendars still exist, not just the master.
    assert [s.title for s in calendars if s.sheet_state == 'visible'] == [native.SHEET]
    assert book[native.SHEET]['B8'].data_type != 'f'  # Common source remains editable.
    assert book[native.SHEET].data_validations.count
    for sheet in calendars:
        if sheet.title != native.SHEET:
            assert sheet.sheet_state == 'hidden'  # Excel's ordinary Unhide remains available.
            assert not sheet.sheet_view.tabSelected
            assert sheet['B8'].data_type == 'f' and "'Аренда ЗУ'!" in sheet['B8'].value
    guide = '\n'.join(str(c.value or '') for row in book[ow.GUIDE_SHEET] for c in row)
    assert '«Отобразить»' in guide and 'продолжают участвовать в формулах' in guide


def test_hidden_calendars_are_still_consumed_and_recalculated(rental_export):
    case, content, meta = rental_export
    formulas = openpyxl.load_workbook(io.BytesIO(content), read_only=True)
    calendars = rental_sheets(formulas)
    if case == 'owned_clean':
        assert not calendars
        return
    # Consumers outside the calendars must retain references to every hidden tab.
    remaining = {s.title for s in calendars if s.title != native.SHEET}
    for sheet in formulas:
        if sheet in calendars:
            continue
        for row in sheet.iter_rows(values_only=True):
            for value in row:
                if isinstance(value, str) and value.startswith('='):
                    remaining = {name for name in remaining if "'" + name + "'!" not in value}
        if not remaining:
            break
    assert not remaining, remaining
    cached = openpyxl.load_workbook(io.BytesIO(content), data_only=True, read_only=True)
    assert cached[ow.CHECK_SHEET]['I5'].value == ow.PASSED
    for sheet in calendars:
        assert isinstance(cached[sheet.title]['D6'].value, (int, float)), sheet.title
    assert len(meta['comparisons'][0]['paths']) == 5
