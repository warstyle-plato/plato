import developaid_monitor_manager as manager


def test_payment_and_schedule_axes_are_not_same_metric():
    assert manager._financial_control("2.2.1.4") == "Основные объекты"
    assert "cost/evidence" in manager.__doc__
    assert "Calendar forecast never extrapolates dates from the monetary pace" in manager.__doc__


def test_rss_code_does_not_define_temporal_phase():
    prep = manager._schedule_bucket({"wbs": "1.16.1.2.1", "name": "Подготовка"}, "2.1")
    pos = manager._schedule_bucket({"wbs": "1.16.1.3.1", "name": "Работы ПОС"}, "2.1")
    assert prep[0] == "Подготовка"
    assert pos[0] == "Организация стройплощадки / ПОС"
