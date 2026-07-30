"""Прогноз ключевой ставки должен уезжать в шаблон.

Блок устроен не как остальные вводные: подпись лежит в колонке A, а значения
разбросаны по C–G. Карта ищет подписи в колонке B и до него не дотягивалась,
поэтому шаблон жил на своих ставках: цели 13/11/10% против наших 11/9/7% и
выбранный сценарий «Низкая» вместо базового. Проценты по кредитам расходились
с расчётом почти на треть — 785 млн ₽ против 1 110 млн ₽.

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


def sheet_for(**overrides):
    inputs = dict(core.DEFAULT_INPUTS)
    inputs.update(purchase_price_mln=700, **overrides)
    tep = {key: dict(value) for key, value in core.TEP_DEFAULT.items()}
    data, _ = core.fill_plato_template(inputs, tep, project_name="Проверка")
    workbook = openpyxl.load_workbook(io.BytesIO(data), data_only=False)
    sheet = workbook["Вводные"]
    row = next(r for r in range(1, sheet.max_row + 1)
               if core._plato_normalize(sheet.cell(r, 1).value) == "сценарий ставки")
    return sheet, row, inputs


def test_the_current_key_rate_and_horizon_reach_the_template():
    sheet, row, inputs = sheet_for()

    assert sheet.cell(row, 5).value == pytest.approx(inputs["rate_start_pct"] / 100)
    assert sheet.cell(row, 7).value == inputs["rate_normalization_months"]


def test_the_target_rates_replace_the_template_defaults():
    """В шаблоне лежали 13/11/10% — на два пункта выше наших."""
    sheet, row, inputs = sheet_for()

    assert sheet.cell(row + 1, 4).value == pytest.approx(inputs["rate_target_high_pct"] / 100)
    assert sheet.cell(row + 1, 5).value == pytest.approx(inputs["rate_target_base_pct"] / 100)
    assert sheet.cell(row + 1, 6).value == pytest.approx(inputs["rate_target_low_pct"] / 100)


@pytest.mark.parametrize("key,name", [("base", "Базовая"), ("high", "Высокая"), ("low", "Низкая")])
def test_the_chosen_scenario_reaches_the_template(key, name):
    """Шаблон стоял на «Низкой» независимо от выбранного в модели сценария."""
    sheet, row, _ = sheet_for(rate_scenario=key)

    assert sheet.cell(row, 3).value == name


def test_an_unknown_scenario_falls_back_to_the_base_one():
    sheet, row, _ = sheet_for(rate_scenario="выдумка")

    assert sheet.cell(row, 3).value == "Базовая"


def test_the_scenario_selector_formula_survives():
    """Колонку G выбирает INDEX по названию сценария — её трогать нельзя."""
    sheet, row, _ = sheet_for()

    assert str(sheet.cell(row + 1, 7).value or "").startswith("=INDEX")


def test_the_block_is_reported_as_filled():
    inputs = dict(core.DEFAULT_INPUTS)
    tep = {key: dict(value) for key, value in core.TEP_DEFAULT.items()}
    _, report = core.fill_plato_template(inputs, tep)
    labels = {str(item["label"]) for item in report["filled"]}

    assert "Текущая ключевая ставка" in labels
    assert "Целевая ставка · базовая" in labels
    assert report["missing"] == []
