"""An open saved report must identify the destination of the next upload."""
from __future__ import annotations

import pytest
from urllib.parse import parse_qs, urlsplit

from market_search import contracting, sales_store
from test_sales_chessboard import book
from test_the_cabinet_takes_the_project_file import client, _workbook


@pytest.mark.parametrize(("saved_project", "source_project"), [
    ("Открытый проект", ""),
    ("Открытый проект", "Имя из прежней выгрузки"),
    ("", ""),
])
def test_stored_report_names_its_destination_and_uploads_stay_there(
    client, saved_project, source_project,
):
    where = sales_store.default_dir()
    contracts = contracting.read_contracts(_workbook())
    contracts["project"] = source_project
    sales_store.save(where, saved_project, {"contracting": contracts}, "contracts.xlsx")
    # A second project prevents the server from guessing the only destination.
    other = sales_store.save(where, "Соседний проект", {"pool": {"rows": []}}, "pool.xlsx")
    destination = saved_project or sales_store.slug(saved_project)

    current = client.get("/cabinet/sales/summary", params={"project": destination})
    assert current.status_code == 200
    assert current.json()["project"] == destination
    assert current.json()["total"]["contracts"] == 2
    assert sales_store.load(where, saved_project)["project"] == saved_project

    for corpus in [3, 1, 2]:
        uploaded = client.post("/cabinet/contracting", params={
            "project": current.json()["project"], "as_of": "2026-11-03",
        }, content=book(corpus))
        assert uploaded.status_code == 200, uploaded.text
        current = uploaded
        assert current.json()["project"] == destination
    sources = sales_store.load(where, destination)["sources"]
    assert set(sources["chessboard"]["data"]["buildings"]) == {"1", "2", "3"}
    assert sources["contracting"]["data"] == contracts
    assert sales_store.load(where, "Соседний проект") == other
    assert len(sales_store.projects(where)) == 2


def test_a_chessboard_without_a_destination_is_still_refused(client):
    where = sales_store.default_dir()
    for name in ["Один проект", "Другой проект"]:
        sales_store.save(where, name, {"pool": {"rows": []}}, "pool.xlsx")
    answer = client.post("/cabinet/contracting", params={"as_of": "2026-11-03"}, content=book())
    assert answer.status_code == 422
    assert all("chessboard" not in sales_store.load(where, row["project"])["sources"]
               for row in sales_store.projects(where))


def test_project_list_skips_question_journals_and_preserves_real_project_names(client):
    import json

    where = sales_store.default_dir()
    sales_store.save(where, "Обычный проект", {"pool": {"rows": []}}, "pool.xlsx")
    sales_store.save(where, "Проект.asked", {"pool": {"rows": []}}, "pool.xlsx")
    directory = where / "cabinet"
    for name, data in [("обычный-проект.asked", {"questions": []}),
                       ("invalid-list", []), ("invalid-sources", {"sources": []})]:
        (directory / (name + ".json")).write_text(json.dumps(data), encoding="utf-8")
    answer = client.get("/cabinet/sales/summary")
    assert answer.status_code == 200
    assert {row["project"] for row in answer.json()["known"]} == {
        "Обычный проект", "Проект.asked"}


