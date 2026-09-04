"""Снос и расселение доезжают в книгу — и делятся между очередями один раз.

Движок тратил 270,9 млн ₽ на снос, а в шаблоне книги v4 строки для этой
статьи не было: книга теряла её молча, и ровно на эту сумму расходились пик
БРИДЖа, а следом CAPEX, проценты, налог и LLCR (владелец, 04.09.2026:
«расхождения опять»). Вводные сноса с 0.21.84 стояли в F39–F41 «Вводных», но их
не читала ни одна формула. Рядом второе: в очередях снос копировался в каждую
целиком — четыре очереди сносили одно и то же четыре раза.

Запуск: python3 -m pytest tests/test_demolition_reaches_the_book.py -q
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import main_legacy as core  # noqa: E402
from test_book_interest_horizon_follows_the_engine import BASE, tep_of_a_real_project  # noqa: E402

openpyxl = pytest.importorskip("openpyxl")

DEMOLITION = {"demolition_area_sqm": 20_000, "demolition_cost_th_per_sqm": 13.5,
              "resettlement_cost_mln": 100}


def _book(**overrides):
    content, _, missing = core.build_project_workbook(
        {**BASE, **DEMOLITION, **overrides}, tep_of_a_real_project(), [], {}, project_name="П")
    return openpyxl.load_workbook(io.BytesIO(content)), missing


def _evaluator(wb):
    from xlsx_eval import Evaluator

    sys.setrecursionlimit(400000)
    return Evaluator(wb)


def test_the_rows_are_written_and_read() -> None:
    wb, missing = _book()
    assert not [m for m in missing if "снос" in m.lower() or "CAPEX" in m], missing
    ws = wb["CAPEX"]
    assert ws["A36"].value == "Снос и демонтаж" and ws["A37"].value == "Расселение"
    assert "'Вводные'!$F$39" in ws["B36"].value and "'Вводные'!$F$40" in ws["B36"].value
    assert "'Вводные'!$F$41" in ws["B37"].value
    # Итог блока и база резерва видят новые строки — в каждом из четырёх блоков.
    for base in (0, 34, 68, 102):
        assert f"+D{36 + base}+D{37 + base}" in ws.cell(32 + base, 4).value
        assert f"+B{36 + base}+B{37 + base}" in ws.cell(30 + base, 2).value
    # Вводные сноса теперь читаются формулой, а не стоят обещанием.
    ev = _evaluator(wb)
    assert ev.cell("CAPEX", "B36") == pytest.approx(20_000 * 13.5 / 1000, rel=1e-6)
    assert ev.cell("CAPEX", "B37") == pytest.approx(100.0, rel=1e-6)
    # Помесячно — окно перед РнС, как у подготовки: сумма месяцев равна статье.
    months = sum(float(ev.cell("CAPEX", f"{openpyxl.utils.get_column_letter(4 + i)}36") or 0)
                 for i in range(120))
    assert months == pytest.approx(270.0, rel=1e-6)


def test_the_book_keeps_parity_with_the_engine_on_demolition() -> None:
    """Паритет — на тех строках ПРОВЕРОК, которые расходились у владельца."""
    wb, _ = _book()
    ev = _evaluator(wb)
    ws = wb["ПРОВЕРКИ"]
    checked = 0
    for row in range(70, 95):
        name = str(ws.cell(row, 1).value or "")
        if "Паритет" not in name and "ПАРИТЕТ" not in name:
            continue
        if not any(word in name for word in ("CAPEX", "БРИДЖ", "финансирования", "прибыль")):
            continue
        fact = ev.cell("ПРОВЕРКИ", f"B{row}")
        expected, tolerance = ws.cell(row, 3).value, ws.cell(row, 5).value
        assert abs(float(fact) - float(expected)) <= float(tolerance), (name, fact, expected)
        checked += 1
    assert checked >= 4


def test_queues_share_the_demolition_instead_of_each_paying_it() -> None:
    inputs = {**BASE, **DEMOLITION}
    single = core.build_operating_model(dict(inputs), tep_of_a_real_project(), [])
    one = single["capex_amounts"]["demolition"] + single["capex_amounts"]["resettlement"]
    bundle = core.calculate_phased(core.PhasedCalcRequest(
        inputs=dict(inputs), tep=tep_of_a_real_project(), rates=[],
        phasing={"enabled": True, "phase_count": 2, "phase_gap_months": 0}))
    paid = 0.0
    for phase in bundle["phases"]:
        costs = ((phase.get("result") or {}).get("monthly") or {}).get("costs") or []
        paid += sum(float(c.get("total") or 0) for c in costs
                    if c.get("key") in ("demolition", "resettlement"))
    assert len(bundle["phases"]) == 2
    assert paid == pytest.approx(one, rel=1e-6), (paid, one)
    # Подпись статьи в отчёте — по-русски, а не сырым ключом.
    assert core._MONTHLY_CAPEX_LABELS["demolition"] == "Снос и демонтаж"
