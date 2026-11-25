"""Personnel compares one source date/category/cohort, never a company pool."""
import copy
import datetime as dt
import io
import json

import pytest
from openpyxl import Workbook, load_workbook

import developaid_contract_workforce as workforce


def inputs():
    row={'id':'a'*64,'contract':'A-123','contract_date':'2026-01-01',
         'contractor':'ООО «Исполнитель»','scope':['Устройство кровли Корпус 1']}
    source={'sha256':'b'*64,'contract':{'number':row['contract'],'date':row['contract_date']},
            'edition':{'kind':'agreement','date':'2026-02-01'}}
    schedule={'source_identity':source,'resources':[
        {'category':kind,'name':'Количество '+('рабочих' if kind=='workers' else 'ИТР')+' на объекте','period_basis':'literal_date','source':{'page':1,'row':index},
         'values':[{'start':'2026-01-20','finish':'2026-01-20','value':count,'raw':str(count)}]}
        for index,(kind,count) in enumerate([('workers',10),('itr',2)],1)]}
    reports=[{'date':'2026-01-20','text':'ООО «Исполнитель», договор A-123 ИТР 1, рабочие 8'}]
    return row,source,schedule,reports,{'rows':[row]}


def view(values=None, **kw):
    row,source,schedule,reports,register=values or inputs()
    return workforce.project(schedule,reports,row,register,'2026-01-25',source=source,**kw)


def test_explicit_contract_is_a_real_source_binding_without_new_manual_gate():
    got=view();r=got['rows'][0]
    assert (r['workers_plan'],r['workers_fact'],r['workers_delta'])==(10,8,-2)
    assert (r['itr_plan'],r['itr_fact'],r['itr_delta'])==(2,1,-1)
    assert got['coverage']=={'dates':1,'workers_pairs':1,'itr_pairs':1,'project_total':False}
    assert any('более поздней' in reason for reason in r['reasons'])


def test_one_party_with_two_contracts_is_not_a_distribution_even_if_count_equal():
    values=inputs();row,_,_,reports,register=values
    reports[0]['text']='ООО «Исполнитель» ИТР 1, рабочие 8'
    register['rows'].append(dict(row,id='c'*64,contract='A-456'))
    got=view(values)['rows'][0]
    assert got['workers_fact'] is got['itr_fact'] is None
    assert got['candidates'][0]['workers']==8
    assert 'между договорами' in ' '.join(got['reasons'])


def test_one_party_one_contract_still_needs_full_work_scope():
    values=inputs();values[3][0]['text']='ООО «Исполнитель» ИТР 1, рабочие 8'
    got=view(values)['rows'][0]
    assert got['workers_fact'] is None
    assert 'полного состава' in ' '.join(got['reasons'])


def test_partial_objects_do_not_become_the_whole_contract_crew():
    values=inputs();values[0]['scope']=['Кровля Корпус 1','Кровля Корпус 2']
    values[3][0]['text']='ООО «Исполнитель», договор A-123 Корпус 1 ИТР 1, рабочие 8'
    got=view(values)['rows'][0]
    assert got['workers_fact'] is None and 'объектов' in ' '.join(got['reasons'])


def test_only_same_literal_dates_are_compared_and_future_is_excluded():
    values=inputs();values[3][0]['date']='2026-01-21'
    values[3].append({'date':'2026-02-10','text':'ООО «Исполнитель», договор A-123 ИТР 1, рабочие 8'})
    got=view(values)
    assert [r['date'] for r in got['rows']]==['2026-01-20','2026-01-21']
    assert all(r['workers_delta'] is None for r in got['rows'])
    assert got['rows'][1]['workers_fact']==8  # Applicable dated fact survives a missing same-day plan.


@pytest.mark.parametrize('raw,expected',[(None,None),('ООО «Исполнитель», договор A-123 рабочие 0',0)])
def test_absent_parsed_category_is_not_confirmed_zero(raw, expected):
    values=inputs()
    values[3][0]={'date':'2026-01-20','parsed':{'contractors':[{'name':'ООО «Исполнитель», договор A-123','workers':0,'itr':0}]}}
    if raw is not None:values[3][0]['text']=raw
    got=view(values)['rows'][0]
    assert got['workers_fact']==expected
    assert got['itr_fact'] is None


def test_duplicate_saved_report_is_one_source_but_two_crew_lines_are_not_summed():
    values=inputs();values[3].append(copy.deepcopy(values[3][0]))
    assert view(values)['rows'][0]['workers_fact']==8
    values=inputs();values[3][0]['text']+='\n'+values[3][0]['text']
    got=view(values)['rows'][0]
    assert got['workers_fact'] is None


