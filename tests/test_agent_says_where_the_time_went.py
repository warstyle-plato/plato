"""«Платон завис» разбирается по окну, а не по логу хостинга.

Работу перестали держать соединением — и это сняло обрывы, но не сняло второй
вопрос: куда уходит время. Окно показывало одну надпись «Платон Сергеевич
думает», одинаковую и на первой секунде, и на пятой минуте, а разбираться
приходилось по логу закрытого хостинга.

Теперь стадия называет, что именно происходит: какая попытка обращения к
сервису модели идёт и сколько секунд он уже считает. Вторая попытка означает
ровно одно — сервис не ответил за окно пробуждения; это первое, что надо знать,
и узнаваться оно должно из окна.

Заодно у разговора появился общий срок. Восемь раундов, каждый со своим сроком
в четыре минуты, дают полчаса — столько не ждёт никто, а оборванный на середине
разговор человеку бесполезен. Кончился бюджет — ответ собирается из уже
посчитанного.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core


def _stage(trace_id: str) -> dict:
    path = core._plato_stage_path("trace", trace_id)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


class _FakeResponse:
    def __init__(self, body: bytes):
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


# --- стадия называет, где стоим ----------------------------------------------

def test_the_second_attempt_is_visible_in_the_window(monkeypatch):
    """Повтор означает, что сервис модели не ответил за окно пробуждения."""
    monkeypatch.setattr(core, "_PLATO_AI_URL", "https://render.example/internal/plato/chat")
    monkeypatch.setattr(core, "_PLATO_AI_PROXY_SECRET", "s3cret")
    monkeypatch.setattr(core, "_PLATO_PROXY_BACKOFF_SECONDS", 0.01, raising=False)
    core._PLATO_TRACE_LOCAL.trace_id = "aaaabbbbcccc"
    attempts = {"n": 0}

    def fake_urlopen(request, timeout=None):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise TimeoutError("timed out")
        return _FakeResponse(json.dumps({"id": "resp_ok"}).encode())

    monkeypatch.setattr(core.urllib.request, "urlopen", fake_urlopen)
    try:
        assert core._openai_proxy_request({"model": "m"}) == {"id": "resp_ok"}
        stage = _stage("aaaabbbbcccc")
        assert "попытка 2" in stage.get("label", "")
    finally:
        core._PLATO_TRACE_LOCAL.trace_id = ""


def test_the_wait_for_the_model_service_is_counted_in_seconds(monkeypatch):
    """«Считает 70 с» — это работа. «Жду ответ» без числа — неизвестно что."""
    monkeypatch.setattr(core, "_PLATO_AI_URL", "https://render.example/internal/plato/chat")
    monkeypatch.setattr(core, "_PLATO_AI_PROXY_SECRET", "s3cret")
    monkeypatch.setattr(core, "_PLATO_PROXY_POLL_SECONDS", 0.05)
    core._PLATO_TRACE_LOCAL.trace_id = "ddddeeeeffff"
    polls = {"n": 0}

    def fake_urlopen(request, timeout=None):
        if request.get_method() == "POST":
            return _FakeResponse(b'{"pending": true}')
        polls["n"] += 1
        if polls["n"] < 3:
            return _FakeResponse(b'{"pending": true}')
        return _FakeResponse(json.dumps({"pending": False, "answer": {"id": "r"}}).encode())

    monkeypatch.setattr(core.urllib.request, "urlopen", fake_urlopen)
    try:
        core._openai_proxy_request({"model": "m"})
        # Стадия последнего опроса — с секундомером.
        assert "Сервис модели считает" in _stage("ddddeeeeffff").get("label", "")
    finally:
        core._PLATO_TRACE_LOCAL.trace_id = ""


def test_the_stage_needs_no_run_id_threaded_through_the_call():
    """Вызов модели лежит на три этажа ниже разбора вопроса: номер запуска
    живёт в потоке, а не в подписи каждой функции по пути."""
    core._PLATO_TRACE_LOCAL.trace_id = ""
    core._plato_trace_stage("ai_ask", "без номера писать некуда")  # не падает и не пишет
    assert _stage("") == {}


# --- у разговора есть общий срок ---------------------------------------------

def _tool_call_response(name: str = "explain_metric"):
    return {"id": "r", "output": [{"type": "function_call", "name": name,
                                   "call_id": "c1", "arguments": '{"metric": "llcr"}'}]}


def _text_response(text: str):
    return {"id": "r", "output": [{"type": "message",
                                   "content": [{"type": "output_text", "text": text}]}]}


def _request(message: str = "Что оптимизировать при цене 550?"):
    return core.AgentChatRequest(
        message=message, inputs=dict(core.DEFAULT_INPUTS),
        tep={k: dict(v) for k, v in core.TEP_DEFAULT.items()},
        rates=[], phasing={}, history=[], selected_view="all")


def test_a_spent_budget_ends_in_an_answer_not_in_silence(monkeypatch):
    """Прежде разговор шёл восемь раундов независимо от того, сколько каждый
    из них занял, и человек не получал ничего."""
    monkeypatch.setattr(core, "_PLATO_AGENT_BUDGET_SECONDS", 0.5)
    rounds = {"tools": 0}

    def fake_model(payload):
        if payload.get("tools"):
            rounds["tools"] += 1
            time.sleep(0.4)
            return _tool_call_response()
        return _text_response("Снижать себестоимость и просить льготу по ВРИ.")

    monkeypatch.setattr(core, "_openai_responses_request", fake_model)
    bundle = core._run_authoritative_model(
        dict(core.DEFAULT_INPUTS),
        {k: dict(v) for k, v in core.TEP_DEFAULT.items()}, [], {})
    result = core._call_openai_tool_agent(_request(), bundle, trace_id="1122334455aa")
    assert result["forced_synthesis"] is True
    assert "льготу" in result["answer"]
    assert rounds["tools"] < core._AGENT_MAX_TOOL_ROUNDS, "бюджет не остановил разговор"


def test_a_silent_model_says_how_long_it_was_silent(monkeypatch):
    """502 без подробностей неотличим от «думает»: человеку нужно знать, куда
    ушло время."""
    monkeypatch.setattr(core, "_PLATO_AGENT_BUDGET_SECONDS", 0.2)

    def mute(payload):
        if payload.get("tools"):
            time.sleep(0.3)
            return _tool_call_response()
        raise core.HTTPException(status_code=502, detail="OpenAI API: gateway timeout")

    monkeypatch.setattr(core, "_openai_responses_request", mute)
    bundle = core._run_authoritative_model(
        dict(core.DEFAULT_INPUTS),
        {k: dict(v) for k, v in core.TEP_DEFAULT.items()}, [], {})
    with pytest.raises(core.HTTPException) as exc:
        core._call_openai_tool_agent(_request(), bundle, trace_id="2233445566bb")
    assert "молчала" in str(exc.value.detail)
    assert "Расчётная модель работает" in str(exc.value.detail)


def test_the_budget_is_shorter_than_the_window_is_willing_to_wait():
    """Иначе окно сдаётся раньше, чем сервер перестаёт спрашивать модель, и
    посчитанное опять уходит в никуда."""
    assert core._PLATO_AGENT_BUDGET_SECONDS <= 900


def test_the_round_time_reaches_the_log():
    """По логу должно быть видно, ушли минуты в модель или в цепочку до неё."""
    import inspect
    source = inspect.getsource(core._call_openai_tool_agent)
    assert "round %d took %.1fs" in source
