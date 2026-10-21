"""Один проект под двумя именами сводится в один, ничего не теряя.

«Почему разница между Гродненской и Кутузов Сити? Это один проект»
(владелец, 21.10.2026; главное имя — «Кутузов Сити»).

Проверки:
- проверка только показывает план и ничего не трогает;
- объединение не перезаписывает главный проект: недостающее переезжает,
  журналы дописываются, ручные отметки одного дня сливаются (главный сильнее),
  разное с одним именем ложится рядом и называется;
- старое имя ведёт в главный каталог (чат стройки, бот, ссылки), в списке
  остаётся одно имя, прежний каталог сохранён в `.merged/`;
- получатели рассылки и ссылка-приглашение старого имени переходят к главному;
- на отрисованной странице проверка и объединение делаются кнопками.

Запуск: python3 -m pytest tests/test_monitor_merges_one_project.py -q
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from test_management_report_model import PROJECT, _gpr_book, _project

import developaid_management_report as report
import developaid_monitor as monitor
import developaid_monitor_merge as merge
import developaid_project_notes as notes
import developaid_report_mailing as mailing

MAIN = "Кутузов Сити"
PORT = 18805


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path / "monitor")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))


def _two_names():
    _project()  # «Гродненская»: ГПР, ГПР-факт, РСС
    monitor.store_schedule(MAIN, _gpr_book({"1": 0.9}), None, "2026-08-21")
    notes.add(PROJECT, "Арбитраж", "Иск подан", "Иванов")
    notes.add(MAIN, "Разрешение на ввод", "Готовим пакет", "Петров")
    monitor.store_work_fact(PROJECT, [{"id": "1", "progress": 0.5},
                                      {"id": "2", "progress": 1.0}], "2026-10-17")
    monitor.store_work_fact(MAIN, [{"id": "1", "progress": 0.7}], "2026-10-17")
    return (monitor._project_dir(MAIN) / "baseline" / "gpr.xlsx").read_bytes()


def test_the_check_only_shows_the_plan():
    _two_names()
    plan = merge.merge(PROJECT, MAIN, "Иванов")
    assert plan["applied"] is False
    assert plan["counts"]["move"] >= 2  # ГПР-факт и РСС
    assert plan["counts"]["append"] == 1 and plan["counts"]["combine"] == 1
    assert "baseline/gpr.xlsx" in plan["conflicts"]
    assert [item["project"] for item in monitor.projects()] == [PROJECT, MAIN]


def test_merging_keeps_the_main_project_and_adds_what_it_lacks():
    main_gpr = _two_names()
    token = mailing.invite(PROJECT, "Иванов")["start"]
    mailing.subscribe(token, 501, "Пётр")
    done = merge.merge(PROJECT, MAIN, "Иванов", apply=True)
    assert done["applied"] and done["subscribers_moved"] == 1

    assert [item["project"] for item in monitor.projects()] == [MAIN]
    folder = monitor._project_dir(MAIN)
    assert (folder / "baseline" / "gpr.xlsx").read_bytes() == main_gpr
    assert (folder / ".merged-from-Гродненская" / "baseline" / "gpr.xlsx").exists()
    assert sorted(p.name for p in (folder / "schedule_fact").glob("*.xlsx")) == [
        "2026-10-09.xlsx", "2026-10-16.xlsx"]
    assert {n["topic"] for n in notes.notes(MAIN)} == {"Арбитраж", "Разрешение на ввод"}
    facts = monitor.work_facts(MAIN)
    assert facts["1"]["progress"] == 0.7 and facts["2"]["progress"] == 1.0

    # Старое имя ведёт в главный каталог: и чтение, и запись.
    assert monitor._project_dir(PROJECT) == folder
    notes.add(PROJECT, "Из чата стройки", "по старому имени", "бот")
    assert "Из чата стройки" in {n["topic"] for n in notes.notes(MAIN)}
    parked = list((monitor._SNAPSHOT_DIR / ".merged").glob("Гродненская-*"))
    assert len(parked) == 1 and (parked[0] / "baseline" / "gpr.xlsx").exists()
    log = (monitor._SNAPSHOT_DIR / ".merged" / "log.jsonl").read_text(encoding="utf-8")
    assert json.loads(log)["by"] == "Иванов"

    # Сводка главного видит ГПР-факт, загруженный под старым именем.
    got = report.physical(MAIN, "week", "2026-10-18")
    assert got["fact_snapshot"] == "2026-10-16"
    assert [row["chat_id"] for row in mailing.subscribers(MAIN)] == [501]
    assert mailing.subscribe(token, 502, "Мария") == MAIN

    with pytest.raises(KeyError):
        merge.merge(PROJECT, MAIN, "Иванов", apply=True)


def test_the_route_names_an_unknown_project(monkeypatch):
    from fastapi import HTTPException

    import main_legacy as core

    _two_names()
    monkeypatch.setattr(core, "_require_web_access", lambda *_a, **_k: None)
    with pytest.raises(HTTPException) as unknown:
        core.monitor_merge(core.MonitorMergeRequest(source="Нет такого", target=MAIN))
    assert unknown.value.status_code == 404
    with pytest.raises(HTTPException) as same:
        core.monitor_merge(core.MonitorMergeRequest(source=MAIN, target=MAIN))
    assert same.value.status_code == 400


def test_the_page_checks_and_merges(monkeypatch):
    from browser import chromium_or_skip, serve

    chrome = chromium_or_skip()
    from playwright.sync_api import sync_playwright

    import main_legacy as core

    _two_names()
    monkeypatch.setattr(core, "_require_web_access", lambda *_a, **_k: None)
    with serve(core.app, PORT) as base, sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chrome))
        try:
            tab = browser.new_page()
            errors: list[str] = []
            tab.on("pageerror", lambda e: errors.append(str(e)))
            tab.on("dialog", lambda d: d.accept())
            tab.add_init_script("localStorage.setItem('developaid_web_session','проба');"
                                f"localStorage.setItem('mgmt_report_project','{MAIN}')")
            tab.goto(f"{base}/report", wait_until="domcontentloaded")
            tab.wait_for_selector("#mergeCard:not(.hidden)")
            source, target = tab.input_value("#mergeSource"), tab.input_value("#mergeTarget")
            disabled = tab.is_disabled("#mergeApplyBtn")
            tab.click("#mergeCheckBtn")
            tab.wait_for_function("document.getElementById('mergePlan').textContent.length>0")
            plan = tab.inner_text("#mergePlan")
            tab.click("#mergeApplyBtn")
            tab.wait_for_function(
                "document.getElementById('mergeMsg').textContent.startsWith('Готово')")
            options = tab.eval_on_selector_all("#project option", "o=>o.map(x=>x.value)")
            hidden = tab.locator("#mergeCard").get_attribute("class")
        finally:
            browser.close()
    assert not errors, errors
    assert (source, target) == (PROJECT, MAIN) and disabled
    assert "перенесётся файлов" in plan and "baseline/gpr.xlsx" in plan
    assert options == [MAIN] and "hidden" in hidden
