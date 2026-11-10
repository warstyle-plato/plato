"""Расчёт договорной стоимости и ГПР договора читаются по линейкам таблицы.

Документы рисуются здесь же, с выдуманными номерами, суммами и работами:
репозиторий публичный, а договоры владельца — нет. Нарисовано то, на чём
ломался разбор живых документов: штамп электронной подписи поверх строки,
лишняя вертикальная линейка внутри графы, страница продолжения без верхней
рамки, повторённый номер позиции, шапка графика с объединёнными месяцами и
группа, чьи даты не совпадают с её работами. Каждая такая особенность
проверяется и обратным ходом: без неё (или без её обработки) разбор обязан
ошибиться, иначе зелёный тест ничего не доказывает.
"""
from __future__ import annotations

import pathlib
import re

import pytest

import developaid_contract_documents as documents
from tests.egrn_fixtures import FONTS

pymupdf = pytest.importorskip("pymupdf")

LANDSCAPE = (842, 595)
COLUMNS = (40, 80, 300, 340, 390, 450, 510, 570, 640, 710, 790)
STRAY = 200  # линейка внутри графы наименования: объединённая ячейка шапки
HEADER = ("№ п/п", "Наименование работ", "Ед. изм.", "Кол-во", "Цена мат.", "Цена раб.",
          "Цена всего", "Сумма мат.", "Сумма раб.", "Сумма всего")
NUMBERS = tuple(str(n) for n in range(1, 11))
TITLE = ("Приложение № 1.2 к Дополнительному соглашению № 4 от 01.02.2026",
         "к Договору подряда № 12-ТСТ от 01.09.2025",
         "Расчёт договорной стоимости на завершение работ",
         "в редакции Дополнительного соглашения № 4 от 01.02.2026")


def _empty(name):
    return ("", name) + ("",) * 8


FIRST_PAGE = [
    _empty("Раздел № 1. Земляные работы"),
    ("1", "Разработка грунта") + ("",) * 8,
    ("1.1", "Разработка грунта экскаватором", "м3", "100,00", "0,00", "500,00", "500,00",
     "0,00", "50 000,00", "50 000,00"),
    ("1.2", "Вывоз грунта", "т", "10,50", "100,00", "200,00", "300,00",
     "1 050,00", "2 100,00", "3 150,00"),
]
SECOND_PAGE = [
    ("1.3", "Обратная засыпка", "м3", "20,00", "50,00", "150,00", "200,00",
     "1 000,00", "3 000,00", "4 000,00"),
    ("", "Итого по Разделу № 1. Земляные работы", "", "", "", "", "",
     "2 050,00", "55 100,00", "57 150,00"),
    _empty("Раздел № 2. Бетонные работы"),
    ("2.1", "Бетонирование плиты", "м3", "5,00", "6 000,00", "4 000,00", "10 000,00",
     "30 000,00", "20 000,00", "50 000,00"),
    ("2.1", "Бетонирование стен", "м3", "2,00", "6 000,00", "4 000,00", "10 000,00",
     "12 000,00", "8 000,00", "20 000,00"),
    ("", "Итого по Разделу № 2. Бетонные работы", "", "", "", "", "",
     "42 000,00", "28 000,00", "70 000,00"),
    ("", "ВСЕГО с учетом НДС, руб.:", "", "", "", "", "",
     "44 050,00", "83 100,00", "127 150,00"),
    # Сноска под таблицей пересекает графы, как в живом расчёте.
    ("1. 2. Примечание: в стоимость входят все сопутствующие работы, доставка материалов, "
     "погрузка и разгрузка, уборка и вывоз строительного мусора",) + ("",) * 9,
]
# Штамп оператора ЭДО: синий текст поверх граф единицы, количества и цены строки 1.2.
STAMP = (("ДОКУМЕНТ ПОДПИСАН ЭЛЕКТРОННОЙ ПОДПИСЬЮ", 0), ("ОТПРАВЛЕНО ООО «Ромашка», 01.02.26", 8))
BLUE = (0, 0, 1)


