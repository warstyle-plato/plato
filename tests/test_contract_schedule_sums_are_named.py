"""Суммы, напечатанные в ГПР, читатель не берёт, но называет: план раскладывается по дням строк равномерно.

Сумма в клетке диаграммы и графа «Сумма» в шапке дают предупреждение со страницей и строками.
Номера недель, единицы и год в клетках суммой не считаются. Графики выдуманы: репозиторий публичный.
"""
from __future__ import annotations

import pymupdf
import pytest

import developaid_contract_documents as documents
from tests.test_contract_documents_are_read_from_their_tables import SCHEDULE_COLUMNS, _font, schedule_pdf
from tests.test_contract_documents_of_the_weekly_layout import WEEK_COLUMNS, weekly_pdf

TAIL = "Помесячные суммы графика не прочитаны: план разложен по дням строк равномерно."


def _edited(data, *texts):
    """The PDF with `texts` (page, x, y, text) printed over it, as a schedule with sums is."""
    document = pymupdf.open(stream=data, filetype="pdf")
    for number, x, y, text in texts:
        page = document[number]
        page.insert_font(fontname="cyr", fontfile=_font())
        page.insert_text((x, y), text, fontsize=6, fontname="cyr")
    return document.tobytes()


def _warnings(data):
    return documents.read(data)["schedule"]["warnings"]


# Строка 1.1 «Разметка» — вторая строка тела дневного графика.
ROW_1_1 = 60 + 40 + 16 + 11


def test_a_sum_in_a_day_cell_of_the_chart_is_named_with_its_line():
    warnings = _warnings(_edited(schedule_pdf(), (0, SCHEDULE_COLUMNS[5] + 1, ROW_1_1, "12500")))
    assert f"Стр. 1: на диаграмме напечатаны суммы у строк 1.1. {TAIL}" in warnings


@pytest.mark.parametrize("text", ["2-14", "1", "2026"])
def test_a_week_number_a_unit_or_a_year_in_a_cell_is_no_sum(text):
    assert not any(TAIL in w for w in _warnings(_edited(schedule_pdf(), (0, SCHEDULE_COLUMNS[5] + 2, ROW_1_1, text))))


def test_a_money_column_in_the_weekly_header_is_named():
    warnings = _warnings(_edited(weekly_pdf(), (0, WEEK_COLUMNS[2] + 2, 60 + 26, "Сумма, руб.")))
    assert f"Стр. 1: в шапке графика есть графа «Примечание Сумма, руб.». {TAIL}" in warnings


def test_a_sum_on_a_weekly_continuation_page_is_named_with_its_line():
    # Строка 4 «Благоустройство территории» — седьмая строка второй страницы.
    warnings = _warnings(_edited(weekly_pdf(), (1, WEEK_COLUMNS[3] + 2, 40 + 16 * 6 + 11, "350,00")))
    assert f"Стр. 2: на диаграмме напечатаны суммы у строк 4. {TAIL}" in warnings


def test_a_schedule_without_sums_says_nothing_about_them():
    assert not any(TAIL in w for w in _warnings(schedule_pdf()) + _warnings(weekly_pdf()))
