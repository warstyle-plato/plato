"""Контекст Платона Сергеевича переживает переход между воркерами.

Сервис работает в несколько процессов, и память у них раздельная: страница
отправляет расчёт в один воркер, а нажатие «Спросить Платона» приходит вебхуком
в другой. Тот отвечал «Платону пока не передан проект» по только что
посчитанному проекту. Контекст дублируется на диск: словари — быстрый кеш,
диск — общая память воркеров.
Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

CONTEXT = {
    "session": "s-1", "chat_id": 42,
    "inputs": {"purchase_price_mln": 700}, "tep": {},
    "rates": [], "phasing": {}, "selected_view": "all",
}


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setattr(wrapper, "_STATE_DIR", tmp_path)
    for name in ("_PLATON_CONTEXT_BY_SESSION", "_PLATON_LAST_SESSION", "_PLATON_TEP_CONTEXT"):
        monkeypatch.setattr(wrapper, name, {})
    return tmp_path


def forget_memory(monkeypatch):
    """Имитирует другой воркер: та же файловая система, пустая память."""
    for name in ("_PLATON_CONTEXT_BY_SESSION", "_PLATON_LAST_SESSION", "_PLATON_TEP_CONTEXT"):
        monkeypatch.setattr(wrapper, name, {})


def test_full_model_context_survives_a_worker_switch(state, monkeypatch):
    wrapper._state_write("session:s-1", CONTEXT)
    wrapper._state_write("chat:42", {"session": "s-1"})
    forget_memory(monkeypatch)

    session, context = wrapper._resolve_context(42)
    assert session == "s-1"
    assert context["inputs"]["purchase_price_mln"] == 700
    assert wrapper._has_model_context(42)


def test_bot_tep_context_survives_a_worker_switch(state, monkeypatch):
    wrapper._state_write("chat:42", {"tep_context": {**CONTEXT, "origin": "tep"}})
    forget_memory(monkeypatch)

    session, context = wrapper._resolve_context(42)
    assert session == ""
    assert context["origin"] == "tep"


def test_another_chat_gets_nothing(state, monkeypatch):
    wrapper._state_write("session:s-1", CONTEXT)
    wrapper._state_write("chat:42", {"session": "s-1"})
    forget_memory(monkeypatch)
    assert wrapper._resolve_context(99) == ("", {})


def test_memory_is_refilled_so_the_disk_is_read_once(state, monkeypatch):
    wrapper._state_write("session:s-1", CONTEXT)
    wrapper._state_write("chat:42", {"session": "s-1"})
    forget_memory(monkeypatch)
    wrapper._resolve_context(42)
    assert wrapper._PLATON_CONTEXT_BY_SESSION["s-1"]["chat_id"] == 42
    assert wrapper._PLATON_LAST_SESSION[42] == "s-1"


def test_write_is_atomic_and_leaves_no_temporary_files(state):
    wrapper._state_write("session:s-1", CONTEXT)
    assert not list(state.glob("*.tmp")), "временный файл остался — сосед прочитает половину записи"
    stored = json.loads(next(state.glob("*.json")).read_text(encoding="utf-8"))
    assert stored["chat_id"] == 42


def test_unreadable_state_does_not_break_the_bot(state, monkeypatch):
    """Диск — подстраховка: его отказ не должен ронять ответ пользователю."""
    monkeypatch.setattr(wrapper, "_STATE_DIR", state / "нет" / "такого")
    wrapper._state_write("session:s-1", CONTEXT)
    assert wrapper._state_read("session:s-1") in ({}, CONTEXT)
    assert wrapper._resolve_context(42) == ("", {})


def test_stale_state_is_pruned(state):
    import os
    import time
    wrapper._state_write("session:old", CONTEXT)
    old = next(state.glob("*.json"))
    ancient = time.time() - wrapper._STATE_TTL_SECONDS - 60
    os.utime(old, (ancient, ancient))
    wrapper._state_write("session:new", CONTEXT)
    assert not old.exists(), "просроченный контекст должен убираться сам"
