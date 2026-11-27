"""The card must display canonical RDS evidence even before a GPR source is chosen."""
import copy
import json

import pytest

from developaid_monitor_page import MONITOR_PAGE
from tests import page_blocks
from tests.contract_rds_fixtures import native_card
import developaid_contract_fact as fact
import developaid_contract_files as files
import developaid_contract_plan as plan
import developaid_contract_rds as rds
import developaid_contract_schedule_links as links


def unscheduled_card():
    source=native_card()
    estimate=copy.deepcopy(source['documents'][0]['estimates'][0])
    estimate['links']=links.propose(estimate,None)
    current={'sha256':'a'*64,'estimate_sha256':'a'*64,'title':'Synthetic RDS',
        'estimate_title':'Synthetic RDS','date':'2026-02-01','start':None,'estimates':[estimate],
        'schedule':None,'schedule_sha256':''}
    cut=source['plan']['cut']
    found=fact.acts({'physical_items':source['fact']['physical_source_rows']})
    planned=plan.build([current],cut)
    actual=fact.build([current],planned['in_force'],found,cut)
    documents=[{'sha256':'a'*64,'title':'Synthetic RDS','estimates':[estimate],
        'contract':{'number':'Т-1','date':'2026-02-01'}}]
    listed=files._with_control({'contract_id':'c'*64,'documents':documents,
        'plan':planned,'fact':actual},found,cut)
    listed['rds_comparison']=rds.build(listed)
    return listed


def render(cached, *, filter='all', query=''):
    state, rds = cached['comparison'], cached['rds_comparison']
    prelude = 'const source='+json.dumps({'state':state,'rds':rds},ensure_ascii=False)+';\n'
    prelude += 'const before=JSON.stringify(source);const widgets='+json.dumps({
        'contractComparisonFilter':{'value':filter},'contractComparisonSearch':{'value':query}})+';\n'
    prelude += "function $(id){return widgets[id]};let contractComparisonState=contractRdsComparisonState(source.state,source.rds,source.rds.cut);\n"
    result = page_blocks.run_json(prelude,r"""
const rows=contractComparisonSelection().map(x=>x.row);
console.log(JSON.stringify({same:before===JSON.stringify(source),fallback:contractComparisonState.rds_fallback===true,
rows:rows.map(r=>({code:r.code,state:r.state,rds:r.rds,reporting:r.ks_reporting})),html:contractComparisonGroupedRows(rows)}));
""",page=MONITOR_PAGE)
    assert result['same']
    return result


def test_known_rds_execution_does_not_disappear_when_schedule_comparison_is_empty():
    cached = unscheduled_card()
    assert cached['comparison']['lines']==[]
    result = render(cached)
    assert result['fallback'] and len(result['rows'])==2
    assert result['rows'][0]['rds']['fact_quantity']==6
    assert result['rows'][0]['rds']['plan_quantity'] is None
    assert '6 м3' in result['html'] and '300' in result['html']
    assert 'Факт по загруженным КС' in result['html']


def test_explicit_zero_unknown_and_material_cost_have_different_meanings():
    cached=native_card(unknown=True)
    cached['comparison']['lines']=[]
    rows=cached['rds_comparison']['rows']
    assert rows[0]['fact_quantity'] is None and rows[1]['fact_quantity']==0
    # A canonical total can describe delivered materials while work is explicitly zero.
    rows[1]['fact']=200.0
    result=render(cached)
    assert result['rows'][0]['rds']['fact_quantity'] is None
    assert result['rows'][1]['rds']['fact_quantity']==0
    assert '0 м2' in result['html'] and 'Неизвестно' in result['html']
    assert 'Стоимость работ и поставки: 200' in result['html']
    assert 'Доля объёма РДС по КС: 0 %' in result['html']


def test_known_negative_variances_filter_search_and_export_identity_stay_canonical():
    cached=native_card();cached['comparison']['lines']=[]
    canonical=copy.deepcopy(cached['rds_comparison']['rows'][0])
    assert canonical['quantity_deviation'] < 0 and canonical['deviation'] < 0
    result=render(cached,filter='behind',query='кладка')
    assert len(result['rows'])==1 and result['rows'][0]['rds']==canonical
    assert str(int(canonical['quantity_deviation'])) in result['html']
    assert str(int(canonical['deviation'])) in result['html']
    assert result['rows'][0]['code']=='rds:0:0'


