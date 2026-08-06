"""Одна ссылка отвечает, доходит ли вызов до модели и где он встал.

«Платон не отвечает» разбиралось скриншотами и логом закрытого хостинга, хотя
вопрос всегда один: доходит ли вызов до модели. Цепочка длинная — браузер,
ядро на Яндексе, сервис модели на Render, OpenAI, — и в ней ломается ровно
одно звено за раз, а видно это только по строке в логе, до которого с чужой
машины не дотянуться.

Проверка идёт тем же маршрутом, что и настоящий вопрос: тот же секрет, тот же
билет, тот же опрос. Отличий два — короткий срок и запрос на один токен: она
отвечает «дошло или нет», а не решает задачу.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core


@pytest.fixture
def client():
    return TestClient(core.app)


@pytest.fixture(autouse=True)
def fresh_selftest():
    core._PLATO_SELFTEST.update(at=0.0, result=None)
    yield
    core._PLATO_SELFTEST.update(at=0.0, result=None)


def test_a_working_chain_answers_with_how_long_it_took(client, monkeypatch):
    monkeypatch.setattr(core, "_openai_responses_request",
                        lambda payload, budget_seconds=None: {"id": "resp_ok"})
    body = client.get("/agent/selftest").json()
    assert body["ok"] is True
    assert body["response_id"] == "resp_ok"
    assert "Цепочка работает" in body["verdict"]
    assert body["seconds"] >= 0


def test_a_silent_model_service_is_named_as_such(client, monkeypatch):
    """Главное, что должна снимать проверка: ключ и модель ни при чём, если до
    них вызов не доходит."""
    monkeypatch.setattr(core, "_plato_route", lambda: "render_proxy")

    def timeout(payload, budget_seconds=None):
        raise core.HTTPException(status_code=504,
                                 detail="Платон Сергеевич не ответил за 60 с.")

    monkeypatch.setattr(core, "_openai_responses_request", timeout)
    body = client.get("/agent/selftest").json()
    assert body["ok"] is False
    assert "не отвечает этому серверу" in body["verdict"]
    assert "Ключ и модель ни при чём" in body["verdict"]


def test_a_wrong_secret_is_named_precisely(client, monkeypatch):
    monkeypatch.setattr(core, "_plato_route", lambda: "render_proxy")
    monkeypatch.setattr(core, "_openai_responses_request",
                        lambda payload, budget_seconds=None: (_ for _ in ()).throw(
                            core.HTTPException(status_code=403, detail="Неверный секрет")))
    assert "PLATO_AI_PROXY_SECRET" in client.get("/agent/selftest").json()["verdict"]


def test_a_missing_key_on_this_server_is_named_too(client, monkeypatch):
    monkeypatch.setattr(core, "_plato_route", lambda: "local_openai")
    monkeypatch.setattr(core, "_openai_responses_request",
                        lambda payload, budget_seconds=None: (_ for _ in ()).throw(
                            core.HTTPException(status_code=503,
                                               detail="OPENAI_API_KEY не задан")))
    assert "Ключ OpenAI" in client.get("/agent/selftest").json()["verdict"]


def test_the_check_costs_a_token_not_a_conversation(client, monkeypatch):
    """Проверка — не вопрос Платону: ни инструментов, ни истории, ни расчёта."""
    seen = {}
    monkeypatch.setattr(core, "_openai_responses_request",
                        lambda payload, budget_seconds=None: seen.update(
                            payload=payload, budget=budget_seconds) or {"id": "r"})
    client.get("/agent/selftest")
    assert "tools" not in seen["payload"]
    assert seen["payload"]["max_output_tokens"] <= 32
    assert seen["budget"] == core._PLATO_SELFTEST_BUDGET


def test_the_check_waits_far_less_than_a_real_question():
    """Иначе диагностика сама висит четыре минуты — ровно то, что она должна
    объяснять."""
    assert core._PLATO_SELFTEST_BUDGET <= core._PLATO_AI_TIMEOUT_SECONDS / 2


def test_refreshing_the_page_does_not_re_run_it(client, monkeypatch):
    calls = {"n": 0}

    def once(payload, budget_seconds=None):
        calls["n"] += 1
        return {"id": "r"}

    monkeypatch.setattr(core, "_openai_responses_request", once)
    assert client.get("/agent/selftest").json()["cached"] is False
    assert client.get("/agent/selftest").json()["cached"] is True
    assert calls["n"] == 1


def test_the_result_carries_the_keepalive_state(client, monkeypatch):
    """Пинг и вызов проверяют разное: сервис может отвечать на /health и не
    отвечать на вызов модели."""
    monkeypatch.setattr(core, "_openai_responses_request",
                        lambda payload, budget_seconds=None: {"id": "r"})
    monkeypatch.setitem(core._PLATO_KEEPALIVE, "last_ok", "2026-08-06T14:00:00")
    body = client.get("/agent/selftest").json()
    assert body["keepalive"]["last_ok"] == "2026-08-06T14:00:00"


# --- срок вызова задаётся снаружи --------------------------------------------

def test_the_budget_reaches_the_transport(monkeypatch):
    """Без этого самопроверка ждала бы полный срок тяжёлого вопроса."""
    monkeypatch.setattr(core, "_PLATO_AI_URL", "https://render.example/internal/plato/chat")
    monkeypatch.setattr(core, "_PLATO_AI_PROXY_SECRET", "s3cret")
    monkeypatch.setattr(core, "_PLATO_WAKE_TIMEOUT_SECONDS", 45.0)
    seen = []

    def fake_urlopen(request, timeout=None):
        seen.append(timeout)
        raise TimeoutError("timed out")

    monkeypatch.setattr(core.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(core, "_PLATO_PROXY_BACKOFF", (0, 0))
    started = time.monotonic()
    with pytest.raises(core.HTTPException):
        core._openai_proxy_request({"model": "m"}, budget_seconds=1.0)
    assert time.monotonic() - started < 3.0
    assert max(seen) <= 1.0, "короткий срок не доехал до попытки"
