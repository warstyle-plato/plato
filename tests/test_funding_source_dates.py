"""Dates identify the financial inputs; they do not change the money calculation."""
from __future__ import annotations

import datetime
import json
from pathlib import Path

import pytest

import developaid_monitor as monitor
import developaid_monitor_dashboard as dashboard
import developaid_management_report as report
import developaid_funding_schedule as schedules
from test_management_report_funding import PROJECT, _project
from test_the_approved_budget_says_what_it_is_made_of import _finmodel


def source_case(tmp_path: Path, monkeypatch, missing_dates: bool = False):
    """Synthetic real funding calculation + report, also usable by visual review."""
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path / "monitor")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    _project()
    monitor.replace_finance_baseline(PROJECT, _finmodel(), "2026-10-01", file_name="model.xlsx")
    meta_path = monitor._project_dir(PROJECT) / "baseline" / monitor.FINANCE_META
    meta = json.loads(meta_path.read_text())
    meta["uploaded_at"] = "2026-10-19T10:00:00+00:00"
    if missing_dates:
        meta.pop("taken_at")
    meta_path.write_text(json.dumps(meta))
    root = monitor._project_dir(PROJECT)
    schedule_path = root / ("legacy_plan.xlsx" if missing_dates else "funding_schedule/2026-09-23.xlsx")
    schedule_path.parent.mkdir(exist_ok=True)
    schedule_path.write_bytes(b"synthetic read stub")
    monkeypatch.setattr(schedules, "sources", lambda *_: {"versions": {
        "2026-09-23": {"path": schedule_path, "file": schedule_path.name,
                       "where": "синтетический график"}}})
    monkeypatch.setattr(schedules, "read_schedule", lambda _: {"rows": [
        {"code": "2", "work": "Строительство", "parent": "", "paid": 0.0, "notes": [],
         "plan": {"2026-09": 50_000.0, "2026-10": 80_000.0, "2026-11": 100_000.0}}],
        "months": ["2026-09", "2026-10", "2026-11"], "unit": "руб.", "uncoded": [],
        "total": {"plan": {"2026-09": 50_000.0, "2026-10": 80_000.0, "2026-11": 100_000.0},
                  "paid": 0.0, "contract": 230_000.0}})
    cut = datetime.date(2026, 10, 20)
    rss = monitor._latest(PROJECT, "estimate", ".xlsx", cut.isoformat())
    limit = dashboard._funding_risk(PROJECT, rss, cut, {})
    assert limit["known"] and limit["own_money"]
    view = {"project": PROJECT, "date": cut.isoformat(), "dashboard": {
        "funding": limit, "construction": {"approved": limit["approved"]}}}
    monkeypatch.setattr(report, "_monitor_view", lambda *_: view)
    built = report.build(PROJECT, "week", cut.isoformat())
    assert built["funding_schedule"]["state"] == "ok", built["funding_schedule"]
    return built, view


def nofinance_case(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path / "monitor")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    _project()
    cut = datetime.date(2026, 10, 20)
    rss = monitor._latest(PROJECT, "estimate", ".xlsx", cut.isoformat())
    limit = dashboard._funding_risk(PROJECT, rss, cut, {})
    view = {"project": PROJECT, "date": cut.isoformat(), "dashboard": {"funding": limit}}
    monkeypatch.setattr(report, "_monitor_view", lambda *_: view)
    return report.build(PROJECT, "week", cut.isoformat()), view


def test_distinct_source_dates_reach_all_views_and_visible_cards(tmp_path, monkeypatch):
    built, view = source_case(tmp_path, monkeypatch)
    limit = view["dashboard"]["funding"]
    dates = limit["source_dates"]
    assert dates["report_date"] == "2026-10-20"
    assert dates["budget"]["data_date"] == "2026-10-01"
    assert dates["budget"]["uploaded_at"].startswith("2026-10-19")
    assert dates["rss"]["data_date"] == "2026-10-18"
    assert dates["schedule"]["data_date"] == "2026-09-23"
    expected = dashboard.funding_source_notes(limit)
    html, text = report.render_html(built), report.render_text(built)
    for line in expected.values():
        assert line in html and line in text
        assert line in limit["limit_reconciliation_lines"]
    tiles = {item["label"]: item for item in report.tiles(built)}
    for title, key in (("Утверждённый бюджет", "budget"), ("Лимит банка", "limit"),
                       ("Оплачено с начала проекта", "paid"), ("Выбрано у банка", "paid"),
                       ("Доступный остаток лимита банка", "left"), ("Расчётная дополнительная потребность", "need")):
        assert expected[key] in tiles[title]["note"]  # printed, not only in a hidden tooltip
    assert "14.10.2026–20.10.2026" in tiles["Выбрано у банка"]["note"]
    assert "с начала месяца (01.10.2026–20.10.2026)" in tiles["Выбрано у банка"]["note"]
    bridge = dashboard.own_budget_reconciliation_lines(limit["own_money"], report._rub)
    assert bridge and all(line in html and line in text for line in bridge)


