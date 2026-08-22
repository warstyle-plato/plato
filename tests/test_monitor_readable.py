import datetime

import developaid_monitor_readable as readable


def test_progress_gap_becomes_schedule_days_not_money_pace():
    start = datetime.date(2026, 1, 1)
    finish = datetime.date(2026, 7, 20)  # 200 days
    cut = datetime.date(2026, 5, 1)      # 120 days => plan 60%
    result = readable._progress_forecast(start, finish, cut, 0.50)
    # 50% progress is equivalent to day 100, so the task is 20 days behind.
    assert result["delta_days"] == 20
    assert result["forecast_finish"] == datetime.date(2026, 8, 9)
    assert result["status"] == "ОТСТАВАНИЕ"


def test_progress_ahead_produces_negative_delta():
    start = datetime.date(2026, 1, 1)
    finish = datetime.date(2026, 7, 20)
    cut = datetime.date(2026, 5, 1)
    result = readable._progress_forecast(start, finish, cut, 0.70)
    assert result["delta_days"] < 0
    assert result["status"] == "ОПЕРЕЖЕНИЕ"


def test_future_zero_acts_is_not_called_delay():
    result = readable._progress_forecast(
        datetime.date(2026, 10, 1),
        datetime.date(2027, 2, 1),
        datetime.date(2026, 8, 21),
        0.0,
    )
    assert result["delta_days"] == 0
    assert result["status"] == "БУДУЩАЯ ЗАДАЧА"


def test_corpus_label_uses_object_first():
    assert readable._corpus_label({"object": "Жилой корпус № 2", "section": "", "name": "Фасад"}) == "Корпус 2"
    assert readable._corpus_label({"object": "", "section": "Корпус 3", "name": "Фасад"}) == "Корпус 3"


def test_main_objects_are_split_into_corpus_blocks():
    task1 = {"level": "task", "id": "1", "wbs": "1", "object": "Корпус 1", "name": "Фасад", "plan_start": "2026-01-01", "plan_finish": "2026-06-01", "forecast_finish": "2026-06-15", "delta_days": 14}
    task2 = {"level": "task", "id": "2", "wbs": "2", "object": "Корпус 2", "name": "Фасад", "plan_start": "2026-02-01", "plan_finish": "2026-07-01", "forecast_finish": "2026-07-01", "delta_days": 0}
    rss = {"level": "rss", "key": "rss:x", "code": "2.2.2.6", "name": "Фасады", "plan_start": "2026-01-01", "plan_finish": "2026-07-01", "forecast_finish": "2026-07-01", "children": [task1, task2]}
    root = {"level": "control", "name": "Основные объекты", "children": [{"level": "detail", "name": "Надземная часть", "children": [rss]}]}
    result = readable._split_main_objects([root])
    corpuses = result[0]["children"]
    assert [item["name"] for item in corpuses] == ["Корпус 1", "Корпус 2"]
    assert corpuses[0]["children"][0]["children"][0]["shared_finance"] is True
