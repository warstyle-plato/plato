"""Шахматка читается из книги и доходит до вопросов бота и обеих поверхностей."""
from __future__ import annotations

import datetime
import io
import sys
from pathlib import Path

import pytest
from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from market_search import chessboard, sales_questions, sales_store
from test_the_cabinet_takes_the_project_file import client, _workbook


def book(corpus=1, rows=None):
    wb = Workbook()
    s = wb.active
    s.title = "1"
    s["A2"] = f"корпус {corpus}"
    for i, (unit, floor, area, price, amount, status) in enumerate(rows or [
            (1, 3, 40, 100_000, 4_000_000, "Свободно"),
            (2, 2, 60, 100_000, 6_000_000, "ПРОЕКТИРОВАНИЕ"),
            (3, 4, 50, 100_000, 5_000_000, "Бронь при ипотеке (14 календарных дней)"),
            (4, 4, 50, 100_000, 5_000_000, "Продано"),
            (1, -1, 14, 100_000, 1_400_000, "Свободно")]):
        r = 7 + i * 4
        for column, value in {2: floor, 3: unit, 4: "0к", 5: area, 6: "м2"}.items():
            s.cell(r, column, value)
        s.cell(r + 2, 3, f"{price:,}".replace(",", " "))
        s.cell(r + 2, 5, amount)
        s.cell(r + 3, 3, status)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def snapshot(corpus=1, as_of="2026-11-01", rows=None):
    got = chessboard.read(book(corpus, rows))
    for data in got["buildings"].values():
        data["as_of"] = as_of
    return got


def contract(unit=1, amount=3_200_000, signed="2026-11-02", area=40):
    return {"unit": f"корп 1 кв.{unit}", "contract": f"ДДУ {unit}",
            "signed": signed, "area": area, "amount": amount, "product": "Квартира"}


def test_reader_keeps_studios_and_does_not_mix_underground_lots():
    got = chessboard.lots(snapshot(), "2026-11-03")
    assert len(got) == 5
    assert sum(x["product"] == "apartment" for x in got) == 4
    assert len({x["key"] for x in got}) == 5
    assert got[1]["status"] == "regrouping"
    assert got[0]["price_per_sqm"] == 100_000
    assert got[0]["cell"] == "C7"


def test_three_uploads_keep_all_corps_and_replace_only_the_uploaded_one(tmp_path):
    for corpus in [1, 3, 2]:
        sales_store.save(tmp_path, "Проба", {"chessboard": snapshot(corpus)}, f"корпус {corpus}.xlsx")
    kept = sales_store.load(tmp_path, "Проба")["sources"]["chessboard"]["data"]
    assert set(kept["buildings"]) == {"1", "2", "3"}
    changed = snapshot(2, "2026-11-03")
    changed["buildings"]["2"]["lots"][0]["status"] = "sold"
    sales_store.save(tmp_path, "Проба", {"chessboard": changed}, "новый.xlsx")
    after = sales_store.load(tmp_path, "Проба")["sources"]["chessboard"]["data"]
    assert after["buildings"]["1"] == kept["buildings"]["1"]
    assert after["buildings"]["2"]["lots"][0]["status"] == "sold"
    with pytest.raises(ValueError, match="старше"):
        sales_store.save(tmp_path, "Проба", {"chessboard": snapshot(2)}, "старый.xlsx")
    assert sales_store.load(tmp_path, "Проба")["sources"]["chessboard"]["data"] == after


@pytest.mark.parametrize("amount,expected", [(3_400_000, 0), (4_600_000, 0),
                                             (3_200_000, 1), (4_800_000, 1)])
def test_price_question_requires_more_than_fifteen_percent(amount, expected):
    found = chessboard.questions(snapshot(), [contract(amount=amount)], "", "2026-11-03")
    assert len(found) == expected
    if expected:
        assert "шахматки" in found[0]["text"] and "почему" in found[0]["text"]