def _font():
    font = next((path for path in FONTS if pathlib.Path(path).exists()), "")
    if not font:
        pytest.skip("в образе нет шрифта с кириллицей: " + ", ".join(FONTS))
    return font


def _page(document):
    page = document.new_page(width=LANDSCAPE[0], height=LANDSCAPE[1])
    page.insert_font(fontname="cyr", fontfile=_font())
    return page


def _text(page, x, y, text, color=(0, 0, 0)):
    page.insert_text((x, y), text, fontsize=7, fontname="cyr", color=color)


def _table(page, rows, top, *, columns=COLUMNS, height=18, top_border=True, stray=None):
    """Ruled table; returns the y of every row edge."""
    edges = [top + height * n for n in range(len(rows) + 1)]
    for index, y in enumerate(edges):
        if index or top_border:
            page.draw_line((columns[0], y), (columns[-1], y), width=0.5)
    for x in columns:
        page.draw_line((x, edges[0]), (x, edges[-1]), width=0.5)
    if stray:
        page.draw_line((stray, edges[0]), (stray, edges[2]), width=0.5)
    for row, cells in enumerate(rows):
        for column, text in enumerate(cells):
            if text:
                _text(page, columns[column] + 2, edges[row] + 12, text)
    return edges


def estimate_pdf(first=FIRST_PAGE, second=SECOND_PAGE, *, stamp=True, top_border=False, title=TITLE):
    document = pymupdf.open()
    page = _page(document)
    for n, line in enumerate(title):
        _text(page, 40, 40 + 12 * n, line)
    edges = _table(page, [HEADER, NUMBERS] + list(first), 100, stray=STRAY)
    if stamp:
        for text, shift in STAMP:
            _text(page, COLUMNS[2] + 4, edges[-2] + 9 + shift, text, color=BLUE)
    page = _page(document)
    _table(page, second, 60, top_border=top_border)
    return document.tobytes()


def test_estimate_positions_sections_and_edition_are_read_across_pages():
    result = documents.read(estimate_pdf())
    assert result["contract"] == {"number": "12-ТСТ", "date": "2025-09-01"}
    assert result["agreement"] == {"number": "4", "date": "2026-02-01"}
    (estimate,) = result["estimates"]
    assert (estimate["annex"], estimate["scope"], estimate["pages"]) == ("1.2", "remaining", [1, 2])
    assert estimate["edition"] == {"number": "4", "date": "2026-02-01"}
    assert [p["number"] for p in estimate["positions"]] == ["1.1", "1.2", "1.3", "2.1", "2.1"]
    removal = estimate["positions"][1]
    assert (removal["name"], removal["unit"], removal["quantity"]) == ("Вывоз грунта", "т", 10.5)
    assert removal["unit_price"] == {"material": 100.0, "work": 200.0, "total": 300.0}
    assert removal["amount"] == {"material": 1050.0, "work": 2100.0, "total": 3150.0}
    assert removal["section"] == "Раздел № 1. Земляные работы"
    assert removal["group"] == {"number": "1", "name": "Разработка грунта"}
    assert estimate["positions"][2]["section"] == "Раздел № 1. Земляные работы"
    assert estimate["positions"][3]["section"] == "Раздел № 2. Бетонные работы"
    assert [t["amount"] for t in estimate["totals"]] == [57150.0, 70000.0, 127150.0]
    # Повтор номера — свойство источника: о нём сказано, позиции не слиты.
    (warning,) = estimate["warnings"]
    assert "2.1" in warning and "2 раза" in warning and "название и единица" in warning
    assert result["warnings"] == [] and result["schedule"] is None


