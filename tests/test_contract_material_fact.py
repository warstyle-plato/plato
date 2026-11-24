"""Accepted materials and installed work retain independent quantities and money."""
import pytest

import developaid_contract_acts as acts
import developaid_contract_fact as fact
import developaid_contract_schedule_links as links


POSITION = {'number': '1', 'name': 'Монтаж стены', 'unit': 'м2', 'quantity': 100,
            'unit_price': {'work': 10, 'material': 100, 'total': 110},
            'amount': {'work': 1000, 'material': 10000, 'total': 11000}}


def act_position(work=20, material=5, *, basis='work'):
    return {'number': '1', 'name': 'Монтаж стены', 'unit': 'м2', 'quantity': work,
            'quantity_material': material, 'quantity_basis': basis,
            'unit_price': {'work': 10, 'material': 100, 'total': 110},
            'amount': {'work': 0 if basis == 'material' else work*10,
                       'material': material*100 if material is not None else None,
                       'total': (0 if basis == 'material' else work*10) + (material or 0)*100}}


def accumulated(*positions):
    return acts.accumulated([{'sha256': 'a'*64, 'title': 'Учебный акт', 'filename': 'Акт.pdf',
        'act': {'number': '1', 'date': '2026-03-01', 'start': '2026-02-01', 'finish': '2026-03-01',
                'positions': list(positions)}}], '2026-03-15')


def build(performed, *, start=None, status='confirmed'):
    link = {'key': links.position_key(POSITION), 'status': status,
            'lines': [{'code': '1', 'share': 1}]}
    editions = [{'sha256': 'b'*64, 'title': 'Учебный расчёт', 'date': '2026-01-01', 'start': start,
                 'estimates': [{'scope': 'full', 'positions': [POSITION], 'links': {'positions': [link]}}],
                 'schedule': {'lines': [{'code': '1', 'name': 'Стена', 'start': '2026-01-01',
                                          'finish': '2026-04-01', 'parent': None}]}}]
    # The same separately printed work/material quantities are in the KS-6a.
    statement = {'acts': fact.from_acts(performed), 'unread': [], 'works': 1, 'items': []}
    return fact.build(editions, 'b'*64, statement, '2026-03-15', performed)


def test_separate_quantities_survive_accumulation_and_use_separate_prices():
    performed = accumulated(act_position())
    source = fact.from_acts(performed)[0]
    assert source['quantity'] == 20 and source['quantity_material'] == 5
    assert source['basis'] == 'work'
    assert source['unit_price'] == {'work': 10, 'material': 100, 'total': 110}
    got = build(performed)
    assert got['total'] == 700
    line, = got['lines']
    assert (line['work_fact'], line['material_fact']) == (200, 500)
    assert line['volumes'] == [{'unit': 'м2', 'quantity': 20}]
    assert line['material_volumes'] == [{'unit': 'м2', 'quantity': 5}]
    assert got['materials'][0]['quantity'] == 5 and got['materials'][0]['amount'] == 500


def test_material_only_receipt_does_not_install_or_complete_work():
    got = build(accumulated(act_position(10, 10, basis='material')))
    line, = got['lines']
    assert got['total'] == 1000 and line['work_fact'] == 0
    assert line['volumes'] == [] and line['last'] is None and not line['complete']
    assert line['material_volumes'] == [{'unit': 'м2', 'quantity': 10}]
    assert line['material_last'] == '2026-03-01'


def test_explicit_zero_work_with_positive_material_quantity_is_not_dropped():
    got = build(accumulated(act_position(0, 10)))
    line, = got['lines']
    assert got['total'] == 1000 and line['work_fact'] == 0
    assert line['volumes'] == [] and line['material_volumes'] == [{'unit': 'м2', 'quantity': 10}]


def test_material_delivery_date_does_not_move_the_last_installed_work_period():
    documents=[]
    for number,end,position in [('1','2026-03-01',act_position(20,0)),
                                 ('2','2026-03-10',act_position(0,10))]:
        documents.append({'sha256':number*64,'title':'Учебный акт','filename':'Акт.pdf',
            'act':{'number':number,'date':end,'start':'2026-02-01','finish':end,'positions':[position]}})
    got=build(acts.accumulated(documents,'2026-03-15'))
    line,=got['lines']
    assert line['last']=='2026-03-01' and line['material_last']=='2026-03-10'
    assert (line['work_fact'],line['material_fact'])==(200,1000)


def test_unknown_material_quantity_is_never_assumed_to_equal_work_quantity():
    source = {'quantity': 20, 'quantity_material': None, 'act_amount': 1700,
              'basis': 'work', 'unit_price': {'work': 10, 'material': 100}, 'amount_components': {}}
    got = fact._components(source, POSITION)
    assert got['work_amount'] == 200 and got['material_quantity'] is None
    assert got['material_amount'] is None and got['total'] is None and got['reason']
    assert got['act_amount'] == 1700 and got['known_total'] == 200


def unknown_material_position():
    source = act_position(20, None)
    source['amount'] = {'material': None, 'work': None, 'total': 1700}
    return source


