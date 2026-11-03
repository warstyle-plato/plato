"""«Из него на погашение ПФ» показывало ноль на любом проекте.

Величина заведена 25.08.2026 ради счёта, который не сходился: раскрытый эскроу
минус долг не давал остатка, потому что эскроу гасит СВОЙ ПФ, а излишек уходит
в кассу. Четвёртое число — сколько из раскрытого пошло на погашение — движок
считает и по очередям суммирует, а в `report.financing` его не клали ни в одной
из двух сборок. Экран читал отсутствующий ключ и печатал ноль.

Тест на эту величину был и оставался зелёным: он смотрел в исходник движка,
то есть проверял, что число ВЫДАЁТСЯ, а не что оно ДОХОДИТ. Проверка своей
формы ошибку в чужой не ловит.

Запуск: python3 -m pytest tests/test_the_escrow_repayment_reaches_the_screen.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))

import main as _wrapper  # noqa: E402

core = _wrapper.core


def _inputs() -> tuple[dict, dict]:
    inputs = dict(core.DEFAULT_INPUTS)
    inputs["purchase_price_mln"] = 700
    return inputs, {key: dict(row) for key, row in core.TEP_DEFAULT.items()}


def test_a_single_project_carries_it_to_the_report() -> None:
    inputs, tep = _inputs()
    result = core.calculate(core.CalcRequest(inputs=inputs, tep=tep, rates=[]))
    financing = result["report"]["financing"]
    assert "rve_pf_repayment" in financing, "ключа нет — экран напечатает ноль"
    assert float(financing["rve_pf_repayment"]) == pytest.approx(
        float(result["finance"]["rve_pf_repayment"]), rel=1e-9)
    assert float(financing["rve_pf_repayment"]) > 0, (
        "предохранитель: на этих вводных погашение обязано быть, иначе ноль "
        "в отчёте ничего не доказывает")


def test_the_three_numbers_now_subtract() -> None:
    """Ради этого величина и заведена: долг = погашено + остаток."""
    inputs, tep = _inputs()
    financing = core.calculate(core.CalcRequest(
        inputs=inputs, tep=tep, rates=[]))["report"]["financing"]
    assert float(financing["rve_pf_before_repayment"]) == pytest.approx(
        float(financing["rve_pf_repayment"]) + float(financing["rve_pf_shortfall"]),
        rel=1e-9)


def test_the_consolidated_report_carries_it_too() -> None:
    """Свод очередей — вторая сборка, и ключа не было в обеих."""
    inputs, tep = _inputs()
    bundle = core.calculate_phased(core.PhasedCalcRequest(
        inputs=inputs, tep=tep, rates=[],
        phasing={"enabled": True, "mode": "phased", "user_enabled": True,
                 "phase_count": 2, "phase_gap_months": 12,
                 "phases": [{"name": "О1"}, {"name": "О2"}],
                 "shared_cash": {}, "shared_allocation": {}, "social_objects": []}))
    consolidated = bundle["consolidated"]
    financing = (consolidated.get("report") or {}).get("financing") or {}
    assert float(financing.get("rve_pf_repayment") or 0.0) == pytest.approx(
        float(consolidated["finance"]["rve_pf_repayment"]), rel=1e-9)
    assert float(financing["rve_pf_repayment"]) > 0
    # И сумма по очередям — это сумма их собственных погашений.
    by_queue = sum(float(phase["result"]["finance"].get("rve_pf_repayment") or 0.0)
                   for phase in bundle["phases"])
    assert float(financing["rve_pf_repayment"]) == pytest.approx(by_queue, rel=1e-9)


def test_every_number_the_card_prints_exists_in_the_report() -> None:
    """Общее правило: экран не должен читать ключей, которых отчёт не кладёт.

    Ноль вместо числа и ноль как значение выглядят одинаково — на этом строка
    и прожила незамеченной.
    """
    inputs, tep = _inputs()
    financing = core.calculate(core.CalcRequest(
        inputs=inputs, tep=tep, rates=[]))["report"]["financing"]
    for key in ("rve_pf_before_repayment", "rve_escrow_release", "rve_pf_repayment",
                "rve_pf_shortfall", "ending_pf", "pf_limit", "pf_uncovered_peak",
                "calculated_bridge", "actual_bridge", "own_funds"):
        assert key in financing, key
