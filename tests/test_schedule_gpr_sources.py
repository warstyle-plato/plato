"""One GPR forecast across APIs, money-independent and with honest source facts."""
from __future__ import annotations

import datetime as dt

import pytest

import developaid_monitor as monitor
import developaid_monitor_manager as manager
import developaid_monitor_pace as pace
import developaid_management_report as report
from test_monitor_management_gantt import _gpr_book

CUT = dt.date(2026, 11, 6)
PROJECT = "Учебный график"


@pytest.fixture
def site(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path)
    start, finish = dt.date(2026, 9, 1), dt.date(2026, 10, 31)
    monitor.store_schedule(PROJECT, _gpr_book([
        (1, "Каркас", .2, start, finish, "В работе", "2.2.1.1"),
        (2, "Фасад", .3, start, finish, "В работе", "2.2.1.1"),
    ]), None, "2026-10-01")
    monitor.store_schedule_fact(PROJECT, _gpr_book([
        (1, "Каркас", .4, start, finish, "В работе", "2.2.1.1"),
        (2, "Фасад", .3, start, finish, "В работе", "2.2.1.1"),
    ]), "2026-10-21")
    # Install the same production stack without replacing its captured builds.
    import developaid_monitor_page  # noqa: F401
    return PROJECT


def test_schedule_only_workflows_need_no_rss_and_all_readers_agree(site):
    view = monitor.build(site, CUT)
    assert view["financial_state"]["state"] == "missing"
    assert all(value is None for value in view["money"].values())
    assert view["by_code"] == view["schedule"]["rows"]
    rows = {r["id"]: r for r in view["by_code"]}
    assert rows["1"]["forecast_finish"] == "2026-12-20"
    assert rows["2"]["forecast_finish"] is None
    assert rows["2"]["pace_forecast_method"] == "stalled"
    assert view["schedule"]["risks"] == 2
    assert view["schedule"]["forecast_state"] == "partial"
    assert view["schedule"]["forecast_end"] is None
    assert view["schedule"]["indicative_forecast_end"] == "2026-12-20"
    api = monitor.gantt(site, CUT)
    assert api["rows"] == view["schedule"]["rows"]
    assert api["by_code"] == api["rows"]
    assert api["overdue"] == 2 and api["forecast_end"] is None
    assert api["work_fact"] == view["schedule"]["work_fact"]
    block = report.gantt(view, view["dashboard"])
    assert block["work_fact"] == api["work_fact"]
    assert block["corpora"][0]["forecast_partial"]
    assert block["corpora"][0]["forecast_finish"] == "2026-12-20"
    assert block["source"]["basis"] == "gpr"


def test_overlay_replaces_all_old_money_aliases_and_dates(site):
    view = manager._schedule_only(site, CUT)
    view["by_code"] = [{"actual_progress": .99, "forecast_finish": "2099-01-01"}]
    view["schedule"].update(risks=99, forecast_end="2099-01-01", pace_forecast_end="2099-01-01")
    for node in pace._walk(view["schedule"]["management"]):
        node.update(actual_progress=.99, actual_equivalent_date="2026-12-01", accepted=99, eac=100)
    pace._apply_gpr(site, view, CUT)
    assert view["by_code"] == view["schedule"]["rows"]
    assert view["schedule"]["risks"] == 2 and view["schedule"]["forecast_end"] is None
    for node in pace._walk(view["schedule"]["management"]):
        assert node["actual_equivalent_date"] is None
        if node["level"] == "task":
            assert node["actual_progress"] in (.3, .4)
            assert node["progress_source"]["date"] == "2026-10-21"
            assert node["progress_source"]["kind"] == "weekly_gpr"
        else:
            assert node["actual_progress"] is None and node["pace_progress"] is None
            assert node["progress_kind"] == "not_aggregated"
            assert node["progress_reason"]


