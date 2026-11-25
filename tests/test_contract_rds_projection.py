"""Synthetic primary-source proofs for an RDS-led, cached export; no private source data."""
import copy

import pytest

import developaid_contract_fact as fact
import developaid_contract_files as files
import developaid_contract_plan as plan
import developaid_contract_rds as rds
import developaid_contract_schedule_links as links
from tests.test_contract_ks6a_primary_fact import EDITION, CUT, statement, uploaded
from tests.contract_rds_fixtures import native_card


def edition(template=EDITION, *, sha='a', price=None, date='2026-01-01', start=None, no_schedule=False):
    value = copy.deepcopy(template)
    value.update(sha256=sha*64, estimate_sha256=sha*64, date=date, start=start,
                 title='Редакция '+sha, schedule_sha256='b'*64)
    for estimate in value['estimates']:
        estimate.setdefault('structure', [])
        for index, (position, binding) in enumerate(zip(estimate['positions'], estimate['links']['positions'])):
            binding.update(index=index)
            if price is not None:
                position['unit_price'].update(work=price,total=price)
                position['amount'].update(work=position['quantity']*price,total=position['quantity']*price)
                binding.update(amount=position['amount']['total'])
    if no_schedule:
        value.update(schedule=None, schedule_sha256='')
        for estimate in value['estimates']:
            estimate['links'] = links.propose(estimate, None)
    return value


def card(editions, found=None, performed=None, cut=CUT):
    planned = plan.build(editions, cut)
    actual = fact.build(editions, planned['in_force'], found, cut, performed)
    current = next(item for item in reversed(editions) if item['date'] <= cut)
    documents = [{'sha256': item['estimate_sha256'], 'title': item['title'],
                  'contract': {'number': 'Учебный', 'date': '2026-01-01'}, 'estimates': item['estimates']}
                 for item in editions]
    if current.get('schedule'):
        documents.append({'sha256': current['schedule_sha256'], 'title': 'Учебный ГПР',
                          'contract': {'number': 'Учебный', 'date': '2026-01-01'}, 'schedule': current['schedule']})
    result = files._with_control({'contract_id': 'c'*64, 'documents': documents,
                                  'plan': planned, 'fact': actual}, found, cut)
    result['rds_comparison'] = rds.build(result)
    return result


def test_statement_priority_and_missing_acts_do_not_change_rds_facts():
    native = card([edition()], statement(), uploaded(1,2,3,4,5))
    assert native['fact']['source'] == 'ks6a'
    assert native['rds_comparison']['rows'][0]['fact_quantity'] == 15
    assert native['rds_comparison']['rows'][0]['fact'] == 1500
    fallback = card([edition()], None, uploaded(1))
    assert fallback['fact']['source'] == 'ks2'
    assert fallback['rds_comparison']['rows'][0]['fact_quantity'] == 100


def test_explicit_statement_zero_is_numeric_but_missing_act_rows_stay_unknown():
    known = native_card()['rds_comparison']['rows'][1]
    assert known['fact_quantity'] == known['fact'] == 0
    found = fact.acts({'physical_items': [{'position': '1', 'name': 'Монтаж', 'unit': 'м2',
        'plan_quantity': 100, 'completed_quantity': 0, 'reported_completed_quantity': 0,
        'periods': [{'quantity': 0, 'amount': 0, 'material_quantity': 0,
                     'work_amount': 0, 'material_amount': 0, 'date_end': '2026-02-01'}]}]})
    assert not found['acts'] and len(found['zero_acts']) == 1
    row = card([edition()], found, uploaded(1))['rds_comparison']['rows'][0]
    assert row['fact_quantity'] == row['fact'] == 0
    without_reported = fact.acts({'physical_items': [{'position': '1', 'name': 'Монтаж', 'unit': 'м2',
        'plan_quantity': 100, 'completed_quantity': 0,
        'periods': [{'quantity': 0, 'amount': 0, 'material_quantity': 0,
                     'work_amount': 0, 'material_amount': 0, 'date_end': '2026-02-01'}]}]})
    assert card([edition()], without_reported)['rds_comparison']['rows'][0]['fact_quantity'] == 0
    missing = card([edition()], None, {'positions': [], 'acts': []})['rds_comparison']['rows'][0]
    assert missing['fact_quantity'] is None and missing['fact'] is None and missing['day_deviation'] is None
    assert 'выбранной КС-6а' not in missing['comments']['fact_quantity']


