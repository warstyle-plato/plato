"""Final delivery is bounded and ambiguous delivery is never auto-retried."""
from __future__ import annotations

import json
import shutil
import subprocess

import pytest
import main

core = main.core


def send_source():
    start = core.PAGE.index('async function sendTelegramResult(){')
    return core.PAGE[start:core.PAGE.index('\n}\n',start)+3]


def probe(mode, *, repeat=False, explicit=False, caller=None):
    script = '''
let inputs={_manual_tep_import:{project_name:'Synthetic'}},tep={},lastResult={summary:{},report:{financing:{}}};
let telegramSession='synthetic',telegramResultSent=false,telegramMode='',cadastralAnalysis=null,phaseBundle=null,telegramEditSubmitting=false;
let timers=new Map(),nextTimer=0,progress=[],finished=[],status={innerHTML:''},calls=0;
const document={getElementById:()=>status},window={};
function withoutHousing(){return false}
function persistLocalSilently(){}
function tepSourceLabel(){return 'Synthetic'}
function parkingProvisionText(){return 'Synthetic'}
function telegramParkingByKind(){return {}}
function irrEquityNa(){return 'Unknown'}
function currentPdfReportPayload(){return {}}
function serverDetail(x){return x?.detail||''}
function escapeHtml(x){return String(x)}
function telegramProgress(x){progress.push(x)}
function finishTelegramSession(x){finished.push(x)}
function setTimeout(fn,ms){const id=++nextTimer;timers.set(id,{fn,ms});return id}
function clearTimeout(id){timers.delete(id)}
function showTelegramResendButton(){} async function calculate(){} function openTab(){}
'''
    responses = {
        'pending': 'return new Promise(()=>{})',
        'body_pending': 'return Promise.resolve({ok:true,json:()=>new Promise(()=>{})})',
        'http_error': "return Promise.resolve({ok:false,status:503,json:()=>Promise.resolve({detail:'Synthetic upstream failure'})})",
        'denied': "return Promise.resolve({ok:false,status:403,json:()=>Promise.resolve({detail:'Synthetic access denied'})})",
        'invalid_json': "return Promise.resolve({ok:true,json:()=>Promise.reject(new Error('Synthetic invalid JSON'))})",
        'invalid_schema': 'return Promise.resolve({ok:true,json:()=>Promise.resolve({})})',
        'success': 'return Promise.resolve({ok:true,json:()=>Promise.resolve({ok:true})})',
    }
    script += 'function fetch(){calls++;'+responses[mode]+'}\n'+send_source()+'\n'
    if caller:
        import page_blocks
        script += page_blocks.function(caller,core.PAGE)+'\n'
    script += '''
async function flush(){for(let i=0;i<30;i++)await Promise.resolve()}
(async()=>{
 let settled=false;
 const first=CALL.then(()=>settled=true);
 await flush();
 for(const [id,timer]of Array.from(timers)){if(timers.has(id)){timers.delete(id);timer.fn()}}
 await flush();
 const afterFirst={settled,sent:telegramResultSent,progress:[...progress],finished:[...finished],status:status.innerHTML,calls,uncertain:!!sendTelegramResult.uncertain};
'''
    invocation = "telegramRecalculateAndFinish('report')" if caller=='telegramRecalculateAndFinish' else 'submitTelegramEditedResult()' if caller else 'sendTelegramResult()'
    script=script.replace('CALL',invocation)
    if repeat:
        script += 'telegramEditSubmitting='+json.dumps(explicit)+';\n'
        if explicit:
            script += "fetch=function(){calls++;return Promise.resolve({ok:true,json:()=>Promise.resolve({ok:true})})};\n"
        script += 'await sendTelegramResult();await flush();\n'
    script += 'console.log(JSON.stringify({first:afterFirst,calls,sent:telegramResultSent,finished}));})();'
    node = shutil.which('node')
    assert node,'Node is required for native PAGE regression'
    done = subprocess.run([node,'-e',script],capture_output=True,text=True,timeout=10)
    assert done.returncode == 0,done.stderr
    return json.loads(done.stdout)


@pytest.mark.parametrize('mode',['pending','body_pending'])
def test_deadline_finishes_even_when_transport_or_body_never_resolves(mode):
    outcome = probe(mode)
    assert outcome['first']['settled']
    assert not outcome['sent'] and not outcome['finished']
    assert outcome['first']['progress'][-1] == ''
    assert outcome['first']['uncertain']
    assert 'Доставка неизвестна' in outcome['first']['status']


@pytest.mark.parametrize('mode',['pending','http_error','invalid_json','invalid_schema'])
def test_ambiguous_delivery_is_not_retried_by_an_automatic_second_call(mode):
    outcome = probe(mode,repeat=True)
    assert outcome['calls'] == 1
    assert not outcome['sent'] and not outcome['finished']


def test_only_explicit_user_retry_may_send_after_an_unknown_outcome():
    outcome = probe('pending',repeat=True,explicit=True)
    assert outcome['first']['uncertain'] and not outcome['first']['sent']
    assert outcome['calls'] == 2 and outcome['sent']
    assert len(outcome['finished']) == 1


def test_confirmed_access_denial_does_not_claim_ambiguous_delivery():
    outcome = probe('denied')
    assert not outcome['first']['uncertain'] and not outcome['sent']
    assert not outcome['finished'] and 'access denied' in outcome['first']['status']


def test_success_clears_the_existing_deadline_and_closes_once():
    outcome = probe('success',repeat=True)
    assert outcome['first']['settled'] and outcome['sent']
    assert len(outcome['finished']) == 1 and outcome['calls'] == 1
    assert 'придут следом' in outcome['first']['status']


def test_final_server_reply_uses_canonical_html_splitter_and_last_part_button(monkeypatch):
    chat = 900000002
    monkeypatch.setattr(core,'_telegram_verify_session',lambda *_:{'chat_id':chat,'cad':[]})
    monkeypatch.setattr(core,'_telegram_user_allowed',lambda *_:True)
    monkeypatch.setattr(core,'calc_access_for_chat',lambda *args,**kwargs:None)
    monkeypatch.setattr(core,'_telegram_web_app_url',lambda *args,**kwargs:'https://example.invalid/synthetic')
    delivered=[]
    def send(identifier,text,**kwargs):
        assert identifier == chat
        assert len(text.encode('utf-16-le'))//2 <= 4096
        delivered.append((text,kwargs.get('reply_markup')))
    monkeypatch.setattr(core,'_telegram_send_message',send)
    title='Synthetic project '+('🌳'*3000)
    request=core.TelegramResultRequest(session='synthetic',summary={'project_name':title})
    assert core.telegram_result(request)['ok']
    assert len(delivered)>1
    assert sum(text.count('🌳')for text,_ in delivered) == 3000
    assert all(markup is None for _,markup in delivered[:-1])
    assert delivered[-1][1]['inline_keyboard']


@pytest.mark.parametrize('caller',['telegramRecalculateAndFinish','submitTelegramEditedResult'])
@pytest.mark.parametrize('mode',['pending','body_pending'])
def test_actual_entry_callers_preserve_the_unknown_delivery_reason(caller,mode):
    outcome = probe(mode,caller=caller)
    assert outcome['first']['settled'] and not outcome['sent'] and not outcome['finished']
    assert outcome['first']['uncertain']
    assert 'Доставка неизвестна' in outcome['first']['status']
    assert 'проверьте чат' in outcome['first']['status'].lower()
