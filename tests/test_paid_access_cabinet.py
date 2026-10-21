"""Тарифы, мой доступ и администрирование — на странице и в боте.

Здесь закреплено:

- экран «Тарифы» — настоящий код страницы (`tariffsHtml`, стенд на node):
  цены и НДС «в том числе», остаток бесплатного, сроки участков, а оплата —
  кнопками только там, где сервер её включил, иначе — куда идти;
- кабинет и бот читают одни и те же права и условия (`/access/me`);
- администрирование — только администраторам; ручная выдача пишется в журнал
  с именем выдавшего;
- подвал несёт строку о регистрации программы из `docs/legal/product.json`,
  ссылки на договор и возврат.

Запуск: python3 -m pytest tests/test_paid_access_cabinet.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import page_blocks

import main as _wrapper

core = _wrapper.core
client = TestClient(core.app)
CHAT, ADMIN = 9090, 777
A1 = "50:20:0010101:31"


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:cabinet-test-token")
    monkeypatch.setenv("DEVELOPAID_ADMIN_IDS", str(ADMIN))
    monkeypatch.setenv("DEVELOPAID_ADMIN_KEY", "kluch")
    monkeypatch.setattr(core, "_MO_CALC_API_URL", "")
    yield


def me(chat: int = CHAT) -> dict:
    answer = client.post("/access/me", json={"session": core._telegram_session(chat, [])})
    assert answer.status_code == 200, answer.text
    return answer.json()


def tariffs(data: dict) -> str:
    prelude = "function escapeHtml(s){return String(s).replace(/</g,'&lt;')}"
    out, _ = page_blocks.run(prelude, f"console.log(tariffsHtml({json.dumps(data)}));")
    return out


def test_the_tariffs_screen_shows_prices_vat_and_my_plots():
    core.access_use(CHAT, core.access_plot(cadastral=[A1]))
    text = tariffs(me())
    assert "10 000 ₽" in text and "100 000 ₽" in text
    assert "в том числе НДС 5" in text
    assert "Бесплатных участков осталось: 0 из 1" in text
    assert A1 in text and "доступ до" in text
    # Ключей и оферты нет — кнопок оплаты нет, сказано, куда идти.
    assert "payForAccess" not in text and "напишите нам в бот" in text
    assert "свидетельство № 2026691589" in text


def test_payment_buttons_appear_only_when_the_server_enables_payment():
    data = me()
    data["payments_available"] = True
    text = tariffs(data)
    assert "payForAccess('plot')" in text and "payForAccess('subscription')" in text
    assert 'href="/offer"' in text and 'href="/refund"' in text


def test_a_visitor_without_login_is_told_to_log_in():
    data = client.post("/access/me", json={}).json()
    assert data["signed_in"] is False
    assert "войдите через Telegram" in tariffs(data)


def test_the_admin_section_is_for_admins_only():
    assert client.post("/access/admin/overview",
                       json={"session": core._telegram_session(CHAT, [])}).status_code == 403
    assert client.post("/access/admin/grant", json={
        "session": core._telegram_session(CHAT, []), "chat": CHAT, "cadastral": [A1]}).status_code == 403


def test_the_admin_grants_by_hand_and_sees_it():
    session = core._telegram_session(ADMIN, [])
    answer = client.post("/access/admin/grant", json={
        "session": session, "chat": CHAT, "kind": "plot", "cadastral": [A1], "days": 7,
        "note": "пилот"})
    assert answer.status_code == 200, answer.text
    plots = answer.json()["status"]["plots"]
    assert plots[0]["source"] == "admin" and plots[0]["active"]
    overview = client.post("/access/admin/overview", json={"key": "kluch"}).json()
    person = next(p for p in overview["people"] if p["chat"] == CHAT)
    assert person["active_plots"][0]["label"] == A1
    grant = next(r for r in overview["journal"] if r.get("chat") == CHAT)
    assert "администратор 777" in grant["note"] and "пилот" in grant["note"]
    assert me()["status"]["plots"][0]["source"] == "admin"


def test_the_bot_shows_the_same_tariffs(monkeypatch):
    sent: list[str] = []
    monkeypatch.setattr(_wrapper, "_send_message", lambda chat, text, **kw: sent.append(text))
    core.access_use(CHAT, core.access_plot(cadastral=[A1]))
    _wrapper._tariffs_message(CHAT)
    text = sent[-1]
    assert "10 000 ₽" in text and "в том числе НДС 5" in text
    assert "Бесплатных участков осталось: 0 из 1" in text and A1 in text


def test_the_bot_grant_is_for_admins(monkeypatch):
    sent: list[str] = []
    monkeypatch.setattr(_wrapper, "_send_message", lambda chat, text, **kw: sent.append(text))
    _wrapper._grant_command(CHAT, CHAT, f"{CHAT} 30 {A1}")
    assert "только администраторы" in sent[-1]
    _wrapper._grant_command(ADMIN, ADMIN, f"{CHAT} 30 подписка")
    assert "Доступ выдан" in sent[-1]
    assert core.access_status(CHAT)["subscription_active"]


def test_the_footer_names_the_registration_and_the_contract():
    page = core.PAGE
    footer = page[page.index("<footer"):page.index("</footer>")]
    assert core.product_registration_line() in footer
    assert 'href="/offer"' in footer and 'href="/refund"' in footer


def test_the_locked_economics_leads_to_the_tariffs():
    prelude = ("const box={style:{},innerHTML:''};"
               "const document={getElementById:()=>box};let lastResult=1,phaseBundle=1;")
    out, _ = page_blocks.run(prelude, "renderCalcLocked('Причина',402);console.log(box.innerHTML);")
    assert "openTariffs()" in out


def test_the_tariffs_open_on_the_drawn_page(monkeypatch, tmp_path):
    """Кнопка «Тарифы» видна в шапке и открывает кабинет с условиями — в браузере."""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import browser

    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    path = browser.chromium_or_skip()
    errors: list[str] = []
    with browser.serve(core.app, 18971) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            page = engine.new_page(viewport={"width": 1440, "height": 900})
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.goto(base, wait_until="networkidle")
            button = page.locator("#tariffsButton")
            assert button.is_visible()
            button.click()
            page.wait_for_function(
                "document.getElementById('tariffsBox').textContent.includes('Подписка')")
            text = page.locator("#tariffsBox").inner_text()
            assert page.locator("#projectsDialog").is_visible()
            footer = page.locator("footer").first.inner_text()
            page.close()
    assert "10 000 ₽" in text.replace(" ", " ") and "в том числе НДС 5" in text
    assert "войдите через Telegram" in text
    assert "свидетельство № 2026691589" in footer
    assert not errors, errors
