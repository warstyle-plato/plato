"""Ни одна машина в цепочке не держит соединение под работу Платона.

На сайте тяжёлый вопрос не заканчивался ничем: в логе ядра шли десятки строк
опроса стадии, а записи «llm answer» не появлялось вовсе. Причина — цепочка
из длинных запросов. Браузер держал один запрос к ядру, ядро держало запрос к
Render, Render держал запрос к OpenAI, и у каждого звена свой предел: nginx
рвёт на шестидесяти секундах, Render — на своих, мобильный Safari — на своих.
Тяжёлый вопрос гоняет модель с инструментами по нескольку раундов и не
укладывался ни в один из этих сроков; работа при этом доходила до конца, но
уносилась в никуда, а ядро начинало всё заново.

Сроками это не лечится — лечится схемой. Работа принимается и считается фоном,
результат ждёт под номером запуска (на ядре) и под билетом (на сервисе модели),
а забирается коротким опросом, который рвать не за что.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import inspect
import json
import sys
import threading
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


def _payload(trace_id: str, message: str = "При каких вводных проект станет рентабельным?"):
    return {
        "message": message, "trace_id": trace_id,
        "inputs": dict(core.DEFAULT_INPUTS),
        "tep": {k: dict(v) for k, v in core.TEP_DEFAULT.items()},
        "rates": [], "phasing": {}, "history": [], "selected_view": "all",
    }


def _slow_llm(seconds: float, answer: str = "Ответ по расчёту."):
    def call(req, bundle, trace_id=None):
        time.sleep(seconds)
        return {"answer": answer, "model": "test-model", "source": "llm",
                "response_id": None, "tools_used": [], "proposals": []}
    return call


# --- ядро: запрос не ждёт конца работы ---------------------------------------

def test_a_heavy_question_is_accepted_not_held(client, monkeypatch):
    """Прежде запрос висел до конца работы и умирал на чужом таймауте."""
    monkeypatch.setattr(core, "_PLATO_CHAT_HANDOFF_SECONDS", 0.4)
    monkeypatch.setattr(core, "_call_openai_tool_agent", _slow_llm(2.0))
    started = time.monotonic()
    response = client.post("/agent/chat", json=_payload("aa11bb22cc33"))
    assert response.status_code == 200
    assert time.monotonic() - started < 1.5, "соединение держали дольше передачи работы"
    body = response.json()
    assert body["pending"] is True
    assert body["trace_id"] == "aa11bb22cc33"


def test_the_accepted_work_finishes_and_waits_under_the_run_id(client, monkeypatch):
    monkeypatch.setattr(core, "_PLATO_CHAT_HANDOFF_SECONDS", 0.4)
    monkeypatch.setattr(core, "_call_openai_tool_agent", _slow_llm(1.5, "Пересчитал: LLCR 1,27x."))
    trace = "bb22cc33dd44"
    assert client.post("/agent/chat", json=_payload(trace)).json()["pending"] is True

    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        body = client.get("/agent/result/" + trace).json()
        if not body.get("pending"):
            assert "LLCR" in body["answer"]
            return
        time.sleep(0.2)
    pytest.fail("работа, принятая сервером, до ответа не дошла")


def test_a_quick_answer_still_comes_back_in_the_same_request(client, monkeypatch):
    """Опрос — цена только для долгой работы. Кнопка отвечает как раньше."""
    monkeypatch.setattr(core, "_call_openai_tool_agent", _slow_llm(0.0, "Быстрый ответ."))
    body = client.post("/agent/chat", json=_payload("cc33dd44ee55")).json()
    assert body.get("pending") is None
    assert body["answer"] == "Быстрый ответ."


def test_the_page_picks_up_accepted_work():
    page = core.PAGE
    assert "if(response.ok&&data&&data.pending)" in page
    assert "awaitAgentResult(traceId,thinking,true)" in page
    # Принятая работа и оборванное соединение — разные вещи.
    assert "Работа принята, жду ответ" in page
    assert "работа идёт, жду ответ" in page


def test_the_page_waits_while_the_engine_reports_progress():
    """Сдаваться по часам, когда на той стороне идёт шаг за шагом, — терять
    посчитанное: тяжёлый вопрос честно длиннее пяти минут."""
    page = core.PAGE
    assert "let deadline=Date.now()+300000" in page
    assert "hardStop=Date.now()+900000" in page
    assert "seenStage" in page


# --- бот ждёт сам: забирать результат ему неоткуда ---------------------------

def test_the_bot_waits_for_the_whole_answer(monkeypatch):
    """`agent_chat` отдал бы боту «работа принята», и человек в телеграме
    получил бы вместо ответа пустоту."""
    source = inspect.getsource(wrapper._run_agent)
    assert "core.plato_answer(" in source
    assert "core.agent_chat(" not in source


def test_the_blocking_call_returns_the_answer_itself(monkeypatch):
    monkeypatch.setattr(core, "_PLATO_CHAT_HANDOFF_SECONDS", 0.2)
    monkeypatch.setattr(core, "_call_openai_tool_agent", _slow_llm(1.0, "Ответ боту."))
    req = core.AgentChatRequest(
        message="вопрос из телеграма", inputs=dict(core.DEFAULT_INPUTS),
        tep={k: dict(v) for k, v in core.TEP_DEFAULT.items()},
        rates=[], phasing={}, history=[], selected_view="all")
    result = core.plato_answer(req, _fake_request())
    assert result["answer"] == "Ответ боту."


def _fake_request():
    from starlette.requests import Request
    return Request({"type": "http", "method": "POST", "path": "/agent/chat",
                    "headers": [], "query_string": b"",
                    "client": ("telegram", 1), "server": ("developaid", 443)})


# --- сервис модели: тоже не держит -------------------------------------------

@pytest.fixture
def render_side(monkeypatch):
    """Ядро отличается от Render пустым PLATO_AI_URL — там служебный путь и
    обслуживается."""
    monkeypatch.setattr(core, "_PLATO_AI_URL", "")
    monkeypatch.setenv("PLATO_AI_PROXY_SECRET", "s3cret")
    monkeypatch.setattr(core, "_PLATO_PROXY_HANDOFF_SECONDS", 0.4)
    core._PLATO_PROXY_JOBS.clear()
    yield {"X-Plato-Secret": "s3cret"}
    core._PLATO_PROXY_JOBS.clear()


def test_the_model_service_accepts_the_job_by_ticket(client, render_side, monkeypatch):
    monkeypatch.setattr(core, "_openai_direct_request",
                        lambda payload: time.sleep(1.5) or {"output": [], "id": "resp_1"})
    response = client.post("/internal/plato/chat",
                           json={"payload": {"model": "gpt-5.6"}, "ticket": "ab12ab12ab12"},
                           headers=render_side)
    assert response.json() == {"pending": True, "ticket": "ab12ab12ab12"}

    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        body = client.get("/internal/plato/result/ab12ab12ab12", headers=render_side).json()
        if not body.get("pending"):
            assert body["answer"]["id"] == "resp_1"
            return
        time.sleep(0.2)
    pytest.fail("сервис модели принял работу и не отдал результат")


def test_a_retry_with_the_same_ticket_does_not_order_a_second_call(client, render_side, monkeypatch):
    """Повтор после обрыва обязан подобрать начатую работу: второй вызов модели
    стоит денег и удваивает ожидание."""
    calls = {"n": 0}

    def once(payload):
        calls["n"] += 1
        time.sleep(1.0)
        return {"id": "resp_once"}

    monkeypatch.setattr(core, "_openai_direct_request", once)
    for _ in range(3):
        client.post("/internal/plato/chat",
                    json={"payload": {"model": "m"}, "ticket": "cd34cd34cd34"},
                    headers=render_side)
    time.sleep(1.6)
    assert calls["n"] == 1


def test_a_failure_of_the_model_reaches_the_caller(client, render_side, monkeypatch):
    def boom(payload):
        time.sleep(0.8)
        raise core.HTTPException(status_code=502, detail="OpenAI API: rate limit")

    monkeypatch.setattr(core, "_openai_direct_request", boom)
    client.post("/internal/plato/chat",
                json={"payload": {"model": "m"}, "ticket": "ef56ef56ef56"}, headers=render_side)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        body = client.get("/internal/plato/result/ef56ef56ef56", headers=render_side).json()
        if not body.get("pending"):
            assert "rate limit" in body["error"]
            assert body["status"] == 502
            return
        time.sleep(0.2)
    pytest.fail("неудача модели не доехала до зовущего")


def test_the_result_endpoint_is_closed_without_the_secret(client, render_side):
    assert client.get("/internal/plato/result/ab12ab12ab12").status_code == 403
    assert client.get("/internal/plato/result/не-билет", headers=render_side).status_code == 400


def test_an_old_client_without_a_ticket_still_gets_the_answer(client, render_side, monkeypatch):
    """Выкатка новой машины не имеет права сломать старую."""
    monkeypatch.setattr(core, "_openai_direct_request",
                        lambda payload, budget_seconds=None: {"id": "sync"})
    body = client.post("/internal/plato/chat", json={"payload": {"model": "m"}},
                       headers=render_side).json()
    assert body == {"id": "sync"}


# --- клиент прокси: билет и опрос --------------------------------------------

def test_the_proxy_client_sends_a_ticket_and_picks_the_answer_up(monkeypatch):
    """Между машинами не остаётся ни одного длинного запроса."""
    monkeypatch.setattr(core, "_PLATO_AI_URL", "https://render.example/internal/plato/chat")
    monkeypatch.setattr(core, "_PLATO_AI_PROXY_SECRET", "s3cret")
    monkeypatch.setattr(core, "_PLATO_PROXY_POLL_SECONDS", 0.05)
    seen: dict[str, object] = {"polls": 0}

    class FakeResponse:
        def __init__(self, body: bytes):
            self._body = body

        def read(self) -> bytes:
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(request, timeout=None):
        url = request.full_url
        if request.get_method() == "POST":
            body = json.loads(request.data.decode("utf-8"))
            seen["ticket"] = body.get("ticket")
            assert body["payload"]["model"] == "gpt-5.6"
            return FakeResponse(json.dumps({"pending": True, "ticket": body["ticket"]}).encode())
        seen["polls"] = int(seen["polls"]) + 1
        assert url.endswith("/internal/plato/result/" + str(seen["ticket"]))
        assert request.get_header("X-plato-secret") == "s3cret"
        if int(seen["polls"]) < 2:
            return FakeResponse(b'{"pending": true}')
        return FakeResponse(json.dumps({"pending": False, "answer": {"id": "resp_9"}}).encode())

    monkeypatch.setattr(core.urllib.request, "urlopen", fake_urlopen)
    answer = core._openai_proxy_request({"model": "gpt-5.6"})
    assert answer == {"id": "resp_9"}
    assert seen["ticket"], "билет не отправлен — опрос был бы невозможен"
    assert int(seen["polls"]) >= 2


def test_the_ticket_is_one_per_call_not_per_attempt():
    """Иначе повтор после обрыва заказал бы вторую работу вместо того, чтобы
    подобрать начатую."""
    source = inspect.getsource(core._openai_proxy_request)
    ticket_line = source.index("ticket = os.urandom")
    loop_line = source.index("for attempt in range(")
    assert ticket_line < loop_line


def test_the_result_address_is_built_from_the_chat_address(monkeypatch):
    monkeypatch.setattr(core, "_PLATO_AI_URL", "https://render.example/internal/plato/chat")
    assert core._plato_proxy_result_url("ab12ab12ab12") == \
        "https://render.example/internal/plato/result/ab12ab12ab12"
    monkeypatch.setattr(core, "_PLATO_AI_URL", "")
    assert core._plato_proxy_result_url("ab12ab12ab12") == ""


def test_no_step_of_the_chain_holds_a_long_connection():
    """Смысл переделки: длинных запросов не остаётся нигде."""
    assert core._PLATO_CHAT_HANDOFF_SECONDS <= 30
    assert core._PLATO_PROXY_HANDOFF_SECONDS <= 30
    assert core._PLATO_PROXY_POLL_TIMEOUT <= 60


def test_the_handoff_is_written_to_the_log():
    """«Платон молчит» разбирается по логу: видно, что работа принята."""
    source = inspect.getsource(core.agent_chat)
    assert "handed off to polling" in source
