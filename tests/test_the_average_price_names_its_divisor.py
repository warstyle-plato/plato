"""«Средняя цена квартир» — это цена МЕТРА, и подпись обязана это сказать.

В блоке «Итог» строка показывала «916,6 тыс. ₽» без единицы. Число — выручка
квартир, делённая на ПРОДАВАЕМУЮ ПЛОЩАДЬ квартир (`average_apartment_price_th`
в движке), то есть тыс. ₽ за метр. Владелец читал его как цену квартиры
(27.09.2026).

Спутать было тем легче, что «Средняя цена квартиры» — в рублях ЗА КВАРТИРУ —
на той же странице действительно есть, в блоке продаж квартир. Два названия
отличались одной буквой: «квартир» и «квартиры».

Правило CLAUDE.md: удельный показатель подписывается тем делителем, на который
число делится, а база берётся из кода, а не из заголовка. Здесь делитель —
`apartment_saleable_sqm`, и соседние строки того же блока уже подписаны
«/м² прод.».

Проверка смотрит на ОТРИСОВАННУЮ страницу: подпись рядом с числом — это то,
что читает человек, и в исходнике верный код от сломанного не отличить.

Запуск: python3 -m pytest tests/test_the_average_price_names_its_divisor.py -q
"""

from __future__ import annotations

import copy
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import main_legacy as core  # noqa: E402
from browser import chromium_or_skip, serve  # noqa: E402

PORT = 8793


def test_the_value_really_is_price_per_square_metre():
    """Сперва — что число именно такое: подпись без этого ничего не значит."""
    inputs = copy.deepcopy(core.DEFAULT_INPUTS)
    tep = {key: dict(value) for key, value in core.TEP_DEFAULT.items()}
    got = core.calculate(core.CalcRequest(inputs=inputs, tep=tep, rates=[]))
    summary = got["summary"]
    apartments = next(p for p in got["report"]["products"] if p["key"] == "apartments")
    metres = float(summary["apartment_saleable_sqm"])
    assert metres > 0
    expected = float(apartments["revenue"]) / metres / 1000
    assert abs(float(summary["average_apartment_price_th"]) - expected) < 0.01, (
        "величина не равна «выручка квартир ÷ продаваемая площадь квартир»")
    # И это НЕ цена квартиры: та — в миллионах за штуку.
    per_flat = float((got["report"].get("apartment_sales") or {}).get("avg_unit_price_mln") or 0)
    assert per_flat > 0, "в стенде нет цены за квартиру — спутать не с чем"
    assert abs(per_flat * 1000 - expected) > 1, "две величины совпали — стенд не различает их"


def test_the_two_names_are_not_one_letter_apart():
    """Название однозначно: «квартир» и «квартиры» отличались одной буквой."""
    page = core.PAGE
    assert "row('Средняя цена м² квартир'" in page
    assert "row('Средняя цена квартир'," not in page, "прежнее двусмысленное имя вернулось"
    # Цена ЗА КВАРТИРУ — другая величина, и она остаётся на месте.
    assert "row('Средняя цена квартиры'" in page


def test_in_a_real_browser_the_unit_stands_next_to_the_number():
    chrome = chromium_or_skip()
    from playwright.sync_api import sync_playwright

    from main_registry import app as registry_app

    with serve(registry_app, PORT) as base, sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chrome))
        try:
            tab = browser.new_page()
            errors: list[str] = []
            tab.on("pageerror", lambda e: errors.append(str(e)))
            tab.goto(f"{base}/classic", wait_until="domcontentloaded")
            tab.wait_for_timeout(700)
            got = tab.evaluate("""async ()=>{
              await calculate();
              const rows=[...document.querySelectorAll('tr,div')]
                .map(x=>x.textContent||'').filter(t=>t.includes('Средняя цена'));
              // Результат берётся у глобальной `lastResult`: `r` — имя
              // внутри `renderResult`, снаружи его нет.
              return {rows: rows,
                      value: lastResult.summary.average_apartment_price_th};
            }""")
        finally:
            browser.close()

    other = [line for line in errors if "Failed to fetch" not in line]
    assert not other, f"страница упала: {other[:2]}"
    lines = [re.sub(r"\s+", " ", one).strip() for one in got["rows"]]
    per_sqm = [one for one in lines if "Средняя цена м² квартир" in one]
    assert per_sqm, f"строки цены метра на странице нет: {lines[:6]}"
    # Берётся САМАЯ КОРОТКАЯ: длинные — это родительские узлы со всей таблицей.
    cell = min(per_sqm, key=len)
    assert "/м² прод." in cell, f"единицы рядом с числом нет: {cell!r}"
    assert "тыс. ₽" in cell, cell
    # И число то самое, а не соседнее.
    shown = re.search(r"([\d  ,]+) тыс\. ₽", cell)
    assert shown, cell
    number = float(shown.group(1).replace(" ", "").replace(" ", "").replace(",", "."))
    assert abs(number - float(got["value"])) < 1.0, (number, got["value"])
