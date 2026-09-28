"""Места школы и ДОО — мощность соцобъекта, а не продаваемые единицы.

Регрессия: в отчёте 350 мест ДОО и 1 000 мест СОШ попадали в колонку
«Продаётся, шт.» как 350 и 1 000. Эти числа нужны модели как мощность
социальной инфраструктуры, но товара из них не возникает.

Запуск: python3 -m pytest tests/test_social_capacity_is_not_saleable.py -q
"""

from __future__ import annotations

import copy
import io
import re

import pytest

import main_legacy as core


def _report() -> dict:
    inputs = copy.deepcopy(core.DEFAULT_INPUTS)
    inputs.update(
        social_mode="Строительство",
        social_area_source="manual",
        kindergarten_places=350,
        school_places=1000,
        clinic_capacity=0,
        social_dou_gba_sqm=5670.3,
        social_school_gba_sqm=19998.2,
    )
    tep = copy.deepcopy(core.TEP_DEFAULT)
    return core.calculate(core.CalcRequest(inputs=inputs, tep=tep, rates=[]))


def test_social_capacity_stays_visible_but_is_not_saleable() -> None:
    result = _report()
    rows = {row["key"]: row for row in result["tep"]["rows"]}

    assert rows["kindergarten"]["units"] == pytest.approx(350)
    assert rows["school"]["units"] == pytest.approx(1000)
    assert rows["kindergarten"]["saleable_units"] == 0
    assert rows["school"]["saleable_units"] == 0


def test_social_capacity_does_not_enter_saleable_units_total() -> None:
    result = _report()
    rows = result["tep"]["rows"]
    expected = sum(row["saleable_units"] for row in rows
                   if row["key"] not in core.SOCIAL_TEP_FIELDS)
    assert result["tep"]["total"]["saleable_units"] == pytest.approx(expected)


def _social_inputs() -> dict:
    inputs = copy.deepcopy(core.DEFAULT_INPUTS)
    inputs.update(
        social_mode="Строительство",
        social_area_source="manual",
        kindergarten_places=350,
        school_places=1000,
        clinic_capacity=0,
        social_dou_gba_sqm=5670.3,
        social_school_gba_sqm=19998.2,
    )
    return inputs


def test_the_model_v2_workbook_does_not_turn_capacity_into_sales() -> None:
    """Проверяем саму книгу, а не конкретную запись условия в исходнике.

    Колонка «Продаётся, ед.» есть только в книге `build_plato_model_v2`
    (лист «ТЭП», шапка в 4-й строке): там формула `=G-H` превращала места
    школы в продажи. Книга v4 (`build_project_workbook`) такой колонки не
    имеет — её проверяет следующий тест.
    """
    openpyxl = pytest.importorskip("openpyxl")
    content, _meta = core.build_plato_model_v2(
        _social_inputs(), copy.deepcopy(core.TEP_DEFAULT), [],
        project_name="Социальная мощность")
    sheet = openpyxl.load_workbook(io.BytesIO(content), data_only=False)["ТЭП"]
    headers = [sheet.cell(row=4, column=c).value for c in range(1, 10)]
    sold_column = headers.index("Продаётся, ед.") + 1
    units_column = headers.index("Единиц") + 1
    rows = {}
    for row in range(5, sheet.max_row + 1):
        label = str(sheet.cell(row=row, column=1).value or "")
        if label == "ИТОГО":
            break
        if label in {"ДОО", "СОШ"}:
            rows.setdefault(label, row)
    assert set(rows) == {"ДОО", "СОШ"}
    # Мощность видна, но в продаже её нет — ни числом, ни формулой от мест.
    assert sheet.cell(row=rows["ДОО"], column=units_column).value == pytest.approx(350)
    assert sheet.cell(row=rows["СОШ"], column=units_column).value == pytest.approx(1000)
    assert sheet.cell(row=rows["ДОО"], column=sold_column).value == 0
    assert sheet.cell(row=rows["СОШ"], column=sold_column).value == 0


def test_the_v4_workbook_keeps_capacity_out_of_sales() -> None:
    """В книге v4 места соцобъектов живут в «Параметры модели»!B174:B185.

    Читать их вправе только стоимость соцобъекта (F174:F185) и таблица
    «СОЦИАЛЬНЫЕ ОБЪЕКТЫ · не продаются» на листе ТЭП. Любая другая формула,
    которая тянет эти места (продажи, единицы, выручка), — мощность стала
    товаром.
    """
    openpyxl = pytest.importorskip("openpyxl")
    content, _, _ = core.build_project_workbook(
        _social_inputs(), copy.deepcopy(core.TEP_DEFAULT), [], {},
        project_name="Социальная мощность")
    book = openpyxl.load_workbook(io.BytesIO(content), data_only=False)
    params = "Параметры модели"
    capacity_ref = re.compile(r"\$?B\$?(17[4-9]|18[0-5])(?!\d)")
    # Ссылка на ЧУЖОЙ лист (`'Вводные'!B174`) — не места соцобъектов, даже
    # если номер строки совпал: строки «Вводных» сдвигаются с каждым новым
    # полем. Места живут только на «Параметрах модели», поэтому перед
    # поиском вычёркиваются ссылки, адресованные любому другому листу.
    foreign_ref = re.compile(r"(?:'[^']+'|[^\W\d][\w.]*)!\$?[A-Z]{1,3}\$?\d+")

    def own_refs(formula: str) -> str:
        return foreign_ref.sub(
            lambda m: m.group(0) if m.group(0).split("!")[0].strip("'") == params else "",
            formula)
    tep = book["ТЭП"]
    social_rows = {}
    for row in range(1, tep.max_row + 1):
        label = tep.cell(row=row, column=1).value
        if label in {"ДОО", "СОШ", "Поликлиника"}:
            social_rows.setdefault(label, row)
    assert set(social_rows) == {"ДОО", "СОШ", "Поликлиника"}
    title_row = min(social_rows.values()) - 2
    assert "не продаются" in str(tep.cell(row=title_row, column=1).value)
    allowed = {(params, f"F{row}") for row in range(174, 186)}
    allowed |= {("ТЭП", f"{col}{row}") for row in social_rows.values()
                for col in "BCD"}
    leaks = []
    for sheet in book:
        for line in sheet.iter_rows():
            for cell in line:
                value = cell.value
                if not (isinstance(value, str) and value.startswith("=")):
                    continue
                same_sheet = sheet.title == params
                if not (same_sheet or params in value):
                    continue
                if capacity_ref.search(own_refs(value)) and (sheet.title, cell.coordinate) not in allowed:
                    leaks.append(f"{sheet.title}!{cell.coordinate}: {value[:120]}")
    assert not leaks, leaks
    # Итог единиц проекта складывает очереди и объекты, но не места.
    total_units = next(
        tep.cell(row=row, column=5).value for row in range(1, tep.max_row + 1)
        if str(tep.cell(row=row, column=1).value or "").startswith("ИТОГО ПРОЕКТ"))
    for row in social_rows.values():
        assert f"B{row}" not in str(total_units)
