"""Вкладка «Чувствительность», диаграмма и раздел в отчёте.

Диаграмма своя, на SVG: тащить графическую библиотеку ради одного графика
незачем, а печать и PDF со сторонним холстом работают хуже.

Тесты гоняют настоящий код страницы в node.
Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import io
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core


def project():
    inputs = dict(core.DEFAULT_INPUTS)
    inputs["purchase_price_mln"] = 6500
    tep = {key: dict(value) for key, value in core.TEP_DEFAULT.items()}
    return inputs, tep


@pytest.fixture(scope="module")
def report():
    inputs, tep = project()
    return core.run_sensitivity(inputs, tep, [], {}, metric="llcr")


# --- Вкладка -----------------------------------------------------------------

def test_the_tab_sits_between_the_calendar_and_the_report():
    page = core.PAGE
    order = [page.index(f'data-tab="{name}"') for name in ("calendar", "sensitivity", "report")]

    assert order == sorted(order), "вкладка встала не рядом с отчётом и календарём"
    assert '<div id="sensitivity" class="panel">' in page


def test_the_analysis_never_runs_on_an_ordinary_recalculation():
    """Десятки расчётов не должны запускаться при правке обычных вводных."""
    page = core.PAGE
    start = page.index("async function calculate()")
    body = page[start:page.index("\n}\n", start)]

    assert "runSensitivity" not in body
    assert "/analysis/sensitivity" not in body


def test_the_report_carries_the_analysis_only_when_it_was_run():
    page = core.PAGE
    start = page.index("function currentPdfReportPayload(")
    body = page[start:page.index("\n}\n", start)]

    assert "sensitivity:sensitivityReport" in body


# --- Диаграмма ---------------------------------------------------------------

def page_function(name: str) -> str:
    source = core.PAGE
    start = source.index(f"function {name}(")
    depth = 0
    for position in range(source.index("{", start), len(source)):
        if source[position] == "{":
            depth += 1
        elif source[position] == "}":
            depth -= 1
            if depth == 0:
                return source[start:position + 1]
    raise AssertionError(f"не найдена функция {name}")


def draw(items: list[dict], base: float, digits: int = 3) -> str:
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    payload = {"base": {"value": base, "digits": digits, "label": "LLCR", "unit": "x"},
               "items": items}
    script = (
        "const nodes={};\n"
        "const document={getElementById:(id)=>nodes[id]||(nodes[id]={innerHTML:''})};\n"
        "function escapeHtml(s){return String(s??'').replace(/[&<>\"']/g,"
        "m=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[m]))}\n"
        + page_function("sensFormat") + "\n"
        + page_function("renderTornado") + "\n"
        f"renderTornado({json.dumps(payload, ensure_ascii=False)});\n"
        "console.log(nodes['sensitivityChart'].innerHTML);\n"
    )
    done = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    return done.stdout


ROW = {"label": "Стартовая цена квартир", "low_result": 0.72, "high_result": 0.88,
       "impact": 0.16, "kind": "pct"}


def test_the_chart_is_plain_svg():
    svg = draw([ROW], 0.80)

    assert svg.startswith("<svg") and "</svg>" in svg
    assert "<rect" in svg and "<line" in svg


def test_the_base_line_is_drawn():
    svg = draw([ROW], 0.80)

    assert "база 0,80" in svg


def test_a_parameter_whose_growth_hurts_is_drawn_on_the_correct_side():
    """Рост себестоимости ухудшает LLCR — плечо обязано уйти влево от базы."""
    cost = {"label": "СМР", "low_result": 0.85, "high_result": 0.75, "impact": 0.10, "kind": "pct"}
    svg = draw([cost], 0.80)
    positions = [float(value) for value in re.findall(r'<rect x="([\d.]+)"', svg)]

    assert len(positions) == 2
    assert positions[0] != positions[1], "оба плеча нарисованы в одной точке"


def test_a_missing_scenario_does_not_break_the_chart():
    svg = draw([{"label": "Параметр", "low_result": None, "high_result": 0.9,
                 "impact": 0.1, "kind": "pct"}], 0.80)

    assert svg.startswith("<svg")


def test_an_empty_report_draws_nothing():
    assert draw([], 0.80).strip() == ""


def test_the_chart_is_limited_so_it_stays_readable():
    rows = [{**ROW, "label": f"Параметр {i}"} for i in range(30)]
    svg = draw(rows, 0.80)

    assert svg.count("<rect") == 14 * 2, "на диаграмму попали все параметры подряд"


# --- Раздел в отчёте ---------------------------------------------------------

def pdf_text(payload) -> str:
    pypdf = pytest.importorskip("pypdf")
    data = core._build_developaid_pdf(payload)
    return "\n".join(page.extract_text() or ""
                     for page in pypdf.PdfReader(io.BytesIO(data)).pages)


def payload_for(report=None):
    inputs, tep = project()
    bundle = core._run_authoritative_model(inputs, tep, [], {})
    payload = {"result": bundle["consolidated"], "inputs": inputs, "tep": tep,
               "rates": [], "phasing": {}, "scenario": "base"}
    if report is not None:
        payload["sensitivity"] = report
    return payload


def test_the_report_shows_the_analysis_when_it_was_run(report):
    text = pdf_text(payload_for(report))

    assert "Чувствительность проекта" in text
    assert report["items"][0]["label"] in text
    assert "один параметр за расчёт" in text


def test_the_report_stays_as_it_was_without_the_analysis():
    assert "Чувствительность проекта" not in pdf_text(payload_for())


def test_the_verdict_reaches_the_report(report):
    text = pdf_text(payload_for(report))

    assert "Наибольшее влияние" in text


def test_the_markup_is_not_printed_literally(report):
    """P() экранирует текст сам — теги в него класть нельзя."""
    text = pdf_text(payload_for(report))

    assert "<b>" not in text
