"""Fixed B/P/L source observations: primary cells, scope and closed native API."""
from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import time

import openpyxl
import pytest
from fastapi.testclient import TestClient

import developaid_budget_funding_source as proof
import developaid_cached_source_audit as audit
import developaid_monitor as monitor
import main as wrapper

PROJECT = "Synthetic BPL source"
CUT = "2026-11-13"
KEY = "synthetic-bpl-admin-key"
ROUTE = "/monitor/audit/budget-funding"
RUNTIME = {"version": "0.29.test", "commit": "a" * 40}


def book_bytes(book):
    out = io.BytesIO()
    book.save(out)
    book.close()
    return out.getvalue()


def fm_bytes(edit=None):
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "cf_1_new"
    sheet["B2"] = "Все суммы в тыс. руб."
    for col, name in ((9, "ИТОГО"), (10, "ФАКТ"), (11, "ПЛАН")):
        sheet.cell(6, col, name)
    rows = [("2", 9999, 9999, 9999), ("2.1", 100, 10, 90),
            ("2.2", 500, 150, 350), ("2.2.1", 200, 50, 150),
            ("2.2.2", 300, 100, 200), ("2.4", 1039, 1019, 20),
            ("2.4.1", 40, 20, 20), ("2.4.5", 999, 999, 0),
            ("2.4.5.1", 999, 999, 0), ("3.1.4.1.3", 5, 1, 4)]
    for index, (code, *values) in enumerate(rows, 10):
        sheet.cell(index, 3, code)
        sheet.cell(index, 4, "PRIVATE-FM-NAME-CANARY")
        for col, value in enumerate(values, 9):
            sheet.cell(index, col, value)
    if edit:
        edit(sheet)
    return book_bytes(book)


def rss_bytes(edit=None):
    book = openpyxl.Workbook()
    estimate = book.active
    estimate.title = proof.ESTIMATE
    estimate["B2"] = "Все суммы в руб."
    estimate["E8"], estimate["G8"] = "Смета / лимит банка", "Оплачено"
    for row, (code, limit) in enumerate([
            ("1", 1000), ("1.1", 1000), ("2", 500), ("2.1", 500),
            ("3", 0), ("3.1", 0), ("4", 30), ("4.1", 30)], 10):
        estimate.cell(row, 1, code)
        estimate.cell(row, 2, "PRIVATE-RSS-NAME-CANARY")
        estimate.cell(row, 5, limit)
        estimate.cell(row, 6, 999999)  # A neighbouring column is not the limit.
        estimate.cell(row, 7, 777777)  # Reported paid is not a payment registry.
    payments = book.create_sheet(proof.PAYMENTS)
    payments["B2"] = "Все суммы в руб."
    payments["G8"], payments["I8"], payments["J8"] = "Код РСС", "Дата оплаты", "Сумма оплаты"
    rows = [("1.1", "2026-11-12", 100), ("1.1", "2026-11-13", -20),
            ("2.1", "2026-11-13", 200), ("3.1", "2026-11-14", 999),
            ("4.1", "2026-11-12", 30), (None, "2026-11-14", 123)]
    for row, (code, day, amount) in enumerate(rows, 10):
        payments.cell(row, 2, "PRIVATE-PAYEE-CANARY")
        payments.cell(row, 7, code)
        payments.cell(row, 9, dt.date.fromisoformat(day))
        payments.cell(row, 10, amount)
    if edit:
        edit(estimate, payments)
    return book_bytes(book)


@pytest.fixture
def source(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path / "monitor")
    monkeypatch.setenv("DEVELOPAID_ADMIN_KEY", KEY)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    fm = fm_bytes()
    monitor.replace_finance_baseline(PROJECT, fm, "2026-11-01", "PRIVATE-FILENAME-CANARY")
    project = monitor._project_dir(PROJECT)
    estimate = project / "estimate"
    estimate.mkdir()
    rss = rss_bytes()
    path = estimate / "2026-11-10.xlsx"
    path.write_bytes(rss)
    path.with_suffix(".json").write_text(json.dumps({
        "taken_at": "2026-11-10", "bytes": len(rss), "filename": "PRIVATE-FILENAME-CANARY",
        "token": "PRIVATE-META-CANARY", "source_sha256": hashlib.sha256(rss).hexdigest()}))
    return project, fm, rss


def capture():
    return proof.capture(PROJECT, CUT, runtime=RUNTIME)


def replace_rss(source, raw):
    path = source[0] / "estimate" / "2026-11-10.xlsx"
    path.write_bytes(raw)
    meta = json.loads(path.with_suffix(".json").read_text())
    meta.update(bytes=len(raw), source_sha256=hashlib.sha256(raw).hexdigest())
    path.with_suffix(".json").write_text(json.dumps(meta))


