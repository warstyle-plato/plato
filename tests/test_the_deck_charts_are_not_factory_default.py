"""Графики колоды одеты по продукту, а не оставлены заводскими.

«PPT убогие графики очень, как для первого класса школы» (владелец,
30.08.2026) — и это была правда: столбик во всю ширину слота офисной синевы,
сетка по всему полю, ось со значениями, подписи заводским шрифтом, таблицы в
синюю полоску.

Правила взяты не с потолка: один ряд — легенды нет, её работу делает заголовок
слайда; текст носит текстовые токены, а не цвет ряда; значения стоят прямо на
столбиках, пока их немного, и тогда сетка с осью — лишняя краска; столбик не
заполняет слот. Цвет — фирменный синий кабинета, и он проверен валидатором
палитры (светлота, насыщенность, контраст к белому).

Запуск: python3 -m pytest tests/test_the_deck_charts_are_not_factory_default.py -q
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from market_search import sales_deck  # noqa: E402

pptx = pytest.importorskip("pptx")


def deck(categories: int):
    head = ["Месяц", "млн ₽"]
    rows = [[f"2026-{month + 1:02d}", str(100 + month)] for month in range(categories)]
    pages = [{"title": "Динамика", "note": "Темп растёт.",
              "tables": [{"head": head, "rows": rows}], "lines": []}]
    raw = sales_deck.build(pages, title="Продажи", subtitle="срез", footer="DevelopAid")
    return pptx.Presentation(io.BytesIO(raw))


def charts(presentation):
    return [shape.chart for slide in presentation.slides for shape in slide.shapes
            if getattr(shape, "has_chart", False) and shape.has_chart]


def tables(presentation):
    return [shape.table for slide in presentation.slides for shape in slide.shapes
            if getattr(shape, "has_table", False) and shape.has_table]


def test_the_bar_wears_the_product_colour_not_the_office_blue() -> None:
    chart = charts(deck(6))[0]
    series = chart.plots[0].series[0]
    assert str(series.format.fill.fore_color.rgb) == "1367AE", "фирменный синий кабинета"
    # Обводки у столбика нет: рамка вокруг метки — краска, которая не данные.
    assert series.format.line.fill.type is not None


def test_one_series_has_no_legend() -> None:
    """Легенда из одной строки повторяет заголовок слайда и ест место."""
    assert charts(deck(6))[0].has_legend is False


def test_few_columns_carry_their_values_and_drop_the_grid() -> None:
    chart = charts(deck(5))[0]
    plot = chart.plots[0]
    assert plot.has_data_labels is True
    assert chart.value_axis.has_major_gridlines is False
    assert chart.value_axis.visible is False, "ось со значениями рядом с подписями — лишняя"


def test_many_columns_drop_the_labels_and_keep_a_hairline_grid() -> None:
    """Число на каждом столбике — хаос, когда столбиков тринадцать."""
    chart = charts(deck(13))[0]
    assert chart.plots[0].has_data_labels is False
    assert chart.value_axis.has_major_gridlines is True
    assert chart.value_axis.visible is True
    line = chart.value_axis.major_gridlines.format.line
    assert str(line.color.rgb) == "E3EBF2", "сетка волосяная и отступает на второй план"


def test_the_column_does_not_fill_its_slot() -> None:
    """Столбик во всю ширину слота и есть то самое «как для первого класса»."""
    assert charts(deck(3))[0].plots[0].gap_width >= 400
    assert charts(deck(6))[0].plots[0].gap_width >= 250
    assert charts(deck(14))[0].plots[0].gap_width <= 100, "тринадцати столбикам нужен воздух поуже"


def test_the_text_does_not_wear_the_data_colour() -> None:
    chart = charts(deck(5))[0]
    assert str(chart.font.color.rgb) == "5B6B7D"
    labels = chart.plots[0].data_labels
    assert str(labels.font.color.rgb) == "16202B"
    assert labels.number_format == "#,##0.#" and labels.number_format_is_linked is False


def test_the_table_is_not_blue_striped() -> None:
    grid = tables(deck(5))[0]
    assert grid.first_row is True and grid.horz_banding is False
    assert str(grid.cell(0, 0).fill.fore_color.rgb) == "F4F7FA", "шапка на светлой подложке"
    assert str(grid.cell(1, 0).fill.fore_color.rgb) == "FFFFFF"


def test_numbers_stand_to_the_right() -> None:
    """Колонка чисел, прижатая влево, не читается столбиком."""
    from pptx.enum.text import PP_ALIGN

    grid = tables(deck(5))[0]
    value = grid.cell(1, 1)
    assert value.text_frame.paragraphs[0].alignment == PP_ALIGN.RIGHT
    assert grid.cell(1, 0).text_frame.paragraphs[0].alignment != PP_ALIGN.RIGHT
