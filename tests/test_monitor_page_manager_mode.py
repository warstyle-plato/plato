from developaid_monitor_page import MONITOR_PAGE


def test_manager_gantt_is_default_and_sources_are_explicit():
    assert "Управленческий Гант · сроки + КС + оплаты" in MONITOR_PAGE
    assert "КС/актирование — только «Реестр выполненных работ»" in MONITOR_PAGE
    assert "Денежный факт — только «Реестр платежей»" in MONITOR_PAGE
    assert "КС/EAC не считается физическим процентом WBS" in MONITOR_PAGE


def test_works_and_payments_have_separate_lanes():
    assert 'lane-name">работы' in MONITOR_PAGE
    assert 'lane-name">оплаты' in MONITOR_PAGE
    assert "КС/EAC (только RSS-уровень)" in MONITOR_PAGE
    assert "план оплат" in MONITOR_PAGE
    assert "факт оплат" in MONITOR_PAGE


def test_problem_card_and_rebaseline_are_exposed():
    assert 'id="detailCard"' in MONITOR_PAGE
    assert "зависимости PM" in MONITOR_PAGE
    assert "Утверждённый rebaseline статьи" in MONITOR_PAGE
    assert 'id="worksCard"' not in MONITOR_PAGE
