"""Платон Сергеевич думает через отдельный сервис, а живёт в интерфейсе модели.

Ключ OpenAI лежит только там, где выполняется обращение к модели. Сервер с
расчётом ключа не знает и пересылает вызов серверным запросом с общим секретом.
Наружу уходит ровно один шаг: цикл вызова инструментов, расчётный контекст,
LLCR, очереди, Goal Seek, аномалии и сценарии остаются рядом с моделью —
инструменты работают по её данным, и разрывать цикл нельзя.
Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import io
import json
import socket
import sys
import urllib.error
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as _wrapper  # noqa: E402

main = _wrapper.core
client = TestClient(main.app)

PAYLOAD = {"model": "gpt-5.6", "input": [{"role": "user", "content": "LLCR?"}]}


def http_error(code: int, detail: str):
    def boom(*args, **kwargs):
        raise urllib.error.HTTPError(
            "https://example.invalid", code, "err", {},
            io.BytesIO(json.dumps({"detail": detail}).encode()),
        )
    return boom


# --- маршрутизация вызова ----------------------------------------------------

def test_call_goes_direct_when_no_proxy_configured(monkeypatch):
    seen = {}
    monkeypatch.setattr(main, "_PLATO_AI_URL", "")
    monkeypatch.setattr(main, "_openai_direct_request", lambda p: seen.setdefault("direct", p))
    main._openai_responses_request(PAYLOAD)
    assert seen == {"direct": PAYLOAD}


def test_call_goes_through_the_proxy_when_configured(monkeypatch):
    seen = {}
    monkeypatch.setattr(main, "_PLATO_AI_URL", "https://bot.example/internal/plato/chat")
    monkeypatch.setattr(main, "_openai_proxy_request", lambda p: seen.setdefault("proxy", p))
    main._openai_responses_request(PAYLOAD)
    assert seen == {"proxy": PAYLOAD}


def test_proxy_sends_the_secret_in_a_header(monkeypatch):
    captured = {}

    class Response:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return json.dumps({"output": []}).encode()

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.data.decode())
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr(main, "_PLATO_AI_URL", "https://bot.example/internal/plato/chat")
    monkeypatch.setattr(main, "_PLATO_AI_PROXY_SECRET", "s3cret-ascii")
    monkeypatch.setattr(main, "_PLATO_AI_TIMEOUT_SECONDS", 120.0)
    monkeypatch.setattr(main.urllib.request, "urlopen", fake_urlopen)

    main._openai_proxy_request(PAYLOAD)
    assert captured["url"] == "https://bot.example/internal/plato/chat"
    assert captured["headers"]["X-plato-secret"] == "s3cret-ascii"
    # Ключ OpenAI не должен покидать сервис, где он задан.
    assert not any("authorization" in name.lower() for name in captured["headers"])
    assert captured["body"] == {"payload": PAYLOAD}
    assert captured["timeout"] == 120.0


# --- служебный эндпоинт ------------------------------------------------------

def test_internal_endpoint_rejects_a_wrong_secret(monkeypatch):
    monkeypatch.setenv("PLATO_AI_PROXY_SECRET", "right-secret")
    response = client.post("/internal/plato/chat",
                           json={"payload": PAYLOAD},
                           headers={"X-Plato-Secret": "wrong-secret"})
    assert response.status_code == 403


def test_internal_endpoint_refuses_when_no_secret_is_set(monkeypatch):
    monkeypatch.delenv("PLATO_AI_PROXY_SECRET", raising=False)
    response = client.post("/internal/plato/chat", json={"payload": PAYLOAD})
    assert response.status_code == 503
    assert "PLATO_AI_PROXY_SECRET" in response.json()["detail"]


def test_internal_endpoint_forwards_to_openai(monkeypatch):
    monkeypatch.setenv("PLATO_AI_PROXY_SECRET", "s3cret-ascii")
    monkeypatch.setattr(main, "_openai_direct_request", lambda p: {"echo": p})
    response = client.post("/internal/plato/chat",
                           json={"payload": PAYLOAD},
                           headers={"X-Plato-Secret": "s3cret-ascii"})
    assert response.status_code == 200
    assert response.json() == {"echo": PAYLOAD}


def test_internal_endpoint_rejects_an_empty_payload(monkeypatch):
    monkeypatch.setenv("PLATO_AI_PROXY_SECRET", "s3cret-ascii")
    response = client.post("/internal/plato/chat", json={"payload": {}},
                           headers={"X-Plato-Secret": "s3cret-ascii"})
    assert response.status_code == 400


# --- понятные ошибки ---------------------------------------------------------

def test_timeout_is_reported_as_a_temporary_outage(monkeypatch):
    monkeypatch.setattr(main, "_PLATO_AI_URL", "https://bot.example/internal/plato/chat")
    monkeypatch.setattr(main, "_PLATO_AI_TIMEOUT_SECONDS", 120.0)

    def boom(*args, **kwargs):
        raise socket.timeout()

    monkeypatch.setattr(main.urllib.request, "urlopen", boom)
    with pytest.raises(HTTPException) as exc:
        main._openai_proxy_request(PAYLOAD)
    assert exc.value.status_code == 504
    assert "120" in str(exc.value.detail)


def test_wrong_secret_is_explained(monkeypatch):
    monkeypatch.setattr(main, "_PLATO_AI_URL", "https://bot.example/internal/plato/chat")
    monkeypatch.setattr(main.urllib.request, "urlopen", http_error(403, ""))
    with pytest.raises(HTTPException) as exc:
        main._openai_proxy_request(PAYLOAD)
    assert "PLATO_AI_PROXY_SECRET" in str(exc.value.detail)


def test_service_outage_is_readable(monkeypatch):
    monkeypatch.setattr(main, "_PLATO_AI_URL", "https://bot.example/internal/plato/chat")
    monkeypatch.setattr(main.urllib.request, "urlopen", http_error(502, "сервис перезапускается"))
    with pytest.raises(HTTPException) as exc:
        main._openai_proxy_request(PAYLOAD)
    assert "временно недоступен" in str(exc.value.detail)


# --- статус ------------------------------------------------------------------

def test_status_is_enabled_without_a_local_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(main, "_PLATO_AI_URL", "https://bot.example/internal/plato/chat")
    status = main.agent_status()
    assert status["enabled"] is True
    assert status["thinks_via"] == "внешний сервис"


def test_status_is_disabled_without_key_and_proxy(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(main, "_PLATO_AI_URL", "")
    assert main.agent_status()["enabled"] is False


def test_context_stays_with_the_model():
    """Инструменты Платона Сергеевича считают по модели — их нельзя уносить."""
    names = {tool["name"] for tool in main._AGENT_TOOLS}
    assert names, "агент остался без инструментов"
    # Наружу уходит только вызов модели: сам цикл инструментов остаётся здесь.
    source = Path(main.__file__).read_text(encoding="utf-8")
    start = source.index("def _call_openai_tool_agent")
    body = source[start:source.index("\n@app.", start)]
    assert "_openai_responses_request" in body
    assert "PLATO_AI_URL" not in body


def test_non_ascii_secret_is_refused_with_a_clear_message(monkeypatch):
    """Кириллица в секрете ломала запрос на кодировании заголовка."""
    monkeypatch.setattr(main, "_PLATO_AI_URL", "https://bot.example/internal/plato/chat")
    monkeypatch.setattr(main, "_PLATO_AI_PROXY_SECRET", "секрет")
    with pytest.raises(HTTPException) as exc:
        main._openai_proxy_request(PAYLOAD)
    assert "не-ASCII" in str(exc.value.detail)
