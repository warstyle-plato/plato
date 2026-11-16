"""Actual PAGE chooser and raw-card dispatch in NodeVM, without importing the app."""
from __future__ import annotations

import ast
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


def page_literal(source=None):
    source = source or (ROOT / "developaid_monitor_page.py").read_text()
    return next(node.value for node in ast.walk(ast.parse(source))
                if isinstance(node, ast.Constant) and isinstance(node.value, str)
                and node.value.startswith("<!doctype html>"))


def offline_page_blocks():
    # Reuse the existing resolver/runner, including its dependency discovery.
    # Its default PAGE import starts the app, so load its helpers without that
    # import and always supply the actual Monitor PAGE literal explicitly.
    path = ROOT / "tests" / "page_blocks.py"
    tree = ast.parse(path.read_text())
    tree.body = [node for node in tree.body if not (
        isinstance(node, ast.Import) and any(alias.name == "main_legacy" for alias in node.names))]
    namespace = {"__file__": str(path), "__name__": "offline_page_blocks"}
    exec(compile(tree, str(path), "exec"), namespace)
    return SimpleNamespace(**namespace)


DOM_AND_BOUNDARIES = r"""
const calls=[],nodes=new Map();
class Element{
 constructor(id){this.id=id;this.open=false;this.value='';this.isConnected=true;this.children=[];this.html='';this.classList={add(){},remove(){}};}
 set innerHTML(value){for(const id of this.children)nodes.delete(id);this.children=[];this.html=value;
  for(const match of value.matchAll(/\bid="([^"]+)"/g)){this.children.push(match[1]);nodes.set(match[1],new Element(match[1]));}}
 get innerHTML(){return this.html;}
 replaceChildren(){this.innerHTML='';this.onclick=null;}
 querySelectorAll(){return [];}
 showModal(){this.open=true;}
 close(){this.open=false;}
 focus(){}
 closest(){return this.id==='tableOpener'?this:null;}
}
for(const id of ['contractsDetails','contractDialog','contractDialogTitle','contractDialogDocuments','contractDialogScroll',
 'contractsTerm','contractsHeaderDate','contractsTermDate','contractsTermNote','contractsHeaderDateValue','contractsHeaderDateNote',
 'contractsTermTitle','contractsTermMsg','contractsHeaderDateTitle','contractsHeaderDateMsg','tableOpener'])nodes.set(id,new Element(id));
const document={getElementById:id=>nodes.get(id)||null,activeElement:nodes.get('tableOpener'),
 body:{classList:{add(){},remove(){}}},querySelector:()=>nodes.get('tableOpener')};
const CSS={escape:String};
let contractRegister,contractDialogOpener=null,contractDialogContext=null,contractComparisonState=null,contractComparisonExport=null,
 contractDocumentsRequest=0,contractDocumentsState={id:'',list:[]},editingContract=null,editingHeaderDate=null;
function cumulativeContext(){return {project:'Synthetic',cut:'2026-11-16'};}
function sameCumulativeContext(){return true;}
function forbidden(){throw new Error('No transport, credentials or mutations in this stand');}
const fetch=forbidden,post=forbidden,cumulativeJob=forbidden,hasAuth=forbidden,requireLogin=forbidden,
 uploadContractDocument=forbidden,openContractTerm=forbidden;
const contractReportSignalAction=undefined,runContractReportCheck=undefined;
function loadContractDocuments(id){calls.push(['documents',id]);}
function contractCardSummary(row){calls.push(['summary',row.id]);return '<p>RAW_CARD_SUMMARY</p>';}
function contractFinancialSourceHtml(row){calls.push(['financial',row.id]);return '<p>RAW_CARD_FINANCE</p>';}
function contractPhysicalSourceHtml(){return '';}
function contractCarriedHtml(){return '';}
function contractComparisonShell(){return '';}
function contractUploadBlock(){return '<button id="contractDocumentUpload"></button><input id="contractKs2File"><button id="contractKs2Upload"></button>';}
function contractDocumentsBlock(){return '<div id="contractDocuments"></div>';}
function contractNextStep(){return '';}
function manualDeadlineReferenceHtml(){return '';}
function contractSourcesHtml(){return '';}
function reconciliationDates(){return '';}
function contractLabelCells(){}
function bindEvidenceControls(){}
"""


