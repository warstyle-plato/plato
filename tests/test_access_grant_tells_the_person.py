"""Выданный доступ человек узнаёт из Telegram (решение владельца 26.10.2026).

- при любой выдаче — в кабинете, командой /grant, после оплаты — бот пишет
  человеку, что открыто и до какого числа; комментарий администратора — только
  для журнала и в сообщение не попадает;
- не дошло — причина в ответе выдавшему, а доступ всё равно выдан;
- повтор уведомления об оплате второго сообщения не шлёт.

Запуск: python3 -m pytest tests/test_access_grant_tells_the_person.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import main as _wrapper

core = _wrapper.core
client = TestClient(core.app)
ADMIN, CHAT = 777, 9494
A1 = "50:20:0010101:51"


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:notify-test-token")
    monkeypatch.setenv("DEVELOPAID_ADMIN_IDS", str(ADMIN))
    monkeypatch.setenv("DEVELOPAID_PUBLIC_URL", "https://developaid.ru")
    monkeypatch.setattr(core, "_MO_CALC_API_URL", "")
    core.users_touch(CHAT, surface="telegram", name="Иван Петров")
    yield


@pytest.fixture
def sent(monkeypatch):
    box: list[tuple[int, str]] = []
    monkeypatch.setattr(core, "_telegram_send_message",
                        lambda chat, text, **_: box.append((int(chat), text)))
    return box


def grant(**body) -> dict:
    answer = client.post("/access/admin/grant", json={
        "session": core._telegram_session(ADMIN, []), "chat": CHAT, **body})
    assert answer.status_code == 200, answer.text
    return answer.json()


def test_a_subscription_is_told_without_the_admin_note(sent):
    result = grant(kind="subscription", days=30, note="Сотрудник")
    assert result["notice"] == {"sent": True}
    assert len(sent) == 1 and sent[0][0] == CHAT
    text = sent[0][1]
    assert "Вам открыта подписка DevelopAid до" in text and "любые участки" in text
    assert "https://developaid.ru" in text
    assert "Сотрудник" not in text and "администратор" not in text


def test_a_plot_and_a_reserve_are_told(sent):
    grant(kind="plot", cadastral=[A1], days=30)
    grant(kind="reserve", count=3)
    assert A1 in sent[0][1] and "пересчитывать его можно" in sent[0][1]
    assert "Вам добавлено участков в запас: 3" in sent[1][1] and "Всего в запасе: 3" in sent[1][1]


def test_an_undelivered_message_is_named_and_the_access_stays(monkeypatch):
    def blocked(chat, text, **_):
        raise RuntimeError("Telegram API: Forbidden: bot was blocked by the user")

    monkeypatch.setattr(core, "_telegram_send_message", blocked)
    result = grant(kind="subscription", days=30)
    assert result["notice"]["sent"] is False
    assert "blocked by the user" in result["notice"]["reason"]
    assert core.access_status(CHAT)["subscription_active"]


def test_a_repeated_payment_notice_does_not_write_twice(sent):
    plot = core.access_plot(cadastral=[A1])
    core.access_grant(CHAT, plot=plot, payment_id="pay-notify-1")
    core.access_grant(CHAT, plot=plot, payment_id="pay-notify-1")
    assert len(sent) == 1 and A1 in sent[0][1]


def test_the_bot_grant_tells_the_admin_whether_the_person_was_told(monkeypatch, sent):
    replies: list[str] = []
    monkeypatch.setattr(_wrapper, "_send_message", lambda chat, text, **_: replies.append(text))
    _wrapper._grant_command(ADMIN, ADMIN, f"{CHAT} 30 подписка")
    assert len(sent) == 1
    assert "Доступ выдан" in replies[-1] and "Сообщение ему в Telegram отправлено" in replies[-1]


def test_the_admin_form_says_whether_the_person_was_told(sent):
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    import browser

    path = browser.chromium_or_skip()
    with browser.serve(core.app, 18997) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            page = engine.new_page(viewport={"width": 1280, "height": 900})
            page.add_init_script("localStorage.setItem('developaid_web_session', "
                                 f"{json.dumps(core._telegram_session(ADMIN, []))})")
            page.goto(base, wait_until="networkidle")
            page.add_style_tag(content="#profileDialog{display:none!important}")
            page.click("#tariffsButton")
            page.wait_for_function(
                "document.querySelector('#grantChat option[value=\"" + str(CHAT) + "\"]')")
            page.select_option("#grantKind", "subscription")
            page.select_option("#grantChat", str(CHAT))
            page.click("button:has-text('Выдать доступ')")
            page.wait_for_function(
                "document.getElementById('accessAdminStatus').textContent.includes('Выдано')")
            status = page.inner_text("#accessAdminStatus")
            page.close()
    assert "Сообщение в Telegram отправлено" in status
