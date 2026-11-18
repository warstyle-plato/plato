"""Sparse discovery warms every original formula in the original calendar order."""
import copy
import sys

from openpyxl import Workbook
from openpyxl.utils import get_column_letter
import pytest

import office_workbook as office
from xlsx_eval import Evaluator, FormulaError


def _book(months):
    book = Workbook()
    clock = book.active
    clock.title = office.TIME_SHEET
    for index in range(months):
        clock.cell(office.K_ROW, office.FIRST_COL + index, index)
    return book


def _legacy_warmup(book, evaluator_type=Evaluator):
    """Pre-change traversal, used only as the independent regression oracle."""
    evaluator = evaluator_type(book)
    n = book[office.TIME_SHEET].max_column - office.FIRST_COL + 1
    monthly = [sheet for sheet in book.worksheets
               if sheet.max_column >= office.FIRST_COL + n - 1
               and sheet.cell(office.K_ROW, office.FIRST_COL).value is not None]
    for column in range(office.FIRST_COL, office.FIRST_COL + n):
        letter = get_column_letter(column)
        for sheet in monthly:
            for row in range(1, sheet.max_row + 1):
                value = sheet[f'{letter}{row}'].value
                if isinstance(value, str) and value.startswith('='):
                    evaluator.cell(sheet.title, f'{letter}{row}')
    return evaluator


def _snapshot(book):
    return [(sheet.title, tuple(sorted((key, cell.value, cell.data_type, cell.style_id)
                                      for key, cell in sheet._cells.items())),
             str(sheet.merged_cells)) for sheet in book.worksheets]


def _sparse(months):
    book = _book(months)
    for title, header in [('Первый', 0), ('Второй', False)]:
        sheet = book.create_sheet(title)
        sheet['D4'] = header  # Zero/False still qualify: only None excludes a sheet.
        sheet['F6'] = 1
        # Deliberately insert formulas out of row/column order.
        sheet['E10000'] = '=2+3'
        sheet['D1000'] = '=4+5'
        sheet['F50'] = '=6+7'
        sheet['D11'] = '=8+9'
        sheet['D12'] = ' =not-a-formula'
        sheet['E12'] = None
        sheet['F12'] = True
        sheet['D13'] = 0
        sheet['D15'] = '=1'
        sheet.merge_cells('D15:E15')
        sheet['C20'] = '=NOT_IN_MONTHS()'
        sheet['G20'] = '=AFTER_LAST_MONTH()'
    empty_header = book.create_sheet('Без календаря')
    empty_header['D4'], empty_header['F5'] = None, '=NO_CALENDAR()'
    short = book.create_sheet('Короткий')
    short['D4'], short['D500'] = 0, '=SHORT_SHEET()'
    return book


@pytest.mark.parametrize('months', [1, 3])
def test_sparse_discovery_preserves_exact_trace_and_never_creates_blank_cells(monkeypatch, months):
    class Trace:
        def __init__(self, book):
            self.book, self.calls = book, []

        def cell(self, sheet, address):
            self.calls.append((sheet, address))

    legacy = _sparse(months)
    expected = _legacy_warmup(legacy, Trace).calls
    source = _sparse(months)
    before = _snapshot(source)
    limit = sys.getrecursionlimit()
    monkeypatch.setattr(office, 'Evaluator', Trace)
    actual = office.evaluate(source)
    assert actual.calls == expected
    assert ('Первый', 'D1000') in actual.calls
    assert ('Второй', 'D11') in actual.calls
    assert (('Первый', 'E10000') in actual.calls) == (months == 3)
    assert all(address[0] not in ('C', 'G') for _, address in actual.calls)
    assert not any(sheet == 'Без календаря' for sheet, _ in actual.calls)
    assert (('Короткий', 'D500') in actual.calls) == (months == 1)
    assert _snapshot(source) == before
    assert sys.getrecursionlimit() == limit
    assert sum(len(sheet._cells) for sheet in legacy) > sum(len(sheet._cells) for sheet in source)


def _dependent_book():
    book = _book(3)
    first = book.create_sheet('Первый')
    second = book.create_sheet('Второй')
    for sheet in (first, second):
        sheet['D4'], sheet['F4'] = 0, 2
    first['D6'], first['E6'], first['F6'] = 2, '=D6+1', '=E6+1'
    first['D8'] = "='Второй'!F8+1"  # Forward cross-sheet/month dependency.
    first['E1000'], first['F1000'] = '=SUM(D6:F6)', '=IF(1,42,1/0)'
    second['D6'], second['F8'] = 10, '=D6+4'
    second['D10'] = '=IFERROR(1/0,3)'
    first['G10'] = '=AFTER_LAST_MONTH()'
    return book


def test_real_evaluator_keeps_dependencies_lazy_errors_cache_and_source_cells():
    source = _dependent_book()
    before = _snapshot(source)
    expected = _legacy_warmup(copy.deepcopy(source))
    actual = office.evaluate(source)
    assert actual._cache == expected._cache
    assert actual.cell('Первый', 'D8') == 15
    assert actual.cell('Первый', 'E1000') == 9
    assert actual.cell('Первый', 'F1000') == 42
    assert actual.cell('Второй', 'D10') == 3
    assert _snapshot(source) == before


def test_dense_calendar_keeps_full_cache_ranges_and_monthly_dependencies():
    source = _book(36)
    first = source.create_sheet('Первый')
    second = source.create_sheet('Второй')
    for index in range(36):
        column = office.FIRST_COL + index
        letter = get_column_letter(column)
        previous = get_column_letter(column - 1)
        for sheet in (first, second):
            sheet.cell(office.K_ROW, column, index)
        first.cell(6, column, '=1' if index == 0 else f'={previous}6+1')
        second.cell(6, column, f"='Первый'!{letter}6*2")
        first.cell(7, column, f'=SUM($D$6:{letter}6)')
        second.cell(7, column, f'=IF(1,SUM({letter}6:{letter}6),1/0)')
        first.cell(8, column, '=IFERROR(1/0,3)')
        second.cell(8, column, '=IF(0,NOPE(1),7)')
    before = _snapshot(source)
    expected = _legacy_warmup(copy.deepcopy(source))
    actual = office.evaluate(source)
    assert actual._cache == expected._cache
    assert actual._ranges == expected._ranges
    assert actual.cell('Первый', 'AM6') == 36
    assert actual.cell('Второй', 'AM7') == 72
    assert _snapshot(source) == before


@pytest.mark.parametrize('formula', ['=NOPE(1)', '=SUM(1;2)', '=D20'])
def test_unknown_formula_and_cycle_errors_still_fail_and_restore_recursion_limit(formula):
    source = _book(1)
    source[office.TIME_SHEET]['D20'] = formula
    limit = sys.getrecursionlimit()
    with pytest.raises(FormulaError) as old:
        _legacy_warmup(copy.deepcopy(source))
    with pytest.raises(FormulaError) as new:
        office.evaluate(source)
    assert type(new.value) is type(old.value) and str(new.value) == str(old.value)
    assert sys.getrecursionlimit() == limit
