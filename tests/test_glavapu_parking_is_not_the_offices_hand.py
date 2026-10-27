"""Места сценария ГлавАПУ не делают поле офиса «заданным руками».

Владелец, 25.10.2026, участок 77:06:0003002:18 (деловое управление 4.1):
ничего не вписывал, а под нулём в поле «мест на первых этажах» стояло красным
«Задано руками… Строим 149 — дефицит 122». Импорт участка кладёт места
сценария ГлавАПУ в поле подземного паркинга проекта (`setUndergroundFromMethod`);
прежде нежилой проект отдавал их офису, и офис читал их как вписанные руками.
Перенос убран (#911), и движок это проверяет. Эта проверка — того же пути на
отрисованной странице: импорт настоящими функциями страницы, нетронутое поле
офиса идёт за нормативом и так подписано.

Запуск: python3 -m pytest tests/test_glavapu_parking_is_not_the_offices_hand.py -q
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

PORT = 18167

# Как импорт участка: чистый проект, тип «нежилой», офис с площадями и места
# сценария ГлавАПУ последними — всё настоящими функциями страницы.
SETUP = """async ()=>{
  const set=(id,value)=>{
    const el=document.getElementById('f_'+id);
    if(el.type==='checkbox')el.checked=value;else el.value=value;
    el.dispatchEvent(new Event('change'));
  };
  resetAll();
  applyProjectKind('nonresidential');
  set('offices_enabled',true);
  set('offices_gba_sqm','27000');
  set('offices_saleable_sqm','20000');
  setUndergroundFromMethod(136,13);
}"""

READ = """()=>{
  renderInputs();
  const item=((projectParking().own)||[]).find(o=>o&&o.prefix==='offices')||{};
  const value=id=>Number((document.getElementById('f_'+id)||{}).value||0);
  return {under:value('offices_parking_under_spaces'),
          over:value('offices_parking_over_spaces'),
          note:objectParkingFieldNote('offices'),
          item:item};
}"""


@pytest.fixture(scope="module")
def seen():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    path = browser.chromium_or_skip()
    with browser.serve(core.app, PORT) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            page = engine.new_page(viewport={"width": 1440, "height": 900})
            page.goto(base, wait_until="domcontentloaded")
            browser.wait_for_result(page)
            page.evaluate(SETUP)
            browser.wait_for_result(page)
            page.evaluate("()=>settledCalculate()")
            got = page.evaluate(READ)
            page.close()
    return got


def test_the_office_garage_follows_the_norm(seen):
    item = seen["item"]
    assert item.get("by_norm") is True, item
    assert item["required_spaces"] > 0, item
    # Строится норматив, а не места сценария ГлавАПУ.
    assert item["units"] == item["required_spaces"], item


def test_the_fields_show_the_norm(seen):
    assert seen["under"] + seen["over"] == seen["item"]["required_spaces"], seen


def test_the_note_does_not_blame_a_person(seen):
    assert "Задано руками" not in seen["note"], seen["note"]
    assert "дефицит" not in seen["note"], seen["note"]
    assert "нормативу" in seen["note"], seen["note"]
