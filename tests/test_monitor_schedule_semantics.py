from developaid_monitor_page import MONITOR_PAGE


def test_dashboard_does_not_call_cost_ratio_physical_readiness():
    assert "Физическая готовность СМР" not in MONITOR_PAGE
    assert "Актировано СМР / утв. модель" in MONITOR_PAGE
    assert "это не физический % WBS" in MONITOR_PAGE


def test_payment_ticks_live_on_their_own_lane():
    assert '<span class="lane-name">работы</span>' in MONITOR_PAGE
    assert '<span class="lane-name">оплаты</span>' in MONITOR_PAGE
    assert 'class="lane paylane"' in MONITOR_PAGE


def test_float_is_presented_only_as_wbs_metric():
    assert "lvl==='task'&&dep.current_float_days" in MONITOR_PAGE
    assert "float показывается только на WBS" in MONITOR_PAGE