def chapter(result, code):
    return next(row for row in result["bank"]["chapters"] if row["chapter"] == code)


def test_fixed_primary_cells_are_not_neighbour_columns_or_double_counted_parents(source):
    result = capture()
    assert result["finance"]["observations"]["total"]["rubles"] == 645000
    assert result["finance"]["observations"]["fact"]["rubles"] == 181000
    assert result["finance"]["observations"]["plan"]["rubles"] == 464000
    assert result["finance"]["leaf_count"] == 5
    assert [row["code"] for row in result["finance"]["sections"]] == ["2.1", "2.2", "2.4", "3.1.4.1.3"]
    assert chapter(result, "1")["observed_limit"]["rubles"] == 1000
    assert chapter(result, "2")["observed_limit"]["rubles"] == 500
    assert chapter(result, "3")["observed_limit"]["rubles"] == 0
    assert chapter(result, "1")["observed_payments_at_or_before_cut"]["rubles"] == 80
    assert chapter(result, "2")["observed_payments_at_or_before_cut"]["rubles"] == 200
    assert chapter(result, "3")["observed_payments_at_or_before_cut"]["rubles"] == 0
    assert result["bank"]["observed_payments_at_or_before_cut"]["rubles"] == 280
    assert result["bank"]["row_counts"] == {"nonempty": 6, "future": 2, "outside": 1,
                                             "selected": 3, "incomplete": 0}
    assert result["finance_source"]["sha256"] == hashlib.sha256(source[1]).hexdigest()
    assert result["rss_source"]["sha256"] == hashlib.sha256(source[2]).hexdigest()
    assert result["finance_source"]["namespace_sha256"] == result["rss_source"]["namespace_sha256"]
    assert result["bank"]["payments_complete_through_cut"] is None
    assert not result["financial_acceptance"] and not result["full_BPL_at_cut_confirmed"]
    assert result["finance"]["amounts_at_cut"] is None
    assert not result["source_files_written"] and not result["formulas_evaluated"]
    text = json.dumps(result, ensure_ascii=False)
    for forbidden in ("PRIVATE-FM-NAME-CANARY", "PRIVATE-RSS-NAME-CANARY", "PRIVATE-PAYEE-CANARY",
                      "PRIVATE-META-CANARY", "PRIVATE-FILENAME-CANARY", "content_base64"):
        assert forbidden not in text


@pytest.mark.parametrize("date,state", [(None, "source_date_unknown"), ("2026-11-14", "source_after_cut")])
def test_undated_and_future_fm_observations_never_claim_money_at_the_cut(source, date, state):
    path = source[0] / "baseline" / monitor.FINANCE_META
    meta = json.loads(path.read_text())
    meta["taken_at"] = date
    path.write_text(json.dumps(meta))
    result = capture()
    assert result["finance"]["source_temporal_state"] == state
    assert result["finance"]["observations"]["total"]["rubles"] == 645000
    assert result["finance"]["amounts_at_cut"] is None
    assert not result["finance"]["historical_financial_acceptance"]
    assert result["finance_source"]["version_date"] == date


@pytest.mark.parametrize("value", [None, False, "#REF!", "=1+2", "PRIVATE-CELL-CANARY", "NaN", "1e309"])
def test_unknown_budget_cells_poison_the_total_without_exporting_text(source, value):
    raw = fm_bytes(lambda sheet: setattr(sheet["I11"], "value", value))
    monitor.replace_finance_baseline(PROJECT, raw, "2026-11-01")
    got = capture()["finance"]
    assert got["observations"]["total"]["state"] == "unknown"
    assert got["observations"]["total"]["rubles"] is None
    assert got["observations"]["fact"]["rubles"] == 181000
    assert "PRIVATE-CELL-CANARY" not in json.dumps(got)


def test_narrow_nbsp_decimal_strings_preserve_exact_observed_sums(source):
    raw = fm_bytes(lambda sheet: setattr(sheet["I11"], "value", "1\u202f234,56789"))
    monitor.replace_finance_baseline(PROJECT, raw, "2026-11-01")
    got = capture()["finance"]["observations"]["total"]
    assert got["raw_cached_sum_decimal"] == "1779.56789"
    assert got["rubles_decimal"] == "1779567.89000"


@pytest.mark.parametrize("value", ["1e-350", "1e-9999999999", "1e9999999999", 1e308])
def test_decimal_underflow_or_scaled_float_overflow_is_not_reported_as_known_zero(value):
    got = proof._observation([value], {"state": "observed", "recognized_unit": "млн руб."})
    assert got["state"] == "unknown" and got["rubles"] is None
    assert got["reason"] == "numeric_range_limit"


