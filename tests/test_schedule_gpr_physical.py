"""Explicit, source-bound GPR/natural mappings; never inherit a PM mapping."""
from __future__ import annotations

import copy
import datetime as dt
from concurrent.futures import ThreadPoolExecutor

import pytest

import developaid_monitor as monitor
import developaid_schedule_gpr_physical as physical
import developaid_monitor_pace as pace
from test_monitor_management_gantt import _gpr_book
from test_schedule_physical import snapshot, item

CUT = "2026-11-06"
PROJECT = "Учебный график"


def config():
    return {"tasks": [{"task_id": "1", "mode": "quantities", "scope_confirmed": True, "actual_finish": ""}],
            "components": [{"component_id": "Корпус 1 — фасад", "task_id": "1", "item_ids": ["0:0"]}],
            "note": "Проверены работа, корпус, единица и полный объём."}


@pytest.fixture
def site(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path)
    monkeypatch.setattr(physical, "_now", lambda: dt.datetime(2026, 11, 6, 12, tzinfo=dt.timezone.utc))
    start, finish = dt.date(2026, 9, 1), dt.date(2026, 10, 31)
    blob = _gpr_book([(1, "Фасад", .8, start, finish, "В работе", "2.2.1.1")])
    monitor.store_schedule(PROJECT, blob, None, "2026-10-01")
    snap = snapshot()
    monkeypatch.setattr(physical.ledgers, "latest_snapshot", lambda project, cut="": copy.deepcopy(snap)
                        if not cut or cut >= CUT else None)
    return tmp_path, snap, blob


def save(**changes):
    state = physical.catalog(PROJECT, CUT)
    args = {k: state[k] for k in ("source_kind", "source_sha256", "snapshot_id", "revision")}
    args["configuration"] = config()
    args.update(changes)
    return physical.save(PROJECT, **args)


def test_natural_mapping_is_an_explicit_action_and_overrides_money_and_gpr_pace(site):
    before = physical.catalog(PROJECT, CUT)
    assert before["can_edit"] and before["source_kind"] == "gpr"
    assert before["model"]["tasks"][0]["progress"] is None
    saved = save()
    assert saved["revision"] == 1
    bound = saved["model"]["tasks"][0]
    assert bound["known"] and bound["progress"] == .5
    assert bound["forecast_finish"] == "2026-12-07"
    assert bound["progress_date"] == "2026-10-31"
    import developaid_monitor_page  # noqa: F401
    view = monitor.build(PROJECT, CUT)
    row = view["schedule"]["rows"][0]
    assert row["pace_forecast_method"] == "cumulative_quantities"
    assert row["actual_progress"] == .5 and row["forecast_finish"] == "2026-12-07"
    assert row["gpr_progress"] == .8
    facts = view["schedule"]["work_fact"]["works"]["1"]
    assert facts["gpr"]["progress"] == .8 and facts["ks"]["progress"] == .5 and facts["divergent"]
    assert view["money"]["accepted"] is None  # no RSS/financial workbook required


def test_pm_journal_is_neither_read_nor_migrated_and_projects_are_isolated(site):
    root, _, blob = site
    old = monitor._project_dir(PROJECT) / "physical_schedule_links"
    old.mkdir()
    (old / "000000000001.json").write_text("broken old PM journal")
    assert not physical.catalog(PROJECT, CUT)["model"]["physical_evidence"]
    save()
    monitor.store_schedule("Другой", blob, None, "2026-10-01")
    assert physical.catalog("Другой", CUT)["configuration"]["tasks"] == []
    assert physical.catalog("Другой", CUT)["model"]["tasks"][0]["progress"] is None


@pytest.mark.parametrize("change", [{"source_sha256": "c"*64}, {"snapshot_id": CUT+"-"+"c"*64},
                                     {"revision": 1}, {"revision": True}, {"source_kind": "pm"}])
def test_stale_or_substituted_source_cannot_record_a_binding(site, change):
    with pytest.raises(physical.PhysicalProblem):
        save(**change)
    assert not list(site[0].rglob("gpr_physical_links/[0-9]*.json"))


