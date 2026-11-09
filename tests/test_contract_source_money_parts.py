"""Source money remains distinct from natural readiness and labelled cost halves."""
from __future__ import annotations

import pytest

import developaid_monitor_contracts as contracts
from test_contracts_from_cumulative_headers import context, parsed, provide
from test_monitor_cumulative_ledgers import book


def split_source(context, **first_changes):
    snapshot = parsed(('Example.xlsx', book(split=True)))
    first, second = snapshot['ledgers'][0]['items']
    first.update(planned_cost_split=True, planned_work_amount=400,
                 planned_material_amount=600, planned_work_amount_basis='unspecified')
    second.update(planned_cost_split=True, planned_work_amount=20,
                  planned_material_amount=0, planned_work_amount_basis='unspecified')
    first.update(first_changes)
    provide(context, snapshot)
    return contracts.build('Example', '2026-11-06')


def test_financial_source_is_complete_even_when_natural_fields_are_missing(context):
    row, = split_source(context, unit='', plan_quantity=None, completed_quantity=None)['rows']
    ref, = row['reported_performance_sources']
    assert ref['financial_complete'] and not ref['natural_complete']
    assert ref['source_complete'] is False
    assert ref['completion_ratio'] == pytest.approx(700/1020)
    assert row['physical_items'][0]['plan_quantity'] is None
    assert row['physical_items'][0]['reported_completed_quantity'] is None
    assert row['statement_progress']['state'] == 'incomparable'
    assert 'Денежные итоги ведомости известны' in row['progress']['reason']
    assert 'прочитана не полностью' not in row['progress']['reason']


def test_source_work_and_material_percentages_have_their_own_proven_denominators(context):
    row, = split_source(context)['rows']
    ref, = row['reported_performance_sources']
    assert ref['planned_works'] == 420 and ref['planned_materials'] == 600
    assert ref['completed_works'] == 200 and ref['completed_materials'] == 500
    assert ref['works_completion_ratio'] == pytest.approx(200/420)
    assert ref['materials_completion_ratio'] == pytest.approx(500/600)
    assert ref['completion_ratio'] == pytest.approx(700/1020)
    assert row['physical_items'][0]['reported_completion_ratio'] == .4


@pytest.mark.parametrize('changes', [
    {'planned_work_amount': None}, {'planned_material_amount': 601},
    {'planned_amount': None}, {'completed_amount': None},
    {'planned_work_amount_basis': 'without_vat', 'completed_amount_basis': 'with_vat'},
    {'planned_work_amount': -20, 'planned_material_amount': 1020},
])
def test_unknown_conflicting_or_unreconciled_parts_do_not_make_a_source_work_percentage(context, changes):
    row, = split_source(context, **changes)['rows']
    ref, = row['reported_performance_sources']
    assert ref['works_completion_ratio'] is None
    assert ref['materials_completion_ratio'] is None


@pytest.mark.parametrize('width', [390, 1440])
def test_visible_card_distinguishes_work_money_material_money_and_total(context, width):
    from playwright.sync_api import expect
    from test_monitor_cumulative_controls import browser_page
    view = split_source(context)
    with browser_page(width) as (page, responses, errors):
        responses.data = view
        page.locator('#contractsTab').click()
        cell = page.locator('#contractsRows td[data-label="Выполнено по накопительным"]')
        expect(cell).to_contain_text('СМР: 47,6% стоимости работ')
        expect(cell).to_contain_text('Материалы: 83,3% стоимости материалов')
        expect(cell).to_contain_text('68,6%')
        assert not errors
