"""Two readiness facts per GPR work: the GPR file and cumulative KS, side by side."""
from __future__ import annotations

import datetime

import pytest

import developaid_monitor as monitor
import developaid_monitor_manager as manager
import developaid_schedule_work_fact as work_fact
from test_monitor_management_gantt import _gpr_book

D1, D2 = datetime.date(2025, 8, 23), datetime.date(2025, 10, 28)


@pytest.fixture
def site(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path)
    monitor.store_schedule("Учебный", _gpr_book([
        (1, "Котлован", 0.0, D1, D2, "В работе", "2.2.1.1"),
        (2, "Кровля", 0.0, D1, D2, "В работе", "2.2.2.3"),
        (3, "Фасад", 0.2, D1, D2, "В работе", "2.2.2.4"),
    ]), None, "2026-07-23")
    monitor.store_schedule_fact("Учебный", _gpr_book([
        (1, "Котлован", 0.6, D1, D2, "В работе", "2.2.1.1"),
        (2, "Кровля", 0.4, D1, D2, "В работе", "2.2.2.3"),
    ]), "2026-08-20")
    monitor.store_work_fact("Учебный", [{"id": "2", "progress": 0.5}], "2026-09-01")
    return "Учебный"


def rows(site, upto):
    schedule = {"rows": [{"id": tid, "plan_finish": "2027-01-01", "actual_progress": 0.0}
                         for tid in ("1", "2", "3")]}
    manager._sanitize_base_schedule(site, schedule, upto)
    return {row["id"]: row for row in schedule["rows"]}


def test_past_cut_does_not_read_a_later_weekly_file_or_manual_decision(site):
    early = rows(site, "2026-08-01")
    assert early["1"]["gpr_progress"] == 0.0 and early["1"]["gpr_progress_origin"] == "approved_gpr"
    middle = rows(site, "2026-08-25")
    assert middle["1"]["gpr_progress"] == pytest.approx(0.6)
    assert (middle["1"]["gpr_progress_origin"], middle["1"]["gpr_progress_date"]) == ("weekly_gpr", "2026-08-20")
    assert middle["2"]["gpr_progress"] == pytest.approx(0.4)
    late = rows(site, "2026-09-05")
    assert late["2"]["gpr_progress"] == pytest.approx(0.5)
    assert (late["2"]["gpr_progress_origin"], late["2"]["gpr_progress_date"]) == ("manual", "2026-09-01")
    # A work absent from the weekly file keeps the approved GPR as its origin.
    assert late["3"]["gpr_progress_origin"] == "approved_gpr"


def physical_task(tid, **values):
    return dict({"task_id": tid, "mode": "quantities", "known": True, "progress": None,
                 "components": [], "reason": ""}, **values)


def component(cid, progress, end, unit="м²"):
    return {"component_id": cid, "progress": progress, "period_end": end, "unit": unit, "reason": ""}


def test_two_facts_side_by_side_with_a_ten_point_divergence():
    chart = [{"id": "1", "gpr_progress": 0.60, "gpr_progress_origin": "weekly_gpr", "gpr_progress_date": "2026-10-30"},
             {"id": "2", "gpr_progress": 0.55, "gpr_progress_origin": "weekly_gpr", "gpr_progress_date": "2026-10-30"},
             {"id": "3", "gpr_progress": 0.20, "gpr_progress_origin": "approved_gpr", "gpr_progress_date": None},
             {"id": "4", "gpr_progress": None, "gpr_progress_origin": "approved_gpr", "gpr_progress_date": None},
             {"id": "5", "gpr_progress": 0.9, "gpr_progress_origin": "manual", "gpr_progress_date": "2026-11-01"},
             {"id": "6", "gpr_progress": 0.1, "gpr_progress_origin": "weekly_gpr", "gpr_progress_date": "2026-10-30"}]
    physical = {"tasks": [
        physical_task("1", progress=0.48, components=[component("Корпус 1", 0.48, "2026-10-31")]),
        physical_task("2", progress=0.50, components=[component("Корпус 2", 0.50, "2026-10-31")]),
        physical_task("3", progress=None, components=[component("Бетон", 0.3, "2026-10-31", "м³"),
                                                       component("Арматура", 0.5, "2026-10-31", "т")]),
        physical_task("5", mode="completed", known=True, actual_finish="2026-10-15"),
        physical_task("6", mode="plan_duration")]}
    result = work_fact.model(chart, physical)
    works = result["works"]
    one = works["1"]
    assert one["gpr"]["progress"] == 0.60 and one["gpr"]["label"] == "еженедельный файл ГПР"
    assert one["ks"]["progress"] == 0.48 and one["ks"]["date"] == "2026-10-31"
    assert one["divergent"] and one["gap"] == pytest.approx(0.12)
    assert not works["2"]["divergent"]  # 5 points apart
    assert works["3"]["ks"]["progress"] is None and "по компонентам" in works["3"]["ks"]["reason"]
    assert [c["progress"] for c in works["3"]["ks"]["components"]] == [0.3, 0.5]
    assert works["4"]["ks"]["reason"] == "Работа не сопоставлена с накопительными."
    assert works["4"]["gpr"]["reason"]
    assert works["5"]["ks"]["progress"] == 1.0 and works["5"]["ks"]["origin"] == "confirmed_completion"
    assert works["5"]["gpr"]["label"] == "решение в Мониторе"
    assert works["6"]["ks"]["progress"] is None and "плановая длительность" in works["6"]["ks"]["reason"]
    assert works["5"]["divergent"]  # manual 90% against a confirmed completion
    assert result["counts"] == {"works": 6, "with_ks": 3, "divergent": 2}


def test_exactly_ten_points_is_divergent():
    chart = [{"id": "1", "gpr_progress": 0.5, "gpr_progress_origin": "weekly_gpr"}]
    physical = {"tasks": [physical_task("1", progress=0.4)]}
    assert work_fact.model(chart, physical)["works"]["1"]["divergent"]


def test_pace_attaches_the_one_model_to_the_monitor_view(monkeypatch):
    import developaid_monitor_pace as pace
    from test_schedule_dependency_timeline import network
    pm = network()
    monkeypatch.setattr(pace.schedule_graph, '_load_pm', lambda *_: pm)
    monkeypatch.setattr(pace.corpus_gpr, 'latest', lambda *_: None)
    row = {'id': '1', 'plan_start': '2026-11-01', 'plan_finish': '2026-11-20',
           'gpr_progress': 0.3, 'gpr_progress_origin': 'weekly_gpr', 'gpr_progress_date': '2026-11-01'}
    view = {'cut': '2026-11-06', 'schedule': {'rows': [row], 'management': []}, 'dashboard': {'schedule': {}}}
    pace._apply_pace('Synthetic', view, datetime.date(2026, 11, 6))
    fact = view['schedule']['work_fact']['works']['1']
    assert fact['gpr']['progress'] == 0.3 and fact['ks']['progress'] is None
