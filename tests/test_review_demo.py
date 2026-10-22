"""Публичные «Тарифы» и «Контакты» и демо-доступ по ссылке (клиенту, партнёру, ЮKassa).

Решение владельца 22.10.2026: проверяющему магазина нужно видеть без входа цены,
оферту, политику возврата и реквизиты, а в кабинете — как клиент входит и где
платит. Здесь закреплено:

- публичные страницы открываются без входа, реквизиты — из одного источника;
- демо-ссылка выдаётся и отзывается только администратором; отзыв гасит и
  уже выданную сессию;
- демо-пользователь — новый клиент: своих проектов нет, чужих не видит,
  админка закрыта;
- оплата в демо не берёт денег: тестовый магазин ЮKassa или пояснение, а
  тестовый платёж не открывает доступ настоящему человеку;
- в браузере ссылка ведёт в кабинет на «Тарифы и доступ».

Запуск: python3 -m pytest tests/test_review_demo.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as _wrapper  # noqa: E402

core = _wrapper.core
client = TestClient(core.app)
OWNER = 777


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:review-demo-test-token")
    monkeypatch.setenv("DEVELOPAID_ADMIN_IDS", str(OWNER))
    monkeypatch.setenv("DEVELOPAID_ADMIN_KEY", "kluch")
    monkeypatch.delenv("YOOKASSA_TEST_SHOP_ID", raising=False)
    monkeypatch.delenv("YOOKASSA_TEST_SECRET_KEY", raising=False)
    monkeypatch.setattr(core, "_MO_CALC_API_URL", "")
    core._DEMO_ALIVE_CACHE.clear()
    yield


def invite() -> str:
    answer = client.post("/access/admin/demo/create", json={"key": "kluch", "note": "ЮKassa"})
    assert answer.status_code == 200, answer.text
    return answer.json()["code"]


def claim(code: str) -> str:
    answer = client.post("/demo/claim", json={"code": code})
    assert answer.status_code == 200, answer.text
    return answer.json()["session"]


# --- публичные страницы ---------------------------------------------------------

def test_the_public_pages_open_without_login():
    tariffs = client.get("/tariffs")
    assert tariffs.status_code == 200
    text = tariffs.text
    assert "10 000 ₽" in text and "100 000 ₽" in text
    assert "в том числе НДС 5" in text and "30 дней" in text
    assert 'href="/offer"' in text and 'href="/refund"' in text and 'href="/contacts"' in text
    assert "свидетельство № 2026691589" in text
    contacts = client.get("/contacts").text
    seller = core.seller_info()
    for value in (seller["inn"], seller["ogrnip"], seller["email"], seller["name"]):
        assert value and value in contacts
    # Заготовка оферты помечена явно, а не выдана за договор.
    assert "Заготовка." in client.get("/offer").text
    assert "Заготовка." in client.get("/refund").text


def test_the_footer_leads_to_the_tariffs_and_contacts():
    page = core.PAGE
    footer = page[page.index("<footer"):page.index("</footer>")]
    assert 'href="/tariffs"' in footer and 'href="/contacts"' in footer


# --- демо-доступ ---------------------------------------------------------------

def test_only_an_admin_issues_and_revokes_a_demo_link():
    stranger = core._telegram_session(5050, [])
    assert client.post("/access/admin/demo/create", json={"session": stranger}).status_code == 403
    code = invite()
    assert client.post("/access/admin/demo/revoke",
                       json={"session": stranger, "code": code}).status_code == 403


def test_a_demo_link_opens_a_new_client_cabinet_without_the_admin():
    session = claim(invite())
    me = client.post("/access/me", json={"session": session}).json()
    assert me["signed_in"] and me["demo"] and not me["is_admin"]
    assert me["status"]["free_left"] == 1, "демо — новый клиент"
    assert client.post("/access/admin/overview", json={"session": session}).status_code == 403
    assert client.post("/access/admin/demo/list", json={"session": session}).status_code == 403


def test_a_demo_user_does_not_see_other_projects():
    core.project_save(OWNER, "Проект владельца", {"inputs": {}})
    assert core.project_list(OWNER), "чужой проект на месте"
    session = claim(invite())
    listed = client.post("/projects/list", json={"session": session})
    assert listed.status_code == 200
    assert listed.json()["projects"] == []


def test_a_revoked_link_closes_the_session_too():
    code = invite()
    session = claim(code)
    assert core._web_identity_chat_id(session)
    client.post("/access/admin/demo/revoke", json={"key": "kluch", "code": code})
    assert core._web_identity_chat_id(session) == 0
    refused = client.post("/demo/claim", json={"code": code})
    assert refused.status_code == 410 and "отозвана" in refused.json()["detail"]
    assert client.post("/access/me", json={"session": session}).json()["signed_in"] is False


def test_demo_payment_shows_the_form_without_charging():
    session = claim(invite())
    answer = client.post("/payments/create", json={"session": session, "kind": "plot",
                                                   "cadastral": ["50:20:0010101:1"],
                                                   "email": "check@yookassa.ru"})
    assert answer.status_code == 200, answer.text
    data = answer.json()
    assert data["preview"] is True and "деньги не списываются" in data["message"]
    assert "10 000 ₽" in data["message"]


def test_with_test_keys_the_demo_pays_in_the_test_shop(monkeypatch):
    monkeypatch.setenv("YOOKASSA_TEST_SHOP_ID", "test-shop")
    monkeypatch.setenv("YOOKASSA_TEST_SECRET_KEY", "test-secret")
    calls: list[tuple] = []

    def fake_call(method, path, body=None, idempotence_key="", test=False):
        calls.append((method, test, body))
        return {"id": "2f6c1a2b-000f-5000-8000-1a2b3c4d5e6f", "status": "pending",
                "confirmation": {"confirmation_url": "https://yoomoney.ru/test"}}

    monkeypatch.setattr(core, "_yookassa_call", fake_call)
    session = claim(invite())
    answer = client.post("/payments/create", json={"session": session, "kind": "subscription",
                                                   "email": "check@yookassa.ru"})
    assert answer.status_code == 200, answer.text
    assert calls and calls[0][1] is True, "демо платит только тестовым магазином"
    assert calls[0][2]["metadata"]["demo"] == "1"


def test_a_test_payment_never_opens_a_real_client():
    paid = {"id": "x", "status": "succeeded", "paid": True,
            "amount": {"value": "100000.00", "currency": "RUB"},
            "metadata": {"chat": "4242", "kind": "subscription", "days": "30",
                         "price": "100000", "demo": "1"}}
    result = core.payment_apply(paid)
    assert result["granted"] is False and "демо" in result["reason"]
    assert not core.access_status(4242)["subscription_active"]


# --- на отрисованной странице -----------------------------------------------------

def test_the_demo_link_leads_into_the_cabinet_in_a_browser():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import browser

    code = invite()
    path = browser.chromium_or_skip()
    errors: list[str] = []
    with browser.serve(core.app, 18973) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            page = engine.new_page(viewport={"width": 1280, "height": 900})
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            # Публичные страницы — без входа, с подвалом.
            page.goto(f"{base}/tariffs")
            assert "Тарифы DevelopAid" in page.inner_text("h1")
            assert page.locator("footer a[href='/contacts']").count() == 1
            page.goto(f"{base}/demo/{code}")
            assert "вход через Telegram" in page.inner_text("body").replace("«Войти через Telegram»", "вход через Telegram")
            page.click("#demoEnter")
            page.wait_for_function(
                "document.getElementById('tariffsBox') && "
                "document.getElementById('tariffsBox').textContent.includes('Это демо-доступ')",
                timeout=60_000)
            assert page.locator("#projectsDialog").is_visible()
            assert not page.locator("#accessAdminBox").is_visible()
            page.fill("#payEmail", "check@yookassa.ru")
            page.click("button:has-text('Оформить подписку')")
            page.wait_for_function(
                "document.getElementById('payStatus').textContent.includes('деньги не списываются')")
            page.close()
    assert not errors, errors
