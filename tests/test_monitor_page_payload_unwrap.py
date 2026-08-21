from developaid_monitor_page import MONITOR_PAGE


def test_monitor_unwraps_view_payload_before_rendering():
    assert "raw.snapshot||raw.view||raw.report||raw.response||raw" in MONITOR_PAGE


def test_existing_rss_snapshot_is_opened_instead_of_stopping():
    assert "Этот срез уже сохранён — открываю существующий расчёт" in MONITOR_PAGE
    assert "уже загружен" in MONITOR_PAGE
