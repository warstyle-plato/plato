import datetime

import pytest

import developaid_monitor_manager as manager


def test_rss_codes_use_natural_numeric_order():
    codes = ["2.2.3.10", "2.4.1", "2.2.3.2", "2.2.3.9", "2.1"]
    assert sorted(codes, key=manager._natural) == [
        "2.1", "2.2.3.2", "2.2.3.9", "2.2.3.10", "2.4.1"
    ]


def test_management_groups_follow_developaid_control_structure():
    assert manager._control("2.1") == "Подготовка"
    assert manager._control("2.2.1.4") == "Основные объекты"
    assert manager._detail("2.2.1.4") == "Основное строительство — подземная часть"
    assert manager._detail("2.2.3.4") == "Основное строительство — надземная часть + ВИС"
    assert manager._control("2.4.3") == "Наружные сети"
    assert manager._control("2.5") == "Благоустройство"


def test_physical_progress_uses_construction_acts_only():
    cut = datetime.date(2026, 8, 1)
    estimate = {
        "rows": [{"code": "2.2.1.4", "parent": ""}],
        "by_code": {"2.2.1.4": {"estimate": 100.0}},
    }
    works = {"rows": [
        {"code": "2.2.1.4", "construction": True,
         "date": datetime.date(2026, 7, 15), "amount": 40.0},
        # Money-like/non-construction rows must never become physical Gantt fact.
        {"code": "2.2.1.4", "construction": False,
         "date": datetime.date(2026, 7, 20), "amount": 50.0},
        # Future act is outside the reporting cut.
        {"code": "2.2.1.4", "construction": True,
         "date": datetime.date(2026, 8, 15), "amount": 30.0},
    ]}

    result = manager._metrics(estimate, works, "2.2.1.4", cut)

    assert result["accepted"] == pytest.approx(40.0)
    assert result["progress"] == pytest.approx(0.4)


def test_summary_aggregates_unique_rss_rows_not_wbs_duplicates():
    cut = datetime.date(2026, 8, 1)
    children = [
        {"plan_start": datetime.date(2026, 1, 1),
         "plan_finish": datetime.date(2026, 10, 1),
         "plan_progress": 0.7, "actual_progress": 0.5,
         "accepted": 50.0, "eac": 100.0, "rate_3m": 0.1,
         "forecast_finish": datetime.date(2026, 9, 1), "status": "В СРОК"},
        {"plan_start": datetime.date(2026, 3, 1),
         "plan_finish": datetime.date(2026, 12, 1),
         "plan_progress": 0.4, "actual_progress": 0.2,
         "accepted": 20.0, "eac": 100.0, "rate_3m": 0.05,
         "forecast_finish": datetime.date(2027, 1, 1), "status": "ОТСТАВАНИЕ"},
    ]

    result = manager._summary(children, cut, "Основные объекты",
                              "control:Основные объекты", "control")

    assert result["eac"] == pytest.approx(200.0)
    assert result["accepted"] == pytest.approx(70.0)
    assert result["actual_progress"] == pytest.approx(0.35)
    assert result["children"] == children
