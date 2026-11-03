"""Гостевых больше, чем мест, — чужое число: оно отбрасывается, а не режется.

В сохранённом проекте «Донской» (владелец, 15.10.2026, файл настроек в
tests/fixtures) у подземного паркинга 29 мест и 109 гостевых — хвост прежнего
ТЭП. `underground_guest_spaces` обрезал гостевые до числа мест: все 29 мест
становились гостевыми, и там, где строку не пересчитывал норматив, продажи
паркинга обнулялись. Чужое число теперь отбрасывается, гостевые выводятся из
норматива (S/11 = 3), продаётся 26. Страница пишет назад число движка — хвост
не переезжает с сохранением, — а замена видна уведомлением при загрузке. В ТЭП
PDF у паркинга стоит число мест к продаже: «Продаваемая, м²» у него 0.

Запуск: python3 -m pytest tests/test_stale_guest_spaces_are_dropped.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import browser  # noqa: E402
import main_legacy as core  # noqa: E402

PORT = 18976
SETTINGS = json.loads((ROOT / "tests" / "fixtures" / "project_settings_donskoy_0_25_78.json")
                      .read_text(encoding="utf-8"))


def test_foreign_guest_count_falls_back_to_the_norm() -> None:
    assert core.underground_guest_spaces({"units": 29, "guest_units": 109}) == 3
    # Своё число гостевых (выгрузка ГлавАПУ) остаётся своим.
    assert core.underground_guest_spaces({"units": 369, "guest_units": 34}) == 34
    assert core.underground_guest_spaces({"units": 29, "guest_units": 29}) == 29


def test_engine_names_the_dropped_value() -> None:
    result = core.calculate(core.CalcRequest(
        inputs={**core.DEFAULT_INPUTS, **SETTINGS["inputs"]},
        tep=json.loads(json.dumps(SETTINGS["tep"])), rates=[]))
    row = next(r for r in result["tep"]["rows"] if r["key"] == "underground_parking")
    assert (row["units"], row["guest_units"], row["saleable_units"]) == (29, 3, 26)
    assert row["guest_units_stale"] == 109


PROBE = r"""async (data) => {
  applyProjectSnapshot(data);
  await settledCalculate();
  renderResult();
  const note = document.getElementById('pageNotice');
  return {note: note ? note.innerText.trim() : '',
          table: /исправлено при загрузке/.test((document.getElementById('report') || document.body).innerText),
          guest: tep.underground_parking.guest_units,
          sold: lastResult.tep.rows.find(r => r.key === 'underground_parking').saleable_units};
}"""


@pytest.fixture(scope="module")
def page_state() -> dict:
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    path = browser.chromium_or_skip()
    with browser.serve(core.app, PORT) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            page = engine.new_page(viewport={"width": 1440, "height": 900})
            page.goto(base, wait_until="domcontentloaded")
            browser.wait_for_result(page)
            got = page.evaluate(PROBE, SETTINGS)
            page.close()
    return got


def test_the_page_heals_the_saved_state(page_state) -> None:
    assert page_state["guest"] == 3, page_state
    assert page_state["sold"] == 26, page_state


def test_the_replacement_is_a_notice_not_a_table_note(page_state) -> None:
    # Таблица молчит (владелец, 16.10.2026); число «было → стало» — в уведомлении.
    assert "гостевые места 109 → 3 (норматив)" in page_state["note"], page_state
    assert not page_state["table"], page_state

def test_the_pdf_tep_names_spaces_for_sale() -> None:
    inputs = {**core.DEFAULT_INPUTS, **SETTINGS["inputs"]}
    tep = json.loads(json.dumps(SETTINGS["tep"]))
    bundle = core._run_authoritative_model(inputs, tep, [], {})
    pdf = core._build_developaid_pdf({
        "result": bundle["consolidated"], "phases": bundle.get("phases") or [],
        "inputs": inputs, "tep": tep, "rates": [], "phasing": {}, "scenario": "base",
        "cadastral_numbers": []})
    pypdf = pytest.importorskip("pypdf")
    import io
    text = "\n".join(p.extract_text() for p in pypdf.PdfReader(io.BytesIO(pdf)).pages)
    assert "к продаже 26" in " ".join(text.split())
