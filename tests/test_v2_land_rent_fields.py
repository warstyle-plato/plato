"""Synthetic territory transfer and the actual V2 draft preserve rent inputs."""
import copy
import json
import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import developaid_v2_form as v2form
from developaid_v2 import install
import main
from tests import page_blocks

core=main.core
DATES={'housing':'2029-08-05','phase:0:offices':'2030-07-01'}


@pytest.fixture(autouse=True)
def no_source_parser(monkeypatch):
    monkeypatch.setattr(core,'parse_glavapu_xlsx',lambda *a,**k:pytest.fail('synthetic normalized payload must not read or parse a source workbook'))


def synthetic_territory():
    return {'source':{'kind':'synthetic'},'normalized':{'site_area_ha':1.25,
        'density_spp_th_sqm_ha':12,'cadastral_quarter':'77:01:0000001'},
        'recognized':['77:01:0000001:11'],'warnings':[],
        'mappings':{'inputs':{'vri_region':'msk','land_right':'lease','land_rights_cost_mln':0},
                    'tep':{'apartments':{'gns':12000,'total_area':11000,'saleable':9000,'units':120}}}}


def main_page(parsed,extra=None,action=None):
    keys=re.search(r'(const TERRITORY_INPUT_KEYS=.*?)\nfunction resetTerritoryData',core.PAGE,re.S)
    body=re.search(r'(function resetTerritoryData\(.*?)\nfunction getGlavapuUnderground',core.PAGE,re.S)
    assert keys and body
    inputs={**copy.deepcopy(core.DEFAULT_INPUTS),'vri_region':'msk',**(extra or {})}
    stubs="""
const document={getElementById:()=>({style:{},innerHTML:''})};
const glavapuStatus={innerHTML:''};let phasing=null,cadastralAnalysis=null,moResult=null;
function makeDefaultPhasing(){return {enabled:false,phase_count:1}}
function applyRequiredSocialProgramFromGlavapu(){} function syncTep(){}
function repairParkingFromGlavapu(){} function applyTelegramCalcOverrides(){}
function renderInputs(){} function renderTep(){} function renderPhasing(){}
function renderGlavapuPreview(){} function fillUndergroundFromTep(){}
function getGlavapuUnderground(){return null}
async function calculate(){} async function sendTelegramResult(){}
"""
    prelude=(f'const payload={json.dumps(parsed)};let inputs={json.dumps(inputs)};'
        f'let tep={json.dumps(core.TEP_DEFAULT)};let glavapuImport=null;'+stubs+
        page_blocks.krt_lock()+'\n'+keys.group(1)+'\n'+body.group(1))
    action=action or 'glavapuImport=payload;await applyGlavapu();'
    return page_blocks.run_json(prelude,'(async()=>{'+action+'console.log(JSON.stringify({inputs,tep}));})()')


def test_synthetic_normalized_transfer_matches_main_page_without_source_workbook():
    parsed=synthetic_territory()
    expected=v2form.inputs_from_glavapu(core,copy.deepcopy(parsed))
    actual=main_page(parsed)
    for key in sorted(set(actual['inputs'])|set(expected['inputs'])):
        if not key.startswith('_'):
            assert actual['inputs'].get(key)==expected['inputs'].get(key),key
    for row in expected['tep']:
        for field in ('gns','total_area','useful','saleable','transfer','units'):
            assert actual['tep'][row].get(field,0)==expected['tep'][row].get(field,0),(row,field)
    assert actual['inputs']['land_rent_registration_months']==3
    assert actual['inputs']['land_rent_exposure_exit_dates']=={}


def test_new_territory_discards_previous_contract_and_restores_fresh_canonical_defaults():
    actual=main_page(synthetic_territory(),{'land_rent_registration_months':6,
        'land_rent_exposure_exit_dates':DATES,'land_rent_mode':'manual','land_rent_cadastral_mln':654})
    assert actual['inputs']['land_rent_registration_months']==3
    assert actual['inputs']['land_rent_exposure_exit_dates']=={}
    assert 'land_rent_cadastral_mln' not in actual['inputs']


@pytest.mark.parametrize('keep',[False,True])
def test_same_territory_and_explicit_keep_lease_terms_preserve_manual_values(keep):
    action=('glavapuImport=payload;await applyGlavapu();'
        f'inputs.land_rent_registration_months=6;inputs.land_rent_exposure_exit_dates={json.dumps(DATES)};')
    action+=('resetTerritoryData({keepLeaseTerms:true,keepPhasing:true});' if keep else
             'glavapuImport=payload;await applyGlavapu();')
    actual=main_page(synthetic_territory(),action=action)
    assert actual['inputs']['land_rent_registration_months']==6
    assert actual['inputs']['land_rent_exposure_exit_dates']==DATES


