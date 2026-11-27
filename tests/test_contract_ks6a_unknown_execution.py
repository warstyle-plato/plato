"""An unread KS-6a position is unknown, while independent known facts survive."""
import copy

import pytest

import developaid_contract_comparison as comparison
import developaid_contract_control as control
import developaid_contract_fact as fact
import developaid_contract_plan as plan
import developaid_contract_schedule_links as links
from tests.test_contract_ks6a_primary_fact import CUT, EDITION, POSITION


def two_lines():
    edition = copy.deepcopy(EDITION)
    position = dict(copy.deepcopy(POSITION), number='2', name='Вторая работа')
    estimate = edition['estimates'][0]
    estimate['positions'].append(position)
    estimate['links']['positions'].append(dict(copy.deepcopy(estimate['links']['positions'][0]),
        key=links.position_key(position), lines=[{'code': '2', 'share': 1}]))
    edition['schedule']['lines'].append(dict(edition['schedule']['lines'][0], code='2', name='Вторая работа'))
    return edition


def unread(*, number='1', movements=(15,), total=None, material_only=False, split=True):
    return {'position': number, 'name': 'Монтаж' if number == '1' else 'Вторая работа', 'unit': 'м2',
        'plan_quantity': 100, 'completed_quantity': None,
        'reported_completed_quantity': sum(movements) if total is None else total,
        'quantity_basis': 'Периоды выполнения без дат.', 'periods': [],
        'undated_periods': [{'label': f'КС-2 № {i+1}', 'quantity': None if material_only else value,
            'material_quantity': 5 if material_only else 0, 'amount': 500 if material_only else value*100,
            'work_amount': 0 if material_only else value*100, 'amount_split': split,
            'material_amount': 500 if material_only else 0} for i, value in enumerate(movements)]}


def known(number='2', quantity=0):
    return {'position': number, 'name': 'Вторая работа', 'unit': 'м2', 'plan_quantity': 100,
        'completed_quantity': quantity, 'periods': [{'label': 'январь', 'date_start': '2026-01-01',
            'date_end': '2026-01-28', 'quantity': quantity, 'amount': quantity*100}]
        if quantity else []}


def calculate(*items, edition=None):
    edition = edition or two_lines()
    found = fact.acts({'physical_items': list(items)})
    measured = fact.build([edition], edition['sha256'], found, CUT)
    planned = plan.build([edition], CUT)
    observed = control.build(planned, measured, None, '', CUT)
    return measured, observed, planned


@pytest.mark.parametrize('known_quantity', [0, 10])
def test_unknown_work_is_not_zero_even_with_another_known_work(known_quantity):
    measured, observed, planned = calculate(unread(), known(quantity=known_quantity))
    assert measured['total'] is None and measured['known_total'] == known_quantity*100
    rows = {row['code']: row for row in observed['lines']}
    assert rows['1']['state'] == 'unknown' and rows['1']['readiness'] is None
    assert rows['1']['volume']['fact'] is None and rows['1']['plan_done'] is None
    assert rows['1']['forecast_finish'] is None and rows['1']['overdue_days'] is None
    assert rows['2']['readiness'] == pytest.approx(known_quantity/100)
    assert observed['total'] is None and observed['forecast'] is None
    result = comparison.build({'control': observed, 'fact': measured, 'plan': planned, 'documents': []}, CUT)
    unknown = next(row for row in result['lines'] if row['code'] == '1')
    assert unknown['state'] == 'unknown' and unknown['fact'] is None and unknown['planned'] is not None
    if measured['months']:
        assert measured['months'][0]['fact'] is None
        assert measured['months'][0]['known_fact'] == known_quantity*100


def test_unknown_part_of_the_same_position_does_not_become_a_partial_percentage():
    first = known(number='1', quantity=5)
    first['name'] = 'Монтаж'
    measured, observed, _ = calculate(first, unread(), edition=copy.deepcopy(EDITION))
    assert measured['known_total'] == 500 and measured['total'] is None
    row, = observed['lines']
    assert row['state'] == 'unknown' and row['readiness'] is None and row['volume']['fact'] is None
    part, = measured['lines'][0]['position_facts']
    assert part['quantity'] is None and part['known_quantity'] == 5


def test_uncertainty_follows_all_nonzero_shares_without_marking_foreign_work_unknown():
    edition = two_lines()
    estimate = edition['estimates'][0]
    estimate['links']['positions'][0]['lines'] = [{'code': '1', 'share': .4}, {'code': '2', 'share': .6}]
    measured, observed, _ = calculate(unread(), known(quantity=10), edition=edition)
    assert {row['state'] for row in observed['lines']} == {'unknown'}
    foreign = unread(number='99')
    foreign['name'] = 'Чужая работа'
    measured, observed, _ = calculate(foreign, known(quantity=10))
    rows = {row['code']: row for row in observed['lines']}
    assert rows['2']['readiness'] == .1 and measured['total'] == 1000


