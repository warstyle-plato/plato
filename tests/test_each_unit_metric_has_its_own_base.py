"""Каждый удельный «на м²» делится на свою базу и подписан ею.

Решение владельца 29.09.2026 (ревизия книги, решение 4) и ответы 03.10.2026:
  * полные расходы, CAPEX и все расходные строки — на суммарную площадь в ГНС
    (наземная + подземная);
  * СМР наземной части — на наземную ГНС МКД, подземной — на подземную площадь
    МКД (на них СМР и начислено);
  * выручка, цена, EBITDA и чистая прибыль — на продаваемую площадь;
  * у расходов остаётся вторая колонка «на м² продаваемой».

Прежде все строки делились на наземную ГНС проекта, и СМР подземной части
выходило 23 тыс. ₽/м² при ставке 88: подземные деньги делились на наземные
метры. Проверка на прежнем коде падает на первой же строке (ставка СМР не
равна введённой), а на странице — и на подделке, решающей базу саму.

Запуск: python3 -m pytest tests/test_each_unit_metric_has_its_own_base.py -q
"""

from __future__ import annotations

import copy
import io
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import main as _wrapper  # noqa: E402
import terms_glossary as tg  # noqa: E402
from browser import chromium_or_skip, serve  # noqa: E402

core = _wrapper.core
PORT = 18801


def _inputs() -> dict:
    return copy.deepcopy(core.DEFAULT_INPUTS)


def _tep() -> dict:
    return copy.deepcopy(core.TEP_DEFAULT)


@pytest.fixture(scope="module")
def single() -> dict:
    return core._run_authoritative_model(_inputs(), _tep(), [], {})["consolidated"]


@pytest.fixture(scope="module")
def phased() -> dict:
    phasing = {"enabled": True, "mode": "phased", "phase_count": 2, "user_enabled": True,
               "phase_gap_months": 12,
               "phases": [{"name": f"О{i + 1}", "start_offset_months": 12 * i,
                           "construction_months": 30} for i in range(2)]}
    return core._run_authoritative_model(_inputs(), _tep(), [], phasing)["consolidated"]


EXPECTED_ROW_BASES = {
    "revenue": "saleable_area", "ebitda": "saleable_area", "net_profit": "saleable_area",
    "capex": "total_area", "commercial_costs": "total_area", "financing_cost": "total_area",
    "profit_tax": "total_area", "vat": "total_area", "total_expenses": "total_area",
}


def _check_rows(result: dict) -> None:
    summary = result["summary"]
    bases = summary["unit_bases"]
    assert bases["total_area"] == pytest.approx(summary["construction_volume_sqm"])
    assert bases["saleable_area"] == pytest.approx(summary["monetizable_saleable_sqm"])
    assert bases["core_above_area"] == pytest.approx(result["tep"]["core_above_gns"])
    assert bases["core_under_area"] == pytest.approx(result["tep"]["core_under_gns"])
    rows = {row["key"]: row for row in result["report"]["unit_economics"]}
    assert {key: row["base"] for key, row in rows.items()} == EXPECTED_ROW_BASES
    for row in rows.values():
        area = bases[row["base"]]
        assert row["per_base_th"] == pytest.approx(row["total"] / area / 1000)
        assert row["base_label"] == tg.unit_label(row["base"]), "подпись — не из словаря"
    for row in result["report"]["expense_structure"]:
        assert row["base"] == "total_area"
        assert row["per_base_th"] == pytest.approx(row["value"] / bases["total_area"] / 1000)
    costs = {row["label"]: row for row in result["report"]["construction_costs"]}
    assert costs["СМР наземной части"]["base"] == "core_above_area"
    assert costs["СМР подземной части"]["base"] == "core_under_area"
    assert costs["ИРД"]["base"] == "total_area"
    assert summary["full_cost_per_total_area_th"] == pytest.approx(
        summary["total_expenses"] / bases["total_area"] / 1000)
    for gone in ("full_cost_per_gns_th", "ebitda_per_gns_th", "net_profit_per_gns_th"):
        assert gone not in summary, f"{gone}: прибыль и расходы на наземную ГНС больше не считаются"


def test_construction_is_divided_by_the_part_it_was_charged_on(single):
    """СМР на метр своей части — это и есть введённая ставка."""
    costs = {row["label"]: row for row in single["report"]["construction_costs"]}
    inputs = _inputs()
    assert costs["СМР наземной части"]["per_base_th"] == pytest.approx(
        float(inputs["main_above_th_per_sqm"]))
    assert costs["СМР подземной части"]["per_base_th"] == pytest.approx(
        float(inputs["main_under_th_per_sqm"]))


def test_every_row_has_its_base_single(single):
    _check_rows(single)


def test_every_row_has_its_base_phased(phased):
    _check_rows(phased)
    table = phased["comparison_table"]
    labels = [row["label"] for block in table["blocks"] for row in block["rows"]]
    assert f"CAPEX на м² {tg.TOTAL_AREA.genitive}" in labels
    assert not [label for label in labels if label.endswith("на м² ГНС")], labels


def test_the_base_choice_has_one_owner():
    """Выбор базы статьи CAPEX — один на движок и книгу."""
    import v4_dashboard
    assert core.capex_unit_base is tg.capex_unit_base
    assert v4_dashboard.capex_unit_base is tg.capex_unit_base


