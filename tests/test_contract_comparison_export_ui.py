"""One source-bound contract workbook; no ordinary-card one-sheet fallback."""
import copy
import json
from openpyxl import load_workbook
import pytest
from developaid_monitor_page import MONITOR_PAGE
import developaid_contract_gpr as gpr
import developaid_contract_gpr_export as export
from tests import page_blocks
from tests.test_contract_comparison_export import native_card, PROJECT, CUT

@pytest.mark.parametrize('case',['download','filter_changed','context_changed','source_changed','denied','wrong_mime'])
def test_native_page_downloads_only_the_bound_full_workbook(case):
    prelude = r"""
let contractGprState={source:{sha256:'b'.repeat(64)}};
let contractGprExport={available:true,schema:'contract-gpr-performance-xlsx-v13',mode:'active',draft:false,ticket:'a'.repeat(32),id:'c'.repeat(64),revision:'d'.repeat(64),cut:'2026-03-05',filename:'synthetic-full-book.xlsx'};
const widgets={contractGprDownload:{isConnected:true,disabled:false},contractComparisonFilter:{value:'behind'}};
function $(id){return widgets[id]};let live=true,authEpoch=1,calls=[],downloads=[],messages=[],checks=[];
function hasAuth(){return live};function requireLogin(){throw Error('unexpected login')};
function cumulativeContext(){return{project:'Synthetic',cut:'2026-03-05',key:'synthetic-key',session:'synthetic-owner'}};
function sameCumulativeContext(){return live};function msg(...args){messages.push(args)};
function checkAuthResponse(r,d,key,epoch){checks.push([r.status,key,epoch]);if(r.status===403)live=false};
const URL={createObjectURL:()=>{downloads.push('blob-created');return'blob:local'},revokeObjectURL:()=>{}};
const document={body:{appendChild:()=>{}},createElement:()=>({click(){downloads.push(this.download)},remove(){}})};
let deliver;const ok={ok:true,status:200,headers:{get:()=> 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'},blob:async()=>({size:20})};
globalThis.fetch=(path,options)=>{calls.push({path,method:options.method,redirect:options.redirect,body:JSON.parse(options.body)});return new Promise(resolve=>deliver=resolve)};
"""
    action = {'download':'deliver(ok);',
        'filter_changed':"widgets.contractComparisonFilter.value='all';deliver(ok);",
        'context_changed':'live=false;deliver(ok);',
        'source_changed':"contractGprExport={...contractGprExport,revision:'e'.repeat(64)};deliver(ok);",
        'denied':"deliver({ok:false,status:403,json:async()=>({detail:'Нет доступа'})});",
        'wrong_mime':"deliver({...ok,headers:{get:()=> 'text/html'}});"}[case]
    result=page_blocks.run_json(prelude,"(async()=>{const pending=exportContractGpr();"+action+r"""
await pending;console.log(JSON.stringify({calls,downloads,checks}));})().catch(e=>{console.error(e);process.exit(1)});
""",page=MONITOR_PAGE)
    assert len(result['calls'])==1
    req=result['calls'][0]
    assert req['path']=='/monitor/contracts/gpr.xlsx' and req['method']=='POST' and req['redirect']=='error'
    assert req['body']['ticket']=='a'*32 and req['body']['revision']=='d'*64
    assert not {'rows','planned','fact','deviation','selected_tokens','filter','query'} & req['body'].keys()
    assert result['downloads']==(['blob-created','synthetic-full-book.xlsx'] if case in {'download','filter_changed'} else [])
    if case=='denied': assert result['checks']==[[403,'synthetic-key',1]]

