"""Оплата через ЮKassa: права — только по подтверждённому платежу.

Здесь закреплено:

- без ключей магазина, оферты или политики возврата оплата выключена и
  говорит об этом человеку понятными словами;
- платёж несёт чек 54-ФЗ: НДС 5 % кодом 7 (цена включает налог, расчёт полный),
  предмет — право использования программы, назначение — не длиннее 128 знаков;
- выдачу решает перечитанный из API платёж, а не тело уведомления и не возврат
  браузера: поддельное «succeeded» в уведомлении ничего не открывает;
- повтор уведомления не продлевает доступ второй раз;
- уведомление не с адреса ЮKassa — отказ, и подставной `X-Forwarded-For` не
  помогает;
- сумма, не совпавшая с ценой заказа, прав не даёт;
- чужой платёж в «проверке оплаты» не открывается.

Запуск: python3 -m pytest tests/test_payments_yookassa.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as _wrapper

core = _wrapper.core
CHAT = 8080
A1 = "50:20:0010101:21"
PAY_ID = "2f6c1a2b-000f-5000-8000-1a2b3c4d5e6f"
YOOKASSA_IP = "185.71.76.5"


@pytest.fixture()
def shop(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:payments-test-token")
    monkeypatch.setenv("YOOKASSA_SHOP_ID", "100500")
    monkeypatch.setenv("YOOKASSA_SECRET_KEY", "test_secret")
    monkeypatch.delenv("DEVELOPAID_ADMIN_IDS", raising=False)
    monkeypatch.setattr(core, "_MO_CALC_API_URL", "")
    legal = tmp_path / "legal"
    legal.mkdir()
    (legal / "product.json").write_text(
        (core._LEGAL_DIR / "product.json").read_text(encoding="utf-8"), encoding="utf-8")
    (legal / "offer.md").write_text("# Оферта\n\nТекст владельца.", encoding="utf-8")
    (legal / "refund.md").write_text("# Возврат\n\nТекст владельца.", encoding="utf-8")
    monkeypatch.setattr(core, "_LEGAL_DIR", legal)
    store: dict[str, dict] = {}
    calls: list[tuple] = []

    def fake_call(method, path, body=None, idempotence_key="", test=False):
        calls.append((method, path, body, idempotence_key))
        if method == "POST":
            payment = {"id": PAY_ID, "status": "pending", "paid": False,
                       "amount": body["amount"], "metadata": body["metadata"],
                       "confirmation": {"confirmation_url": "https://yoomoney.ru/pay/x"}}
            store[PAY_ID] = payment
            return payment
        return dict(store[path.rsplit("/", 1)[-1]])

    monkeypatch.setattr(core, "_yookassa_call", fake_call)
    return {"store": store, "calls": calls, "legal": legal}


def client(ip: str = YOOKASSA_IP) -> TestClient:
    return TestClient(core.app, client=(ip, 50000))


def session() -> str:
    return core._telegram_session(CHAT, [])


def create(kind: str = "plot") -> dict:
    answer = client().post("/payments/create", json={
        "session": session(), "kind": kind, "cadastral": [A1], "email": "buyer@example.ru"})
    assert answer.status_code == 200, answer.text
    return answer.json()


def pay(shop) -> None:
    shop["store"][PAY_ID].update(status="succeeded", paid=True)


def webhook(ip: str = YOOKASSA_IP, **headers):
    return client(ip).post("/payments/yookassa/webhook", headers=headers, json={
        "type": "notification", "event": "payment.succeeded",
        "object": {"id": PAY_ID, "status": "succeeded", "paid": True}})


def plot_open() -> bool:
    return core.access_use(CHAT, core.access_plot(cadastral=[A1]))["allowed"] and \
        core.access_use(CHAT, core.access_plot(cadastral=[A1]))["basis"] == "payment"


def test_without_keys_or_offer_payment_is_off_and_says_so(shop, monkeypatch):
    (shop["legal"] / "offer.md").write_text("<!-- ЗАГОТОВКА: -->\n# Оферта", encoding="utf-8")
    assert "оферты" in " ".join(core.payments_missing())
    answer = client().post("/payments/create", json={
        "session": session(), "cadastral": [A1], "email": "buyer@example.ru"})
    assert answer.status_code == 503
    assert "Оплата на сайте пока не подключена" in answer.json()["detail"]
    assert not shop["calls"], "без оферты в ЮKassa не ходим"
    (shop["legal"] / "offer.md").write_text("# Оферта\n\nТекст.", encoding="utf-8")
    monkeypatch.delenv("YOOKASSA_SECRET_KEY")
    assert not core.payments_available()


def test_the_payment_carries_a_54fz_receipt(shop):
    create()
    method, path, body, key = shop["calls"][0]
    assert (method, path) == ("POST", "/payments") and key
    assert body["amount"] == {"value": "10000.00", "currency": "RUB"}
    assert body["capture"] is True
    item = body["receipt"]["items"][0]
    assert item["vat_code"] == 7 and item["payment_mode"] == "full_payment"
    assert item["payment_subject"] == "intellectual_activity"
    assert item["description"].startswith("Право использования программы для ЭВМ")
    assert len(body["description"]) <= 128
    assert body["receipt"]["customer"] == {"email": "buyer@example.ru"}
    assert body["metadata"]["plot_key"] == f"cad:{A1}"


def test_an_email_is_needed_for_the_receipt(shop):
    answer = client().post("/payments/create", json={"session": session(), "cadastral": [A1]})
    assert answer.status_code == 400 and "почты" in answer.json()["detail"]


def test_returning_from_the_payment_page_does_not_open_an_unpaid_plot(shop):
    create()
    answer = client().post("/payments/status", json={"session": session(), "payment_id": PAY_ID})
    assert answer.json()["granted"] is False
    assert core.access_status(CHAT)["plots"] == []


def test_a_forged_succeeded_notification_opens_nothing(shop):
    create()
    # Тело говорит «оплачен», API — «ещё нет»: верим API.
    assert webhook().status_code == 200
    assert core.access_status(CHAT)["plots"] == []


def test_a_confirmed_payment_opens_the_plot_once(shop):
    create()
    pay(shop)
    assert webhook().json()["granted"] is True
    until = core.access_status(CHAT)["plots"][0]["until"]
    assert webhook().status_code == 200
    status = core.access_status(CHAT)
    assert len(status["plots"]) == 1 and status["plots"][0]["until"] == until
    # Возврат браузера после уведомления — тоже без второй выдачи.
    client().post("/payments/status", json={"session": session(), "payment_id": PAY_ID})
    assert len(core.access_status(CHAT)["plots"]) == 1
    assert plot_open()


def test_a_subscription_payment_grants_the_subscription(shop):
    create("subscription")
    assert shop["calls"][0][2]["amount"]["value"] == "100000.00"
    pay(shop)
    webhook()
    assert core.access_status(CHAT)["subscription_active"]


def test_a_notification_from_elsewhere_is_refused(shop):
    create()
    pay(shop)
    assert webhook(ip="203.0.113.7").status_code == 403
    # Подставной адрес в начале X-Forwarded-For не помогает: верим последнему.
    spoofed = webhook(ip="10.0.0.2", **{"X-Forwarded-For": f"{YOOKASSA_IP}, 203.0.113.7"})
    assert spoofed.status_code == 403
    assert core.access_status(CHAT)["plots"] == []
    assert webhook(ip="10.0.0.2", **{"X-Forwarded-For": f"203.0.113.7, {YOOKASSA_IP}"}).status_code == 200


def test_a_wrong_amount_grants_nothing(shop):
    create()
    pay(shop)
    shop["store"][PAY_ID]["amount"] = {"value": "1.00", "currency": "RUB"}
    assert webhook().json()["granted"] is False
    assert core.access_status(CHAT)["plots"] == []


def test_someone_elses_payment_is_not_shown(shop):
    create()
    other = core._telegram_session(CHAT + 1, [])
    answer = client().post("/payments/status", json={"session": other, "payment_id": PAY_ID})
    assert answer.status_code == 403


def test_render_hands_the_grant_to_the_core(shop, monkeypatch):
    sent: list[dict] = []

    def core_post(url, payload, timeout):
        sent.append(payload)
        return TestClient(core.app).post("/internal/access/grant", json=payload).json()

    monkeypatch.setattr(core, "_MO_CALC_API_URL", "https://core.example/mo/calculate")
    monkeypatch.setattr(core, "_core_post", core_post)
    create()
    pay(shop)
    webhook()
    assert sent and sent[0]["payment_id"] == PAY_ID
    assert len(core.access_status(CHAT)["plots"]) == 1
    forged = {**sent[0], "key": "cad:50:20:0010101:99", "cadastral": ["50:20:0010101:99"]}
    assert TestClient(core.app).post("/internal/access/grant", json=forged).status_code == 403


def test_the_registration_has_one_source(shop):
    info = core.product_info()
    assert info["certificate_number"] == "2026691589"
    line = core.product_registration_line()
    assert "№ 2026691589 от 14.10.2026" in line
    assert line in client().get("/offer").text
    terms = client().get("/payments/terms").json()
    assert terms["registration"] == line and terms["plot"]["vat_note"] == "в том числе НДС 5 %"
