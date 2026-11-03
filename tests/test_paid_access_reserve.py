"""Несколько участков вперёд: пакет, запас и его трата.

Решение владельца 23.10.2026: пакет из N участков стоит N × цена участка (без
скидки). Текущий участок открывается сразу, остальные ложатся в запас; без
текущего участка весь пакет — в запас. Участок из запаса привязывается при
первом расчёте участка без действующего права — после бесплатного и до
отказа «нужна оплата» — на 30 дней от момента привязки.

Здесь закреплено:

- пакет из 3: текущий участок открыт, 2 в запасе, чек — одна позиция
  quantity=3 по цене участка, сумма 30 000 ₽;
- первый расчёт нового участка берёт участок из запаса и пишет журнал; при
  пустом запасе — отказ со словами про оплату;
- подписка запас не тратит; повтор уведомления ЮKassa запас не удваивает;
- тестовый магазин кладёт запас только демо-пользователю;
- Render передаёт запас на ядро с подписью, подделанное число — отказ;
- кабинет (настоящий `tariffsHtml`), бот и админ-форма показывают и выдают
  запас; тексты возврата и оферты о нём говорят;
- на отрисованной странице (Chromium): поле «Сколько участков», сумма в
  строке «К оплате», после оплаты — «В запасе участков: 2».

Запуск: python3 -m pytest tests/test_paid_access_reserve.py -q
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
CHAT, ADMIN = 7070, 777
FREE, A1, B, C, D = ("50:20:0010101:40", "50:20:0010101:41", "50:20:0010101:42",
                     "50:20:0010101:43", "50:20:0010101:44")
PAY_ID = "2f6c1a2b-000f-5000-8000-7a7b7c7d7e7f"
YOOKASSA_IP = "185.71.76.5"


@pytest.fixture()
def shop(monkeypatch, tmp_path):
    """Магазин ЮKassa без сети: платёж создаётся и перечитывается из памяти."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:reserve-test-token")
    monkeypatch.setenv("YOOKASSA_SHOP_ID", "100500")
    monkeypatch.setenv("YOOKASSA_SECRET_KEY", "test_secret")
    monkeypatch.setenv("DEVELOPAID_ADMIN_IDS", str(ADMIN))
    monkeypatch.setenv("DEVELOPAID_ADMIN_KEY", "kluch")
    monkeypatch.setenv("DEVELOPAID_PAYWALL", "1")
    monkeypatch.setattr(core, "_MO_CALC_API_URL", "")
    core._ACCESS_REMOTE_CACHE.clear()
    legal = tmp_path / "legal"
    legal.mkdir()
    (legal / "product.json").write_text(
        (core._LEGAL_DIR / "product.json").read_text(encoding="utf-8"), encoding="utf-8")
    (legal / "offer.md").write_text("# Оферта\n\nТекст владельца.", encoding="utf-8")
    (legal / "refund.md").write_text("# Возврат\n\nТекст владельца.", encoding="utf-8")
    monkeypatch.setattr(core, "_LEGAL_DIR", legal)
    store: dict[str, dict] = {}
    calls: list[tuple] = []
    state = {"confirmation_url": "https://yoomoney.ru/pay/x"}

    def fake_call(method, path, body=None, idempotence_key="", test=False):
        calls.append((method, path, body, idempotence_key, test))
        if method == "POST":
            payment = {"id": PAY_ID, "status": "pending", "paid": False,
                       "amount": body["amount"], "metadata": body["metadata"],
                       "confirmation": {"confirmation_url": state["confirmation_url"]}}
            store[PAY_ID] = payment
            return payment
        return dict(store[path.rsplit("/", 1)[-1]])

    monkeypatch.setattr(core, "_yookassa_call", fake_call)
    return {"store": store, "calls": calls, "state": state}


def client(ip: str = YOOKASSA_IP) -> TestClient:
    return TestClient(core.app, client=(ip, 50000))


def session(chat: int = CHAT) -> str:
    return core._telegram_session(chat, [])


def create(count: int, cadastral: list[str] | None = None, chat: int = CHAT) -> dict:
    answer = client().post("/payments/create", json={
        "session": session(chat), "kind": "plot", "count": count,
        "cadastral": cadastral or [], "email": "buyer@example.ru"})
    assert answer.status_code == 200, answer.text
    return answer.json()


def pay(shop) -> None:
    shop["store"][PAY_ID].update(status="succeeded", paid=True)


