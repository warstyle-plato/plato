"""Only exact copies excluded by both printed totals leave source aggregation."""
from __future__ import annotations

import copy
import io
import json

import openpyxl
import pytest
from playwright.sync_api import expect

import developaid_cumulative_progress as progress
import developaid_monitor_contracts as contracts
import developaid_monitor_ledgers as ledgers
import developaid_schedule_gpr_physical as gpr
import developaid_schedule_physical as physical
from test_contracts_from_cumulative_headers import context, provide
from test_ledger_merged_cost_fields import add_caches
from test_monitor_cumulative_controls import browser_page
from test_monitor_cumulative_ledgers import archive, book


def duplicate_book(*, mismatch=None, fact_range='9:10', plan_formula=True):
    wb = openpyxl.load_workbook(io.BytesIO(book()))
    ws = wb.active
    ws.delete_rows(11)
    for row in (9, 10):
        ws.append([cell.value for cell in ws[row]])
    if mismatch:
        ws[mismatch[0]] = mismatch[1]
    ws['C13'] = 'ИТОГО'
    ws['G13'] = '=SUM(G9:G10)' if plan_formula else 1020
    first, last = fact_range.split(':')
    ws['O13'] = f'=SUM(O{first}:O{last})'
    out = io.BytesIO()
    wb.save(out)
    return add_caches(out.getvalue(), {'G13': 1020, 'O13': 400})


def snapshot(**options):
    source = ledgers.parse_archive(archive([('Example.xlsx', duplicate_book(**options))]))
    source.update(taken_at='2026-11-06', snapshot_id='2026-11-06-'+'a'*64)
    return source


def test_both_grand_totals_prove_copies_without_deleting_source_rows():
    source = snapshot()
    ledger, = source['ledgers']
    items = ledger['items']
    assert len(items) == 4 and ledger['duplicate_rows_count'] == 2
    assert [(row['source']['row'], row['duplicate_of']['row'])
            for row in items if row.get('is_duplicate')] == [(11, 9), (12, 10)]
    assert sum(item['planned_amount'] for item in ledgers.aggregation_members(items)) == 1020
    assert sum(item['completed_amount'] for item in ledgers.aggregation_members(items)) == 400
    assert items[2]['plan_quantity'] == items[0]['plan_quantity'] == 10
    assert items[2]['completed_quantity'] == items[0]['completed_quantity'] == 4
    assert items[2]['duplicate_proof']['plan']['formula'] == '=SUM(G9:G10)'
    assert items[2]['duplicate_proof']['completed'][0]['formula'] == '=SUM(O9:O10)'


@pytest.mark.parametrize('options', [
    {'plan_formula': False}, {'fact_range': '9:11'},
    {'mismatch': ('C11', 'Другая работа')}, {'mismatch': ('D11', 'шт')},
    {'mismatch': ('E11', 11)}, {'mismatch': ('G11', 1001)},
    {'mismatch': ('H11', 3)}, {'mismatch': ('N11', 5)}, {'mismatch': ('O11', 500)},
])
def test_a_flag_is_not_inferred_from_equal_names_or_an_incomplete_total_proof(options):
    ledger, = snapshot(**options)['ledgers']
    assert not ledger['duplicate_rows_count']
    assert len(ledgers.aggregation_members(ledger['items'])) == 4


@pytest.mark.parametrize('change', [
    lambda x: x.update(name='Другая работа'), lambda x: x.update(scope='Корпус 2'),
    lambda x: x.update(unit='шт'), lambda x: x.update(period_year=2027),
    lambda x: x.update(planned_amount=999), lambda x: x.update(completed_quantity=9),
    lambda x: x['source'].update(filename='Other.xlsx'),
    lambda x: x['source'].update(sheet='Другой лист'),
    lambda x: x['periods'][0].update(quantity=9),
    lambda x: x['duplicate_proof']['completed'][0].update(formula='=SUM(O9:O11)'),
    lambda x: x['duplicate_proof'].update(source_fingerprint='b'*64),
    lambda x: x.update(duplicate_of={'filename': 'Example.xlsx', 'sheet': 'Работы', 'row': 10, 'period_year': 2026}),
])
def test_every_consumer_rechecks_copy_and_scope_instead_of_trusting_the_flag(change):
    ledger, = snapshot()['ledgers']
    duplicate = ledger['items'][2]
    change(duplicate)
    retained = ledgers.aggregation_members(ledger['items'])
    assert any(item is duplicate for item in retained)


