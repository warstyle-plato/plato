"""Обрыв TLS до Render не доходит до пользователя.

После переноса на Yandex VM вызовы Платона Сергеевича падали с
`SSL: UNEXPECTED_EOF_WHILE_READING`, при том что в логах Render те же запросы
отвечали 200. То есть Render и OpenAI отрабатывали, а рвалось чтение ответа на
стороне клиента — транспорт, а не отказ сервиса.

Такой сбой повторяется до трёх раз с паузами 1 и 2 секунды. Ответы самого
приложения — 400, 401, 403 — не повторяются никогда: они детерминированы, и
повтор лишь задержал бы понятную ошибку.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import http.client
import io
import json
import socket
import ssl
import sys
import urllib.error
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core
PAYLOAD = {"model": "gpt-5.6", "input": [{"role": "user", "content": "LLCR?"}]}
ANSWER = {"output": [{"content": [{"text": "1,07x"}]}]}


class Response:
    def __init__(self, body=None, error=None):
        self._body = body if body is not None else json.dumps(ANSWER).encode()
        self._error = error

    def __enter__(self): return self
    def __exit__(self, *a): return False

    def read(self):
        if self._error:
            raise self._error
        return self._body


@pytest.fixture(autouse=True)
def proxy(monkeypatch):
    monkeypatch.setattr(core, "_PLATO_AI_URL", "https://render.example/internal/plato/chat")
    monkeypatch.setattr(core, "_PLATO_AI_PROXY_SECRET", "s3cret-ascii")
    monkeypatch.setattr(core, "_PLATO_AI_TIMEOUT_SECONDS", 120.0)
    monkeypatch.setattr(core.time, "sleep", lambda _s: None)


def urlopen_returning(*outcomes):
    """Каждый вызов отдаёт очередной исход: исключение или ответ."""
    calls = {"n": 0, "requests": []}

    def fake(request, timeout=None):
        calls["requests"].append(request)
        outcome = outcomes[min(calls["n"], len(outcomes) - 1)]
        calls["n"] += 1
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    return fake, calls


def http_error(code, detail=""):
    return urllib.error.HTTPError(
        "https://render.example", code, "err", {},
        io.BytesIO(json.dumps({"detail": detail}).encode()))


def test_a_tls_eof_is_retried_and_succeeds(monkeypatch):
    fake, calls = urlopen_returning(ssl.SSLEOFError("UNEXPECTED_EOF_WHILE_READING"), Response())
    monkeypatch.setattr(core.urllib.request, "urlopen", fake)

    assert core._openai_proxy_request(PAYLOAD) == ANSWER
    assert calls["n"] == 2


def test_two_connection_resets_still_succeed(monkeypatch):
    fake, calls = urlopen_returning(ConnectionResetError(), ConnectionResetError(), Response())
    monkeypatch.setattr(core.urllib.request, "urlopen", fake)

    assert core._openai_proxy_request(PAYLOAD) == ANSWER
    assert calls["n"] == 3


def test_three_failures_give_a_readable_message(monkeypatch):
    fake, calls = urlopen_returning(ssl.SSLEOFError("eof"), ssl.SSLEOFError("eof"), ssl.SSLEOFError("eof"))
    monkeypatch.setattr(core.urllib.request, "urlopen", fake)

    with pytest.raises(HTTPException) as exc:
        core._openai_proxy_request(PAYLOAD)

    assert calls["n"] == 3
    assert "временно недоступен" in str(exc.value.detail)
    assert "Traceback" not in str(exc.value.detail)
    assert "SSLEOFError" not in str(exc.value.detail)


def test_a_wrong_secret_is_not_retried(monkeypatch):
    fake, calls = urlopen_returning(http_error(401), Response())
    monkeypatch.setattr(core.urllib.request, "urlopen", fake)

    with pytest.raises(HTTPException) as exc:
        core._openai_proxy_request(PAYLOAD)

    assert calls["n"] == 1
    assert "PLATO_AI_PROXY_SECRET" in str(exc.value.detail)


def test_a_bad_request_is_not_retried(monkeypatch):
    fake, calls = urlopen_returning(http_error(400, "Пустой запрос к модели"), Response())
    monkeypatch.setattr(core.urllib.request, "urlopen", fake)

    with pytest.raises(HTTPException) as exc:
        core._openai_proxy_request(PAYLOAD)

    assert calls["n"] == 1
    assert "Пустой запрос" in str(exc.value.detail)


def test_an_incomplete_body_is_retried(monkeypatch):
    fake, calls = urlopen_returning(
        Response(error=http.client.IncompleteRead(b"partial")), Response())
    monkeypatch.setattr(core.urllib.request, "urlopen", fake)

    assert core._openai_proxy_request(PAYLOAD) == ANSWER
    assert calls["n"] == 2


def test_an_empty_body_is_retried(monkeypatch):
    fake, calls = urlopen_returning(Response(body=b""), Response())
    monkeypatch.setattr(core.urllib.request, "urlopen", fake)

    assert core._openai_proxy_request(PAYLOAD) == ANSWER
    assert calls["n"] == 2


def test_the_connection_is_closed_each_time(monkeypatch):
    fake, calls = urlopen_returning(Response())
    monkeypatch.setattr(core.urllib.request, "urlopen", fake)
    core._openai_proxy_request(PAYLOAD)

    headers = dict(calls["requests"][0].headers)
    assert headers.get("Connection") == "close"


def test_a_timeout_is_not_retried(monkeypatch):
    fake, calls = urlopen_returning(socket.timeout(), Response())
    monkeypatch.setattr(core.urllib.request, "urlopen", fake)

    with pytest.raises(HTTPException) as exc:
        core._openai_proxy_request(PAYLOAD)

    assert calls["n"] == 1
    assert exc.value.status_code == 504


def test_secrets_never_reach_the_log(monkeypatch, caplog):
    fake, _ = urlopen_returning(ssl.SSLEOFError("eof"), Response())
    monkeypatch.setattr(core.urllib.request, "urlopen", fake)

    with caplog.at_level("INFO", logger="developaid.platon"):
        core._openai_proxy_request(PAYLOAD)

    text = " ".join(record.getMessage() for record in caplog.records)
    assert "s3cret-ascii" not in text
    assert "render.example" not in text
    assert "LLCR?" not in text
    assert "Platon proxy attempt 1/3 failed" in text
    assert "Platon proxy retry in 1s" in text