def webhook():
    return client().post("/payments/yookassa/webhook", json={
        "type": "notification", "event": "payment.succeeded",
        "object": {"id": PAY_ID, "status": "succeeded", "paid": True}})


def buy_package(shop, count: int = 3, cadastral: list[str] | None = None) -> dict:
    created = create(count, cadastral)
    pay(shop)
    assert webhook().json()["granted"] is True
    return created


def use(number: str, chat: int = CHAT) -> dict:
    return core.access_use(chat, core.access_plot(cadastral=[number]), surface="test")


def journal(chat: int = CHAT) -> list[dict]:
    return [row for row in core.access_journal_read(500) if row.get("chat") == chat]


# --- покупка пакета -----------------------------------------------------------

def test_a_package_of_three_opens_the_current_plot_and_keeps_two_in_reserve(shop):
    created = buy_package(shop, 3, [A1])
    assert created["price_rub"] == 30000 and created["count"] == 3
    _method, path, body, _key, test = shop["calls"][0]
    assert path == "/payments" and test is False
    # Сумма — три участка по цене участка; чек — одна позиция quantity=3 по
    # цене за единицу (items[].amount у ЮKassa — цена единицы).
    assert body["amount"] == {"value": "30000.00", "currency": "RUB"}
    item = body["receipt"]["items"][0]
    assert len(body["receipt"]["items"]) == 1
    assert item["quantity"] == "3.00" and item["amount"] == {"value": "10000.00", "currency": "RUB"}
    assert item["vat_code"] == 7
    assert "к 3 участкам" in body["description"] and len(body["description"]) <= 128
    assert body["metadata"]["count"] == "3" and body["metadata"]["price"] == "30000"
    assert body["metadata"]["plot_key"] == f"cad:{A1}"
    status = core.access_status(CHAT)
    assert status["reserve"] == 2
    assert [p["label"] for p in status["plots"] if p["active"]] == [A1]
    assert status["plots"][0]["source"] == "payment"
    assert status["reserve_items"][0]["payment_id"] == PAY_ID
    assert status["reserve_items"][0]["happened_at"] > 0
    reserved = [row for row in journal() if row.get("event") == "reserve"]
    assert len(reserved) == 1 and reserved[0]["count"] == 2 and reserved[0]["payment_id"] == PAY_ID
    assert use(A1)["basis"] == "payment"


def test_the_first_calculation_of_a_new_plot_takes_one_from_the_reserve(shop):
    assert use(FREE)["basis"] == "free"
    buy_package(shop, 3, [A1])
    decision = use(B)
    assert decision["allowed"] and decision["basis"] == "reserve"
    assert decision["code"] == "reserve_granted" and decision["reserve_left"] == 1
    terms = core.access_terms()
    assert abs(decision["until"] - (core.time.time() + terms["plot_days"] * 86400)) < 60
    status = core.access_status(CHAT)
    assert status["reserve"] == 1
    bound = next(p for p in status["plots"] if p["label"] == B)
    assert bound["active"] and bound["source"] == "reserve"
    record = core._access_load(CHAT)
    grant = next(g for g in record["grants"] if g["key"] == f"cad:{B}")
    assert grant["payment_id"] == PAY_ID and grant["source"] == "reserve"
    rows = [row for row in journal() if row.get("event") == "grant" and row.get("source") == "reserve"]
    assert len(rows) == 1 and rows[0]["key"] == f"cad:{B}" and rows[0]["reserve_left"] == 1
    assert rows[0]["payment_id"] == PAY_ID and rows[0]["surface"] == "test"
    # Повторный расчёт того же участка запас не трогает.
    again = use(B)
    assert again["code"] == "plot" and again["basis"] == "reserve"
    assert core.access_status(CHAT)["reserve"] == 1
    # Та же выдача видна маршруту расчёта: единственное решение — `access_use`.
    assert core.calc_access_for_chat(CHAT, "Расчёт", cadastral=[C])["basis"] == "reserve"
    assert core.access_status(CHAT)["reserve"] == 0


def test_the_free_plot_goes_first_and_an_expired_plot_takes_from_the_reserve(shop):
    buy_package(shop, 2, [A1])
    # Бесплатный участок ещё не потрачен — он идёт раньше запаса.
    assert use(FREE)["basis"] == "free"
    assert core.access_status(CHAT)["reserve"] == 1
    # Участок с закончившимся сроком — без действующего права: берёт из запаса.
    with core._access_locked(CHAT):
        record = core._access_load(CHAT)
        for grant in record["grants"]:
            if grant["key"] == f"cad:{FREE}":
                grant["until"] = core.time.time() - 10
        core._access_store(CHAT, record)
    renewed = use(FREE)
    assert renewed["basis"] == "reserve" and core.access_status(CHAT)["reserve"] == 0


