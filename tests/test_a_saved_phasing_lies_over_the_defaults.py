"""Сохранённая очерёдность накладывается на умолчания, а не заменяет их.

Прод 0.27.7, телефон владельца, Safari, «Проект → ТЭП»: «Незавершённая работа
страницы. undefined is not an object (evaluating 'phasing.discrete[o.key]')».
Восстановление из браузера (`loadLocal`) и открытие проекта/снимка
(`applyProjectSnapshot`) ставили `phasing` сохранённым объектом целиком; у
проекта, сохранённого без поля `discrete` (или с частичной очерёдностью из
Торгов, Платона, передачи), его так и не было, и блок очередей объектов падал.

Теперь у сохранённого один вход — `phasingFromSaved`: умолчания своего числа
очередей, поверх них сохранённое, словари — поключево. Проверяется отрисованная
страница: настоящий PAGE в Chromium, снимок приезжает разобранным JSON, а
состояние браузера — через настоящую перезагрузку.

Запуск: python3 -m pytest tests/test_a_saved_phasing_lies_over_the_defaults.py -q
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

PORT = 18147

INPUTS = {"offices_enabled": True, "offices_gba_sqm": 10000, "offices_saleable_sqm": 6000}
TEP = {"offices": {"gns": 10000, "total_area": 9400, "saleable": 6000}}

# Старая очерёдность: включена человеком, две очереди, словаря `discrete` нет.
OLD_PHASING = {
    "enabled": True, "user_enabled": True, "phase_count": 2, "phase_gap_months": 12,
    "phases": [{"name": "О1", "start_offset_months": 0, "construction_months": 24},
               {"name": "О2", "start_offset_months": 12, "construction_months": 24}],
    "products": {"apartments": [60, 40]},
}

READ = """()=>Array.from(document.querySelectorAll('#assignObjects select[data-object]'))
  .map(s=>({key:s.dataset.object,value:s.value}))"""

SNAPSHOT = """async ([x, t, ph])=>{
  const asStored=(body)=>JSON.parse(JSON.stringify(body));
  const out={};
  try{
    applyProjectSnapshot(asStored({inputs:Object.assign({},INPUT_DEFAULT,x),tep:t,phasing:ph,scenario:'base'}));
    await calculate();
    renderPhasing();
  }catch(e){out.error=String(e&&e.message||e)}
  out.objects=(%s)();
  out.discrete=phasing.discrete;
  out.apartments=phasing.products.apartments;
  out.commercial=phasing.products.ground_commercial;
  out.shared=Object.keys(phasing.shared_cash||{}).length;
  out.phases=phasing.phases.length;
  out.user_enabled=phasing.user_enabled;
  // Частичный словарь: сохранённая очередь объекта не теряется.
  try{
    applyProjectSnapshot(asStored({inputs:Object.assign({},INPUT_DEFAULT,x),tep:t,
      phasing:Object.assign({},ph,{discrete:{offices:2}}),scenario:'base'}));
    renderPhasing();
  }catch(e){out.partial_error=String(e&&e.message||e)}
  out.partial=(%s)();
  return out;
}""" % (READ, READ)


@pytest.fixture(scope="module")
def seen():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    path = browser.chromium_or_skip()
    out: dict = {}
    errors: list[str] = []
    with browser.serve(core.app, PORT) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            page = engine.new_page(viewport={"width": 1300, "height": 900})
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.on("dialog", lambda dialog: dialog.accept())
            page.goto(base, wait_until="domcontentloaded")
            browser.wait_for_result(page)
            out["snapshot"] = page.evaluate(SNAPSHOT, [INPUTS, TEP, OLD_PHASING])

            # Состояние браузера старой версии: та же очерёдность без `discrete`.
            tep = page.evaluate("()=>JSON.parse(JSON.stringify(tep))")
            for key, row in TEP.items():
                tep.setdefault(key, {}).update(row)
            stored = {"inputs": dict(core.DEFAULT_INPUTS, **INPUTS), "tep": tep,
                      "phasing": OLD_PHASING, "scenario": "base"}
            page.evaluate("(s)=>localStorage.setItem('plato_v04',s)", json.dumps(stored))
            page.reload(wait_until="domcontentloaded")
            try:
                browser.wait_for_result(page)
            except AssertionError as exc:
                out["boot_error"] = str(exc)
            out["restored"] = page.evaluate(
                "()=>({objects:(%s)(),user_enabled:phasing.user_enabled,"
                "discrete:phasing.discrete,phases:phasing.phases.length})" % READ)
            page.evaluate("localStorage.removeItem('plato_v04')")
            page.close()
    out["errors"] = errors
    return out


def test_the_page_does_not_fall_on_old_phasing(seen):
    """То, ради чего всё: ни снимок, ни состояние браузера не роняют страницу."""
    snap = seen["snapshot"]
    assert "error" not in snap, f"снимок без discrete уронил страницу: {snap['error']}"
    assert "partial_error" not in snap, snap.get("partial_error")
    assert "boot_error" not in seen, f"старое состояние браузера уронило загрузку: {seen.get('boot_error')}"
    assert not seen["errors"], f"страница упала: {seen['errors'][:2]}"


def test_the_object_queue_selectors_are_in_place(seen):
    """Блок очередей объектов на месте — и после снимка, и после перезагрузки."""
    assert [o["key"] for o in seen["snapshot"]["objects"]] == ["offices"], seen["snapshot"]
    assert [o["key"] for o in seen["restored"]["objects"]] == ["offices"], seen["restored"]
    assert seen["restored"]["user_enabled"] is True
    assert seen["restored"]["phases"] == 2
    assert isinstance(seen["restored"]["discrete"], dict) and "offices" in seen["restored"]["discrete"]


def test_saved_values_win_and_missing_ones_come_from_defaults(seen):
    """Сохранённое — поверх умолчаний: своё не теряется, недостающее добирается."""
    snap = seen["snapshot"]
    assert snap["user_enabled"] is True and snap["phases"] == 2
    assert snap["apartments"] == [60, 40], "сохранённые доли квартир подменены"
    assert isinstance(snap["commercial"], list) and len(snap["commercial"]) == 2, \
        "недостающий продукт не добран из умолчаний"
    assert snap["shared"] > 0, "служебные аллокации не добраны из умолчаний"
    assert "offices" in snap["discrete"]
    assert snap["partial"] == [{"key": "offices", "value": "2"}], \
        f"сохранённая очередь объекта потеряна: {snap['partial']}"


def test_every_saved_phasing_goes_through_one_door():
    """Внешнее phasing ставится только через `phasingFromSaved`, не присваиванием."""
    page = core.PAGE
    assert "function phasingFromSaved(" in page
    for bad in ("phasing=x.phasing||", "phasing=data.phasing||", "phasing=Object.assign(phaseDefaults"):
        assert bad not in page, f"сохранённая очерёдность ставится в обход: {bad}"
