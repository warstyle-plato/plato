"""Readable payment amounts reach the shared calculation without an audit gate."""
import copy
import datetime

import pytest

import developaid_admin_expenses_cash as cash
import developaid_funding_reconciliation as reconciliation
import developaid_management_report as report
import developaid_monitor_dashboard as dashboard
from test_funding_strict_source_readers import CUT, source_case
from test_the_approved_budget_says_what_it_is_made_of import SMETA


def report_for(funding):
    return {"kind": "week", "end": CUT.isoformat(), "funding": {
        "state": "ok", "rss": CUT.isoformat(),
        "draws": {"period": 0, "month": 0, "total": 0},
        "interest": {"period": 0, "month": 0, "total": 0}, "limit": funding}}


@pytest.mark.parametrize("incomplete_count", [1, 7])
def test_partial_payments_keep_full_unknown_and_show_the_readable_calculation(tmp_path, monkeypatch, incomplete_count):
    _, funding = source_case(tmp_path, monkeypatch,
                            [(CUT, 100, "2.6")] + [(CUT, None, "2.6")] * incomplete_count)
    r = funding["reconciliation"]
    assert r["paid_at_cut"] is r["available_bank_limit"] is r["calculated_additional"] is None
    observed = r["calculation"]
    assert observed["basis"] == "observed_payments" and observed["partial"]
    assert observed["observed_count"] == 1
    assert observed["paid_at_cut"] == 100
    assert observed["available_bank_limit"] == sum(SMETA.values()) - 100
    assert observed["calculated_additional"] == r["budget"] - sum(SMETA.values())
    assert len(observed["missing_payment_rows"]) == incomplete_count
    before = copy.deepcopy(funding)
    built = report_for(funding)
    tiles = {item["label"]: item for item in report.tiles(built)}
    assert tiles["Оплачено с начала проекта"]["value"] == "учтено " + report._rub(100)
    assert tiles["Доступный остаток лимита банка"]["value"] == "расчётно " + report._rub(observed["available_bank_limit"])
    need = tiles["Расчётная потребность в допфинансировании"]
    assert need["value"] == report._rub(observed["calculated_additional"])
    for label in ("Оплачено с начала проекта", "Доступный остаток лимита банка",
                  "Расчётная потребность в допфинансировании"):
        assert tiles[label]["note"].count("Расчёт по учтённым оплатам.") == 1
        assert tiles[label]["note"].count(
            f"Строк с непрочитанными реквизитами: {incomplete_count}.") == 1
    summary = dashboard.funding_cash_summary(funding, {"balance_after_observed_payments": 999}, report._rub)
    assert summary["amount"] == observed["calculated_additional"]
    finding = next(row for row in report.findings(built) if row["topic"] == "Финансирование")
    assert report._rub(summary["amount"]) in finding["text"]
    html = report._funding_html(built)
    assert "учтено " + report._rub(100) in html
    assert report._rub(summary["amount"]) in html
    assert "сверка первичных источников не завершена" not in html.lower()
    assert funding == before


def test_unknown_only_is_not_a_known_zero(tmp_path, monkeypatch):
    _, funding = source_case(tmp_path, monkeypatch, [(CUT, None, "2.6")])
    c = funding["reconciliation"]["calculation"]
    assert c["observed_count"] == 0
    assert c["paid_at_cut"] is c["available_bank_limit"] is c["calculated_additional"] is None
    assert dashboard.funding_cash_summary(funding, {}, cash.money)["amount"] is None
    assert "не прочитано ни одной оплаты" in reconciliation.calculation_note(funding["reconciliation"])


def test_legacy_canonical_row_keeps_the_summary_payment_warning(tmp_path, monkeypatch):
    _, funding = source_case(tmp_path, monkeypatch, [(CUT, 100, "2.6"), (CUT, None, "2.6")])
    row = next(row for row in funding["reconciliation"]["display_rows"]
               if row["key"] == "calculated_additional")
    row["note"] = "Пояснение сохранённого отчёта."
    need = next(tile for tile in report.tiles(report_for(funding))
                if tile.get("group") == "additional_funding")
    assert "Пояснение сохранённого отчёта." in need["note"]
    assert need["note"].count("Расчёт по учтённым оплатам.") == 1
    assert need["note"].count("Строк с непрочитанными реквизитами: 1.") == 1


@pytest.mark.parametrize("payments,count", [([], 0), ([(CUT, 0, "2.6")], 1)])
def test_complete_empty_or_explicit_zero_stays_a_known_zero(tmp_path, monkeypatch, payments, count):
    _, funding = source_case(tmp_path, monkeypatch, payments)
    c = funding["reconciliation"]["calculation"]
    assert not c["partial"] and c["observed_count"] == count
    assert c["paid_at_cut"] == 0 and c["available_bank_limit"] == sum(SMETA.values())
    assert dashboard.funding_cash_summary(funding, {}, cash.money)["amount"] is not None
    need = next(tile for tile in report.tiles(report_for(funding))
                if tile.get("group") == "additional_funding")
    assert need["note"].count("Расчёт по сохранённым данным.") == 1


def test_unknown_scope_or_date_is_not_added_to_the_observed_subset(tmp_path, monkeypatch):
    _, funding = source_case(tmp_path, monkeypatch, [
        (CUT, 100, "2.6"), (CUT, 777, "unreadable"), (None, 500, "2.6")])
    c = funding["reconciliation"]["calculation"]
    assert c["paid_at_cut"] == 100 and c["observed_count"] == 1
    assert len(c["missing_payment_rows"]) == 2
    assert c["available_bank_limit"] == sum(SMETA.values()) - 100
    assert c["calculated_additional"] == funding["reconciliation"]["budget"] - sum(SMETA.values())
    assert not c["missing_fields"]
    assert funding["reconciliation"]["paid_at_cut"] is None