def test_an_empty_reserve_refuses_with_the_payment_words(shop):
    assert use(FREE)["basis"] == "free"
    buy_package(shop, 3, [A1])
    assert use(B)["basis"] == "reserve" and use(C)["basis"] == "reserve"
    assert core.access_status(CHAT)["reserve"] == 0
    refused = use(D)
    assert not refused["allowed"] and refused["code"] == "paid_needed"
    words = refused["detail"].replace("\u00a0", " ")
    assert "Бесплатный участок уже использован" in words
    assert "оплатите доступ" in words and "10 000 ₽" in words and "Тарифы" in words
    with pytest.raises(core.HTTPException) as refusal:
        core.calc_access_for_chat(CHAT, "Расчёт", cadastral=[D])
    assert refusal.value.status_code == 402
    assert [r["code"] for r in journal() if r.get("event") == "refuse"] == ["paid_needed"] * 2


def test_a_subscription_does_not_spend_the_reserve(shop):
    buy_package(shop, 3, [A1])
    core.access_grant(CHAT, subscription=True, source="admin")
    assert use(B)["basis"] == "subscription"
    assert use(C)["basis"] == "subscription"
    assert core.access_status(CHAT)["reserve"] == 2


def test_a_repeated_notification_does_not_double_the_reserve(shop):
    buy_package(shop, 3, [A1])
    assert webhook().status_code == 200
    client().post("/payments/status", json={"session": session(), "payment_id": PAY_ID})
    status = core.access_status(CHAT)
    assert status["reserve"] == 2 and len(status["plots"]) == 1
    assert len([r for r in journal() if r.get("event") == "reserve"]) == 1


def test_a_package_without_a_current_plot_goes_entirely_to_reserve(shop):
    created = create(3)
    assert created["count"] == 3
    body = shop["calls"][0][2]
    assert "plot_key" not in body["metadata"] and body["metadata"]["count"] == "3"
    pay(shop)
    assert webhook().json()["granted"] is True
    status = core.access_status(CHAT)
    assert status["reserve"] == 3 and status["plots"] == []
    assert use(FREE)["basis"] == "free"
    assert use(B)["basis"] == "reserve" and core.access_status(CHAT)["reserve"] == 2


def test_one_plot_without_a_current_plot_is_refused_as_before(shop):
    answer = client().post("/payments/create", json={
        "session": session(), "kind": "plot", "count": 1, "email": "buyer@example.ru"})
    assert answer.status_code == 400 and "за какой участок" in answer.json()["detail"]
    for count in (0, 11, "много"):
        answer = client().post("/payments/create", json={
            "session": session(), "kind": "plot", "count": count, "cadastral": [A1],
            "email": "buyer@example.ru"})
        assert answer.status_code in {400, 422}, count
    assert not shop["calls"]


def test_a_tampered_count_or_sum_grants_nothing(shop):
    create(3, [A1])
    pay(shop)
    shop["store"][PAY_ID]["amount"] = {"value": "10000.00", "currency": "RUB"}
    assert webhook().json()["granted"] is False
    assert core.access_status(CHAT)["reserve"] == 0 and core.access_status(CHAT)["plots"] == []
    shop["store"][PAY_ID]["amount"] = {"value": "30000.00", "currency": "RUB"}
    shop["store"][PAY_ID]["metadata"]["count"] = "7"
    assert webhook().json()["granted"] is False
    assert core.access_status(CHAT)["reserve"] == 0


def test_a_test_payment_puts_the_reserve_only_to_the_demo_user(shop):
    paid = {"id": "x", "status": "succeeded", "paid": True,
            "amount": {"value": "30000.00", "currency": "RUB"},
            "metadata": {"chat": str(CHAT), "kind": "plot", "days": "30", "price": "30000",
                         "count": "3", "demo": "1"}}
    result = core.payment_apply(paid)
    assert result["granted"] is False and "демо" in result["reason"]
    assert core.access_status(CHAT)["reserve"] == 0
    demo = core._DEMO_CHAT_BASE + 77
    result = core.payment_apply({**paid, "metadata": {**paid["metadata"], "chat": str(demo)}})
    assert result["granted"] is True and result["reserve"] == 3
    assert core.access_status(demo)["reserve"] == 3
    # Боевой платёж демо-пользователю запас не кладёт.
    real = {**paid, "id": "y", "metadata": {**paid["metadata"], "chat": str(demo)}}
    del real["metadata"]["demo"]
    assert core.payment_apply(real)["granted"] is False
    assert core.access_status(demo)["reserve"] == 3


