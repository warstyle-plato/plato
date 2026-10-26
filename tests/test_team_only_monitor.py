"""Монитор и сводка руководству — для команды владельца, а не для всех вошедших.

Решение владельца 22.10.2026: вход через Telegram открывает расчёт и личный
кабинет, а данные проектов команды — финансы, споры, бюджеты, записи,
объединение проектов, рассылка — видит только команда: ключ администратора,
ключ кабинета рынка или человек из `DEVELOPAID_ADMIN_IDS` / `DEVELOPAID_TEAM_IDS`
(по умолчанию пуст). Здесь закреплено:

- обычный вошедший получает 403 с причиной простыми словами, без входа — 401;
- команда проходит каждым из трёх способов;
- все маршруты данных монитора читают одно решение (`_require_team_access`),
  а не прежний пропуск «вошёл».

Запуск: python3 -m pytest tests/test_team_only_monitor.py -q
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as _wrapper  # noqa: E402

core = _wrapper.core
client = TestClient(core.app, raise_server_exceptions=False)
OWNER, CLIENT = 777, 5050
ROUTES = ["/monitor/report", "/monitor/legal", "/monitor/notes", "/monitor/budget",
          "/monitor/report/projects", "/monitor/merge", "/monitor/credit",
          "/monitor/credit/data"]


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:team-only-test-token")
    monkeypatch.setenv("DEVELOPAID_ADMIN_IDS", str(OWNER))
    monkeypatch.setenv("DEVELOPAID_ADMIN_KEY", "kluch")
    monkeypatch.setenv("MARKET_CABINET_KEY", "team-test-key")
    monkeypatch.delenv("DEVELOPAID_TEAM_IDS", raising=False)
    yield


def post(path: str, session: str = "", key: str = "", headers: dict | None = None):
    # Поля с запасом на модели всех маршрутов: отказ доступа обязан прийти
    # раньше разбора дела, а не прятаться за 422.
    return client.post(path, json={"project": "проверка", "session": session, "key": key,
                                   "sources": [], "target": "проверка", "source": "проверка",
                                   "taken_at": "2026-10-22", "content_base64": ""},
                       headers=headers or {})


@pytest.mark.parametrize("path", ROUTES)
def test_a_client_login_does_not_open_the_team_data(path):
    answer = post(path, session=core._telegram_session(CLIENT, []))
    assert answer.status_code == 403, answer.text
    assert "для команды владельца" in answer.json()["detail"]


@pytest.mark.parametrize("path", ROUTES)
def test_without_a_login_the_answer_is_log_in(path):
    answer = post(path)
    assert answer.status_code == 401 and "Telegram" in answer.json()["detail"]


@pytest.mark.parametrize("path", ROUTES)
def test_the_team_passes_every_way(path, monkeypatch):
    for answer in (post(path, session=core._telegram_session(OWNER, [])),
                   post(path, key="kluch"),
                   post(path, headers={"X-Market-Key": "team-test-key"})):
        assert answer.status_code not in (401, 403), answer.text
    monkeypatch.setenv("DEVELOPAID_TEAM_IDS", str(CLIENT))
    answer = post(path, session=core._telegram_session(CLIENT, []))
    assert answer.status_code not in (401, 403), answer.text


def test_every_monitor_data_route_reads_the_team_gate():
    """Проверка по читателям: каждый маршрут данных монитора зовёт командный
    пропуск, а не прежний «вошёл». Оболочки страниц и подписанные ботом
    `/internal/*` — без него."""
    source = (Path(__file__).resolve().parent.parent / "engine" / "monitor.py").read_text(
        encoding="utf-8")
    assert "_require_web_access(" not in source
    blocks = re.split(r'(?m)^@app\.(?:get|post)\("([^"]+)"', source)[1:]
    for path, body in zip(blocks[0::2], blocks[1::2]):
        if path.startswith("/internal/") or path in {"/report", "/monitor"}:
            continue
        assert "_require_team_access(" in body.split("\n@app.")[0], path
