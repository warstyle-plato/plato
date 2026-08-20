"""Экономика — за входом через бота, участок и ТЭП — открыты.

Решение владельца 18.08.2026: «счёт виден, вывод — за входом». Человек без
входа видит участок, нормативный ТЭП и градостроительные ограничения — то, что
показывает, умеем ли мы что-то вообще. Экономика, вердикт, LLCR, отчёт и
выгрузки принадлежат конкретному человеку, и за ними нужен вход.

Здесь закреплено:

- `/calculate` и `/calculate-phased` без сессии отвечают 401, а не считают;
- сессия входа и ключ администратора открывают их одинаково;
- без токена бота гейт честно выключен: проверять подпись нечем, и порядок
  остаётся прежним, а не запертым для всех;
- страница не стучится в закрытую дверь на каждой правке поля, а показывает,
  что делать, — расчёт зовётся при изменении любой вводной.

Запуск: python3 -m pytest tests/test_calculation_is_behind_the_login.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as _wrapper  # noqa: E402

core = _wrapper.core
client = TestClient(core.app)

CHAT_ID = 5150

# Настоящие вводные движка: гейт проверяется на работающем расчёте, иначе
# «401» и «падение от неполных данных» неотличимы.
MODEL = {"inputs": dict(core.DEFAULT_INPUTS), "tep": {k: dict(v) for k, v in core.TEP_DEFAULT.items()},
         "rates": []}


@pytest.fixture()
def gate(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:calc-gate-test-token")
    monkeypatch.setenv("DEVELOPAID_ADMIN_IDS", "777")
    monkeypatch.setenv("DEVELOPAID_ADMIN_KEY", "kluch")
    return None


def test_without_a_login_the_economics_is_not_calculated(gate):
    answer = client.post("/calculate", json=MODEL)
    assert answer.status_code == 401
    assert "вход" in answer.json()["detail"].lower()
    assert "Расчёт экономики" in answer.json()["detail"]


def test_a_session_opens_the_calculation(gate):
    session = core._telegram_session(CHAT_ID, [])
    answer = client.post("/calculate", json={**MODEL, "session": session})
    assert answer.status_code == 200
    assert "finance" in answer.json()


def test_the_owner_key_opens_it_too(gate):
    answer = client.post("/calculate", json={**MODEL, "access_key": "kluch"})
    assert answer.status_code == 200


def test_the_phased_calculation_is_behind_the_same_door(gate):
    body = {**MODEL, "phasing": {"enabled": True, "phase_count": 2}}
    assert client.post("/calculate-phased", json=body).status_code == 401

    body["session"] = core._telegram_session(CHAT_ID, [])
    assert client.post("/calculate-phased", json=body).status_code == 200


def test_without_a_bot_token_the_gate_is_honestly_off(monkeypatch):
    """Проверять подпись нечем — значит порядок прежний, а не заперт для всех."""
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setattr(core, "_telegram_token", lambda: "")
    assert client.post("/calculate", json=MODEL).status_code == 200


def test_the_status_tells_the_page_about_the_gate(gate):
    assert client.get("/projects/status").json()["calc_requires_login"] is True


def test_the_page_does_not_knock_on_a_closed_door():
    """Расчёт зовётся при правке любой вводной: ловить 401 на каждом изменении
    значит слать десятки отказов вместо одного ответа человеку."""
    body = core.PAGE[core.PAGE.index("async function calculate(){"):]
    body = body[:body.index("function row(label,value)")]
    assert "if(calcNeedsLogin()){renderCalcLocked();return null}" in body
    assert body.index("calcNeedsLogin()") < body.index("fetch('/calculate")
    assert body.count("session:activeSession(),access_key:projectsAdminKey") == 2, (
        "оба маршрута расчёта несут, чем открыть дверь")


def test_the_page_says_what_is_open_and_what_is_not():
    page = core.PAGE
    body = page[page.index("function renderCalcLocked("):page.index("function hideCalcLocked(")]
    assert "после входа через Telegram" in body
    assert "Участок, ТЭП и градостроительные ограничения считаются без входа" in body
    assert "openLogin()" in body, "из плашки можно войти, а не только прочитать"
    assert 'id="calcLocked"' in page

    report = page[page.index('<div id="report" class="panel">'):]
    assert report.index('id="calcLocked"') < report.index("report-hero"), (
        "плашка стоит там, где человек ждал числа")


def test_the_gate_is_off_on_the_page_when_the_server_says_so():
    body = core.PAGE[core.PAGE.index("function calcNeedsLogin()"):]
    body = body[:body.index("async function calcRefusal(")]
    assert "calcRequiresLogin" in body
    assert "activeSession()" in body and "projectsAdminKey" in body


def test_a_successful_calculation_removes_the_plate():
    body = core.PAGE[core.PAGE.index("function renderResult(){"):]
    assert "hideCalcLocked();" in body[:300]