def test_render_signs_the_reserve_and_the_core_rejects_a_forged_count(shop, monkeypatch):
    sent: list[dict] = []

    def core_post(url, payload, timeout):
        sent.append(payload)
        return TestClient(core.app).post("/internal/access/grant", json=payload).json()

    monkeypatch.setattr(core, "_MO_CALC_API_URL", "https://core.example/mo/calculate")
    monkeypatch.setattr(core, "_core_post", core_post)
    buy_package(shop, 3, [A1])
    assert sent and sent[0]["reserve"] == 2 and sent[0]["payment_id"] == PAY_ID
    status = core.access_status(CHAT)
    assert status["reserve"] == 2 and len(status["plots"]) == 1
    forged = {**sent[0], "reserve": 9, "payment_id": PAY_ID + "1"}
    assert TestClient(core.app).post("/internal/access/grant", json=forged).status_code == 403
    assert core.access_status(CHAT)["reserve"] == 2


# --- кабинет, бот, администратор, тексты --------------------------------------

def me(chat: int = CHAT) -> dict:
    answer = client().post("/access/me", json={"session": session(chat)})
    assert answer.status_code == 200, answer.text
    return answer.json()


def tariffs(data: dict) -> str:
    prelude = "function escapeHtml(s){return String(s).replace(/</g,'&lt;')}"
    out, _ = page_blocks.run(prelude, f"console.log(tariffsHtml({json.dumps(data)}));")
    return out


def test_the_cabinet_and_the_bot_show_the_reserve(shop, monkeypatch):
    assert use(FREE)["basis"] == "free"
    buy_package(shop, 3, [A1])
    assert use(B)["basis"] == "reserve"
    data = me()
    assert data["status"]["reserve"] == 1 and data["package_max_plots"] == 10
    text = tariffs(data)
    assert "В запасе участков: 1." in text
    assert B + " — доступ до" in text and "(из запаса)" in text
    assert 'id="payCount"' in text and "Сколько участков" in text and 'max="10"' in text
    assert "Несколько участков вперёд" in text
    # Пустой запас — без обещания, что участок откроется сам.
    empty = json.loads(json.dumps(data))
    empty["status"]["reserve"] = 0
    assert "В запасе участков: 0." in tariffs(empty)
    assert "Участок из запаса откроется сам" not in tariffs(empty)
    sent: list[str] = []
    monkeypatch.setattr(_wrapper, "_send_message", lambda chat, text, **kw: sent.append(text))
    _wrapper._tariffs_message(CHAT)
    assert "В запасе участков: 1." in sent[-1] and "(из запаса)" in sent[-1]
    assert "Несколько участков вперёд" in sent[-1]


def test_the_admin_puts_plots_in_reserve_by_hand(shop, monkeypatch):
    core.users_touch(CHAT, surface="telegram", name="Иван Петров")
    refused = client().post("/access/admin/grant", json={
        "key": "kluch", "chat": CHAT, "kind": "reserve", "count": 0})
    assert refused.status_code == 400 and "от 1 до 10" in refused.json()["detail"]
    answer = client().post("/access/admin/grant", json={
        "key": "kluch", "chat": CHAT, "kind": "reserve", "count": 3, "note": "пилот"})
    assert answer.status_code == 200, answer.text
    data = answer.json()
    assert data["what"] == "запас: 3 участка" and data["status"]["reserve"] == 3
    assert data["until"] is None and data["reserve"] == 3
    row = next(r for r in journal() if r.get("event") == "reserve")
    assert row["count"] == 3 and row["source"] == "admin" and "администратор" in row["note"]
    assert "пилот" in row["note"]
    overview = client().post("/access/admin/overview", json={"key": "kluch"}).json()
    assert next(p for p in overview["people"] if p["chat"] == CHAT)["reserve"] == 3
    assert use(FREE)["basis"] == "free"
    assert use(B)["basis"] == "reserve"
    sent: list[str] = []
    monkeypatch.setattr(_wrapper, "_send_message", lambda chat, text, **kw: sent.append(text))
    _wrapper._grant_command(ADMIN, ADMIN, f"{CHAT} запас 2")
    assert "положено в запас: 2 участка" in sent[-1] and "Теперь в запасе: 4" in sent[-1]
    assert core.access_status(CHAT)["reserve"] == 4
    _wrapper._grant_command(ADMIN, ADMIN, f"{CHAT} запас много")
    assert "/grant ID запас N" in sent[-1]


