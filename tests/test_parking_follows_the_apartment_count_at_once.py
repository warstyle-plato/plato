"""Машино-места по норме идут за числом квартир сразу, а не после ответа расчёта.

Владелец 22.10.2026 (прод, вкладка ТЭП): «машиноместа даже не дрогнули при
изменении кол-ва квартир». Число квартир в ячейке — 1000, потом 500, а строка
паркинга и подписи остались прежними: «660 м/м … по средней квартире 67,5 м²
(750 квартир × 0,8)», у квартир «Средняя квартира 67,5 м²» — всё от 750.
Подписи у коммерции тоже были прежние: таблица ТЭП не перерисовывалась.

Правка числа квартир попадала в `tep`, а строку перерисовывал только ответ
расчёта (`calculate` → `renderTep`). Расчёт долгий или отказал — места стоят,
хотя норма у страницы своя (`parkingRequirement`) и считается сразу.

Проверка гоняет настоящую страницу, а ответ `/calculate` держит: места обязаны
смениться, пока расчёт ещё идёт.

Запуск: python3 -m pytest tests/test_parking_follows_the_apartment_count_at_once.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import browser  # noqa: E402
import main as wrapper  # noqa: E402

PORT = 18293

READ = """() => {
  const tepText = document.getElementById('tep').innerText;
  return {
    units: tep.apartments.units,
    spaces: tep.underground_parking.units,
    need: (tepText.match(/Потребность[^\\n]*/) || [''])[0],
    note: (tepText.match(/Средняя квартира[^\\n]*/) || [''])[0],
    field: Number(document.getElementById('f_underground_manual_spaces')
                  ? document.getElementById('f_underground_manual_spaces').value : -1),
  };
}"""


import pytest  # noqa: E402


@pytest.mark.parametrize("pair_by_norm", [False, True], ids=["empty-pair", "pair-filled-by-norm"])
def test_parking_moves_with_the_apartment_count_while_the_calculation_runs(pair_by_norm) -> None:
    browser.chromium_or_skip()
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        chrome = pw.chromium.launch(executable_path=str(browser.chromium_or_skip()))
        page = chrome.new_page(viewport={"width": 1400, "height": 900})
        errors: list[str] = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        with browser.serve(wrapper.app, PORT) as root:
            page.goto(root + "/", wait_until="domcontentloaded")
            browser.wait_for_result(page)
            if pair_by_norm:
                # Как у владельца: пара «места — площадь» заполнена нормой,
                # строка паркинга в ТЭП серая (`fillUndergroundFromTep`).
                page.evaluate("() => { fillUndergroundFromTep(); renderInputs(); }")
            page.evaluate("() => openTab('tep')")
            before = page.evaluate(READ)
            # Расчёт «идёт»: ответ не приходит, пока проверка не закончится.
            page.route("**/calculate*", lambda route: None)
            cell = page.locator("input[onchange*=\"'apartments','units'\"]").first
            seen = []
            for count in ("1000", "500"):
                cell.fill(count)
                cell.dispatch_event("change")
                page.wait_for_timeout(300)
                seen.append(page.evaluate(READ))
        chrome.close()

    assert not errors, errors
    first, second = seen
    assert first["units"] == 1000 and second["units"] == 500
    assert first["spaces"] != before["spaces"], (before, first)
    assert second["spaces"] < first["spaces"], "места не пошли за числом квартир"
    assert "1 000 квартир" in first["need"].replace(" ", " "), first["need"]
    assert "500 квартир" in second["need"].replace(" ", " "), second["need"]
    # Поле мест во «Вводных» — пустое («по нормативу») или то же число, что
    # в строке ТЭП: норма одна.
    assert second["field"] in (0, second["spaces"]), second
    if pair_by_norm:
        assert second["field"] == second["spaces"], "поле мест осталось от прежней нормы"
    # Подпись средней квартиры — от нового числа квартир, а не от прежнего.
    assert first["note"] != second["note"], "подпись квартир не перерисовалась"
