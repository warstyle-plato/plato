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


@pytest.mark.parametrize("amount,expected", [(4_000_000, 0), (3_400_001, 0), (3_400_000, 0),
                                             (3_399_999, 1), (3_200_000, 1), (4_600_000, 0),
                                             (4_800_000, 0), (8_000_000, 0), (40_000_000, 0)])
def test_price_question_requires_discount_strictly_over_fifteen_percent(amount, expected):
    found = chessboard.questions(snapshot(), [contract(amount=amount)], "", "2026-11-03")
    assert len(found) == expected
    if expected:
        assert "ниже цены шахматки" in found[0]["text"] and "почему" in found[0]["text"]
        assert "вверх" not in found[0]["text"]


def test_explicit_contract_rate_above_chessboard_does_not_ask():
    row = dict(contract(amount=6_400_000), contract_price_per_sqm=160_000)
    assert not chessboard.questions(snapshot(), [row], "", "2026-11-03")


def test_discount_question_keeps_its_identity_and_is_not_asked_twice():
    contracts = {"rows": [contract()]}
    first = sales_questions.questions(None, contracts, "2026-11-03", "2026-11-03", snapshot=snapshot())
    assert len(first) == 1 and first[0]["key"] == "chess-price:ДДУ 1"
    assert not sales_questions.questions(None, contracts, "2026-11-03", "2026-11-03",
                                         {first[0]["key"]}, snapshot=snapshot())


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
    out = chessboard.overlay(snapshot(), rows, "2026-11-03",
                             {"from": "2026-08-01", "through": "2026-10-31"})
    assert out["available"] == 1 and out["available_area"] == 40
    assert out["valuation"] == 4_000_000
    assert out["booked"] == 1
    assert out["regrouping_units"] == 1 and out["regrouping_lots"] is None
    assert out["regrouping_value"] is None
    assert out["pace_area"] == 20 and out["months_to_sell"] == 2
    assert out["pace_months"] == ["2026-08", "2026-09", "2026-10"]
    other_corpus = dict(rows[0], unit="корп 2 кв.99", area=600)
    assert chessboard.overlay(snapshot(), rows + [other_corpus], "2026-11-03",
                              {"from": "2026-08-01", "through": "2026-10-31"})["pace_area"] == 20
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


@pytest.mark.parametrize("width", [390, 1440])
def test_sales_page_draws_the_shared_overlay(client, width):
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
            page = browser.new_page(viewport={"width": width, "height": 844})
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
            if width == 1440:
                from pypdf import PdfReader
                printed = page.evaluate("salesPrintHtml()")
                paper = browser.new_page()
                paper.set_content(printed)
                pdf = paper.pdf()
                text = " ".join(" ".join((p.extract_text() or "").split())
                                for p in PdfReader(io.BytesIO(pdf)).pages)
                assert "Остаток по шахматке" in text
                assert "Состав новых лотов" in text
                assert "не график поступлений на эскроу" in text
                paper.close()
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


def test_replied_chessboard_question_is_not_repeated_after_asked_file_is_lost(monkeypatch, tmp_path):
    """Main's durable answer journal must remain authoritative after merging stock questions."""
    import html
    import time
    from market_search import sales_dialogue
    from test_sales_chat_answers import _setup, _reply

    bot, where, _ = _setup(monkeypatch, tmp_path)
    today = datetime.date.today()
    sales_store.save(where, "Тест", {"contracting": {"rows": []},
                     "chessboard": snapshot(as_of=today.isoformat())}, "synthetic.xlsx")
    text = (f"Отчёт за {today:%d.%m.%Y}\nВстречи за день - 1\nТекущих броней: 1\n"
            "- квартира №4, 50 кв.м.")
    bot.send(text, date=int(time.time()))
    quoted = html.unescape(next(t for c, t in bot.said if c == bot.chat["id"]))
    assert "Продано" in quoted
    _reply(bot, quoted, text="Бронь снята; в отчёте осталась старая строка.")
    batch = next(iter(sales_dialogue.load(where, "Тест")["batches"].values()))
    assert len(batch["replies"]) == 1
    assert batch["questions"][0]["kind"] == "chess_status"
    sales_questions._asked_path(where, "Тест").unlink()
    sales_store.save(where, "Тест", {"chessboard": snapshot(as_of=today.isoformat())}, "new.xlsx")
    bot.send(text, date=int(time.time()))
    assert len([t for c, t in bot.said if c == bot.chat["id"]]) == 1


def test_pace_deduplicates_same_contract_without_merging_other_corps():
    coverage = {"from": "2026-08-01", "through": "2026-10-31"}
    row = contract(signed="2026-08-15", area=30)
    first = chessboard.overlay(snapshot(), [row], "2026-11-03", coverage)
    twice = chessboard.overlay(snapshot(), [row, dict(row)], "2026-11-03", coverage)
    assert first["pace_area"] == twice["pace_area"] == 10
    assert twice["pace_duplicate_rows"] == 1
    combined = chessboard.merge(snapshot(), snapshot(2), "two.xlsx")
    other = dict(row, unit="корпус 2 кв.1")
    assert chessboard.overlay(combined, [row, other], "2026-11-03", coverage)["pace_area"] == 20
    # Conflicting quantities for one identity are not silently picked or added.
    bad = chessboard.overlay(snapshot(), [row, dict(row, area=50)], "2026-11-03", coverage)
    assert bad["pace_state"] == "unknown" and bad["pace_area"] is None
    assert bad["months_to_sell"] is None


