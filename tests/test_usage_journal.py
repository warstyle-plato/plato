"""Сколько людей пользуются ботом и о чём спрашивают.

Пользователей считали по ощущениям, а вопросы читали через плечо. Ни того, ни
другого не хватает, чтобы решать, что делать дальше: непонятно, растёт ли
аудитория, и непонятно, о чём её спрашивают чаще всего.

Журнал пишется одной строкой на событие в файл дня. Учёт стоит там, куда
сходятся все обращения, а не по веткам разбора: ветка, добавленная позже, иначе
молча выпадет из счёта. Свод и выгрузка закрыты списком администраторов —
чужие вопросы не та вещь, которую отдают по умолчанию.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core


@pytest.fixture(autouse=True)
def journal_on(monkeypatch):
    monkeypatch.setenv("DEVELOPAID_USAGE_JOURNAL", "on")


# --- сама запись --------------------------------------------------------------

def test_an_event_reaches_the_journal():
    core.usage_track("message", chat_id=11, user_id=11, name="@ivan", text="Привет")
    events = core.usage_events(1)
    assert len(events) == 1
    assert events[0]["text"] == "Привет"
    assert events[0]["name"] == "@ivan"
    assert events[0]["surface"] == "bot"


def test_two_workers_append_instead_of_overwriting():
    """Воркеров два, файл дня один: перезапись стоила бы половины журнала."""
    for index in range(20):
        core.usage_track("message", chat_id=index, user_id=index, text=f"вопрос {index}")
    assert len(core.usage_events(1)) == 20


def test_a_long_text_is_trimmed_not_dropped():
    core.usage_track("question", chat_id=1, user_id=1, text="я" * 4000)
    assert len(core.usage_events(1)[0]["text"]) == core._USAGE_TEXT_LIMIT


def test_a_broken_line_does_not_cost_the_whole_day():
    core.usage_track("message", chat_id=1, user_id=1, text="целая строка")
    path = next(core._USAGE_DIR.glob("events-*.jsonl"))
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"at": 1, "text": "обо')  # оборванная запись
    assert [e["text"] for e in core.usage_events(1)] == ["целая строка"]


def test_the_journal_can_be_switched_off(monkeypatch):
    """Журнал пользовательских текстов — данные людей: решение хранить их
    принимает владелец, а не код."""
    monkeypatch.setenv("DEVELOPAID_USAGE_JOURNAL", "off")
    core.usage_track("message", chat_id=1, user_id=1, text="не должно записаться")
    assert core.usage_events(1) == []


def test_the_journal_never_breaks_the_answer(monkeypatch):
    """Учёт — удобство. Ронять из-за него ответ человеку нельзя."""
    monkeypatch.setattr(core, "_USAGE_DIR", Path("/proc/нет-такого/каталога"))
    core.usage_track("message", chat_id=1, user_id=1, text="ответ важнее учёта")


def test_old_days_are_swept(monkeypatch):
    monkeypatch.setattr(core, "_USAGE_KEEP_DAYS", 2)
    core._USAGE_SWEPT.clear()
    core._USAGE_DIR.mkdir(parents=True, exist_ok=True)
    (core._USAGE_DIR / "events-2020-01-01.jsonl").write_text("{}\n", encoding="utf-8")
    core.usage_track("message", chat_id=1, user_id=1, text="свежее")
    assert not (core._USAGE_DIR / "events-2020-01-01.jsonl").exists()


# --- свод ---------------------------------------------------------------------

def _seed():
    core.usage_track("command", chat_id=1, user_id=1, name="@one", text="/vritep")
    core.usage_track("command", chat_id=2, user_id=2, name="@two", text="/vritep Москва")
    core.usage_track("command", chat_id=2, user_id=2, name="@two", text="/platon")
    core.usage_track("button", chat_id=1, user_id=1, text="ask_platon")
    core.usage_track("question", chat_id=1, user_id=1, text="Какая цена покупки предельная?")
    core.usage_track("question", surface="site", text="Почему такой LLCR?")


def test_the_summary_counts_people_not_events():
    _seed()
    summary = core.usage_summary(30)
    assert summary["users_today"] == 2
    assert summary["users_window"] == 2
    assert summary["events_window"] == 6


def test_the_site_questions_are_counted_apart_from_the_bot():
    """Сайт и бот — разные аудитории, и складывать их в одно число значит не
    знать ни той, ни другой."""
    _seed()
    summary = core.usage_summary(30)
    assert summary["questions_bot"] == 1
    assert summary["questions_site"] == 1


def test_the_commands_are_counted_by_name_not_by_full_text():
    """«/vritep Москва» — та же команда, что и «/vritep»."""
    _seed()
    assert dict(core.usage_summary(30)["top_commands"])["/vritep"] == 2


def test_a_returning_user_is_not_a_new_one():
    old = time.time() - 60 * 86400
    core._USAGE_DIR.mkdir(parents=True, exist_ok=True)
    core._usage_path(core._usage_day(old)).write_text(
        json.dumps({"at": old, "surface": "bot", "kind": "message",
                    "chat": 1, "user": 1, "name": "@one", "text": "давно"}) + "\n",
        encoding="utf-8")
    core.usage_track("message", chat_id=1, user_id=1, text="сегодня")
    core.usage_track("message", chat_id=9, user_id=9, text="впервые")
    summary = core.usage_summary(7)
    assert summary["users_window"] == 2
    assert summary["new_users_window"] == 1, "старый пользователь посчитан новым"


def test_the_last_questions_are_readable():
    _seed()
    last = core.usage_summary(30)["last_questions"]
    assert "цена покупки" in last[-2]["text"]


# --- выгрузка -----------------------------------------------------------------

def test_the_csv_opens_in_excel_with_cyrillic():
    _seed()
    raw = core.usage_csv(30)
    assert raw.startswith("﻿".encode("utf-8")), "без BOM Excel испортит кириллицу"
    text = raw.decode("utf-8")
    assert ";" in text.splitlines()[0], "запятая склеила бы колонки в русском Excel"
    assert "Какая цена покупки предельная?" in text


def test_a_newline_in_a_question_does_not_break_a_row():
    core.usage_track("question", chat_id=1, user_id=1, text="первая строка\nвторая")
    body = core.usage_csv(1).decode("utf-8")
    assert len(body.strip().splitlines()) == 2


# --- кому это видно -----------------------------------------------------------

def test_nobody_sees_the_journal_by_default(monkeypatch):
    monkeypatch.delenv("DEVELOPAID_ADMIN_IDS", raising=False)
    assert core.usage_admin_ids() == set()


def test_the_admin_list_is_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("DEVELOPAID_ADMIN_IDS", "123, 456;789")
    assert core.usage_admin_ids() == {123, 456, 789}


def test_the_refusal_names_the_id_to_add(monkeypatch):
    """Иначе «доступ закрыт» — тупик: свой Telegram ID человек не знает."""
    monkeypatch.delenv("DEVELOPAID_ADMIN_IDS", raising=False)
    sent = []
    monkeypatch.setattr(wrapper, "_send_message", lambda chat, text, **kw: sent.append(text))
    wrapper._stats_message(555, 777, "")
    assert "777" in sent[0] and "DEVELOPAID_ADMIN_IDS" in sent[0]


def test_a_stranger_gets_no_numbers(monkeypatch):
    monkeypatch.setenv("DEVELOPAID_ADMIN_IDS", "111")
    _seed()
    sent = []
    monkeypatch.setattr(wrapper, "_send_message", lambda chat, text, **kw: sent.append(text))
    wrapper._stats_message(555, 222, "")
    assert "Пользователей" not in sent[0]


def test_the_owner_sees_the_summary(monkeypatch):
    monkeypatch.setenv("DEVELOPAID_ADMIN_IDS", "111")
    _seed()
    sent = []
    monkeypatch.setattr(wrapper, "_send_message", lambda chat, text, **kw: sent.append(text))
    wrapper._stats_message(111, 111, "7")
    assert "Обращения за 7 дн." in sent[0]
    assert "цена покупки" in sent[0]


def test_the_owner_can_take_the_journal_out(monkeypatch):
    monkeypatch.setenv("DEVELOPAID_ADMIN_IDS", "111")
    _seed()
    files = []
    monkeypatch.setattr(core, "_telegram_send_document_bytes",
                        lambda chat, content, filename, caption="", content_type="":
                        files.append((filename, content)))
    wrapper._stats_message(111, 111, "csv 14")
    assert files and files[0][0].endswith(".csv")
    assert "LLCR" in files[0][1].decode("utf-8")


# --- учёт стоит там, где сходятся обращения -----------------------------------

def test_every_message_is_counted_including_those_the_engine_handles(monkeypatch):
    """Считать по веткам разбора нельзя: ветка, добавленная позже, молча
    выпадет из счёта."""
    monkeypatch.setattr(wrapper, "_send_help", lambda chat_id: None)
    monkeypatch.setattr(wrapper, "_ORIGINAL_HANDLE_MESSAGE", lambda message: None)
    wrapper._handle_message({"chat": {"id": 42}, "from": {"id": 42, "username": "ivan"},
                             "text": "/help"})
    wrapper._handle_message({"chat": {"id": 42}, "from": {"id": 42, "username": "ivan"},
                             "text": "77:01:0001001:1"})
    kinds = [event["kind"] for event in core.usage_events(1)]
    assert kinds == ["command", "message"]
    assert core.usage_events(1)[0]["name"] == "@ivan"


def test_a_button_press_is_counted(monkeypatch):
    monkeypatch.setattr(wrapper, "_answer_callback", lambda query: None)
    monkeypatch.setattr(wrapper, "_send_help", lambda chat_id: None)
    wrapper._handle_update({"callback_query": {
        "data": "show_help", "from": {"id": 7, "first_name": "Пётр"},
        "message": {"chat": {"id": 7}}}})
    event = core.usage_events(1)[0]
    assert event["kind"] == "button" and event["text"] == "show_help"
    assert event["name"] == "Пётр"


def test_a_site_question_is_counted(monkeypatch):
    monkeypatch.setattr(core, "_call_openai_tool_agent",
                        lambda req, bundle, trace_id=None: {
                            "answer": "ответ", "model": "m", "source": "llm",
                            "response_id": None, "tools_used": [], "proposals": []})
    TestClient(core.app).post("/agent/chat", json={
        "message": "Сколько стоит вход в проект?", "trace_id": "abcabcabcabc",
        "inputs": dict(core.DEFAULT_INPUTS),
        "tep": {k: dict(v) for k, v in core.TEP_DEFAULT.items()},
        "rates": [], "phasing": {}, "history": [], "selected_view": "all"})
    events = [e for e in core.usage_events(1) if e["surface"] == "site"]
    assert events and events[0]["text"] == "Сколько стоит вход в проект?"


# --- сводка приходит сама -----------------------------------------------------

def test_the_digest_is_sent_once_a_day(monkeypatch):
    """Диск под ботом живёт до следующей выкатки; сводка, ушедшая в чат, —
    дольше. Но дважды в день она уже спам."""
    monkeypatch.setenv("DEVELOPAID_ADMIN_IDS", "111")
    monkeypatch.setenv("DEVELOPAID_USAGE_DIGEST_HOUR", "0")
    monkeypatch.setattr(core, "_telegram_webhook_enabled", lambda: True)
    assert wrapper._usage_digest_due() is True
    assert wrapper._usage_digest_due() is False


def test_only_the_host_holding_the_webhook_sends_it(monkeypatch):
    """Второй экземпляр с тем же токеном обязан молчать — иначе сводка придёт
    дважды, и оба раза по половине картины."""
    monkeypatch.setenv("DEVELOPAID_ADMIN_IDS", "111")
    monkeypatch.setenv("DEVELOPAID_USAGE_DIGEST_HOUR", "0")
    monkeypatch.setattr(core, "_telegram_webhook_enabled", lambda: False)
    assert wrapper._usage_digest_due() is False


def test_without_admins_nothing_is_sent(monkeypatch):
    monkeypatch.delenv("DEVELOPAID_ADMIN_IDS", raising=False)
    monkeypatch.setattr(core, "_telegram_webhook_enabled", lambda: True)
    assert wrapper._usage_digest_due() is False


def test_the_tep_review_is_not_counted_as_a_question(monkeypatch):
    """Разбор ТЭП — нажатие кнопки, а не вопрос человека: в одном ряду с
    вопросами он завысил бы их число и засорил бы список последних."""
    monkeypatch.setattr(wrapper, "_resolve_context",
                        lambda chat_id: ("s", {"inputs": dict(core.DEFAULT_INPUTS),
                                               "tep": {k: dict(v) for k, v in core.TEP_DEFAULT.items()}}))
    monkeypatch.setattr(wrapper, "_agent_ready", lambda: True)
    monkeypatch.setattr(wrapper, "_send_message", lambda *a, **kw: None)
    monkeypatch.setattr(core, "plato_answer",
                        lambda req, request: {"answer": "разбор", "proposals": []})
    wrapper._run_agent(1, wrapper._TEP_COMMENT_REQUEST)
    assert [e["kind"] for e in core.usage_events(1)] == ["tep_comment"]
