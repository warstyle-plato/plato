"""Плата за смену ВРИ из ГлавАПУ включает расчёт ВРИ.

Импорт переносил сумму из строки 44 калькулятора в `land_rights_cost_mln`, но
не трогал флаг «Требуется изменение ВРИ». Если он выключен, движок относит
сумму в расходы, а график платежей не строит: платить нечего и незачем. Дальше
это выходит наружу в выгрузке — в книге остаются её собственные формулы,
первый платёж в дату РнС и рассрочка на 72 месяца, — и объём долга расходится
с расчётом.

Для офисов такой признак уже был: пришли площади — `offices_enabled: True`.
Для ВРИ его не было.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core


def imported(vri_mln):
    """Книга калькулятора с одной значащей строкой — платой за смену ВРИ."""
    rows = [
        ["№", "Наименования", "Единицы измерения", "Показатель"],
        ["44", "Многоквартирная жилые здания", "млн.руб.", vri_mln],
    ]
    data = core._build_glavapu_xlsx_from_rows(rows, [])
    return core.parse_glavapu_xlsx(data, "ГлавАПУ.xlsx")["mappings"]


def test_a_vri_charge_switches_the_calculation_on():
    result = imported(1276.304)
    inputs = result["inputs"]

    assert inputs.get("land_rights_cost_mln") == pytest.approx(1276.304)
    assert inputs.get("vri_required") is True, "сумма пришла, а расчёт ВРИ остался выключенным"


def test_without_a_charge_the_flag_is_left_alone():
    """Нулевая плата — не повод включать расчёт за пользователя."""
    inputs = imported(0)["inputs"]

    assert "vri_required" not in inputs


def test_the_switched_on_calculation_produces_a_payment_schedule():
    """Ради этого флаг и нужен: без графика платить нечего и книга считает своё."""
    inputs = dict(core.DEFAULT_INPUTS)
    inputs.update(imported(1276.304)["inputs"])
    inputs.update(project_start="2027-01-01", ird_months=18)
    permit = core.add_months(core.d("2027-01-01"), 18)
    _relief, net = core.vri_relief(inputs, inputs["land_rights_cost_mln"] * 1_000_000)
    schedule = core.build_vri_schedule(inputs, net, permit)

    assert schedule["enabled"] is True
    assert schedule["rows"], "график платежей пуст"


def social_import(compensation_mln, kindergarten_places):
    rows = [
        ["№", "Наименования", "Единицы измерения", "Показатель"],
        ["18", "ДОУ мест", "мест", kindergarten_places],
        ["54", "Компенсация ДОУ", "млн.руб.", compensation_mln],
    ]
    data = core._build_glavapu_xlsx_from_rows(rows, [])
    return core.parse_glavapu_xlsx(data, "ГлавАПУ.xlsx")["normalized"]


def test_moscow_always_suggests_the_compensation_mode():
    """ГлавАПУ — московский калькулятор, а в Москве социалка исполняется
    только денежной компенсацией. Места ДОУ/СОШ из документа — параметры
    расчёта компенсации, а не обязательство строить: раньше «есть места →
    Строительство», и на 77:09:0004014:13 режим переключали руками."""
    assert social_import(580.668, 19)["suggested_social_mode"] == "Денежная компенсация"
    assert social_import(0, 19)["suggested_social_mode"] == "Денежная компенсация"
    assert social_import(0, 0)["suggested_social_mode"] == "Денежная компенсация"
