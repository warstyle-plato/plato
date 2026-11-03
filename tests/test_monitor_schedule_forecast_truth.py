import datetime

import developaid_monitor_schedule_graph as graph


def _pm():
    return {
        "known": True,
        "source": "pm.xlsx",
        "rnv_id": "2",
        "tasks": {
            "1": {
                "id": "1",
                "name": "Фасад",
                "start": datetime.date(2026, 8, 1),
                "finish": datetime.date(2026, 12, 1),
                "duration_days": 122,
                "predecessors": [],
                "free_float_days": 0,
                "total_float_days": 0,
            },
            "2": {
                "id": "2",
                "name": "Получение РНВ",
                "start": datetime.date(2027, 9, 30),
                "finish": datetime.date(2027, 9, 30),
                "duration_days": 0,
                "predecessors": [{"id": "1", "type": "FS", "lag_days": 303}],
                "free_float_days": 0,
                "total_float_days": 0,
            },
        },
    }


def test_pm_baseline_is_approved_date_not_current_forecast(monkeypatch):
    monkeypatch.setattr(graph, "_load_pm", lambda _: _pm())
    monkeypatch.setattr(graph, "_rebaselines", lambda _: {})
    view = {"schedule": {"rows": [
        {"id": "1", "plan_finish": "2026-12-01", "forecast_finish": "2026-12-01"},
        {"id": "2", "plan_finish": "2027-09-30", "forecast_finish": "2027-09-30"},
    ], "management": []}}

    result = graph.apply("demo", view)
    meta = result["schedule"]["dependency_graph"]

    assert meta["forecast_known"] is False
    assert result["schedule"]["approved_end"] == "2027-09-30"
    assert result["schedule"]["forecast_end"] is None
    assert meta["rnv_forecast"] is None


def test_explicit_rebaseline_seed_creates_network_forecast(monkeypatch):
    monkeypatch.setattr(graph, "_load_pm", lambda _: _pm())
    monkeypatch.setattr(graph, "_rebaselines", lambda _: {})
    view = {"schedule": {"rows": [
        {
            "id": "1",
            "plan_finish": "2026-12-01",
            "forecast_finish": "2027-01-01",
            "forecast_source": "approved_rebaseline",
        },
        {"id": "2", "plan_finish": "2027-09-30", "forecast_finish": "2027-09-30"},
    ], "management": []}}

    result = graph.apply("demo", view)
    meta = result["schedule"]["dependency_graph"]

    assert meta["forecast_known"] is True
    assert meta["forecast_source"] == "approved_rebaseline"
    assert result["schedule"]["forecast_end"] is not None