def test_true_zero_without_unread_remains_zero():
    measured, observed, _ = calculate(known(number='1'), known())
    assert measured['total'] == 0 and observed['total']['readiness'] == 0


@pytest.mark.parametrize('split', [True, False])
def test_only_explicit_zero_work_component_can_remain_zero_with_undated_material(split):
    measured, observed, _ = calculate(unread(movements=(0,), total=0, material_only=True, split=split), known())
    first = next(row for row in observed['lines'] if row['code'] == '1')
    assert first['readiness'] == (0 if split else None)


def test_cancelling_undated_movements_do_not_prove_zero_execution_at_cut():
    measured, observed, _ = calculate(unread(movements=(15, -15), total=0), known())
    first = next(row for row in observed['lines'] if row['code'] == '1')
    assert measured['total'] is None and first['readiness'] is None


def test_original_pricing_fixture_matching_unread_keeps_only_the_known_subtotal(card):
    import developaid_contract_files as files
    from tests.test_contract_card_confirms_and_chooses_links import CONTRACT
    from tests.test_contract_fact_prices_ks_by_the_edition import REGISTER_ROW
    row = copy.deepcopy(REGISTER_ROW)
    row['physical_items'][-1].update(position='1.2', name='Устройство плит перекрытия')
    listed = files.listing('Учебный', CONTRACT, '2026-02-04', fact.acts(row))
    assert listed['fact']['total'] is None and listed['fact']['known_total'] == 5500
    measured = {line['code']: line for line in listed['fact']['lines']}
    assert measured['1.1']['fact'] == 1500 and measured['1.2']['fact'] == 2500
    assert measured['1.3']['fact'] is None and measured['1.3']['known_fact'] == 1500
    uncertain = next(line for line in listed['control']['lines'] if line['code'] == '1.3')
    assert uncertain['readiness'] is None and uncertain['volume']['fact'] is None
    assert listed['control']['total'] is None


def test_unknown_indexed_operation_preserves_known_operations_and_exports_blank_fact():
    import io
    from openpyxl import load_workbook
    import developaid_contract_comparison_export as export
    import developaid_contract_rds as rds
    from tests.test_contract_indexed_operations import source_case, CUT as operation_cut
    edition, found = source_case()
    missing = found['acts'].pop(1)
    found['unread'] = [{'number': missing['number'], 'name': missing['name'], 'unit': 'м2',
        'item': 1, 'reported_quantity': 15, 'plan_quantity': 100,
        'reason': 'Период без даты.', 'periods': [{'label': 'КС-2 № 5', 'quantity': 15, 'amount': 300}]}]
    planned = plan.build([edition], operation_cut)
    measured = fact.build([edition], planned['in_force'], found, operation_cut)
    observed = control.build(planned, measured, None, '', operation_cut)
    parent, = observed['lines']
    assert parent['readiness'] is None and observed['total'] is None
    parts = {part['display_code']: part for part in parent['operations']['lines']}
    assert parts['4.1.1']['readiness'] == .25
    assert parts['4.1.2']['state'] == 'unknown' and parts['4.1.2']['volume']['fact'] is None
    assert parts['4.1.3']['readiness'] == 0
    cached={'ok':True,'contract_id':'c'*64,'control':observed,'fact':measured,'plan':planned,
            'documents':[{'sha256':'b'*64,'title':'Учебная РДС','estimates':edition['estimates']},
                         {'sha256':'schedule','title':'Учебный ГПР','schedule':edition['schedule']}]}
    cached['comparison']=comparison.build(cached,operation_cut)
    cached['rds_comparison']=rds.build(cached)
    meta=export.bind_snapshot('Учебный',operation_cut,'c'*64,cached,{})
    raw = export.workbook(meta,cached['rds_comparison'],cached['rds_comparison']['rows'])
    sheet = load_workbook(io.BytesIO(raw), data_only=True).active
    excel_row = next(row for row in sheet if row[0].value=='4.1.2')
    assert excel_row[7].value is None and excel_row[5].value is not None
    assert excel_row[11].value is None and excel_row[13].value is None
    assert 'Период без даты' in excel_row[7].comment.text


from tests.test_contract_fact_prices_ks_by_the_edition import card  # noqa: E402,F401