def test_the_stamp_over_a_row_is_cut_and_without_the_cut_the_row_breaks(monkeypatch):
    clean = documents.read(estimate_pdf(stamp=False))["estimates"][0]
    stamped = documents.read(estimate_pdf())["estimates"][0]
    assert stamped["positions"] == clean["positions"]
    monkeypatch.setattr(documents, "_STAMP", re.compile(r"(?!)"))
    broken = documents.read(estimate_pdf())["estimates"][0]
    assert "1.2" not in [p["number"] for p in broken["positions"]]
    assert any("Вывоз грунта" in w and "не распознана" in w for w in broken["warnings"])


def test_a_marker_word_in_body_text_does_not_erase_the_page():
    # Два разных маркера штампа, но шрифтом и цветом самой таблицы.
    first = list(FIRST_PAGE) + [_empty("Сертификат на грунт ОТПРАВЛЕНО заказчику")]
    estimate = documents.read(estimate_pdf(first, stamp=False))["estimates"][0]
    assert [p["number"] for p in estimate["positions"]] == ["1.1", "1.2", "1.3", "2.1", "2.1"]
    assert estimate["positions"][2]["group"] == {"number": "", "name": first[-1][1]}


def test_one_marker_word_in_its_own_colour_is_not_a_stamp(monkeypatch):
    """Цветной заголовок «Сертификаты …» — один маркер, а у штампа их несколько."""
    heading, colour = "Сертификаты на материалы", (0.6, 0, 0)
    text = _text

    def coloured(page, x, y, value, color=(0, 0, 0)):
        text(page, x, y, value, colour if value == heading else color)
    monkeypatch.setitem(globals(), "_text", coloured)
    first = list(FIRST_PAGE) + [_empty(heading)]
    estimate = documents.read(estimate_pdf(first, stamp=False))["estimates"][0]
    assert estimate["positions"][2]["group"] == {"number": "", "name": heading}


def test_a_continuation_page_without_top_border_keeps_its_first_row():
    page = pymupdf.open(stream=estimate_pdf(), filetype="pdf")[1]
    across, _ = documents._rules(page)
    first_row = next(w for w in documents._words(page) if w[4] == "1.3")
    assert min(y for y, *_ in across) > first_row[1], "в образце у продолжения есть верхняя рамка"
    with_border = documents.read(estimate_pdf(top_border=True))["estimates"][0]
    without = documents.read(estimate_pdf())["estimates"][0]
    assert without["positions"] == with_border["positions"]
    assert "1.3" in [p["number"] for p in without["positions"]]


def test_section_total_mismatch_names_the_section_and_both_sums():
    second = [row if row[0] != "1.3" else row[:9] + ("5 000,00",) for row in SECOND_PAGE]
    warnings = documents.read(estimate_pdf(second=second))["estimates"][0]["warnings"]
    assert any("Итого по Разделу № 1" in w and "58 150.00" in w and "57 150.00" in w for w in warnings)
    assert any(w.startswith("ВСЕГО") and "128 150.00" in w for w in warnings)
    assert any("Позиция 1.3: количество × цена = 4 000.00" in w for w in warnings)


def test_a_row_without_unit_is_named_with_its_page_not_dropped_silently():
    second = [row if row[0] != "1.3" else row[:2] + ("",) + row[3:] for row in SECOND_PAGE]
    warnings = documents.read(estimate_pdf(second=second))["estimates"][0]["warnings"]
    assert any(w.startswith("Стр. 2: строка «1.3 Обратная засыпка") for w in warnings)
    assert any("Итого по Разделу № 1" in w for w in warnings)


def test_contract_text_naming_the_annex_is_not_a_broken_table():
    document = pymupdf.open()
    page = _page(document)
    _text(page, 40, 60, "Договор подряда № 12-ТСТ от 01.09.2025")
    _text(page, 40, 80, "Приложение № 1. Расчёт договорной стоимости — неотъемлемая часть договора.")
    result = documents.read(document.tobytes())
    assert result["estimates"] == [] and result["schedule"] is None
    assert result["warnings"] == ["Расчёт договорной стоимости упомянут, но его таблица не найдена."]


