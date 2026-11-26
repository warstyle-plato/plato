"""Accepted facts stay distinct from missing input and unallocated company crews."""
import copy
import datetime as dt
import io
import json

import pytest
from openpyxl import Workbook, load_workbook

import developaid_contract_comparison_export as comparison_export
import developaid_contract_gpr_export as export
import developaid_contract_gpr_reporting as reporting
import developaid_contract_physical_audit as audit
from developaid_contract_physical_sheets import write_audit
import developaid_contract_workforce as workforce
from tests.contract_rds_fixtures import native_card


def staffing():
    row={'id':'a'*64,'contract':'A-123','contract_date':'2026-01-01','contractor':'ООО «Исполнитель»'}
    source={'sha256':'b'*64,'contract':{'number':'A-123','date':'2026-01-01'},
            'edition':{'date':'2026-01-15'}}
    return row,source,{'resources':[]},{'rows':[row]}


def test_work_qualifier_keeps_company_reports_without_changing_strict_contract_admission():
    row,source,schedule,register=staffing()
    reports=[{'date':day,'text':'Исполнитель (кровля) ИТР 2, рабочие '+str(value)}
             for day,value in [('2026-01-14',4),('2026-01-24',0),('2026-01-26',99)]]
    got=workforce.project(schedule,reports,row,register,'2026-01-24',source=source)
    assert got['available'] is False
    assert all(r['workers_fact'] is r['itr_fact'] is r['workers_delta'] is r['itr_delta'] is None for r in got['rows'])
    rows=export.company_workforce_rows(got)
    assert [(r['date'],r['workers'],r['itr']) for r in rows]==[('2026-01-14',4,2),('2026-01-24',0,2)]
    wb=Workbook();sheet=export.write_company_workforce(wb,got)
    assert sheet['C6'].value==0 and sheet['F6'].value==2
    assert all(sheet.cell(i,c).value is None for i in (5,6) for c in (2,4,5,7))
    assert 'предшествует' in sheet['H5'].value
    assert 'contractor_unallocated' in sheet['H6'].comment.text and sheet.freeze_panes is None


@pytest.mark.parametrize('party',['ИсполнительДругой (кровля)','АО «Исполнитель» (кровля)','Чужая бригада'])
def test_company_evidence_never_uses_substring_or_conflicting_legal_identity(party):
    row,source,schedule,register=staffing()
    got=workforce.project(schedule,[{'date':'2026-01-24','text':party+' ИТР 5, рабочие 82'}],row,register,'2026-01-24',source=source)
    assert got['company_observations']==[] and export.company_workforce_rows(got)==[]


def test_two_contracts_share_one_company_observation_without_allocation_or_double_sum():
    row,source,schedule,register=staffing()
    register['rows'].append({**row,'id':'c'*64,'contract':'B-456'})
    reports=[{'date':'2026-01-24','text':'Исполнитель (кровля) ИТР 5, рабочие 82'}]
    got=workforce.project(schedule,reports,row,register,'2026-01-24',source=source)
    values=export.company_workforce_rows(got)
    assert len(values)==1 and (values[0]['workers'],values[0]['itr'])==(82,5)
    assert all(r['workers_fact'] is None for r in got['rows'])
    assert 'повторно не суммировать' in values[0]['reason']
    # A second, genuinely distinct report is a conflict, never 164 workers.
    reports.append({'date':'2026-01-24','text':'Исполнитель (кровля) ИТР 5, рабочие 82','source':{'message':2}})
    assert export.company_workforce_rows(workforce.project(schedule,reports,row,register,'2026-01-24',source=source))==[]


def test_unknown_plan_ranges_are_source_context_not_workers_itr_totals_or_carried_forward_plan():
    row,source,schedule,register=staffing()
    annotation={'literal':'2–5 чел','minimum':2,'maximum':5,'category':'people_unspecified',
        'operation':'1.1.1','name':'Работа','start':'2026-01-11','finish':'2026-01-20',
        'source':{'sha256':source['sha256'],'page':1,'row':4,'column':10}}
    schedule['personnel_annotations']=[annotation,{**copy.deepcopy(annotation),'operation':'1.1.2'}]
    reports=[{'date':day,'text':'Исполнитель (кровля) ИТР 2, рабочие 2'} for day in ['2026-01-14','2026-01-24']]
    got=workforce.project(schedule,reports,row,register,'2026-01-24',source=source)
    assert len(got['plan_annotations'])==2 and not got['available']
    wb=Workbook();s=export.write_company_workforce(wb,got)
    assert '2–5 чел' in s['H5'].value and 'предшествует' in s['H5'].value
    assert 'нет подписи' in s['H6'].value
    assert all(s.cell(r,c).value is None for r in [5,6] for c in [2,4,5,7])
    assert len(json.loads(s['H5'].comment.text)['plan_annotations'])==2
    assert sum(c.value=='2–5 чел' for cells in s for c in cells)==2
    assert any('SHA '+source['sha256'] in str(c.value) for cells in s for c in cells)
    other=copy.deepcopy(schedule);other['personnel_annotations'][0]['source']['sha256']='f'*64
    projected=workforce.project(other,reports,row,register,'2026-01-24',source=source)
    assert len(projected['plan_annotations'])==1


