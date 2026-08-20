import developaid_monitor_manager as manager


def test_payment_and_work_sources_are_not_same_metric():
    # These are intentionally separate axes in the manager view.
    assert manager._control("2.2.1.4") == "Основные объекты"
    assert "Реестр выполненных работ" in manager.__doc__
    assert "Реестр платежей" in manager.__doc__
