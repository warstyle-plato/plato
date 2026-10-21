"""Общая информация по проекту: записи с датой и автором, журналом, в сводке.

Проверки:
- правка не переписывает прежнюю версию: журнал хранит обе, текущая — последняя;
- в сводку периода идут все открытые и закрытые за период; правка после
  конца периода в сводку этого периода не попадает;
- автор записи — тот, кто вошёл, а не тот, кто её создал;
- на отрисованной странице запись добавляется, дополняется и закрывается.

Запуск: python3 -m pytest tests/test_project_notes.py -q
"""
from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import developaid_management_report as report  # noqa: E402
import developaid_monitor as monitor  # noqa: E402
import developaid_project_notes as notes  # noqa: E402

PROJECT = "Гродненская"
PORT = 18798


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path / "monitor")


def test_an_edit_is_a_new_version_not_a_rewrite(tmp_path):
    first = notes.add(PROJECT, "Арбитраж с подрядчиком", "Иск подан", "Иванов",
                      at="2026-10-01T09:00:00+00:00")
    notes.update(PROJECT, first["id"], "Петров", text="Заседание 12.11",
                 at="2026-10-14T09:00:00+00:00")
    current = notes.notes(PROJECT)
    assert len(current) == 1
    note = current[0]
    assert (note["text"], note["author"], note["version"]) == ("Заседание 12.11", "Петров", 2)
    assert (note["created_by"], note["created_at"][:10]) == ("Иванов", "2026-10-01")
    log = (tmp_path / "monitor" / PROJECT / "notes" / "log.jsonl").read_text(encoding="utf-8")
    assert [json.loads(x)["text"] for x in log.splitlines()] == ["Иск подан", "Заседание 12.11"]


def test_wrong_input_is_refused_by_name():
    with pytest.raises(ValueError, match="тема и текст"):
        notes.add(PROJECT, "", "текст", "Иванов")
    note = notes.add(PROJECT, "Спор", "текст", "Иванов")
    with pytest.raises(ValueError, match="ничего не изменилось"):
        notes.update(PROJECT, note["id"], "Иванов", text="текст")
    with pytest.raises(KeyError):
        notes.update(PROJECT, "нет-такой", "Иванов", status="closed")
    with pytest.raises(ValueError, match="статус"):
        notes.update(PROJECT, note["id"], "Иванов", status="забыт")


def test_the_report_shows_open_and_closed_in_period_as_of_its_end():
    old = notes.add(PROJECT, "Спор с соседом", "Ждём экспертизу", "Иванов",
                    at="2026-09-01T09:00:00+00:00")
    fresh = notes.add(PROJECT, "Арбитраж с подрядчиком", "Иск подан", "Петров",
                      at="2026-10-14T09:00:00+00:00")
    gone = notes.add(PROJECT, "Разрешение на ввод", "Ждём", "Петров",
                     at="2026-09-02T09:00:00+00:00")
    notes.update(PROJECT, gone["id"], "Сидоров", status="closed",
                 text="Разрешение получено", at="2026-10-15T09:00:00+00:00")
    long_gone = notes.add(PROJECT, "Старый спор", "Закрыт давно", "Иванов",
                          status="closed", at="2026-08-01T09:00:00+00:00")
    # Правка после конца недели — в сводку этой недели не идёт.
    notes.update(PROJECT, old["id"], "Иванов", status="closed",
                 at="2026-10-20T09:00:00+00:00")

    got = notes.for_period(PROJECT, datetime.date(2026, 10, 12), datetime.date(2026, 10, 18))
    assert [n["id"] for n in got["open"]] == [fresh["id"], old["id"]]
    assert [n["changed"] for n in got["open"]] == [True, False]
    assert [n["id"] for n in got["closed"]] == [gone["id"]]
    assert long_gone["id"] not in {n["id"] for n in got["closed"]}

    text = report.render_text(report.build(PROJECT, "week", "2026-10-18"))
    section = text.split("<b>Общая информация</b>")[1]
    assert "<b>Арбитраж с подрядчиком</b> (новое): Иск подан — 14.10.2026, Петров." in section
    assert "<b>Спор с соседом</b>: Ждём экспертизу" in section
    assert "<b>Разрешение на ввод</b> — вопрос закрыт: Разрешение получено — 15.10.2026, Сидоров." in section
    assert "Старый спор" not in section