def test_old_dto_cannot_invent_an_empty_observed_subset():
    c = reconciliation.bank_calculation({
        "1": {"total": None, "incomplete_rows": [{"source_row": 2, "fields": ["amount"]}]},
        "2": {"total": None, "observed_total": 100, "observed_count": 1},
    }, {"1": 500, "2": 500})
    assert c["paid_at_cut"] == 100
    assert c["available_bank_limit"] is None
    assert "chapter_payments" in c["missing_fields"]


def test_future_rows_are_filtered_and_refunds_keep_their_sign(tmp_path, monkeypatch):
    _, funding = source_case(tmp_path, monkeypatch, [
        (CUT, 100, "2.6"), (CUT, -25, "2.6"),
        (CUT + datetime.timedelta(days=1), None, "2.6")])
    c = funding["reconciliation"]["calculation"]
    assert c["paid_at_cut"] == 75 and c["observed_count"] == 2
    assert not c["partial"] and not c["missing_payment_rows"]
    assert c["available_bank_limit"] == sum(SMETA.values()) - 75


def test_missing_model_does_not_hide_bank_payment_observations(tmp_path, monkeypatch):
    rss, _ = source_case(tmp_path, monkeypatch, [(CUT, 100, "2.6"), (CUT, None, "2.6")])
    monkeypatch.setattr(dashboard, "_finance_for_cut", lambda *_: {"known": False, "reason": "ФМ не загружена."})
    funding = dashboard._funding_risk("demo", rss, CUT, {})
    c = funding["bank_observations"]["calculation"]
    assert c["paid_at_cut"] == 100
    assert c["available_bank_limit"] == sum(SMETA.values()) - 100
    assert c["calculated_additional"] is None and c["missing_fields"] == ["budget"]
    tiles = {tile["label"]: tile for tile in report.tiles(report_for(funding))}
    assert tiles["Оплачено с начала проекта"]["value"] == "учтено " + report._rub(100)
    assert tiles["Осталось по смете после всех оплат"]["value"] == "расчётно " + report._rub(c["available_bank_limit"])
    assert tiles["Расчётная потребность в допфинансировании"]["value"] == "нет данных"


def test_missing_limit_preserves_readable_paid_amount(tmp_path, monkeypatch):
    _, funding = source_case(tmp_path, monkeypatch, [(CUT, 100, "2.6")], limits={**SMETA, "2": None})
    c = funding["reconciliation"]["calculation"]
    assert c["paid_at_cut"] == 100
    assert c["available_bank_limit"] is c["calculated_additional"] is None
    assert "bank_limit" in c["missing_fields"]


def test_known_bank_base_is_visible_with_unknown_ahr_cash():
    summary = cash.funding_summary(250, {"observed_payments": 100, "balance_after_observed_payments": None}, cash.money)
    assert summary["scope"] == "bank_only" and summary["amount"] == 250


@pytest.mark.parametrize("width", [390, 1440])
def test_rendered_partial_funding_tile_has_one_warning_in_screen_and_pdf(tmp_path, monkeypatch, width):
    import io
    import re
    from pypdf import PdfReader
    from playwright.sync_api import sync_playwright, expect
    from browser import chromium_or_skip
    from developaid_report_page import REPORT_PAGE

    _, funding = source_case(tmp_path, monkeypatch,
                            [(CUT, 100, "2.6")] + [(CUT, None, "2.6")] * 7)
    built = report_for(funding)
    need = next(tile for tile in report.tiles(built) if tile.get("group") == "additional_funding")
    value = report._rub(funding["reconciliation"]["calculation"]["calculated_additional"])
    qualifier = "Расчёт по учтённым оплатам."
    count = "Строк с непрочитанными реквизитами: 7."
    styles = re.search(r'<style>(.*?)</style>', REPORT_PAGE, re.S)[0]
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chromium_or_skip()), headless=True)
        page = browser.new_page(viewport={"width": width, "height": 950})
        page.set_content('<meta charset="utf-8">' + styles + '<main id="reportBox">'
                         + report._tiles_html(report.tiles(built)) + '</main>')
        tile = page.locator('.tile[data-group="additional_funding"]')
        expect(tile).to_have_count(1)
        expect(tile.locator('.v')).to_have_text(value)
        text = tile.inner_text()
        assert text.count(qualifier) == text.count(count) == 1
        assert "Утверждённый бюджет уже включает АХР." in text
        assert tile.evaluate('(e)=>e.scrollWidth <= e.clientWidth')
        page.screenshot(path=str(tmp_path/f'partial-funding-{width}.png'), full_page=True)
        if width == 1440:
            # Print the same canonical tile renderer on its own to count its warning in PDF.
            page.set_content('<meta charset="utf-8">' + styles + '<main id="reportBox">'
                             + report._tiles_html([need]) + '</main>')
            raw = page.pdf(format="A4")
            (tmp_path/'partial-funding.pdf').write_bytes(raw)
            text = " ".join(" ".join(sheet.extract_text() or '' for sheet in
                                       PdfReader(io.BytesIO(raw)).pages).split())
            assert text.count(qualifier) == text.count(count) == 1
            assert value in text
        browser.close()