def test_accepted_ks2_event_keeps_original_quantity_date_and_page_row_in_physical_audit():
    event={'quantity_kind':'increment','work_quantity':12.5,'start':None,'end':'2026-01-20',
           'label':'КС-2 №1','source':{'sha256':'d'*64,'page':2,'row':7},'date_basis':'document_observation'}
    position={'number':'1.1.1','name':'Монтаж','unit':'м2','quantity':30}
    observed={'work_observed':True,'work_quantity':12.5,'sources':[],'reporting_events':[event]}
    before=copy.deepcopy(observed)
    projection=audit.position_audit(position,(0,0),{}, {'source':'ks2'},observed,None,'2026-01-24')
    assert projection['accepted_events']==[event] and projection['sources']==[] and observed==before
    wb=Workbook();write_audit(wb,{'rows':[dict(position,contract_quantity=30,fact_quantity=12.5,physical_audit=projection)]})
    s=wb['Аудит физобъёмов']
    assert s['G4'].value=='12.5' and s['I4'].value=='2026-01-20'
    assert 'стр. 2' in s['F4'].value and 'строка 7' in s['F4'].value and 'd'*64 in s['F4'].value
    assert s['J4'].value==12.5 and 'нет источника' not in str([s.cell(4,c).value for c in [6,7,9]])
    observed['reporting_events'][0]['end']='2026-01-25'
    assert audit.position_audit(position,(0,0),{}, {'source':'ks2'},observed,None,'2026-01-24')['accepted_events']==[]


@pytest.mark.parametrize('quantity',[None,0,6])
def test_native_deviation_formula_and_cached_result_require_two_numbers_but_keep_explicit_zero(quantity):
    card=native_card();table=card['rds_comparison'];table['rows'][0].update(fact_quantity=quantity,fact=None if quantity is None else quantity*50)
    meta=comparison_export.bind_snapshot('Учебный проект',table['cut'],card['contract_id'],card,{})
    raw=comparison_export.workbook(meta,table,table['rows'])
    formula=load_workbook(io.BytesIO(raw));cached=load_workbook(io.BytesIO(raw),data_only=True)
    f=formula.active['J7'].value
    assert f=='=IF(COUNT(F7,H7)<2,"",H7-F7)'
    assert cached.active['J7'].value==(None if quantity is None else quantity-10)
    assert cached.active['M7'].value==(None if quantity is None else quantity*50-500)
    assert cached.active['H7'].value==quantity


def test_unknown_overdue_remains_calendar_risk_without_zero_observation_or_forecast():
    line={'code':'1','name':'Работа','start':'2026-01-01','finish':'2026-01-10'}
    model=reporting.project(line,None,[(0,10)],dt.date(2026,1,1),'2026-01-24')
    assert model['checkpoints']==[] and model['current'] is None and not model.get('forecast')
    assert all(b['state']=='overdue_unclosed' and b.get('fact_quantity') is None for b in model['bars'])
    assert 'физфакт не подтверждён' in export.deadline_status(line,None,'2026-01-24')['text']
    assert 'Красная штриховка' in reporting.LEGEND


def test_heading_context_uses_source_ordinal_and_resets_between_estimates_not_repeated_numbers():
    import developaid_contract_gpr as gpr
    rows=[{'estimate':estimate,'index':index,'number':number,'name':number,'contract_quantity':10}
          for estimate,index,number in [(0,0,'1.1.6'),(0,1,'1.1.6'),(0,2,'2.1'),(1,0,'1.1.6')]]
    rds={'available':True,'rows':rows,'headings':[{'before_position':0,'number':'1','name':'Устройство кровли Корпус 1'},
         {'before_position':2,'number':'2','name':'Крановые работы'}],'cut':'2026-01-24'}
    values=gpr.position_projections({'plan':{'editions':[]}},rds,{'lines':[]})
    assert [v['position_key'] for v in values]==[[0,0],[0,1],[0,2],[1,0]]
    assert [v['section'] for v in values]==['Устройство кровли Корпус 1','Устройство кровли Корпус 1','Крановые работы','']


def test_initial_builder_numeric_zero_has_negative_cached_draft_deviation_without_observation_date():
    from developaid_contract_physical_sheets import write_builder_template
    from developaid_contract_builder_plan import cache_builder_formulas
    card=native_card();comparison=card['rds_comparison'];before=copy.deepcopy(card)
    schedule=next(d['schedule'] for d in card['documents'] if d.get('schedule'))
    wb=Workbook();write_builder_template(wb,comparison,schedule)
    stream=io.BytesIO();wb.save(stream)
    raw=cache_builder_formulas(stream.getvalue(),wb)
    cached=load_workbook(io.BytesIO(raw),data_only=True)['Физфакт строителей']
    row=next(cells for cells in cached if cells[3].value=='Монтаж' and cells[9].value)
    assert row[8].value is None and row[11].value==0 and type(row[11].value) is int
    assert row[13].value==-row[9].value and row[14].value==-row[10].value*100
    assert card==before,'Draft zero is never admitted as a new physical observation'


def test_unvalidated_string_zero_is_not_silently_admitted_as_numeric_physical_fact():
    card=native_card();card['rds_comparison']['rows'][0]['fact_quantity']='0'
    with pytest.raises(comparison_export.ExportProblem,match='числовое'):
        comparison_export.workbook(card['comparison_export'],card['rds_comparison'],card['rds_comparison']['rows'])


def test_canonical_rds_uses_the_same_missing_and_zero_rules_as_the_workbook():
    import developaid_contract_rds as rds
    unknown=native_card(unknown=True)['rds_comparison']['rows'][0]
    assert unknown['fact_quantity'] is None and unknown['quantity_deviation'] is None and unknown['deviation'] is None
    card=native_card();zero=card['rds_comparison']['rows'][1]
    assert zero['fact_quantity']==0 and zero['quantity_deviation']==-zero['plan_quantity']
    card['plan']['editions'][0]['position_links']=[]
    got=rds.build(card)['rows'][0]
    assert got['fact_quantity']==6 and got['fact']==300
    assert got['plan_quantity'] is got['planned'] is got['quantity_deviation'] is got['deviation'] is None
