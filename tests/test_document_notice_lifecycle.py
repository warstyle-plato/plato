"""Native PAGE notice lifecycle: replaced/unavailable results vs current evidence."""
import copy,json
import pytest
from tests import page_blocks
from test_a_saved_project_is_written_over import STUBS
from test_document_qualification import core,document
import intake_qualification as qualification

DOM=r'''
const nodes={};
function element(){return {style:{},classList:{add(){},remove(){}},children:[],setAttribute(){},
 querySelectorAll(){return[]},replaceChildren(...children){this.children=children},remove(){delete nodes[this.id]}}}
const anchor=element();anchor.parentNode={insertBefore(node){nodes[node.id]=node}};
nodes.calcLocked=element();nodes.report=element();nodes.calcAccessLine=element();
const document={getElementById:id=>nodes[id]||null,querySelector:()=>anchor,querySelectorAll:()=>[],createElement:()=>element()};
function projectsCall(){return Promise.resolve({id:'synthetic-clean',name:'Synthetic clean project',payload:{inputs:{land_right:'ownership',vri_region:'mo'},tep:{}}})}
'''


def run(tail):
    stand=STUBS.replace('function renderCalculationQualification(){}','')
    return page_blocks.run_json(stand+DOM,tail,page=core.PAGE)


@pytest.mark.parametrize('action',['replace','refuse'])
def test_old_generic_notice_is_removed_when_the_result_no_longer_belongs_to_the_page(action):
    state=qualification.state({qualification.KEY:None},lambda _:b'synthetic-key')
    got=run(r'''
(async()=>{
 inputs._intake_qualification={invalid:'retained until project replacement'};
 const before=JSON.stringify(inputs);
 renderCalculationQualification({summary:{intake_qualification:STATE}});
 const originallyPresent=!!nodes.documentQualificationNotice;
 if(ACTION==='replace')await loadProject('synthetic-clean');else renderCalcLocked('Synthetic refused calculation',401);
 console.log(JSON.stringify({originallyPresent,present:!!nodes.documentQualificationNotice,
  inputsUnchanged:before===JSON.stringify(inputs),hasRecord:Object.hasOwn(inputs,'_intake_qualification'),result:lastResult}));
})().catch(e=>{console.error(e);process.exit(1)});
'''.replace('STATE',json.dumps(state,ensure_ascii=False)).replace('ACTION',json.dumps(action)))
    assert got['originallyPresent']
    assert not got['present'],got
    if action=='replace':assert not got['hasRecord']
    else:assert got['inputsUnchanged']and got['hasRecord']and got['result']is None


@pytest.mark.parametrize('invalid',[False,True],ids=['conditional','invalid-record'])
def test_a_current_successful_result_keeps_or_recreates_its_warning(document,invalid):
    item=document();inputs=copy.deepcopy(item['inputs'])
    if invalid:inputs[qualification.KEY]['signature']='0'*64
    state=core._intake_qualification_state(inputs)
    assert state['status']==('review_required'if invalid else'conditional')
    got=run(r'''
(async()=>{
 inputs=MODEL;const before=JSON.stringify(inputs);
 const result={summary:{intake_qualification:STATE}};
 renderCalculationQualification(result);const first=!!nodes.documentQualificationNotice;
 renderCalculationQualification(result);const retained=!!nodes.documentQualificationNotice;
 renderCalcLocked('Synthetic refused calculation',401);const cleared= !nodes.documentQualificationNotice;
 renderCalculationQualification(result);const again=nodes.documentQualificationNotice;
 console.log(JSON.stringify({first,retained,cleared,again:!!again,
  reason:again?again.children[1].textContent:'',unchanged:before===JSON.stringify(inputs)}));
})().catch(e=>{console.error(e);process.exit(1)});
'''.replace('MODEL',json.dumps(inputs,ensure_ascii=False)).replace('STATE',json.dumps(state,ensure_ascii=False)))
    assert got['first']and got['retained']and got['cleared']and got['again']and got['unchanged'],got
    assert got['reason']==state['reason']
    if not invalid:assert '275 м²'in got['reason']and 'не включена'in got['reason']