def test_missing_export_unknown_coverage_and_confirmed_zero_are_different():
    coverage = {"from": "2026-08-01", "through": "2026-10-31"}
    missing = chessboard.overlay(snapshot(), None, "2026-11-03")
    assert missing["pace_state"] == "missing" and missing["pace_area"] is None
    assert missing["pace_observed_area"] is None
    assert "Контрактация не загружена" in chessboard.render(missing)
    partial = chessboard.overlay(snapshot(), [contract(signed="2026-08-15", area=30)], "2026-11-03")
    assert partial["pace_state"] == "partial" and partial["pace_area"] is None
    assert partial["pace_observed_area"] == 10 and partial["months_to_sell"] is None
    assert partial["confirmed_months_to_sell"] is None
    assert partial["conditional_months_to_sell"] == 4 and partial["forecast_state"] == "conditional"
    assert "при сохранении темпа по загруженным договорам; полнота периода не подтверждена" in chessboard.render(partial)
    assert "Только по найденным договорам" in chessboard.render(partial)
    old = chessboard.overlay(snapshot(), [], "2026-11-03", {"from": "2026-08-01", "through": "2026-09-30"})
    assert old["pace_state"] == "partial" and old["pace_area"] is None
    zero = chessboard.overlay(snapshot(), [], "2026-11-03", coverage)
    assert zero["pace_state"] == "ok" and zero["pace_area"] == 0
    assert zero["months_to_sell"] is None


def test_public_stock_without_contract_source_does_not_claim_zero_pace(client):
    response = client.post("/cabinet/contracting", params={"project": "Проба", "as_of": "2026-11-01"}, content=book())
    assert response.status_code == 200
    block = response.json()["chessboard"]
    assert block["pace_state"] == "missing" and block["pace_area"] is None
    got = client.get("/cabinet/sales/summary", params={"project": "Проба"}).json()
    assert got["chessboard"] == block


@pytest.mark.parametrize("changed", [{"area": 50}, {"amount": 9_000_000}, {"contract_price_per_sqm": 999_999}])
def test_conflicting_contract_facts_do_not_pick_a_price_or_forecast(changed):
    row = contract(signed="2026-08-15", area=30)
    out = chessboard.overlay(snapshot(), [row, dict(row, **changed)], "2026-11-03",
                             {"from": "2026-08-01", "through": "2026-10-31"})
    assert out["pace_state"] == "unknown" and out["pace_area"] is None
    assert out["conditional_months_to_sell"] is None and out["months_to_sell"] is None
    fresh = contract()
    assert not chessboard.questions(snapshot(), [fresh, dict(fresh, **changed)], "", "2026-11-03")


@pytest.mark.parametrize("path,method", [("/cabinet/sales/summary", "get"), ("/cabinet/contracting", "post")])
def test_private_stock_responses_are_not_cached_and_require_admission_before_source_io(client, monkeypatch, path, method):
    from market_search import cabinet
    from fastapi import HTTPException
    request = getattr(client, method)
    data = {"content": book()} if method == "post" else {}
    params = {"project": "Проба", "as_of": "2026-11-01"}
    response = request(path, params=params, **data)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["pragma"] == "no-cache"

    def fail_io(*_args, **_kwargs):
        raise AssertionError("private-source-marker")

    monkeypatch.setattr(sales_store, "load", fail_io)
    response = request(path, params=params, **data)
    assert response.status_code == 500
    assert "private-source-marker" not in response.text
    assert response.headers["cache-control"] == "private, no-store"
    client.cookies.clear()
    response = request(path, params=params, **data)
    assert response.status_code == 401
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["pragma"] == "no-cache"

    def denied(_request):
        raise HTTPException(403, "synthetic denied")

    monkeypatch.setattr(cabinet, "require_cabinet", denied)
    response = request(path, params=params, **data)
    assert response.status_code == 403
    assert response.headers["cache-control"] == "private, no-store"


def test_invalid_stock_upload_is_not_cached(client):
    response = client.post("/cabinet/contracting", content=b"not-a-workbook")
    assert response.status_code == 422
    assert response.headers["cache-control"] == "private, no-store"


def test_conflicting_price_facts_do_not_fall_back_to_a_median_accusation():
    peers = [dict(contract(unit=i, amount=4_000_000), rooms="2К") for i in (11, 12, 13)]
    low = dict(contract(), rooms="2К", escrow_total=3_200_000)
    contradictory = dict(low, amount=4_000_000)
    got = sales_questions.questions(None, {"rows": peers + [low, contradictory]},
                                    "2026-11-03", "2026-11-03", snapshot=snapshot())
    assert not [q for q in got if q["kind"] in ("price", "chess_price")]