def test_the_book_dashboard_reads_the_same_numbers(single):
    openpyxl = pytest.importorskip("openpyxl")
    import v4_dashboard as vd
    from xlsx_eval import Evaluator
    sys.setrecursionlimit(400000)
    content, _, meta = core.build_project_workbook(_inputs(), _tep(), [], {})
    assert meta["missing"] == [], meta["missing"]
    ev = Evaluator(openpyxl.load_workbook(io.BytesIO(content), data_only=False))
    costs = {row["label"]: row for row in single["report"]["construction_costs"]}
    for index, (label, _keys) in enumerate(vd.COST_ITEMS):
        row = vd.COST_FIRST_ROW + index
        if label not in costs:
            continue
        book = float(ev.cell(vd.DATA_SHEET, f"C{row}") or 0)
        engine = costs[label]["per_base_th"]
        assert abs(book - engine) <= max(0.05, engine * 0.002), (label, book, engine)
        assert ev.cell(vd.DATA_SHEET, f"E{row}") == "м² " + tg.TERMS[costs[label]["base"]].genitive


def test_the_pdf_names_each_base(single):
    pytest.importorskip("reportlab")
    from market_search.krt_requirements import pdf_text
    pdf = core._build_developaid_pdf({"result": single, "project_name": "Базы",
                                      "inputs": _inputs(), "tep": _tep()})
    text = re.sub(r"\s+", " ", pdf_text(pdf))
    for term in (tg.TOTAL_AREA, tg.SALEABLE_AREA, tg.CORE_ABOVE_AREA, tg.CORE_UNDER_AREA):
        assert f"м² {term.genitive}" in text, term.genitive
    assert "наземной ГНС МКД" in text and "88,00" in text
    assert "тыс ₽/м² наземной ГНС" not in text, "прежняя единая база вернулась"


def test_the_teaser_names_the_construction_base(single):
    from pypdf import PdfReader
    bundle = core._run_authoritative_model(_inputs(), _tep(), [], {})
    pdf = core.build_teaser_pdf(bundle, _inputs(), _tep(), {})
    reader = PdfReader(io.BytesIO(pdf))
    assert len(reader.pages) == 2
    text = re.sub(r"\s+", " ", " ".join(p.extract_text() for p in reader.pages))
    assert tg.CORE_ABOVE_AREA.genitive in text and tg.CORE_UNDER_AREA.genitive in text
    assert f"тыс ₽/м² {tg.TOTAL_AREA.genitive}" in text
    assert "тыс ₽/м² ГНС" not in text, "прежняя подпись базы вернулась"


def test_the_page_prints_the_engines_bases():
    """Отрисованная страница: базу строки называет движок.

    Подделка: движку подменяют базу строки «Выручка» и её число — страница,
    решающая базу сама по подписи строки, этого бы не заметила.
    """
    chrome = chromium_or_skip()
    from playwright.sync_api import sync_playwright

    from main_registry import app as registry_app

    with serve(registry_app, PORT) as base, sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chrome))
        try:
            tab = browser.new_page()
            errors: list[str] = []
            tab.on("pageerror", lambda e: errors.append(str(e)))
            tab.goto(f"{base}/classic", wait_until="domcontentloaded")
            tab.wait_for_timeout(700)
            got = tab.evaluate("""async ()=>{
              await calculate();
              const grab=id=>[...document.querySelectorAll('#'+id+' tr')]
                .map(tr=>[...tr.children].map(x=>(x.textContent||'').replace(/\\s+/g,' ').trim()));
              const before={unit:grab('unitEconomicsTable'), capex:grab('capexTable'),
                            revenue:grab('revenueTable'),
                            head:(document.getElementById('expenseBaseHead')||{}).textContent||''};
              const row=lastResult.report.unit_economics.find(x=>x.key==='revenue');
              row.base='core_under_area'; row.per_base_th=12345;
              renderResult();
              return {before, after: grab('unitEconomicsTable')};
            }""")
        finally:
            browser.close()

    other = [line for line in errors if "Failed to fetch" not in line]
    assert not other, f"страница упала: {other[:2]}"
    unit = {row[0]: row for row in got["before"]["unit"]}
    assert unit["Выручка"][3] == "м² " + tg.SALEABLE_AREA.genitive, unit["Выручка"]
    assert unit["Выручка"][4] == "—", "у выручки вторая колонка не повторяется"
    assert unit["CAPEX"][3] == "м² " + tg.TOTAL_AREA.genitive, unit["CAPEX"]
    capex = {row[0]: row for row in got["before"]["capex"]}
    under = next(row for label, row in capex.items() if "подземн" in label.lower())
    assert under[2] == "88,00" and under[3] == "м² " + tg.CORE_UNDER_AREA.genitive, under
    assert all(len(row) == 3 for row in got["before"]["revenue"]), got["before"]["revenue"][:2]
    assert got["before"]["head"] == "тыс ₽/м² " + tg.TOTAL_AREA.genitive
    after = {row[0]: row for row in got["after"]}
    assert after["Выручка"][3] == "м² " + tg.CORE_UNDER_AREA.genitive, after["Выручка"]
    assert after["Выручка"][2].replace(" ", " ").startswith("12 345"), after["Выручка"]