def test_old_task_forecast_is_removed_when_current_gpr_has_no_pace(site):
    view = manager._schedule_only(site, CUT)
    for node in pace._walk(view["schedule"]["management"]):
        node["forecast_finish"] = "2099-01-01"
    pace._apply_gpr(site, view, CUT)
    leaf = next(node for node in pace._walk(view["schedule"]["management"])
                if node.get("id") == "2")
    assert leaf["forecast_finish"] is None and not leaf["forecast_known"]
    assert "стоит" in leaf["forecast_reason"]


def test_known_zero_has_source_and_missing_reading_is_not_zero(site):
    import developaid_schedule_gpr_forecast as gpr
    row = {"plan_start": "2026-09-01", "plan_finish": "2026-10-31"}
    known = gpr.work(row, [(dt.date(2026, 11, 1), 0., "weekly_gpr")], CUT)
    unknown = gpr.work(row, [], CUT)
    assert known["progress"] == 0 and known["progress_origin"] == "weekly_gpr"
    assert known["progress_date"] == "2026-11-01"
    assert unknown["progress"] is None and unknown["progress_origin"] is None
    assert unknown["method"] == "unknown" and "стоит" not in unknown["reason"]


def test_future_readings_never_supply_a_percent_or_pace():
    import developaid_schedule_gpr_forecast as gpr
    row = {"plan_start": "2026-09-01", "plan_finish": "2026-10-31"}
    got = gpr.work(row, [(dt.date(2026, 11, 7), 1., "weekly_gpr")], CUT)
    assert got["progress"] is None and got["forecast_finish"] is None


def test_duplicate_gpr_identifiers_do_not_borrow_the_last_rows_progress(monkeypatch):
    import developaid_schedule_gpr_forecast as gpr
    monkeypatch.setattr(gpr, "history", lambda *_: {"1": [(dt.date(2026,11,1), 1., "weekly_gpr")]})
    rows = [{"id": "1", "plan_finish": "2026-10-31"}, {"id": "1", "plan_finish": "2026-10-31"}]
    got = gpr.forecasts("Учебный", CUT, rows)["1"]
    assert got["forecast_finish"] is None and got["progress"] is None
    assert "повторяется" in got["reason"]


def test_nonconstruction_tasks_do_not_define_the_rnv_plan(site):
    view = manager._schedule_only(site, CUT)
    view["schedule"]["rows"].append({"id": "3", "name": "Продажи", "code": "",
                                      "plan_start": "2026-01-01", "plan_finish": "2030-01-01"})
    pace._apply_gpr(site, view, CUT)
    qualified = view["schedule"]["dependency_timeline"]["rnv"]
    assert qualified["approved"] == "2026-10-31"
    assert any("без статьи" in reason for reason in qualified["reasons"])


def test_unapproved_corpus_file_has_source_view_and_a_specific_mapping_blocker(tmp_path, monkeypatch):
    import developaid_schedule_gpr_physical as physical
    from test_gpr_corpus_preview import book
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path)
    monitor.store_schedule_fact(PROJECT, book(bad_date="01.02.2027"), CUT.isoformat())
    import developaid_monitor_page  # noqa: F401
    view = monitor.build(PROJECT, CUT)
    assert view["schedule"]["rows"] == []
    assert view["schedule"]["corpus_gpr"]["baseline_approved"] is False
    assert "Исходные показания ГПР" in view["schedule"]["corpus_gpr_html"]
    assert view["schedule"]["forecast_end"] is None
    state = physical.catalog(PROJECT, CUT.isoformat())
    assert state["source_state"] == "unapproved_corpus" and not state["can_edit"]
    assert "пакет и корпус" in state["source_reason"]
    assert state["tasks"] == [] and not state["model"]["physical_evidence"]


@pytest.mark.parametrize("value", [True, False, -1, -0.1, 101, float("nan"), float("inf")])
def test_corrupt_percent_cannot_become_work_readiness(value):
    import developaid_schedule_gpr_forecast as gpr
    assert gpr._progress(value) is None
