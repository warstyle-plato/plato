"""Оборванное соединение не должно съедать готовый ответ Платона.

На сайте кнопки-сценарии отвечали, а свободный вопрос заканчивался красным
«Load failed». Это не ответ сервера: будь это 401, 429 или 500, окно напечатало
бы их текст — оно печатает `data.detail`. «Load failed» Safari показывает,
когда fetch не дождался ответа вообще.

Причина — длина одного HTTP-запроса. Кнопка-сценарий считается движком и
отвечает сразу; свободный вопрос идёт в модель через цепочку ядро → Render →
OpenAI, а на сервере ещё стоят повторы: первая попытка 45 с, пауза, вторая до
120 с. Столько не держит ни nginx с его шестьюдесятью секундами, ни мобильный
Safari. Соединение рвётся, а посчитанный ответ уходит в никуда.

Теперь ответ кладётся на диск под номером запуска, и окно забирает его коротким
запросом. На диск — потому что воркеров два, и опрос попадёт в другой.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core


@pytest.fixture
def client():
    return TestClient(core.app)


def _ask(client, monkeypatch, trace_id: str, message: str = "Почему такой БРИДЖ?"):
    monkeypatch.setattr(core, "_call_openai_tool_agent",
                        lambda req, bundle, trace_id=None: {
                            "answer": "Потому что покупка и проектирование платятся до РнС.",
                            "model": "test-model", "source": "llm",
                            "response_id": None, "tools_used": [], "proposals": []})
    return client.post("/agent/chat", json={
        "message": message, "trace_id": trace_id,
        "inputs": dict(core.DEFAULT_INPUTS),
        "tep": {k: dict(v) for k, v in core.TEP_DEFAULT.items()},
        "rates": [], "phasing": {}, "history": [], "selected_view": "all"})


def test_the_answer_waits_under_the_run_id(client, monkeypatch):
    """Соединение оборвалось — ответ никуда не делся."""
    trace = "a1b2c3d4e5f6"
    assert _ask(client, monkeypatch, trace).status_code == 200
    late = client.get("/agent/result/" + trace)
    assert late.status_code == 200
    body = late.json()
    assert body["pending"] is False
    assert "проектирование" in body["answer"]


def test_an_unknown_run_is_pending_not_an_error(client):
    """Окно опрашивает результат, пока идёт работа: «ещё нет» — не ошибка."""
    body = client.get("/agent/result/ffffffffffff").json()
    assert body == {"pending": True}


def test_a_broken_run_id_is_refused(client):
    assert client.get("/agent/result/../../etc/passwd").status_code in (400, 404)
    assert client.get("/agent/result/не-номер").status_code == 400


def test_the_answer_survives_the_other_worker(client, monkeypatch, tmp_path):
    """Воркеров два: ответ обязан лежать на диске, а не в памяти процесса."""
    trace = "0badc0ffee11"
    _ask(client, monkeypatch, trace)
    stored = list(core._PLATO_STAGE_DIR.glob("answer_*.json"))
    assert stored, "ответ не доехал до диска — второй воркер его не увидит"


def test_the_page_picks_the_answer_up_after_a_drop():
    """Окно обязано забирать ответ, а не показывать «Load failed»."""
    page = core.PAGE
    assert "async function awaitAgentResult(" in page
    assert "'/agent/result/'+traceId" in page
    # Сетевой сбой fetch — единственное место, где появлялся «Load failed».
    assert "catch(networkError)" in page
    assert "Соединение оборвалось, забираю готовый ответ" in page


def test_the_page_retries_on_gateway_errors_only():
    """502 и 504 — повод подождать готовый ответ. 400 и 429 повторять нечего:
    вопрос не станет короче, а лимит не станет мягче от повтора."""
    page = core.PAGE
    assert "response.status===502||response.status===504" in page
    assert "response.status===429" not in page


def test_the_page_shows_the_agreed_wording_when_the_model_is_silent():
    """Придуманный ответ хуже честного «не получилось»."""
    assert ("Платон Сергеевич временно не получил ответ от AI-сервиса. "
            "Расчётная модель продолжает работать. Повторите вопрос через "
            "несколько секунд.") in core.PAGE


def test_the_server_logs_enough_to_find_the_cause():
    """Причину неудачного запроса ищут по логу, а не по скриншотам."""
    import inspect
    source = inspect.getsource(core.agent_chat)
    for part in ("trace_id", "route=", "model=", "kind="):
        assert part in source, part


def test_the_free_question_always_reaches_the_model(monkeypatch, client):
    """Свободный вопрос не имеет права застрять в локальной ветке: сценарии
    отрабатывают только по своему ключу, всё остальное идёт в модель."""
    calls = {}

    def fake_llm(req, bundle, trace_id=None):
        calls["asked"] = req.message
        return {"answer": "ответ", "model": "m", "source": "llm",
                "response_id": None, "tools_used": [], "proposals": []}

    monkeypatch.setattr(core, "_call_openai_tool_agent", fake_llm)
    client.post("/agent/chat", json={
        "message": "По твоему какова цена покупки актива",
        "trace_id": "abcdefabcdef", "inputs": dict(core.DEFAULT_INPUTS),
        "tep": {k: dict(v) for k, v in core.TEP_DEFAULT.items()},
        "rates": [], "phasing": {}, "history": [], "selected_view": "all"})
    assert calls.get("asked") == "По твоему какова цена покупки актива"


def test_an_unknown_scenario_is_not_an_error(monkeypatch, client):
    """Неизвестный ключ сценария — это свободный вопрос, а не отказ."""
    calls = {}
    monkeypatch.setattr(core, "_call_openai_tool_agent",
                        lambda req, bundle, trace_id=None: calls.setdefault("ran", True) and {} or {
                            "answer": "ответ", "model": "m", "source": "llm",
                            "response_id": None, "tools_used": [], "proposals": []})
    response = client.post("/agent/chat", json={
        "message": "вопрос", "scenario": "выдуманный_сценарий",
        "trace_id": "beefbeefbeef", "inputs": dict(core.DEFAULT_INPUTS),
        "tep": {k: dict(v) for k, v in core.TEP_DEFAULT.items()},
        "rates": [], "phasing": {}, "history": [], "selected_view": "all"})
    assert response.status_code == 200
    assert calls.get("ran") is True


def test_the_server_timeout_is_not_shorter_than_ninety_seconds():
    assert core._PLATO_AI_TIMEOUT_SECONDS >= 90


# --- тяжёлый вопрос: работа падает — окно узнаёт причину ---------------------

def test_a_failure_is_remembered_under_the_run_id(client, monkeypatch):
    """Иначе окно, потерявшее соединение, опрашивает результат до конца и не
    узнаёт, что работа давно упала: «забираю готовый ответ» висит пять минут
    вместо честной причины."""
    def boom(req, bundle, trace_id=None):
        raise RuntimeError("модель не ответила")

    monkeypatch.setattr(core, "_call_openai_tool_agent", boom)
    trace = "dead0000beef"
    try:
        client.post("/agent/chat", json={
            "message": "тяжёлый вопрос", "trace_id": trace,
            "inputs": dict(core.DEFAULT_INPUTS),
            "tep": {k: dict(v) for k, v in core.TEP_DEFAULT.items()},
            "rates": [], "phasing": {}, "history": [], "selected_view": "all"})
    except Exception:
        pass

    stored = client.get("/agent/result/" + trace).json()
    assert stored.get("pending") is False
    assert "модель не ответила" in str(stored.get("error"))


def test_the_page_shows_the_stored_failure():
    """Причина показывается вместо бесконечного ожидания."""
    page = core.PAGE
    assert "x.error" in page and "detail:String(x.error)" in page


def test_the_page_shows_the_stage_while_it_waits():
    """«Долго» должно отличаться от «зависло»: пока ждём, видно, что делает
    движок."""
    page = core.PAGE
    assert "'/agent/trace/'+traceId" in page
    assert "соединение оборвалось, жду ответ" in page


def test_the_wait_is_long_enough_for_a_heavy_question():
    """Свободный вопрос гоняет goal_seek и simulate_change по нескольку раз;
    соединение до окна всё равно не держат, значит ждать дешевле, чем терять
    посчитанный ответ."""
    assert core._PLATO_AI_TIMEOUT_SECONDS >= 240
    assert "Date.now()+300000" in core.PAGE
