import datetime

import pytest

import developaid_monitor_manager as manager


def test_rss_codes_use_natural_numeric_order():
    codes = ["2.2.3.10", "2.4.1", "2.2.3.2", "2.2.3.9", "2.1"]
    assert sorted(codes, key=manager._natural) == [
        "2.1", "2.2.3.2", "2.2.3.9", "2.2.3.10", "2.4.1"
    ]


def test_rss_21_is_split_by_wbs_meaning_not_used_as_one_schedule_phase():
    prep = {"wbs": "1.16.1.2.4", "name": "Организация строительной площадки"}
    pos = {"wbs": "1.16.1.3.1", "name": "Работы, предусмотренные ПОС"}

    assert manager._schedule_bucket(prep, "2.1") == (
        "Подготовка", "Подготовка территории"
    )
    assert manager._schedule_bucket(pos, "2.1") == (
        "Организация стройплощадки / ПОС", "ПОС и временная инфраструктура"
    )


def test_completed_works_are_cost_evidence_not_physical_wbs_percent():
    cut = datetime.date(2026, 8, 1)
    estimate = {
        "rows": [{"code": "2.2.1.4", "parent": ""}],
        "by_code": {"2.2.1.4": {"estimate": 100.0}},
    }
    works = {"rows": [
        {"code": "2.2.1.4", "construction": True,
         "date": datetime.date(2026, 7, 15), "amount": 40.0},
        {"code": "2.2.1.4", "construction": False,
         "date": datetime.date(2026, 7, 20), "amount": 50.0},
        {"code": "2.2.1.4", "construction": True,
         "date": datetime.date(2026, 8, 15), "amount": 30.0},
    ]}

    result = manager._metrics(estimate, works, "2.2.1.4", cut)

    assert result["accepted"] == pytest.approx(40.0)
    assert result["accepted_ratio"] == pytest.approx(0.4)
    assert "progress" not in result


def test_money_pace_can_never_push_a_wbs_finish_to_2031(monkeypatch):
    monkeypatch.setattr(manager, "_baseline_status", lambda _: {
        "100": {"closed": False, "status": "В работе"}
    })
    schedule = {"rows": [{
        "id": "100",
        "wbs": "1.16.2.5",
        "plan_finish": "2027-03-31",
        "forecast_finish": "2031-06-01",
        "actual_progress": 0.829,
        "rate_3m": 0.002,
        "delta_days": 1523,
    }]}

    manager._sanitize_base_schedule("demo", schedule)
    row = schedule["rows"][0]

    assert row["forecast_finish"] == "2027-03-31"
    assert row["delta_days"] == 0
    assert row["actual_progress"] is None
    assert row["rss_accepted_ratio"] == pytest.approx(0.829)
    assert row["progress_kind"] == "accepted_cost_ratio"


def test_closed_wbs_stays_closed_even_if_cost_ratio_is_below_one(monkeypatch):
    monkeypatch.setattr(manager, "_baseline_status", lambda _: {
        "914": {"closed": True, "status": "Завершено"}
    })
    schedule = {"rows": [{
        "id": "914",
        "wbs": "1.16.1.2.4",
        "plan_finish": "2025-06-09",
        "forecast_finish": "2031-01-01",
        "actual_progress": 0.829,
        "rate_3m": 0.0,
        "delta_days": 2000,
    }]}

    manager._sanitize_base_schedule("demo", schedule)
    row = schedule["rows"][0]

    assert row["baseline_closed"] is True
    assert row["forecast_finish"] == "2025-06-09"
    assert row["status"] == "ЗАВЕРШЕНО ПО УТВЕРЖДЕННОМУ ГПР"
