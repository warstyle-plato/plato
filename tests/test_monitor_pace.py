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


def test_mixed_lifecycle_rss_21_is_cost_evidence_not_a_calendar_forecast():
    cut = datetime.date(2026, 8, 22)
    row = _row(code="2.1", plan_start="2024-01-01", plan_finish="2027-09-30")
    finish, method = pace._pace_finish(row, cut)
    assert finish is None
    assert method == "mixed_lifecycle_rss"


def test_task_without_own_pace_inherits_plan_duration_shifted_by_predecessors(monkeypatch):
    """Будущая работа без актов — не «без прогноза»: её прогноз строится от
    плановой длительности со стартом, сдвинутым задержкой предшественников."""
    d = datetime.date
    cut = d(2026, 8, 22)
    pm = {"known": True, "rnv_id": "", "tasks": {
        "A": {"id": "A", "name": "Монолит", "start": d(2026, 7, 1),
              "finish": d(2026, 12, 31), "duration_days": 183,
              "predecessors": [], "free_float_days": 0, "total_float_days": 0},
        "B": {"id": "B", "name": "Фасад", "start": d(2027, 1, 1),
              "finish": d(2027, 3, 1), "duration_days": 59,
              "predecessors": [{"id": "A", "type": "FS", "lag_days": 0}],
              "free_float_days": 0, "total_float_days": 0},
        "C": {"id": "C", "name": "Старый нулевой цикл", "start": d(2025, 1, 1),
              "finish": d(2025, 6, 30), "duration_days": 180,
              "predecessors": [], "free_float_days": 0, "total_float_days": 0},
        "D": {"id": "D", "name": "Благоустройство", "start": d(2027, 6, 1),
              "finish": d(2027, 9, 1), "duration_days": 92,
              "predecessors": [], "free_float_days": 0, "total_float_days": 0},
    }}
    monkeypatch.setattr(pace.schedule_graph, "_load_pm", lambda _p: pm)
    rows = [
        {"id": "A", "plan_start": "2026-07-01", "plan_finish": "2026-12-31",
         "rss_accepted_ratio": 0.25, "rss_act_cost_rate_3m": 0.05},
        {"id": "B", "plan_start": "2027-01-01", "plan_finish": "2027-03-01",
         "rss_accepted_ratio": None, "rss_act_cost_rate_3m": None},
        {"id": "C", "plan_start": "2025-01-01", "plan_finish": "2025-06-30",
         "rss_accepted_ratio": 0.0, "rss_act_cost_rate_3m": 0.0},
        {"id": "D", "plan_start": "2027-06-01", "plan_finish": "2027-09-01",
         "rss_accepted_ratio": None, "rss_act_cost_rate_3m": None},
    ]
    view = {"schedule": {"rows": rows, "management": []}, "dashboard": {"schedule": {}}}
    pace._apply_pace("Проект", view, cut)
    by_id = {row["id"]: row for row in rows}

    # Сдвинутый предшественником наследует задержку по сети (было и раньше).
    assert by_id["B"]["pace_forecast_known"] is True
    assert by_id["B"]["pace_forecast_method"] == "acts_pace_plus_pm_dependencies"
    assert by_id["B"]["pace_delta_days"] > 0
    assert by_id["B"]["pace_forecast_finish"] > "2027-03-01"

    # Будущая работа, чьи предшественники не сдвинуты, идёт по плану — и это
    # прогноз, а не «forecast не рассчитан».
    assert by_id["D"]["pace_forecast_known"] is True
    assert by_id["D"]["pace_forecast_method"] == "plan_duration_shifted_by_predecessors"
    assert by_id["D"]["pace_delta_days"] == 0
    assert by_id["D"]["pace_forecast_finish"] == "2027-09-01"
    assert by_id["D"]["pace_status"] == "ПО ПЛАНУ (ТЕМПА КС НЕТ)"

    # Просроченная работа без актов прогноза не получает: «план» в прошлом —
    # не прогноз, а немаркированный риск.
    assert not by_id["C"].get("pace_forecast_known")


def test_management_aggregate_exposes_pace_forecast_on_presentation_tree():
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
    assert nodes[0]["forecast_finish"] == "2027-07-15"
    assert nodes[0]["pace_forecast_finish"] == "2027-07-15"
    assert nodes[0]["pace_delta_days"] == 15
    assert nodes[0]["pace_forecast_known"] is True
