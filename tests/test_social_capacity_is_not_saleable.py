"""Места школы и ДОО — мощность соцобъекта, а не продаваемые единицы.

Регрессия: в отчёте 350 мест ДОО и 1 000 мест СОШ попадали в колонку
«Продаётся, шт.» как 350 и 1 000. Эти числа нужны модели как мощность
социальной инфраструктуры, но товара из них не возникает.

Запуск: python3 -m pytest tests/test_social_capacity_is_not_saleable.py -q
"""

from __future__ import annotations

import copy
import inspect

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
    source = inspect.getsource(core.build_project_workbook)
    assert 'item.get("key") in SOCIAL_TEP_FIELDS' in source
    assert 'sold_value = (0 if item.get("key") in SOCIAL_TEP_FIELDS' in source
