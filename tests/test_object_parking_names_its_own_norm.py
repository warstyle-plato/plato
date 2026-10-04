"""Подпись норматива паркинга объекта называет документ своей юрисдикции.

Мытищи (владелец, 04.10.2026): «Мы в Подмосковье, а приложение 6 —
московское?» Расчёт приобъектных мест регион читал (`parking_demand` →
`parking_norms.MOSCOW_OBLAST`), а подписи на странице «по нормативу
приложения 6 к 945-ПП» были зашиты и от региона не зависели: под областным
числом стояло имя московского документа. Теперь имя приходит из движка
(`PARKING_NORM_OF`) рядом с юрисдикцией, по которой посчитано число.

Проверяется на отрисованной странице для Москвы и для области; Москва —
предохранитель: там имя приложения 6 обязано остаться.

Запуск: python3 -m pytest tests/test_object_parking_names_its_own_norm.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import browser  # noqa: E402
import main_legacy as core  # noqa: E402

SETUP = """async (region)=>{
  // Всё — через обработчики полей, как это делает человек.
  const set=(id,value)=>{
    const el=document.getElementById('f_'+id);
    if(el.type==='checkbox')el.checked=value;else el.value=value;
    el.dispatchEvent(new Event('change'));
  };
  set('vri_region',region);
  set('offices_enabled',true);
  set('offices_gba_sqm','40000');
  set('offices_saleable_sqm','30000');
}"""

READ = """()=>{
  renderInputs();
  const cell=document.getElementById('parkNorm_offices');
  return {
          jurisdiction:(projectParking()||{}).jurisdiction,
          field:cell?cell.textContent.trim():'',
          tep:objectParkingNote('offices'),
          summary:String((((lastResult||{}).summary)||{}).object_parking_note||'')};
}"""


@pytest.fixture(scope="module")
def seen():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    path = browser.chromium_or_skip()
    out: dict[str, dict] = {}
    with browser.serve(core.app, 18159) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            for region in ("msk", "mo"):
                ctx = engine.new_context(viewport={"width": 1440, "height": 900})
                page = ctx.new_page()
                page.goto(base, wait_until="domcontentloaded")
                page.wait_for_timeout(2000)
                page.evaluate(SETUP, region)
                page.wait_for_timeout(2500)
                page.evaluate("()=>calculate()")
                page.wait_for_timeout(2500)
                out[region] = page.evaluate(READ)
                out[region]["region"] = region
                ctx.close()
    return out


def test_the_engine_counts_by_the_region(seen):
    assert seen["msk"]["jurisdiction"] == "moscow"
    assert seen["mo"]["jurisdiction"] == "moscow_oblast"


def test_moscow_keeps_appendix_6(seen):
    """Предохранитель: без него проверка ниже зелена и на пустой подписи."""
    got = seen["msk"]
    assert "приложения 6 к 945-ПП" in got["field"], got["field"]
    assert "приложения 6 к 945-ПП" in got["tep"], got["tep"]


def test_the_region_names_its_own_document(seen):
    got = seen["mo"]
    assert got["field"] and got["tep"], got
    for text in (got["field"], got["tep"]):
        assert "945-ПП" not in text and "приложения 6" not in text, text
        assert "Московской области" in text, text


def test_names_come_from_the_engine():
    assert set(core.PARKING_NORM_OF) == {core.parking_norms.MOSCOW,
                                         core.parking_norms.MOSCOW_OBLAST}
