"""Independent-review regressions: dated, unique evidence across every reader."""
from __future__ import annotations

import datetime as dt

import pytest

import developaid_management_report as report
import developaid_monitor as monitor
import developaid_monitor_manager as manager
from test_monitor_management_gantt import _gpr_book

CUT = "2026-11-06"
PROJECT = "Датированный учебный график"
START, FINISH = dt.date(2026, 9, 1), dt.date(2026, 10, 31)


def book(*rows):
    return _gpr_book([(tid, name, progress, START, FINISH, status, "2.2.1.1")
                      for tid, name, progress, status in rows])


@pytest.fixture(autouse=True)
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path)
    import developaid_monitor_page  # noqa: F401


@pytest.mark.parametrize("source", ["future", "undated"])
@pytest.mark.parametrize("progress,status", [(.8, "В работе"), (None, "Завершено")])
def test_future_or_undated_baseline_is_not_historical_fact_or_completion(source, progress, status):
    monitor.store_schedule(PROJECT, book((1, "Фасад", progress, status)), None,
                           "2026-11-10" if source == "future" else "2026-10-01")
    if source == "undated":
        (monitor._project_dir(PROJECT) / "baseline" / "meta.json").unlink()
    view = monitor.build(PROJECT, CUT)
    state = manager._baseline_status(PROJECT, CUT)["1"]
    assert view["schedule"]["rows"][0]["gpr_progress"] is None
    assert state["progress"] is None and not state["closed"]
    assert state["progress_date"] is None and state["progress_reason"]
    block = report.physical(PROJECT, "week", CUT)
    assert block["state"] == "missing" and block.get("fact") is None


def test_zero_and_explicit_dated_completion_are_known_source_facts():
    monitor.store_schedule(PROJECT, book((1, "Фасад", 0., "В работе"),
                                        (2, "Каркас", None, "Завершено")), None, "2026-10-01")
    view = monitor.build(PROJECT, CUT)
    state = manager._baseline_status(PROJECT, CUT)
    by_id = {row["id"]: row for row in view["schedule"]["rows"]}
    assert state["1"]["progress"] == by_id["1"]["gpr_progress"] == 0.
    assert not state["1"]["closed"] and state["1"]["progress_date"] == "2026-10-01"
    assert state["2"]["progress"] == by_id["2"]["gpr_progress"] == 1.
    assert state["2"]["closed"] and by_id["2"]["forecast_finish"] == "2026-10-01"


def test_duplicate_weekly_id_keeps_previous_valid_point_and_its_real_date():
    monitor.store_schedule(PROJECT, book((1, "Фасад", .2, "В работе")), None, "2026-10-01")
    monitor.store_schedule_fact(PROJECT, book((1, "Фасад", .5, "В работе")), "2026-10-21")
    monitor.store_schedule_fact(PROJECT, book((1, "Фасад", .4, "В работе"),
                                            (1, "Другая работа", .9, "В работе")), "2026-11-04")
    view = monitor.build(PROJECT, CUT)
    state = manager._baseline_status(PROJECT, CUT)["1"]
    assert state["progress"] == view["schedule"]["rows"][0]["gpr_progress"] == .5
    assert state["progress_date"] == "2026-10-21" and state["progress_origin"] == "weekly_gpr"
    block = report.physical(PROJECT, "week", CUT)
    assert block["fact"] == .5 and block["snapshot"] == block["fact_snapshot"] == "2026-10-21"
    assert not block["fresh"] and block["source"]["day"] == "2026-10-21"
    assert [point["day"] for point in block["series"]["fact"]] == ["2026-10-21"]
    assert not report.progress_charts_shown(block)


def test_future_baseline_date_does_not_date_an_older_valid_weekly_fact():
    monitor.store_schedule(PROJECT, book((1, "Фасад", .8, "В работе")), None, "2026-11-10")
    monitor.store_schedule_fact(PROJECT, book((1, "Фасад", .5, "В работе")), "2026-10-21")
    block = report.physical(PROJECT, "week", CUT)
    assert block["fact"] == .5 and block["snapshot"] == "2026-10-21"
    assert block["source"]["day"] == "2026-10-21" and block["source"]["baseline"] is None
    assert "10.11.2026" not in block["source"]["label"]


def test_blank_progress_is_not_zero_in_a_valid_dated_source():
    monitor.store_schedule(PROJECT, book((1, "Фасад", None, "В работе"),
                                        (2, "Каркас", 0., "В работе")), None, "2026-10-01")
    status = manager._baseline_status(PROJECT, CUT)
    assert status["1"]["progress"] is None and status["2"]["progress"] == 0.
    block = report.physical(PROJECT, "week", CUT)
    assert block["works"] == 1 and block["works_unknown"] == 1 and block["fact"] == 0.


def test_duplicate_baseline_ids_cannot_borrow_either_work_as_one_fact():
    monitor.store_schedule(PROJECT, book((1, "Фасад", .4, "В работе"),
                                        (1, "Другая работа", .9, "В работе")), None, "2026-10-01")
    monitor.store_schedule_fact(PROJECT, book((1, "Одна из работ", 1., "Завершено")), "2026-10-21")
    state = manager._baseline_status(PROJECT, CUT)["1"]
    assert state["progress"] is None and not state["closed"]
    assert "повторяется" in state["progress_reason"]
    assert all(row["gpr_progress"] is None for row in monitor.build(PROJECT, CUT)["schedule"]["rows"])
    assert report.physical(PROJECT, "week", CUT)["state"] == "missing"


def test_a_gpr_stall_report_uses_its_real_source_reason_without_inventing_acts():
    monitor.store_schedule(PROJECT, book((1, "Фасад", .2, "В работе")), None, "2026-10-01")
    monitor.store_schedule_fact(PROJECT, book((1, "Фасад", .2, "В работе")), "2026-10-21")
    view = monitor.build(PROJECT, CUT)
    schedule = report.schedule(view["dashboard"])
    text = report._stalled_words(schedule)
    assert schedule["qualification"]["basis"] == "gpr"
    assert "ГПР" in text and "процент" in text and "Фасад" in text
    assert "актов" not in text and "годы" not in text
