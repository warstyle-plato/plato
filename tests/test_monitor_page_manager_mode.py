from developaid_monitor_page import MONITOR_PAGE


def test_manager_gantt_is_default_and_sources_are_explicit():
    assert "Управленческий Гант · работы + оплаты" in MONITOR_PAGE
    assert "Физический факт — только «Реестр выполненных работ»" in MONITOR_PAGE
    assert "Денежный факт — только «Реестр платежей»" in MONITOR_PAGE
    assert "DevelopAid → RSS → WBS" in MONITOR_PAGE


def test_old_flat_works_table_is_not_the_primary_view_anymore():
    assert 'id="worksCard"' not in MONITOR_PAGE
    assert "Сортировка идёт по номеру RSS-статьи" in MONITOR_PAGE