def test_a_scan_and_a_non_pdf_are_refused_with_the_reason():
    document = pymupdf.open()
    page = document.new_page()
    page.draw_rect(pymupdf.Rect(40, 40, 400, 400), color=(0, 0, 0), fill=(0.5, 0.5, 0.5))
    with pytest.raises(ValueError, match="скан"):
        documents.read(document.tobytes())
    with pytest.raises(ValueError, match="PDF"):
        documents.read(b"not a pdf")


# --- ГПР ---------------------------------------------------------------------

DAY = 25
SCHEDULE_COLUMNS = (30, 60, 200, 260, 320) + tuple(320 + DAY * n for n in range(1, 9))
MONTHS = (("Январь 2026", (29, 30, 31)), ("Февраль 2026", (1, 2, 3, 4, 5)))
YELLOW, BLUE_BAR = (1, 0.9, 0.6), (0, 0.69, 0.94)
# код, название, начало, окончание, полоса (первый и последний столбец дня)
LINES = (
    ("1", "Подготовка", "", "", None),
    ("1.1", "Разметка", "29.01.2026", "31.01.2026", (0, 2)),
    ("1.2", "Ограждение", "01.02.2026", "03.02.2026", (3, 5)),
    ("2", "Каркас", "01.02.2026", "02.02.2026", (3, 4)),
    ("2.1", "Колонны", "01.02.2026", "05.02.2026", (3, 7)),
    ("2.2", "Плиты", "", "", (5, 7)),
    ("2.3", "Стены", "02.02.2026", "03.02.2026", (0, 2)),
)


def schedule_pdf(months=MONTHS, lines=LINES):
    document = pymupdf.open()
    page = _page(document)
    _text(page, 30, 40, "График производства работ")
    columns, top, header, height = SCHEDULE_COLUMNS, 60, 40, 16
    edges = [top, top + header] + [top + header + height * n for n in range(1, len(lines) + 1)]
    for y in edges:
        page.draw_line((columns[0], y), (columns[-1], y), width=0.5)
    # Месяцы и числа — одна строка шапки: делящая их линейка не доходит до графы номера.
    page.draw_line((columns[4], top + 20), (columns[-1], top + 20), width=0.5)
    for x in columns:
        page.draw_line((x, top), (x, edges[-1]), width=0.5)
    for text, x in (("№", 0), ("Наименование работ", 1), ("Дата нач.", 2), ("Дата ок.", 3)):
        _text(page, columns[x] + 2, top + 12, text)
    day = 4
    for name, days in months:
        _text(page, columns[day] + 2, top + 12, name)
        for n in days:
            _text(page, columns[day] + 8, top + 34, str(n))
            day += 1
    for index, (code, name, start, finish, bar) in enumerate(lines):
        y0, y1 = edges[index + 1], edges[index + 2]
        page.draw_rect(pymupdf.Rect(columns[0], y0, columns[-1], y1), color=None, fill=YELLOW)
        if bar:
            page.draw_rect(pymupdf.Rect(columns[4 + bar[0]] + 1, y0 + 3, columns[5 + bar[1]] - 1, y1 - 3),
                           color=None, fill=BLUE_BAR)
        for column, text in enumerate((code, name, start, finish)):
            if text:
                _text(page, columns[column] + 2, y0 + 11, text)
    return document.tobytes()