def test_missing_data_dates_are_not_replaced_by_upload_or_selection_day(tmp_path, monkeypatch):
    built, view = source_case(tmp_path, monkeypatch, missing_dates=True)
    limit = view["dashboard"]["funding"]
    assert limit["source_dates"]["budget"]["data_date"] is None
    assert limit["source_dates"]["schedule"]["data_date"] is None
    notes = dashboard.funding_source_notes(limit)
    assert "дата данных не указана" in notes["budget"]
    assert "Загружена 19.10.2026" in notes["budget"]
    assert "дата данных не указана" in notes["schedule"]
    assert "23.09.2026" not in notes["schedule"]  # selected version is not a known data date
    assert "График финансирования от 23.09.2026" not in report.render_text(built)
    assert "графика от 23.09.2026" not in report._schedule_html(built["funding_schedule"])
    assert notes['schedule'] in " ".join(report._own_money_lines(limit))
    assert notes["budget"] in report.render_html(built) and notes["budget"] in report.render_text(built)


def test_arbitrary_filename_is_not_data_date(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path / "monitor")
    arbitrary = tmp_path / "2026-10-18.xlsx"
    arbitrary.write_bytes(b"unused")
    assert dashboard._stored_funding_source("demo", arbitrary)["data_date"] is None
    canonical = monitor._project_dir("demo") / "estimate" / arbitrary.name
    assert dashboard._stored_funding_source("demo", canonical)["data_date"] == "2026-10-18"


def test_rss_date_is_visible_without_a_financial_book(tmp_path, monkeypatch):
    built, view = nofinance_case(tmp_path, monkeypatch)
    limit = view["dashboard"]["funding"]
    assert not limit["known"]
    assert limit["source_dates"]["rss"]["data_date"] == "2026-10-18"
    tiles = {item["label"]: item for item in report.tiles(built)}
    assert "18.10.2026" in tiles["Выбрано у банка"]["note"]
    assert "20.10.2026" in tiles["Выбрано у банка"]["note"]
    assert tiles["Утверждённый бюджет"]["tone"] == "missing"
    assert "версия от" not in tiles["Утверждённый бюджет"]["note"]
    assert any("18.10.2026" in line for line in limit["limit_reconciliation_lines"])


def test_bank_financial_book_has_a_neutral_source_name():
    notes = dashboard.funding_source_notes({"need_basis": "budget", "source_dates": {
        "report_date": "2026-10-20", "budget": {"data_date": "2026-10-01"},
        "rss": {"data_date": "2026-10-18"}}})
    assert notes["budget"].startswith("Финансовая книга: версия от 01.10.2026")
    assert "финмодель" not in notes["need"]


def test_report_preserves_known_rss_date_when_monitor_funding_fails(tmp_path, monkeypatch):
    built, _ = nofinance_case(tmp_path, monkeypatch)

    def broken_funding(*_):
        raise ValueError("synthetic finance parser failure")

    monkeypatch.setattr(report, "_monitor_funding", broken_funding)
    built["funding"] = report.funding(PROJECT, "week", "2026-10-20")
    limit = built["funding"]["limit"]
    assert not limit["known"]
    assert limit["reason"] == "ValueError: synthetic finance parser failure"
    assert limit["source_dates"]["rss"]["data_date"] == "2026-10-18"
    tiles = {item["label"]: item for item in report.tiles(built)}
    assert "18.10.2026" in tiles["Выбрано у банка"]["note"]
    assert "20.10.2026" in tiles["Выбрано у банка"]["note"]


def test_later_budget_version_is_explicit_without_rewriting_money(tmp_path, monkeypatch):
    built, view = source_case(tmp_path, monkeypatch)
    limit = view["dashboard"]["funding"]
    before = {k: limit["own_money"][k] for k in ("budget", "paid", "left", "need")}
    meta_path = monitor._project_dir(PROJECT) / "baseline" / monitor.FINANCE_META
    meta = json.loads(meta_path.read_text())
    meta["taken_at"] = "2026-10-25"
    meta_path.write_text(json.dumps(meta))
    rss = monitor._latest(PROJECT, "estimate", ".xlsx", "2026-10-20")
    updated = dashboard._funding_risk(PROJECT, rss, datetime.date(2026, 10, 20), {})
    view["dashboard"]["funding"] = updated
    built = report.build(PROJECT, "week", "2026-10-20")
    note = dashboard.funding_source_notes(updated)["budget"]
    assert "версия от 25.10.2026" in note and "позже даты расчётного среза" in note
    assert note in report.render_html(built)
    assert before == {k: updated["own_money"][k] for k in before}