@pytest.mark.parametrize("width", [390, 1440])
@pytest.mark.parametrize("stock_only", [False, True])
def test_project_choice_survives_reload_and_corpora_uploads(client, width, stock_only):
    import main_registry
    from browser import chromium_or_skip, serve
    from playwright.sync_api import expect, sync_playwright
    from test_sales_chessboard import snapshot
    from test_the_cabinet_takes_the_project_file import KEY

    where = sales_store.default_dir()
    other = sales_store.save(where, "Альфа", {"pool": {"rows": []}}, "pool.xlsx")
    if stock_only:
        parts = {"chessboard": snapshot()}
    else:
        contracts = contracting.read_contracts(_workbook())
        contracts["project"] = "Прежнее имя выгрузки"
        parts = {"contracting": contracts}
    sales_store.save(where, "Бета", parts, "initial.xlsx")

    with serve(main_registry.app, 18772) as base, sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chromium_or_skip()))
        try:
            page = browser.new_page(viewport={"width": width, "height": 900})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.request.post(base + "/cabinet/login", form={"key": KEY})
            page.goto(base + "/cabinet/sales")
            expect(page.locator("#salesProject")).to_have_value("Альфа")
            page.select_option("#salesProject", "Бета")
            expect(page.locator("#overviewTitle")).to_contain_text("Бета")
            expect(page.locator("#cf")).to_be_enabled()
            assert parse_qs(urlsplit(page.url).query)["project"] == ["Бета"]
            if stock_only:
                expect(page.locator(".chessboard-overlay")).to_be_visible()
                expect(page.locator("#overviewBody")).to_contain_text("Контрактация ещё не загружена")
            for corpus in [2, 3, 3]:
                page.reload()
                expect(page.locator("#salesProject")).to_have_value("Бета")
                expect(page.locator("#cf")).to_be_enabled()
                page.fill("#chessboardDate", "2026-11-03")
                with page.expect_response("**/cabinet/contracting?*") as pending:
                    page.locator("#cf").set_input_files({"name": f"корпус {corpus}.xlsx",
                        "mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        "buffer": book(corpus)})
                response = pending.value
                assert response.status == 200, response.text()
                assert parse_qs(urlsplit(response.url).query)["project"] == ["Бета"]
                expect(page.locator(".chessboard-overlay")).to_be_visible()
            assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
            assert not errors
        finally:
            browser.close()
    assert sales_store.load(where, "Альфа") == other
    saved = sales_store.load(where, "Бета")["sources"]
    expected = {"1", "2", "3"} if stock_only else {"2", "3"}
    assert set(saved["chessboard"]["data"]["buildings"]) == expected
    if not stock_only:
        assert saved["contracting"]["data"] == contracts


def test_failed_project_switch_prevents_upload_to_the_previous_project(client):
    import main_registry
    from browser import chromium_or_skip, serve
    from playwright.sync_api import expect, sync_playwright
    from test_the_cabinet_takes_the_project_file import KEY

    where = sales_store.default_dir()
    for name in ["Альфа", "Бета"]:
        sales_store.save(where, name, {"pool": {"rows": []}}, "pool.xlsx")
    with serve(main_registry.app, 18773) as base, sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chromium_or_skip()))
        try:
            page = browser.new_page()
            page.request.post(base + "/cabinet/login", form={"key": KEY})
            page.goto(base + "/cabinet/sales")
            expect(page.locator("#salesProject")).to_have_value("Альфа")
            pending = []
            page.route("**/cabinet/sales/summary?*", lambda route: pending.append(route))
            page.select_option("#salesProject", "Бета")
            expect(page.locator("#cf")).to_be_disabled()
            assert page.evaluate("salesData") is None
            assert page.locator("#salesreport").count() == 0
            assert len(pending) == 1
            pending[0].fulfill(status=503, body='{"detail":"temporary outage"}',
                               content_type="application/json")
            expect(page.locator("#overviewBody")).to_contain_text("Ядро ответило кодом 503")
            expect(page.locator("#salesProject")).to_be_enabled()
            expect(page.locator("#cf")).to_be_disabled()
            page.unroute("**/cabinet/sales/summary?*")
            page.select_option("#salesProject", "Альфа")
            expect(page.locator("#overviewTitle")).to_contain_text("Альфа")
            expect(page.locator("#cf")).to_be_enabled()
        finally:
            browser.close()


@pytest.mark.parametrize("width", [390, 1440])
def test_the_page_uploads_to_the_open_legacy_report_after_each_refresh(client, width):
    import main_registry
    from browser import chromium_or_skip, serve
    from playwright.sync_api import expect, sync_playwright
    from test_the_cabinet_takes_the_project_file import KEY

    where = sales_store.default_dir()
    contracts = contracting.read_contracts(_workbook())
    contracts["project"] = ""
    sales_store.save(where, "", {"contracting": contracts}, "contracts.xlsx")
    other = sales_store.save(where, "Соседний проект", {"pool": {"rows": []}}, "pool.xlsx")
    with serve(main_registry.app, 18771) as base, sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chromium_or_skip()))
        try:
            page = browser.new_page(viewport={"width": width, "height": 900})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.request.post(base + "/cabinet/login", form={"key": KEY})
            page.goto(base + "/cabinet/sales")
            expect(page.locator("#salesreport")).to_be_visible()
            for corpus in [3, 1, 2]:
                page.fill("#chessboardDate", "2026-11-03")
                with page.expect_response("**/cabinet/contracting?*") as pending:
                    page.locator("#cf").set_input_files({"name": f"корпус {corpus}.xlsx",
                        "mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        "buffer": book(corpus)})
                response = pending.value
                assert response.status == 200, response.text()
                assert parse_qs(urlsplit(response.url).query)["project"] == ["без-имени"]
                expect(page.locator(".chessboard-overlay")).to_be_visible()
                # Reload must recover the same project from persisted sources.
                page.reload()
                expect(page.locator(".chessboard-overlay")).to_be_visible()
            expect(page.locator(".chessboard-overlay")).to_contain_text("свободно квартир — 3")
            assert not errors
        finally:
            browser.close()
    saved = sales_store.load(where, "")
    assert set(saved["sources"]["chessboard"]["data"]["buildings"]) == {"1", "2", "3"}
    assert sales_store.load(where, "Соседний проект") == other
