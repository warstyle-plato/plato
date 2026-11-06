#!/usr/bin/env python3
"""Offline preflight of existing Monitor files; never financial acceptance.

Only fixed-schema diagnostics leave this process. No HTTP, keys, source copies,
payment identifiers, money, paths or exception messages are written to output.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import io
import json
import math
from pathlib import Path
import sys
import warnings

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import developaid_actuals as actuals
import developaid_monitor_dashboard as dashboard
import developaid_funding_schedule as schedules
import developaid_monthly_budget as budgets

MAX_FILE_BYTES = 32 * 1024 * 1024
# Exact labels are discovery hints only. They do not establish shared identity
# semantics, completeness or uniqueness. Other labels may exist in the source.
ID_HEADERS = frozenset(("id платежа", "идентификатор платежа", "payment id"))


def _stream(data: bytes) -> io.BytesIO:
    source = io.BytesIO(data)
    source.name = "source.xlsx"
    return source


def _day(value):
    if not isinstance(value, str):
        return None
    try:
        day = dt.date.fromisoformat(value).isoformat()
        return day if day == value else None
    except ValueError:
        return None


def _read(path: Path) -> bytes:
    with path.open("rb") as source:
        data = source.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("file_limit")
    return data


def _metadata(path: Path | None, cut: str) -> dict:
    result = {"state": "not_supplied", "data_date": None, "after_cut": None}
    if path is None:
        return result
    try:
        meta = json.loads(_read(path))
        day = _day(meta.get("taken_at")) if isinstance(meta, dict) else None
        return {"state": "read", "data_date": day,
                "after_cut": day > cut if day else None}
    except Exception:
        return {**result, "state": "unreadable"}


def _header_hints(data: bytes) -> int:
    from openpyxl import load_workbook

    book = load_workbook(_stream(data), read_only=True, data_only=True)
    try:
        return sum(str(cell or "").strip().lower() in ID_HEADERS
                   for sheet in book for row in sheet.iter_rows(max_row=20, values_only=True)
                   for cell in row)
    finally:
        book.close()


def _identity(values, expected):
    if any(type(value) not in (int, float) or not math.isfinite(value)
           for value in [*values, expected]):
        return None
    return abs(math.fsum(values) - expected) <= 1.0


def _finance(data: bytes, cut: str) -> dict:
    # A stream bypasses both the pickle cache and its on-disk writes. Use the
    # product's reader and allocation rules, not another financial calculation.
    model = dashboard._read_finance_baseline(_stream(data))
    if not model.get("known"):
        return {"parsed": False}
    admin = dashboard._admin_expenses(model.get("budget_composition"), model.get("chapter_flow"))
    result = {"parsed": True, "admin_present": admin is not None}
    if admin is None:
        return result
    items = admin["items"]
    fields = ("total", "fact", "plan")
    result.update({
        "admin_leaf_count": len(items),
        "admin_leaf_detail_present": bool(items),
        "admin_missing_money_cells": sum(not item.get("known_fields", {}).get(field, True)
                                         for item in items for field in fields),
        "admin_mixed_leaf_count": sum(len(item["chapter_candidates"]) > 1 for item in items),
        "admin_unmapped_leaf_count": sum(not item["chapter_candidates"] for item in items),
        "admin_allocation_known": admin["allocation_known"],
        "admin_tax_code_in_parsed_items": any(dashboard._fm_is_tax(item["code"]) for item in items),
        "admin_leaf_fact_plan_identity": _identity([admin["paid"], admin["to_pay"]], admin["total"]),
    })
    for target, label in (("2", "chapter2"), ("3", "chapter3"), ("outside", "outside")):
        result["admin_" + label + "_leaf_count"] = sum(
            len(item["chapter_candidates"]) == 1 and
            (item["chapter_candidates"][0] == target if target != "outside"
             else item["chapter_candidates"][0] not in dashboard.CHAPTERS)
            for item in items)
    for field, source in (("total", "total"), ("paid", "paid"), ("to_pay", "to_pay")):
        result["admin_allocation_" + field + "_identity"] = _identity(
            [row[field] for row in admin["by_chapter"].values()] + [admin["unallocated"][field]],
            admin[source])
    return result


def _rss(data: bytes, cut: str) -> dict:
    rows = actuals.read_payments(_stream(data))["rows"]
    day = dt.date.fromisoformat(cut)
    return {"parsed": True, "payment_row_count": len(rows),
            "payment_undated_count": sum(row["date"] is None for row in rows),
            "payment_after_cut_count": sum(row["date"] is not None and row["date"] > day for row in rows)}


def _schedule(data: bytes, cut: str) -> dict:
    parsed = schedules.read_schedule(data)
    return {"parsed": True, "row_count": len(parsed["rows"]),
            "uncoded_row_count": len(parsed["uncoded"])}


def _budget(data: bytes, cut: str) -> dict:
    parsed = budgets.read_budget(data)
    return {"parsed": True, "supplies_cut_month": any(
        month[:7] == cut[:7] for month in parsed["months"])}


def inspect_source(path: Path | None, kind: str, cut: str, meta: Path | None = None) -> dict:
    # openpyxl warnings can include workbook-defined names. Readers may also
    # emit diagnostics of their own; only the explicit return schema is public.
    with warnings.catch_warnings(), contextlib.redirect_stdout(io.StringIO()), \
            contextlib.redirect_stderr(io.StringIO()):
        warnings.simplefilter("ignore")
        return _inspect_source(path, kind, cut, meta)


def _inspect_source(path: Path | None, kind: str, cut: str, meta: Path | None = None) -> dict:
    result = {"state": "not_supplied", "metadata": _metadata(meta, cut)}
    if path is None:
        return result
    try:
        data = _read(path)
    except FileNotFoundError:
        return {**result, "state": "unreadable", "error": "file_not_found"}
    except PermissionError:
        return {**result, "state": "unreadable", "error": "permission_denied"}
    except ValueError:
        return {**result, "state": "unreadable", "error": "file_limit"}
    except Exception:
        return {**result, "state": "unreadable", "error": "file_read_failed"}
    try:
        result.update(state="read", sha256=hashlib.sha256(data).hexdigest(),
                      payment_id_header_candidates=_header_hints(data))
    except Exception:
        return {**result, "state": "unreadable", "error": "workbook_unreadable"}
    try:
        result.update({"finance": _finance, "rss": _rss,
                       "schedule": _schedule, "bdds": _budget}[kind](data, cut))
    except Exception:
        # Reader errors may contain private sheet names, values or filenames.
        result["parsed"] = False
    if not result.get("parsed"):
        result["error"] = "profile_parser_rejected"
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cut", required=True, help="YYYY-MM-DD")
    for kind in ("finance", "rss", "schedule", "bdds"):
        parser.add_argument("--" + kind, type=Path, action="append" if kind == "bdds" else "store")
        parser.add_argument("--" + kind + "-meta", type=Path,
                            action="append" if kind == "bdds" else "store")
    args = parser.parse_args(argv)
    if _day(args.cut) is None:
        print('{"error":"invalid_cut","primary_source_gate":"BLOCKED"}')
        return 2
    bdds = args.bdds or []
    metas = args.bdds_meta or []
    if metas and len(metas) != len(bdds):
        print('{"error":"metadata_count","primary_source_gate":"BLOCKED"}')
        return 2
    sources = {kind: inspect_source(getattr(args, kind), kind, args.cut,
                                   getattr(args, kind + "_meta"))
               for kind in ("finance", "rss", "schedule")}
    sources["bdds"] = [inspect_source(path, "bdds", args.cut, metas[i] if metas else None)
                       for i, path in enumerate(bdds)]
    print(json.dumps({"schema": 1, "cut": args.cut, "sources": sources,
                      "primary_source_gate": "BLOCKED",
                      "bank_coverage_verified": None, "schedule_admin_coverage_verified": None,
                      "payment_identity_verified": None, "payment_deduplication_verified": None,
                      "financial_baseline_date_verified": None,
                      "financial_acceptance_performed": False}, sort_keys=True))
    # A successful inventory must never become a green financial acceptance job.
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
