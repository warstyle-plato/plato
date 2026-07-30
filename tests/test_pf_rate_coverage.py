"""Ставка ПФ при покрытии эскроу.

Методика простая: базовая ставка (ключ + спред ПФ) начисляется на часть долга,
не покрытую эскроу, покрытая часть считается по специальной ставке. Средняя
ставка по кредиту — их взвешенная сумма.

В движке сверх этого жили две ветки: при покрытии от 1× до 2× специальная
ставка ещё и снижалась на «доход от передачи», а выше 2× ставка падала до
0,01% годовых. Ни того, ни другого банк не даёт: покрывать больше 100% долга
нечего. На реальной сделке с покрытием 2,38× движок считал долг почти
бесплатным, и проценты расходились с отчётом — 781 против 1 110 млн ₽.

Здесь закреплена сама формула и её поведение за 1×.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core


def finance(**overrides):
    inputs = dict(core.DEFAULT_INPUTS)
    inputs.update(overrides)
    result = core.calculate(core.CalcRequest(inputs=inputs, tep=core.TEP_DEFAULT, rates=[]))
    return inputs, result


def months_under_debt(result):
    return [row for row in result["finance"]["rows"] if row["pf_balance"] > 0]


def test_the_rate_is_the_weighted_sum_of_the_base_and_special_rates():
    """Проверка помесячно: ставка ровно посередине между базовой и специальной."""
    inputs, result = finance()
    special = inputs["pf_special_pct"] / 100
    spread = inputs["pf_spread_pp"] / 100

    for row in months_under_debt(result):
        base = row["key_rate"] + spread
        weight = min(row["coverage"], 1.0)
        assert row["pf_rate"] == pytest.approx(base * (1 - weight) + special * weight)


def test_without_escrow_the_debt_costs_the_base_rate():
    inputs, result = finance(apartment_price_th=1)
    spread = inputs["pf_spread_pp"] / 100
    rows = [row for row in months_under_debt(result) if row["coverage"] == 0]

    assert rows, "нужен хотя бы один месяц долга без эскроу"
    for row in rows:
        assert row["pf_rate"] == pytest.approx(row["key_rate"] + spread)


def test_coverage_above_one_does_not_go_below_the_special_rate():
    """Та самая ошибка: при покрытии 2,38× долг выходил почти бесплатным."""
    inputs, result = finance(apartment_price_th=1000)
    special = inputs["pf_special_pct"] / 100
    rows = [row for row in months_under_debt(result) if row["coverage"] > 1]

    assert max(row["coverage"] for row in rows) > 2, "сценарий должен доходить до 2×"
    for row in rows:
        assert row["pf_rate"] == pytest.approx(special)


def test_the_rate_never_falls_below_the_special_one():
    for price in (350, 600, 1000, 1600, 2500):
        inputs, result = finance(apartment_price_th=price)
        special = inputs["pf_special_pct"] / 100
        rates = [row["pf_rate"] for row in months_under_debt(result)]

        assert min(rates) >= special - 1e-12, f"цена {price}: ставка ушла ниже специальной"


def test_a_richer_project_pays_at_least_the_special_rate_on_average():
    """Средняя ставка не может быть ниже специальной — раньше выходило 0,74%."""
    inputs, result = finance(apartment_price_th=1000)

    assert result["report"]["financing"]["avg_pf_rate"] >= inputs["pf_special_pct"] / 100


def test_the_transfer_income_knob_is_gone():
    """Параметр «Снижение ставки ПФ при покрытии эскроу > 1×» больше не нужен."""
    keys = {field[0] for _, fields in core.FIELD_GROUPS for field in fields}

    assert "pf_transfer_income_pct" not in keys
    assert "pf_transfer_income_pct" not in core.DEFAULT_INPUTS
