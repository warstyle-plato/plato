"""IRR гостиницы против модели Отеля 1: мост сходится, различия подписаны (#654).

Методика гостиницы сведена с книгой (владелец, 11.10.2026): FCFF без процентов,
капитал первым, Гордон, инфраструктура в смете — правила движка. Мост
`scripts/hotel_irr_bridge.py` идёт от расчёта движка на ориентире «Отель 1» по
различиям вводных (даты, ключевая ставка, смета книги) и шагу IRR. Проверки:

* остаток против книги (Контр_панель!G14, G20) — в допуске 0,5 п.п.;
* без инфраструктуры или с продажей 4× вместо Гордона мост не сходится —
  подделка ловится;
* таблица в `docs/hotel_irr_vs_hotel1.md` — та, что считает мост сейчас;
* различия методики напечатаны в отчёте (раздел «Решение») и в книге («Итоги»).

Запуск: python3 -m pytest tests/test_hotel_irr_bridge.py -q
"""

from __future__ import annotations

import copy
import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

pytest.importorskip("openpyxl")

import developaid_hotel_strategy as hs  # noqa: E402
import hotel_irr_bridge as hb  # noqa: E402

TOLERANCE_PP = 0.5


@pytest.fixture(scope="module")
def plan():
    return hb.engine_plan()


@pytest.fixture(scope="module")
def steps(plan):
    return hb.bridge(plan)


def _remainder(steps) -> tuple[float, float]:
    last, book = steps[-2], steps[-1]
    return ((book["irr_project"] - last["irr_project"]) * 100,
            (book["irr_equity"] - last["irr_equity"]) * 100)


def test_the_bridge_starts_at_the_engine_result(plan, steps) -> None:
    assert steps[0]["irr_project"] == pytest.approx(plan["kpi"]["irr_project"], abs=1e-9)
    assert steps[0]["irr_equity"] == pytest.approx(plan["kpi"]["irr_equity"], abs=1e-9)
    assert steps[-1]["irr_project"] == pytest.approx(0.1768128251, abs=1e-9)
    assert steps[-1]["irr_equity"] == pytest.approx(0.3463452842, abs=1e-9)


def test_the_bridge_reaches_the_book_within_tolerance(steps) -> None:
    project, equity = _remainder(steps)
    assert abs(project) <= TOLERANCE_PP and abs(equity) <= TOLERANCE_PP, (project, equity)


@pytest.mark.parametrize("cause", ["infra", "gordon"])
def test_without_a_cause_the_bridge_does_not_close(plan, cause) -> None:
    project, equity = _remainder(hb.bridge(plan, skip=frozenset({cause})))
    assert max(abs(project), abs(equity)) > 2 * TOLERANCE_PP, (cause, project, equity)


def test_the_document_carries_the_current_bridge(steps) -> None:
    text = (ROOT / "docs" / "hotel_irr_vs_hotel1.md").read_text(encoding="utf-8")
    block = text.split("<!-- hotel_irr_bridge:begin")[1].split("-->", 1)[1]
    block = block.split("<!-- hotel_irr_bridge:end -->")[0].strip()
    assert block == hb.table(steps)


def test_every_named_cause_is_a_step_with_book_cells(steps) -> None:
    keys = [s["key"] for s in steps]
    assert keys == ["engine", "dates", "key_rate", "capex", "annual", "book"]
    for s in steps[1:]:
        assert "!" in s["cells"], s["key"]


# --- подпись на поверхностях ---------------------------------------------------

@pytest.fixture(scope="module")
def project():
    import hotel_presets
    import main as wrapper
    core = wrapper.core
    x = copy.deepcopy(core.DEFAULT_INPUTS)
    t = copy.deepcopy(core.TEP_DEFAULT)
    x["project_kind"] = core.PROJECT_KIND_HOTEL
    x = hotel_presets.apply_preset(x, "hotel1")
    return core, x, t


def test_the_report_signs_the_method_differences(project) -> None:
    core, x, t = project
    result = core.calculate(core.CalcRequest(inputs=x, tep=t, rates=[]))
    decision = next(s for s in result["report"]["object_report"]["sections"]
                    if s["key"] == "decision")
    block = next(b for b in decision["blocks"] if b.get("title") == hs.IRR_METHOD_TITLE)
    assert [(r["label"], r["value"]) for r in block["rows"]] == list(hs.IRR_METHOD_NOTES)
    assert [name for name, _ in hs.IRR_METHOD_NOTES] == ["Шаг IRR", "Шаг расчёта"]


def test_the_book_signs_the_method_differences(project) -> None:
    import openpyxl
    import hotel_workbook as hw
    core, x, t = project
    content, _, _ = core.build_project_workbook(x, t, [], {}, project_name="Отель")
    sheet = openpyxl.load_workbook(io.BytesIO(content))[hw.TOTALS_SHEET]
    assert sheet["A23"].value == hs.IRR_METHOD_TITLE
    rows = [(sheet[f"A{n}"].value, sheet[f"B{n}"].value)
            for n in range(24, 24 + len(hs.IRR_METHOD_NOTES))]
    assert rows == list(hs.IRR_METHOD_NOTES)
