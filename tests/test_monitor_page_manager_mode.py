from developaid_monitor_page import MONITOR_PAGE


def test_manager_gantt_is_default_and_sources_are_explicit():
    assert "Управленческий Гант · работы + оплаты" in MONITOR_PAGE
    assert "Физический факт — только «Реестр выполненных работ»" in MONITOR_PAGE
    assert "Денежный факт — только «Реестр платежей»" in MONITOR_PAGE
    assert "По умолчанию только крупные статьи" in MONITOR_PAGE


def test_problem_card_and_rebaseline_are_exposed():
    assert 'id="detailCard"' in MONITOR_PAGE
    assert "зависимости PM" in MONITOR_PAGE
    assert "Утверждённый rebaseline статьи" in MONITOR_PAGE
    assert 'id="worksCard"' not in MONITOR_PAGE
