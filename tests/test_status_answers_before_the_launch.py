"""Перед раздачей ссылки на пятьсот человек `/status` отвечает сам.

Два вопроса задаются каждый раз перед выкаткой: кому открыт бот и жив ли
штатный калькулятор ГлавАПУ. Ответ на первый жил только в панели хостинга, на
второй — в `/telegram/status`, куда с телефона никто не ходит. Забытый в
`TELEGRAM_ALLOWED_USER_IDS` единственный ID превращает приглашение в «Доступ к
DevelopAid пока не открыт» для всех, кроме владельца, — и узнаётся это от них.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main  # noqa: E402
import main_legacy as core  # noqa: E402


# --- кому открыт бот ---------------------------------------------------------------

def test_an_empty_list_says_the_link_can_be_shared(monkeypatch):
    monkeypatch.delenv("TELEGRAM_ALLOWED_USER_IDS", raising=False)
    line = main._gate_status_line()
    assert "открыт всем" in line
    assert "⚠️" not in line


def test_a_filled_list_warns_with_the_count(monkeypatch):
    """Молча «список из двух» никого не спасёт: строка обязана кричать и
    называть, что чистить."""
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "111, 222")
    line = main._gate_status_line()
    assert "⚠️" in line
    assert "только 2 ID" in line
    assert "TELEGRAM_ALLOWED_USER_IDS" in line


def test_the_line_reaches_the_status_message(monkeypatch):
    """Иначе она есть в коде и её нет в чате."""
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "111")
    sent: list[str] = []
    monkeypatch.setattr(main, "_send_message", lambda chat_id, text, **kw: sent.append(text))
    main._status_message(4242, 4242)
    assert sent and "только 1 ID" in sent[0]


# --- сколько занял последний расчёт ГлавАПУ -----------------------------------------

def test_the_health_carries_the_last_timing(monkeypatch):
    monkeypatch.setitem(core._GLAVAPU_HEADLESS, "last_ms", {"total": 42000, "open": 900})
    monkeypatch.setattr(core, "_core_api_url", lambda path: "")
    assert core.glavapu_health()["last_total_ms"] == 42000


def test_a_ready_calculator_reports_its_seconds(monkeypatch):
    monkeypatch.setattr(main.core, "glavapu_health",
                        lambda: {"state": "готов", "where": "ядро", "last_total_ms": 42000})
    assert "последний расчёт 42 с" in main._glavapu_status_line()


def test_a_calculator_that_never_ran_says_nothing_about_seconds(monkeypatch):
    """Ноль секунд — это «ещё не считали», а не «мгновенно»."""
    monkeypatch.setattr(main.core, "glavapu_health",
                        lambda: {"state": "готов", "where": "ядро", "last_total_ms": 0})
    assert "последний расчёт" not in main._glavapu_status_line()