def test_repeated_itr_resources_are_not_summed_or_deduplicated_by_equal_counts():
    values=inputs();values[2]['resources'].extend(copy.deepcopy(values[2]['resources'][1]) for _ in range(7))
    got=view(values)['rows'][0]
    assert got['itr_plan'] is got['itr_delta'] is None
    assert got['workers_delta']==-2


def test_mixed_category_and_range_stay_visible_without_invented_split():
    values=inputs();values[2]['resources'][0]['category']='workers_and_itr'
    values[2]['resources'][1]['values'][0]['value']={'min':1,'max':2,'raw':'1–2'}
    got=view(values)['rows'][0]
    assert got['workers_plan'] is got['itr_plan'] is None
    assert got['combined_plan'][0]['value']==10
    assert got['itr_plan_sources'][0]['range']['raw']=='1–2'


def test_plan_scope_hint_is_not_a_whole_object_fact_binding():
    values=inputs();values[3][0]['text']='ООО «Исполнитель» (кровля) ИТР 1, рабочие 8'
    for r in values[2]['resources']:r.update(name='Численность',scope_hint='кровля',scope_state='requires_confirmation')
    got=view(values)['rows'][0]
    assert got['workers_fact'] is None


def test_existing_source_binding_must_pin_report_plan_category_and_one_owner():
    values=inputs();values[3][0]['text']='ООО «Исполнитель» ИТР 1, рабочие 8'
    p=workforce.personnel(values[3],'2026-01-25')[0]
    binding={'personnel_key':p['personnel_key'],'contract_id':values[0]['id'],
        'plan_sha256':values[1]['sha256'],'scope_complete':True,'confirmed':True,
        'categories':['workers'],'scope':'Полный состав кровельной бригады','source':{'sha256':'d'*64}}
    got=view(values,existing_bindings=[binding])['rows'][0]
    assert got['workers_delta']==-2 and got['itr_fact'] is None
    changed=dict(binding,plan_sha256='e'*64)
    assert view(values,existing_bindings=[changed])['rows'][0]['workers_fact'] is None
    foreign=dict(binding,contract_id='f'*64,plan_sha256='f'*64)
    assert view(values,existing_bindings=[binding,foreign])['rows'][0]['workers_fact'] is None


def test_no_resources_still_explains_real_report_candidate_without_fake_zeros():
    values=inputs();values[2]['resources']=[]
    got=view(values)
    assert got['rows'][0]['workers_plan'] is got['rows'][0]['workers_fact'] is None
    assert got['rows'][0]['candidates'][0]['workers']==8
    assert 'нет подтверждённого календарного' in ' '.join(got['rows'][0]['reasons'])
    assert not got['available'] and 'записи подрядчика' in got['reason']
    wb=Workbook()
    assert workforce.write_sheet(wb,got) is None and len(wb.worksheets)==1


def test_excluded_or_wrong_contract_source_never_becomes_a_comparison():
    values=inputs();values[0]['excluded']=True
    assert not view(values)['available']
    values=inputs();values[1]['contract']['number']='OTHER'
    assert not view(values)['available']


def test_writer_has_compact_native_numbers_no_formula_or_freeze_and_preserves_provenance():
    got=view();wb=Workbook();wb.active.title='ГПР'
    sheet=workforce.write_sheet(wb,got)
    assert sheet.freeze_panes is None and sheet.max_column==8
    assert [c.value for c in sheet[6]][:7]==[dt.date(2026,1,20),10,8,-2,2,1,-1]
    assert 'более поздней' in sheet['H6'].value and 'text_sha256' in sheet['H6'].comment.text
    assert not any(c.data_type in {'e','f'} for r in sheet for c in r)
    buf=io.BytesIO();wb.save(buf);buf.seek(0)
    assert load_workbook(buf)['Численность'].freeze_panes is None


def test_report_counts_in_work_prose_and_missing_party_are_not_silent_facts():
    reports=[{'date':'2026-01-20','text':'Рабочие 8\nПо работам\nЧужая бригада ИТР 99'}]
    assert workforce.personnel(reports,'2026-01-25')==[]


@pytest.mark.parametrize('raw,category',[
    ('ИТР 1–2, рабочие 8','itr'),('ИТР 1, ИТР 2, рабочие 8','itr'),
    ('ИТР 1, рабочие 8+2','workers'),('ИТР 1, рабочие 8/2','workers'),
    ('ИТР 1, рабочие 8,5','workers'),('ИТР 1, рабочие 8 и 2','workers'),
    ('ИТР 1, рабочие 8\nИТР 2','itr')])
def test_ambiguous_raw_category_keeps_other_exact_category(raw,category):
    values=inputs();values[3][0]['text']='ООО «Исполнитель», договор A-123 '+raw
    got=view(values)['rows'][0]
    assert got[category+'_fact'] is got[category+'_delta'] is None
    other='workers' if category=='itr' else 'itr'
    assert got[other+'_fact'] is not None
    assert any('исходн' in reason or 'повтор' in reason for reason in got['reasons'])


