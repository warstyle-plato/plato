"""An unreadable FM cannot hide independent RSS readings or their exact gaps."""
import ast
import copy
import datetime as dt
import math
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest


@pytest.fixture
def cover(monkeypatch):
    from market_search import contracting

    # Execute the exact pure presentation functions without importing the app,
    # starting background services or loading any saved project sources.
    source = Path(__file__).resolve().parents[1] / "developaid_management_report.py"
    names = {"tiles", "_rub", "_payment_total_gap_note", "_payment_observation_note",
             "_report_uses_owner", "_escrow_total_tile", "_date", "_day", "_months_label"}
    nodes = [node for node in ast.parse(source.read_text()).body
             if (isinstance(node, ast.FunctionDef) and node.name in names)
             or (isinstance(node, ast.Assign) and any(
                 isinstance(target, ast.Name) and target.id == "_MONTHS"
                 for target in node.targets))]
    scope = {
        "Any": Any, "datetime": dt, "math": math, "contracting": contracting,
        "PERIODS": {"week": "week"},
        "_report_gpr_summary": lambda _: None, "_quarter_elapsed": lambda _: 0.5,
        "admin_cash": SimpleNamespace(funding_base_for_limit=lambda *_: None),
        "_funding_cash_summary": lambda *_: {
            "amount": None, "scope": "unconfirmed_total",
            "note": "Общая потребность пока не определена."},
        "period_bounds": lambda *_: {"start": dt.date(2026, 3, 7),
                                     "end": dt.date(2026, 3, 13)},
        "_approved_need": lambda _: {"approved": 1000}, "_budget_hint": lambda _: [],
    }
    dashboard = ModuleType("developaid_monitor_dashboard")
    dashboard.funding_source_tile_notes = lambda _: {
        key: "" for key in ("budget", "limit", "paid", "left", "need")}
    monkeypatch.setitem(sys.modules, dashboard.__name__, dashboard)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), "exec"), scope)
    return scope


def report_case(paid, available, issues=(), draws=None):
    return {"kind": "week", "end": "2026-03-13", "funding": {
        "state": "ok", "draws": draws, "limit": {
            "known": False, "reason": "Единицы ФМ не указаны.",
            "bank_observations": {"bank_limit": 1000, "paid_actual": paid,
                "available_bank_limit": available, "incomplete_rows": list(issues),
                "note": "По сохранённому РСС, главы 1–3."}}}}


@pytest.mark.parametrize("paid,available", [(200, 800), (0, 1000)])
def test_known_rss_payments_survive_an_unreadable_model(cover, paid, available):
    report = report_case(paid, available)
    before = copy.deepcopy(report)
    tiles = {tile["label"]: tile for tile in cover["tiles"](report)}
    assert tiles["Оплачено с начала проекта"]["value"] == cover["_rub"](paid)
    assert tiles["Осталось по смете после всех оплат"]["value"] == cover["_rub"](available)
    assert tiles["Утверждённый бюджет"]["value"] == "нет данных"
    need = tiles["Потребность в допфинансировании"]
    assert need["value"] == "нет данных" and need["tone"] == "missing"
    assert "Единицы ФМ не указаны" in need["note"]
    assert report == before


@pytest.mark.parametrize("paid,available,escrow_paid,owed", [
    (None, None, 250, 750), (0, 1000, 0, 0)])
def test_all_time_escrow_coexists_with_unknown_or_zero_rss_payments(
        cover, paid, available, escrow_paid, owed):
    report = report_case(paid, available)
    report["funding"]["escrow_track"] = {
        "state": "ok", "paid_now": escrow_paid, "owed": owed, "data_month": "2026-03"}
    report["sales"] = {"uploaded": "2026-03-12T14:00:00+00:00"}
    before = copy.deepcopy(report)
    tiles = {tile["label"]: tile for tile in cover["tiles"](report)}
    escrow = tiles["Оплачено на эскроу всего"]
    assert escrow["value"] == cover["_rub"](escrow_paid) and escrow["tone"] == ""
    assert f"Ещё ожидается {cover['_rub'](owed)}" in escrow["note"]
    assert "март 2026" in escrow["note"]
    assert "Источник загружен 12.03.2026" in escrow["note"]
    for label, amount in (("Оплачено с начала проекта", paid),
                          ("Осталось по смете после всех оплат", available)):
        assert tiles[label]["value"] == ("нет данных" if amount is None else cover["_rub"](amount))
    assert tiles["Утверждённый бюджет"]["value"] == "нет данных"
    need = tiles["Потребность в допфинансировании"]
    assert need["value"] == "нет данных" and need["tone"] == "missing"
    assert "Единицы ФМ не указаны" in need["note"]
    assert report == before


def test_incomplete_payment_readings_keep_their_reason_and_separate_loan_part(cover):
    issues = [{"source_row": 10, "fields": ["date", "estimate_code"]},
              {"source_row": 11, "fields": ["amount"]}]
    draws = {"state": "incomplete", "total": None, "period": None, "month": None,
             "known_part": {"total": 123}}
    report = report_case(None, None, issues, draws)
    before = copy.deepcopy(report)
    tiles = {tile["label"]: tile for tile in cover["tiles"](report)}
    for label in ("Оплачено с начала проекта", "Осталось по смете после всех оплат"):
        tile = tiles[label]
        assert tile["value"] == "нет данных" and tile["tone"] == "missing"
        assert "строк с непрочитанными реквизитами — 2" in tile["note"]
        assert "дата, сумма, привязка к главе РСС" in tile["note"]
        assert "123" not in tile["note"]
    assert tiles["Выбрано у банка"]["value"] == "учтено 123 ₽"
    assert "не полный итог" in tiles["Выбрано у банка"]["note"]
    assert tiles["Потребность в допфинансировании"]["value"] == "нет данных"
    assert report == before


def test_canonical_payment_gaps_are_visible_and_counted_once_per_source_row(cover):
    issue = {"source_row": 10, "fields": ["estimate_code"]}
    canonical = {"budget": 1000, "bank_limit_total": 800,
        "observation_scope": "raw_saved_sources", "source_completeness": {
            "payments": {chapter: [copy.deepcopy(issue)] for chapter in ("1", "2", "3")}},
        "display_rows": [
            {"key": "paid_at_cut", "label": "Оплачено с начала проекта", "value": None, "note": ""},
            {"key": "available_bank_limit", "label": "Доступный остаток лимита банка", "value": None, "note": ""},
            {"key": "calculated_additional", "label": "Расчётная дополнительная потребность", "value": None, "note": ""}]}
    report = {"kind": "week", "end": "2026-03-13", "funding": {"state": "ok", "limit": {
        "known": True, "reconciliation": canonical, "own_money": {"reconciliation": canonical}}}}
    before = copy.deepcopy(report)
    tiles = {tile["label"]: tile for tile in cover["tiles"](report)}
    for label in ("Оплачено с начала проекта", "Доступный остаток лимита банка"):
        assert tiles[label]["value"] == "нет данных" and tiles[label]["tone"] == "missing"
        assert "строк с непрочитанными реквизитами — 1" in tiles[label]["note"]
        assert "привязка к главе РСС" in tiles[label]["note"]
    assert tiles["Потребность в допфинансировании"]["value"] == "нет данных"
    assert report == before