def test_schedule_dates_come_from_cells_bars_and_works():
    schedule = documents.read(schedule_pdf())["schedule"]
    assert schedule["pages"] == [1]
    lines = {line["code"]: line for line in schedule["lines"]}
    assert list(lines) == ["1", "1.1", "1.2", "2", "2.1", "2.2", "2.3"]
    assert (lines["1"]["start"], lines["1"]["finish"], lines["1"]["dates_from"]) == \
        ("2026-01-29", "2026-02-03", "works")
    assert (lines["1.1"]["start"], lines["1.1"]["finish"], lines["1.1"]["dates_from"]) == \
        ("2026-01-29", "2026-01-31", "cells")
    assert lines["1.1"]["bar"] == {"start": "2026-01-29", "finish": "2026-01-31"}
    assert (lines["2.2"]["start"], lines["2.2"]["finish"], lines["2.2"]["dates_from"]) == \
        ("2026-02-03", "2026-02-05", "bar")
    assert (lines["2.1"]["level"], lines["2.1"]["parent"]) == (2, "2")
    assert schedule["warnings"] == []
    # Решение владельца: ошибка дат источника исправляется по полосе, а не только называется.
    assert (lines["2.3"]["start"], lines["2.3"]["finish"], lines["2.3"]["dates_from"]) == \
        ("2026-01-29", "2026-01-31", "bar")
    assert lines["2.3"]["cells"] == {"start": "2026-02-02", "finish": "2026-02-03"}
    # Группа берёт размах работ уже после исправления своих строк.
    assert (lines["2"]["start"], lines["2"]["finish"], lines["2"]["dates_from"]) == \
        ("2026-01-29", "2026-02-05", "works")
    assert [line["code"] for line in schedule["lines"] if line["corrected"]] == ["2", "2.3"]
    assert schedule["corrections"] == [
        {"code": "2.3", "name": "Стены", "page": 1, "basis": "bar",
         "cells": {"start": "2026-02-02", "finish": "2026-02-03"},
         "used": {"start": "2026-01-29", "finish": "2026-01-31"},
         "text": "Стр. 1: у строки 2.3 «Стены» в графах дат 02.02.2026 — 03.02.2026, а полоса на диаграмме "
                 "идёт 29.01.2026 — 31.01.2026. Взяты даты полосы: 29.01.2026 — 31.01.2026."},
        {"code": "2", "name": "Каркас", "page": 1, "basis": "works",
         "cells": {"start": "2026-02-01", "finish": "2026-02-02"},
         "used": {"start": "2026-01-29", "finish": "2026-02-05"},
         "text": "Строка 2 «Каркас»: в графике 01.02.2026 — 02.02.2026, а входящие в неё работы идут "
                 "29.01.2026 — 05.02.2026. Взяты сроки работ."},
    ]


def test_a_finish_before_start_takes_the_bar_and_without_a_bar_is_named():
    lines = LINES[:1] + (("1.1", "Разметка", "31.01.2026", "29.01.2026", (0, 2)),
                         ("1.2", "Ограждение", "03.02.2026", "01.02.2026", None))
    schedule = documents.read(schedule_pdf(lines=lines))["schedule"]
    marking, fence = schedule["lines"][1:]
    assert (marking["start"], marking["finish"], marking["corrected"]) == ("2026-01-29", "2026-01-31", True)
    assert schedule["corrections"][0]["text"] == (
        "Стр. 1: у строки 1.1 «Разметка» окончание 29.01.2026 раньше начала 31.01.2026. "
        "Взяты даты полосы: 29.01.2026 — 31.01.2026.")
    assert (fence["start"], fence["finish"], fence["corrected"]) == ("2026-02-03", "2026-02-01", False)
    assert schedule["warnings"] == ["Стр. 1: у строки 1.2 окончание 01.02.2026 раньше начала 03.02.2026, "
                                    "а полосы на диаграмме нет: исправить даты нечем."]


def test_a_bar_within_a_day_of_the_cells_is_not_a_correction():
    lines = (("1.1", "Разметка", "29.01.2026", "01.02.2026", (0, 2)),)
    schedule = documents.read(schedule_pdf(lines=lines))["schedule"]
    assert schedule["corrections"] == [] and schedule["lines"][0]["finish"] == "2026-02-01"


def test_months_that_do_not_match_the_day_numbers_leave_bars_unread():
    months = (("Январь 2026", MONTHS[0][1] + MONTHS[1][1]),)
    schedule = documents.read(schedule_pdf(months=months))["schedule"]
    assert any("Месяцы графика не совпали с числами дней" in w for w in schedule["warnings"])
    assert all(line["bar"] is None for line in schedule["lines"])
    assert any("у строки 2.2 «Плиты» нет дат" in w for w in schedule["warnings"])
