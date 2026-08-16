"""/status бота предупреждает, когда связка со штатным ГлавАПУ сбилась.

Сбой связки — предохранитель после срыва браузера, выключенный headless,
недоступное ядро — был виден только в предупреждении карточки ТЭП: расчёт
уходил на запасные формулы, а владелец узнавал об этом из расхождения с
сайтом (Гродненская, 16.08.2026). /status смотрят, когда что-то проверяют, —
здесь сбой и должен кричать, чтобы задача ставилась по строке статуса, а не
по загадочным цифрам.

Браузер живёт на ядре, /status спрашивают у бота на Render, поэтому состояние
идёт маршрутом /glavapu/health: ядро отвечает о себе, Render переспрашивает
ядро.

Запуск: python3 -m pytest tests/test_status_warns_about_glavapu_link.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core
CHAT_ID = 424242


@pytest.fixture()
def sent(monkeypatch):
    messages: list[dict] = []

    def fake_send(chat_id, text, *, reply_markup=None, **kwargs):
        messages.append({"chat_id": chat_id, "text": text})
        return {"ok": True}

    monkeypatch.setattr(wrapper, "_ORIGINAL_SEND_MESSAGE", fake_send)
    return messages


def test_the_health_route_reports_the_local_state():
    """Без адреса ядра маршрут отвечает о себе — состоянием и счётчиками."""
    routes = {getattr(route, "path", "") for route in wrapper.app.routes}
    assert "/glavapu/health" in routes
    state = core.glavapu_health()
    assert state["state"], state
    for key in ("runs", "fallbacks", "last_ok", "last_error"):
        assert key in state, f"в ответе нет счётчика {key}"


def test_the_health_route_asks_the_core_when_it_is_remote(monkeypatch):
    """На Render правда живёт на ядре: маршрут переспрашивает его."""
    import io
    import json as jsonlib

    asked: list[str] = []

    def fake_urlopen(request, timeout=0):
        asked.append(request.full_url)
        return io.BytesIO(jsonlib.dumps({"state": "готов", "where": "ядро"}).encode("utf-8"))

    monkeypatch.setattr(core, "_core_api_url",
                        lambda path: "http://core.test" + path)
    monkeypatch.setattr(core.urllib.request, "urlopen", fake_urlopen)
    assert core.glavapu_health() == {"state": "готов", "where": "ядро"}
    assert asked == ["http://core.test/glavapu/health"]


def test_a_dead_core_is_a_loud_state_not_an_exception(monkeypatch):
    def broken(request, timeout=0):
        raise OSError("нет маршрута")

    monkeypatch.setattr(core, "_core_api_url", lambda path: "http://core.test" + path)
    monkeypatch.setattr(core.urllib.request, "urlopen", broken)
    state = core.glavapu_health()
    assert state["state"] == "ядро недоступно"
    assert "нет маршрута" in state["hint"]


def test_status_shows_a_ready_link_quietly(sent, monkeypatch):
    monkeypatch.setattr(core, "glavapu_health", lambda: {
        "state": "готов", "where": "ядро", "runs": 12, "fallbacks": 2})
    wrapper._status_message(CHAT_ID, CHAT_ID)
    text = sent[-1]["text"]
    assert "ГлавАПУ: штатный калькулятор готов" in text
    assert "запусков 12, фолбэков 2" in text
    assert "⚠️" not in text.split("ГлавАПУ")[1].split("\n")[0]


def test_status_shouts_when_the_link_is_broken(sent, monkeypatch):
    """Предохранитель — это задача владельцу, а не строка мелким шрифтом."""
    monkeypatch.setattr(core, "glavapu_health", lambda: {
        "state": "предохранитель", "where": "ядро", "blocked_for": 240,
        "hint": "Браузер сорвался; следующая попытка через 240 с.",
        "last_error": "genplan.tech: timeout", "runs": 5, "fallbacks": 3})
    wrapper._status_message(CHAT_ID, CHAT_ID)
    text = sent[-1]["text"]
    assert "⚠️" in text and "предохранитель" in text
    assert "запасными формулами" in text
    assert "genplan.tech: timeout" in text


def test_a_broken_health_call_does_not_kill_status(sent, monkeypatch):
    def boom():
        raise RuntimeError("совсем сломалось")

    monkeypatch.setattr(core, "glavapu_health", boom)
    wrapper._status_message(CHAT_ID, CHAT_ID)
    text = sent[-1]["text"]
    assert "состояние не проверить" in text
    assert wrapper._RUNTIME_VERSION in text, "статус обязан дойти целиком"