def test_the_refund_policy_and_the_offer_mention_the_reserve():
    refund = TestClient(core.app).get("/refund").text.replace(" ", " ")
    assert "остаются в запасе" in refund and "считается не посчитанным" in refund
    assert "полная цена участка, 10 000 ₽" in refund and "14 дней после оплаты" in refund
    assert "от двух до 10" in refund and "{{" not in refund and "не задано" not in refund
    offer = TestClient(core.app).get("/offer").text.replace(" ", " ")
    assert "сразу к нескольким участкам" in offer and "в запасе Лицензиата" in offer
    assert "от двух до 10 одним платежом" in offer and "по цене 10 000 ₽ за каждый" in offer
    assert "{{" not in offer and "не задано" not in offer
    assert not [m for m in core.payments_missing() if "полей" in m]
    public = TestClient(core.app).get("/tariffs").text
    assert "Несколько участков вперёд" in public and "до 10 участков" in public


def test_the_offer_item_prices_the_package_without_a_discount(monkeypatch):
    monkeypatch.setenv("DEVELOPAID_PLOT_PRICE_RUB", "12000")
    item = core.payment_offer_item("plot", None, 4)
    assert item["price_rub"] == 48000 and item["unit_price_rub"] == 12000 and item["count"] == 4
    single = core.payment_offer_item("plot", {"label": A1})
    assert single["price_rub"] == 12000 and single["count"] == 1 and A1 in single["description"]
    assert core.payment_offer_item("subscription", None, 5)["count"] == 1
    with pytest.raises(core.HTTPException):
        core.payment_offer_item("plot", None, 11)


# --- отрисованная страница ------------------------------------------------------

def test_the_package_is_bought_from_the_drawn_page(shop, monkeypatch):
    """Поле «Сколько участков», сумма в строке «К оплате», оплата и запас в
    кабинете — в браузере, через настоящие маршруты."""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import browser

    monkeypatch.setenv("DEVELOPAID_PUBLIC_URL", "")
    path = browser.chromium_or_skip()
    errors: list[str] = []
    with browser.serve(core.app, 18983) as base, sync_playwright() as pw:
        shop["state"]["confirmation_url"] = base + "/payments/return"
        with pw.chromium.launch(executable_path=str(path)) as engine:
            page = engine.new_page(viewport={"width": 1280, "height": 900})
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.add_init_script(
                f"localStorage.setItem('developaid_web_session', {json.dumps(session())})")
            page.goto(base, wait_until="networkidle")
            page.evaluate(f"inputs.cadastral_numbers={json.dumps(A1)}")
            page.click("#tariffsButton")
            page.wait_for_selector("#payCount")
            assert page.locator("label[for=payCount]").inner_text().strip() == "Сколько участков"
            assert page.input_value("#payCount") == "1"
            assert page.locator("#payPlotButton").inner_text() == "Оплатить текущий участок"
            page.fill("#payCount", "3")
            page.dispatch_event("#payCount", "input")
            total = page.inner_text("#payTotal").replace(" ", " ")
            assert page.locator("#payPlotButton").inner_text() == "Оплатить 3 участка"
            page.fill("#payEmail", "buyer@example.ru")
            # Платёж подтверждается «в ЮKassa» до возврата на сайт: страница
            # возврата спрашивает статус и видит оплату.
            page.click("#payPlotButton")
            page.wait_for_url("**/payments/return", timeout=15000)
            pay(shop)
            page.wait_for_function(
                "document.getElementById('status').textContent.includes('Оплата прошла')",
                timeout=15000)
            page.goto(base, wait_until="networkidle")
            page.click("#tariffsButton")
            page.wait_for_function(
                "document.getElementById('accessReserve')&&"
                "document.getElementById('accessReserve').textContent.includes('В запасе участков')")
            cabinet = page.inner_text("#tariffsBox").replace(" ", " ")
            page.close()
    assert "К оплате: 30 000 ₽ за 3 участка" in total and "в том числе НДС 5" in total
    assert "2 участка останется в запасе" in total
    body = shop["calls"][0][2]
    assert body["metadata"]["count"] == "3" and body["amount"]["value"] == "30000.00"
    assert body["metadata"]["plot_key"] == f"cad:{A1}"
    assert "В запасе участков: 2." in cabinet and A1 in cabinet
    assert core.access_status(CHAT)["reserve"] == 2
    assert not errors, errors