def test_empty_feed_says_so():
    text = report.render_text(report.build(PROJECT, "week", "2026-10-18"))
    assert "Открытых вопросов нет, за период записей не было." in text


def test_html_in_a_note_is_escaped_in_the_message():
    notes.add(PROJECT, "<b>тема</b>", "a < b & c", "Иванов", at="2026-10-14T09:00:00+00:00")
    text = report.render_text(report.build(PROJECT, "week", "2026-10-18"))
    assert "&lt;b&gt;тема&lt;/b&gt;" in text and "a &lt; b &amp; c" in text


def test_the_author_is_who_is_signed_in(monkeypatch):
    import main_legacy as core

    monkeypatch.setattr(core, "_require_web_access", lambda *_a, **_k: None)
    monkeypatch.setattr(core, "_web_identity_chat_id", lambda s: {"a": 11, "b": 22}.get(s, 0))
    monkeypatch.setattr(core, "profile_read",
                        lambda chat: {11: {"name": "Иван Иванов"}, 22: {"telegram_name": "petrov"}}[chat])
    made = core.monitor_notes(core.MonitorNotesRequest(
        project=PROJECT, topic="Арбитраж", text="Иск подан", session="a"))
    note = made["notes"][0]
    assert note["author"] == "Иван Иванов"
    closed = core.monitor_notes(core.MonitorNotesRequest(
        project=PROJECT, note_id=note["id"], status="closed", session="b"))
    assert closed["notes"][0]["author"] == "petrov"
    assert closed["notes"][0]["created_by"] == "Иван Иванов"
    by_key = core.monitor_notes(core.MonitorNotesRequest(
        project=PROJECT, topic="Спор", text="x", key="secret"))
    assert by_key["notes"][0]["author"] == "администратор"
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as missing:
        core.monitor_notes(core.MonitorNotesRequest(project=PROJECT, note_id="nope", status="open"))
    assert missing.value.status_code == 404


def test_notes_on_the_rendered_page(monkeypatch):
    from browser import chromium_or_skip, serve

    chrome = chromium_or_skip()
    from playwright.sync_api import sync_playwright

    import main_legacy as core

    from test_management_report_model import _gpr_book

    # Проект выбирается из списка Монитора — у него должен быть хоть график.
    monitor.store_schedule(PROJECT, _gpr_book({}), None, "2026-07-01")
    monkeypatch.setattr(core, "_require_web_access", lambda *_a, **_k: None)
    with serve(core.app, PORT) as base, sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chrome))
        try:
            tab = browser.new_page()
            errors: list[str] = []
            tab.on("pageerror", lambda e: errors.append(str(e)))
            tab.add_init_script("localStorage.setItem('developaid_web_session','проба')")
            # Записи живут на странице «Сводка руководству», а не в Мониторе
            # стройки (владелец, 20.10.2026).
            tab.goto(f"{base}/report", wait_until="domcontentloaded")
            tab.wait_for_selector(f"#project option[value='{PROJECT}']", state="attached")
            tab.select_option("#project", PROJECT)
            tab.click("#reportBtn")
            tab.wait_for_function(
                "document.getElementById('notesList').textContent.includes('Записей пока нет')")
            empty = tab.inner_text("#notesList")

            tab.fill("#noteTopic", "Арбитраж с подрядчиком")
            tab.fill("#noteText", "Иск подан")
            tab.click("#noteAddBtn")
            tab.wait_for_selector("#notesList .note")
            added = tab.inner_text("#notesList")
            cleared = tab.input_value("#noteTopic")

            tab.fill("#notesList .noteNew", "Заседание 12.11")
            tab.click("#notesList .noteSave")
            tab.wait_for_function(
                "document.getElementById('notesList').textContent.includes('Заседание 12.11')")
            tab.click("#notesList .noteToggle")
            tab.wait_for_function(
                "document.getElementById('notesList').textContent.includes('Вопрос закрыт')")
            final = tab.inner_text("#notesList")
            state = tab.inner_text("#notesState")
            button = tab.inner_text("#notesList .noteToggle")
        finally:
            browser.close()

    assert not errors, errors
    assert "Записей пока нет" in empty
    assert "Арбитраж с подрядчиком" in added and "Вопрос открыт" in added
    assert cleared == ""
    assert "Заседание 12.11" in final and "правок: 2" in final
    assert state == "Открытых вопросов: 0 из 1."
    assert button == "Открыть снова"
