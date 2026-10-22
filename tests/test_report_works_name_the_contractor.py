"""Работы в сводке приписаны тому подрядчику, который в строке назван.

«МОЭК в отчёте по работам за неделю — это не Клодо! Это отдельный
подрядчик» (владелец, 21.10.2026). Строку «Моэк ( теплосети)- монтаж
ограждения» разбор отдаёт названному подрядчику, только если имя известно
проекту. Сводка проверяла имя лишь по численности того же дня, а в тот день
МОЭК людей не выводил — и строка уходила заголовку выше, Клодо. Карточка
Монитора при этом смотрела ещё и в реестры РСС и ГУ: два ответа на один
вопрос. Теперь список известных подрядчиков один (`daily.known_parties`):
реестры РСС и ГУ плюс численность всех ежедневных отчётов проекта.

Запуск: python3 -m pytest tests/test_report_works_name_the_contractor.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import developaid_management_report as report
import developaid_monitor as monitor
import developaid_monitor_daily as daily

PROJECT = "Кутузов Сити"

EARLIER = """Добрый день.
1. НУР: ИТР- 11чел.; Рабочие - 54чел.;
2. Клодо ( кладка) - Итр- 2 чел.Рабочие - 12чел.
3. МОЭК (теплосети): ИТР - 1 чел., Рабочие - 4 чел.
По работам:
1. МОЭК (теплосети): прокладка трубы
"""

WEEK = """Добрый день.
1. НУР: ИТР- 11чел.; Рабочие - 54чел.;
2. Клодо ( кладка) - Итр- 2 чел.Рабочие - 12чел.
По работам:
1. Клодо ( кладка): Корпус 2 кладка 3 эт
Моэк ( теплосети)- монтаж ограждения
"""


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path / "monitor")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))


def _groups(end: str) -> dict[str, list[str]]:
    got = report.crew(PROJECT, "week", end)
    return {group["contractor"]: [entry["line"] for entry in group["lines"]]
            for group in got["works"]}


def test_a_contractor_known_from_another_day_gets_its_line():
    daily.store_daily_report(PROJECT, EARLIER, "2026-10-08")
    daily.store_daily_report(PROJECT, WEEK, "2026-10-14")
    groups = _groups("2026-10-18")
    moek = next(name for name in groups if "МОЭК" in name.upper())
    assert groups[moek] == ["монтаж ограждения"]
    klodo = next(name for name in groups if "Клодо" in name)
    assert groups[klodo] == ["Корпус 2 кладка 3 эт"]


def test_a_contractor_known_from_the_registers_gets_its_line(monkeypatch):
    daily.store_daily_report(PROJECT, WEEK, "2026-10-14")
    monkeypatch.setattr(monitor, "latest_retention", lambda _p: {
        "rows": [{"counterparty": "ПАО «МОЭК»", "customer": ""}]})
    groups = _groups("2026-10-18")
    assert groups.get("ПАО «МОЭК»") == ["монтаж ограждения"]
    assert all("ограждения" not in line
               for name, lines in groups.items() if "Клодо" in name for line in lines)


def test_the_monitor_and_the_report_share_one_list(monkeypatch):
    import main_legacy as core

    daily.store_daily_report(PROJECT, EARLIER, "2026-10-08")
    assert core._monitor_known_parties(PROJECT) == daily.known_parties(PROJECT)
    assert any("МОЭК" in name for name in daily.known_parties(PROJECT))
    # Отчёт после даты сводки в список этой сводки не попадает.
    assert not any("МОЭК" in name for name in daily.known_parties(PROJECT, "2026-10-07"))


def test_a_contractor_named_by_hand_gets_its_line():
    # «Конкретно МОЭК это подрядчик» (владелец, 21.10.2026): ни реестры, ни
    # численность его не знают — имя, названное руками, решает.
    daily.store_daily_report(PROJECT, WEEK, "2026-10-14")
    assert "МОЭК" not in _groups("2026-10-18")
    daily.declare_party(PROJECT, "  МОЭК ", "Иванов")
    daily.declare_party(PROJECT, "моэк", "Петров")  # повтор не плодит записей
    assert [(r["name"], r["by"]) for r in daily.declared_parties(PROJECT)] == [("моэк", "Петров")]
    groups = _groups("2026-10-18")
    assert groups.get("моэк") == ["монтаж ограждения"]
    daily.declare_party(PROJECT, "МОЭК", "Петров", remove=True)
    assert daily.declared_parties(PROJECT) == []
    assert "моэк" not in _groups("2026-10-18")
    with pytest.raises(ValueError):
        daily.declare_party(PROJECT, " ", "Петров")


def test_the_monitor_page_adds_a_contractor(monkeypatch):
    from browser import chromium_or_skip, serve

    chrome = chromium_or_skip()
    from playwright.sync_api import sync_playwright

    import main_legacy as core

    daily.store_daily_report(PROJECT, WEEK, "2026-10-14")
    monkeypatch.setattr(core, "_require_web_access", lambda *_a, **_k: None)
    with serve(core.app, 18807) as base, sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chrome))
        try:
            tab = browser.new_page()
            errors: list[str] = []
            tab.on("pageerror", lambda e: errors.append(str(e)))
            tab.add_init_script("localStorage.setItem('developaid_web_session','проба')")
            tab.goto(f"{base}/monitor", wait_until="domcontentloaded")
            tab.evaluate(f"""async()=>{{document.getElementById('project').value='{PROJECT}';
                                       document.getElementById('cut').value='2026-10-18';
                                       await renderPeople()}}""")
            tab.wait_for_selector("#partyAdd")
            before = tab.text_content("#peopleLatest")
            tab.fill("#partyName", "МОЭК")
            tab.click("#partyAdd")
            tab.wait_for_selector("#partiesList .party")
            tab.wait_for_function(
                "document.getElementById('peopleLatest').textContent.includes('МОЭК:')")
            after = tab.text_content("#peopleLatest")
            chip = tab.inner_text("#partiesList")
        finally:
            browser.close()
    assert not errors, errors
    assert "МОЭК:" not in before and "МОЭК" in chip
    assert [r["name"] for r in daily.declared_parties(PROJECT)] == ["МОЭК"]
    assert "МОЭК: Моэк ( теплосети)- монтаж ограждения" in after


def test_the_route_names_an_unknown_project(monkeypatch):
    from fastapi import HTTPException

    import main_legacy as core

    monkeypatch.setattr(core, "_require_web_access", lambda *_a, **_k: None)
    with pytest.raises(HTTPException) as unknown:
        core.monitor_declare_contractor(core.MonitorContractorRequest(project="Нет такого",
                                                                      name="МОЭК"))
    assert unknown.value.status_code == 404
