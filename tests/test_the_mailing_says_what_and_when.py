"""Рассылка сводки: страница говорит, какая сводка и когда ушла, и что не собралось.

Владелец 26.10.2026: «По-моему отчёт не был отправлен ботом», а страница
писала у получателя «последняя сводка: отправлено» — без даты и без того, за
какой срок. Сводку срока, которую ядро не собрало, нельзя было отличить от
доставленной прошлой, а причина сбоя сборки лежала только в памяти воркера.

Проверки:
- сбой сборки одного проекта не останавливает рассылку остальных, причина
  ложится на диск и видна по проекту, пока срок не соберётся;
- у получателя — за какой срок сводка и когда отправлена;
- на странице: «Сводка за неделю по … должна была уйти … но ещё не собрана.
  Причина: …» и у получателя «за неделю по 08.11.2026: отправлено 09.11.2026 в 09:02».

Запуск: python3 -m pytest tests/test_the_mailing_says_what_and_when.py -q
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from test_management_report_model import PROJECT, _project

import developaid_monitor as monitor
import developaid_report_mailing as mailing

MSK = mailing.MSK
PORT = 18806
OTHER = "Кутузов Сити"


def at(text: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(text).replace(tzinfo=MSK)


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path / "monitor")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:test")
    monkeypatch.setenv("TELEGRAM_BOT_USERNAME", "developaid_bot")
    monkeypatch.delenv("MO_CALC_API_URL", raising=False)
    monkeypatch.delenv("CORE_API_URL", raising=False)


def _make(broken: set[str]):
    def make(project, kind, end):
        if project in broken:
            raise KeyError("нет среза Монитора за 25.10.2026")
        return {"text": f"Сводка {project}", "pdf": b"%PDF-1.4 test",
                "filename": "Сводка.pdf", "error": ""}
    return make


def _subscribe(project: str, chat: int, name: str) -> None:
    mailing.subscribe(mailing.invite(project, "Иванов")["start"], chat, name)


def test_one_broken_project_does_not_stop_the_others_and_says_why():
    _subscribe(OTHER, 601, "Анна")          # по имени — раньше «Гродненской»
    _subscribe(PROJECT, 501, "Пётр")
    now = at("2026-11-09T09:01")
    assert mailing.build_due(_make({OTHER}), now) == [f"week-2026-11-08:{PROJECT}"]

    broken = mailing.status(OTHER, now)
    assert [row["slot"] for row in broken["missing"]] == ["week-2026-11-08"]
    assert "нет среза Монитора" in broken["missing"][0]["error"]
    assert broken["missing"][0]["at"].startswith("2026-11-09T09:00")
    assert mailing.status(PROJECT, now)["missing"] == []

    # Починили — следующий проход собирает, причина уходит.
    later = at("2026-11-09T09:05")
    assert mailing.build_due(_make(set()), later) == [f"week-2026-11-08:{OTHER}"]
    assert mailing.status(OTHER, later)["missing"] == []


def test_the_last_report_names_its_period_and_time():
    _subscribe(PROJECT, 501, "Пётр")
    mailing.build_due(_make(set()), at("2026-11-09T09:01"))
    mailing.take(at("2026-11-09T09:02"))
    mailing.confirm("week-2026-11-08", PROJECT, {"501": ""}, at("2026-11-09T09:02"))
    last = mailing.status(PROJECT, at("2026-11-09T09:03"))["subscribers"][0]["last"]
    assert (last["label"], last["kind"], last["end"]) == ("отправлено", "week", "2026-11-08")
    assert last["at"].startswith("2026-11-09T09:02")


def test_the_page_tells_what_went_and_what_did_not(monkeypatch):
    from browser import chromium_or_skip, serve

    chrome = chromium_or_skip()
    from playwright.sync_api import sync_playwright

    import main_legacy as core

    _project()
    _subscribe(PROJECT, 501, "Пётр Петров")
    # Прошлая неделя ушла, нынешняя не собралась.
    mailing.build_due(_make(set()), at("2026-11-09T09:01"))
    mailing.take(at("2026-11-09T09:02"))
    mailing.confirm("week-2026-11-08", PROJECT, {"501": ""}, at("2026-11-09T09:02"))
    now = at("2026-11-16T10:40")
    mailing.build_due(_make({PROJECT}), now)
    monkeypatch.setattr(mailing, "_now", lambda moment=None: (moment or now).astimezone(MSK))
    monkeypatch.setattr(core, "_require_web_access", lambda *_a, **_k: None)
    with serve(core.app, PORT) as base, sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chrome))
        try:
            tab = browser.new_page()
            errors: list[str] = []
            tab.on("pageerror", lambda e: errors.append(str(e)))
            tab.add_init_script("localStorage.setItem('developaid_web_session','проба')")
            tab.goto(f"{base}/report", wait_until="domcontentloaded")
            tab.wait_for_selector(f"#project option[value='{PROJECT}']", state="attached")
            tab.select_option("#project", PROJECT)
            tab.click("#reportBtn")
            tab.wait_for_selector("#mailingList .mailingPerson")
            shown = tab.inner_text("#mailingList")
        finally:
            browser.close()
    assert not errors, errors
    assert ("Сводка за неделю по 15.11.2026 должна была уйти 16.11.2026 в 09:00, "
            "но ещё не собрана.") in shown, shown
    assert "нет среза Монитора" in shown, shown
    assert "последняя сводка — за неделю по 08.11.2026: отправлено 09.11.2026 в 09:02" in shown, shown
