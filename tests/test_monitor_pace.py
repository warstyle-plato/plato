import datetime

import developaid_monitor_pace as pace


def _row(**overrides):
    row = {
        "plan_start": "2026-07-01",
        "plan_finish": "2026-12-31",
        "rss_accepted_ratio": 0.25,
        "rss_act_cost_rate_3m": 0.05,
    }
    row.update(overrides)
    return row


def test_pace_finish_uses_recent_acts_rate():
    cut = datetime.date(2026, 8, 22)
    finish, method = pace._pace_finish(_row(), cut)
    assert method == "rolling_3m_acts"
    assert finish > datetime.date(2027, 11, 1)
    assert pace._status(_row(), cut, finish) == "ОТСТАВАНИЕ ПО ТЕМПУ КС"


def test_pace_finish_can_show_ahead_of_plan():
    cut = datetime.date(2026, 8, 22)
    row = _row(rss_accepted_ratio=0.8, rss_act_cost_rate_3m=0.35)
    finish, _ = pace._pace_finish(row, cut)
    assert finish < datetime.date(2026, 12, 31)
    assert pace._status(row, cut, finish) == "ОПЕРЕЖЕНИЕ ПО ТЕМПУ КС"


def test_zero_progress_after_start_does_not_invent_remote_finish():
    cut = datetime.date(2026, 8, 22)
    row = _row(rss_accepted_ratio=0.0, rss_act_cost_rate_3m=0.0)
    finish, method = pace._pace_finish(row, cut)
    assert finish is None
    assert method == "no_pace"
    assert pace._status(row, cut, finish) == "НЕТ ТЕМПА КС / РИСК"


def test_future_task_has_no_pace_forecast():
    cut = datetime.date(2026, 8, 22)
    row = _row(plan_start="2026-10-01", plan_finish="2027-02-01")
    finish, method = pace._pace_finish(row, cut)
    assert finish is None
    assert method == "future"
    assert pace._status(row, cut, finish) == "БУДУЩАЯ ЗАДАЧА"


def test_management_aggregate_uses_separate_pace_forecast_fields():
    nodes = [{
        "level": "corpus",
        "plan_finish": "2027-06-30",
        "forecast_finish": "2027-06-30",
        "children": [
            {"level": "task", "plan_finish": "2027-05-31", "forecast_finish": "2027-05-31",
             "pace_forecast_finish": "2027-07-15", "pace_forecast_known": True},
            {"level": "task", "plan_finish": "2027-06-30", "forecast_finish": "2027-06-30",
             "pace_forecast_known": False},
        ],
    }]
    pace._aggregate_management(nodes)
    assert nodes[0]["forecast_finish"] == "2027-06-30"
    assert nodes[0]["pace_forecast_finish"] == "2027-07-15"
    assert nodes[0]["pace_delta_days"] == 15
    assert nodes[0]["pace_forecast_known"] is True
