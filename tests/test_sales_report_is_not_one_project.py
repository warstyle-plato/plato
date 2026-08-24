"""Отчёт о продажах загружает кто угодно, а не владелец одной книги.

Кнопка звалась «Загрузить финмодель ПЛАТО», подпись под ней печатала имя
проекта из книги, а формат принимался только .xlsx и .xlsm. Вместе это читалось
как «сюда грузят вон тот проект»: на чужой книге подпись показывала чужое имя,
а рабочая финмодель в двоичном .xlsb получала ответ «файл не читается как книга
Excel» — верный по букве и бесполезный (владелец, 24.08.2026).

Запуск: python3 -m pytest tests/test_sales_report_is_not_one_project.py -q
"""

from __future__ import annotations

import datetime
import io
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from market_search import cabinet, plan  # noqa: E402


def _book(rows: list[list]) -> bytes:
    openpyxl = pytest.importorskip("openpyxl")
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "План продаж_утв"
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


ROWS = [
    ["Дата", None, "ВСЕГО, руб", None, None, None],
    [None, None, "руб", "шт", "кв.м.", "руб/кв.м."],
    ["ИТОГО", None, 100.0, 2.0, 80.0, 1.25],
    [datetime.date(2026, 1, 1), "факт", 50.0, 1.0, 40.0, 640000],
    [datetime.date(2026, 2, 1), None, 50.0, 1.0, 40.0, 660000],
]


def test_the_button_no_longer_names_a_project() -> None:
    page = cabinet.CABINET_HTML if hasattr(cabinet, "CABINET_HTML") else ""
    source = page or Path("market_search/cabinet.py").read_text(encoding="utf-8")
    assert "Загрузить отчёт о продажах" in source
    assert "Загрузить финмодель ПЛАТО" not in source


def test_the_binary_format_is_accepted_by_the_form() -> None:
    source = Path("market_search/cabinet.py").read_text(encoding="utf-8")
    assert ".xlsb" in source


def test_the_status_line_does_not_print_a_project_name() -> None:
    source = Path("market_search/cabinet.py").read_text(encoding="utf-8")
    assert "План загружен:" not in source
    assert "Отчёт загружен:" in source


def test_the_parser_no_longer_returns_a_project() -> None:
    """Кто загрузил, тот и знает, чей это отчёт."""
    got = plan.parse_plan(_book(ROWS))
    assert "project" not in got
    assert got["sheet"] == "План продаж_утв"


def test_the_plain_book_still_parses() -> None:
    got = plan.parse_plan(_book(ROWS))
    kinds = [month["kind"] for month in got["months"]]
    assert kinds == ["fact", "plan"]
    assert got["fact_until"] == "2026-01" and got["plan_from"] == "2026-02"


def test_the_format_is_read_from_the_content_not_the_name() -> None:
    """Имя файла человек меняет как угодно, а workbook.bin внутри — нет."""
    assert plan._is_xlsb(_book(ROWS)) is False
    fake = io.BytesIO()
    with zipfile.ZipFile(fake, "w") as archive:
        archive.writestr("xl/workbook.bin", b"\x00")
    assert plan._is_xlsb(fake.getvalue()) is True


def test_an_excel_serial_date_becomes_a_month() -> None:
    """В .xlsb дата лежит числом дней от 30.12.1899.

    Вернуть его как есть значит потерять весь ряд молча: строки не станут
    месяцами, и разбор скажет «плана нет» на книге, где план есть.
    """
    assert plan._month(45658.0) == "2025-01"
    assert plan._month(46600.0) == "2027-08"


def test_a_quantity_is_not_mistaken_for_a_date() -> None:
    """В первой колонке встречается и число штук — оно не 1954 год."""
    assert plan._month(220.0) is None
    assert plan._month(13428.9) is None


