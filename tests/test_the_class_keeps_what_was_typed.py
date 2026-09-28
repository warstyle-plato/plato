"""Окно класса называет объект у его поля, а смена класса не затирает ручное.

Две беды одного узла (владелец, 27.09.2026):

1. В окне «Настройки класса» стояли две строки «Стартовая цена тыс. ₽/м²» с
   одним числом — цены офисов и ТЦ. Короткая подпись однозначна только внутри
   своей группы; вне её поле объекта называет объект (имя — из реестра).
   Пояснение «считается от цены квартир» снято 28.09.2026: у нежилого своя
   цена, за ценой квартир она не идёт.
2. Ручную правку помнили пять полей из литерала; цену офисов, благоустройство
   и прочие поля профиля следующий выбор класса перезаписывал молча. Теперь
   поле профиля, изменённое руками, помечается вписанным, и смена класса
   спрашивает, называя поля: заменить или оставить.

Проверяется отрисованная страница в Chromium; на прежнем коде проверки красные.

Запуск: python3 -m pytest tests/test_the_class_keeps_what_was_typed.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main_legacy as core  # noqa: E402
from tests import browser  # noqa: E402

PORT = 18773

CLASS_ROWS = """()=>{
 openClassDialog();renderClassDialog();
 const rows=[...document.querySelectorAll('#classDialogBody table tr')].slice(1);
 return rows.map(r=>r.cells[0]?r.cells[0].innerText.replace(/\\s+/g,' ').trim():'')
   .filter(Boolean);
}"""

TYPE = """([id,value])=>{
 const el=document.getElementById('f_'+id);
 el.value=String(value);el.dispatchEvent(new Event('change'));
 return inputs[id];
}"""


def _open(engine, base):
    page = engine.new_page(viewport={"width": 1300, "height": 900})
    page.goto(base, wait_until="domcontentloaded")
    page.wait_for_function("document.querySelectorAll('details[data-group]').length>3",
                           timeout=20000)
    return page


def test_the_class_window_names_the_object_and_the_rule() -> None:
    from playwright.sync_api import sync_playwright

    path = browser.chromium_or_skip()
    with browser.serve(core.app, PORT) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            rows = _open(engine, base).evaluate(CLASS_ROWS)
    # Строка — это подпись плюс единица; пояснение правила стоит после «·».
    names = [row.split(" · ")[0] for row in rows]
    assert len(names) == len(set(names)), f"в окне класса две одинаковые строки: {names}"
    offices = next(r for r in rows if r.startswith("Стартовая цена — МФОЦ / офисы"))
    retail = next(r for r in rows if r.startswith("Стартовая цена — ТЦ / коммерция ОСЗ"))
    # У нежилого своя цена: правило даёт только базу класса, дальше за ценой
    # квартир она не идёт (владелец, 28.09.2026), и строка этого не обещает.
    for row in (offices, retail):
        assert "считается от цены квартир" not in row, row


def test_a_deviation_names_the_object_too() -> None:
    # Строки отклонений PDF и «Не подставлено» читают ту же подпись вне группы.
    inputs = dict(core.DEFAULT_INPUTS, offices_price_th_per_sqm=777)
    rows = core.project_class_deviations(inputs)["rows"]
    assert [r["label"] for r in rows] == ["Стартовая цена — МФОЦ / офисы"]


def _switch(engine, base, answer: str, typed: dict):
    page = _open(engine, base)
    messages: list[str] = []

    def on_dialog(dialog):
        messages.append(dialog.message)
        dialog.accept() if answer == "accept" else dialog.dismiss()

    page.on("dialog", on_dialog)
    for key, value in typed.items():
        if key in core.CLASS_ONLY_INPUTS:
            page.evaluate("([k,v])=>setClassRate(k,v)", [key, value])
        else:
            page.evaluate(TYPE, [key, value])
    page.evaluate("()=>applyProjectClassPreset('business')")
    got = page.evaluate("keys=>Object.fromEntries(keys.map(k=>[k,inputs[k]]))",
                        list(typed) + ["apartment_price_th", "project_class"])
    return got, messages


TYPED = {"offices_price_th_per_sqm": 777, "landscaping_th_per_sqm": 42}


def test_a_class_switch_keeps_what_was_typed_when_asked_to() -> None:
    from playwright.sync_api import sync_playwright

    path = browser.chromium_or_skip()
    business = core.PROJECT_CLASS_PRESETS["business"]
    with browser.serve(core.app, PORT + 1) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            kept, asked = _switch(engine, base, "dismiss", TYPED)
            replaced, _ = _switch(engine, base, "accept", TYPED)
    # Не молча: окно было, и оно назвало оба поля с именем объекта.
    assert len(asked) == 1, f"смена класса не спросила про вписанное руками: {asked}"
    assert "Стартовая цена — МФОЦ / офисы" in asked[0], asked[0]
    assert classFieldLabel_of("landscaping_th_per_sqm") in asked[0], asked[0]
    # «Оставить» — ручное стоит, остальное взял класс.
    assert kept["offices_price_th_per_sqm"] == 777
    assert kept["landscaping_th_per_sqm"] == 42
    assert kept["apartment_price_th"] == business["apartment_price_th"]
    assert kept["project_class"] == "business"
    # «Заменить» — класс поставил свои числа.
    assert replaced["offices_price_th_per_sqm"] == business["offices_price_th_per_sqm"]
    assert replaced["landscaping_th_per_sqm"] == business["landscaping_th_per_sqm"]


def test_a_plain_class_switch_does_not_ask() -> None:
    # Без ручных правок смена класса — обычное действие, и окна нет.
    from playwright.sync_api import sync_playwright

    path = browser.chromium_or_skip()
    with browser.serve(core.app, PORT + 2) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            got, asked = _switch(engine, base, "dismiss", {})
    assert asked == []
    assert got["project_class"] == "business"


def classFieldLabel_of(key: str) -> str:  # noqa: N802 — имя по функции страницы
    return core._input_field_label(key)
