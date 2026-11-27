"""A numbered construction and its numbered operations have different volumes."""
import copy
import io

from openpyxl import load_workbook
import pytest

import developaid_contract_comparison as comparison
import developaid_contract_comparison_export as export
import developaid_contract_control as control
import developaid_contract_documents as documents
import developaid_contract_fact as fact
import developaid_contract_plan as plan
import developaid_contract_schedule_links as links
import developaid_contract_rds as rds

CUT = '2026-03-05'


def source_case(*, group_volume=True):
    group = {'number': '4.1', 'name': 'Витраж учебного корпуса'}
    if group_volume:
        group.update(quantity=100.0, unit='м2', page=2)
    positions = []
    for n, name in enumerate(['Каркас', 'Узлы примыкания', 'Остекление', 'Завершающая операция'], 1):
        positions.append({'number': f'4.1.{n}', 'name': name, 'unit': 'м2', 'quantity': 100.0,
            'group': copy.deepcopy(group), 'section': 'Корпус 1', 'page': 2,
            'unit_price': {'material': 0.0, 'work': n * 10.0, 'total': n * 10.0},
            'amount': {'material': 0.0, 'work': n * 1000.0, 'total': n * 1000.0}})
    proposed = [{'index': index, 'number': p['number'], 'name': p['name'],
                 'key': links.position_key(p), 'status': 'confirmed', 'amount': p['amount']['total'],
                 'unit': p['unit'], 'quantity': p['quantity'], 'work_amount': p['amount']['work'],
                 'material_amount': 0.0, 'lines': [{'code': '4.1', 'share': 1.0}]} for index,p in enumerate(positions)]
    schedule = {'lines': [{'code': '4.1', 'name': group['name'], 'section': 'Корпус 1',
                          'start': '2026-03-01', 'finish': '2026-03-10', 'parent': None}]}
    edition = {'sha256': 'a' * 64, 'title': 'Учебное соглашение', 'date': '2026-02-01',
               'estimates': [{'positions': positions, 'links': {'positions': proposed}, 'annex': 'Расчёт',
                              'structure': [dict(group,before_position=0)]}],
               'estimate_sha256': 'b' * 64, 'schedule': schedule, 'schedule_sha256': 'c'*64, 'start': None}
    acts = [{'number': p['number'], 'name': p['name'], 'unit': p['unit'], 'quantity': 25.0 if i == 0 else 0.0,
             'quantity_material': 0.0, 'act_amount': 250.0 if i == 0 else 0.0,
             'unit_price': p['unit_price'], 'amount_components': {'material': 0.0},
             'start': '2026-03-01', 'end': CUT, 'label': 'Учебный период', 'item': i,
             'source': {'sheet': 'Учебная ведомость', 'row': i + 10}}
            for i, p in enumerate(positions)]
    found = {'acts': acts, 'unread': [], 'works': 4, 'items': [], 'physical_groups': []}
    return edition, found


def projected(*, group_volume=True, physical_groups=None):
    edition, found = source_case(group_volume=group_volume)
    found['physical_groups'] = physical_groups or []
    planned = plan.build([edition], CUT)
    performed = fact.build([edition], planned['in_force'], found, CUT)
    measured = control.build(planned, performed, None, '', CUT)
    listed = {'control': measured, 'plan': planned, 'fact': performed,
              'documents': [{'sha256': 'c'*64, 'title': 'ГПР', 'schedule': edition['schedule'], 'contract': {'number':'Т-1','date':'2026-02-01'}},
                            {'sha256': 'b'*64, 'title': 'Учебная РДС', 'estimates': edition['estimates'], 'contract': {'number':'Т-1','date':'2026-02-01'}}]}
    return comparison.build(listed, CUT), listed


def test_explicit_indexed_stages_are_not_added_to_the_physical_volume():
    view, listed = projected()
    parent, *stages = view['lines']
    assert listed['plan']['editions'][0]['lines'][0]['volume'] is None
    assert parent['physical_scope']['quantity'] == 100.0
    assert parent['physical_scope']['physical_fact'] is None
    assert parent['basis'] == 'money' and parent['planned'] == 5000.0 and parent['fact'] == 250.0
    assert [(r['display_code'], r['planned'], r['fact']) for r in stages] == [
        ('4.1.1', 50.0, 25.0), ('4.1.2', 50.0, 0.0), ('4.1.3', 50.0, 0.0), ('4.1.4', 50.0, 0.0)]
    assert all(r['parent_code'] == '4.1' and r['section'] == 'Корпус 1' for r in stages)
    assert view['coverage']['calculated'] == view['coverage']['source_works'] == 1
    assert listed['control']['total']['amount'] == 10000.0
    assert listed['control']['total']['fact'] == 250.0
    assert [r['quantity'] for r in listed['fact']['lines'][0]['position_facts']] == [25.0, 0.0, 0.0, 0.0]


