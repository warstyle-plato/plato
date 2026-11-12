"""Contract, report and Monitor read one qualified percentage and its history."""
from __future__ import annotations

import copy

import pytest
from playwright.sync_api import expect

import developaid_management_report as report
import developaid_monitor_contract_links as contract_links
import developaid_monitor_contract_history as history
from contract_rows import opened
from test_contract_progress_history import calculate, register, row
from test_contract_statement_percentages import context, source_view
from browser import expand_gantt
from test_monitor_cumulative_controls import browser_page


UNION_REASON = 'План одной работы различается между ведомостями; общий процент не выбран.'


def source_link():
    return {'id': 'a'*64, 'contractor': 'ООО Учебный исполнитель', 'contract': 'А-12',
            'amount': None, 'completed': None, 'completion_ratio': None,
            'progress': {'ratio': None, 'state': 'incomparable', 'reason': UNION_REASON},
            'statement_progress': {'ratio': None, 'state': 'incomparable', 'why': UNION_REASON},
            'reported_performance_sources': [
                {'amount_scope': 'statement', 'period_year': 2025, 'completion_ratio': 0,
                 'future_periods_excluded': False, 'monetary_comparable': True},
                {'amount_scope': 'statement', 'period_year': 2026, 'completion_ratio': .75,
                 'future_periods_excluded': False, 'monetary_comparable': True}],
            'observation_forecast': {'scope': 'uploaded_statements', 'eligible': False,
                                     'state': 'current_unknown', 'reason': UNION_REASON},
            'risk': {'status': 'unknown', 'label': 'Прогноз не рассчитан'}}


def test_unknown_union_preserves_known_year_percentages_and_its_real_reason():
    link = source_link()
    before = copy.deepcopy(link)
    text = report._work_contract_progress(link)
    assert '2025 — 0,0%' in text and '2026 — 75,0%' in text
    assert UNION_REASON in text
    assert 'суммы договора' not in text and 'нет полной суммы' not in text
    assert UNION_REASON in report._work_contract_forecast(link)
    assert 'нет полной суммы' not in report._work_contract_forecast(link)
    assert link == before


def test_unknown_canonical_observation_blocks_a_stale_legacy_ratio():
    link = source_link()
    link['completion_ratio'] = .9
    assert '90,0%' not in report._work_contract_progress(link)
    assert UNION_REASON in report._work_contract_progress(link)


def test_unknown_union_works_before_history_enrichment():
    link = source_link()
    link.pop('progress')
    assert UNION_REASON in report._work_contract_progress(link)
    assert '75,0%' in report._work_contract_progress(link)
    link['statement_progress'].update(state='known', ratio=.6, basis_label='стоимости работ по ведомостям')
    assert report._work_contract_progress(link) == '60,0% стоимости работ по ведомостям'


@pytest.mark.parametrize('change', [
    {'future_periods_excluded': True}, {'future_periods_excluded': None},
    {'monetary_comparable': False}, {'amount_scope': 'whole_contract'},
    {'completion_ratio': None}, {'completion_ratio': True}, {'completion_ratio': float('nan')},
])
def test_unqualified_source_percentage_is_not_promoted_to_known(change):
    link = source_link()
    link['reported_performance_sources'] = [dict(link['reported_performance_sources'][1], **change)]
    text = report._work_contract_progress(link)
    assert '75,0%' not in text and UNION_REASON in text


def test_multiple_sources_in_the_same_year_remain_distinguishable():
    link = source_link()
    link['reported_performance_sources'][1]['period_year'] = 2025
    text = report._work_contract_progress(link)
    assert '2025, ведомость 1 — 0,0%' in text
    assert '2025, ведомость 2 — 75,0%' in text


def test_report_link_retains_canonical_source_evidence_and_forecast():
    record = source_link()
    record['reconciliation'] = {'daily_evidence': [{
        'id': 'message', 'date': '2026-11-06', 'text': 'Монтаж',
        'contractor': record['contractor'], 'match_status': 'confirmed',
        'contract_id': record['id'], 'link_basis': 'exact_party', 'scope_confirmed': False}]}
    context = {'register': {'rows': [record]}}
    groups = [{'contractor': record['contractor'], 'lines': [{'line': 'Монтаж', 'days': ['2026-11-06']}]}]
    original = copy.deepcopy((record, groups))
    linked = contract_links.enrich_report_works('Example', groups, '2026-11-01', '2026-11-06', context=context)
    link, = linked[0]['lines'][0]['contract_links']
    for key in ('progress', 'statement_progress', 'reported_performance_sources', 'observation_forecast'):
        assert link[key] == record[key] and link[key] is not record[key]
    assert link['scope_note'] == 'Договор определён; корпусный состав сообщений требует уточнения.'
    assert (record, groups) == original
    markup = report._works_html({'state': 'ok', 'works': linked}, 'week')
    text = report._work_contract_text(linked[0]['lines'][0])
    for output in (markup, text):
        assert '2026 — 75,0%' in output and UNION_REASON in output
        assert 'нет полной суммы' not in output
        assert 'всему договору' not in output
        assert 'Материалы включены' not in output


