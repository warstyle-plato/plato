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
