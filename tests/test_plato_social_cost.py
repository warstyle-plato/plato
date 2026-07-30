"""Себестоимость соцобъектов в шаблоне должна совпадать с расчётом.

Карта записи не содержала себестоимости, а сами ячейки — формулы, тянущие
значение с листа «Расчет ВРИ (ТЭП)», остатка прежней методики. Шаблон брал
0,0097 млн ₽ за место вместо 2,75: социальная нагрузка выходила 0,6 млн ₽
вместо 193,2 млн ₽, а прибыль и LLCR оказывались выше настоящих.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core
openpyxl = pytest.importorskip("openpyxl")


@pytest.fixture(scope="module")
def sheet():
    inputs = dict(core.DEFAULT_INPUTS)
    inputs.update(purchase_price_mln=700, kindergarten_places=19,
                  school_places=38, clinic_capacity=9)
    tep = {key: dict(value) for key, value in core.TEP_DEFAULT.items()}
    data, _ = core.fill_plato_template(inputs, tep, project_name="Проверка")
    return openpyxl.load_workbook(io.BytesIO(data))["Вводные"]


def value_of(sheet, block: str, label: str):
    for row in range(1, 140):
        if str(sheet.cell(row, 1).value or "").startswith(block) \
                and str(sheet.cell(row, 2).value or "").startswith(label):
            return sheet.cell(row, 4).value
    raise AssertionError(f"не найдена строка {block} · {label}")


def test_the_cost_per_place_matches_the_engine(sheet):
    assert value_of(sheet, "ДОУ", "Себестоимость") == core.DEFAULT_INPUTS["kindergarten_cost_mln_per_place"]
    assert value_of(sheet, "СОШ", "Себестоимость") == core.DEFAULT_INPUTS["school_cost_mln_per_place"]
    assert value_of(sheet, "Поликлиника", "Себестоимость") == core.DEFAULT_INPUTS["clinic_cost_mln_per_unit"]


def test_the_capacities_match_the_engine(sheet):
    assert value_of(sheet, "ДОУ", "Количество мест") == 19
    assert value_of(sheet, "СОШ", "Количество мест") == 38
    assert value_of(sheet, "Поликлиника", "Мощность") == 9


def test_the_social_total_matches_the_report(sheet):
    """19×2,75 + 38×3 + 9×3 = 193,25 млн ₽ — столько же в PDF-отчёте."""
    total = (19 * value_of(sheet, "ДОУ", "Себестоимость")
             + 38 * value_of(sheet, "СОШ", "Себестоимость")
             + 9 * value_of(sheet, "Поликлиника", "Себестоимость"))

    assert total == pytest.approx(193.25, abs=0.1)


def test_the_scenario_selector_is_left_alone(sheet):
    """Колонку G выбирает формула шаблона — перезаписывать её нельзя."""
    for row in range(1, 140):
        if str(sheet.cell(row, 2).value or "").startswith("Себестоимость одного места"):
            assert str(sheet.cell(row, 7).value or "").startswith("=")


def test_only_the_listed_fields_override_the_template():
    assert core._PLATO_OVERRIDE_TEMPLATE_FORMULA == frozenset({
        "kindergarten_cost_mln_per_place", "school_cost_mln_per_place",
        "clinic_cost_mln_per_unit", "clinic_capacity",
    })
