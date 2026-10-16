"""Потоки очередей платят налог свода — тот, что в P&L, а не свой в одиночку.

Проект с очередями — один спецзастройщик и один налогоплательщик (владелец,
24.08.2026). P&L свода платит налог по годам с переносом убытка не больше
половины базы года (ст. 283), а потоки капитала и проекта очереди несли
налог, посчитанный ею в одиночку: убыток соседних очередей его не уменьшал.
На Нагатино в потоках было 3 699,5 + 3 474,8 = 7 174 млн, в P&L — 3 669, и
IRR и NPV капитала считались с налогом почти вдвое больше начисленного
(ревизия книги v4, 15.10.2026, вопрос 5).

Решение владельца (16.10.2026): доля очереди — та же, что у её налога в
таблице очередей (по базе каждого года), месяц — тот же, что у свода.

Запуск: python3 -m pytest tests/test_the_queue_cashflows_pay_the_consolidated_tax.py -q
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_the_consolidated_tax_is_shared_year_by_year import _scenario

import main_legacy as core


@pytest.fixture(scope="module")
def phased():
    inputs, tep, phasing = _scenario()
    return core.calculate_phased(core.PhasedCalcRequest(
        inputs=inputs, tep=tep, phasing=phasing))


def _cash_tax_by_month(phased) -> dict[str, float]:
    out: dict[str, float] = {}
    for phase in phased["phases"]:
        cashflow = phase["result"]["cashflow"]
        for month, tax in zip(cashflow["months"], cashflow["profit_tax"]):
            if tax:
                out[month] = out.get(month, 0.0) + float(tax)
    return out


def test_the_queues_alone_would_pay_a_different_tax(phased) -> None:
    """Предохранитель набора: в одиночку очереди платили бы не налог свода.

    Совпади налог в одиночку со сводом — тест ниже зеленел бы и на старом
    поведении, ничего не проверяя.
    """
    alone = sum(float(phase["result"]["finance"]["standalone_profit_tax"])
                for phase in phased["phases"])
    total = float(phased["consolidated"]["summary"]["profit_tax"])
    assert total > 0, "проверять нечего: налога на этом проекте нет"
    assert abs(alone - total) > 1e6, (
        f"в одиночку {alone / 1e6:,.1f} = свод {total / 1e6:,.1f}: набор не различает меры")


def test_the_queue_cashflows_carry_the_consolidated_tax_month_by_month(phased) -> None:
    """Сумма налога в потоках очередей = налог P&L свода, месяц в месяц."""
    total = float(phased["consolidated"]["summary"]["profit_tax"])
    cash = _cash_tax_by_month(phased)
    assert sum(cash.values()) == pytest.approx(total, rel=1e-9)
    rows = {str(row["month"]): float(row.get("profit_tax") or 0.0)
            for row in phased["consolidated"]["finance"]["rows"]}
    for month, tax in rows.items():
        assert cash.get(month, 0.0) == pytest.approx(tax, abs=1.0), month
    assert set(cash) <= {month for month, tax in rows.items() if tax}


def test_the_queue_pays_in_its_cashflow_what_its_pnl_says(phased) -> None:
    """Одна доля на два читателя: налог очереди в P&L = налог в её потоке."""
    for phase, row in zip(phased["phases"], phased["comparison"]):
        cash = sum(float(v or 0.0) for v in phase["result"]["cashflow"]["profit_tax"])
        assert cash == pytest.approx(float(row["profit_tax"]), rel=1e-9, abs=1.0), row["name"]
        assert cash == pytest.approx(float(phase["result"]["summary"]["profit_tax"]),
                                     rel=1e-9, abs=1.0)


def test_the_queue_returns_follow_its_restated_flow(phased) -> None:
    """IRR и NPV очереди посчитаны по её потоку с налогом свода."""
    rate = float(core.DEFAULT_INPUTS.get("discount_rate_pct", 20)) / 100
    checked = 0
    for phase in phased["phases"]:
        summary = phase["result"]["summary"]
        if summary.get("npv_equity") is None:
            continue
        equity = phase["result"]["cashflow"]["equity"]
        assert summary["npv_equity"] == pytest.approx(core._equity_npv(equity, rate), rel=1e-9)
        assert summary["irr_equity"] == core._monthly_irr(equity)
        checked += 1
    assert checked, "ни у одной очереди нет NPV — проверять нечего"


def test_the_irr_survives_a_tax_tail_after_the_inflow() -> None:
    """Вложение, приход и хвост налога после него — у ряда есть доходность.

    Края поиска у такого ряда одного знака: у −95% решает хвост, у больших
    ставок — вложение. Прежний поиск сдавался и снимал IRR очереди.
    """
    flows = [-100.0] + [0.0] * 11 + [1_000.0] + [-60.0] * 6
    irr = core._monthly_irr(flows)
    assert irr is not None and irr > 0
    monthly = (1 + irr) ** (1 / 12) - 1
    assert sum(cf / (1 + monthly) ** i for i, cf in enumerate(flows)) == pytest.approx(0, abs=1e-3)
    # Обычный ряд считается прежним путём.
    assert core._monthly_irr([-100.0, 110.0]) == pytest.approx(1.1 ** 12 - 1, rel=1e-6)


def test_the_workbook_queue_rows_pay_the_engine_tax(phased) -> None:
    """Строка 24 листов очередей книги — та же доля свода, что у движка."""
    openpyxl = pytest.importorskip("openpyxl")
    from xlsx_eval import Evaluator

    sys.setrecursionlimit(400000)
    inputs, tep, phasing = _scenario()
    content, _, meta = core.build_project_workbook(
        inputs, tep, [], phasing, project_name="Налог свода в потоках очередей")
    assert not [item for item in meta["missing"] if "строка 24" in item or "строка 33" in item]
    book = openpyxl.load_workbook(io.BytesIO(content))
    for index in range(1, 5):
        assert "24" not in str(book[f"CF_{index}"]["AC33"].value).replace("AC$3", "")
    evaluator = Evaluator(book)
    for index, phase in enumerate(phased["phases"], start=1):
        got = evaluator.cell(f"CF_{index}", "B24")
        want = float(phase["result"]["summary"]["profit_tax"]) / 1e6
        assert got == pytest.approx(want, abs=max(1.0, want * 0.01)), (
            f"О{index}: книга {got:,.1f} против движка {want:,.1f}")
