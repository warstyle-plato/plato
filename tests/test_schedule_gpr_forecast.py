"""Work and RNV forecast from the GPR and cumulatives (PM off, no money pace). Synthetic data."""
from __future__ import annotations

import datetime as dt

import pytest

import developaid_monitor as monitor
import developaid_schedule_gpr_forecast as gpr
from test_monitor_management_gantt import _gpr_book

CUT = dt.date(2026, 11, 6)


def d(text):
    return dt.date.fromisoformat(text)


def row(tid="1", start="2026-09-01", finish="2026-12-31", code="2.2.1.1", name="Каркас"):
    return {"id": tid, "plan_start": start, "plan_finish": finish, "code": code, "name": name}


def test_pace_of_gpr_percent_over_the_last_ninety_days():
    points = [(d("2026-10-01"), 0.2, "weekly_gpr"), (d("2026-10-21"), 0.4, "weekly_gpr")]
    got = gpr.work(row(), points, CUT)
    # 0.2 per 20 days -> 0.6 left takes 60 days after the last record.
    assert got["method"] == "gpr_pace" and got["forecast_finish"] == "2026-12-20"
    assert got["window"] == ["2026-10-01", "2026-10-21"]


def test_no_growth_after_the_deadline_is_a_standing_work_without_a_date():
    points = [(d("2026-10-01"), 0.3, "weekly_gpr"), (d("2026-11-01"), 0.3, "weekly_gpr")]
    got = gpr.work(row(finish="2026-10-15"), points, CUT)
    assert got["method"] == "stalled" and got["forecast_finish"] is None and "стоит" in got["reason"]


@pytest.mark.parametrize("start,reason", [("2026-09-01", "роста процента"), ("2026-12-01", "ещё не началась")])
def test_within_plan_without_growth_keeps_the_plan(start, reason):
    points = [(d("2026-10-01"), 0.0, "weekly_gpr"), (d("2026-11-01"), 0.0, "weekly_gpr")]
    got = gpr.work(row(start=start, finish="2027-02-01"), points, CUT)
    assert got["method"] == "plan" and got["forecast_finish"] == "2027-02-01" and reason in got["reason"]


def test_done_work_takes_the_first_record_at_one_hundred_percent():
    points = [(d("2026-09-01"), 0.8, "weekly_gpr"), (d("2026-09-20"), 1.0, "weekly_gpr"),
              (d("2026-10-20"), 1.0, "weekly_gpr")]
    got = gpr.work(row(), points, CUT)
    assert got["method"] == "done" and got["forecast_finish"] == "2026-09-20"


def test_old_records_do_not_make_a_pace_and_stale_overdue_has_no_date():
    points = [(d("2026-07-01"), 0.1, "weekly_gpr"), (d("2026-09-01"), 0.5, "weekly_gpr")]
    got = gpr.work(row(finish="2026-10-01"), points, CUT)
    assert got["forecast_finish"] is None and got["method"] == "stale"


def test_cumulative_quantities_take_precedence_when_the_work_is_bound():
    points = [(d("2026-10-01"), 0.2, "weekly_gpr"), (d("2026-10-21"), 0.4, "weekly_gpr")]
    got = gpr.work(row(), points, CUT, {"forecast_finish": "2027-01-15", "progress": 0.35})
    assert got["method"] == "cumulative_quantities" and got["forecast_finish"] == "2027-01-15"


def test_rnv_is_the_latest_construction_work_and_names_what_is_left_out():
    rows = [row("1", code="2.2.1.1", name="Каркас"), row("2", code="2.2.2.3", name="Кровля"),
            row("3", code="", name="Продажи"), row("4", code="", name="Ходатайство")]
    works = {"1": {"forecast_finish": "2027-03-01", "method": "gpr_pace"},
             "2": {"forecast_finish": "2027-05-10", "method": "plan", "reason": "по плану"},
             "3": {"forecast_finish": "2030-01-01"}, "4": {"forecast_finish": None}}
    got = gpr.rnv(rows, works, "2027-04-30")
    assert got["state"] == "estimate" and got["forecast"] == "2027-05-10" and got["delay_days"] == 10
    assert got["driving_chain"][0]["name"] == "Кровля"
    assert any("2 работ ГПР без статьи" in r for r in got["reasons"])
    assert gpr.ESTIMATE_NOTE in got["reasons"]