def test_old_future_ambiguous_and_inconsistent_prices_do_not_accuse_people():
    # Прайс действует до обновления: возраст снимка сам по себе его не отменяет.
    assert chessboard.questions(snapshot(as_of="2026-10-01"), [contract()], "", "2026-11-03")
    assert not chessboard.questions(snapshot(as_of="2026-11-04"), [contract()], "", "2026-11-03")
    assert not chessboard.questions(snapshot(), [contract(signed="2026-10-31")], "", "2026-11-03")
    bad = snapshot()
    bad["buildings"]["1"]["lots"][0]["price_consistent"] = False
    assert not chessboard.questions(bad, [contract()], "", "2026-11-03")
    assert not chessboard.questions(snapshot(), [dict(contract(), product="Машиноместа")], "", "2026-11-03")
    combined = chessboard.merge(snapshot(), snapshot(2), "two.xlsx")
    assert chessboard.match(chessboard.lots(combined), "1") is None


def test_booking_on_sold_flat_is_asked_without_a_contract_export():
    text = "Отчёт за 03.11.2026\nТекущих броней: 1\n- квартира №4, 50 кв.м."
    got = sales_questions.questions(None, None, None, "2026-11-03",
                                    snapshot=snapshot(), report_text=text)
    assert len(got) == 1 and got[0]["kind"] == "chess_status"
    assert "Продано" in got[0]["text"]
    assert not sales_questions.questions(None, None, None, "2026-11-03", {got[0]["key"]},
                                         snapshot=snapshot(), report_text=text)


def test_forecast_separates_bookings_and_regrouping_and_counts_only_free_stock():
    rows = [contract(unit=99, amount=5_000_000, signed="2026-08-15", area=60)]
    out = chessboard.overlay(snapshot(), rows, "2026-11-03")
    assert out["available"] == 1 and out["available_area"] == 40
    assert out["valuation"] == 4_000_000
    assert out["booked"] == 1
    assert out["regrouping_units"] == 1 and out["regrouping_lots"] is None
    assert out["regrouping_value"] is None
    assert out["pace_area"] == 20 and out["months_to_sell"] == 2
    assert out["pace_months"] == ["2026-08", "2026-09", "2026-10"]
    other_corpus = dict(rows[0], unit="корп 2 кв.99", area=600)
    assert chessboard.overlay(snapshot(), rows + [other_corpus], "2026-11-03")["pace_area"] == 20
    # Новый договор после снимка исключает лот из свободного остатка ровно один раз.
    out = chessboard.overlay(snapshot(), rows + [contract(), contract()], "2026-11-03")
    assert out["available"] == 0 and out["adjusted_signed"] == 1


def test_missing_rate_or_price_remains_unknown():
    out = chessboard.overlay(snapshot(), [], "2026-11-03")
    assert out["months_to_sell"] is None
    bad = snapshot()
    bad["buildings"]["1"]["lots"][0]["price_consistent"] = False
    assert chessboard.overlay(bad, [], "2026-11-03")["valuation"] is None


def test_overlay_reaches_report_with_the_same_numbers(tmp_path):
    import developaid_management_report as report
    from test_management_report_model import _contract

    rows = [_contract("2026-08-15", "Квартира", 60, 5_000_000)]
    sales_store.save(tmp_path, "Проба", {"contracting": {"rows": rows}, "chessboard": snapshot()}, "book.xlsx")
    result = report.sales("Проба", "month", "2026-11-03", tmp_path)
    expected = chessboard.overlay(snapshot(), rows, "2026-11-03")
    assert result["chessboard"] == expected
    body = report._sales_depth_html(result, "month")
    assert chessboard.render(expected) in body


def test_upload_requires_a_date_and_keeps_each_corpus(client):
    assert client.post("/cabinet/contracting?project=Проба", content=book()).status_code == 422
    client.post("/cabinet/contracting", content=_workbook())
    for corpus in [1, 2, 3]:
        response = client.post("/cabinet/contracting", params={
            "project": "Проверочный ЖК", "as_of": "2026-11-01"}, content=book(corpus))
        assert response.status_code == 200, response.text
    summary = client.get("/cabinet/sales/summary", params={"project": "Проверочный ЖК"}).json()
    assert summary["chessboard"]["counts"]["available"] == 3
    assert "Состав новых лотов" in summary["chessboard_html"]
    assert client.post("/cabinet/contracting", params={"project": "Проверочный ЖК",
                       "as_of": "2026-10-01"}, content=book()).status_code == 422
    import developaid_management_report as report
    result = report.sales("Проверочный ЖК", "month", datetime.date.today())
    assert result["chessboard"] == summary["chessboard"]


