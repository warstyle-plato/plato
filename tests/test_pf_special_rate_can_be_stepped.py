"""Специальная ставка ПФ бывает ступенчатой, и ступени надо задавать вводом.

В договорах она не одна. НКЛ Гродненской: 4,26% при покрытии 100–110%, 2,56%
при 110–120%, 0,86% при 120–125%, 0,01% выше — та же лесенка, что в BVX003
Сбера, но со своими цифрами. Формула книги видна дословно:

    IF(покрытие>=1 и <=1.1 → 4.26%; >1.1 и <=1.2 → 2.56%;
       >1.2 и <=1.25 → 0.86%; >1.25 → 0.01%;
       иначе (эскроу×спец + (ПФ−эскроу)×(ключ+спред))/ПФ)

Ниже покрытия 1,0 это ровно наша средневзвешенная ставка. Выше — ступени,
которых модель не знала: она держала одну ставку на всё покрытие и потому
завышала проценты сильным проектам.

Таблица индивидуальна для каждого НКЛ, поэтому «типовой» здесь нет: пустой ввод
оставляет прежнее поведение.

Проверки идут на вводных, где покрытие действительно уходит за единицу. На
умолчаниях оно упирается в 0,96×, и ветка со ступенями просто не исполняется —
на этом мы уже обжигались со ставкой ПФ.
"""

from __future__ import annotations

import copy

import pytest

import main_legacy as engine

# Ступени НКЛ Гродненской, снятые с формулы листа «КРЕДИТЫ».
_STEPS = [
    {"coverage": 1.1, "rate_pct": 4.26},
    {"coverage": 1.2, "rate_pct": 2.56},
    {"coverage": 1.25, "rate_pct": 0.86},
    {"coverage": 99.0, "rate_pct": 0.01},
]


def _strong_project():
    """Вводные, на которых эскроу перекрывает долг: иначе ступени не сработают."""
    inputs = dict(engine.DEFAULT_INPUTS)
    inputs.update(apartment_price_th=1050, commercial_price_th=1050,
                  share_before_rve_pct=95, main_above_th_per_sqm=60,
                  main_under_th_per_sqm=60, land_rights_cost_mln=0,
                  vri_required=False)
    return inputs


def _run(inputs):
    return engine.calculate(engine.CalcRequest(
        inputs=inputs, tep=copy.deepcopy(engine.TEP_DEFAULT), rates=[]))


@pytest.fixture(scope="module")
def strong():
    inputs = _strong_project()
    return _run(inputs), _run({**inputs, "pf_special_steps": _STEPS})


def test_the_threshold_is_actually_reached(strong):
    """Сначала убедиться, что покрытие за единицу уходит.

    Зелёный тест на недостижимой ветке ничего не проверяет: ставка ПФ ниже
    специальной уже пережила у нас 581 проверку именно так.
    """
    plain, _ = strong

    assert plain["finance"]["peak_coverage"] > 1.25


def test_steps_cut_the_rate_for_a_strong_project(strong):
    """Покрытие за 125% — ставка падает до последней ступени, а не держится."""
    plain, stepped = strong

    assert stepped["finance"]["pf_interest"] < plain["finance"]["pf_interest"]
    assert stepped["finance"]["avg_pf_effective_rate"] < \
        plain["finance"]["avg_pf_effective_rate"]
    assert stepped["summary"]["llcr"] > plain["summary"]["llcr"]


def test_no_steps_means_the_old_behaviour():
    """Пустой ввод — прежний расчёт до копейки, а не «ступени по умолчанию»."""
    inputs = _strong_project()
    plain = _run(inputs)
    empty = _run({**inputs, "pf_special_steps": []})

    assert empty["finance"]["pf_interest"] == pytest.approx(
        plain["finance"]["pf_interest"])


def test_below_full_coverage_the_steps_do_not_apply():
    """Ниже покрытия 1,0 работает средневзвешенная ставка, как в книге.

    Ступени начинаются со ста процентов; применить их раньше значило бы дать
    проекту скидку, которой в договоре нет.
    """
    weak = dict(engine.DEFAULT_INPUTS)
    plain = _run(weak)
    stepped = _run({**weak, "pf_special_steps": _STEPS})

    assert plain["finance"]["peak_coverage"] < 1.0
    assert stepped["finance"]["pf_interest"] == pytest.approx(
        plain["finance"]["pf_interest"])


@pytest.mark.parametrize("coverage, expected", [
    (1.00, 0.0426), (1.10, 0.0426),
    (1.15, 0.0256), (1.20, 0.0256),
    (1.22, 0.0086), (1.25, 0.0086),
    (1.30, 0.0001), (5.00, 0.0001),
])
def test_the_step_boundaries_follow_the_contract(coverage, expected):
    """Границы включающие: «>=1 и <=1.1» — это 1,1 внутри первой ступени."""
    steps = engine._pf_special_steps({"pf_special_steps": _STEPS})

    assert engine._pf_step_rate(steps, coverage) == pytest.approx(expected)


def test_steps_are_sorted_and_bad_rows_ignored():
    """Порядок в договоре и порядок ввода — разные вещи, мусор не считается."""
    steps = engine._pf_special_steps({"pf_special_steps": [
        {"coverage": 1.25, "rate_pct": 0.86},
        {"coverage": 1.1, "rate_pct": 4.26},
        {"coverage": "—", "rate_pct": 1.0},      # не число
        {"coverage": 0, "rate_pct": 9.0},        # неположительная граница
        "мусор",
    ]})

    assert steps == [(1.1, pytest.approx(0.0426)), (1.25, pytest.approx(0.0086))]
