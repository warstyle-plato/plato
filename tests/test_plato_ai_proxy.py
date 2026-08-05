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
    monkeypatch.setattr(main, "_PLATO_AI_PROXY_SECRET", "s3cret-ascii")
    monkeypatch.setattr(main, "_openai_proxy_request", lambda p: seen.setdefault("proxy", p))
    main._openai_responses_request(PAYLOAD)
    assert seen == {"proxy": PAYLOAD}


# --- прямой OpenAI недоступен с ядра ----------------------------------------

def test_a_configured_proxy_never_falls_back_to_openai(monkeypatch):
    """Отказ Render не повод идти на api.openai.com: с ядра туда ходить нельзя."""
    monkeypatch.setattr(main, "_PLATO_AI_URL", "https://bot.example/internal/plato/chat")
    monkeypatch.setattr(main, "_PLATO_AI_PROXY_SECRET", "s3cret-ascii")

    def unreachable(payload):
        raise AssertionError("вызван прямой OpenAI при настроенном прокси")

    monkeypatch.setattr(main, "_openai_direct_request", unreachable)
    monkeypatch.setattr(main, "_openai_proxy_request", http_error(502, "Render лёг"))

    with pytest.raises((HTTPException, urllib.error.HTTPError)):
        main._openai_responses_request(PAYLOAD)


def test_an_address_without_a_secret_is_refused_not_rerouted(monkeypatch):
    """Полунастроенный прокси — ошибка конфигурации, а не переход на OpenAI."""
    monkeypatch.setattr(main, "_PLATO_AI_URL", "https://bot.example/internal/plato/chat")
    monkeypatch.setattr(main, "_PLATO_AI_PROXY_SECRET", "")

    def unreachable(payload):
        raise AssertionError("вызван прямой OpenAI без секрета прокси")

    monkeypatch.setattr(main, "_openai_direct_request", unreachable)

    with pytest.raises(HTTPException) as exc:
        main._openai_responses_request(PAYLOAD)
    assert exc.value.status_code == 503
    assert "PLATO_AI_PROXY_SECRET" in str(exc.value.detail)


def test_the_route_is_logged_without_secrets(monkeypatch, caplog):
    monkeypatch.setattr(main, "_PLATO_AI_URL", "https://bot.example/internal/plato/chat")
    monkeypatch.setattr(main, "_PLATO_AI_PROXY_SECRET", "s3cret-ascii")
    monkeypatch.setattr(main, "_openai_proxy_request", lambda p: {})

    with caplog.at_level("INFO", logger="developaid.platon"):
        main._openai_responses_request(PAYLOAD)

    messages = [record.getMessage() for record in caplog.records]
    assert "Platon route: render_proxy" in messages
    joined = " ".join(messages)
    assert "s3cret-ascii" not in joined and "bot.example" not in joined


def test_the_local_route_is_logged_too(monkeypatch, caplog):
    monkeypatch.setattr(main, "_PLATO_AI_URL", "")
    monkeypatch.setattr(main, "_openai_direct_request", lambda p: {})

    with caplog.at_level("INFO", logger="developaid.platon"):
        main._openai_responses_request(PAYLOAD)

    assert "Platon route: local_openai" in [r.getMessage() for r in caplog.records]


