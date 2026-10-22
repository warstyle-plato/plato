"""Рассылка сводки руководству: приглашение, расписание, без двойной отправки.

Решения владельца (20.10.2026): подписка по ссылке-приглашению на бота,
сообщение и PDF по понедельникам (неделя) и 1-го числа (месяц) в 9:00 МСК,
владелец видит получателей и может отписать любого.

Проверки:
- сроки: понедельник — неделя по воскресенье, 1-е — прошлый месяц, до 9:00
  ничего, ядро, лежавшее утром, досылает в тот же день, но не через двое суток;
- ссылка: подписывает, новая закрывает прежнюю, подписанных не трогает;
- два воркера: срок собирается один раз, очередь отдаётся один раз — второй
  получает пустоту; не подтверждённое ботом не выдаётся за «отправлено»;
- маршруты ядра без подписи токеном бота отказывают;
- бот: «/start rep_…» подписывает, «/report_stop» отписывает, круг рассылки
  шлёт сообщение и PDF и сообщает ядру итог;
- настоящая сводка печатается в PDF из фона; страница показывает ссылку и
  получателей и отписывает.

Запуск: python3 -m pytest tests/test_report_mailing.py -q
"""
from __future__ import annotations

import datetime
import json
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from test_management_report_model import PROJECT, _project

import developaid_monitor as monitor
import developaid_report_mailing as mailing

MSK = mailing.MSK
PORT = 18804


def at(text: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(text).replace(tzinfo=MSK)


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path / "monitor")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:test")
    monkeypatch.setenv("TELEGRAM_BOT_USERNAME", "developaid_bot")
    monkeypatch.delenv("MO_CALC_API_URL", raising=False)
    monkeypatch.delenv("CORE_API_URL", raising=False)


def test_the_schedule():
    monday = mailing.due(at("2026-11-09T09:05"))
    assert monday == [{"slot": "week-2026-11-08", "kind": "week", "end": "2026-11-08",
                       "at": "2026-11-09T09:00:00+03:00"}]
    assert mailing.due(at("2026-11-09T08:59")) == []
    assert [item["slot"] for item in mailing.due(at("2027-04-01T09:00"))] == ["month-2027-03"]
    # 1 февраля 2027 — понедельник: и неделя, и месяц.
    assert [item["slot"] for item in mailing.due(at("2027-02-01T10:00"))] == [
        "week-2027-01-31", "month-2027-01"]
    # Ядро лежало в 9:00 — досылает днём и назавтра утром, но не через двое суток.
    assert [item["slot"] for item in mailing.due(at("2026-11-10T08:00"))] == ["week-2026-11-08"]
    assert mailing.due(at("2026-11-11T09:00")) == []
    assert mailing.next_slot(at("2026-10-21T12:00"))["slot"] == "week-2026-10-25"
    assert mailing.next_slot(at("2026-10-26T12:00"))["slot"] == "month-2026-10"


def test_the_invite_link_subscribes_and_a_new_one_closes_the_old():
    first = mailing.invite(PROJECT, "Иванов")
    assert first["start"].startswith("rep_") and len(first["start"]) <= 64
    assert mailing.subscribe(first["start"], 501, "Пётр") == PROJECT
    assert mailing.subscribe(first["start"], 501, "Пётр") == PROJECT  # повтор — не дубль
    second = mailing.invite(PROJECT, "Иванов")
    with pytest.raises(KeyError):
        mailing.subscribe(first["start"], 502, "Мария")
    mailing.subscribe(second["start"], 502, "Мария")
    assert [row["chat_id"] for row in mailing.subscribers(PROJECT)] == [501, 502]
    with pytest.raises(ValueError):
        mailing.subscribe("rep_../../x", 503, "")
    assert mailing.unsubscribe(501) == [PROJECT]
    assert mailing.unsubscribe(501) == []
    assert [row["chat_id"] for row in mailing.subscribers(PROJECT)] == [502]


def _made(calls):
    def make(project, kind, end):
        calls.append((project, kind, end))
        return {"text": f"Сводка {project} {kind} {end}", "pdf": b"%PDF-1.4 test",
                "filename": "Сводка.pdf", "error": ""}
    return make