def test_changed_gpr_or_snapshot_invalidates_evidence_even_when_task_id_matches(site):
    _, snap, _ = site
    save()
    path = monitor._baseline_file(PROJECT)
    original = path.read_bytes()
    path.write_bytes(_gpr_book([(1, "Фасад другой секции", .8, dt.date(2026,9,1),
                               dt.date(2026,10,31), "В работе", "2.2.1.1")]))
    changed = physical.catalog(PROJECT, CUT)
    assert changed["source_changed"] and not changed["model"]["physical_evidence"]
    path.write_bytes(original)
    snap["snapshot_id"] = CUT+"-"+"d"*64
    assert physical.catalog(PROJECT, CUT)["model"]["tasks"][0]["progress"] is None


def test_historical_cut_cannot_read_a_later_binding_or_snapshot(site):
    save()
    earlier = physical.catalog(PROJECT, "2026-11-05")
    assert earlier["configuration"]["tasks"] == [] and not earlier["can_edit"]
    assert not earlier["model"]["physical_evidence"]
    assert earlier["model"]["tasks"][0]["progress"] is None


def test_a_future_or_misidentified_archive_cannot_supply_natural_facts(site):
    _, snap, _ = site
    save()
    snap["snapshot_id"] = "2026-11-07-"+"b"*64
    got = physical.build(PROJECT, CUT)
    assert not got["physical_evidence"] and not got["seeds"]
    snap["snapshot_id"] = CUT+"-"+"b"*64
    snap["sha256"] = "c"*64
    assert not physical.build(PROJECT, CUT)["physical_evidence"]


def test_units_and_dates_are_checked_and_bad_natural_pace_does_not_fall_back_to_a_gpr_date(site):
    _, snap, _ = site
    snap["ledgers"].append(dict(snap["ledgers"][0], period_year=2025,
                                  items=[item(2025, unit="т")]))
    cfg = config()
    cfg["components"][0]["item_ids"] = ["0:0", "1:0"]
    state = save(configuration=cfg)
    task = state["model"]["tasks"][0]
    assert task["forecast_finish"] is None and "единицы" in task["reason"]
    import developaid_monitor_page  # noqa: F401
    row = monitor.build(PROJECT, CUT)["schedule"]["rows"][0]
    assert row["forecast_finish"] is None and row["pace_forecast_method"] == "cumulative_unknown"
    assert row["actual_progress"] is None


def test_money_and_material_values_cannot_change_a_natural_forecast(site):
    _, snap, _ = site
    save()
    before = physical.build(PROJECT, CUT)
    snap["ledgers"][0]["items"][0].update(completed_amount=1e18, material_quantity=1e15)
    assert physical.build(PROJECT, CUT) == before


def test_unconfirmed_scope_does_not_expose_computed_components_as_bound_facts(site):
    cfg = config()
    cfg["tasks"][0]["scope_confirmed"] = False
    task = save(configuration=cfg)["model"]["tasks"][0]
    assert task["progress"] is None and task["components"] == [] and not task["known"]


@pytest.mark.parametrize("change", ["task", "row", "future"])
def test_foreign_work_rows_or_future_completion_cannot_save(site, change):
    cfg = config()
    if change == "task":
        cfg["tasks"][0]["task_id"] = cfg["components"][0]["task_id"] = "not-in-gpr"
    elif change == "row":
        cfg["components"][0]["item_ids"] = ["99:99"]
    else:
        cfg["tasks"][0].update(mode="completed", actual_finish="2026-11-07")
        cfg["components"] = []
    with pytest.raises(physical.PhysicalProblem):
        save(configuration=cfg)


def test_concurrent_editors_cannot_commit_the_same_revision(site):
    state = physical.catalog(PROJECT, CUT)
    def attempt():
        try:
            return physical.save(PROJECT, "gpr", state["source_sha256"], state["snapshot_id"], 0, config())["revision"]
        except physical.PhysicalProblem as exc:
            return exc.status
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: attempt(), range(4)))
    assert results.count(1) == 1 and results.count(409) == 3


def test_corrupt_journal_fails_closed_without_using_its_private_content(site):
    save()
    path = next(site[0].rglob("gpr_physical_links/[0-9]*.json"))
    path.write_text("PRIVATE-SOURCE-MARKER")
    got = physical.build(PROJECT, CUT)
    assert not got["physical_evidence"] and not got["seeds"]
    assert "PRIVATE-SOURCE-MARKER" not in str(got)
