"""Вкладка «ТЭП»: компактный участок, сразу таблица, настройки и кнопки — под ней.

Владелец (17.10.2026): между параметрами участка и таблицей ТЭП лежали три
кнопки пересчёта, коэффициенты парковки, параметры Подмосковья и длинные
пояснения — на телефоне до таблицы приходилось долго прокручивать, а что и в
каком порядке нажимать, было непонятно. Порядок теперь: карточка «Участок и
плотность» → таблица ТЭП → свёрнутые «Паркинг и нормативы» и параметры
Подмосковья → сверка с ГлавАПУ. Кнопки стоят у своих полей (владелец,
18.10.2026): «Сформировать ТЭП по новым параметрам» — в карточке участка,
«Пересчитать по нормативам» и «Подтянуть значения из «Экономики»» — сразу
под таблицей.

Проверяется отрисованная страница в Chromium на ширинах телефона и десктопа:
порядок блоков по геометрии, свёрнутость складок, отсутствие горизонтальной
прокрутки страницы. На прежней вёрстке (кнопки и коэффициенты над таблицей)
проверки краснеют. Для долей без браузера — та же проверка порядка по разметке.

Запуск: python3 -m pytest tests/test_the_tep_tab_leads_with_the_table.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main_legacy as core  # noqa: E402
from tests import browser  # noqa: E402

PORT = 18796

# Порядок узлов сверху вниз, который видит человек.
ORDER = ["siteAreaHa", "tepBody", "siteParkingBox", "moParamsBox", "glavapuScenarioBox"]

PROBE = """(ids)=>{
 const top=el=>Math.round(el.getBoundingClientRect().top+window.scrollY);
 const out={tops:{},buttons:{}};
 for(const id of ids){const el=document.getElementById(id);out.tops[id]=el?top(el):null;}
 for(const fn of ['formTepByDensity','syncTep','recalcFromTep']){
  const b=document.querySelector(`#tep [onclick="${fn}()"]`);
  out.buttons[fn]=b?top(b):null;
 }
 const site=document.getElementById('siteAreaHa').closest('.card');
 out.siteCardHeight=Math.round(site.getBoundingClientRect().height);
 out.siteCardTop=top(site);
 out.tableTop=top(document.querySelector('#tep .teptable'));
 out.parkingOpen=document.getElementById('siteParkingBox').open;
 out.moOpen=document.getElementById('moParamsBox').open;
 out.summary=document.getElementById('siteParkingSummary').textContent;
 out.pageScroll=document.documentElement.scrollWidth-window.innerWidth;
 return out;}"""


def _render(width: int) -> dict:
    from playwright.sync_api import sync_playwright

    path = browser.chromium_or_skip()
    with browser.serve(core.app, PORT) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            page = engine.new_page(viewport={"width": width, "height": 900})
            page.goto(base, wait_until="load")
            browser.wait_for_result(page)
            page.evaluate("async()=>{syncTep(false);await settledCalculate();renderTep();openTab('tep');}")
            page.wait_for_function("document.querySelectorAll('#tepBody tr').length>3",
                                   timeout=20000)
            got = page.evaluate(PROBE, ORDER)
            page.close()
    return got


@pytest.fixture(scope="module")
def phone() -> dict:
    return _render(390)


@pytest.fixture(scope="module")
def desktop() -> dict:
    return _render(1300)


def _check_order(got: dict) -> None:
    tops = [got["tops"][i] for i in ORDER]
    assert None not in tops, f"узла нет на странице: {got['tops']}"
    assert tops == sorted(tops), f"порядок блоков вкладки ТЭП нарушен: {got['tops']}"
    # Заполнение по плотности — в карточке участка, у полей площади и
    # плотности; пересчёт по нормативам — под таблицей, до свёрнутых
    # настроек; подтягивание из «Экономики» — следом за ним.
    buttons, site_top = got["buttons"], got["siteCardTop"]
    assert buttons["formTepByDensity"] is not None
    assert site_top < buttons["formTepByDensity"] < site_top + got["siteCardHeight"] < got["tableTop"], \
        "кнопка заполнения по плотности стоит не в карточке участка"
    assert buttons["recalcFromTep"] is not None
    assert got["tableTop"] < buttons["recalcFromTep"] < got["tops"]["siteParkingBox"], \
        "кнопка пересчёта по нормативам стоит не сразу под таблицей"
    assert buttons["syncTep"] is not None
    assert buttons["recalcFromTep"] < buttons["syncTep"] < got["tops"]["siteParkingBox"], \
        "кнопка «Подтянуть значения из «Экономики»» стоит не под таблицей"
    assert got["parkingOpen"] is False, "«Паркинг и нормативы» раскрыты по умолчанию"
    assert got["moOpen"] is False, "параметры Подмосковья раскрыты по умолчанию"
    assert got["summary"].startswith("Паркинг и нормативы")


def test_on_a_phone_the_table_comes_right_after_the_site_card(phone: dict) -> None:
    _check_order(phone)
    assert phone["pageScroll"] <= 0, "страница на телефоне прокручивается вбок"
    # Между карточкой участка и таблицей — ничего: таблица начинается там,
    # где кончается карточка (следующая карточка — отступ между ними).
    gap = phone["tableTop"] - (phone["tops"]["siteAreaHa"] + phone["siteCardHeight"])
    assert 0 < gap < 260, f"между участком и таблицей снова что-то лежит: {gap}px"


def test_on_a_desktop_the_order_is_the_same(desktop: dict) -> None:
    _check_order(desktop)


def test_the_markup_keeps_the_order_without_a_browser() -> None:
    page = core.PAGE
    tep = page.index('<div id="tep" class="panel">')
    vri = page.index('<div id="vri" class="panel">')
    panel = page[tep:vri]
    marks = ['id="siteAreaHa"', 'onclick="formTepByDensity()"', 'id="tepBody"',
             'onclick="recalcFromTep()"', 'onclick="syncTep()"', 'id="siteParkingBox"', 'id="moParamsBox"',
             'id="glavapuScenarioBox"']
    positions = [panel.index(m) for m in marks]
    assert positions == sorted(positions), "порядок блоков вкладки ТЭП в разметке нарушен"