def test_unknown_material_money_keeps_known_work_volume_and_work_money():
    got = build(accumulated(unknown_material_position()))
    line, = got['lines']
    assert got['total'] is None and got['known_total'] == 200 and got['money_incomplete']
    assert line['fact'] is None and line['known_fact'] == 200
    assert line['work_fact'] == 200 and line['material_fact'] is None
    assert line['volumes'] == [{'unit': 'м2', 'quantity': 20}]
    assert got['positions'][0]['amount'] is None and got['positions'][0]['act_amount'] == 1700
    assert got['months'] == [{'month': '2026-03', 'fact': None, 'known_fact': 200}]
    material, = got['materials']
    assert material['quantity'] is None and material['amount'] is None and material['reason']


@pytest.mark.parametrize('place', ['before', 'review'])
def test_unknown_money_outside_current_plan_remains_unknown_with_known_subtotal(place):
    got = build(accumulated(unknown_material_position()),
                start='2026-03-10' if place == 'before' else None,
                status='review' if place == 'review' else 'confirmed')
    target = got['before'] if place == 'before' else got['outside']['review']
    assert target['amount'] is None and target['known_amount'] == 200
    assert got['money_incomplete'] and got['positions'][0]['amount'] is None


def test_shared_quantity_requires_the_acts_printed_prices_and_total_to_agree():
    source = {'quantity': 20, 'quantity_material': None, 'act_amount': 2200,
              'basis': 'work', 'unit_price': {'work': 10, 'material': 100}, 'amount_components': {}}
    got = fact._components(source, POSITION)
    assert got['material_quantity'] == 20 and got['total'] == 2200
    assert 'подтверждён' in got['material_basis'] and not got['reason']


def test_single_total_price_proves_shared_quantity_only_with_matching_rds_components():
    source = {'quantity': 20, 'quantity_material': None, 'act_amount': 2200,
              'basis': 'work', 'unit_price': {'total': 110}, 'amount_components': {}}
    got = fact._components(source, POSITION)
    assert got['material_quantity'] == 20 and got['total'] == 2200
    assert 'разбивкой цены РДС' in got['material_basis']
    source['unit_price']['total'] = 120
    source['act_amount'] = 2400
    assert fact._components(source, POSITION)['material_quantity'] is None


def test_zero_material_price_does_not_need_or_invent_a_material_quantity():
    source = {'quantity': 20, 'quantity_material': None, 'act_amount': 200,
              'basis': 'work', 'unit_price': {'total': 10}}
    position = {**POSITION, 'unit_price': {'work': 10, 'material': 0, 'total': 10}}
    got = fact._components(source, position)
    assert got['total'] == 200 and got['material_amount'] == 0
    assert got['material_quantity'] is None and not got['reason']


def test_reconciliation_does_not_add_material_volume_to_work_volume():
    performed = accumulated(act_position(10, 10, basis='material'), act_position(5, 0))
    found = {'acts': [{'number': '1', 'name': 'Монтаж стены', 'unit': 'м2', 'quantity': 5,
                      'end': '2026-03-01'}]}
    got = fact.reconcile(performed, found, '2026-03-15')
    assert got['same'] == 1 and got['rows'][0]['ks2'] == 5


def test_legacy_total_price_is_not_reported_as_a_work_component():
    source = {'quantity': 20, 'basis': 'work', 'act_amount': 1000}
    position = {'quantity': 100, 'unit_price': {'total': 50}, 'amount': {'total': 5000}}
    got = fact._components(source, position)
    assert got['total'] == 1000 and got['work_amount'] is None
    assert got['material_amount'] is None and got['reason']


def test_dated_ks6a_period_preserves_zero_work_and_its_separate_material_quantity():
    row = {'physical_items': [{'position': '1', 'name': 'Стена', 'unit': 'м2',
        'completed_quantity': 0, 'plan_quantity': 100, 'periods': [{
            'label': 'Период', 'quantity': 0, 'material_quantity': 5, 'amount': 500,
            'work_amount': 0, 'material_amount': 500, 'date_start': '2026-02-01', 'date_end': '2026-03-01'}]}]}
    source, = fact.acts(row)['acts']
    assert source['quantity'] == 0 and source['quantity_material'] == 5
    result = fact._components(source, POSITION)
    assert result['work_amount'] == 0 and result['material_amount'] == 500


def test_explicit_material_only_ks6a_period_does_not_require_a_work_quantity():
    row = {'physical_items': [{'position': '1', 'name': 'Материал', 'unit': 'м2',
        'completed_quantity': None, 'quantity_basis': 'material', 'plan_quantity': 100, 'periods': [{
            'label': 'Поставка', 'quantity': None, 'material_quantity': 5, 'amount': 500,
            'material_amount': 500, 'date_start': '2026-02-01', 'date_end': '2026-03-01'}]}]}
    source, = fact.acts(row)['acts']
    assert source['quantity'] == 5 and source['basis'] == 'material'
    assert fact._components(source, POSITION)['work_quantity'] == 0
