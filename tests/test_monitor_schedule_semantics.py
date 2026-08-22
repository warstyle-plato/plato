from developaid_monitor_page import MONITOR_PAGE


def test_dashboard_uses_ks_as_progress_proxy_not_fake_physical_readiness():
    assert "Физическая готовность СМР" not in MONITOR_PAGE
    assert "КС / утв. модель" in MONITOR_PAGE
    assert "КС-факт / эквивалент выполнения" in MONITOR_PAGE


def test_payments_are_hoverable_points_not_vertical_columns():
    assert 'class="paydot fact"' in MONITOR_PAGE
    assert 'class="paydot plan"' in MONITOR_PAGE
    assert "факт оплаты ${money(a)}" in MONITOR_PAGE
    assert "план оплаты ${money(a)}" in MONITOR_PAGE
    assert 'lane-name">оплаты' not in MONITOR_PAGE


def test_float_stays_in_wbs_detail_context():
    assert "dep.current_float_days" in MONITOR_PAGE
    assert "влияние на РНВ" in MONITOR_PAGE