def test_the_missing_library_is_named_not_swallowed() -> None:
    fake = io.BytesIO()
    with zipfile.ZipFile(fake, "w") as archive:
        archive.writestr("xl/workbook.bin", b"\x00")
    try:
        import pyxlsb  # noqa: F401
    except ImportError:
        with pytest.raises(plan.PlanNotFound) as info:
            plan.parse_plan(fake.getvalue())
        assert "pyxlsb" in str(info.value)
    else:
        with pytest.raises(plan.PlanNotFound):
            plan.parse_plan(fake.getvalue())


def test_pyxlsb_is_declared_as_a_dependency() -> None:
    """Библиотеки нет в образе — и .xlsb на проде отвалится вежливо и зря."""
    assert "pyxlsb" in Path("requirements.txt").read_text(encoding="utf-8")


def test_the_monitor_does_not_ship_with_someone_elses_project() -> None:
    source = Path("developaid_monitor_page.py").read_text(encoding="utf-8")
    assert 'value="Кутузов Сити"' not in source


# --- второй шаблон отчёта ---------------------------------------------------

def _second_template() -> bytes:
    """Раскладка второго шаблона: шапка ниже, подписи словами, дата не слева.

    Ловушка здесь одна и тихая: рядом с продажами стоит «В РЕАЛИЗАЦИИ, кв.м» —
    ОСТАТОК. Взятый вместо продаж, он даёт тринадцать тысяч метров за месяц и
    выглядит правдоподобно.
    """
    openpyxl = pytest.importorskip("openpyxl")
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "План продаж УТВ"
    for _ in range(17):
        sheet.append([None])
    sheet.append([None, None, None, "ВСЕГО", "ВСЕГО (ФИНМОДЕЛЬ)"])
    sheet.append([None, "ПЕРИОД", None, "СТОИМОСТЬ КОНТРАКТОВ, РУБ",
                  "В РЕАЛИЗАЦИИ, кв.м", "ОБЪЕМ ПРОДАЖ,шт",
                  "ОБЪЕМ ПРОДАЖ КВАРТИР, КВ.М",
                  "ОБЪЕМ ПРОДАЖ НАРАСТАЮЩИМ ИТОГОМ, КВ.М",
                  "СРЕДНЯЯ СТОИМОСТЬ, РУБ./КВ.М"])
    sheet.append([None, "квартиры (м2)", None, None, None, 220, 13428.9, 13428.9, 918384])
    sheet.append([None])
    sheet.append([None, datetime.date(2025, 7, 1), "ФАКТ", None, 13428.9, 1, 33.3, 33.3, 644940])
    sheet.append([None, datetime.date(2025, 8, 1), "ФАКТ", None, 13395.6, 8, 414.2, 447.5, 588849])
    sheet.append([None, datetime.date(2026, 6, 1), None, None, 10791.3, 5, 308.5, 2946.1, 752508])
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def test_the_second_template_parses_too() -> None:
    got = plan.parse_plan(_second_template())
    assert got["sheet"] == "План продаж УТВ"
    assert [month["kind"] for month in got["months"]] == ["fact", "fact", "plan"]
    assert got["fact_until"] == "2025-08" and got["plan_from"] == "2026-06"


def test_sales_are_not_confused_with_the_remaining_inventory() -> None:
    """13 428 м² «продано за месяц» выглядит правдоподобно — и это остаток."""
    got = plan.parse_plan(_second_template())
    july = got["months"][0]
    assert july["area"] == 33.3
    assert july["units"] == 1


def test_the_cumulative_column_is_not_taken_for_the_month() -> None:
    got = plan.parse_plan(_second_template())
    august = got["months"][1]
    assert august["area"] == 414.2      # за месяц, а не 447,5 нарастающим


def test_the_date_column_is_found_by_its_label() -> None:
    """«Дата всегда слева» держалось на одной книге: во втором шаблоне она вторая."""
    got = plan.parse_plan(_second_template())
    assert [month["month"] for month in got["months"]][:2] == ["2025-07", "2025-08"]


def test_the_header_may_stand_below_the_twelfth_row() -> None:
    """Над таблицей второго шаблона — блок с составом очередей на семнадцать строк."""
    assert plan._HEADER_SEARCH_DEPTH >= 19
