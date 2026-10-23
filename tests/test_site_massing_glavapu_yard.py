"""Строка 57 сверки с калькулятором ГлавАПУ — в двор пятна застройки, на странице.

Решение владельца 22.10.2026: двор по норме — большее из нашей нормы и строки 57
«Озеленённые территории ЖК». Готовая сверка («Сверить сценарий») сохраняет
строки 57–58 в проект вместе с числом квартир, принятым калькулятором; движок
берёт строку 57, пока в ТЭП столько же квартир. Здесь выполняется настоящий
`glavapuScenarioKeepTerritory` страницы на ответе сверки, а двор читается из
ответа движка и из карточки «Пятно застройки».

Предохранитель: калькулятор не принял число квартир — строка хранится без
числа квартир, и двор остаётся нашей нормой.

Запуск: python3 -m pytest tests/test_site_massing_glavapu_yard.py -q
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

RUN = """async (refused)=>{
 setSiteArea(4); await settledCalculate();
 const units=Math.round(Number((tep.apartments||{}).units||0));
 const before=(lastResult.tep||{}).site_massing||{};
 glavapuScenarioKeepTerritory({state:'done',key:'test',scenario:{params:{flats_count:units}},
  applied:{refused:refused?[{param:'flats_count',place:'поле',reason:'не принято'}]:[]},
  glavapu:{territory:{green_zhk:[4.0,'строка 57, га'],'57_1':[2.8,'строка 57.1, га'],'57_2':[1.2,'строка 57.2, га']}}});
 await settledCalculate();
 openTab('tep'); renderTep();
 const m=(lastResult.tep||{}).site_massing||{};
 return {units:units, before:before.yard_sqm, yard:m.yard_sqm, basis:m.yard_basis||'',
         kept:!!inputs._glavapu_scenario,
         flats:Number((inputs._glavapu_scenario||{}).flats_count||0),
         card:(document.getElementById('siteMassingBody')||{}).innerText||''};
}"""


@pytest.fixture(scope="module")
def seen():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    path = browser.chromium_or_skip()
    out: dict = {}
    with browser.serve(core.app, 18186) as base, sync_playwright() as pw, \
            pw.chromium.launch(executable_path=str(path)) as engine:
        for refused in (False, True):
            page = engine.new_page(viewport={"width": 1280, "height": 900})
            page.goto(base, wait_until="domcontentloaded")
            browser.wait_for_result(page)
            out[refused] = page.evaluate(RUN, refused)
            page.close()
    return out


def test_the_scenario_check_row_57_becomes_the_yard(seen):
    got = seen[False]
    assert got["units"] > 0 and got["kept"]
    assert got["before"] < 40000.0, "наша норма должна быть меньше строки 57 примера"
    assert got["yard"] == pytest.approx(40000.0)
    assert "сверка сценария, строка 57" in got["basis"]
    card = got["card"].replace("\xa0", " ")
    assert "40 000 м²" in card and "сверка сценария, строка 57" in card, card


def test_a_refused_flats_field_keeps_our_norm(seen):
    """Калькулятор не принял число квартир — строка 57 хранится без квартир и
    в двор не идёт."""
    got = seen[True]
    assert got["kept"] and got["flats"] == 0
    assert got["yard"] == pytest.approx(got["before"])
