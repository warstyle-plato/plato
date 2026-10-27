"""Ручная ставка подземной части как ставка первого уровня — на отрисованной странице.

Проверочный пример владельца — офис на Пролетарском проспекте: участок
0,243 га, 68 машино-мест под землёй, два подземных уровня. Человек вписывает
свою ставку подземной части во «Вводных» — надбавок за глубину нет, оба уровня
по его числу. Рядом со ставкой стоит флажок «Это ставка первого уровня —
глубже добавить надбавки»; человек ставит его — уровень −2 дорожает на
надбавку второго уровня, подпись под таблицей уровней объясняет почему.

Предохранитель: до флажка ставки уровней равны — значит, разница ниже даёт
флажок, а не ставка класса. На старом коде флажка нет, и проверка падает.

Запуск: python3 -m pytest tests/test_a_hand_rate_of_the_first_level_on_the_page.py -q
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

RATE = 200

SETUP = """async ()=>{
 applyProjectKind('nonresidential'); closeProjectKindDialog(); await settledCalculate();
 setSiteArea(0.243); setSiteDensity(22842/0.243);
 applyDensityToObject('offices'); await settledCalculate();
 openTab('inputs'); renderInputs();
 document.querySelectorAll('#inputs details').forEach(d=>{d.open=true});
}"""

OPEN_INPUTS = """()=>{openTab('inputs'); renderInputs();
 document.querySelectorAll('#inputs details').forEach(d=>{d.open=true});}"""

READ = """()=>{
 const rate=document.getElementById('f_main_under_th_per_sqm');
 const box=document.getElementById('f_underground_rate_is_level1');
 const field=box?box.closest('.field'):null;
 const prev=field?field.previousElementSibling:null;
 const rect=field?field.getBoundingClientRect():{width:0,height:0};
 const toggle={present:!!box, checked:!!(box&&box.checked),
  visible:rect.width>0&&rect.height>0, label:field?field.innerText:'',
  next_to_rate:!!(prev&&rate&&prev.contains(rate))};
 openTab('tep'); renderTep();
 const levels=document.querySelector('#siteMassingBody .site-massing-levels');
 const rows=levels?Array.from(levels.querySelectorAll('tbody tr')).map(tr=>
  Array.from(tr.querySelectorAll('td')).map(td=>td.innerText)):[];
 const hint=levels?levels.nextElementSibling:null;
 return {toggle, rows, hint:hint?hint.innerText:'',
         m:(lastResult.tep||{}).site_massing||null};
}"""


@pytest.fixture(scope="module")
def seen():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    path = browser.chromium_or_skip()
    out: dict = {}
    with browser.serve(core.app, 18187) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            page = engine.new_page(viewport={"width": 1440, "height": 900})
            page.goto(base, wait_until="domcontentloaded")
            browser.wait_for_result(page)
            page.evaluate(SETUP)
            page.fill("#f_offices_parking_under_spaces", "68")
            page.dispatch_event("#f_offices_parking_under_spaces", "change")
            browser.wait_for_result(page)
            page.evaluate(OPEN_INPUTS)
            page.fill("#f_main_under_th_per_sqm", str(RATE))
            page.dispatch_event("#f_main_under_th_per_sqm", "change")
            browser.wait_for_result(page)
            page.evaluate(OPEN_INPUTS)
            out["off"] = page.evaluate(READ)
            page.evaluate(OPEN_INPUTS)
            page.check("#f_underground_rate_is_level1")
            browser.wait_for_result(page)
            page.evaluate(OPEN_INPUTS)
            out["on"] = page.evaluate(READ)
    return out


def _rates(rows: list[list[str]]) -> list[str]:
    return [row[2].replace("\xa0", " ") for row in rows]


def test_the_toggle_stands_next_to_the_rate_and_is_off(seen):
    toggle = seen["off"]["toggle"]
    assert toggle["present"] and toggle["visible"], toggle
    assert toggle["next_to_rate"], "флажок стоит не рядом со ставкой подземной части"
    assert "ставка первого уровня" in toggle["label"], toggle["label"]
    assert not toggle["checked"], "флажок по умолчанию должен быть снят"


def test_a_hand_rate_without_the_toggle_has_no_markup(seen):
    got = seen["off"]
    assert got["m"]["underground_levels"] == 2, got["m"]
    assert _rates(got["rows"]) == [f"{RATE} тыс ₽/м²"] * 2, got["rows"]
    assert "надбавки за глубину не применяются" in got["hint"], got["hint"]


def test_the_toggle_adds_the_markup_below_the_first_level(seen):
    got = seen["on"]
    assert got["toggle"]["checked"]
    assert _rates(got["rows"]) == [f"{RATE} тыс ₽/м²", f"{int(RATE * 1.1)} тыс ₽/м²"], got["rows"]
    assert "(надбавка +10%)" in got["rows"][1][0], got["rows"]
    assert "как ставка первого уровня" in got["hint"], got["hint"]
    assert got["m"]["underground_depth_factor"] > 1.0
