import datetime

import pytest

import developaid_monitor_scenarios as scenarios


def pm():
    d = datetime.date
    return {"known": True, "rnv_id": "3", "tasks": {
        "1": {"id": "1", "name": "Фасады", "start": d(2026, 1, 1),
              "finish": d(2026, 1, 31), "duration_days": 30,
              "predecessors": [], "free_float_days": 0, "total_float_days": 0},
        "2": {"id": "2", "name": "Отделка", "start": d(2026, 2, 1),
              "finish": d(2026, 3, 1), "duration_days": 28,
              "predecessors": [{"id": "1", "type": "FS", "lag_days": 0}],
              "free_float_days": 0, "total_float_days": 0},
        "3": {"id": "3", "name": "Получение РНВ", "start": d(2026, 3, 1),
              "finish": d(2026, 3, 1), "duration_days": 0,
              "predecessors": [{"id": "2", "type": "FS", "lag_days": 0}],
              "free_float_days": 0, "total_float_days": 0},
    }}


def test_delay_is_propagated_to_rnv():
    d = datetime.date
    view = {"schedule": {"rows": [
        {"id": "1", "forecast_finish": "2026-01-31", "code": "2.2.1"},
        {"id": "2", "forecast_finish": "2026-03-01", "code": "2.2.2"},
        {"id": "3", "forecast_finish": "2026-03-01", "code": ""},
    ]}}
    current, changed = scenarios._scenario_seeds(
        view, pm(), d(2026, 1, 15), "delay_wbs", ["1"], 20, 20
    )
    tasks = scenarios.graph._propagate(pm(), changed)
    assert tasks["1"]["forecast_finish"] == d(2026, 2, 20)
    assert scenarios._network_rnv(pm(), tasks) == d(2026, 3, 20)


def test_current_pace_uses_rss_evidence_but_not_as_physical_fact():
    d = datetime.date
    row = {"rss_accepted_ratio": .5, "rss_act_cost_rate_3m": .1}
    assert scenarios._pace_finish(row, d(2026, 1, 1)) == d(2026, 6, 2)


def test_delayed_article_need_is_moved_without_changing_amount():
    articles = {"2.2.1.4": {"rss_limit": 10, "monthly_need": {
        "2026-08-01": 30, "2026-09-01": 40,
    }}}
    shifted = scenarios._shift_articles(articles, {"2.2.1": 40})
    assert shifted["2.2.1.4"]["monthly_need"] == {
        "2026-09-01": 30.0, "2026-10-01": 40.0,
    }
    assert sum(shifted["2.2.1.4"]["monthly_need"].values()) == pytest.approx(70)


def test_past_need_is_not_resurrected_by_scenario_rephasing():
    articles = {"2.2.1.4": {"rss_limit": 10, "monthly_need": {
        "2026-06-01": 100, "2026-08-01": 30,
    }}}
    shifted = scenarios._shift_articles(
        articles, {"2.2.1": 90}, datetime.date(2026, 8, 21)
    )
    assert shifted["2.2.1.4"]["monthly_need"] == {
        "2026-06-01": 100.0,
        "2026-10-01": 30.0,
    }


def test_acceleration_recovers_current_delay_but_not_before_baseline():
    d = datetime.date
    view = {"schedule": {"rows": [{
        "id": "1", "forecast_finish": "2026-04-15", "code": "2.2.1",
    }]}}
    _, changed = scenarios._scenario_seeds(
        view, pm(), d(2026, 1, 15), "accelerate_wbs", ["1"], 0, 100
    )
    assert changed["1"] == d(2026, 3, 1)


def test_monitor_v2_shows_scenario_comparison_in_primary_ui():
    from developaid_monitor_page import MONITOR_PAGE
    assert "Cost control" in MONITOR_PAGE
    assert "Управленческий Гант" in MONITOR_PAGE
    assert "Платон · сценарный анализ" in MONITOR_PAGE
    assert "data-scenario=\"current_pace\"" in MONITOR_PAGE
    assert "Текущий утверждённый план" in MONITOR_PAGE


def test_scenario_route_is_registered_behind_monitor_access_gate():
    import main
    route = next(r for r in main.app.routes if getattr(r, "path", "") == "/monitor/scenario")
    assert "POST" in route.methods
