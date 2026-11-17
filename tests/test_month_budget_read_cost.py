"""Reading a small plan/fact sheet must not parse unrelated registry rows."""
import io

import openpyxl
import pytest
from openpyxl.worksheet._read_only import ReadOnlyWorksheet

import developaid_monthly_budget as monthly
from test_management_report_model import budget_book


def encoded(book):
    stream = io.BytesIO()
    book.save(stream)
    book.close()
    return stream.getvalue()


@pytest.mark.parametrize('title', ['П-Ф', 'План-факт'])
@pytest.mark.parametrize('position', [0, 1])
def test_named_budget_is_selected_before_reading_unrelated_sheets(monkeypatch, title, position):
    book = openpyxl.load_workbook(io.BytesIO(budget_book()))
    book.active.title = title
    expected = monthly.read_budget(encoded(book))
    book = openpyxl.load_workbook(io.BytesIO(budget_book()))
    book.active.title = title
    registry = book.create_sheet('Реестр', position)
    registry.cell(15000, 12, 'Посторонний большой реестр')
    raw = encoded(book)
    original, read = ReadOnlyWorksheet.iter_rows, []

    def observed(sheet, *args, **kwargs):
        read.append(sheet.title)
        assert sheet.title != 'Реестр', 'The unrelated registry must never be parsed.'
        return original(sheet, *args, **kwargs)

    monkeypatch.setattr(ReadOnlyWorksheet, 'iter_rows', observed)
    assert monthly.read_budget(raw) == expected
    assert read == [title]


def test_unnamed_budget_preserves_first_matching_sheet_and_stops_after_it(monkeypatch):
    book = openpyxl.load_workbook(io.BytesIO(budget_book()))
    book.active.title = 'Рабочий бюджет'
    expected = monthly.read_budget(encoded(book))
    book = openpyxl.load_workbook(io.BytesIO(budget_book()))
    book.active.title = 'Рабочий бюджет'
    book.create_sheet('Справка', 0)['A1'] = 'Описание'
    book.create_sheet('Поздний реестр')['A1'] = 'Другие данные'
    raw = encoded(book)
    original, read = ReadOnlyWorksheet.iter_rows, []

    def observed(sheet, *args, **kwargs):
        read.append(sheet.title)
        return original(sheet, *args, **kwargs)

    monkeypatch.setattr(ReadOnlyWorksheet, 'iter_rows', observed)
    assert monthly.read_budget(raw) == expected
    assert read == ['Справка', 'Рабочий бюджет']


def test_invalid_named_plan_fact_does_not_fall_back_to_another_sheet():
    book = openpyxl.load_workbook(io.BytesIO(budget_book()))
    book.active.title = 'Прежняя версия'
    book.create_sheet('П-Ф')['A1'] = 'Не прочитана шапка текущего бюджета'
    with pytest.raises(ValueError, match='не нашлось шапки'):
        monthly.read_budget(encoded(book))