def test_rnv_with_a_standing_construction_work_is_partial_not_a_date():
    rows = [row("1", name="Каркас"), row("2", name="Фасад")]
    works = {"1": {"forecast_finish": "2027-03-01"}, "2": {"forecast_finish": None, "method": "stalled"}}
    got = gpr.rnv(rows, works, "2027-04-30")
    assert got["state"] == "partial" and got["forecast"] is None and got["indicative_forecast"] == "2027-03-01"
    assert any("«Фасад»" in r for r in got["reasons"])


def test_monitor_layer_uses_stored_gpr_files_and_never_money_pace(tmp_path, monkeypatch):
    import developaid_monitor_pace as pace
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path)
    start, finish = dt.date(2026, 9, 1), dt.date(2026, 12, 31)
    monitor.store_schedule("Учебный", _gpr_book([
        (1, "Каркас", 0.0, start, finish, "В работе", "2.2.1.1"),
        (2, "Продажи", 0.0, start, dt.date(2030, 1, 1), "В работе", ""),
    ]), None, "2026-09-01")
    monitor.store_schedule_fact("Учебный", _gpr_book([
        (1, "Каркас", 0.2, start, finish, "В работе", "2.2.1.1"),
        (2, "Продажи", 0.1, start, dt.date(2030, 1, 1), "В работе", ""),
    ]), "2026-10-01")
    monitor.store_schedule_fact("Учебный", _gpr_book([
        (1, "Каркас", 0.4, start, finish, "В работе", "2.2.1.1"),
        (2, "Продажи", 0.2, start, dt.date(2030, 1, 1), "В работе", ""),
    ]), "2026-10-21")
    rows = [dict(row("1"), rss_accepted_ratio=0.9, rss_act_cost_rate_3m=0.5),
            dict(row("2", finish="2030-01-01", code="", name="Продажи"))]
    view = {"cut": CUT.isoformat(), "schedule": {"rows": rows, "management": []},
            "dashboard": {"schedule": {"approved_finish": "2026-12-31"}, "summary": []}}
    pace._apply_pace("Учебный", view, CUT)
    first = view["schedule"]["rows"][0]
    # The approved GPR of 01.09 (0%) is inside the 90-day window: 40% per 50 days,
    # 60% left -> 75 days after 21.10.
    assert first["pace_forecast_method"] == "gpr_pace" and first["pace_forecast_finish"] == "2027-01-04"
    qualified = view["dashboard"]["schedule"]["qualified_rnv"]
    assert qualified["state"] == "estimate" and qualified["forecast"] == "2027-01-04"
    assert qualified["basis"] == "gpr" and qualified["delay_days"] == 4
    assert qualified["driving_chain"][0]["name"] == "Каркас"  # «Продажи» has no article
    assert "оценка по ГПР" in view["schedule"]["dependency_timeline_html"]
    assert view["dashboard"]["summary"][0].startswith("Срок.") and "Без цепочки" in view["dashboard"]["summary"][0]


def test_summary_shows_the_estimate_but_does_not_shift_loans():
    import developaid_management_report as report
    qualified = {"state": "estimate", "approved": "2027-04-30", "forecast": "2027-05-10",
                 "delay_days": 10, "basis": "gpr", "reasons": [gpr.ESTIMATE_NOTE], "driving_chain": []}
    dashboard = {"schedule": {"qualified_rnv": qualified}}
    block = report.schedule(dashboard)
    assert block["known"] and block["estimate"] and block["delay_days"] == 10
    assert report._forecast_shift(dashboard, {"date": "2027-04-30"}) is None
    payload = {"project": "Учебный", "kind": "week", "start": "2026-11-01", "end": "2026-11-06", "schedule": block}
    text = " ".join(f["text"] for f in report.findings(payload) if f.get("topic") == "Срок")
    assert "10.05.2027" in text and "без цепочки до получения разрешения" in text


def test_monitor_card_shows_the_estimate_date_with_its_caveat():
    from playwright.sync_api import expect
    from test_monitor_cumulative_controls import browser_page
    qualified = {"state": "estimate", "approved": "2027-04-30", "forecast": "2027-05-10",
                 "delay_days": 10, "basis": "gpr", "reasons": [gpr.ESTIMATE_NOTE], "driving_chain": []}
    with browser_page(390) as (page, responses, errors):
        page.evaluate("(q)=>renderDash({dashboard:{schedule:{qualified_rnv:q}},schedule:{}})", qualified)
        kpis = page.locator('#kpis')
        expect(kpis).to_contain_text('10.05.2027')
        expect(kpis).to_contain_text('оценка по ГПР')
        assert not errors
