"""Owner's decision: the MS Project export (PM) is not a source for Monitor or the summary."""
from __future__ import annotations

import developaid_monitor as monitor
import developaid_monitor_schedule_graph as graph
import developaid_schedule_physical as physical
import developaid_schedule_timeline as timeline


def test_a_stored_pm_file_is_not_read_and_the_reason_is_named(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path)
    folder = monitor._project_dir("Учебный") / "baseline"
    folder.mkdir(parents=True)
    (folder / "pm.xlsx").write_bytes(b"not read")
    pm = graph._load_pm("Учебный")
    assert pm["known"] is False and pm["disabled"] and not pm["tasks"]
    assert "отключена решением владельца" in pm["reason"]


def test_rnv_card_names_pm_off_instead_of_a_missing_upload():
    block = timeline.model(graph._load_pm("Учебный"), {})
    reasons = block["rnv"]["reasons"]
    assert reasons == [graph.PM_DISABLED_REASON]
    assert "не загружена" not in " ".join(reasons)
    assert "отключена" in timeline.render(block)


def test_pm_task_mappings_do_not_apply_and_say_why():
    block = physical.build("Учебный", "2026-11-06", graph._load_pm("Учебный"))
    assert block["state"] == "unknown" and not block["physical_evidence"] and block["disabled"]
    assert "PM отключён" in block["reasons"][0]


def test_monitor_page_hides_pm_cards_and_does_not_request_them():
    from playwright.sync_api import expect
    from test_monitor_cumulative_controls import browser_page
    with browser_page(1440) as (page, responses, errors):
        page.evaluate("loadScheduleConfirmation();loadPhysicalSchedule()")
        page.wait_for_timeout(300)
        paths = [path for path, _, _ in responses.calls]
        assert not any("schedule-confirmation" in p or "schedule-physical" in p for p in paths)
        expect(page.locator("#scheduleConfirmationCard")).to_be_hidden()
        expect(page.locator("#physicalScheduleCard")).to_be_hidden()
        expect(page.locator("#pm")).to_be_hidden()
        assert not errors


def test_pm_off_keeps_the_approved_rnv_from_the_gpr_in_cards_and_summary(monkeypatch):
    import datetime as dt
    import developaid_monitor_dashboard as dashboard
    import developaid_monitor_pace as pace
    monkeypatch.setattr(pace.corpus_gpr, "latest", lambda *_: None)
    row = {"id": "1", "plan_start": "2026-11-01", "plan_finish": "2027-01-20"}
    view = {"cut": "2026-11-06", "schedule": {"rows": [row], "management": [], "approved_end": "2027-02-01"},
            "dashboard": {"schedule": {"approved_finish": "2027-02-01"}, "summary": []}}
    pace._apply_pace("Учебный", view, dt.date(2026, 11, 6))
    qualified = view["dashboard"]["schedule"]["qualified_rnv"]
    assert qualified["approved"] == "2027-02-01" and qualified["approved_source"] == "утверждённый ГПР"
    assert graph.PM_DISABLED_REASON in qualified["reasons"]
    sentence = dashboard._schedule_summary(view["dashboard"]["schedule"])
    assert "Утверждённый ввод — 01.02.2027" in sentence
