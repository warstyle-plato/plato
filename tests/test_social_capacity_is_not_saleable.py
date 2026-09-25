"""Места школы и ДОО — мощность соцобъекта, а не продаваемые единицы.

Регрессия: в отчёте 350 мест ДОО и 1 000 мест СОШ попадали в колонку
«Продаётся, шт.» как 350 и 1 000. Эти числа нужны модели как мощность
социальной инфраструктуры, но товара из них не возникает.

Запуск: python3 -m pytest tests/test_social_capacity_is_not_saleable.py -q
"""

from __future__ import annotations

import copy
import io

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


def test_the_web_report_marks_capacity_and_does_not_print_it_as_sales() -> None:
    page = core.PAGE
    assert "capacityUnits=x=>['kindergarten','school','clinic'].includes(x.key)" in page
    assert "soldCell=x=>capacityUnits(x)?dash:num(soldUnits(x))" in page
    assert "мощность, мест" in page


def test_the_workbook_does_not_turn_capacity_into_sales() -> None:
    """Проверяем саму книгу, а не конкретную запись условия в исходнике."""
    openpyxl = pytest.importorskip("openpyxl")
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
    content, _, _ = core.build_project_workbook(
        inputs, copy.deepcopy(core.TEP_DEFAULT), [], {},
        project_name="Социальная мощность")
    sheet = openpyxl.load_workbook(io.BytesIO(content), data_only=False)["ТЭП"]
    # На листе ниже ТЭП есть другие строки с теми же подписями («ДОО»,
    # «СОШ»). Берём именно первую таблицу ТЭП до её ИТОГО, иначе словарь
    # перезапишет индекс поздней служебной строкой и проверит не ту ячейку.
    rows = {}
    for row in range(5, sheet.max_row + 1):
        label = str(sheet.cell(row=row, column=1).value or "")
        if label == "ИТОГО":
            break
        if label in {"ДОО", "СОШ"}:
            rows.setdefault(label, row)
    assert set(rows) == {"ДОО", "СОШ"}
    assert sheet.cell(row=rows["ДОО"], column=9).value == 0
    assert sheet.cell(row=rows["СОШ"], column=9).value == 0
