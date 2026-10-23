"""Пятно застройки, этажность и подземные уровни — на отрисованной странице.

Проверочный пример владельца — офис на Пролетарском проспекте, вл. 20:
участок 0,243 га, наземная площадь 22 842 м², 68 машино-мест под землёй
(2 380 м²). Путь — как у человека: нежилой проект, площадь участка и потенциал
в «Офисы» из карточки участка, 68 мест в поле гаража офиса. На вкладке «ТЭП»
карточка «Пятно застройки, этажность и подземная часть» показывает пятно около
60 %, этажность 15–20 и два подземных уровня, второй — с надбавкой. Предельная
этажность ниже расчётной — предупреждение простыми словами.

Предохранитель: без ответа движка (`tep.site_massing`) карточка говорит, что
чисел ещё нет, — значит, ниже проверяется ответ движка, а не текст страницы.
На старом коде карточки нет вовсе, и проверка падает.

Запуск: python3 -m pytest tests/test_site_massing_on_the_page.py -q
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

SETUP = """async ()=>{
 applyProjectKind('nonresidential'); closeProjectKindDialog(); await settledCalculate();
 setSiteArea(0.243); setSiteDensity(22842/0.243);
 applyDensityToObject('offices'); await settledCalculate();
 openTab('inputs'); renderInputs();
 document.querySelectorAll('#inputs details').forEach(d=>{d.open=true});
}"""

READ = """()=>{
 openTab('tep'); renderTep();
 const card=document.getElementById('siteMassingCard');
 const body=document.getElementById('siteMassingBody');
 const box=card?card.getBoundingClientRect():{width:0,height:0};
 return {text:body?body.innerText:'', visible:!!card&&box.width>0&&box.height>0,
         warnings:Array.from(document.querySelectorAll('.site-massing-warning')).map(n=>n.innerText),
         m:(lastResult.tep||{}).site_massing||null,
         report:(document.getElementById('reportMassingNote')||{}).innerText||''};
}"""

STRIP = """()=>{delete lastResult.tep.site_massing; renderTep();
 return (document.getElementById('siteMassingBody')||{}).innerText||'';}"""


@pytest.fixture(scope="module")
def seen():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    path = browser.chromium_or_skip()
    out: dict = {}
    with browser.serve(core.app, 18183) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            page = engine.new_page(viewport={"width": 1440, "height": 900})
            page.goto(base, wait_until="domcontentloaded")
            browser.wait_for_result(page)
            page.evaluate(SETUP)
            page.fill("#f_offices_parking_under_spaces", "68")
            page.dispatch_event("#f_offices_parking_under_spaces", "change")
            browser.wait_for_result(page)
            out["example"] = page.evaluate(READ)
            # Предельная этажность — полем карточки, как человек.
            page.evaluate("()=>{openTab('tep');renderTep();"
                          "document.getElementById('siteMassingBox').open=true}")
            page.fill("#massing_max_storeys_allowed", "9")
            page.dispatch_event("#massing_max_storeys_allowed", "change")
            browser.wait_for_result(page)
            out["limited"] = page.evaluate(READ)
            out["stripped"] = page.evaluate(STRIP)
    return out


def test_the_counterfeit_has_no_numbers(seen):
    assert "появятся" in seen["stripped"], seen["stripped"]


def test_the_proletarsky_office_reads_fifteen_storeys_and_two_levels(seen):
    got = seen["example"]
    assert got["visible"], "карточки пятна застройки на вкладке «ТЭП» нет"
    m = got["m"]
    assert m, "движок не вернул пятно застройки"
    assert m["underground_sqm"] == pytest.approx(2380.0)
    assert 0.55 <= m["footprint_share"] <= 0.65
    assert 15 <= m["average_storeys"] <= 20
    assert m["underground_levels"] == 2
    text = got["text"].replace("\xa0", " ")
    for needle in ("Пятно застройки", "1 510 м²", "это 62% участка", "Средняя этажность",
                   "≈ 15,1", "Подземных уровней", "2 380 м²", "−2 (надбавка +10%)"):
        assert needle in text, (needle, text)
    assert "двух уровнях" in got["report"], got["report"]


def test_too_many_storeys_are_warned_in_plain_words(seen):
    got = seen["limited"]
    assert got["m"]["max_storeys_allowed"] == 9
    assert any("разрешено не выше 9 этажей" in w and "не помещается" in w
               for w in got["warnings"]), got["warnings"]
    assert not seen["example"]["warnings"]
