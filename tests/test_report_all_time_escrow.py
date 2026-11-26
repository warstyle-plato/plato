"""Один датированный срез поступлений за все продажи, отдельно от квартала."""
from __future__ import annotations

import copy
import datetime
import io

import pytest
from openpyxl import Workbook

import developaid_management_report as report
from market_search import contracting
from test_management_report_model import _contract

M = 1_000_000
END = datetime.date(2026, 10, 18)
LABEL = "Поступило на эскроу с начала продаж"


def _row(signed="2026-10-09", *, product="Квартира", amount=80*M, paid=20*M,
         observed=True, unit="корп 1 кв.1", contract="synthetic-A", state="Зарегистрирован"):
    row = _contract(signed, product, 60, amount)
    row.update(escrow_paid=paid, escrow_observed=observed, unit=unit, contract=contract, state=state)
    return row


def _contracts(rows, as_of="2026-10-18", provenance="uploader_declared"):
    return {"rows": rows, "as_of": as_of, "as_of_provenance": provenance}


def _dto(rows, **kwargs):
    return report._all_time_escrow(_contracts(rows, **kwargs), END)


def _kept(rows, **kwargs):
    return {"project": "Синтетический проект", "sources": {"contracting": {
        "at": "2026-10-18T23:00:00Z", "file": "synthetic.xlsx", "data": _contracts(rows, **kwargs)}}}


def test_week_and_month_share_all_time_cut_but_quarter_excludes_old_contracts(monkeypatch):
    rows = [_row(), _row("2026-10-05", amount=100*M, paid=100*M, unit="корп 1 кв.2"),
            _row("2024-08-01", amount=50*M, paid=50*M, unit="корп 1 кв.3")]
    kept = _kept(rows)
    before = copy.deepcopy(kept)
    monkeypatch.setattr(report.sales_store, "load", lambda *args: kept)
    week, month = [report.sales("synthetic", kind, END) for kind in ("week", "month")]
    assert week["all_time_escrow"] == month["all_time_escrow"]
    assert week["all_time_escrow"]["contract_amount"] == 230*M
    assert week["all_time_escrow"]["paid"] == 170*M
    assert week["all_time_escrow"]["expected"] == 60*M
    assert week["quarter"]["fact"]["amount"] == 180*M
    assert week["quarter"]["fact"]["escrow"] == 120*M
    assert week["period"]["amount"] != month["period"]["amount"]
    # No other sales number changes when source evidence changes.
    changed = copy.deepcopy(kept)
    for row in changed["sources"]["contracting"]["data"]["rows"]:
        row["escrow_observed"] = False
    monkeypatch.setattr(report.sales_store, "load", lambda *args: changed)
    legacy = report.sales("synthetic", "week", END)
    assert {k:v for k,v in legacy.items() if k != "all_time_escrow"} == {
        k:v for k,v in week.items() if k != "all_time_escrow"}
    assert kept == before


def test_all_products_use_paid_cells_and_ignore_future_receipts_and_releases():
    rows = [_row(product="Квартира", amount=80*M, paid=20*M),
            _row(product="Машиноместо", amount=5*M, paid=5*M, unit="ММ-2"),
            _row(product="Кладовая", amount=2*M, paid=0, unit="К-3"),
            _row(product="Коммерция", amount=10*M, paid=3*M, unit="П-4")]
    for row in rows:
        row["escrow_schedule"] = [{"month": "2027-01", "amount": 999*M}]
    source = _contracts(rows)
    source["forecast_releases"] = {"2027-01": 9999*M}
    source["bank_balance"] = 1
    dto = report._all_time_escrow(source, END)
    assert dto["state"] == "ok"
    assert dto["contract_amount"] == 97*M
    assert dto["paid"] == 28*M and dto["expected"] == 69*M
    assert dto["contract_amount"] == dto["paid"] + dto["expected"]


@pytest.mark.parametrize("observed", [None, False])
def test_legacy_missing_observation_cannot_turn_zero_into_known_receipt(observed):
    row = _row(paid=0, observed=observed)
    if observed is None:
        row.pop("escrow_observed")
    dto = _dto([row])
    assert dto["paid"] is None and dto["expected"] is None and dto["known_paid"] is None
    explicit = _dto([_row(paid=0)])
    assert explicit["paid"] == 0 and explicit["expected"] == 80*M


def test_real_native_xlsx_reader_carries_blank_vs_observed_zero_into_the_card():
    book = Workbook()
    sheet = book.active
    sheet.title = contracting.SHEET_CONTRACTS
    for column, title in enumerate(contracting._COLUMNS.values(), 1):
        sheet.cell(6, column, title)
    for row_number, paid in ((7, 0), (8, None)):
        values = {"product": "Квартира", "unit": f"корп 1 кв.{row_number}", "date": datetime.date(2026, 10, 9),
                  "contract": f"synthetic-{row_number}", "state": "Зарегистрирован", "amount": 80*M,
                  "area": 60, "units": 1, "escrow_total": paid}
        for column, key in enumerate(contracting._COLUMNS, 1):
            sheet.cell(row_number, column, values.get(key))
    raw = io.BytesIO()
    book.save(raw)
    source = contracting.read_contracts(raw.getvalue())
    source.update(as_of="2026-10-18", as_of_provenance="uploader_declared")
    assert [row["escrow_paid"] for row in source["rows"]] == [0, 0]
    assert [row["escrow_observed"] for row in source["rows"]] == [True, False]
    dto = report._all_time_escrow(source, END)
    assert dto["known_paid"] == 0 and dto["observed"] == 1 and dto["contracts"] == 2
    assert dto["paid"] is None and dto["expected"] is None