@pytest.mark.parametrize("header,unit", [("млн руб.", 1000000), ("руб.", 1), ("руб. за м²", None),
                                          ("PRIVATE-UNIT-CANARY", None), ("тыс. руб. и млн руб.", None)])
def test_only_observed_unambiguous_global_currency_units_scale_money(source, header, unit):
    raw = fm_bytes(lambda sheet: setattr(sheet["B2"], "value", header))
    monitor.replace_finance_baseline(PROJECT, raw, "2026-11-01")
    got = capture()["finance"]["observations"]["total"]
    assert got["raw_cached_sum"] == 645
    assert got["rubles"] == (645 * unit if unit is not None else None)


@pytest.mark.parametrize("field,value", [("G10", "2.999"), ("G10", None), ("G10", "PRIVATE-CODE-CANARY"),
                                        ("I10", None), ("J10", None), ("J10", "=100+1"), ("J10", False)])
def test_payment_scope_date_and_amount_unknowns_cannot_be_zero_or_guessed(source, field, value):
    replace_rss(source, rss_bytes(lambda _, payments: setattr(payments[field], "value", value)))
    result = capture()
    assert result["bank"]["observed_payments_at_or_before_cut"]["rubles"] is None
    assert chapter(result, "1")["observed_payments_at_or_before_cut"]["rubles"] is None
    assert result["bank"]["row_counts"]["incomplete"] == 1
    if field == "G10":
        assert all(row["observed_payments_at_or_before_cut"]["rubles"] is None
                   for row in result["bank"]["chapters"])
    assert "PRIVATE-CODE-CANARY" not in json.dumps(result)


def test_late_unknown_scope_is_not_lost_when_issue_output_reaches_its_cap(source, monkeypatch):
    monkeypatch.setattr(proof, "MAX_ISSUES", 1)
    def edit(_, payments):
        payments["I10"] = None
        payments["G12"] = "2.999"
    replace_rss(source, rss_bytes(edit))
    result = capture()
    assert result["bank"]["incomplete_rows_truncated"]
    assert result["bank"]["row_counts"]["incomplete"] == 2
    assert all(row["observed_payments_at_or_before_cut"]["rubles"] is None
               for row in result["bank"]["chapters"])


@pytest.mark.parametrize("kind", ["limit", "payment"])
def test_column_role_must_be_observed_in_its_fixed_header(source, kind):
    def edit(estimate, payments):
        (estimate if kind == "limit" else payments)["E8" if kind == "limit" else "J8"] = "PRIVATE-ROLE-CANARY"
    replace_rss(source, rss_bytes(edit))
    result = capture()
    for row in result["bank"]["chapters"]:
        assert row["observed_limit" if kind == "limit" else "observed_payments_at_or_before_cut"]["rubles"] is None
    assert "PRIVATE-ROLE-CANARY" not in json.dumps(result)


@pytest.mark.parametrize("column,label,role", [
    ("J8", "Дата оплаты", "payment"), ("I8", "Дата выгрузки файла", "payment"),
    ("G8", "Код плательщика", "payment"), ("E8", "Оплачено по смете", "limit"),
    ("E8", "Лимит банка не указан", "limit"), ("E8", "Смета отсутствует", "limit")])
def test_related_or_negative_words_do_not_establish_the_wrong_monetary_role(source, column, label, role):
    def edit(estimate, payments):
        (estimate if role == "limit" else payments)[column] = label
    replace_rss(source, rss_bytes(edit))
    result = capture()
    for row in result["bank"]["chapters"]:
        assert row["observed_limit" if role == "limit" else "observed_payments_at_or_before_cut"]["rubles"] is None


def test_a_second_contradictory_header_cannot_hide_behind_an_earlier_valid_one(source):
    replace_rss(source, rss_bytes(lambda _, payments: setattr(payments["J7"], "value", "Дата оплаты")))
    result = capture()
    assert result["bank"]["payment_role_evidence"]["amount"]["state"] == "ambiguous"
    assert result["bank"]["observed_payments_at_or_before_cut"]["rubles"] is None


def test_reordered_estimate_rows_use_explicit_codes_instead_of_neighbouring_chapters(source):
    def edit(estimate, _):
        estimate["A11"], estimate["A13"] = "2.1", "1.1"
    replace_rss(source, rss_bytes(edit))
    result = capture()
    assert chapter(result, "1")["observed_payments_at_or_before_cut"]["rubles"] == 80
    assert chapter(result, "2")["observed_payments_at_or_before_cut"]["rubles"] == 200


@pytest.mark.parametrize("kind", ["finance", "rss"])
def test_mismatched_source_metadata_hash_is_rejected(source, kind):
    path = source[0] / ("baseline/finance_meta.json" if kind == "finance" else "estimate/2026-11-10.json")
    meta = json.loads(path.read_text())
    meta["source_sha256"] = "0" * 64
    path.write_text(json.dumps(meta))
    with pytest.raises(proof.SourceProblem, match="source_pair_mismatch"):
        capture()


