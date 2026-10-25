"""Плашка доступа над расчётом: какой участок, бесплатный ли, сколько осталось,
что он стоит — и оплата прямо там (решение владельца 25.10.2026).

Здесь закреплено:

- бесплатный участок с сайта тратится только кнопкой «Посчитать бесплатно»
  (`use_free` → `free_consent`): расчёт без неё отвечает `free_offer` и ничего
  не тратит, а бот и мини-приложение тратят его сами, как прежде;
- `/access/check` — то же решение `calc_access_for_chat` без списания: смотреть
  условия не значит тратить бесплатный участок или запас;
- на отрисованной странице: плашка бесплатного участка с остатком, кнопка
  открывает расчёт и строку «открыт бесплатно до…»; следующий участок — плашка
  с ценами и кнопками оплаты, вердикт прежнего участка под ней не виден,
  оплата уходит с текущими вводными.

Запуск: python3 -m pytest tests/test_paid_access_plaque.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as _wrapper

core = _wrapper.core
client = TestClient(core.app)
CHAT = 7171
A1, B = "50:20:0010101:41", "50:20:0010101:42"
MODEL = {"tep": {k: dict(v) for k, v in core.TEP_DEFAULT.items()}, "rates": []}


@pytest.fixture(autouse=True)
def paywall(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:plaque-test-token")
    monkeypatch.setenv("DEVELOPAID_ADMIN_IDS", "777")
    monkeypatch.delenv("DEVELOPAID_FREE_PLOTS", raising=False)
    monkeypatch.setenv("DEVELOPAID_PAYWALL", "1")
    monkeypatch.setattr(core, "_MO_CALC_API_URL", "")
    core._ACCESS_REMOTE_CACHE.clear()
    yield


def session(chat: int = CHAT) -> str:
    return core._telegram_session(chat, [])


def inputs_for(number: str) -> dict:
    return {**core.DEFAULT_INPUTS, "cadastral_numbers": number}


def check(number: str) -> dict:
    answer = client.post("/access/check", json={"session": session(), "inputs": inputs_for(number)})
    assert answer.status_code == 200, answer.text
    return answer.json()


def calculate(number: str, **extra) -> object:
    return client.post("/calculate", json={**MODEL, "inputs": inputs_for(number),
                                           "session": session(), **extra})


def test_looking_at_the_conditions_spends_nothing():
    first = check(A1)
    assert first["code"] == "free_offer" and not first["allowed"]
    assert first["free_left"] == 1 and first["plot"]["label"] == A1
    assert first["terms"]["plot_price_rub"] == 10000
    check(A1)
    assert core.access_status(CHAT)["free_left"] == 1


def test_the_site_spends_the_free_plot_only_by_the_button():
    refused = calculate(A1)
    assert refused.status_code == 402 and "Посчитать бесплатно" in refused.json()["detail"]
    assert core.access_status(CHAT)["free_left"] == 1
    opened = calculate(A1, use_free=True)
    assert opened.status_code == 200, opened.text[:300]
    access = opened.json()["access"]
    assert access["basis"] == "free" and access["free_left"] == 0 and access["plot"]["label"] == A1
    # Открытый участок пересчитывается уже без кнопки.
    assert calculate(A1).status_code == 200
    # Кнопка не покупает: бесплатных больше нет — следующий участок платный.
    assert calculate(B, use_free=True).status_code == 402
    paid = check(B)
    assert paid["code"] == "paid_needed" and paid["plot"]["label"] == B


def test_the_bot_still_spends_the_free_plot_by_itself():
    decision = core.calc_access_for_chat(CHAT, "Отчёт в Telegram", cadastral=[A1], surface="bot")
    assert decision["allowed"] and decision["basis"] == "free"


def test_the_reserve_is_not_bound_by_a_look():
    core.access_use(CHAT, core.access_plot(cadastral=[A1]))
    core.access_grant(CHAT, reserve=2, payment_id="pay-plaque")
    look = check(B)
    assert look["allowed"] and look["code"] == "reserve_granted"
    assert core.access_status(CHAT)["reserve"] == 2


def test_the_core_answers_a_look_without_writing():
    plot = core.access_plot(cadastral=[A1])
    body = {"chat": CHAT, "cadastral": [A1], "key": plot["key"], "label": plot["label"],
            "kind": "cadastral", "surface": "site", "free_consent": True, "spend": False,
            "sign": core._access_sign(plot["key"], CHAT)}
    answer = client.post("/internal/access/use", json=body).json()
    assert answer["allowed"] and answer["code"] == "free_granted"
    assert core.access_status(CHAT)["free_left"] == 1


def _plaque_text(page) -> str:
    page.wait_for_function("document.getElementById('calcLocked').style.display!=='none'"
                           "&&document.getElementById('calcLocked').querySelector('h3')"
                           "&&!/закрыта/.test(document.getElementById('calcLocked').querySelector('h3').textContent)")
    return page.inner_text("#calcLocked").replace("\xa0", " ")


def test_the_plaque_on_the_drawn_page(monkeypatch):
    """Путь посетителя после входа: бесплатный участок кнопкой, второй — оплата
    прямо в плашке. Главная страница — со слоем IA, как у посетителя."""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import browser

    import main_registry

    monkeypatch.setattr(core, "payments_available", lambda: True)
    path = browser.chromium_or_skip()
    errors: list[str] = []
    paid: list[dict] = []

    def fake_payment(route):
        paid.append(json.loads(route.request.post_data or "{}"))
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps({"preview": True, "message": "Здесь откроется форма оплаты."}))

    with browser.serve(main_registry.app, 18993) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            page = engine.new_page(viewport={"width": 1440, "height": 1000})
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.route("**/payments/create", fake_payment)
            page.add_init_script(
                f"localStorage.setItem('developaid_web_session', {json.dumps(session())})")
            page.goto(base, wait_until="networkidle")
            page.add_style_tag(content="#profileDialog{display:none!important}")
            page.click(".ia-nav button:has-text('Результат')")
            page.evaluate(f"()=>{{inputs.cadastral_numbers={json.dumps(A1)};return calculate()}}")
            free = _plaque_text(page)
            assert core.access_status(CHAT)["free_left"] == 1
            page.click("#calcUseFree")
            page.wait_for_function("document.getElementById('calcLocked').style.display==='none'")
            browser.wait_for_result(page)
            line = page.inner_text("#calcAccessLine")
            assert page.locator("#iaVerdict").is_visible()

            page.evaluate(f"()=>{{inputs.cadastral_numbers={json.dumps(B)};return calculate()}}")
            plaque = _plaque_text(page)
            stale_hidden = not page.locator("#iaVerdict").is_visible() \
                and not page.locator("#report .report-hero").is_visible()
            state = page.inner_text("#iaStateText")
            page.fill("#calcPayEmail", "buyer@example.com")
            page.click("#calcLocked button:has-text('Оплатить участок')")
            page.wait_for_function("document.getElementById('calcPayStatus').textContent.length>0")
            status = page.inner_text("#calcPayStatus")
            page.close()
    assert "Этот участок можно посчитать бесплатно" in free and A1 in free
    assert "осталось бесплатных участков: 1 из 1" in free
    assert "открыт бесплатно до" in line and "осталось: 0" in line
    assert "Этот участок — платный" in plaque and B in plaque
    assert "10 000 ₽" in plaque and "100 000 ₽" in plaque
    assert "расчёт запустится сам" in plaque
    assert stale_hidden, "под плашкой виден вердикт прежнего участка"
    assert "актуален" not in state
    assert status == "Здесь откроется форма оплаты."
    assert paid and paid[0]["kind"] == "plot" and paid[0]["count"] == 1
    assert paid[0]["email"] == "buyer@example.com"
    assert paid[0]["inputs"]["cadastral_numbers"] == B
    assert not errors, errors