def test_partial_ledger_reports_observed_subtotal_and_coverage_without_total():
    dto = _dto([_row(), _row(paid=0, observed=False, unit="корп 1 кв.2")])
    assert dto["paid"] is None and dto["expected"] is None
    assert dto["known_paid"] == 20*M and dto["observed"] == 1 and dto["contracts"] == 2
    tile = report._all_time_escrow_tile({"all_time_escrow": dto})
    assert tile["value"] == "нет данных"
    assert "Наблюдаемая часть — 20,0 млн ₽" in tile["note"] and "1 из 2" in tile["note"]
    empty = _dto([])
    assert empty["paid"] is None and empty["expected"] is None


@pytest.mark.parametrize("status", ["", "неизвестный статус", "Не зарегистрирован", "Договор не подписан", "Не отменен"])
def test_unconfirmed_status_cannot_prove_valid_contract_scope(status):
    dto = _dto([_row(state=status)])
    assert dto["paid"] is None and dto["expected"] is None


def test_cancelled_drafts_and_future_are_excluded_without_losing_other_product_cohorts():
    rows = [_row(), _row(state="Расторгнут", unit="2"), _row(state="Бронь", unit="3"),
            _row(state="Проект договора", unit="4"), _row("2026-10-19", unit="5")]
    dto = _dto(rows)
    assert dto["paid"] == 20*M and dto["expected"] == 60*M
    assert (dto["cancelled"], dto["drafts"], dto["future"]) == (1, 2, 1)
    assert _dto([_row(state="Не расторгнут")])["paid"] == 20*M


@pytest.mark.parametrize("as_of,provenance", [(None,"uploader_declared"), ("","uploader_declared"),
    ("2026-02-30","uploader_declared"), ("2026-10-18T12:00:00","uploader_declared"),
    ("2026-10-19","uploader_declared"), ("2026-10-18",None)])
def test_source_date_is_required_and_upload_or_future_source_cannot_prove_report_cut(as_of, provenance):
    dto = _dto([_row()], as_of=as_of, provenance=provenance)
    assert dto["paid"] is None and dto["expected"] is None


def test_old_source_keeps_its_own_cohort_cut_and_visibly_names_the_gap():
    dto = _dto([_row(), _row("2026-10-15", unit="2")], as_of="2026-10-10")
    assert dto["paid"] == 20*M and dto["expected"] == 60*M and dto["future"] == 1
    assert dto["as_of"] == "2026-10-10" and dto["report_end"] == "2026-10-18" and dto["stale"]
    note = report._all_time_escrow_tile({"all_time_escrow": dto})["note"]
    assert "10.10.2026" in note and "до 18.10.2026 не учтены" in note


def test_undated_unidentified_and_duplicate_rows_do_not_double_count_observed_money():
    for row in (dict(_row(unit="2"), signed=None), _row(unit="")):
        dto = _dto([_row(), row])
        assert dto["paid"] is None and dto["expected"] is None
    duplicated = _dto([_row(), _row(unit="корп 1 кв.01")])
    assert duplicated["paid"] is None and duplicated["known_paid"] is None
    assert duplicated["duplicates"] == 2
    # One contract may cover two different lots.
    assert _dto([_row(), _row(unit="корп 1 кв.2")])["paid"] == 40*M


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, True, None])
def test_invalid_or_unobserved_paid_amount_never_becomes_a_payment(value):
    dto = _dto([_row(paid=value)])
    assert dto["paid"] is None and dto["expected"] is None


@pytest.mark.parametrize("value", [0, float("inf"), -1, True, None])
def test_unknown_contract_amount_does_not_suppress_observed_receipts_or_create_pending(value):
    dto = _dto([_row(amount=value)])
    assert dto["paid"] == 20*M and dto["expected"] is None and dto["overpaid"] == 0


def test_overpayment_does_not_net_against_another_buyers_pending_payment():
    dto = _dto([_row(amount=10*M, paid=20*M), _row(amount=80*M, paid=0, unit="2")])
    assert dto["paid"] == 20*M and dto["overpaid"] == 10*M
    assert dto["expected"] is None and dto["state"] == "partial"
    assert "превышают" in dto["reason"]


def test_html_text_and_tiles_share_one_value_and_preserve_all_other_financial_tiles(monkeypatch):
    monkeypatch.setattr(report.sales_store, "load", lambda *args: _kept([_row()]))
    built = report.build("Пустой синтетический", "week", END, sales_project="synthetic")
    tiles = report.tiles(built)
    tile = next(t for t in tiles if t["label"] == LABEL)
    assert tile["value"] == "20,0 млн ₽"
    for consumer in (report.render_html(built), report.render_text(built)):
        assert LABEL in consumer and tile["value"] in consumer
        assert "Ещё ожидается 60,0 млн ₽" in consumer
        assert "18.10.2026" in consumer and "не остаток банка" in consumer
    old = copy.deepcopy(built)
    old["sales"].pop("all_time_escrow")
    assert [t for t in report.tiles(old) if t["label"] != LABEL] == [t for t in tiles if t["label"] != LABEL]
    missing = next(t for t in report.tiles(old) if t["label"] == LABEL)
    assert missing["value"] == "нет данных" and "В сохранённой сводке" in missing["note"]