def test_split_delivery_does_not_inflate_physical_work_and_unknown_component_is_blank():
    source = edition()
    position = source['estimates'][0]['positions'][0]
    position.update(quantity=10)
    position['unit_price'] = {'work': 60, 'material': 40, 'total': 100}
    position['amount'] = {'work': 600, 'material': 400, 'total': 1000}
    source['estimates'][0]['links']['positions'][0].update(quantity=10,amount=1000,work_amount=600,material_amount=400)
    found = {'works': 1, 'items': [], 'unread': [], 'acts': [{
        'number': '1', 'name': 'Монтаж', 'unit': 'м2', 'quantity': 2, 'quantity_material': 5,
        'act_amount': 320, 'amount_components': {'work':120,'material':200},
        'start':'2026-01-01','end':'2026-02-01','item':0,'source':{'row':5}}]}
    row = card([source], found)['rds_comparison']['rows'][0]
    assert row['fact_quantity_ratio'] == .2
    assert row['fact_quantity'] == 2 and row['fact'] == 320  # Never 7, or 3.2 from rubles.
    found['acts'][0].update(quantity_material=None,act_amount=120,amount_components={})
    row = card([source], found)['rds_comparison']['rows'][0]
    assert row['fact_quantity'] == 2 and row['fact'] is None
    assert '120,00 ₽' in row['comments']['fact'] and 'не полный факт' in row['comments']['fact']
    found['acts'][0].update(basis='material',quantity=5,act_amount=200)
    row = card([source], found)['rds_comparison']['rows'][0]
    assert row['fact_quantity'] is None and row['day_deviation'] is None


def test_separately_proved_zero_work_survives_an_unread_material_period():
    found={'works':1,'items':[],'acts':[],'unread':[{
        'number':'1','name':'Монтаж','unit':'м2','reported_quantity':0,
        'reason':'Даты поставки не подтверждены','periods':[{
            'quantity':None,'amount_split':True,'work_amount':0,'material_amount':200}]}]}
    row=card([edition()],found)['rds_comparison']['rows'][0]
    assert row['fact_quantity']==0 and row['fact'] is None
    assert 'Нулевой объём' in row['comments']['fact_quantity']


def test_no_gpr_preserves_all_rds_rows_and_typed_fact_without_act_derived_pseudo_rows():
    result = card([edition(no_schedule=True)], None, uploaded(1))
    assert result['comparison']['lines'] == []
    row, = result['rds_comparison']['rows']
    assert row['fact_quantity'] == 100 and row['fact'] == 10000
    assert all(row[field] is None for field in ('start','finish','plan_quantity','planned','day_deviation'))
    assert native_card(empty=True)['rds_comparison']['available'] is False


def test_historical_prices_stay_canonical_and_before_remaining_start_is_excluded():
    previous, current = edition(), edition(sha='d',price=200,date='2026-03-01')
    found = statement()
    found['acts'] = [dict(found['acts'][0],quantity=2,act_amount=200,end='2026-02-01')]
    result = card([previous,current],found)
    row, = result['rds_comparison']['rows']
    assert row['fact_quantity'] == 2 and row['fact'] == 200  # Active price would give 400.
    current['start']='2026-03-01'
    found['acts'].append(dict(found['acts'][0],quantity=1,act_amount=200,end='2026-03-10'))
    row = card([previous,current],found)['rds_comparison']['rows'][0]
    assert row['fact_quantity'] == 1 and row['fact'] == 200


def test_several_gpr_links_never_invent_one_signed_day_or_date_span():
    source = edition()
    source['schedule']['lines'] = [dict(source['schedule']['lines'][0],code=code) for code in ('1.1','1.2')]
    source['estimates'][0]['links']['positions'][0]['lines'] = [
        {'code':'1.1','share':.5},{'code':'1.2','share':.5}]
    row = card([source],statement())['rds_comparison']['rows'][0]
    assert row['planned'] is not None and row['fact_quantity'] == 15
    assert row['day_deviation'] is None and row['start'] is row['finish'] is None


def test_unread_rds_inputs_and_wrong_observation_source_have_explicit_unknown_comments():
    cached=native_card()
    cached['documents'][0]['estimates'][0]['positions'][0]['quantity']=None
    cached['documents'][0]['estimates'][0]['positions'][0]['amount']['total']=None
    cached['fact']['rds_positions'][0]['estimate_sha256']='f'*64
    rows=rds.build(cached)['rows']
    assert all(rows[0][key] is None and rows[0]['comments'][key] for key in ('plan_quantity','planned','fact_quantity','fact'))


def test_repeated_printed_rds_codes_keep_source_order_and_typed_position_identity():
    source=edition(no_schedule=True)
    estimate=source['estimates'][0]
    estimate['positions'].append(dict(copy.deepcopy(estimate['positions'][0]),name='Другой монтаж'))
    estimate['links']=links.propose(estimate,None)
    found=statement()
    found['acts']=[dict(found['acts'][0],name='Другой монтаж',quantity=3,act_amount=300)]
    rows=card([source],found)['rds_comparison']['rows']
    assert [row['number'] for row in rows]==['1','1']
    assert [row['name'] for row in rows]==['Монтаж','Другой монтаж']
    assert [row['fact_quantity'] for row in rows]==[None,3]
    assert [(row['estimate'],row['index']) for row in rows]==[(0,0),(0,1)]


