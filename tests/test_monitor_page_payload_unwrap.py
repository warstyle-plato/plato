from developaid_monitor_page import MONITOR_PAGE


def test_monitor_unwraps_view_payload_before_rendering():
    assert "d.snapshot||d.view||d.report||d" in MONITOR_PAGE


def test_existing_rss_snapshot_is_opened_instead_of_stopping():
    assert "Срез уже был загружен. Открываю существующий" in MONITOR_PAGE
    assert "уже загружен" in MONITOR_PAGE
