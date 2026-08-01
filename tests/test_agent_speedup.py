"""Платон отвечает на кнопки движком, помнит ответы и показывает стадии.

Ответ на кнопку занимал минуту по трём причинам сразу. Каждый вопрос шёл в
модель, даже когда ответ целиком считает движок: «Структура расходов» — это
explain_metric и форматирование, решать там нечего. Один и тот же вопрос по
тем же вводным считался заново. А пока запрос шёл, окно показывало одну
надпись, и «долго» было неотличимо от «зависло».

Здесь закреплено: сценарии кнопок не ходят в модель вовсе, повторный вопрос
берётся из кэша, стадия запроса доступна для опроса со страницы — и всё это
переживает границу воркера, потому что лежит на диске.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main as wrapper  # noqa: E402

core = wrapper.core
client = TestClient(wrapper.app)


def ask(scenario: str = "", message: str = "Вопрос по модели", **extra):
    body = {
        "message": message,
        "scenario": scenario,
        "inputs": dict(core.DEFAULT_INPUTS),
        "tep": dict(core.TEP_DEFAULT),
        "rates": [],
        "phasing": {},
        "history": [],
        "selected_view": "all",
    }
    body.update(extra)
    return client.post("/agent/chat", json=body)


@pytest.fixture(autouse=True)
def _fresh_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "_PLATO_STAGE_DIR", tmp_path / "agent")
    # Лимит запросов в этих тестах не проверяется — они бьют чаще человека.
    monkeypatch.setattr(core, "_agent_rate_limit", lambda request: None)


@pytest.fixture(autouse=True)
def _no_openai(monkeypatch):
    """Сценарии кнопок не имеют права ходить в модель — поход роняет тест."""
    def _forbidden(payload):
        raise AssertionError("локальный сценарий пошёл в OpenAI")
    monkeypatch.setattr(core, "_openai_responses_request", _forbidden)


# --- локальные сценарии ----------------------------------------------------

SCENARIOS = list(core._AGENT_LOCAL_SCENARIOS)


def test_every_quick_button_has_a_local_scenario():
    """Семь кнопок панели — семь сценариев, и все считаются движком."""
    assert SCENARIOS == [
        "expense_structure", "llcr_breakdown", "max_purchase_price",
        "max_construction_cost", "anomalies", "phase_recovery",
        "purchase_evaluation",
    ]
    for scenario in SCENARIOS:
        assert f"'{scenario}')" in core.PAGE, f"кнопка «{scenario}» не передаёт сценарий"


@pytest.mark.parametrize("scenario", ["expense_structure", "llcr_breakdown",
                                      "anomalies", "phase_recovery"])
def test_the_button_is_answered_by_the_engine(scenario):
    """Модель недоступна (фикстура роняет её вызов), а ответ всё равно есть."""
    response = ask(scenario)

    assert response.status_code == 200
    data = response.json()
    assert data["source"] == "local"
    assert data["model"] == "developaid-engine"
    assert len(data["answer"]) > 60


def test_the_expense_structure_carries_the_engine_numbers():
    answer = ask("expense_structure").json()["answer"]

    result = core.calculate(core.CalcRequest(
        inputs=dict(core.DEFAULT_INPUTS), tep=dict(core.TEP_DEFAULT), rates=[]))
    top = (result["report"]["expense_structure"] or [])[0]
    formatted = core._agent_mln(top["value"] / 1e6)

    assert str(top["label"]) in answer
    assert formatted in answer, f"в ответе нет числа движка {formatted}"


def test_the_llcr_breakdown_shows_numerator_and_denominator():
    answer = ask("llcr_breakdown").json()["answer"]

    assert "Числитель" in answer
    assert "Знаменатель" in answer
    assert "выборка ПФ" in answer


def test_an_unknown_scenario_is_not_trusted(monkeypatch):
    """Неизвестный id не должен уронить запрос — он уходит обычным путём."""
    called = {}

    def fake_agent(req, bundle, trace_id=""):
        called["yes"] = True
        return {"answer": "ок", "model": "m", "response_id": None,
                "tools_used": [], "proposals": []}

    monkeypatch.setattr(core, "_call_openai_tool_agent", fake_agent)
    response = ask("no_such_scenario")

    assert response.status_code == 200
    assert called.get("yes"), "запрос с неизвестным сценарием не дошёл до модели"


# --- кэш -------------------------------------------------------------------

def test_the_same_question_is_answered_from_the_cache(monkeypatch):
    first = ask("expense_structure").json()
    assert first["cached"] is False

    # Повторный вопрос не имеет права пересчитывать модель.
    def _no_model(*args, **kwargs):
        raise AssertionError("повторный вопрос пересчитал модель")
    monkeypatch.setattr(core, "_run_authoritative_model", _no_model)

    second = ask("expense_structure").json()
    assert second["cached"] is True
    assert second["answer"] == first["answer"]


def test_different_inputs_do_not_share_the_cache():
    first = ask("llcr_breakdown").json()

    inputs = dict(core.DEFAULT_INPUTS)
    inputs["purchase_price_mln"] = 500
    second = ask("llcr_breakdown", inputs=inputs).json()

    assert second["cached"] is False
    assert second["answer"] != first["answer"]


def test_the_cache_expires(monkeypatch):
    key_seen = {}
    original = core._plato_answer_put

    def spy(key, payload):
        key_seen["key"] = key
        original(key, payload)

    monkeypatch.setattr(core, "_plato_answer_put", spy)
    ask("anomalies")
    assert core._plato_answer_get(key_seen["key"]) is not None

    # Состарим запись: кэш живёт десять минут, а не вечно.
    import time as real_time
    now = real_time.time()
    monkeypatch.setattr(core.time, "time", lambda: now + 601)
    assert core._plato_answer_get(key_seen["key"]) is None


# --- trace -----------------------------------------------------------------

def test_the_stage_is_readable_while_the_answer_is_prepared():
    """Страница опрашивает стадию по id, который сгенерировала сама."""
    trace_id = "ab12cd34ef56"
    response = ask("expense_structure", trace_id=trace_id)

    assert response.json()["trace_id"] == trace_id
    stage = client.get(f"/agent/trace/{trace_id}").json()
    assert stage["stage"] == "done"
    assert stage["label"]


def test_a_foreign_trace_id_is_replaced_not_trusted():
    response = ask("anomalies", trace_id="../../etc/passwd")

    trace_id = response.json()["trace_id"]
    assert core._TRACE_ID_RE.fullmatch(trace_id), "подставной trace_id пролез в ответ"


def test_an_invalid_trace_id_is_rejected_by_the_poll():
    assert client.get("/agent/trace/{bad}").status_code == 400


def test_an_unknown_trace_reads_as_unknown_not_error():
    assert client.get("/agent/trace/deadbeef0000").json()["stage"] == "unknown"
