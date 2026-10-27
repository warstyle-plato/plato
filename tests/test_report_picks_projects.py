"""Проект сводки выбирается из списка, связь с продажами хранит сервер.

«У нас проект Кутузов Сити, зачем вручную вбивать два раза названия в
отчёте? Надо делать выбор из выпадающего окна» (владелец, 21.10.2026).

Проверки:
- список проектов Монитора — то, что реально лежит на диске; каталог,
  созданный чтением, проектом не считается; имя с пробелом ведёт туда же;
- связь «проект Монитора → проект отчёта о продажах» хранится на сервере
  явно: не задана — `None`, «продаж нет» — решение, а не пустота; чужое имя
  отказывается; сводка без явного `sales_project` берёт связь;
- на отрисованной странице оба поля — списки, связь выбирается один раз и
  видна в новом окне без выбора.

Запуск: python3 -m pytest tests/test_report_picks_projects.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from test_management_report_model import (
    PROJECT,
    M,
    _contract,
    _gpr_book,
    _project,
    _sales,
)

import developaid_management_report as report
import developaid_monitor as monitor

PORT = 18803
SALES = "ЖК Гродненская"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path / "monitor")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))


def test_monitor_projects_are_what_lies_on_disk():
    assert monitor.projects() == []
    monitor.store_schedule("Кутузов Сити", _gpr_book({}), None, "2026-07-01")
    monitor.snapshots("Пустой")  # чтение создаёт каталог — это ещё не проект
    got = monitor.projects()
    assert got == [{"project": "Кутузов Сити", "data": ["baseline"]}]
    # Имя из списка ведёт в тот же каталог, что и имя, под которым грузили.
    assert monitor._project_dir(got[0]["project"]) == monitor._project_dir("Кутузов Сити")


def test_the_link_is_explicit_and_kept_on_the_server():
    _project()
    _sales([_contract("2026-10-13", "Квартира", 50.0, 12.5 * M)])
    assert report.sales_projects() == [SALES]
    assert report.sales_link(PROJECT) is None
    unlinked = report.build(PROJECT, "month", "2026-10-31")
    assert unlinked["sales"]["state"] == "missing"
    assert "выберите его" in unlinked["sales"]["reason"]

    with pytest.raises(ValueError):
        report.link_sales(PROJECT, "Гродненская", "Иванов")  # похоже, но не то имя
    report.link_sales(PROJECT, SALES, "Иванов")
    assert report.sales_link(PROJECT)["sales_project"] == SALES
    linked = report.build(PROJECT, "month", "2026-10-31")
    assert linked["sales"]["state"] == "ok"
    assert "План банка на квартал — 280,0 млн ₽" in report.render_text(linked)

    report.link_sales(PROJECT, "", "Иванов")
    declined = report.build(PROJECT, "month", "2026-10-31")
    assert report.sales_link(PROJECT) == {**report.sales_link(PROJECT), "sales_project": ""}
    assert "не входят" in declined["sales"]["reason"]
    # Явно переданное имя сильнее связи — так зовут проверки и старые вызовы.
    assert report.build(PROJECT, "month", "2026-10-31",
                        sales_project=SALES)["sales"]["state"] == "ok"


def test_the_link_route_refuses_an_unknown_project(monkeypatch):
    from fastapi import HTTPException

    import main_legacy as core

    _project()
    _sales([])
    monkeypatch.setattr(core, "_require_web_access", lambda *_a, **_k: None)
    with pytest.raises(HTTPException) as unknown:
        core.monitor_report_link(core.MonitorReportLinkRequest(
            project="Нет такого", sales_project=SALES))
    assert unknown.value.status_code == 404
    got = core.monitor_report_link(core.MonitorReportLinkRequest(
        project=PROJECT, sales_project=SALES, key="secret"))
    assert got["sales_projects"] == [SALES]
    assert got["projects"][0]["sales"]["sales_project"] == SALES
    assert got["projects"][0]["sales"]["by"] == "администратор"


def test_the_page_picks_both_projects_from_lists(monkeypatch):
    from browser import chromium_or_skip, serve

    chrome = chromium_or_skip()
    from playwright.sync_api import sync_playwright

    import main_legacy as core

    _project()
    _sales([_contract("2026-10-13", "Квартира", 50.0, 12.5 * M)])
    monitor.store_schedule("Кутузов Сити", _gpr_book({}), None, "2026-07-01")
    monkeypatch.setattr(core, "_require_web_access", lambda *_a, **_k: None)

    def visible(tab, selector):
        return tab.locator(selector).is_visible()

    with serve(core.app, PORT) as base, sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chrome))
        try:
            tab = browser.new_page()
            errors: list[str] = []
            tab.on("pageerror", lambda e: errors.append(str(e)))
            # Последний открытый — записан старой страницей рукой, через дефис.
            tab.add_init_script("localStorage.setItem('developaid_web_session','проба');"
                                "localStorage.setItem('mgmt_report_project','кутузов-сити')")
            tab.goto(f"{base}/report", wait_until="domcontentloaded")
            tab.wait_for_selector("#project option[value='Кутузов Сити']", state="attached")
            options = tab.eval_on_selector_all("#project option", "o=>o.map(x=>x.value)")
            default = tab.input_value("#project")
            tag = tab.eval_on_selector("#project", "e=>e.tagName")

            tab.select_option("#project", PROJECT)
            tab.fill("#cut", "2026-10-31")
            tab.select_option("#reportKind", "month")
            tab.wait_for_function(
                "document.getElementById('reportBox').textContent.includes('за октябрь 2026')")
            sales_options = tab.eval_on_selector_all("#reportSales option",
                                                     "o=>o.map(x=>x.textContent)")
            choose_shown = visible(tab, "#reportSales")
            before = tab.inner_text("#reportBox")
            tab.select_option("#reportSales", SALES)
            tab.wait_for_function(
                "document.getElementById('reportBox').textContent.includes('План банка на квартал')")
            after_shown = visible(tab, "#reportSales")
            linked_text = tab.inner_text("#salesLinked")

            # Новое окно: связь уже на сервере, выбирать второй раз не надо.
            fresh = browser.new_page()
            fresh.on("pageerror", lambda e: errors.append(str(e)))
            fresh.add_init_script("localStorage.setItem('developaid_web_session','проба');"
                                  "localStorage.setItem('mgmt_report_project','Гродненская')")
            fresh.goto(f"{base}/report", wait_until="domcontentloaded")
            fresh.wait_for_function(
                "document.getElementById('salesName').textContent.includes('ЖК')")
            fresh_choose = visible(fresh, "#reportSales")
            fresh.click("#salesChange")
            change_shown = visible(fresh, "#reportSales")
            change_value = fresh.input_value("#reportSales")
        finally:
            browser.close()

    assert not errors, errors
    assert tag == "SELECT"
    assert options == ["Гродненская", "Кутузов Сити"]
    assert default == "Кутузов Сити"
    assert choose_shown and SALES in sales_options
    assert "План банка на квартал" not in before
    assert not after_shown and SALES in linked_text
    assert report.sales_link(PROJECT)["sales_project"] == SALES
    assert not fresh_choose
    assert change_shown and change_value == SALES