def test_two_workers_build_once_and_hand_out_once():
    token = mailing.invite(PROJECT, "Иванов")["start"]
    mailing.subscribe(token, 501, "Пётр")
    mailing.subscribe(token, 502, "Мария")
    calls: list = []
    now = at("2026-11-09T09:01")
    assert mailing.build_due(_made(calls), now) == [f"week-2026-11-08:{PROJECT}"]
    assert mailing.build_due(_made(calls), now) == []
    assert calls == [(PROJECT, "week", "2026-11-08")]

    got: list = []
    barrier = threading.Barrier(2)

    def worker():
        barrier.wait()
        got.append(mailing.take(now))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    handed = [item for batch in got for item in batch ]
    assert len(handed) == 1, "очередь отдана дважды — получатели получили бы две сводки"
    assert sorted(handed[0]["chats"]) == [501, 502] and handed[0]["pdf"] == b"%PDF-1.4 test"
    assert mailing.take(now) == []

    # Бот подтвердил одному, у второго ошибка; третий подписался после сборки.
    mailing.subscribe(token, 503, "Олег")
    mailing.confirm("week-2026-11-08", PROJECT, {"501": "", "502": "Forbidden: bot was blocked"})
    people = {row["chat_id"]: row for row in mailing.status(PROJECT, now)["subscribers"]}
    assert people[501]["last"]["label"] == "отправлено"
    assert people[502]["last"]["label"] == "не отправлено"
    assert "blocked" in people[502]["last"]["error"]
    assert people[503]["last"] is None


def test_unconfirmed_is_not_called_sent_and_old_slots_are_not_handed_out():
    token = mailing.invite(PROJECT, "Иванов")["start"]
    mailing.subscribe(token, 501, "Пётр")
    mailing.build_due(_made([]), at("2026-11-09T09:01"))
    assert mailing.take(at("2026-11-11T10:00")) == []  # срок прошёл
    mailing.take(at("2026-11-09T09:02"))
    last = mailing.status(PROJECT, at("2026-11-09T09:03"))["subscribers"][0]["last"]
    assert last["label"] == "отправка не подтверждена"


def test_a_busy_printer_is_retried_then_sent_with_the_reason():
    token = mailing.invite(PROJECT, "Иванов")["start"]
    mailing.subscribe(token, 501, "Пётр")

    def busy(project, kind, end):
        return {"text": "Сводка", "pdf": None, "filename": "", "retry": True,
                "error": "PDF не напечатался: печать занята"}

    assert mailing.build_due(busy, at("2026-11-09T09:01")) == []
    assert mailing.build_due(busy, at("2026-11-09T11:30")) != []
    item = mailing.take(at("2026-11-09T11:31"))[0]
    assert item["pdf"] is None and "печать занята" in item["error"]


def test_core_routes_need_the_bot_signature():
    from fastapi import HTTPException

    import main
    core = main.core
    with pytest.raises(HTTPException) as refused:
        core.internal_report_outbox(core.ReportMailingInternalRequest(chat_id=0, sign="x"))
    assert refused.value.status_code == 403
    token = mailing.invite(PROJECT, "Иванов")["start"]
    with pytest.raises(HTTPException) as forged:
        core.internal_report_subscribe(core.ReportMailingInternalRequest(
            chat_id=501, start=token, sign=core._web_login_sign("report-subscribe", 777)))
    assert forged.value.status_code == 403


def test_the_bot_subscribes_sends_and_reports_back(monkeypatch):
    import main
    core = main.core
    sent: list = []
    docs: list = []
    monkeypatch.setattr(core, "_telegram_send_message",
                        lambda chat, text, **_k: sent.append((chat, text)))
    monkeypatch.setattr(core, "_telegram_send_document_bytes",
                        lambda chat, data, name, caption="", **_k: docs.append((chat, name, data)))
    monkeypatch.setattr(core, "_telegram_webhook_enabled", lambda: True)
    token = mailing.invite(PROJECT, "Иванов")["start"]

    def message(chat, text):
        return {"chat": {"id": chat, "type": "private"},
                "from": {"id": chat, "first_name": "Пётр"}, "text": text}

    core._telegram_handle_message(message(501, f"/start {token}"))
    assert "Вы подписаны на сводку руководству по проекту «Гродненская»" in sent[-1][1]
    assert "/report_stop" in sent[-1][1]
    core._telegram_handle_message(message(502, "/start rep_AAAAAAAAAAAA"))
    assert "больше не действует" in sent[-1][1]
    assert [row["chat_id"] for row in mailing.subscribers(PROJECT)] == [501]

    mailing.build_due(_made([]))  # сегодня не срок — пусто
    monkeypatch.setattr(mailing, "due", lambda now=None: [{
        "slot": "week-2026-11-01", "kind": "week", "end": "2026-11-01",
        "at": "2026-11-09T09:00:00+03:00"}])
    mailing.build_due(_made([]))
    sent.clear()
    done = main._deliver_management_reports()
    assert done[0]["results"] == {"501": ""}
    assert sent == [(501, f"Сводка {PROJECT} week 2026-11-01")]
    assert docs == [(501, "Сводка.pdf", b"%PDF-1.4 test")]
    assert main._deliver_management_reports() == []  # второй круг — ничего
    assert mailing.status(PROJECT)["subscribers"][0]["last"]["label"] == "отправлено"

    core._telegram_handle_message(message(501, "/report_stop"))
    assert "Вы отписаны от сводки" in sent[-1][1]
    assert mailing.subscribers(PROJECT) == []


