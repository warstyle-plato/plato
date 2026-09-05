"""Сводный график эскроу — сумма разных договоров, и он это говорит.

Владелец, 04.09.2026: «кажется, что 2 очередь стартует сразу с выборки и
эскроу не с 0, а с 10 млрд, а 3 с 30». Числа верны: свод складывает счета
эскроу и долги ВСЕХ очередей, и после раскрытия первой кривая продолжается с
остатка остальных. Неверно место — покрытие такой кривой не принадлежит ни
одному договору, а ступень ставки ПФ банк считает по очереди.

Запуск: python3 -m pytest tests/test_the_summed_escrow_names_itself.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402

PAGE = core.PAGE


def _function(name: str) -> str:
    start = PAGE.index(f"function {name}(")
    depth, index, seen = 0, PAGE.index("{", start), False
    while index < len(PAGE):
        if PAGE[index] == "{":
            depth, seen = depth + 1, True
        elif PAGE[index] == "}":
            depth -= 1
            if seen and depth == 0:
                return PAGE[start:index + 1]
        index += 1
    raise AssertionError(f"не нашёл конец функции {name}")


def _phased():
    inputs = dict(core.DEFAULT_INPUTS)
    inputs["apartment_price_th"] = 450.0
    tep = {key: dict(value) for key, value in core.TEP_DEFAULT.items()}
    return core._run_authoritative_model(inputs, tep, [], {"enabled": True, "phase_count": 4})


def test_the_summed_coverage_belongs_to_no_contract() -> None:
    """Мера, ради которой стоит оговорка: свод не равен ни одной очереди."""
    bundle = _phased()
    rows = bundle["consolidated"]["finance"]["rows"]
    phases = [p["result"]["finance"]["rows"] for p in bundle["phases"]]

    def f(row, key):
        return float(row.get(key, 0.0) or 0.0)

    disagreements = 0
    for row in rows:
        duty = f(row, "pf_balance") + f(row, "pf_payable")
        if duty < 1_000_000:
            continue
        summed = f(row, "escrow") / duty
        own = [f(q, "coverage") for rows_q in phases
               for q in rows_q if q["month"] == row["month"]]
        own = [value for value in own if value > 0]
        if own and all(abs(summed - value) > 0.05 for value in own):
            disagreements += 1
    assert disagreements > 12, (
        "свод совпал с очередями — на этих вводных оговорка ничего не защищает")


def test_the_consolidated_chart_says_it_is_a_sum() -> None:
    """Кривая без этой строки читается как покрытие проекта."""
    body = _function("renderFinanceChart")
    assert "Это СУММА очередей" in body
    assert "не совпадает ни с одним договором" in body
    assert "phaseBundle.mode==='phased'" in body, (
        "оговорка обязана появляться только у проекта с очередями")


def test_the_queue_lines_stand_under_the_summed_one() -> None:
    """Методика, до которой надо дойти на соседнюю вкладку, — методика, которой нет."""
    assert 'id="financeEscrowPhases"' in PAGE
    assert 'id="reportEscrowPhases"' in PAGE
    body = _function("renderPhaseEscrowCharts")
    for name in ("phaseEscrowCharts", "financeEscrowPhases", "reportEscrowPhases"):
        assert name in body, f"контейнер {name} не заполняется"
    assert "renderPhaseEscrowCharts();" in _function("renderFinanceChart"), (
        "линии очередей рисуются только при открытии сравнения очередей")
