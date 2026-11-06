"""Offline source preflight stays read-only, private and inconclusive."""
import datetime
import io
import json

import openpyxl
import pytest

from scripts import inspect_funding_sources as probe
from test_the_approved_budget_says_what_it_is_made_of import _finmodel

CUT = "2026-10-31"


def _save(book):
    source = io.BytesIO()
    book.save(source)
    book.close()
    return source.getvalue()


def test_existing_model_reader_is_used_without_disk_cache_or_source_changes(tmp_path, monkeypatch):
    path = tmp_path / "PRIVATE-project.xlsx"
    path.write_bytes(_finmodel())
    # Even if files live in the production cache root, the probe passes streams.
    monkeypatch.setattr(probe.actuals, "DISK_CACHE_ROOTS", [lambda: tmp_path])
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    result = probe.inspect_source(path, "finance", CUT)
    assert result["parsed"] is True
    assert result["admin_leaf_count"] == 1
    assert result["admin_chapter2_leaf_count"] == 1
    assert result["admin_tax_code_in_parsed_items"] is False
    assert result["admin_allocation_total_identity"] is True
    assert result["admin_leaf_fact_plan_identity"] is True
    assert result["metadata"]["data_date"] is None
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before
    assert "PRIVATE-project" not in json.dumps(result)


def test_raw_extra_sheet_is_inspected_even_when_product_parser_omits_it(tmp_path):
    book = openpyxl.load_workbook(io.BytesIO(_finmodel()))
    extra = book.create_sheet("PRIVATE-payment-details")
    extra.append(["Идентификатор платежа", "PRIVATE-customer"])
    extra.append(["PRIVATE-identifier", 987654321])
    path = tmp_path / "finance.xlsx"
    path.write_bytes(_save(book))
    result = probe.inspect_source(path, "finance", CUT)
    assert result["payment_id_header_candidates"] == 1
    assert result["parsed"] is True
    assert "PRIVATE" not in json.dumps(result)
    assert "987654321" not in json.dumps(result)


def test_mixed_map_and_missing_cache_do_not_become_confirmed_allocation(tmp_path):
    book = openpyxl.load_workbook(io.BytesIO(_finmodel()))
    book["статьи_БДДС"].append([None] * 6 + ["2.4.1.2", "PRIVATE", "3.7"])
    sheet = book["cf_1_new"]
    for row in sheet:
        if row[2].value == "2.4.1":
            sheet.cell(row[2].row, 11, "=1+1")  # openpyxl has no cached value
    path = tmp_path / "finance.xlsx"
    path.write_bytes(_save(book))
    result = probe.inspect_source(path, "finance", CUT)
    assert result["admin_mixed_leaf_count"] == 1
    assert result["admin_allocation_known"] is False
    assert result["admin_missing_money_cells"] == 1
    assert result["admin_allocation_to_pay_identity"] is None
    assert result["admin_leaf_fact_plan_identity"] is None


def test_payment_dates_are_counted_without_releasing_payment_details(tmp_path):
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Реестр платежей"
    sheet.cell(9, 13, "ID платежа")
    for r, day in enumerate((datetime.date(2026, 10, 30), datetime.date(2026, 11, 1), None), 10):
        for c, value in ((2, "PRIVATE-company"), (7, "2.6"), (9, day),
                         (10, 987654321), (13, "PRIVATE-id")):
            sheet.cell(r, c, value)
    path = tmp_path / "rss.xlsx"
    path.write_bytes(_save(book))
    result = probe.inspect_source(path, "rss", CUT)
    assert result["payment_row_count"] == 3
    assert result["payment_after_cut_count"] == 1
    assert result["payment_undated_count"] == 1
    assert result["payment_id_header_candidates"] == 1
    assert "PRIVATE" not in json.dumps(result)
    assert "987654321" not in json.dumps(result)


def test_metadata_date_is_not_inferred_from_filename_upload_or_mtime(tmp_path):
    path = tmp_path / "2026-10-01.json"
    path.write_text(json.dumps({"uploaded_at": "2026-10-01", "file_name": "PRIVATE.xlsx"}))
    assert probe._metadata(path, CUT)["data_date"] is None
    path.write_text(json.dumps({"taken_at": "2026-11-01"}))
    assert probe._metadata(path, CUT)["after_cut"] is True


def test_valid_bdds_month_is_not_payment_evidence(tmp_path):
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "П-Ф"
    sheet.append([None, "Октябрь 2026"])
    sheet.append([None, "ПЛАН", "ФАКТ"])
    for name in probe.budgets._BUDGET_ROWS.values():
        sheet.append([name, -100, -50])
    path = tmp_path / "bdds.xlsx"
    path.write_bytes(_save(book))
    result = probe.inspect_source(path, "bdds", CUT)
    assert result["parsed"] is True
    assert result["supplies_cut_month"] is True
    assert result["payment_id_header_candidates"] == 0


def test_schedule_is_read_without_claiming_admin_coverage(tmp_path):
    from funding_schedule_fixture import book

    path = tmp_path / "schedule.xlsx"
    path.write_bytes(book())
    result = probe.inspect_source(path, "schedule", CUT)
    assert result["parsed"] is True
    assert result["row_count"] > 0


def test_reader_messages_and_warnings_are_not_forwarded(tmp_path, monkeypatch, capsys):
    import warnings

    path = tmp_path / "finance.xlsx"
    path.write_bytes(_finmodel())

    def unsafe_reader(*args):
        print("PRIVATE-money")
        warnings.warn("PRIVATE-workbook-name")
        raise ValueError("PRIVATE-body")

    monkeypatch.setattr(probe.dashboard, "_read_finance_baseline", unsafe_reader)
    result = probe.inspect_source(path, "finance", CUT)
    captured = capsys.readouterr()
    assert not captured.out and not captured.err
    assert result["parsed"] is False
    assert "PRIVATE" not in json.dumps(result)


@pytest.mark.parametrize("mode", ["missing", "corrupt", "wrong_sheet"])
def test_unavailable_sources_never_leak_reader_errors(tmp_path, mode):
    path = tmp_path / "PRIVATE.xlsx"
    if mode == "corrupt":
        path.write_bytes(b"PRIVATE-corrupt-data")
    elif mode == "wrong_sheet":
        book = openpyxl.Workbook()
        book.active.title = "PRIVATE-sheet"
        path.write_bytes(_save(book))
    result = probe.inspect_source(path, "rss", CUT)
    assert result.get("parsed") is not True
    assert "PRIVATE" not in json.dumps(result)


def test_even_parsed_sources_cannot_turn_the_primary_gate_green(tmp_path, capsys):
    path = tmp_path / "finance.xlsx"
    path.write_bytes(_finmodel())
    assert probe.main(["--cut", CUT, "--finance", str(path)]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["sources"]["finance"]["parsed"] is True
    assert result["primary_source_gate"] == "BLOCKED"
    assert result["payment_deduplication_verified"] is None
    assert result["financial_baseline_date_verified"] is None
    assert result["financial_acceptance_performed"] is False


@pytest.mark.parametrize("cut", ["20261031", "2026-02-30", "PRIVATE"])
def test_invalid_cut_is_rejected_without_echo(cut, capsys):
    assert probe.main(["--cut", cut]) == 2
    assert json.loads(capsys.readouterr().out)["error"] == "invalid_cut"
