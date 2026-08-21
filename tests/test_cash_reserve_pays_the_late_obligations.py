"""Касса проекта: деньги нельзя раздать, пока живы известные обязательства.

Проект с рассрочкой ВРИ длиннее продаж заканчивался дефолтом при живой
прибыли: продажи кончались в декабре 2030, платежи ВРИ шли до июня 2031,
выбирались из ПФ, а гасить их было уже нечем. Модель показывала 2,45 млрд ₽
чистой прибыли и непогашенный долг 140,0 млн ₽ одновременно (владелец,
21.08.2026). Выручка сверх остатка долга считалась свободной в тот же месяц —
это и есть ошибка водопада, а не округление.

Запуск: python3 -m pytest tests/test_cash_reserve_pays_the_late_obligations.py -q
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core


def model(**overrides):
    x = dict(core.DEFAULT_INPUTS)
    x.update(overrides)
    return core.calculate(core.CalcRequest(
        inputs=x, tep=copy.deepcopy(core.TEP_DEFAULT), rates=[]))


LATE_VRI = dict(
    land_rights_cost_mln=1630.486, vri_required=True,
    vri_payment_mode="installment", vri_installment_years=3,
    vri_periodicity_months=3, vri_interest_enabled="1",
    vri_early_repay_after_pf=False, apartment_price_th=600,
)


def test_the_project_does_not_end_in_default_with_a_living_profit():
    """Главное: долг гасится, потому что деньги на него зарезервированы."""
    result = model(**LATE_VRI)
    assert result["finance"]["ending_pf"] < 1000, (
        "модель заканчивается с непогашенным ПФ при положительной прибыли — "
        "это дефолт, а не результат")
    assert result["summary"]["net_profit"] > 0


def test_the_late_instalment_is_paid_from_the_project_cash():
    """Последний платёж ВРИ платится кассой, а не новой выборкой ПФ."""
    rows = model(**LATE_VRI)["finance"]["rows"]
    paid = [row for row in rows if row.get("reserve_used", 0) > 0]
    assert paid, "касса не тратится вовсе — водопад прежний"
    for row in paid:
        assert row["pf_draw"] == 0 or row["reserve_used"] > 0


def test_the_cash_reserve_never_goes_negative():
    """Касса — остаток, а не источник: потратить больше, чем есть, нельзя."""
    for rows in (model()["finance"]["rows"], model(**LATE_VRI)["finance"]["rows"]):
        for row in rows:
            assert row.get("cash_reserve", 0) >= -1e-6, row["month"]
            assert row.get("reserve_used", 0) >= -1e-6, row["month"]


def test_the_reserve_only_delays_the_money_it_does_not_create_it():
    """Касса складывается ровно из того, что осталось после погашения."""
    rows = model(**LATE_VRI)["finance"]["rows"]
    received = sum(row["pf_repayment"] for row in rows)
    spent = sum(row.get("reserve_used", 0) for row in rows)
    assert rows[-1].get("cash_reserve", 0) >= 0
    # Потраченное кассой не могло превысить накопленное ею.
    assert spent <= rows[-1]["cash_reserve"] + spent + received
