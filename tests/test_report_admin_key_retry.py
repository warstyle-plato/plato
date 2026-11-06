"""Неверный ключ на /report не должен прятать повторный вход.

Браузер открывает настоящую страницу и получает настоящий отказ доступа 403.
Финансовые данные подменены пустым списком проектов; проверка ключа не подменяется.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from browser import chromium_or_skip, serve


@pytest.fixture
def report_server(monkeypatch):
    import main_legacy as core

    monkeypatch.setenv("DEVELOPAID_ADMIN_KEY", "report-browser-admin-key")
    monkeypatch.setattr(core, "_monitor_report_projects",
                        lambda: {"projects": [], "sales_projects": []})
    with serve(core.app, 18847) as base:
        yield base


def enter_key(page, key):
    page.once("dialog", lambda dialog: dialog.accept(key))
    page.locator("#keyBtn").click()


@pytest.mark.parametrize("width", [390, 1280])
@pytest.mark.parametrize("saved_key", [None, "plato_projects_key", "key"])
def test_a_wrong_key_can_be_replaced(report_server, width, saved_key):
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chromium_or_skip()))
        try:
            page = browser.new_page(viewport={"width": width, "height": 844})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            if saved_key:
                page.add_init_script(
                    "if (!localStorage.getItem('plato_projects_key')) "
                    f"localStorage.setItem({json.dumps(saved_key)}, 'wrong-key');")
                with page.expect_response("**/monitor/report/projects") as denied:
                    page.goto(report_server + "/report")
            else:
                page.goto(report_server + "/report")
                expect(page.locator("#keyBtn")).to_be_visible()
                with page.expect_response("**/monitor/report/projects") as denied:
                    enter_key(page, "wrong-key")
            assert denied.value.status == 403
            expect(page.locator("#loginBox")).to_be_visible()
            expect(page.locator("#keyBtn")).to_be_visible()
            expect(page.locator("#privateArea")).to_be_hidden()
            expect(page.locator("#loginMsg")).to_contain_text("ключу администратора")

            with page.expect_response("**/monitor/report/projects") as accepted:
                enter_key(page, "  report-browser-admin-key  ")
            assert accepted.value.status == 200
            expect(page.locator("#privateArea")).to_be_visible()
            expect(page.locator("#loginBox")).to_be_hidden()
            assert page.evaluate("localStorage.getItem('plato_projects_key')") == "report-browser-admin-key"

            # После перезагрузки используется исправленный ключ, включая случай
            # старого сохранения в legacy-поле key.
            with page.expect_response("**/monitor/report/projects") as reopened:
                page.reload()
            assert reopened.value.status == 200
            expect(page.locator("#privateArea")).to_be_visible()
            assert not errors
        finally:
            browser.close()


def test_a_rejected_pdf_key_also_reopens_login(report_server, monkeypatch):
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chromium_or_skip()))
        try:
            page = browser.new_page(viewport={"width": 390, "height": 844})
            page.goto(report_server + "/report")
            with page.expect_response("**/monitor/report/projects"):
                enter_key(page, "report-browser-admin-key")
            expect(page.locator("#privateArea")).to_be_visible()

            # Ключ изменён на сервере после входа: первый отказ придёт от PDF,
            # чей запрос не использует общий post().
            monkeypatch.setenv("DEVELOPAID_ADMIN_KEY", "rotated-report-admin-key")
            with page.expect_response("**/monitor/report.pdf") as denied:
                page.locator("#reportPdfBtn").click()
            assert denied.value.status == 403
            expect(page.locator("#keyBtn")).to_be_visible()
            expect(page.locator("#privateArea")).to_be_hidden()
            with page.expect_response("**/monitor/report/projects") as accepted:
                enter_key(page, "rotated-report-admin-key")
            assert accepted.value.status == 200
            expect(page.locator("#privateArea")).to_be_visible()
        finally:
            browser.close()
