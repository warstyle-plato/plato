"""Число, вписанное руками после рекомендации, — то, что идёт в расчёт.

Владелец (прод 0.25.23): «Человек нажал рекомендацию цены и потом ввёл руками
цифру больше. Но она не вернулась. Подставленные 951 так и остались в
расчёте».

Путь найден в отрисованной странице. Кнопка «Рекомендация DevelopAid» пишет в
то же поле `f_apartment_price_th` (через его `onchange` — во вводные и в
расчёт) и помечает происхождение. Ответ `/market/price-hint` идёт секунды
(Пульс), а поле в это время открыто: человек вписывал 1300, расчёт уходил с
1300 — и тут приходил ответ на нажатие и писал 951 поверх ручного числа. В
поле, во вводных, в расчёте и в сохранённом состоянии оставалась
рекомендация.

Второй путь к тому же итогу: расчёт зовётся каждой правкой, ответы приходят в
любом порядке, и опоздавший ответ по 951 перерисовывал отчёт поверх ответа по
1300 — в поле 1300, в итоге выручка по 951.

Проверяется отрисованная страница `main_registry` в Chromium, ввод — с
клавиатуры в открытой группе вводных, ответ подсказки подменён:

* ответ, пришедший после ручного ввода, поле не перебивает: в поле, во
  вводных, в последнем `/calculate` и в сохранённом состоянии — 1300, а
  подпись говорит, почему ориентир не подставлен;
* обычный порядок: нажатие ставит 951 в поле и в расчёт, ручные 1300 идут в
  расчёт, у поля сразу «вписано руками», а не «рекомендация», и это переживает
  перезагрузку;
* опоздавший ответ расчёта по 951 итог не перерисовывает.

Запуск: python3 -m pytest tests/test_a_typed_price_outlives_the_recommendation.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import browser  # noqa: E402

PORT = 19437
HINT = {"available": True, "price_th_per_sqm": 951, "sample": 7,
        "observed_at": "2026-09-28", "basis": "peers"}

STATE = """()=>{
  const f=document.getElementById('f_apartment_price_th');
  const unit=f&&f.closest('.field').querySelector('.unit');
  const note=document.getElementById('daHintNote');
  let stored=null;
  try{stored=JSON.parse(localStorage.getItem('plato_v04')).inputs.apartment_price_th}catch(e){}
  return {field:f?f.value:null, held:inputs.apartment_price_th,
          unit:unit?unit.textContent:null, note:note?note.textContent:null,
          stored:stored, saved:projectStorePayload().payload.inputs.apartment_price_th,
          result:lastResult&&lastResult.summary?lastResult.summary.average_apartment_price_th:null};
}"""


def _run(scenario):
    path = browser.chromium_or_skip()
    from playwright.sync_api import sync_playwright

    import main_registry  # noqa: PLC0415

    with browser.serve(main_registry.app, PORT) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            page = engine.new_page(viewport={"width": 1400, "height": 900})
            page.on("dialog", lambda d: d.dismiss())
            return scenario(page, base)


class Calls:
    """Что уходило в `/calculate` и что вернулось на каждую цену."""

    def __init__(self, page, hold_price=None):
        self.sent = []
        self.answers = {}
        self.held = []
        self.hold_price = hold_price

        def handle(route):
            body = json.loads(route.request.post_data or "{}")
            price = body.get("inputs", {}).get("apartment_price_th")
            self.sent.append(price)
            response = route.fetch()
            payload = response.json()
            self.answers[price] = payload["summary"]["average_apartment_price_th"]
            if self.hold_price is not None and price == self.hold_price:
                self.held.append((route, response))
                return
            route.fulfill(response=response)

        page.route("**/calculate", handle)

    def release(self):
        for route, response in self.held:
            route.fulfill(response=response)
        self.held = []


def _open(page, base, hint_route):
    page.route("**/market/price-hint", hint_route)
    page.goto(base, wait_until="domcontentloaded")
    page.wait_for_function("()=>!!document.getElementById('daHintBtn')"
                           "&&!!document.getElementById('f_apartment_price_th')",
                           timeout=20000)
    page.wait_for_timeout(800)
    # Как человек: «Экономика», группа с ценой открыта.
    page.get_by_text("Экономика", exact=True).first.click()
    page.evaluate("()=>{document.getElementById('f_apartment_price_th')"
                  ".closest('details').open=true;"
                  "document.getElementById('cadastralNumbers').value='77:01:0004023:1000'}")


def _type_price(page, text):
    field = page.locator("#f_apartment_price_th")
    field.click()
    field.press("Control+A")
    field.type(text)
    field.press("Tab")


def _settle(page, calls, count):
    for _ in range(100):
        if len(calls.sent) >= count and not page.evaluate(
                "()=>!!document.querySelector('#iaState')&&/Считаю/.test(document.getElementById('iaStateText').textContent)"):
            break
        page.wait_for_timeout(100)
    page.wait_for_timeout(400)


def _reload(page):
    page.reload(wait_until="domcontentloaded")
    page.wait_for_function("()=>!!document.getElementById('f_apartment_price_th')", timeout=20000)
    page.wait_for_timeout(1000)
    return page.evaluate(STATE)


def test_a_recommendation_answered_after_typing_does_not_overwrite_it():
    def scenario(page, base):
        held = []
        _open(page, base, lambda route: held.append(route))
        calls = Calls(page)
        page.locator("#daHintBtn").click()
        for _ in range(50):
            if held:
                break
            page.wait_for_timeout(100)
        assert held, "запрос /market/price-hint не ушёл"
        _type_price(page, "1300")
        _settle(page, calls, 1)
        held[0].fulfill(status=200, content_type="application/json", body=json.dumps(HINT))
        page.wait_for_function("()=>!/Считаю/.test(document.getElementById('daHintNote').textContent)",
                               timeout=15000)
        page.wait_for_timeout(1500)
        return page.evaluate(STATE), list(calls.sent), dict(calls.answers), _reload(page)

    state, sent, answers, reloaded = _run(scenario)
    assert state["field"] == "1300" and state["held"] == 1300, state
    assert sent and sent[-1] == 1300, sent
    assert 951 not in sent, sent
    assert state["result"] == answers[1300], (state, answers)
    assert state["saved"] == 1300 and state["stored"] == 1300, state
    assert "951" in state["note"] and "не подставлен" in state["note"], state
    assert "рекомендация" not in state["unit"], state
    assert reloaded["field"] == "1300" and reloaded["held"] == 1300, reloaded


def test_typing_over_the_recommendation_goes_to_the_calculation_and_stays():
    def scenario(page, base):
        _open(page, base, lambda route: route.fulfill(
            status=200, content_type="application/json", body=json.dumps(HINT)))
        calls = Calls(page)
        page.locator("#daHintBtn").click()
        page.wait_for_function("()=>/Подставлено/.test(document.getElementById('daHintNote').textContent)",
                               timeout=15000)
        _settle(page, calls, 1)
        pressed = page.evaluate(STATE)
        _type_price(page, "1300")
        _settle(page, calls, 2)
        typed = page.evaluate(STATE)
        return pressed, typed, list(calls.sent), dict(calls.answers), _reload(page)

    pressed, typed, sent, answers, reloaded = _run(scenario)
    assert pressed["field"] == "951" and pressed["held"] == 951, pressed
    assert sent[0] == 951 and pressed["result"] == answers[951], (sent, pressed)
    assert "рекомендация DevelopAid" in pressed["unit"], pressed

    assert typed["field"] == "1300" and typed["held"] == 1300, typed
    assert sent[-1] == 1300, sent
    assert typed["result"] == answers[1300], (typed, answers)
    assert typed["saved"] == 1300 and typed["stored"] == 1300, typed
    # Без перерисовки: подпись у поля и ответ кнопки уже не выдают ручное
    # число за рекомендацию.
    assert "вписано руками" in typed["unit"] and "рекомендация" not in typed["unit"], typed
    assert not typed["note"].startswith("Подставлено"), typed
    assert "1300" in typed["note"], typed

    assert reloaded["field"] == "1300" and reloaded["held"] == 1300, reloaded
    assert "вписано руками" in reloaded["unit"], reloaded


def test_a_late_calculation_of_the_recommendation_does_not_redraw_the_result():
    def scenario(page, base):
        _open(page, base, lambda route: route.fulfill(
            status=200, content_type="application/json", body=json.dumps(HINT)))
        calls = Calls(page, hold_price=951)
        page.locator("#daHintBtn").click()
        page.wait_for_function("()=>/Подставлено/.test(document.getElementById('daHintNote').textContent)",
                               timeout=15000)
        for _ in range(100):
            if calls.held:
                break
            page.wait_for_timeout(100)
        assert calls.held, "расчёт по рекомендации не ушёл"
        _type_price(page, "1300")
        for _ in range(100):
            if 1300 in calls.answers:
                break
            page.wait_for_timeout(100)
        page.wait_for_timeout(800)
        calls.release()
        page.wait_for_timeout(1500)
        return page.evaluate(STATE), dict(calls.answers)

    state, answers = _run(scenario)
    assert answers[951] != answers[1300], answers
    assert state["field"] == "1300" and state["held"] == 1300, state
    assert state["result"] == answers[1300], (state, answers)