def test_pending_gpr_never_falls_back_to_one_sheet_and_double_click_has_one_request():
    prelude=r"""
let contractGprState={source:null,preview:{schedule:{lines:[{}]}}},contractGprExport={available:false,detail:'Нужна принятая редакция ГПР.'};
const widget={isConnected:true,disabled:false};function $(){return widget};let authEpoch=1,calls=[],messages=[],deliver;
function hasAuth(){return true};function requireLogin(){throw Error('Unexpected login')};function cumulativeContext(){return{project:'Synthetic'}};function sameCumulativeContext(){return true};function msg(...a){messages.push(a)};function checkAuthResponse(){};
globalThis.fetch=(path,options)=>{calls.push(path);return new Promise(resolve=>deliver=resolve)};
"""
    result=page_blocks.run_json(prelude,r"""
(async()=>{await exportContractGpr();const refused=calls.length;
contractGprState={source:{sha256:'b'.repeat(64)}};contractGprExport={available:true,schema:'contract-gpr-performance-xlsx-v13',mode:'active',draft:false,ticket:'a'.repeat(32),revision:'d'.repeat(64)};
const first=exportContractGpr();await exportContractGpr();deliver({ok:false,status:409,json:async()=>({detail:'Источники изменились'})});
await first;console.log(JSON.stringify({refused,calls,messages}));})().catch(e=>{console.error(e);process.exit(1)});
""",page=MONITOR_PAGE)
    assert result['refused']==0 and result['calls']==['/monitor/contracts/gpr.xlsx']
    assert any('принятая редакция' in str(m) for m in result['messages'])

def test_legacy_book_schema_requires_a_fresh_card_without_download_fallback():
    prelude=r"""
const contractGprState={source:{sha256:'b'.repeat(64)}},contractGprExport={available:true,schema:'contract-gpr-performance-xlsx-v11',ticket:'a'.repeat(32)};
const widget={disabled:false,isConnected:true};function $(){return widget};let authEpoch=1,calls=[],messages=[];
function hasAuth(){return true};function requireLogin(){throw Error('Unexpected login')};function cumulativeContext(){return{}};function sameCumulativeContext(){return true};function msg(...a){messages.push(a)};function checkAuthResponse(){};
globalThis.fetch=async(path)=>{calls.push(path);throw Error('Unexpected legacy download')};
"""
    out=page_blocks.run_json(prelude,r"""
(async()=>{await exportContractGpr();console.log(JSON.stringify({calls,messages}));})();
""",page=MONITOR_PAGE)
    assert out['calls']==[]
    assert any('Формат общей книги обновлён' in str(message) for message in out['messages'])

@pytest.mark.parametrize('status',[307,308])
def test_full_book_refuses_redirect_before_replaying_credentials(status):
    prelude='const redirectStatus='+str(status)+';\n'+r"""
let authEpoch=1,calls=[],forwarded=[],downloads=[];
const contractGprState={source:{sha256:'b'.repeat(64)}},contractGprExport={available:true,schema:'contract-gpr-performance-xlsx-v13',mode:'active',draft:false,ticket:'a'.repeat(32),id:'c'.repeat(64),revision:'d'.repeat(64),cut:'2026-03-05'};
const widget={isConnected:true,disabled:false};function $(){return widget};function hasAuth(){return true};function requireLogin(){throw Error('Unexpected login')};function cumulativeContext(){return{key:'synthetic-key',project:'Synthetic'}};function sameCumulativeContext(){return true};function msg(){};function checkAuthResponse(){};
globalThis.fetch=async(path,options)=>{calls.push({path,redirect:options.redirect||'follow',status:redirectStatus});if(options.redirect==='error')throw new TypeError('Redirect refused');forwarded.push(JSON.parse(options.body));return{ok:false,status:500,json:async()=>({})}};
const deny=()=>{throw Error('Actual transport forbidden')};require('http').request=deny;require('https').request=deny;require('net').connect=deny;
"""
    result=page_blocks.run_json(prelude,r"""
(async()=>{await exportContractGpr();console.log(JSON.stringify({calls,forwarded,downloads}));})();
""",page=MONITOR_PAGE)
    assert result['calls']==[{'path':'/monitor/contracts/gpr.xlsx','redirect':'error','status':status}]
    assert result['forwarded']==result['downloads']==[]

def _full_card(cached,contract_id):
    cached=copy.deepcopy(cached);cached['contract_id']=contract_id
    if not cached.get('gpr'): cached['gpr']=gpr.view(PROJECT,contract_id,cached.get('documents') or [],[],CUT)
    state=cached['gpr']
    if state.get('source'):
        state['overlays']=gpr.physical_overlays(cached,cached['rds_comparison'])
        state['presentation']=export.presentation(state['schedule'],state['overlays'],CUT)
        state['workforce']={'contractor':'Synthetic contractor','company_rows':[{'date':CUT,'workers':4,'itr':1,'candidates':[],'reason':'Synthetic observation; not allocated between contracts.'}]}
    cached['gpr_export']=export.bind_snapshot(PROJECT,CUT,contract_id,cached,{'contract':'Т-1'})
    return cached

