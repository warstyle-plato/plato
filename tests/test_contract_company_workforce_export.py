"""Company observations supplement a workbook without becoming contract facts."""
import copy
import io
import json

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook,load_workbook

import developaid_contract_files as files
import developaid_contract_gpr_export as export
import developaid_contract_workforce as workforce
import developaid_monitor_contracts as contracts
import developaid_monitor_daily as daily
from tests.test_contract_relative_gpr_calendar import card,ROW,PROJECT,CUT,KEY,finished


def candidate(key='a',workers=8,itr=2,*,workers_present=True,itr_present=True):
    return {'personnel_key':key,'party':'ООО Учебный','workers':workers,'itr':itr,
        'workers_present':workers_present,'itr_present':itr_present,'ambiguities':{},
        'raw':'Private source text','source':{'path':'/private/report','sha256':'c'*64}}


def projection(rows):
    return {'available':False,'cut':'2026-11-24','contractor':'ООО Учебный','rows':[
        {'date':date,'workers_fact':None,'workers_plan':None,'workers_delta':None,
         'itr_fact':None,'itr_plan':None,'itr_delta':None,'candidates':values} for date,values in rows]}


def test_single_company_observation_preserves_presence_and_never_fills_plan_or_contract_metrics():
    state=projection([('2026-11-23',[candidate()]),('2026-11-24',[candidate('b',0,0,itr_present=False)])])
    before=copy.deepcopy(state);book=Workbook();sheet=export.write_company_workforce(book,state)
    assert state==before and state['available'] is False
    assert sheet.title=='Численность подрядчика' and sheet.freeze_panes is None
    from developaid_contract_builder_plan import BuilderEvaluator
    evaluator=BuilderEvaluator(book)
    assert [evaluator.cell(sheet.title,sheet.cell(5,c).coordinate) for c in range(2,8)]==[None,8,'',None,2,'']
    assert [evaluator.cell(sheet.title,sheet.cell(6,c).coordinate) for c in range(2,8)]==[None,0,'',None,None,'']
    assert 'По договорам повторно не суммировать' in sheet['H5'].value
    assert 'ИТР: категория не подтверждена' in sheet['H6'].value
    assert json.loads(sheet['H5'].comment.text)['contract_fact'] is False
    assert not any('/private/report' in str(cell.value) for row in sheet for cell in row)


def test_unread_reports_preserve_a_company_sheet_without_zero_people_or_a_fake_report_date():
    state={'available':False,'cut':'2026-11-24','contractor':'ООО Учебный','report_input_status':'not_loaded',
           'report_status_note':'Сводки не загружены; фактическая численность не проверена.','rows':[]}
    book=Workbook();sheet=export.write_company_workforce(book,state)
    assert sheet.title=='Численность подрядчика' and sheet.freeze_panes is None
    assert [sheet.cell(5,c).value for c in (1,2,3,5,6)]==[None]*5
    assert sheet['D5'].data_type==sheet['G5'].data_type=='f'
    assert 'не проверена' in sheet['H5'].value


@pytest.mark.parametrize('other',[
    candidate('b'),candidate('b',0,2,workers_present=False),candidate('a',9,2),
])
def test_multiple_or_conflicting_source_records_do_not_make_a_company_total(other):
    first=candidate()
    if other['workers_present'] is False:first=candidate('a',8,0,itr_present=False)
    state=projection([('2026-11-23',[first,other]),('2026-11-24',[candidate('last')])])
    book=Workbook();sheet=export.write_company_workforce(book,state)
    assert sheet['C5'].value==first['workers'] and sheet['F5'].value==(first['itr'] if first['itr_present'] else None)
    assert sheet['C6'].value==(other['workers'] if other['workers_present'] else None)
    assert sheet['F6'].value==other['itr']
    assert len(json.loads(sheet['H5'].comment.text)['candidates'])==1
    assert sheet['D5'].data_type==sheet['G6'].data_type=='f'
    assert 'не суммируется' in sheet['H5'].value


def test_only_identical_source_records_are_deduplicated_even_if_date_rows_repeat():
    state=projection([('2026-11-24',[candidate()]),('2026-11-24',[copy.deepcopy(candidate())])])
    rows=export.company_workforce_rows(state)
    assert len(rows)==1 and rows[0]['workers']==8 and rows[0]['itr']==2


def test_company_observations_survive_multiple_scopes_and_an_applicable_contract_plan_sheet():
    assert export.write_company_workforce(Workbook(),projection([])) is None
    multiple=export.write_company_workforce(Workbook(),projection([('2026-11-24',[candidate('a'),candidate('b')])]))
    assert multiple.max_row==6 and [multiple['C5'].value,multiple['C6'].value]==[8,8]
    state=projection([('2026-11-24',[candidate()])]);state['available']=True
    book=Workbook();workforce.write_sheet(book,state)
    assert export.write_company_workforce(book,state).title=='Численность подрядчика'
    assert book.sheetnames==['Sheet','Численность','Численность подрядчика']


def test_native_unallocated_company_export_is_guarded_even_though_contract_available_is_false(card,monkeypatch):
    import main
    folder,sha,source=card;source['schedule']['resources']=[];files._json(folder/(sha+'.json'),source)
    reports=[{'date':CUT,'text':'ООО Учебный ИТР 2, рабочие 8'}]
    monkeypatch.setattr(daily,'_load_reports',lambda _:copy.deepcopy(reports))
    monkeypatch.setenv('DEVELOPAID_ADMIN_KEY',KEY)
    build=lambda *a,**k:{'rows':[copy.deepcopy(ROW)],'cut':CUT}
    monkeypatch.setattr(contracts,'build',build)
    client=TestClient(main.app);body={'key':KEY,'session':'synthetic-owner','project':PROJECT,'cut':CUT,'contract_id':ROW['id']}
    opened=finished(client,client.post('/monitor/contracts/documents',json=body))
    assert opened['gpr']['workforce']['available'] is False
    assert all(row.get('workers_fact') is None for row in opened['gpr']['workforce']['rows'])
    download={**body,'ticket':opened['ticket'],'revision':opened['gpr_export']['revision']}
    response=client.post('/monitor/contracts/gpr.xlsx',json=download)
    assert response.status_code==200
    book=load_workbook(io.BytesIO(response.content))
    assert book.sheetnames==['ГПР','Выполнение','Аудит физобъёмов','Физфакт строителей','Численность подрядчика']
    assert book['Численность подрядчика']['C5'].value==8 and book['Численность подрядчика']['F5'].value==2
    reports[0]['text']='ООО Учебный ИТР 2, рабочие 9'
    monkeypatch.setattr(contracts,'build',lambda *a,**k:pytest.fail('Synchronous export must not rebuild the register.'))
    assert client.post('/monitor/contracts/gpr.xlsx',json=download).status_code==409
    monkeypatch.setattr(contracts,'build',build)
    fresh=finished(client,client.post('/monitor/contracts/documents',json=body))
    assert fresh['gpr']['workforce']['available'] is False
    result=client.post('/monitor/contracts/gpr.xlsx',json={**body,'ticket':fresh['ticket'],'revision':fresh['gpr_export']['revision']})
    assert load_workbook(io.BytesIO(result.content))['Численность подрядчика']['C5'].value==9