def test_the_core_advises_the_proxy_not_a_local_key(monkeypatch):
    """На ядре совет «добавьте OPENAI_API_KEY» вреден: ключа тут быть не должно."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(HTTPException) as exc:
        main._openai_direct_request(PAYLOAD)
    detail = str(exc.value.detail)
    assert "PLATO_AI_URL" in detail and "PLATO_AI_PROXY_SECRET" in detail


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
    assert captured["body"]["payload"] == PAYLOAD
    # Билет — согласие забрать ответ опросом: с ним сервис модели не держит
    # соединение под вызов, который длиннее любого чужого таймаута.
    assert main._TRACE_ID_RE.fullmatch(captured["body"]["ticket"])
    # Первая попытка ждёт окно пробуждения, а не полный таймаут: спящий Render
    # в него всё равно не уложится, а живой отвечает быстрее.
    assert captured["timeout"] == pytest.approx(main._PLATO_WAKE_TIMEOUT_SECONDS)


def test_a_timeout_is_retried_instead_of_becoming_a_504(monkeypatch):
    """Первый запрос будит уснувший Render и честно не получает ответа —
    раньше человек видел «Ошибка AI (504)» на вопрос, который проходил со
    второй попытки. Теперь таймаут повторяется, и ответ доезжает."""
    import socket
    attempts = []

    class Response:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return json.dumps({"output": [{"text": "ок"}]}).encode()

    def fake_urlopen(request, timeout=None):
        attempts.append(timeout)
        if len(attempts) == 1:
            raise socket.timeout("timed out")
        return Response()

    monkeypatch.setattr(main, "_PLATO_AI_URL", "https://bot.example/internal/plato/chat")
    monkeypatch.setattr(main, "_PLATO_AI_PROXY_SECRET", "s3cret")
    monkeypatch.setattr(main.time, "sleep", lambda _s: None)
    monkeypatch.setattr(main.urllib.request, "urlopen", fake_urlopen)

    answer = main._openai_proxy_request(PAYLOAD)
    assert answer == {"output": [{"text": "ок"}]}
    assert len(attempts) == 2, "таймаут обязан повторяться"
    assert attempts[0] < attempts[1], "первая попытка — короткое окно пробуждения"
    # Вторая попытка получает остаток общего бюджета, а не полный срок заново:
    # 45 + 240 + 240 — это 525 с там, где обещано 240, и окно успевало сдаться
    # раньше, чем ядро переставало ждать.
    # (Здесь сон подменён, поэтому остаток почти равен полному сроку; в жизни
    # он меньше на всё, что уже потрачено.)
    assert attempts[1] <= main._PLATO_AI_TIMEOUT_SECONDS


def test_only_a_full_run_of_timeouts_becomes_a_504(monkeypatch):
    """Когда сервис молчит все попытки — это честная 504 с числом попыток."""
    import socket

    def always_timeout(request, timeout=None):
        raise socket.timeout("timed out")

    monkeypatch.setattr(main, "_PLATO_AI_URL", "https://bot.example/internal/plato/chat")
    monkeypatch.setattr(main, "_PLATO_AI_PROXY_SECRET", "s3cret")
    monkeypatch.setattr(main.time, "sleep", lambda _s: None)
    monkeypatch.setattr(main.urllib.request, "urlopen", always_timeout)

    with pytest.raises(HTTPException) as exc:
        main._openai_proxy_request(PAYLOAD)
    assert exc.value.status_code == 504
    assert "попытки" in str(exc.value.detail)


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


def test_the_core_does_not_serve_internal_calls(monkeypatch):
    """На ядре этот путь ушёл бы прямо на api.openai.com — ровно то, что запрещено.

    Секрет общий для обеих машин, поэтому клиента от сервера отличает только
    заданный адрес прокси.
    """
    monkeypatch.setenv("PLATO_AI_PROXY_SECRET", "s3cret-ascii")
    monkeypatch.setattr(main, "_PLATO_AI_URL", "https://render.example/internal/plato/chat")

    def unreachable(payload):
        raise AssertionError("ядро ушло на api.openai.com через служебный путь")

    monkeypatch.setattr(main, "_openai_direct_request", unreachable)
    response = client.post("/internal/plato/chat", json={"payload": PAYLOAD},
                           headers={"X-Plato-Secret": "s3cret-ascii"})
    assert response.status_code == 503
    assert "Render" in response.json()["detail"]


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
    monkeypatch.setattr(main, "_PLATO_AI_PROXY_SECRET", "s3cret-ascii")
    status = main.agent_status()
    assert status["enabled"] is True
    assert status["thinks_via"] == "внешний сервис"
    assert status["route"] == "render_proxy"


def test_status_is_disabled_without_key_and_proxy(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(main, "_PLATO_AI_URL", "")
    status = main.agent_status()
    assert status["enabled"] is False
    assert status["route"] == "local_openai"


def test_a_half_configured_proxy_is_not_reported_as_ready(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(main, "_PLATO_AI_URL", "https://bot.example/internal/plato/chat")
    monkeypatch.setattr(main, "_PLATO_AI_PROXY_SECRET", "")
    status = main.agent_status()
    assert status["enabled"] is False
    assert status["proxy_configured"] is False


# --- сквозной путь: ядро → Render → OpenAI -----------------------------------

def test_the_core_reaches_openai_through_render_end_to_end(monkeypatch):
    """Сценарий со стенда целиком, без заглушки в середине.

    Ядро на Яндексе зовёт Render настоящим `_openai_proxy_request`, Render
    принимает вызов настоящим `/internal/plato/chat`, и только там появляется
    ключ. Заглушено ровно одно — сокет между машинами и сам api.openai.com.
    """
    monkeypatch.setenv("PLATO_AI_PROXY_SECRET", "s3cret-ascii")
    monkeypatch.setattr(main, "_PLATO_AI_URL", "https://render.example/internal/plato/chat")
    monkeypatch.setattr(main, "_PLATO_AI_PROXY_SECRET", "s3cret-ascii")
    monkeypatch.setattr(main, "_PLATO_AI_TIMEOUT_SECONDS", 120.0)

    reached_openai = {}

    def openai_on_render(payload):
        # На Render ключ есть — здесь и только здесь путь уходит наружу.
        reached_openai["payload"] = payload
        return {"output": [{"content": [{"text": "LLCR 1,03"}]}]}

    monkeypatch.setattr(main, "_openai_direct_request", openai_on_render)

    class Response:
        def __init__(self, body): self._body = body
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return self._body

    def render_hop(request, timeout=None):
        """Сокет между Яндексом и Render — единственное, что подменено."""
        assert request.full_url == "https://render.example/internal/plato/chat"
        # Обе машины здесь — один процесс, а на Render адрес прокси не задан:
        # он там и не нужен, ключ лежит на месте. Без этого приложение приняло
        # бы служебный вызов как ядро и отказало.
        as_core = main._PLATO_AI_URL
        main._PLATO_AI_URL = ""
        try:
            relayed = client.post(
                "/internal/plato/chat",
                content=request.data,
                headers={"X-Plato-Secret": dict(request.headers)["X-plato-secret"],
                         "Content-Type": "application/json"},
            )
        finally:
            main._PLATO_AI_URL = as_core
        assert relayed.status_code == 200, relayed.text
        return Response(relayed.content)

    monkeypatch.setattr(main.urllib.request, "urlopen", render_hop)

    answer = main._openai_responses_request(PAYLOAD)

    assert reached_openai["payload"] == PAYLOAD, "до OpenAI дошёл не тот запрос"
    assert answer == {"output": [{"content": [{"text": "LLCR 1,03"}]}]}


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


# --- готовность Платона в боте ------------------------------------------------

def _ready(monkeypatch, url, secret, key):
    for name, value in (("PLATO_AI_URL", url), ("PLATO_AI_PROXY_SECRET", secret),
                        ("OPENAI_API_KEY", key)):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    return _wrapper._agent_ready()


def test_the_bot_counts_a_configured_proxy_as_ready(monkeypatch):
    """Ядро без ключа объявлялось отключённым при исправном прокси."""
    assert _ready(monkeypatch, "https://render.example/internal/plato/chat",
                  "s3cret-ascii", None) is True


def test_the_bot_still_accepts_a_local_key(monkeypatch):
    assert _ready(monkeypatch, None, None, "sk-local") is True


def test_a_half_configured_proxy_without_a_key_is_not_ready(monkeypatch):
    assert _ready(monkeypatch, "https://render.example/internal/plato/chat", None, None) is False


def test_nothing_configured_is_not_ready(monkeypatch):
    assert _ready(monkeypatch, None, None, None) is False


def test_the_missing_piece_is_named(monkeypatch):
    """«Добавьте OPENAI_API_KEY» на ядре — вредный совет, ключа тут быть не должно."""
    monkeypatch.setenv("PLATO_AI_URL", "https://render.example/internal/plato/chat")
    monkeypatch.delenv("PLATO_AI_PROXY_SECRET", raising=False)
    assert "PLATO_AI_PROXY_SECRET" in _wrapper._agent_unready_reason()

    monkeypatch.delenv("PLATO_AI_URL", raising=False)
    assert "PLATO_AI_URL" in _wrapper._agent_unready_reason()


# --- пинг против засыпания сервиса модели ------------------------------------

def test_keepalive_pings_health_not_the_model(monkeypatch):
    """Будим сервис health-запросом: сам /internal/plato/chat вызывает модель
    и стоит токенов, а инстансу для пробуждения довольно любого обращения."""
    monkeypatch.setattr(main, "_PLATO_AI_URL",
                        "https://developaid.onrender.com/internal/plato/chat")
    assert main._plato_keepalive_url() == "https://developaid.onrender.com/health"


def test_keepalive_stays_quiet_where_the_service_is_local(monkeypatch):
    """На самом Render адрес прокси пуст — там будить некого, и поток
    не поднимается: инстанс всё равно уснёт вместе с ним."""
    monkeypatch.setattr(main, "_PLATO_AI_URL", "")
    assert main._plato_keepalive_url() == ""
    started = []
    monkeypatch.setattr(main.threading, "Thread",
                        lambda *a, **k: started.append(k) or _NoThread())
    main._start_plato_keepalive()
    assert started == [], "на сервере с локальной моделью пинг не нужен"


class _NoThread:
    def start(self):  # pragma: no cover - защита от случайного запуска
        raise AssertionError("поток не должен подниматься")


def test_agent_status_shows_the_keepalive(monkeypatch):
    monkeypatch.setattr(main, "_PLATO_AI_URL",
                        "https://developaid.onrender.com/internal/plato/chat")
    status = main.agent_status()["keepalive"]
    assert status["url"].endswith("/health")
    assert status["every_minutes"] > 0
    # Поля отклика есть всегда: «Платон опять засыпает» должно быть чем объяснить.
    assert "last_ok" in status and "last_error" in status