def _browser_export(page,cached,contract_id,key,calls):
    cached.update(_full_card(cached,contract_id))
    def documents(route):
        body=route.request.post_data_json
        assert body['project']==PROJECT and body['cut']==CUT and body['contract_id']==contract_id
        route.fulfill(json={**cached,'ticket':body['ticket']})
    def download(route):
        body=route.request.post_data_json;calls.append(body)
        assert body['key']==key and body['revision']==cached['gpr_export']['revision']
        assert not {'rows','filter','query','selected_tokens'} & body.keys()
        route.fulfill(body=export.workbook(cached['gpr_export'],cached),content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    page.route('**/monitor/contracts/documents',documents)
    page.route('**/monitor/contracts/gpr.xlsx',download)
    page.locator('#cut').fill(CUT);page.locator('#contractsTab').click()
    page.locator(f'tr[data-contract-id="{contract_id}"] .contract-open').click()
    page.locator('#contractGprDownload').wait_for(state='visible')
    page.locator('#contractExecution > summary').click()

@pytest.mark.parametrize('width',[390,1440])
def test_one_button_downloads_native_full_book_even_when_comparison_is_filtered(width,tmp_path):
    from playwright.sync_api import expect
    from tests.test_monitor_cumulative_controls import browser_page,CONTRACT,KEY
    calls=[]
    with browser_page(width) as (page,_,errors):
        _browser_export(page,native_card(),CONTRACT,KEY,calls)
        expect(page.locator('#contractComparisonExport')).to_have_count(0)
        expect(page.locator('#contractComparisonGprExport')).to_have_count(0)
        page.locator('#contractComparisonSearch').fill('нулевым')
        with page.expect_download() as got: page.locator('#contractGprDownload').click()
        target=tmp_path/'full-contract.xlsx';got.value.save_as(target);book=load_workbook(target)
        assert book.sheetnames == ['ГПР','Выполнение','Численность подрядчика']
        assert book['Выполнение']['H8'].value==0
        assert any('Кладка стен' in str(c.value) for row in book['Выполнение'] for c in row)
        assert len(calls)==1 and not errors

def test_browser_without_gpr_does_not_offer_one_sheet_instead():
    from playwright.sync_api import expect
    from tests.test_monitor_cumulative_controls import browser_page,CONTRACT,KEY
    calls=[]
    with browser_page(390) as (page,_,errors):
        _browser_export(page,native_card(empty=True),CONTRACT,KEY,calls)
        expect(page.locator('#contractGprDownload')).to_be_disabled()
        expect(page.locator('#contractComparisonExport')).to_have_count(0)
        assert calls==[] and not errors


def test_node_normal_reopen_uses_a_fresh_ticket_after_a_legacy_completed_result():
    prelude = r"""
let calls=[],counter=0;function cumulativeNonce(){return String(++counter).repeat(32)};
async function post(path,body){calls.push(body.ticket);return{pending:false,ok:true,ticket:body.ticket,...(calls.length===2?{comparison_export:{available:true}}:{})}};
async function cumulativePause(){throw Error('unexpected poll')};
"""
    # The generic extractor stops at the default options={} argument. Take
    # the complete native declaration, including its multi-line body.
    start = MONITOR_PAGE.index("async function cumulativeJob(")
    end = MONITOR_PAGE.index("\nfunction sourceLabel(", start)
    prelude += MONITOR_PAGE[start:end] + "\n"
    tail = r"""
(async()=>{const old=await cumulativeJob('/documents','/result',{project:'Synthetic'},()=>true);
const fresh=await cumulativeJob('/documents','/result',{project:'Synthetic'},()=>true);
console.log(JSON.stringify({tickets:calls,oldHasBinding:!!old.comparison_export,freshHasBinding:!!fresh.comparison_export}));})();
"""
    result = page_blocks.run_json(prelude, tail, page=MONITOR_PAGE)
    assert result == {"tickets": ["1" * 32, "2" * 32], "oldHasBinding": False, "freshHasBinding": True}