def test_contract_stated_price_is_read_and_used_in_comparison():
    from test_the_sales_report_reads_the_rooms import _book
    from market_search import contracting

    rows = contracting.read_contracts(_book())["rows"]
    assert rows[0]["contract_price_per_sqm"] == 600_000
    row = contract()
    row["contract_price_per_sqm"] = 100_000
    assert not chessboard.questions(snapshot(), [row], "", "2026-11-03")


def test_the_bot_receives_the_chessboard_and_does_not_repeat_the_question(monkeypatch, tmp_path):
    from test_the_bot_reads_the_sales_chat import _Bot
    import developaid_monitor as monitor
    import developaid_management_report as report

    bot = _Bot(monkeypatch, tmp_path)
    today = datetime.date.today()
    where = sales_store.default_dir()
    sales_store.save(where, "Проба", {"chessboard": snapshot(as_of=today.isoformat())}, "board.xlsx")
    monitor._project_dir("Тестовый проект")
    report.link_sales("Тестовый проект", "Проба", "тест")
    bot.send("/site Тестовый проект")
    text = (f"Отчёт за {today:%d.%m.%Y}\nВстречи за день - 1\nТекущих броней: 1\n"
            "- квартира №4, 50 кв.м.")
    import time
    bot.send(text, date=int(time.time()))
    messages = [text for chat, text in bot.said if chat == bot.chat["id"]]
    assert len(messages) == 1 and "Продано" in messages[0]
    bot.send(text, date=int(time.time()))
    assert len([text for chat, text in bot.said if chat == bot.chat["id"]]) == 1


def test_sales_page_draws_the_shared_overlay(client):
    import main_registry
    from browser import chromium_or_skip, serve
    from playwright.sync_api import expect, sync_playwright

    client.post("/cabinet/contracting", content=_workbook())
    response = client.post("/cabinet/contracting", params={"project": "Проверочный ЖК",
                           "as_of": "2026-11-01"}, content=book())
    assert response.status_code == 200
    with serve(main_registry.app, 18848) as base, sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chromium_or_skip()))
        try:
            page = browser.new_page(viewport={"width": 390, "height": 844})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.request.post(base + "/cabinet/login", form={"key": "cabinet-probe-key"})
            page.goto(base + "/cabinet/sales")
            expect(page.locator(".chessboard-overlay")).to_be_visible()
            expect(page.locator(".chessboard-overlay")).to_contain_text("Состав новых лотов")
            expect(page.locator("#chessboardDate")).to_be_visible()
            page.fill("#chessboardDate", "2026-11-02")
            with page.expect_response("**/cabinet/contracting?*") as uploaded:
                page.locator("#cf").set_input_files({"name": "корпус 2.xlsx",
                    "mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    "buffer": book(2)})
            assert uploaded.value.status == 200
            expect(page.locator(".chessboard-overlay")).to_contain_text("свободно квартир — 2")
            assert not errors
        finally:
            browser.close()


def test_rendered_overlay_fits_a_phone_and_keeps_regrouping_explanation():
    from browser import chromium_or_skip
    from playwright.sync_api import sync_playwright, expect

    block = chessboard.overlay(snapshot(), [], "2026-11-03")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chromium_or_skip()))
        try:
            page = browser.new_page(viewport={"width": 390, "height": 844})
            page.set_content("<html><meta name='viewport' content='width=device-width,initial-scale=1'>"
                             + chessboard.render(block) + "</html>")
            expect(page.locator(".chessboard-overlay")).to_be_visible()
            expect(page.locator(".chessboard-overlay")).to_contain_text("Состав новых лотов")
            assert page.evaluate("document.documentElement.scrollWidth") <= 390
        finally:
            browser.close()
