"""Рекомендация DevelopAid стоит в поле, а не только в подписи под ним.

Владелец (прод, 28.09.2026): кнопка у «Стартовая цена квартир» писала
«Подставлено: 639.8 тыс ₽/м² · наблюдений 7», а в поле оставалось 670 с
подписью «ставит класс проекта». Причина: поиск поля перебирал «id, name,
data-key, data-field», а обёртка поля с #533 носит `data-field` того же
ключа. Первым находился div, значение писалось в него, `onchange` поля не
срабатывал, а «Подставлено» писалось без проверки.

Проверяется отрисованная страница `main_registry` в Chromium, ответ
`/market/price-hint` подменён:

* число стоит и в видимом поле, и во вводных расчёта;
* у поля названо происхождение — «рекомендация DevelopAid», а не «класс»;
* оно переживает перерисовку вводных и смену класса;
* поле, перерисованное пока шёл запрос, всё равно получает число (узел,
  пойманный при вставке кнопки, к этому моменту уже не на странице);
* правка руками поверх рекомендации — снова «вписано руками»;
* если поле число не приняло, «Подставлено» не пишется, а названо, что
  осталось.

Запуск: python3 -m pytest tests/test_the_price_hint_lands_in_the_field.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import browser  # noqa: E402

PORT = 19417
HINT = {"available": True, "price_th_per_sqm": 639.8, "sample": 7,
        "observed_at": "2026-09-28", "basis": "peers"}

STATE = """()=>{
  const f=document.getElementById('f_apartment_price_th');
  const unit=f&&f.closest('.field').querySelector('.unit');
  const note=document.getElementById('daHintNote');
  return {field:f?f.value:null, held:inputs.apartment_price_th,
          unit:unit?unit.textContent:null, note:note?note.textContent:null};
}"""

PRESS = """async ()=>{
  const where=document.getElementById('cadastralNumbers');
  where.value='77:01:0004023:1000';
  document.getElementById('daHintBtn').click();
}"""


def _run(scenario):
    path = browser.chromium_or_skip()
    from playwright.sync_api import sync_playwright

    import main_registry  # noqa: PLC0415

    with browser.serve(main_registry.app, PORT) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            page = engine.new_page()
            page.on("dialog", lambda d: d.dismiss())
            return scenario(page, base)


def _open(page, base, answer=None):
    held = []

    def reply(route):
        if answer is not None:
            answer(route, held)
        else:
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(HINT))

    page.route("**/market/price-hint", reply)
    page.goto(base, wait_until="domcontentloaded")
    page.wait_for_function("()=>!!document.getElementById('daHintBtn')"
                           "&&!!document.getElementById('f_apartment_price_th')",
                           timeout=20000)
    return held


def _wait_note(page):
    page.wait_for_function(
        "()=>{const n=document.getElementById('daHintNote');"
        "return n&&n.textContent&&n.textContent!=='Считаю…'}", timeout=15000)


def test_the_recommendation_stands_in_the_field_and_survives_the_class():
    def scenario(page, base):
        _open(page, base)
        before = page.evaluate(STATE)
        page.evaluate(PRESS)
        _wait_note(page)
        pressed = page.evaluate(STATE)
        page.evaluate("()=>renderInputs()")
        redrawn = page.evaluate(STATE)
        # Другой класс: окно «заменить вписанное?» отклоняется — рекомендация
        # стоит на месте и после выбора класса.
        page.evaluate("()=>{const s=document.getElementById('projectClassSelect');"
                      "const other=s&&s.value==='business'?'comfort':'business';"
                      "applyProjectClassPreset(other);renderInputs()}")
        reclassed = page.evaluate(STATE)
        # Правка руками поверх рекомендации — уже не рекомендация.
        page.evaluate("()=>{const f=document.getElementById('f_apartment_price_th');"
                      "f.value='700';f.dispatchEvent(new Event('change',{bubbles:true}));"
                      "renderInputs()}")
        typed = page.evaluate(STATE)
        return before, pressed, redrawn, reclassed, typed

    before, pressed, redrawn, reclassed, typed = _run(scenario)
    assert float(before["field"]) != 639.8, before
    assert pressed["field"] == "639.8", pressed
    assert pressed["held"] == 639.8, pressed
    assert pressed["note"].startswith("Подставлено: 639.8"), pressed
    assert "рекомендация DevelopAid" in pressed["unit"], pressed
    assert "ставит класс" not in pressed["unit"], pressed
    for state in (redrawn, reclassed):
        assert state["field"] == "639.8" and state["held"] == 639.8, state
        assert "рекомендация DevelopAid от 28.09.2026" in state["unit"], state
    assert typed["field"] == "700" and typed["held"] == 700, typed
    assert "вписано руками" in typed["unit"], typed
    assert "рекомендация" not in typed["unit"], typed


def test_a_field_redrawn_during_the_request_still_gets_the_number():
    """Узел, найденный при вставке кнопки, к ответу уже снят со страницы."""

    def answer(route, held):
        held.append(route)

    def scenario(page, base):
        held = _open(page, base, answer)
        page.evaluate(PRESS)
        for _ in range(50):
            if held:
                break
            page.wait_for_timeout(100)
        assert held, "запрос /market/price-hint не ушёл"
        page.evaluate("()=>renderInputs()")
        held[0].fulfill(status=200, content_type="application/json",
                        body=json.dumps(HINT))
        _wait_note(page)
        return page.evaluate(STATE)

    state = _run(scenario)
    assert state["field"] == "639.8" and state["held"] == 639.8, state
    assert state["note"].startswith("Подставлено: 639.8"), state


def test_a_number_the_field_did_not_take_is_not_called_placed():
    def scenario(page, base):
        _open(page, base)
        # Поле, которое число не приняло во вводные: `onchange` снят.
        page.evaluate("()=>{document.getElementById('f_apartment_price_th').onchange=null}")
        page.evaluate(PRESS)
        _wait_note(page)
        return page.evaluate(STATE)

    state = _run(scenario)
    assert not state["note"].startswith("Подставлено"), state
    assert "639.8" in state["note"] and "не подставлен" in state["note"], state
    assert "расчёт держит" in state["note"], state


def test_the_market_panel_places_the_price_by_the_same_helper():
    """Панель «Рынок» пишет в то же поле тем же помощником, а не своей копией."""
    from market_search import ui, ui_v6

    assert ui.PRICE_FIELD_JS in ui._SCRIPT
    assert "mdPlaceApartmentPrice(valueTh" in ui._SCRIPT
    assert ui._SCRIPT.count("function mdApartmentPriceInput") == 1
    assert "mdPlaceApartmentPrice(payload.price_th_per_sqm" in ui_v6.PRICE_HINT_SCRIPT
    assert "mdSetNativeValue(input" not in ui_v6.PRICE_HINT_SCRIPT
