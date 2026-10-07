"""Снос и расселение стоят в «Структуре расходов» отчёта, PDF и свода очередей.

Статьи есть в CAPEX движка и книги (строки 36 и 37), а в структуре расходов
групп для них не было: таблица отчёта и PDF теряли их молча, и итог структуры
не сходился с «Расходами всего» ровно на снос и расселение.

Запуск: python3 -m pytest tests/test_demolition_reaches_the_expense_structure.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import main_legacy as core  # noqa: E402
from test_book_interest_horizon_follows_the_engine import BASE, tep_of_a_real_project  # noqa: E402

DEMOLITION = {"demolition_area_sqm": 20_000, "demolition_cost_th_per_sqm": 13.5,
              "resettlement_cost_mln": 100}


def _rows(result):
    return {item["label"]: item for item in result["report"]["expense_structure"]}


def test_both_articles_are_rows_and_the_table_adds_up():
    result = core._run_authoritative_model({**BASE, **DEMOLITION}, tep_of_a_real_project(),
                                           [], {})["consolidated"]
    rows = _rows(result)
    assert rows["Снос и демонтаж"]["value"] == pytest.approx(20_000 * 13.5 * 1000)
    assert rows["Расселение"]["value"] == pytest.approx(100e6)
    assert rows["Снос и демонтаж"]["per_base_th"] > 0 and rows["Снос и демонтаж"]["base_label"]
    total = sum(item["value"] for item in result["report"]["expense_structure"])
    assert total == pytest.approx(result["summary"]["total_expenses"], rel=1e-9)


def test_zero_articles_take_no_row():
    result = core._run_authoritative_model(dict(BASE), tep_of_a_real_project(), [], {})["consolidated"]
    assert "Снос и демонтаж" not in _rows(result) and "Расселение" not in _rows(result)


def test_the_queue_summary_keeps_them():
    bundle = core.calculate_phased(core.PhasedCalcRequest(
        inputs={**BASE, **DEMOLITION}, tep=tep_of_a_real_project(), rates=[],
        phasing={"enabled": True, "phase_count": 2, "phase_gap_months": 0}))
    rows = _rows(bundle["consolidated"])
    assert rows["Снос и демонтаж"]["value"] == pytest.approx(20_000 * 13.5 * 1000, rel=1e-6)
    assert rows["Расселение"]["value"] == pytest.approx(100e6, rel=1e-6)


def test_the_print_names_them():
    pytest.importorskip("reportlab", reason="reportlab нужен только для PDF")
    from market_search.krt_requirements import pdf_text

    inputs = {**BASE, **DEMOLITION}
    bundle = core._run_authoritative_model(inputs, tep_of_a_real_project(), [], {})
    pdf = core._build_developaid_pdf({"result": bundle["consolidated"], "project_name": "П",
                                      "inputs": inputs, "tep": tep_of_a_real_project()})
    text = pdf_text(pdf)
    assert "Снос и демонтаж" in text and "Расселение" in text
