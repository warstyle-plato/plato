from developaid_monitor_page import MONITOR_PAGE


def test_dashboard_does_not_call_cost_ratio_physical_readiness():
    assert "Физическая готовность СМР" not in MONITOR_PAGE
    assert "КС / EAC proxy" in MONITOR_PAGE
    assert "proxy темпа" in MONITOR_PAGE


def test_payment_ticks_are_not_drawn_on_gantt():
    assert '<span class="lane-name">оплаты</span>' not in MONITOR_PAGE
    assert 'class="lane paylane"' not in MONITOR_PAGE
    assert "Cost control" in MONITOR_PAGE
    assert "payment-strip" in MONITOR_PAGE


def test_dependencies_are_kept_in_wbs_detail():
    assert "Что влияет на работу" in MONITOR_PAGE
    assert "На что влияет работа" in MONITOR_PAGE
    assert "dep.predecessors" in MONITOR_PAGE
    assert "dep.successors" in MONITOR_PAGE
