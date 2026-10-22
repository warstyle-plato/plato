"""Число квартир в ТЭП двигает машино-места — в движке, в книге и на экране.

Владелец (прод, 22.10.2026): «машиноместа даже не дрогнули при изменении
кол-ва квартир». Квартиры — 50 615,2 м² продаваемой, количество 1000, потом
500; строка «Подземный паркинг» оба раза — 660 м/м с подписью «по средней
квартире 67,5 м² (750 квартир × 0,8)», то есть потребность прежнего числа.

Норма (`permanentByNorm` страницы, `moscow_permanent_parking_by_average`
движка) число квартир из ТЭП читала и пересчитывала места в `tep` — но правка
ячейки количества звала только `updateTepTotals`, а не `renderTep`: строка
паркинга, её подпись и запертые ячейки оставались с прежней потребностью.
Движок и книга считают по той же строке ТЭП (`apply_underground_tep_row`) и
от числа квартир идут — это закреплено здесь же, чтобы методика не разошлась.

Числа квартир подобраны так, чтобы полосы 2118-ПП давали разные места:
500 × 1,6 и 1000 × 0,8 — одно и то же (800), и проверка на них зеленела бы
на любом коде.

Запуск: python3 -m pytest tests/test_the_flat_count_moves_the_parking.py -q
"""

from __future__ import annotations

import copy
import io
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import browser  # noqa: E402
import main_legacy as core  # noqa: E402

SALEABLE = 50615.2
GNS = 77869.6


def _need(saleable: float, flats: int) -> int:
    permanent, _ = core.moscow_permanent_parking_by_average(saleable, flats)
    return permanent + math.ceil(permanent * core._PARKING_GUEST_SHARE)


def _tep(flats: int) -> dict:
    t = copy.deepcopy(core.TEP_DEFAULT)
    t["apartments"].update(gns=GNS, saleable=SALEABLE, useful=SALEABLE, units=flats)
    return t


def test_the_engine_counts_the_flats_of_the_tep() -> None:
    got = {}
    for flats in (750, 1000, 600):
        t = _tep(flats)
        core.apply_underground_tep_row(dict(core.DEFAULT_INPUTS), t)
        got[flats] = t["underground_parking"]["units"]
        assert got[flats] == _need(SALEABLE, flats)
    assert got == {750: 660, 1000: 880, 600: 792}, got


def test_the_book_sells_the_places_of_the_same_flats() -> None:
    """Книга берёт места из той же строки ТЭП, что движок, — своей нормы у неё нет."""
    openpyxl = pytest.importorskip("openpyxl")
    seen = {}
    for flats in (1000, 600):
        t = _tep(flats)
        engine = copy.deepcopy(t)
        core.apply_underground_tep_row(dict(core.DEFAULT_INPUTS), engine)
        content, _, _ = core.build_project_workbook(
            dict(core.DEFAULT_INPUTS), t, [], None, project_name="Паркинг")
        sheet = openpyxl.load_workbook(io.BytesIO(content))["Вводные"]
        base = [row[1].value for row in sheet.iter_rows(min_col=1, max_col=2)
                if row[0].value == "База паркинга"]
        assert base == [core.underground_saleable_spaces(engine["underground_parking"])], base
        seen[flats] = base[0]
    assert seen[1000] != seen[600], "книга не заметила другого числа квартир"


# Ячейку правят так, как правит человек: значение и событие `change` на самом
# поле таблицы, а не вызовом функции страницы.
TYPE = """([col,value])=>{
  const el=tepBody.querySelector(`input[onchange*="'apartments','${col}'"]`);
  el.focus();el.value=value;el.dispatchEvent(new Event('change'));el.blur();
}"""

# То, что видит человек: подпись строки и число в её ячейке мест.
SEEN = """()=>{
  const tr=tepBody.querySelector(`input[onchange*="'underground_parking','units'"]`).closest('tr');
  return {text:tr.textContent.replace(/\\s+/g,' '),
          spaces:Number(tr.querySelector(`input[onchange*="'underground_parking','units'"]`).value),
          saleable:Number(tep.apartments.saleable),
          data:Number(tep.underground_parking.units)};
}"""


@pytest.fixture(scope="module")
def screens():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    path = browser.chromium_or_skip()
    out = {}
    with browser.serve(core.app, 18191) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            page = engine.new_page(viewport={"width": 1440, "height": 900})
            page.goto(base, wait_until="domcontentloaded")
            browser.wait_for_result(page)
            for flats in (1000, 500):
                page.evaluate(TYPE, ["units", str(flats)])
                browser.wait_for_result(page)
                out[flats] = page.evaluate(SEEN)
    return out


def test_the_page_redraws_the_parking_row_for_the_typed_flats(screens) -> None:
    for flats, seen in screens.items():
        need = _need(seen["saleable"], flats)
        assert seen["data"] == need, seen
        assert seen["spaces"] == need, (
            f"в ячейке {seen['spaces']} м/м, норма от {flats} квартир — {need}: строка не перерисована")
        count = f"{flats:,}".replace(",", " ")
        assert f"({count} квартир ×" in seen["text"], seen["text"]
        assert f"= {need:,} м/м".replace(",", " ") in seen["text"], seen["text"]
    assert screens[1000]["spaces"] != screens[500]["spaces"], (
        "1000 и 500 квартир дали одни места — проверка ничего не различает")
