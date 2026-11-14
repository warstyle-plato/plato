from developaid_monitor_page import MONITOR_PAGE


def test_manager_gantt_is_default_and_sources_are_explicit():
    assert "График работ по ГПР" in MONITOR_PAGE
    assert "Корпус → этап → работа" in MONITOR_PAGE
    assert "Реестр выполненных работ" in MONITOR_PAGE
    assert "Реестр платежей" in MONITOR_PAGE
    assert "Выполнено по ГПР" in MONITOR_PAGE
    assert "Корпус, этап и работа" in MONITOR_PAGE
    assert "План и прогноз окончания. Выполнение на дату" in MONITOR_PAGE


def test_gpr_tasks_show_plan_fact_and_forecast_shift():
    """Measure actual PAGE bars and dated facts, rather than a JS literal."""
    import pytest
    from playwright.sync_api import expect
    from test_monitor_cumulative_controls import browser_page
    from test_monitor_gpr_sections import monitor_view
    with browser_page(390) as (page, responses, errors):
        page.evaluate('(v)=>renderGantt(v)', monitor_view())
        work = page.locator('#gantt .lvl-task', has_text='Монтаж фасада')
        expect(work).to_contain_text('Выполнено по ГПР: 40% от 06.11.2026')
        expect(work).to_contain_text('План до 01.12.2026')
        expect(work).to_contain_text('Оценка 20.12.2026')
        plan, fact = work.locator('.planbar').bounding_box(), work.locator('.factbar').bounding_box()
        assert fact['width']/plan['width'] == pytest.approx(.4, abs=.01)
        assert work.locator('.forecastmark,.latebar').count() == 2
        zero = page.locator('#gantt .lvl-task', has_text='Внутренние работы')
        expect(zero).to_contain_text('Выполнено по ГПР: 0%')
        expect(zero).to_contain_text('Оценка неизвестна')
        assert zero.locator('.forecastmark,.latebar,.aheadbar').count() == 0
        expect(zero).not_to_contain_text('2031')
        assert not errors


def test_platon_forecast_leads_with_drivers_and_model_confidence():
    assert "Оценка срока" in MONITOR_PAGE
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
    assert "Бюджет и оплаты" in MONITOR_PAGE
    assert "payment-strip" in MONITOR_PAGE
    assert "Наведите на сегмент — дата и сумма" in MONITOR_PAGE


def test_problem_card_and_rebaseline_are_exposed():
    assert 'id="detailCard"' in MONITOR_PAGE
    assert "Что влияет на работу" in MONITOR_PAGE
    assert "Изменение утверждённого плана" in MONITOR_PAGE
    assert 'id="worksCard"' not in MONITOR_PAGE
