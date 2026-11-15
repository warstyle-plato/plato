"""Площадь не выдаётся за комнатность ни в сохранённом импорте, ни на экране."""

import pytest

from market_search import cabinet, contracting, sales_store
from test_management_report_model import _contract
from test_the_cabinet_takes_the_project_file import client  # noqa: F401


@pytest.mark.parametrize("area,label", [
    (0, "Площадь не указана"), (-1, "Площадь не указана"),
    (27.99, "до 28 м²"), (28, "28–45 м²"), (44.99, "28–45 м²"),
    (45, "45–70 м²"), (69.99, "45–70 м²"),
    (70, "70–100 м²"), (99.99, "70–100 м²"), (100, "от 100 м²"),
])
def test_area_boundaries_have_area_labels(area, label):
    assert contracting.size_band(area) == label


@pytest.fixture
def saved_summary(client):
    # Старый импорт хранит строки, а не новые подписи. Одинаковые площади
    # при разной комнатности и разные площади при одинаковой комнатности.
    rows = [
        {**_contract("2026-01-01", "Квартира", 40, 10e6), "rooms": "1К"},
        {**_contract("2026-01-02", "Квартира", 40, 20e6), "rooms": "2К"},
        {**_contract("2026-01-03", "Квартира", 80, 70e6), "rooms": "1К"},
    ]
    sales_store.save(sales_store.default_dir(), "Проверка площади",
                     {"contracting": {"project": "Проверка площади", "rows": rows,
                                      "missing": []}}, "saved-import.xlsx")
    response = client.get("/cabinet/sales/summary", params={"project": "Проверка площади"})
    assert response.status_code == 200, response.text
    return response.json()


def test_saved_import_is_regrouped_without_changing_rooms_or_totals(saved_summary):
    d = saved_summary
    assert [(x["band"], x["contracts"]) for x in d["by_size"]] == [
        ("28–45 м²", 2), ("70–100 м²", 1)]
    assert [(x["rooms"], x["contracts"]) for x in d["by_rooms"]] == [("1К", 2), ("2К", 1)]
    for field in ("contracts", "area", "amount"):
        assert sum(x[field] for x in d["by_size"]) == d["total"][field]
        assert sum(x[field] for x in d["by_rooms"]) == d["total"][field]


@pytest.mark.parametrize("width", [390, 1280])
def test_report_labels_area_rooms_and_revenue_in_screen_and_print(saved_summary, width):
    from playwright.sync_api import sync_playwright
    import browser_launch

    with sync_playwright() as pw:
        browser = browser_launch.launch(pw)
        try:
            page = browser.new_page(viewport={"width": width, "height": 1000})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.route("**/*", lambda route: route.abort())
            page.set_content(cabinet.cabinet_page("sales").replace("__DEVELOPAID_VERSION__", "test"))
            page.evaluate("d => {salesData=d; renderSales(d)}", saved_summary)
            area = page.locator("#sb-mix")
            rooms = page.locator("#sb-rms")
            assert "Продажи по площади квартир" in area.inner_text()
            assert "по площади, а не по числу комнат" in area.inner_text()
            assert "28–45 м² — 30,0%" in area.inner_text()
            assert "70–100 м² — 70,0%" in area.inner_text()
            assert "1к" not in area.inner_text().lower()
            assert "Доли по выручке" in area.inner_text()
            assert "Доли по выручке" in rooms.inner_text()
            assert "1К — 80,0%" in rooms.inner_text()
            assert "2К — 20,0%" in rooms.inner_text()
            assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
            digest = page.evaluate("salesDigest(salesData, 20000)")
            assert "ПЛОЩАДЬ КВАРТИРЫ 28–45 м²" in digest
            assert "КОМНАТ 1К" in digest
            printed = page.evaluate("salesPrintHtml()")
            assert "Продажи по площади квартир" in printed
            assert "28–45 м²" in printed and "Доли по выручке" in printed
            assert "Комнатность проданного" in printed
            assert not errors, errors
        finally:
            browser.close()