@pytest.fixture
def description():
    app=FastAPI();install(app)
    response=TestClient(app).get('/api/v2/form')
    assert response.status_code==200
    assert response.headers['cache-control']=='no-store, no-cache, must-revalidate, max-age=0'
    return response.json()


def test_v2_form_declares_the_scalar_editor_and_existing_object_date_owner(description):
    block=next(b for b in description['blocks'] if b['key']=='land_rent')
    fields={f['key']:f for f in block['fields']}
    registration=fields['land_rent_registration_months']
    assert registration['type']=='number'
    assert (registration['min'],registration['max'],registration['step'])==(0,120,1)
    dates=fields['land_rent_exposure_exit_dates']
    assert dates['type']=='preserved' and dates['owner']=='landRentExposureHtml'
    assert page_blocks.function(dates['owner'])
    assert 'полной версии расчёта' in dates['description']


def test_actual_v2_draft_edit_submit_reload_keeps_typed_object_dates(description):
    script=(Path(__file__).resolve().parents[1]/'frontend_v2'/'app.js').read_text()
    functions='\n'.join(page_blocks.function(name,script) for name in
        ('draftFromResult','fieldControl','fieldRow','renderInputsBlock','submitDraft','calculateProject'))
    request={'inputs':{'land_rent_registration_months':6,'land_rent_exposure_exit_dates':DATES},
             'tep':{},'phasing':{}}
    stubs="""
class Node {
 constructor(tag){this.tagName=tag;this.children=[];this.listeners={};this.dataset={};this.textContent=''}
 addEventListener(key,callback){this.listeners[key]=callback}
 appendChild(node){this.children.push(node);return node}
 append(...nodes){nodes.forEach(node=>this.appendChild(node))}
 setAttribute(key,value){this[key]=value}
}
const document={createElement:tag=>new Node(tag)};
const status={textContent:''};function $(id){if(id==='#inputStatus')return status;throw Error(id)}
function setView(){} function renderResult(result){state.result=result}
const requests=[];
async function fetch(url,options){requests.push(JSON.parse(options.body));return {
 ok:true,json:async()=>({request:requests[requests.length-1],project:{name:'Synthetic'}})}}
function descendants(node){return [node,...node.children.flatMap(descendants)]}
"""
    declaration=re.search(r'^const form\s*=\s*.*;$',script,re.M)
    assert declaration, 'actual V2 form state declaration must be present'
    prelude=(stubs+declaration.group(0)+
        f'const description={json.dumps(description)};const state={{result:{{request:{json.dumps(request)}}}}};'+functions)
    tail="""
(async()=>{
 form.defaults=description.defaults;form.draft=draftFromResult(state.result);
 const block=description.blocks.find(b=>b.key==='land_rent');const controls=[];
 for(const value of [0,6]){
  const host=new Node('div');renderInputsBlock(block,host);const nodes=descendants(host);
  const scalar=nodes.find(n=>n.id==='f_land_rent_registration_months');
  const dates=nodes.find(n=>n.id==='f_land_rent_exposure_exit_dates');
  controls.push({type:scalar.type,step:scalar.step,min:scalar.min,max:scalar.max,
   dateTag:dates.tagName,dateOwner:dates.dataset.fieldOwner,
   text:nodes.map(n=>n.textContent).join(' '),dateHandlers:Object.keys(dates.listeners)});
  scalar.value=String(value);scalar.listeners.change();await submitDraft();
  form.draft=draftFromResult(state.result);
 }
 console.log(JSON.stringify({requests,controls,draft:form.draft,original:state.result.request}));
})()
"""
    actual=page_blocks.run_json(prelude,tail,page=script)
    assert [r['inputs']['land_rent_registration_months'] for r in actual['requests']]==[0,6]
    for request in actual['requests']:
        assert request['inputs']['land_rent_exposure_exit_dates']==DATES
    assert actual['draft']['inputs']['land_rent_exposure_exit_dates']==DATES
    assert actual['draft']['inputs']['land_rent_registration_months']==6
    for control in actual['controls']:
        assert (control['type'],control['step'],control['min'],control['max'])==('number','1','0','120')
        assert control['dateTag']=='span' and control['dateOwner']=='landRentExposureHtml'
        assert control['dateHandlers']==[]
        assert '[object Object]' not in control['text'] and 'housing' not in control['text']
        assert 'phase:0:offices' not in control['text'] and '2029-08-05' not in control['text']