def test_forged_flag_and_both_mutated_copies_are_not_silently_excluded():
    ledger, = snapshot()['ledgers']
    first, _, duplicate, _ = ledger['items']
    first.update(completed_quantity=8)
    duplicate.update(completed_quantity=8)
    assert any(item is duplicate for item in ledgers.aggregation_members(ledger['items']))
    duplicate.pop('duplicate_proof')
    assert any(item is duplicate for item in ledgers.aggregation_members(ledger['items']))


def test_contract_references_and_union_keep_ids_and_count_source_money_once(context):
    source = snapshot()
    provide(context, source)
    view = contracts.build('Example', '2026-11-06')
    row, = view['rows']
    reference, = row['reported_performance_sources']
    assert reference['planned'] == 1020 and reference['completed'] == 400
    assert reference['completion_ratio'] == pytest.approx(400/1020)
    assert len(row['physical_items']) == 4
    assert row['statement_progress']['duplicate_count'] == 2
    assert row['statement_progress']['planned'] == 1020
    assert row['statement_progress']['completed'] == 400
    assert [item['source']['row'] for item in row['physical_items']] == [9, 10, 11, 12]


def test_quantity_views_and_manual_duplicate_binding_never_redirect_or_create_zero_progress():
    source = snapshot()
    before = copy.deepcopy(source)
    items = physical._items(source)
    views = progress.quantity_views(source, '2026-11-06')
    assert set(items) == set(views) == {'0:0', '0:1', '0:2', '0:3'}
    assert views['0:2']['is_duplicate'] and views['0:2']['position_key'] is None
    assert len(ledgers.aggregation_members(list(views.values()))) == 2
    component = {'component_id': 'wall', 'task_id': '1', 'item_ids': ['0:2']}
    result = physical._component(component, items, physical._day('2026-11-06'))
    assert result['progress'] is None and not result['known']
    assert result['excluded_duplicate_item_ids'] == ['0:2'] and result['requires_reconciliation']
    assert gpr._observed_component(component, result, items, views, source, '2026-11-06', []) == result
    assert component['item_ids'] == ['0:2'] and source == before
    members = [dict(views[key], member_key=key, progress=views[key]['completion_ratio']) for key in ('0:0', '0:2')]
    aggregate = progress.aggregate_quantities(members)
    assert aggregate['members'] == 1 and aggregate['excluded_duplicates'] == 1
    assert aggregate['ratio'] == .4
    detached = progress.aggregate_quantities([members[1]])
    assert detached['ratio'] is None and detached['requires_reconciliation']


def test_reparse_preserves_old_duplicate_ids_and_saved_bytes(context):
    ledgers.store_archive('Example', archive([('Example.xlsx', duplicate_book())]), '2026-11-06', 'KS.zip')
    path, = ledgers._root('Example').glob('*.json')
    stored = json.loads(path.read_text())
    stored['parser_schema'] = 4
    for item in stored['ledgers'][0]['items']:
        for key in list(item):
            if key.startswith('duplicate_') or key == 'is_duplicate':
                item.pop(key)
    path.write_text(json.dumps(stored))
    original = path.read_bytes()
    fresh = ledgers.read_snapshot('Example', stored['snapshot_id'])
    items = physical._items(fresh)
    assert items['0:2']['source']['row'] == 11 and items['0:2']['is_duplicate']
    assert items['0:2']['duplicate_of']['row'] == 9
    assert path.read_bytes() == original


@pytest.mark.parametrize('width', [390, 1440])
def test_real_monitor_keeps_duplicate_trace_without_an_extra_work_percentage(context, width):
    source = snapshot()
    provide(context, source)
    view = contracts.build('Example', '2026-11-06')
    with browser_page(width) as (page, responses, errors):
        responses.data = view
        page.locator('#contractsTab').click()
        page.locator('.contract-open').click()
        expect(page.locator('.physical-main')).to_have_count(2)
        expect(page.locator('.physical-duplicate')).to_have_count(2)
        expect(page.locator('.physical-duplicate').first).to_contain_text('Дубликат исходника, повторно не учтён')
        assert '%' not in page.locator('.physical-duplicate').first.inner_text()
        assert not errors
