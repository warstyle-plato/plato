"""Одобренный лимит ПФ ограничивает выборку, а нехватка выходит наружу.

До этого лимит участвовал только в комиссиях: плата за невыбранный лимит и
резервирование считались от него, а сама выборка была `pf_draw += project_costs`
без всякого потолка. Для покупки участка это допустимо — там лимит и
потребность выводятся из одних вводных и сойтись обязаны. На действующем
проекте это скрывает главное.

Гродненская: книга выбирает 8 413,2 млн ₽ при лимите 8 420,0 — 99,92%, свободно
6,8 млн ₽. Маржа 10,7%, LLCR 1,13, всё благополучно. При этом лимит посчитан с
дофинансом, которого банк не давал, и разрыв в такой модели равен нулю по
построению — его негде увидеть.

Поэтому: лимит задан — он потолок, а превышение становится «непокрытой
потребностью» с датой первого месяца нехватки. Лимит не задан — ничего не
меняется, и это проверяется отдельно: инвестиционный анализ ломать нельзя.
"""

from __future__ import annotations

import pytest

import main_legacy as engine


def _finance(**overrides):
    inputs = {**engine.DEFAULT_INPUTS, **overrides}
    bundle = engine._run_authoritative_model(inputs, {}, [], {})
    return bundle["consolidated"]["finance"]


@pytest.fixture(scope="module")
def free():
    """Расчёт без одобренного лимита — поведение, которое было всегда."""
    return _finance()


def test_without_an_approved_limit_nothing_changes(free):
    """Пустое поле — не «лимит ноль», а «лимит выводится из потребности»."""
    assert free["pf_limit_approved"] == 0.0
    assert free["pf_limit"] == free["pf_limit_required"]
    assert free["pf_shortfall"] == 0.0
    assert free["pf_shortfall_month"] == ""
    # Выборка упирается в выведенный лимит только потому, что он из неё и
    # выведен, а не потому, что её обрезали.
    assert free["peak_pf"] <= free["pf_limit"]


def test_an_approved_limit_caps_the_drawdown(free):
    """Пик долга не может превысить одобренный лимит ни на рубль."""
    approved_mln = round(free["pf_limit_required"] * 0.8 / 1e6)
    capped = _finance(pf_limit_approved_mln=approved_mln)

    assert capped["pf_limit_approved"] == pytest.approx(approved_mln * 1e6)
    assert capped["pf_limit"] == pytest.approx(approved_mln * 1e6)
    assert capped["peak_pf"] <= approved_mln * 1e6 + 1.0
    assert capped["peak_pf"] < free["peak_pf"]


def test_the_gap_is_reported_with_the_month_it_opens(free):
    """Нехватка — величина и дата, иначе с ней нечего делать."""
    approved_mln = round(free["pf_limit_required"] * 0.8 / 1e6)
    capped = _finance(pf_limit_approved_mln=approved_mln)

    assert capped["pf_shortfall"] > 0
    assert capped["pf_shortfall_month"]
    # Месяц приходит строкой: результат уезжает в JSON, и `date` там ломает
    # сериализацию на отчёте, а не на расчёте.
    assert isinstance(capped["pf_shortfall_month"], str)
    assert len(capped["pf_shortfall_month"]) == 10


def test_the_required_limit_is_measured_without_the_ceiling(free):
    """Сколько проект просит — считается свободно, иначе потолок сам себя оправдает.

    Если бы потребность мерилась обрезанным прогоном, она всегда равнялась бы
    одобренному лимиту, и «сколько не хватает» вышло бы нулём при любой дыре.
    """
    approved_mln = round(free["pf_limit_required"] * 0.8 / 1e6)
    capped = _finance(pf_limit_approved_mln=approved_mln)

    assert capped["pf_limit_required"] == pytest.approx(free["pf_limit_required"])
    assert capped["pf_limit_required"] > capped["pf_limit_approved"]


def test_a_limit_above_the_need_leaves_no_gap(free):
    """Одобрено больше, чем нужно, — дефицита нет, а лимит остаётся одобренным.

    Комиссия за невыбранный лимит при этом растёт: она берётся с того лимита,
    по которому живёт проект, а не с того, который ему был бы достаточен.
    """
    generous_mln = round(free["pf_limit_required"] * 1.5 / 1e6)
    roomy = _finance(pf_limit_approved_mln=generous_mln)

    assert roomy["pf_shortfall"] == 0.0
    assert roomy["pf_shortfall_month"] == ""
    assert roomy["pf_limit"] == pytest.approx(generous_mln * 1e6)
    assert roomy["pf_limit_fee"] > free["pf_limit_fee"]


def test_capitalized_interest_does_not_eat_the_limit(free):
    """Проценты копятся вне лимита — потолок держит только тело долга.

    Решение владельца 04.08.2026. Если бы потолок считался от «тело плюс
    начисленные», модель находила бы дефицит там, где банк его не видит.
    """
    approved_mln = round(free["pf_limit_required"] * 0.8 / 1e6)
    capped = _finance(pf_limit_approved_mln=approved_mln)

    assert capped["ending_interest_payable"] >= 0.0
    assert capped["peak_pf"] <= approved_mln * 1e6 + 1.0
    # Начисленные проценты существуют и в обрезанном расчёте — их просто не
    # пускают в лимит.
    assert capped["pf_interest"] > 0