def test_closing_summary_report_footer_does_not_expand_its_source_scope():
    link = {'label': 'Договор А-12', 'source_kind': 'closing_summary',
            'progress': {'ratio': .5, 'basis_label': 'суммы КС-2 по сводной',
                         'origin': 'dated_closing_summary'}, 'risk': {}}
    groups = [{'contractor': 'Учебный исполнитель', 'lines': [
        {'line': 'Монтаж', 'days': ['2026-11-06'], 'contract_links': [link]}]}]
    markup = report._works_html({'state': 'ok', 'works': groups}, 'week')
    assert '50,0% суммы КС-2 по сводной' in markup
    assert 'всему договору' not in markup and 'Материалы включены' not in markup


def test_source_forecast_uses_canonical_money_scope_and_dated_risk_keeps_priority():
    link = source_link()
    link['progress'].update(ratio=.5, origin='cumulative_statement', state='known')
    link['observation_forecast'].update(eligible=True, forecast_finish='2026-12-11')
    text = report._work_contract_forecast(link)
    assert text == 'Ориентир 100% стоимости ведомостей: 11.12.2026. По снимкам.'
    assert 'Окончание' not in text
    link['risk'].update(forecast_finish='2026-11-29', delay_days=28)
    assert report._work_contract_forecast(link) == 'Окончание 29.11.2026. Задержка 28 дн.'


def test_known_dated_contract_does_not_use_an_inapplicable_snapshot_forecast_reason():
    link = source_link()
    link.update(amount=1000, completed=500, completion_ratio=.5)
    link['progress'].update(ratio=.5, origin='dated_cumulative', state='known')
    link['observation_forecast'].update(state='not_statement_observation', reason='Не наблюдение ведомостей.')
    link['risk'].update(reason='В последних периодах нет положительного выполнения.')
    assert report._work_contract_forecast(link) == 'Прогноз неизвестен: в последних периодах нет выполнения'


def test_closing_summary_money_never_becomes_cumulative_or_physical_completion():
    link = {'source_kind': 'closing_summary', 'completion_ratio': .5,
            'progress': {'ratio': .5, 'basis': 'closing_summary_contract',
                         'origin': 'dated_closing_summary', 'basis_label': 'суммы КС-2 по сводной'},
            'risk': {'status': 'done'}}
    assert report._work_contract_progress(link) == '50,0% суммы КС-2 по сводной'
    assert report._work_contract_forecast(link) == 'Закрыто по КС-2 из сводной'
    link['risk'] = {'forecast_finish': '2026-12-01'}
    assert 'Прогноз закрытия по сводной: 01.12.2026' in report._work_contract_forecast(link)
    assert 'Окончание' not in report._work_contract_forecast(link)


@pytest.mark.parametrize('width', [390, 1440])
@pytest.mark.parametrize('mode', ['unknown', 'source_forecast', 'closing_summary'])
def test_monitor_forecast_reuses_canonical_reason_and_source_scope(context, width, mode):
    current = source_view(context)
    record = current['rows'][0]
    record.update(source_link())
    if mode == 'source_forecast':
        record['progress'].update(ratio=.5, state='known', origin='cumulative_statement')
        record['statement_progress'].update(state='known', ratio=.5, planned=1000, completed=500)
        record['observation_forecast'].update(eligible=True, forecast_finish='2026-12-11')
    elif mode == 'closing_summary':
        record.update(source_kind='closing_summary', reported_performance_sources=[])
        record['progress'].update(ratio=.5, state='known', origin='dated_closing_summary')
        record['risk'].update(forecast_finish='2026-12-01')
    with browser_page(width) as (page, responses, errors):
        responses.data = current
        page.locator('#contractsTab').click()
        # The forecast lives in the row's detail; neither the row nor the detail says the stale reason.
        main = page.locator('tr[data-contract-id]').first
        more = opened(page)
        if mode == 'unknown':
            expect(more).to_contain_text(UNION_REASON)
        elif mode == 'source_forecast':
            expect(more).to_contain_text('Ориентир 100% стоимости ведомостей: 11.12.2026. По снимкам.')
        else:
            expect(more).to_contain_text('Прогноз закрытия по сводной: 01.12.2026')
            assert 'Прогноз окончания: 01.12.2026' not in main.inner_text() + more.inner_text()
        assert 'Для прогноза нужна полная сумма договора.' not in main.inner_text() + more.inner_text()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert not errors