@pytest.mark.parametrize('change', ['no_group', 'wrong_parent', 'mixed_buildings', 'duplicate_key'])
def test_equal_quantities_without_an_explicit_unique_indexed_parent_are_not_deduplicated(change):
    edition, _ = source_case()
    positions = edition['estimates'][0]['positions']
    if change == 'no_group':
        positions[0]['group'] = None
    elif change == 'wrong_parent':
        positions[0]['group']['number'] = '9'
    elif change == 'mixed_buildings':
        positions[0]['section'] = 'Корпус 2'
    else:
        edition['estimates'][0]['links']['positions'].append(
            copy.deepcopy(edition['estimates'][0]['links']['positions'][0]))
    row = plan.build([edition], CUT)['editions'][0]['lines'][0]
    assert 'operations' not in row
    assert row['volume']['quantity'] >= 400.0


def test_missing_parent_volume_is_not_inferred_from_equal_children_or_another_building():
    view, _ = projected(group_volume=False, physical_groups=[{
        'number': '4.1', 'section': 'Корпус 2', 'quantity': 999, 'unit': 'м2'}])
    assert view['lines'][0]['physical_scope'].get('quantity') is None
    view, _ = projected(group_volume=False, physical_groups=[{
        'number': '4.1', 'section': 'Корпус 1', 'quantity': 100, 'unit': 'м2',
        'source': {'sheet': 'Учебная КС-6а', 'row': 9}}])
    scope = view['lines'][0]['physical_scope']
    assert scope['quantity'] == 100 and scope['source_kind'] == 'ks6a'
    assert scope['source']['row'] == 9


def test_parent_quantity_and_original_operation_indices_reach_excel():
    view, listed = projected()
    cached={'ok':True,'contract_id':'c'*64,**listed,'comparison':view}
    cached['rds_comparison']=rds.build(cached)
    meta=export.bind_snapshot('Учебный',CUT,'c'*64,cached,{})
    raw = export.workbook(meta, cached['rds_comparison'], cached['rds_comparison']['rows'])
    sheet = load_workbook(io.BytesIO(raw)).active
    text = '\n'.join(str(c.value) for row in sheet for c in row if c.value is not None)
    assert sheet['B7'].comment and '100 м2' in sheet['B7'].comment.text
    assert [sheet.cell(row,1).value for row in range(8,12)]==['4.1.1','4.1.2','4.1.3','4.1.4']
    assert [sheet.cell(row,8).value for row in range(8,12)]==[25,0,0,0]
    assert '::operation:' not in text
    assert not any(c.value == 200.0 for row in sheet for c in row)


def test_new_estimate_read_keeps_the_printed_parent_quantity():
    state = {'section': 'Корпус 1', 'group': None, 'headings': {}, 'untitled': None,
             'positions': [], 'totals': []}
    rows = [['4.1', 'Учебный витраж', 'м2', '100', '', '', '', '', '', ''],
            ['4.1.1', 'Каркас', 'м2', '100', '0', '10', '10', '0', '1000', '1000']]
    documents._estimate_rows(rows, 2, state, [])
    positions = state['positions']
    assert len(positions) == 1
    assert positions[0]['group']['quantity'] == 100.0
    assert positions[0]['group']['unit'] == 'м2'


@pytest.mark.parametrize('mixed_groups', [False, True])
def test_nested_printed_operation_indices_never_promote_subgroup_area_to_the_whole(mixed_groups):
    edition, _ = source_case()
    estimate = edition['estimates'][0]
    estimate['positions'] = estimate['positions'][:2]
    for i, position in enumerate(estimate['positions'], 1):
        group = '4.1.' + str(i if mixed_groups else 1)
        position['group'].update(number=group, name='Подраздел ' + group)
        position['number'] = group + '.' + str(i)
    estimate['links']['positions'] = [
        {'key': links.position_key(p), 'status': 'confirmed', 'amount': p['amount']['total'],
         'unit': p['unit'], 'quantity': p['quantity'], 'work_amount': p['amount']['work'],
         'material_amount': 0.0, 'lines': [{'code': '4.1', 'share': 1.0}]}
        for p in estimate['positions']]
    row = plan.build([edition], CUT)['editions'][0]['lines'][0]
    assert row['volume'] is None
    assert row['operations']['group']['number'] == '4.1'
    assert row['operations']['group'].get('quantity') is None
    assert len(row['operations']['group']['nested_groups']) == (2 if mixed_groups else 1)
    assert [p['number'] for p in row['operations']['parts']] == [
        p['number'] for p in estimate['positions']]


