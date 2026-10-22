"""Запись «Общей информации» и карточку спора можно удалить; обрыв связи назван.

«И это был тест, как его удалить» (владелец, 22.10.2026, про запись «Кимакг —
вопрос закрыт…»): кнопки удаления не было. Удаление — последняя версия в
журнале с пометкой `deleted` (кто и когда); список и сводка её не показывают,
журнал цел. «После нажатия кнопки Подтвердить и сохранить пишет load failed»:
обрыв связи страница называет словами и оставляет форму с правками.

Запуск: python3 -m pytest tests/test_report_entries_can_be_deleted.py -q
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import developaid_legal_cases as legal  # noqa: E402
import developaid_management_report as report  # noqa: E402
import developaid_monitor as monitor  # noqa: E402
import developaid_project_notes as notes  # noqa: E402
from developaid_report_page import REPORT_PAGE  # noqa: E402
from test_legal_cases import CARD  # noqa: E402

PROJECT = "Гродненская"
PORT = 18809


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path / "monitor")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))


def test_a_deleted_note_leaves_the_list_and_the_report_but_stays_in_the_log():
    kept = notes.add(PROJECT, "Арбитраж", "Иск подан", "Иванов", at="2026-10-14T09:00:00+00:00")
    gone = notes.add(PROJECT, "Кимакг", "Иск подан 18.10", "администратор",
                     status="closed", at="2026-10-21T09:00:00+00:00")
    entry = notes.remove(PROJECT, gone["id"], "администратор", at="2026-10-22T09:00:00+00:00")
    assert entry["deleted"] is True and entry["version"] == 2 and entry["author"] == "администратор"
    assert [n["id"] for n in notes.notes(PROJECT)] == [kept["id"]]
    period = notes.for_period(PROJECT, datetime.date(2026, 10, 19), datetime.date(2026, 10, 25))
    assert period["closed"] == [] and [n["id"] for n in period["open"]] == [kept["id"]]
    # Журнал цел: обе версии удалённой записи на месте.
    assert sum(1 for row in notes._read(notes._log(PROJECT)) if row["id"] == gone["id"]) == 2
    with pytest.raises(KeyError):
        notes.update(PROJECT, gone["id"], "Иванов", text="поздно")
    with pytest.raises(KeyError):
        notes.remove(PROJECT, gone["id"], "Иванов")
    text = report.render_text(report.build(PROJECT, "week", "2026-10-25"))
    assert "Кимакг" not in text and "Арбитраж" in text


def test_a_deleted_case_leaves_the_register_and_the_report():
    first = legal.save(PROJECT, CARD, [], "Иванова", at="2026-10-05T09:00:00+00:00")
    other = legal.save(PROJECT, dict(CARD, counterparty="Тест-Подряд", contract="Д-0"), [],
                       "Иванова", at="2026-10-06T09:00:00+00:00")
    entry = legal.remove(PROJECT, other["id"], "администратор", at="2026-10-22T09:00:00+00:00")
    assert entry["deleted"] is True and entry["version"] == 2 and entry["by"] == "администратор"
    assert [row["id"] for row in legal.cases(PROJECT)] == [first["id"]]
    week = legal.for_report(PROJECT, datetime.date(2026, 10, 19), datetime.date(2026, 10, 25))
    assert [row["id"] for row in week["open"]] == [first["id"]] and week["recorded"] == 1
    with pytest.raises(KeyError):
        legal.save(PROJECT, CARD, [], "Иванова", case_id=other["id"])
    with pytest.raises(KeyError):
        legal.remove(PROJECT, other["id"], "Иванова")
    with pytest.raises(ValueError):
        legal.remove(PROJECT, "не номер", "Иванова")
    assert "Тест-Подряд" not in report.render_html(report.build(PROJECT, "week", "2026-10-25"))


def test_the_page_deletes_and_names_a_lost_connection(monkeypatch):
    from browser import chromium_or_skip, serve

    chrome = chromium_or_skip()
    from playwright.sync_api import sync_playwright
    from test_management_report_model import _gpr_book

    import main_legacy as core

    monitor.store_schedule(PROJECT, _gpr_book({}), None, "2026-07-01")
    monkeypatch.setattr(core, "_require_web_access", lambda *_a, **_k: None)
    notes.add(PROJECT, "Кимакг", "Иск подан 18.10", "администратор", status="closed")
    legal.save(PROJECT, CARD, [], "Иванова")
    with serve(core.app, PORT) as base, sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chrome))
        try:
            tab = browser.new_page()
            errors: list[str] = []
            tab.on("pageerror", lambda e: errors.append(str(e)))
            tab.add_init_script("localStorage.setItem('developaid_web_session','проба')")
            tab.on("dialog", lambda d: d.accept())
            tab.goto(f"{base}/report", wait_until="domcontentloaded")
            tab.wait_for_selector(f"#project option[value='{PROJECT}']", state="attached")
            tab.select_option("#project", PROJECT)
            tab.click("#reportBtn")
            tab.wait_for_selector("#notesList .note .noteRemove")
            tab.click("#notesList .note .noteRemove")
            tab.wait_for_function(
                "document.getElementById('notesList').textContent.includes('Записей пока нет')")
            tab.wait_for_selector("#legalList .legal-case .legalRemove")
            # Обрыв связи при сохранении: причина словами, форма с правками остаётся.
            tab.click("#legalList .legal-case .legalEdit")
            tab.wait_for_selector("#legalForm:not(.hidden) #lfNext")
            tab.fill("#lfNext", "Подать иск 30.10")
            tab.route("**/monitor/legal/case", lambda route: route.abort("failed"))
            tab.click("#lfSave")
            tab.wait_for_function(
                "document.getElementById('legalMsg').textContent.includes('связь прервалась')")
            lost = tab.inner_text("#legalMsg")
            still_open = tab.is_visible("#legalForm") and tab.input_value("#lfNext")
            tab.unroute("**/monitor/legal/case")
            tab.click("#lfSave")
            tab.wait_for_function(
                "document.getElementById('legalList').textContent.includes('Подать иск 30.10')")
            tab.click("#legalList .legal-case .legalRemove")
            tab.wait_for_function(
                "document.getElementById('legalList').textContent.includes('Споров пока нет')")
        finally:
            browser.close()
    assert not errors, errors
    assert "load failed" not in lost.lower() and "/monitor/legal/case" in lost
    assert "Форма с вашими правками осталась открытой" in lost
    assert still_open == "Подать иск 30.10"
    assert notes.notes(PROJECT) == [] and legal.cases(PROJECT) == []
    assert legal._versions(PROJECT)[-1]["deleted"] is True