def test_normal_gpr_comparison_is_kept_when_it_has_known_values():
    cached=native_card()
    result=render(cached)
    assert not result['fallback']
    assert [row['code'] for row in result['rows']]==[row['code'] for row in cached['comparison']['lines']]


@pytest.mark.parametrize('schema',['rds-loaded-ks-reporting-v1','wrong-schema'])
def test_only_typed_backend_credited_zero_can_override_unknown_physical_fact(schema):
    cached=native_card(unknown=True)
    row=cached['rds_comparison']['rows'][0]
    row['ks_reporting']={'schema':schema,'basis':'loaded_ks2','state':'unreported_zero',
        'fact_quantity':0,'fact_quantity_ratio':0,'quantity_deviation':-10,
        'fact':0,'deviation':-500,'physical_quantity_confirmed':False,
        'comments':{'fact_quantity':'Не предъявлено в загруженных КС; физический ноль не подтверждён.'}}
    result=render(cached)
    if schema=='rds-loaded-ks-reporting-v1':
        assert result['fallback'] and result['rows'][0]['reporting']
        assert result['rows'][0]['rds']['fact_quantity']==0
        assert result['rows'][0]['rds']['deviation']==-500
        assert 'не подтверждение физического нуля' in result['html']
        assert row['fact_quantity'] is None
    else:
        assert not result['fallback']


def test_wrong_cut_or_missing_rds_does_not_admit_a_foreign_projection():
    cached=native_card();cached['comparison']['lines']=[]
    cached['rds_comparison']['cut']='2027-01-01'
    state, rds=cached['comparison'],cached['rds_comparison']
    out=page_blocks.run_json('const state='+json.dumps(state)+';const rds='+json.dumps(rds)+';',
        "console.log(JSON.stringify({same:contractRdsComparisonState(state,rds,'2026-03-05')===state,missing:contractRdsComparisonState(state,null,'2026-03-05')===state}))",page=MONITOR_PAGE)
    assert out=={'same':True,'missing':True}


def test_document_call_forwards_the_existing_rds_projection_without_recalculation():
    prelude=r"""
const rds={available:true,layout:'rds-plan-fact-v3',cut:'2026-03-05',rows:[{fact_quantity:0}]};
const answer={ok:true,ticket:'a'.repeat(32),rds_comparison:rds,documents:[],comparison:{cut:'2026-03-05',lines:[]}};
const host={isConnected:true,querySelectorAll:()=>[]},widget={disabled:false,querySelectorAll:()=>[]};
function $(id){return id==='contractDocuments'?host:widget};let contractGprExport=null,contractDocumentsRequest=0,contractDocumentsState=null,contractRawMode=false,captured=[];
function hasAuth(){return true};function requireLogin(){throw Error('Unexpected login')};function cumulativeError(e){return e.message};function contractCardSummary(){return ''};function cumulativeContext(){return{project:'Synthetic',cut:'2026-03-05'}};function sameCumulativeContext(){return true};
function contractById(){return null};async function cumulativeJob(){return answer};function msg(){};function renderContractGpr(){};
function renderContractDocuments(...args){captured.push(args[7]===rds)};function updateContractActEvidence(){};
"""
    out=page_blocks.run_json(prelude,r"""
(async()=>{await contractDocumentsCall('c'.repeat(64),'/monitor/contracts/documents',{},()=> '');console.log(JSON.stringify(captured));})().catch(e=>{console.error(e);process.exit(1)});
""",page=MONITOR_PAGE)
    assert out==[True]


def test_document_renderer_forwards_rds_and_only_one_book_action_exists():
    prelude=r"""
const rds={rows:[{fact_quantity:0}]},host={querySelectorAll:()=>[],innerHTML:''};let forwarded=false;
function contractLabelCells(){};function contractDocumentsClick(){};function contractScanKind(){};function contractScanHtml(){return ''};function contractDocumentConditions(){return ''};function contractDocumentWarnings(){return ''};function contractOptionalExcelPart(){return ''};function contractEstimateHtml(){return ''};function contractScheduleHtml(){return ''};
function renderContractComparison(state,control,fact,value){forwarded=value===rds};
"""
    out=page_blocks.run_json(prelude,r"""
renderContractDocuments(host,[],[],null,null,null,null,rds);
const shell=contractComparisonShell();console.log(JSON.stringify({forwarded,secondary:shell.includes('contractComparisonExport'),link:shell.includes('href="#contractGprDownload"')}));
""",page=MONITOR_PAGE)
    assert out=={'forwarded':True,'secondary':False,'link':True}
