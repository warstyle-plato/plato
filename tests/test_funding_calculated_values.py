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


def test_partial_payments_keep_full_unknown_and_show_the_readable_calculation(tmp_path, monkeypatch):
    _, funding = source_case(tmp_path, monkeypatch, [(CUT, 100, "2.6"), (CUT, None, "2.6")])
    r = funding["reconciliation"]
    assert r["paid_at_cut"] is r["available_bank_limit"] is r["calculated_additional"] is None
    observed = r["calculation"]
    assert observed["basis"] == "observed_payments" and observed["partial"]
    assert observed["observed_count"] == 1
    assert observed["paid_at_cut"] == 100
    assert observed["available_bank_limit"] == sum(SMETA.values()) - 100
    assert observed["calculated_additional"] == r["budget"] - sum(SMETA.values())
    assert len(observed["missing_payment_rows"]) == 1
    before = copy.deepcopy(funding)
    built = report_for(funding)
    tiles = {item["label"]: item for item in report.tiles(built)}
    assert tiles["Оплачено с начала проекта"]["value"] == "учтено " + report._rub(100)
    assert tiles["Доступный остаток лимита банка"]["value"] == "расчётно " + report._rub(observed["available_bank_limit"])
    need = tiles["Расчётная потребность в допфинансировании"]
    assert need["value"] == report._rub(observed["calculated_additional"])
    assert "по учтённым оплатам" in need["note"] and "реквизитами: 1" in need["note"]
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


@pytest.mark.parametrize("payments,count", [([], 0), ([(CUT, 0, "2.6")], 1)])
def test_complete_empty_or_explicit_zero_stays_a_known_zero(tmp_path, monkeypatch, payments, count):
    _, funding = source_case(tmp_path, monkeypatch, payments)
    c = funding["reconciliation"]["calculation"]
    assert not c["partial"] and c["observed_count"] == count
    assert c["paid_at_cut"] == 0 and c["available_bank_limit"] == sum(SMETA.values())
    assert dashboard.funding_cash_summary(funding, {}, cash.money)["amount"] is not None


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