def test_source_files_are_not_written_and_only_fixed_reader_paths_are_opened(source, monkeypatch):
    before = {str(p.relative_to(source[0])): (p.read_bytes(), p.stat().st_mtime_ns)
              for p in source[0].rglob("*") if p.is_file()}
    reads = set()
    original = audit.Reader.read
    def read(reader, relative, **kwargs):
        reads.add(relative)
        return original(reader, relative, **kwargs)
    monkeypatch.setattr(audit.Reader, "read", read)
    capture()
    assert reads == {".aliases.json", "baseline/finance.xlsx", "baseline/finance_meta.json",
                     "estimate/2026-11-10.xlsx", "estimate/2026-11-10.json"}
    assert before == {str(p.relative_to(source[0])): (p.read_bytes(), p.stat().st_mtime_ns)
                      for p in source[0].rglob("*") if p.is_file()}


def test_changed_source_is_rejected_across_the_complete_capture(source, monkeypatch):
    original = proof._finance
    def change(raw):
        result = original(raw)
        monitor.replace_finance_baseline(PROJECT, fm_bytes(lambda sheet: setattr(sheet["I11"], "value", 1)), "2026-11-01")
        return result
    monkeypatch.setattr(proof, "_finance", change)
    with pytest.raises(proof.SourceProblem, match="source_changed"):
        capture()


def call(client, suffix="", **body):
    return client.post(ROUTE + suffix, json={"key": KEY, "session": "owner", **body})


def poll(client, ticket, **body):
    end = time.monotonic() + 5
    while time.monotonic() < end:
        response = call(client, "/result", ticket=ticket, **body)
        if response.status_code != 202:
            return response
        time.sleep(.01)
    pytest.fail("Synthetic BPL source observation did not finish")


def test_native_admin_gate_precedes_store_or_source_reads_and_job_is_private_owner_bound(source, monkeypatch):
    client = TestClient(wrapper.core.app)
    monkeypatch.setattr(monitor, "build", lambda *a, **k: pytest.fail("Financial widget must not run"))
    assert call(client, project=PROJECT, cut=CUT, key="wrong").status_code == 403
    root = monitor._SNAPSHOT_DIR / ".admin_budget_funding_source_jobs"
    assert not root.exists()
    admitted = call(client, project=PROJECT, cut=CUT, ticket="a" * 32)
    assert admitted.status_code == 202
    assert admitted.headers["cache-control"] == "private, no-store"
    assert poll(client, "a" * 32, session="other").status_code == 404
    result = poll(client, "a" * 32)
    assert result.status_code == 200 and result.json()["ok"]
    assert result.headers["cache-control"] == "private, no-store"
    assert call(client, project="other", cut=CUT, ticket="a" * 32).status_code == 409
    metadata = (root / ("a" * 32 + ".json")).read_text()
    assert KEY not in metadata and PROJECT not in metadata and "PRIVATE" not in metadata
    monkeypatch.setenv("DEVELOPAID_ADMIN_KEY", "rotated-bpl-key")
    assert poll(client, "a" * 32).status_code == 403
    assert poll(client, "a" * 32, key="rotated-bpl-key").status_code == 404


@pytest.mark.parametrize("extra", [{"sheet": "Other"}, {"path": "/etc/passwd"}, {"range": "A1:ZZ99"},
                                   {"url": "https://example.com"}, {"cells": ["J14"]},
                                   {"content_base64": "private"}, {"session": []}, {"ticket": "invalid"},
                                   {"cut": "2026-02-31"}, {"cut": "2999-01-01"}, {"project": "../escape"}])
def test_native_body_is_closed_to_source_selectors_and_invalid_fields(source, extra):
    response = call(TestClient(wrapper.core.app), **{"project": PROJECT, "cut": CUT, **extra})
    assert response.status_code == 400
    assert response.headers["cache-control"] == "private, no-store"
    assert not (monitor._SNAPSHOT_DIR / ".admin_budget_funding_source_jobs").exists()


def test_oversized_and_duplicate_json_are_refused_before_source_reads(source, monkeypatch):
    monkeypatch.setattr(proof, "capture", lambda *a, **k: pytest.fail("Source must not be read"))
    client = TestClient(wrapper.core.app)
    response = client.post(ROUTE, content=b" " * 12289, headers={"content-type": "application/json"})
    assert response.status_code == 413 and response.headers["cache-control"] == "private, no-store"
    duplicate = '{"key":"' + KEY + '","project":"one","project":"two","cut":"' + CUT + '"}'
    assert client.post(ROUTE, content=duplicate, headers={"content-type": "application/json"}).status_code == 400
