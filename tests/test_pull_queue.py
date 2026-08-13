"""Работу забирает сервис модели: направление развёрнуто.

Из российского дата-центра до Render не дойти. Проверка с самой машины: до
`ya.ru` и `cloudflare.com` соединение устанавливается, до Render и до
`api.telegram.org` — таймаут на connect. Значит, дело не в группе безопасности и
не в адресе: закрыто само направление, и ни сроками, ни настройками это не
лечится.

Поэтому ядро больше не зовёт сервис модели, а кладёт задание у себя. Сервис
модели — которому наружу не мешает никто, он дозванивается и до OpenAI, и до
Telegram — забирает задание коротким опросом и приносит ответ обратно.

Очередь на диске: воркеров два, и задание, положенное одним, обязан видеть
другой. Забрать его может только один — файл переименовывается.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

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


@pytest.fixture
def core_side(monkeypatch):
    """Ядро: адрес сервиса задан, очередь включена, ключа нет."""
    monkeypatch.setattr(core, "_PLATO_AI_URL", "https://render.example/internal/plato/chat")
    monkeypatch.setattr(core, "_PLATO_AI_PROXY_SECRET", "s3cret")
    monkeypatch.setattr(core, "_PLATO_PULL_ENABLED", True)
    monkeypatch.setenv("PLATO_AI_PROXY_SECRET", "s3cret")
    monkeypatch.setattr(core, "_PLATO_QUEUE_POLL_SECONDS", 0.05)
    return {"X-Plato-Secret": "s3cret"}


# --- маршрут --------------------------------------------------------------

def test_the_route_names_the_reversed_direction(core_side):
    assert core._plato_route() == "render_pull"


def test_without_the_switch_nothing_changes(monkeypatch):
    """Умолчание — прежняя схема: переключатель включают там, где прямая
    дорога закрыта, а не везде."""
    monkeypatch.setattr(core, "_PLATO_AI_URL", "https://render.example/internal/plato/chat")
    monkeypatch.setattr(core, "_PLATO_PULL_ENABLED", False)
    assert core._plato_route() == "render_proxy"


def test_the_call_goes_to_the_queue_not_to_the_network(core_side, monkeypatch):
    seen = {}
    monkeypatch.setattr(core, "_openai_pull_request",
                        lambda payload, budget_seconds=None: seen.setdefault("queued", payload))
    monkeypatch.setattr(core, "_openai_proxy_request",
                        lambda payload, budget_seconds=None: pytest.fail("вызван закрытый путь"))
    core._openai_responses_request({"model": "m"})
    assert seen["queued"] == {"model": "m"}


# --- круг: положили, забрали, вернули ----------------------------------------

def test_a_job_travels_there_and_back(client, core_side, monkeypatch):
    answer = {"id": "resp_pull", "output": []}
    result: dict = {}

    def worker():
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            job = client.get("/internal/plato/queue?wait=1", headers=core_side).json()
            if job.get("job_id"):
                client.post(f"/internal/plato/queue/{job['job_id']}",
                            json={"answer": answer}, headers=core_side)
                return
            time.sleep(0.05)

    threading.Thread(target=worker, daemon=True).start()
    result = core._openai_pull_request({"model": "gpt-5.6"}, budget_seconds=10)
    assert result == answer


def test_the_payload_reaches_the_worker_untouched(client, core_side):
    payload = {"model": "gpt-5.6", "input": [{"role": "user", "content": "LLCR?"}]}
    threading.Thread(
        target=lambda: core._openai_pull_request(payload, budget_seconds=3),
        daemon=True).start()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job = client.get("/internal/plato/queue?wait=1", headers=core_side).json()
        if job.get("job_id"):
            assert job["payload"] == payload
            return
        time.sleep(0.05)
    pytest.fail("задание не доехало до очереди")


def test_a_failure_of_the_model_comes_back_too(client, core_side):
    """Молчание оставило бы ядро ждать до конца срока впустую."""
    def worker():
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            job = client.get("/internal/plato/queue?wait=1", headers=core_side).json()
            if job.get("job_id"):
                client.post(f"/internal/plato/queue/{job['job_id']}",
                            json={"error": "OpenAI API: rate limit", "status": 429},
                            headers=core_side)
                return
            time.sleep(0.05)

    threading.Thread(target=worker, daemon=True).start()
    with pytest.raises(core.HTTPException) as exc:
        core._openai_pull_request({"model": "m"}, budget_seconds=8)
    assert "rate limit" in str(exc.value.detail)
    assert exc.value.status_code == 429


def test_nobody_taking_the_job_is_an_honest_refusal(core_side):
    with pytest.raises(core.HTTPException) as exc:
        core._openai_pull_request({"model": "m"}, budget_seconds=0.5)
    assert exc.value.status_code == 504
    assert "не забрал задание" in str(exc.value.detail)
    assert "PLATO_PULL_URL" in str(exc.value.detail)


def test_an_expired_job_does_not_stay_in_the_queue(client, core_side):
    """Иначе брошенное задание заберут через час и посчитают впустую."""
    with pytest.raises(core.HTTPException):
        core._openai_pull_request({"model": "m"}, budget_seconds=0.5)
    assert client.get("/internal/plato/queue?wait=0", headers=core_side).json() == {}


# --- очередь ------------------------------------------------------------------

def test_a_job_is_taken_once_even_by_two_pollers(client, core_side):
    """Воркеров два: задание, посчитанное дважды, стоит денег дважды."""
    core._PLATO_STAGE_DIR.mkdir(parents=True, exist_ok=True)
    core._plato_job_path("aa11aa11aa11").write_text(
        json.dumps({"at": time.time(), "payload": {"model": "m"}}), encoding="utf-8")
    first = client.get("/internal/plato/queue?wait=0", headers=core_side).json()
    second = client.get("/internal/plato/queue?wait=0", headers=core_side).json()
    assert first.get("job_id") == "aa11aa11aa11"
    assert second == {}


def test_an_empty_queue_answers_empty_not_an_error(client, core_side):
    assert client.get("/internal/plato/queue?wait=0", headers=core_side).json() == {}


def test_the_queue_is_closed_without_the_secret(client, core_side):
    assert client.get("/internal/plato/queue").status_code == 403
    assert client.post("/internal/plato/queue/aa11aa11aa11",
                       json={"answer": {"id": "x"}}).status_code == 403


def test_the_queue_is_closed_where_it_is_not_switched_on(client, monkeypatch):
    monkeypatch.setattr(core, "_PLATO_PULL_ENABLED", False)
    monkeypatch.setenv("PLATO_AI_PROXY_SECRET", "s3cret")
    response = client.get("/internal/plato/queue", headers={"X-Plato-Secret": "s3cret"})
    assert response.status_code == 503
    assert "PLATO_AI_PULL" in response.json()["detail"]


def test_a_broken_job_number_is_refused(client, core_side):
    assert client.post("/internal/plato/queue/не-номер", json={"answer": {"id": "x"}},
                       headers=core_side).status_code == 400


# --- сторона сервиса модели ---------------------------------------------------

def test_the_worker_computes_and_returns(monkeypatch):
    """Один круг работника: забрал, посчитал, отдал."""
    monkeypatch.setattr(core, "_openai_direct_request",
                        lambda payload, budget_seconds=None: {"id": "resp_worker"})
    sent = {}

    class FakeResponse:
        def __init__(self, body: bytes):
            self._body = body

        def read(self, *args):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(request, timeout=None):
        if request.get_method() == "GET":
            assert "/internal/plato/queue?wait=" in request.full_url
            return FakeResponse(json.dumps(
                {"job_id": "bb22bb22bb22", "payload": {"model": "m"}}).encode())
        sent["url"] = request.full_url
        sent["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse(b"{}")

    monkeypatch.setattr(core.urllib.request, "urlopen", fake_urlopen)
    assert core._plato_pull_once("https://core.example", {"X-Plato-Secret": "s3cret"}) is True
    assert sent["url"].endswith("/internal/plato/queue/bb22bb22bb22")
    assert sent["body"]["answer"] == {"id": "resp_worker"}


def test_the_worker_reports_a_failure_instead_of_swallowing_it(monkeypatch):
    def boom(payload, budget_seconds=None):
        raise core.HTTPException(status_code=502, detail="OpenAI API: gateway")

    monkeypatch.setattr(core, "_openai_direct_request", boom)
    sent = {}

    class FakeResponse:
        def __init__(self, body: bytes):
            self._body = body

        def read(self, *args):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(request, timeout=None):
        if request.get_method() == "GET":
            return FakeResponse(json.dumps(
                {"job_id": "cc33cc33cc33", "payload": {}}).encode())
        sent["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse(b"{}")

    monkeypatch.setattr(core.urllib.request, "urlopen", fake_urlopen)
    core._plato_pull_once("https://core.example", {})
    assert "gateway" in sent["body"]["error"]
    assert sent["body"]["status"] == 502


def test_the_worker_starts_only_where_the_key_is(monkeypatch):
    import inspect
    source = inspect.getsource(core._start_plato_pull_worker)
    assert "_PLATO_PULL_URL and not _PLATO_AI_URL" in source
    assert "OPENAI_API_KEY" in source


# --- видно снаружи ------------------------------------------------------------

def test_the_status_shows_the_queue(core_side):
    status = core.agent_status()["pull_queue"]
    assert status["enabled"] is True
    assert "waiting_jobs" in status


def test_the_selftest_names_a_silent_worker(client, core_side, monkeypatch):
    core._PLATO_SELFTEST.update(at=0.0, result=None)
    monkeypatch.setattr(core, "_openai_responses_request",
                        lambda payload, budget_seconds=None: (_ for _ in ()).throw(
                            core.HTTPException(status_code=504,
                                               detail="Сервис модели не забрал задание за 60 с.")))
    verdict = client.get("/agent/selftest").json()["verdict"]
    assert "не забирает задания" in verdict
    assert "PLATO_PULL_URL" in verdict


def test_a_working_pull_chain_says_where_the_answer_came_from(client, core_side, monkeypatch):
    """«Через этот сервер» верно только для локального ключа: в обратной схеме
    ответ тоже приходит с Render, просто он сам за ним пришёл."""
    core._PLATO_SELFTEST.update(at=0.0, result=None)
    monkeypatch.setattr(core, "_openai_responses_request",
                        lambda payload, budget_seconds=None: {"id": "resp_ok"})
    verdict = client.get("/agent/selftest").json()["verdict"]
    assert "через Render, по очереди заданий" in verdict


def test_the_keepalive_is_silent_in_pull_mode():
    """Пинговать некого: до сервиса не дойти, ради этого схему и развернули."""
    import inspect
    source = inspect.getsource(core._start_plato_keepalive)
    assert "not _PLATO_PULL_ENABLED" in source