def test_an_operation_with_unknown_total_quantity_has_no_claimed_live_overdue_days():
    edition, found = source_case()
    edition['estimates'][0]['positions'][0]['quantity'] = None
    edition['estimates'][0]['links']['positions'][0]['quantity'] = None
    cut = '2026-03-30'
    planned = plan.build([edition], cut)
    performed = fact.build([edition], planned['in_force'], found, cut)
    measured = control.build(planned, performed, None, '', cut)
    first, second = measured['lines'][0]['operations']['lines'][:2]
    assert first['state'] == 'unknown' and first['overdue_days'] is None
    assert first['forecast_finish'] is None
    assert second['state'] == 'behind' and second['overdue_days'] == 20


def test_pure_material_supply_does_not_become_an_unfinished_installation_operation():
    edition, found = source_case()
    estimate = edition['estimates'][0]
    supply = copy.deepcopy(estimate['positions'][0])
    supply.update(number='4.1.5', name='Поставка материала',
                  unit_price={'work':0.0,'material':10.0,'total':10.0},
                  amount={'work':0.0,'material':1000.0,'total':1000.0})
    estimate['positions'].append(supply)
    estimate['links']['positions'].append({'key':links.position_key(supply),'status':'confirmed',
        'amount':1000.0,'work_amount':0.0,'material_amount':1000.0,'unit':'м2','quantity':100.0,
        'lines':[{'code':'4.1','share':1.0}]})
    for act, position in zip(found['acts'], estimate['positions']):
        act.update(quantity=100.0,act_amount=position['amount']['work'])
    planned = plan.build([edition], CUT)
    performed = fact.build([edition], planned['in_force'], found, CUT)
    measured = control.build(planned, performed, None, '', CUT)
    row = measured['lines'][0]
    assert row['state'] == 'done'
    assert len(row['operations']['lines']) == 4
    assert all(part['state']=='done' for part in row['operations']['lines'])
    assert row['material_amount'] == 1000.0
    assert len(planned['editions'][0]['lines'][0]['operations']['supplies']) == 1
    assert planned['editions'][0]['total'] == 11000.0


@pytest.mark.parametrize('width', [390, 1440])
def test_native_card_and_excel_keep_the_original_stage_indices(width, tmp_path):
    from playwright.sync_api import expect
    from tests.test_contract_comparison_export import native_card
    from tests.test_contract_comparison_export_ui import _browser_export
    from tests.test_monitor_cumulative_controls import browser_page, CONTRACT, KEY
    view, listed = projected()
    cached={'ok':True,'contract_id':'c'*64,**listed,'comparison':view}
    cached['rds_comparison']=rds.build(cached)
    with browser_page(width) as (page, _, errors):
        _browser_export(page, cached, CONTRACT, KEY, [])
        rows = page.locator('#contractComparisonRows .contract-operation')
        expect(rows).to_have_count(4)
        expect(rows.nth(0)).to_contain_text('4.1.1')
        expect(rows.nth(0)).to_contain_text('50 м2')
        expect(page.locator('.contract-physical-scope')).to_contain_text('100 м2')
        assert '::operation:' not in page.locator('#contractComparisonRows').inner_text()
        page.locator('#contractComparisonSearch').fill('4.1.3')
        expect(rows).to_have_count(1)
        expect(rows).to_contain_text('Остекление')
        with page.expect_download() as got:
            page.locator('#contractGprDownload').click()
        path = tmp_path / 'selected-operation.xlsx'
        got.value.save_as(path)
        sheet = load_workbook(path)['Выполнение']
        text = '\n'.join(str(c.value) for row in sheet for c in row if c.value is not None)
        assert [sheet.cell(row,1).value for row in range(8,12)]==['4.1.1','4.1.2','4.1.3','4.1.4']
        assert '::operation:' not in text
        assert not errors