def test_reader13_cache_refresh_preserves_all_source_headings_without_upload(monkeypatch,tmp_path):
    import json
    import developaid_monitor as monitor
    import developaid_contract_documents as documents
    from tests.test_contract_documents_are_read_from_their_tables import estimate_pdf
    monkeypatch.setattr(monitor,'_SNAPSHOT_DIR',tmp_path/'monitor')
    contract={'id':'c'*64,'contract':'12-ТСТ','contract_date':'2025-09-01'}
    raw=estimate_pdf()
    saved=files.store('Учебный',contract,'Учебная РДС.pdf',raw)
    folder=files._directory('Учебный',contract['id']);path=folder/(saved['sha256']+'.json')
    old=json.loads(path.read_text());old['reader']=13
    old['estimates'][0].pop('structure')
    path.write_text(json.dumps(old,ensure_ascii=False))
    current,=files.listing('Учебный',contract['id'],'2026-02-04')['documents']
    assert current['reader']==documents.READER_VERSION==14
    headings=current['estimates'][0]['structure']
    assert [item['before_position'] for item in headings]==[0,0,3]
    assert [item['number'] for item in headings]==['','1','']
    assert [p['number'] for p in current['estimates'][0]['positions']]==['1.1','1.2','1.3','2.1','2.1']
    assert (folder/(saved['sha256']+'.pdf')).read_bytes()==raw and not files._choices(folder)


def test_physical_percent_uses_full_rds_quantity_preserves_zero_and_overrun():
    cached = native_card()
    first, zero = cached['rds_comparison']['rows']
    assert first['plan_quantity_ratio'] == .5 and first['fact_quantity_ratio'] == .3
    assert zero['fact_quantity_ratio'] == 0 and zero['contract_quantity'] == 10
    assert 'полное количество' in zero['comments']['fact_quantity_ratio']
    found = statement()
    found['acts'] = [dict(found['acts'][0], quantity=120, act_amount=12000)]
    row = card([edition()], found)['rds_comparison']['rows'][0]
    assert row['fact_quantity_ratio'] == 1.2  # Physical overrun is not capped readiness.
    for quantity in (None, 0, -1):
        source = edition()
        source['estimates'][0]['positions'][0]['quantity'] = quantity
        row = card([source], statement())['rds_comparison']['rows'][0]
        assert row['plan_quantity_ratio'] is None and row['fact_quantity_ratio'] is None
        assert row['forecast_finish'] is None and row['forecast_delay_days'] is None
        assert row['comments']['fact_quantity_ratio']


def test_forecast_is_existing_individual_physical_model_not_current_lag_or_legal_overdue():
    cached = native_card()
    row = cached['rds_comparison']['rows'][0]
    canonical = cached['control']['lines'][0]
    assert row['forecast_finish'] == canonical['forecast_finish'] == '2026-03-12'
    assert row['forecast_delay_days'] == 2 and row['day_deviation'] == -2
    assert row['forecast_kind'] == 'forecast' and 'Условный прогноз' in row['comments']['forecast_finish']
    done = native_card(finished=True)['rds_comparison']['rows'][0]
    assert done['day_deviation'] == 0 and done['forecast_delay_days'] == 4
    assert done['forecast_finish'] == '2026-03-14' and done['forecast_kind'] == 'actual'
    # Existing model leaves an unfinished ahead-of-plan work on its GPR end.
    source, found = edition(), statement()
    found['acts'][0].update(quantity=60, act_amount=6000, end='2026-01-05')
    ahead = card([source], found, cut='2026-01-10')['rds_comparison']['rows'][0]
    assert ahead['day_deviation'] > 0 and ahead['forecast_delay_days'] == 0
    assert ahead['forecast_kind'] == 'forecast'


def test_forecast_never_uses_partial_link_money_only_or_unobserved_fact():
    source = edition()
    source['estimates'][0]['links']['positions'][0]['lines'][0]['share'] = .5
    row = card([source], statement())['rds_comparison']['rows'][0]
    assert row['forecast_finish'] is None and row['forecast_delay_days'] is None
    cached = native_card()
    cached['control']['lines'][0]['volume'] = None
    cached['control']['lines'][0]['basis'] = 'money'
    assert rds.build(cached)['rows'][0]['forecast_finish'] is None
    unknown = native_card(unknown=True)['rds_comparison']['rows'][0]
    assert unknown['fact_quantity_ratio'] is None and unknown['forecast_finish'] is None
