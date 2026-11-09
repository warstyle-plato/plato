"""Contract, report and Monitor read one qualified percentage and its history."""
from __future__ import annotations

import copy

import pytest
from playwright.sync_api import expect

import developaid_management_report as report
import developaid_monitor_contract_history as history
from test_contract_progress_history import calculate, register, row
from test_contract_statement_percentages import context, source_view
from test_monitor_cumulative_controls import browser_page


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
        expect(main).to_contain_text('68,6%')
        expect(main).to_contain_text('стоимости работ по ведомостям')
        expect(main).to_contain_text('Изменение: +48,6 п.п. за 31 дн.')
        main.locator('.contract-history summary').click()
        expect(main.locator('.contract-history')).to_contain_text('06.10.2026')
        expect(main.locator('.contract-history')).to_contain_text('20% стоимости работ по ведомостям')
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
         'actual_progress':.4,'pace_progress':.4,'gpr_progress':.8,
         'progress_kind':'cumulative_statement','pace_forecast_method':'cumulative_statement',
         'pace_forecast_known':False,'forecast_finish':None,
         'progress_source':{'label':'Накопительная ведомость','date':'2026-11-06','date_basis':'snapshot'}}]}}
    with browser_page(width) as (page, responses, errors):
        page.evaluate('(v)=>renderGantt(v)', view)
        gantt = page.locator('#gantt')
        expect(gantt).to_contain_text('По ведомости: 40% от 06.11.2026')
        assert '80%' not in gantt.inner_text()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert not errors