FIXTURE_AND_ASSERTIONS = r"""
const A='a'.repeat(64),B='b'.repeat(64),L='c'.repeat(64);
const first={id:A,source_kind:'cumulative',contract:'Исходная А',contractor:'Синтетический подрядчик',contract_date:'2026-01-01',source_date:'2026-11-01'};
const second={...first,id:B,contract:'Исходная Б'};
const state={status:'confirmed',logical_id:L,member_ids:[A,B]};
const logical={id:L,source_kind:'logical_ownership',raw_member_ids:[A,B],raw_observations:[first,second],
 logical_ownership:{resolution_status:'confirmed'},amount:999999999};
contractRegister={rows:[logical],raw_rows:[first,second],logical_ownership:{states:{[A]:state,[B]:state}}};
const scenario=SCENARIO;
if(scenario==='chooser'){
 openContractDetails(L);
 const host=nodes.get('contractsDetails'),html=host.innerHTML;
 assert.equal(nodes.get('contractDialog').open,true,'logical row must open the chooser');
 assert.ok(html.includes('Выберите исходную карточку договора'));
 assert.ok(html.includes('Финансовый источник, срок и общий прогноз между ними не выбраны'));
 assert.equal((html.match(/data-raw-contract=/g)||[]).length,2);
 assert.ok(html.includes('data-raw-contract="'+A+'"')&&html.includes('data-raw-contract="'+B+'"'));
 assert.ok(!html.includes('999999999')&&!html.includes('RAW_CARD_')&&!html.includes('aria-current'));
 assert.equal(nodes.get('contractDialogDocuments').disabled,true);
 assert.deepEqual(calls,[],'chooser must not pick a card or request documents');
 host.onclick({target:{closest:selector=>selector==='[data-raw-contract]'?{dataset:{rawContract:B}}:null}});
 assert.deepEqual(calls,[['summary',B],['financial',B],['documents',B]],'explicit second-card choice uses the existing raw path');
 assert.ok(nodes.get('contractsDetails').innerHTML.includes('aria-current="true"'));
 assert.equal(nodes.get('contractDialogDocuments').disabled,false);
}else if(scenario==='raw'||scenario==='unknown-ownership'){
 if(scenario==='raw')contractRegister={rows:[first]};
 else{state.status='source_conflict';logical.id=A;logical.logical_ownership.resolution_status='source_conflict';}
 openContractDetails(A);
 assert.equal(nodes.get('contractDialog').open,true);
 assert.deepEqual(calls,[['summary',A],['financial',A],['documents',A]]);
 assert.ok(!nodes.get('contractsDetails').innerHTML.includes('Выберите исходную карточку договора'));
}else{
 if(scenario==='unconfirmed-logical'){
  logical.logical_ownership.resolution_status='source_conflict';state.status='source_conflict';
 }
 openContractDetails(scenario==='unknown-id'?'d'.repeat(64):L);
 assert.equal(nodes.get('contractDialog').open,false);
 assert.deepEqual(calls,[]);
}
console.log('ok');
"""


def run_native(scenario, page=None):
    page = page or page_literal()
    helpers = offline_page_blocks()
    # Dependencies come from PAGE and the shared resolver, never a second copy
    # of the chooser logic. Only DOM, finance rendering and transport boundaries
    # are supplied above; the native open/close/dialog/ownership code runs in VM.
    # The runner inserts native pieces inside this function. Its complete
    # source then executes in a VM that has no require/process/network access.
    prelude = "const vm=require('node:vm'),assert=require('node:assert/strict');\nfunction stand(){\n" + DOM_AND_BOUNDARIES
    tail = FIXTURE_AND_ASSERTIONS.replace("SCENARIO", json.dumps(scenario))
    # The existing runner bounds the child process. A VM watchdog would add
    # another native thread, unnecessary for these fixed synthetic scenarios.
    tail += "\n}\nvm.runInNewContext('('+stand.toString()+')()',{assert,console});"
    output, _ = helpers.run(prelude, tail, page=page)
    assert output.strip() == "ok"


@pytest.mark.parametrize("scenario", ["chooser", "raw", "unknown-ownership", "unknown-id", "unconfirmed-logical"])
def test_native_page_logical_chooser_and_existing_raw_dispatch(scenario):
    run_native(scenario)