@pytest.mark.parametrize('basis',[None,'unknown','literal_date'])
def test_unknown_or_literal_basis_never_spreads_a_plan_between_dates(basis):
    values=inputs()
    for resource in values[2]['resources']:
        resource['period_basis']=basis
        resource['values'][0].update(start='2026-01-15',finish='2026-01-22')
    got=view(values)
    assert all(r['workers_plan'] is None and r['itr_plan'] is None for r in got['rows'])
    assert all(r['workers_delta'] is None and r['itr_delta'] is None for r in got['rows'])


@pytest.mark.parametrize('basis',['explicit_interval','relative_explicit_period'])
def test_source_interval_only_and_relative_requires_native_anchor(basis):
    values=inputs()
    for resource in values[2]['resources']:
        resource['period_basis']=basis
        resource['values'][0].update(start='2026-01-15',finish='2026-01-22')
    if basis=='relative_explicit_period':
        assert all(r['workers_plan'] is None for r in view(values)['rows'])
        values[2].update(calendar_state='anchored',anchor={'handover_date':'2026-01-01'})
    got=view(values)
    assert next(r for r in got['rows'] if r['date']=='2026-01-20')['workers_delta']==-2


def test_contract_reference_does_not_prove_resource_cohort():
    values=inputs()
    for resource in values[2]['resources']:
        resource.update(name='Рабочие каменной кладки',scope_hint='каменная кладка',scope_state='requires_confirmation')
    got=view(values)['rows'][0]
    assert got['workers_plan']==10 and got['workers_fact'] is got['workers_delta'] is None


def test_unique_source_work_context_and_object_resource_need_no_new_assignment():
    values=inputs();row,_,_,reports,register=values
    reports[0]['text']='ООО «Исполнитель» (кровля) ИТР 1, рабочие 8'
    register['rows'].append(dict(row,id='c'*64,contract='A-456',scope=['Временные дороги']))
    got=view(values)['rows'][0]
    assert got['workers_delta']==-2 and got['itr_delta']==-1
    register['rows'][1]['scope']=['Кровля Корпус 2']
    assert view(values)['rows'][0]['workers_fact'] is None


def test_work_context_uses_every_word_not_only_one_matching_word():
    values=inputs();values[3][0]['text']='ООО «Исполнитель» (кровля монолит) ИТР 1, рабочие 8'
    got=view(values)
    assert all(r['workers_fact'] is None for r in got['rows'])


def test_download_guard_pins_raw_presence_sources_and_existing_bindings(monkeypatch):
    import developaid_monitor_daily as daily
    values=inputs();reports=values[3]
    monkeypatch.setattr(daily,'_load_reports',lambda _:reports)
    got=view(values)
    assert workforce.require_current(got,'test')
    assert not workforce.require_current(got,'test',existing_bindings=[{'scope':'changed'}])
    reports[0]['text']=reports[0]['text'].replace('ИТР 1, ','')
    assert not workforce.require_current(got,'test')
    reports.append({'date':'2026-01-21','text':'Новый исходник без категории численности'})
    assert not workforce.require_current(got,'test')


def test_empty_and_unbound_projection_never_creates_placeholder_sheet():
    wb=Workbook()
    assert workforce.write_sheet(wb,{}) is None
    values=inputs();values[3].clear();values[2]['resources']=[]
    assert not view(values)['available']
    assert workforce.write_sheet(wb,view(values)) is None


def test_source_text_is_always_excel_text_even_if_it_starts_with_formula():
    got=view();got['rows'][0]['reasons']=['=HYPERLINK("bad")']
    sheet=workforce.write_sheet(Workbook(),got)
    assert sheet['H6'].data_type=='s' and sheet['H6'].value.startswith('=')
    assert not any(c.data_type=='f' for row in sheet for c in row)


@pytest.mark.parametrize('caption',[
    'Рабочие каменной кладки на объекте',
    'Количество рабочих каменной кладки на объекте',
    'Количество рабочих на объекте (каменная кладка)',
    'Количество рабочих на объекте (отделочники,подсобники)',
    'Всего рабочих на монтаж лифта 1',
    'Количество рабочих на объекте Корпус 2',
    'Количество рабочих на объекте (подсобники)'])
def test_restrictive_or_foreign_resource_caption_does_not_become_full_roof_crew(caption):
    values=inputs();values[2]['resources'][0]['name']=caption
    got=view(values)['rows'][0]
    assert got['workers_plan']==10 and got['workers_fact'] is got['workers_delta'] is None
    assert got['itr_delta']==-1


def test_compact_counts_keep_every_digit():
    values=inputs();values[3][0]['text']='ООО «Исполнитель», договор A-123 ИТР12, рабочие123'
    got=view(values)['rows'][0]
    assert got['workers_fact']==123 and got['itr_fact']==12