@pytest.mark.parametrize('width', [390, 1440])
def test_real_register_shows_canonical_change_and_source_percentage(context, width, monkeypatch):
    current = source_view(context)
    previous = copy.deepcopy(current)
    previous.update(source_date='2026-10-06')
    previous['snapshots'].update(cumulative='2026-10-06', cumulative_id='2026-10-06-'+'b'*64)
    for item in previous['rows'][0]['reported_performance_sources']:
        item.update(completion_ratio=.2, completed=204)
    prior_row = previous['rows'][0]
    prior_row['source_date'] = '2026-10-06'
    prior_row['physical_items'][0]['reported_completed_amount'] = 204
    from developaid_monitor_statement_union import statement_union
    prior_row['statement_progress'] = statement_union(prior_row)
    current['snapshots']['cumulative_id'] = '2026-11-06-'+'a'*64
    monkeypatch.setattr(history.ledgers, 'list_snapshots', lambda _: [
        {'taken_at':'2026-10-06', 'snapshot_id':previous['snapshots']['cumulative_id']},
        {'taken_at':'2026-11-06', 'snapshot_id':current['snapshots']['cumulative_id']}])
    view = history.enrich('Example', '2026-11-08', current, build_register=lambda _: previous)
    progress = view['rows'][0]['progress']
    assert progress['ratio'] == view['rows'][0]['reported_performance_sources'][0]['completion_ratio']
    assert progress['comparison_state'] == 'comparable'
    with browser_page(width) as (page, responses, errors):
        responses.data = view
        page.locator('#contractsTab').click()
        main = page.locator('tr[data-contract-id]').first
        expect(main.locator('.contract-money')).to_contain_text('68,6%')
        more = opened(page)
        expect(more).to_contain_text('68,6%')
        expect(more).to_contain_text('стоимости работ по ведомостям')
        expect(more).to_contain_text('Изменение: +48,6 п.п. за 31 дн.')
        more.locator('.contract-history summary').click()
        expect(more.locator('.contract-history')).to_contain_text('06.10.2026')
        expect(more.locator('.contract-history')).to_contain_text('20% стоимости работ по ведомостям')
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert not errors


def test_report_reuses_known_statement_percentage_and_change(monkeypatch):
    previous = register('2026-10-06', [row(ratio=.2, completed=200)], 'b')
    enriched, _ = calculate(monkeypatch, previous={'2026-10-06': previous})
    progress = enriched['rows'][0]['progress']
    link = {'completion_ratio':None, 'amount':None, 'completed':None, 'progress':progress}
    text = report._work_contract_progress(link)
    assert '40,0%' in text and 'стоимости ведомости' in text and '+20,0 п.п.' in text
    assert 'неизвестна' not in text
    assert 'нет полной суммы' not in report._work_contract_forecast(link)


@pytest.mark.parametrize('width', [390, 1440])
def test_monitor_gpr_shows_statement_observation_not_manual_gpr_percentage(width):
    view = {'cut':'2026-11-06', 'schedule':{'management':[
        {'level':'task','key':'task:1','id':'1','wbs':'1','name':'Монтаж', 'object':'Корпус 1',
         'plan_start':'2026-09-01','plan_finish':'2026-12-01',
         'actual_progress':.4,'pace_progress':.4,'gpr_progress':.8,'gpr_progress_date':'2026-11-04',
         'progress_kind':'cumulative_statement','pace_forecast_method':'cumulative_statement',
         'pace_forecast_known':False,'forecast_finish':None,
         'progress_source':{'label':'Накопительная ведомость','date':'2026-11-06','date_basis':'snapshot'}}]}}
    with browser_page(width) as (page, responses, errors):
        page.evaluate('(v)=>renderGantt(v)', view)
        expand_gantt(page)
        gantt = page.locator('#gantt')
        expect(gantt).to_contain_text('По ведомости: 40% от 06.11.2026')
        # Current owner brief keeps both facts; the source-qualified statement
        # remains the primary fill and never inherits the separate GPR value.
        work = gantt.locator('.lvl-task')
        expect(work.locator('.work-progress')).to_contain_text('ГПР: 80% от 04.11.2026')
        expect(work.locator('.work-progress')).to_contain_text('Накопительная ведомость')
        expect(work.locator('.factbar')).to_have_attribute('title','По ведомости: 40%')
        plan, fact = work.locator('.planbar').bounding_box(), work.locator('.factbar').bounding_box()
        assert fact['width']/plan['width'] == pytest.approx(.4, abs=.01)
        assert work.locator('.forecastmark,.latebar,.aheadbar').count() == 0
        expect(work).to_contain_text('Оценка неизвестна')
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert not errors
