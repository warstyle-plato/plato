"""Места сценария ГлавАПУ — не «задано руками» у офиса нежилого проекта.

Владелец, 25.10.2026, участок 77:06:0003002:18 (деловое управление 4.1):
ничего не вписывал, а в поле «мест на первых этажах» стоял 0 и красным
«Задано руками… Строим 149 — дефицит 122 мест». Импорт кладёт места сценария
ГлавАПУ в поле подземного паркинга проекта (`setUndergroundFromMethod`),
движок нежилого проекта отдавал их офису (`office_takes_project_parking`), а
офис читал непустое поле как человеческое. Число калькулятора — не решение
человека: нетронутое поле офиса идёт за нормативом и так подписывается.

Предохранитель — места проекта, вписанные человеком: они по-прежнему
переходят офису, и подпись называет, откуда они.

Запуск: python3 -m pytest tests/test_glavapu_parking_is_not_the_offices_hand.py -q
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import browser  # noqa: E402
import main_legacy as core  # noqa: E402

PORT = 18167

# Как импорт участка: тип проекта, офис с ТЭП и места сценария ГлавАПУ —
# всё настоящими функциями страницы, без подмены логики.
SETUP = """async ()=>{
  const set=(id,value)=>{
    const el=document.getElementById('f_'+id);
    if(el.type==='checkbox')el.checked=value;else el.value=value;
    el.dispatchEvent(new Event('change'));
  };
  // Новый участок начинается с чистого проекта: пометок «норма/руками» у
  // паркинга проекта ещё нет, ТЭП пуст.
  resetAll();
  applyProjectKind('nonresidential');
  set('offices_enabled',true);
  set('offices_gba_sqm','27000');
  set('offices_saleable_sqm','20000');
  // Импорт ставит места сценария последними (`setUndergroundFromMethod`).
  setUndergroundFromMethod(136,13);
}"""

# Места проекта, вписанные человеком, на странице нежилого проекта не
# набираются — правка полей обнуляет пару. Приходят они с сохранённым
# проектом (Пролетарский): его и загружаем настоящим `loadLocal`.
SAVED = """(saved)=>{localStorage.setItem('plato_v04',JSON.stringify(saved))}"""


def _saved_person_project() -> dict:
    x = {"project_kind": core.PROJECT_KIND_NONRESIDENTIAL, "offices_enabled": True,
         "offices_gba_sqm": 27000, "offices_saleable_sqm": 20000,
         "offices_parking_under_spaces": 0, "offices_parking_over_spaces": 0,
         "underground_manual_spaces": 149}
    tep = {"offices": {"gns": 27000, "total_area": 24000, "useful": 20000, "saleable": 20000}}
    return {"inputs": x, "tep": tep, "scenario": "base"}


READ = """()=>{
  renderInputs();
  const item=((projectParking().own)||[]).find(o=>o&&o.prefix==='offices')||{};
  return {under:Number((document.getElementById('f_offices_parking_under_spaces')||{}).value||0),
          over:Number((document.getElementById('f_offices_parking_over_spaces')||{}).value||0),
          note:objectParkingFieldNote('offices'),
          item:item};
}"""


@pytest.fixture(scope="module")
def seen():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    path = browser.chromium_or_skip()
    out: dict[str, dict] = {}
    with browser.serve(core.app, PORT) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            for case in ("method", "person"):
                ctx = engine.new_context(viewport={"width": 1440, "height": 900})
                page = ctx.new_page()
                page.goto(base, wait_until="domcontentloaded")
                browser.wait_for_result(page)
                if case == "method":
                    page.evaluate(SETUP)
                else:
                    page.evaluate(SAVED, _saved_person_project())
                    page.reload(wait_until="domcontentloaded")
                browser.wait_for_result(page)
                page.evaluate("()=>settledCalculate()")
                out[case] = page.evaluate(READ)
                ctx.close()
    return out


def test_the_method_places_leave_the_office_to_the_norm(seen):
    got = seen["method"]
    item = got["item"]
    assert item.get("by_norm") is True, item
    assert item["required_spaces"] > 0, item
    assert got["under"] + got["over"] == item["required_spaces"], got
    assert "Задано руками" not in got["note"], got["note"]
    assert "поставил норматив" in got["note"], got["note"]


def test_places_named_by_a_person_still_go_to_the_office(seen):
    got = seen["person"]
    item = got["item"]
    assert item.get("by_norm") is False and item.get("from_project") is True, item
    assert item["units"] == 149, item
    # В поле объекта ноль — подпись обязана сказать, откуда 149.
    assert "поле подземного паркинга проекта" in got["note"], got["note"]
    assert "Задано руками" not in got["note"], got["note"]


def test_the_engine_tells_the_method_from_a_person():
    x = copy.deepcopy(core.DEFAULT_INPUTS)
    x.update(project_kind=core.PROJECT_KIND_NONRESIDENTIAL, offices_enabled=True,
             offices_gba_sqm=27000, offices_saleable_sqm=20000,
             offices_parking_under_spaces=0, underground_manual_spaces=149)
    t = copy.deepcopy(core.TEP_DEFAULT)
    t["offices"].update(gns=27000, total_area=24000, useful=20000, saleable=20000)
    method = dict(x, _underground_method_guest={"spaces": 149, "guest": 13})
    _, _, moves = core.office_takes_project_parking(method, t)
    assert moves == [], "места метода ушли офису как человеческие"
    _, _, moves = core.office_takes_project_parking(dict(x, _parking_by_hand=[]), t)
    assert moves, "места, вписанные человеком, офису не перешли"
    moved, _, _ = core.office_takes_project_parking(dict(x, _parking_by_hand=[]), t)
    assert "offices" in moved["_parking_by_hand"], "норма заменила бы названные места"
