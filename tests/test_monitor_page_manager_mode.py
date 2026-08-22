from developaid_monitor_page import MONITOR_PAGE


def test_manager_gantt_is_readable_and_sources_are_explicit():
    assert "Управленческий Гант" in MONITOR_PAGE
    assert "Состояние работ берётся из актов РСС" in MONITOR_PAGE
    assert "Forecast строится из КС-процента" in MONITOR_PAGE
    assert "корпуса идут отдельными блоками" in MONITOR_PAGE


def test_gantt_explains_plan_fact_forecast_and_payments():
    assert "утверждённый план" in MONITOR_PAGE
    assert "КС-факт / эквивалент выполнения" in MONITOR_PAGE
    assert "просрочка forecast" in MONITOR_PAGE
    assert "опережение" in MONITOR_PAGE
    assert "факт оплаты" in MONITOR_PAGE
    assert "план оплаты" in MONITOR_PAGE
    assert "title=\"${dt(m)} · факт оплаты ${money(a)}\"" in MONITOR_PAGE


def test_finance_is_ratio_bar_not_payment_columns():
    assert 'class="fundbar"' in MONITOR_PAGE
    assert "потребность / лимит" in MONITOR_PAGE
    assert "не покрыто собственным лимитом" in MONITOR_PAGE
    assert 'lane-name">оплаты' not in MONITOR_PAGE


def test_problem_card_and_rebaseline_are_exposed():
    assert 'id="detailCard"' in MONITOR_PAGE
    assert "Утверждённый rebaseline" in MONITOR_PAGE
    assert "Предшественники" in MONITOR_PAGE
    assert "Последователи" in MONITOR_PAGE