def test_a_long_message_is_split_on_lines():
    import main
    text = "\n".join(f"<b>Строка {n}</b> " + "х" * 90 for n in range(100))
    parts = main._split_message(text)
    assert len(parts) > 1 and all(len(part) <= 3900 for part in parts)
    assert "\n".join(parts) == text


def test_the_real_report_prints_from_the_background():
    from browser import chromium_or_skip

    chromium_or_skip()
    import main
    _project()
    got = main.core._mailing_make(PROJECT, "week", "2026-10-18")
    assert got["pdf"] and got["pdf"].startswith(b"%PDF"), got.get("error")
    assert got["filename"].endswith(".pdf")
    assert "Сводка по проекту «Гродненская»" in got["text"]
    assert got["text"].endswith("Отписаться от сводки: /report_stop")


def test_the_page_shows_the_link_and_the_recipients(monkeypatch):
    from browser import chromium_or_skip, serve

    chrome = chromium_or_skip()
    from playwright.sync_api import sync_playwright

    import main_legacy as core

    _project()
    monkeypatch.setattr(core, "_require_web_access", lambda *_a, **_k: None)
    with serve(core.app, PORT) as base, sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chrome))
        try:
            tab = browser.new_page()
            errors: list[str] = []
            tab.on("pageerror", lambda e: errors.append(str(e)))
            tab.on("dialog", lambda d: d.accept())
            tab.add_init_script("localStorage.setItem('developaid_web_session','проба')")
            tab.goto(f"{base}/report", wait_until="domcontentloaded")
            tab.wait_for_selector(f"#project option[value='{PROJECT}']", state="attached")
            tab.select_option("#project", PROJECT)
            tab.click("#reportBtn")
            tab.wait_for_function(
                "document.getElementById('mailingList').textContent.includes('Получателей пока нет')")
            tab.click("#mailingInviteBtn")
            tab.wait_for_selector("#mailingLinkText")
            link = tab.input_value("#mailingLinkText")
            mailing.subscribe(link.split("start=")[1], 501, "Пётр Петров")
            tab.click("#mailingInviteBtn")
            tab.wait_for_function(
                f"document.getElementById('mailingLinkText').value !== {json.dumps(link)}")
            tab.wait_for_selector("#mailingList .mailingPerson")
            person = tab.inner_text("#mailingList")
            new_link = tab.input_value("#mailingLinkText")
            tab.click("#mailingList .mailingRemove")
            tab.wait_for_function(
                "document.getElementById('mailingList').textContent.includes('Получателей пока нет')")
            nxt = tab.inner_text("#mailingNext")
        finally:
            browser.close()
    assert not errors, errors
    assert link.startswith("https://t.me/developaid_bot?start=rep_")
    assert new_link != link
    assert "Пётр Петров" in person and "сводок ещё не было" in person
    assert nxt.startswith("Ближайшая рассылка")
    assert mailing.subscribers(PROJECT) == []


def test_the_internal_routes_read_their_body_over_http():
    """Тело маршрута читается как JSON, а не уезжает в строку запроса (422)."""
    from fastapi.testclient import TestClient

    import main
    core = main.core
    token = mailing.invite(PROJECT, "Иванов")["start"]
    client = TestClient(core.app)
    got = client.post("/internal/report/subscribe", json={
        "chat_id": 501, "start": token, "name": "Пётр",
        "sign": core._web_login_sign("report-subscribe", 501)})
    assert got.status_code == 200, got.text
    assert got.json()["project"] == PROJECT
    outbox = client.post("/internal/report/outbox", json={
        "chat_id": 0, "sign": core._web_login_sign("report-outbox", 0)})
    assert outbox.status_code == 200 and outbox.json() == {"items": []}
