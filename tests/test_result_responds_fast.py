"""Ответ на /telegram/result не должен ждать PDF и Excel-модель.

Мини-приложение закрывается по ответу этого запроса. Пока PDF и модель
собирались внутри него, в чат всё уже приходило, а окно висело с надписью
«Готов. Отправляю в чат…» десятки секунд. Тяжёлые вложения уходят следом за
ответом, а не до него.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core

SUMMARY = {
    "purchase_price_mln": 6500, "net_profit_mln": 900, "llcr": 1.3,
    "report_payload": {"result": {"summary": {}}, "inputs": {}, "tep": {},
                       "rates": [], "phasing": {}},
}


@pytest.fixture
def telegram(monkeypatch):
    events: list[str] = []
    monkeypatch.setattr(core, "_telegram_verify_session", lambda s: {"chat_id": 42, "cad": []})
    monkeypatch.setattr(core, "_telegram_user_allowed", lambda c: True)
    monkeypatch.setattr(core, "_telegram_web_app_url", lambda *a, **k: "https://example.org/")
    monkeypatch.setattr(core, "_telegram_send_message",
                        lambda chat_id, text, **kw: events.append("карточка"))
    monkeypatch.setattr(core, "_telegram_send_document_bytes",
                        lambda *a, **k: events.append("вложение"))

    def slow_pdf(payload):
        time.sleep(0.4)
        events.append("PDF собран")
        return b"%PDF-"

    monkeypatch.setattr(core, "_build_developaid_pdf", slow_pdf)
    monkeypatch.setattr(core, "build_model_archive",
                        lambda *a, **k: (b"PK\x03\x04", "модель.zip"))
    return events


def call_asgi(events: list[str]) -> None:
    """Гоняет запрос через ASGI напрямую, отмечая момент отправки ответа.

    TestClient дожидается фоновых задач, поэтому по нему не отличить «ответили
    сразу» от «ответили после сборки». Здесь виден сам порядок событий.
    """
    import asyncio
    import json

    body = json.dumps({"session": "s", "summary": SUMMARY}).encode("utf-8")
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": "POST", "path": "/telegram/result", "raw_path": b"/telegram/result",
        "query_string": b"", "root_path": "", "scheme": "http",
        "headers": [(b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode())],
        "client": ("test", 1), "server": ("test", 80),
    }

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        if message["type"] == "http.response.body" and not message.get("more_body"):
            events.append("ответ отправлен")

    asyncio.run(wrapper.app(scope, receive, send))


def test_the_response_leaves_before_the_attachments_are_built(telegram):
    call_asgi(telegram)

    assert "ответ отправлен" in telegram, "ответ не ушёл"
    assert telegram.index("ответ отправлен") < telegram.index("PDF собран"), \
        "ответ дождался сборки вложений — окно снова будет висеть"


def test_the_card_goes_out_before_the_response(telegram):
    """Карточка уходит внутри запроса: её отказ обязан вернуться ошибкой."""
    call_asgi(telegram)

    assert telegram.index("карточка") < telegram.index("ответ отправлен")


def test_the_attachments_still_arrive(telegram):
    from fastapi.testclient import TestClient

    with TestClient(wrapper.app) as client:
        client.post("/telegram/result", json={"session": "s", "summary": SUMMARY})

    assert telegram[0] == "карточка", "карточка должна уходить первой"
    assert "PDF собран" in telegram
    assert telegram.count("вложение") == 2, "должны прийти и PDF, и модель"


def test_a_direct_call_still_sends_everything(telegram):
    """Прямой вызов без фоновых задач обязан отработать целиком."""
    core.telegram_result(core.TelegramResultRequest(session="s", summary=SUMMARY))

    assert "PDF собран" in telegram
    assert telegram.count("вложение") == 2


def test_the_bot_report_carries_the_sensitivity_section(monkeypatch):
    """В боте окно закрывается сразу после расчёта — до вкладки не добраться."""
    seen = {}
    inputs = dict(core.DEFAULT_INPUTS)
    inputs["purchase_price_mln"] = 700
    tep = {key: dict(value) for key, value in core.TEP_DEFAULT.items()}
    bundle = core._run_authoritative_model(inputs, tep, [], {})
    monkeypatch.setattr(core, "_telegram_send_document_bytes", lambda *a, **k: None)
    monkeypatch.setattr(core, "_telegram_send_message", lambda *a, **k: None)
    monkeypatch.setattr(core, "build_model_archive", lambda *a, **k: (b"PK", "м.zip"))
    monkeypatch.setattr(core, "_build_developaid_pdf",
                        lambda payload: seen.update(payload) or b"%PDF-")

    core._telegram_send_attachments(42, {"result": bundle["consolidated"], "inputs": inputs,
                                         "tep": tep, "rates": [], "phasing": {}}, "", [])

    assert seen.get("sensitivity"), "анализ не посчитан — раздела в отчёте не будет"
    assert seen["sensitivity"]["items"]


def test_an_explicit_analysis_is_not_recomputed(monkeypatch):
    """Посчитанное на вкладке уходит как есть — второй раз считать незачем."""
    seen = {}
    monkeypatch.setattr(core, "_telegram_send_document_bytes", lambda *a, **k: None)
    monkeypatch.setattr(core, "_telegram_send_message", lambda *a, **k: None)
    monkeypatch.setattr(core, "build_model_archive", lambda *a, **k: (b"PK", "м.zip"))
    monkeypatch.setattr(core, "_build_developaid_pdf",
                        lambda payload: seen.update(payload) or b"%PDF-")
    monkeypatch.setattr(core, "run_sensitivity",
                        lambda *a, **k: pytest.fail("анализ пересчитан заново"))

    core._telegram_send_attachments(42, {**SUMMARY["report_payload"],
                                         "sensitivity": {"items": [], "base": {}}}, "", [])

    assert seen["sensitivity"] == {"items": [], "base": {}}
