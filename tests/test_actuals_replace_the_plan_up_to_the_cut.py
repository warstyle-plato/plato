"""Прошлое действующего проекта берётся фактом, будущее считается на остаток.

Движок разворачивает весь проект от даты старта. Гродненская идёт с 01.2024:
выбрано 3 689,6 млн ПФ, погашен БРИДЖ, продано 2 396,7 м² из 13 428,9. Считать
это заново — значит считать другой проект.

Наложение подменяет ряды до даты среза фактическими и перенормирует плановый
хвост на остаток. Проверки здесь — про то, на чём такая подмена ломается: итог
уезжает вдвое, детализация расходится с итогом, остаток растворяется.
"""

from __future__ import annotations

import copy
import datetime

import pytest

import developaid_actuals as actuals
import main_legacy as engine


def _plan():
    """Плановая операционная модель и её ряды — тем же путём, что и расчёт."""
    captured = {}
    original = engine.simulate_financing

    def spy(x, t, rates, op):
        captured.setdefault("op", op)
        return original(x, t, rates, op)

    engine.simulate_financing = spy
    try:
        engine.calculate(engine.CalcRequest(
            inputs=dict(engine.DEFAULT_INPUTS),
            tep=copy.deepcopy(engine.TEP_DEFAULT), rates=[]))
    finally:
        engine.simulate_financing = original
    return captured["op"]


@pytest.fixture(scope="module")
def plan():
    return _plan()


def test_the_total_survives_the_overlay(plan):
    """Итог не меняется от того, что часть его уже случилась.

    Подменить прошлое фактом и оставить будущее как было — значит посчитать
    проект дважды: разом и по факту, и по плану.
    """
    months = sorted(plan["capex"])
    cut = months[8]
    fact = {month: 120e6 for month in months[:8]}
    planned_total = sum(plan["capex"].values())

    result = actuals.overlay(plan, {"cut": cut, "capex": fact})
    blended = result["op"]["capex"]

    assert sum(blended.values()) == pytest.approx(planned_total)
    assert sum(v for m, v in blended.items() if m < cut) == pytest.approx(960e6)


def test_the_fact_replaces_the_plan_month_by_month(plan):
    """До среза стоит ровно факт, а не факт поверх плана."""
    months = sorted(plan["capex"])
    cut = months[8]
    fact = {months[0]: 500e6, months[3]: 700e6}

    blended = actuals.overlay(plan, {"cut": cut, "capex": fact})["op"]["capex"]

    assert blended[months[0]] == pytest.approx(500e6)
    assert blended[months[3]] == pytest.approx(700e6)
    # Месяц, которого нет в факте, до среза пуст: факт полон, а не дополняет.
    assert months[1] not in blended


def test_the_detail_by_article_still_adds_up(plan):
    """Сумма по статьям равна итогу, иначе обе цифры выглядят достоверно."""
    months = sorted(plan["capex"])
    cut = months[8]
    fact = {month: 120e6 for month in months[:8]}

    result = actuals.overlay(plan, {"cut": cut, "capex": fact})
    by_article = result["op"]["capex_by_article"]

    assert sum(sum(s.values()) for s in by_article.values()) == pytest.approx(
        sum(result["op"]["capex"].values()))
    assert any("долями плана" in note for note in result["report"]["notes"])


def test_a_remainder_with_nowhere_to_go_is_not_lost(plan):
    """Планового хвоста нет — остаток ложится на месяц среза и объявляется.

    Молча растворить его в перенормировке значит занизить расходы проекта
    ровно на ту сумму, которую никто не заметит.
    """
    months = sorted(plan["capex"])
    cut = months[-1] + datetime.timedelta(days=40)  # срез за горизонтом плана
    fact = {months[0]: 100e6}

    result = actuals.overlay(plan, {"cut": cut, "capex": fact})
    blended = result["op"]["capex"]

    assert sum(blended.values()) == pytest.approx(sum(plan["capex"].values()))
    assert any("остаток" in note for note in result["report"]["notes"])


def test_spending_more_than_planned_is_reported_as_an_overrun(plan):
    """Факт больше плана — хвост обнуляется, а перерасход называется вслух."""
    months = sorted(plan["capex"])
    cut = months[8]
    over = sum(plan["capex"].values()) * 2
    fact = {months[0]: over}

    result = actuals.overlay(plan, {"cut": cut, "capex": fact})

    assert sum(v for m, v in result["op"]["capex"].items() if m >= cut) == 0.0
    assert any("перерасход" in note for note in result["report"]["notes"])


def test_debt_capex_follows_the_new_capex(plan):
    """Долговой расход пересобирается из нового CAPEX, а не масштабируется свой.

    Иначе связь между ними разъедется на второй же правке, и долг посчитается
    от расхода, которого в модели уже нет.
    """
    months = sorted(plan["capex"])
    cut = months[8]
    fact = {month: 120e6 for month in months[:8]}

    result = actuals.overlay(plan, {"cut": cut, "capex": fact})["op"]
    equity = result.get("vri_equity") or {}

    for month, value in result["capex"].items():
        expected = max(0.0, value - float(equity.get(month, 0.0)))
        assert result["debt_capex"][month] == pytest.approx(expected)


def test_a_missing_series_stays_planned(plan):
    """Чего нет в факте — остаётся планом. Отсутствие ряда не значит «ноль»."""
    months = sorted(plan["capex"])
    cut = months[8]

    result = actuals.overlay(plan, {"cut": cut, "capex": {months[0]: 100e6}})["op"]

    assert result["operating"] == plan["operating"]
    assert result["revenue_product_schedules"] == plan["revenue_product_schedules"]


def test_a_cut_without_a_date_is_refused(plan):
    """Без даты среза наложение бессмысленно — молча делать нечего."""
    with pytest.raises(ValueError):
        actuals.overlay(plan, {"capex": {}})


def test_the_calculation_carries_the_actuals_report():
    """Расчёт с фактом доносит наружу, что именно подменено.

    Приближение, видное только в коде, неотличимо от точного расчёта.
    """
    plan = _plan()
    months = sorted(plan["capex"])
    cut = months[8]
    fact = {month.isoformat(): 120e6 for month in months[:8]}

    result = engine.calculate(engine.CalcRequest(
        inputs=dict(engine.DEFAULT_INPUTS),
        tep=copy.deepcopy(engine.TEP_DEFAULT), rates=[],
        actuals={"cut": cut.isoformat(), "capex": fact}))

    assert result["actuals"]["cut"] == cut.isoformat()
    assert result["actuals"]["series"]["capex"]["fact"] == pytest.approx(960e6)
    assert result["actuals"]["notes"]


def test_a_plain_calculation_is_untouched():
    """Без факта расчёт прежний, а отчёт о наложении пуст."""
    plain = engine.calculate(engine.CalcRequest(
        inputs=dict(engine.DEFAULT_INPUTS),
        tep=copy.deepcopy(engine.TEP_DEFAULT), rates=[]))

    assert plain["actuals"] == {}
    assert plain["summary"]["revenue"] > 0
