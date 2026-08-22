from developaid_monitor_page import MONITOR_PAGE


def test_manager_gantt_is_default_and_sources_are_explicit():
    assert "Управленческий Гант" in MONITOR_PAGE
    assert "Проект → корпус/объект → этап → WBS" in MONITOR_PAGE
    assert "Реестр выполненных работ" in MONITOR_PAGE
    assert "Реестр платежей" in MONITOR_PAGE
    assert "КС/EAC" in MONITOR_PAGE
    assert "Корпус / этап / RSS-статья / WBS" in MONITOR_PAGE
    assert "План % · КС % · Forecast · Δ" in MONITOR_PAGE


def test_rss_articles_show_plan_fact_and_forecast_shift():
    assert "RSS-статья · КС/EAC proxy" in MONITOR_PAGE
    assert "план ${pct(planRatio)} · КС ${pct(ratio)}" in MONITOR_PAGE
    assert "${dt(n.plan_finish)} → ${ff!=null?dt(n.forecast_finish):'—'}" in MONITOR_PAGE


def test_payments_are_removed_from_gantt_and_live_in_cost_control():
    assert 'lane-name">оплаты' not in MONITOR_PAGE
    assert 'class="lane paylane"' not in MONITOR_PAGE
    assert "Cost control" in MONITOR_PAGE
    assert "payment-strip" in MONITOR_PAGE
    assert "Наведите на сегмент — дата и сумма" in MONITOR_PAGE


def test_problem_card_and_rebaseline_are_exposed():
    assert 'id="detailCard"' in MONITOR_PAGE
    assert "Что влияет на работу" in MONITOR_PAGE
    assert "Утверждённый rebaseline" in MONITOR_PAGE
    assert 'id="worksCard"' not in MONITOR_PAGE
