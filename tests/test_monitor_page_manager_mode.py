from developaid_monitor_page import MONITOR_PAGE


def test_manager_gantt_is_default_and_sources_are_explicit():
    assert "Управленческий Гант" in MONITOR_PAGE
    assert "Проект → корпус/объект → этап → RSS → WBS" in MONITOR_PAGE
    assert "Реестр выполненных работ" in MONITOR_PAGE
    assert "Реестр платежей" in MONITOR_PAGE
    assert "КС/EAC" in MONITOR_PAGE
    assert "Корпус / этап / RSS-статья / WBS" in MONITOR_PAGE
    assert "План % · КС % · Forecast · Δ" in MONITOR_PAGE


def test_rss_articles_show_plan_fact_and_forecast_shift():
    assert "RSS-статья · КС/EAC proxy" in MONITOR_PAGE
    assert "план ${pct(planRatio)} · КС ${pct(ratio)}" in MONITOR_PAGE
    assert "${dt(n.plan_finish)} → ${known&&!n.forecast_partial?dt(n.forecast_finish):'—'}" in MONITOR_PAGE


def test_platon_forecast_leads_with_drivers_and_model_confidence():
    assert "Платон · управленческий прогноз" in MONITOR_PAGE
    assert 'id="forecastDrivers"' in MONITOR_PAGE
    assert 'id="forecastConfidence"' in MONITOR_PAGE
    assert "await runScenario('current_pace',true)" in MONITOR_PAGE
    assert 'class="model-warning"' in MONITOR_PAGE


def test_platon_answers_free_questions_and_still_runs_modelled_scenarios():
    """Расчётные вопросы идут в сеть, свободные — Платону (решение владельца,
    26.08.2026: «снять ограничение на формат вопроса»). Отказа «я распознаю
    три вопроса» больше нет: нераспознанное не отвергается, а отвечается."""
    assert 'id="scenarioQuestion"' in MONITOR_PAGE
    assert 'id="scenarioAsk"' in MONITOR_PAGE
    assert "function askScenarioQuestion()" in MONITOR_PAGE
    assert "runScenario('delay_wbs')" in MONITOR_PAGE
    assert "runScenario('accelerate_wbs')" in MONITOR_PAGE
    assert "три расчётных вопроса" not in MONITOR_PAGE
    assert "askMonitorPlato" in MONITOR_PAGE
    assert "/monitor/ask" in MONITOR_PAGE
    # Числа экрана уезжают в вопрос готовыми, пересчёт запрещён прямо в тексте.
    assert "не пересчитывай" in MONITOR_PAGE
    # За долгим ответом ходим по номеру запуска — соединение столько не живёт.
    assert "/agent/result/" in MONITOR_PAGE


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
