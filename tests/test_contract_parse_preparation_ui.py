"""Native Monitor PAGE prepares a finite corpus, then reads one new register."""
import pytest

from tests import page_blocks
from developaid_monitor_page import MONITOR_PAGE


@pytest.mark.parametrize('case', ['complete', 'stalled', 'network_resume', 'context_changed'])
def test_native_helper_keeps_finite_progress_and_same_ticket_on_resume(case):
    prelude = r'''
let contractParsePreparation=null,nonce=0,calls=[],messages=[],active=true,fail=true;
function sameCumulativeContext(){return active}function cumulativeNonce(){return String(++nonce).padStart(32,'0')}
function msg(...args){messages.push(args)}
const c={project:'Synthetic',cut:'2026-11-26'};
const response=(remaining,processed,guard)=>({parse_refresh:{remaining,processed,guard:guard.repeat(64),done:remaining===0,limit:256}});
async function cumulativeJob(path,result,body,current,waiting,options){
 calls.push({path,result,guard:body.expected_guard,ticket:options.ticket});
 if(calls.length===1)return response(2,0,'a');
 if(CASE==='network_resume'&&fail){fail=false;throw new TypeError('Synthetic interrupted transport')}
 if(CASE==='context_changed'){active=false;return response(1,1,'b')}
 if(CASE==='stalled')return response(2,1,'b');
 return body.expected_guard==='a'.repeat(64)?response(1,1,'b'):response(0,1,'c');
}
'''.replace('CASE', repr(case))
    # The helper's transport/context are deliberately stubbed above; import
    # its complete native declaration without resolving unrelated PAGE locals.
    prelude += page_blocks.function('prepareContractParses', page=MONITOR_PAGE)+'\n'
    tail = r'''
(async()=>{let first,error=null,second=null;try{first=await prepareContractParses(c,()=>active)}catch(e){error=e.message}
if(CASE==='network_resume')second=await prepareContractParses(c,()=>active);
console.log(JSON.stringify({first,error,second,calls,messages,state:contractParsePreparation}));})().catch(e=>{console.error(e);process.exit(1)});
'''.replace('CASE', repr(case))
    result = page_blocks.run_json(prelude, tail, page=MONITOR_PAGE)
    calls = result['calls']
    assert calls[0]['guard'] == ''
    if case == 'complete':
        assert result['first'] is True and result['state'] is None
        assert [c['guard'] for c in calls] == ['', 'a'*64, 'b'*64]
        assert len({c['ticket'] for c in calls}) == 3
    elif case == 'network_resume':
        assert result['second'] is True and len(calls) == 4
        assert calls[1]['ticket'] == calls[2]['ticket']
        assert calls[1]['guard'] == calls[2]['guard'] == 'a'*64
    elif case == 'stalled':
        assert result['state'] is None and len(calls) == 2
        assert 'Состав' in result['error'] and '0 из 2' in result['error']
    else:
        assert result['first'] is False and len(calls) == 2


@pytest.mark.parametrize('width', [390, 1440])
@pytest.mark.parametrize('changed', [False, True])
def test_native_page_sequences_one_pdf_jobs_or_shows_partial_source_change(width, changed):
    from playwright.sync_api import expect
    from tests.test_monitor_cumulative_controls import browser_page, CONTRACT
    with browser_page(width) as (page, responses, errors):
        builds, reads = [], []
        def build(route):
            body = route.request.post_data_json
            builds.append(body)
            if len(builds) == 1:
                return route.fulfill(json={'pending': False, 'ticket': body['ticket'], 'ok': False,
                    'parse_refresh_required': True, 'detail': 'Synthetic bounded refresh is required.'})
            return route.fulfill(json={'pending': False, 'ticket': body['ticket'], 'ok': True,
                                      'register': responses.data})
        def prepare(route):
            body = route.request.post_data_json
            reads.append(body)
            if changed and len(reads) == 3:
                return route.fulfill(json={'pending': False, 'ticket': body['ticket'], 'ok': False,
                    'detail': 'Источники изменились. Обновите договоры.'})
            remaining = 3-len(reads)
            return route.fulfill(json={'pending': False, 'ticket': body['ticket'], 'ok': True,
                'parse_refresh': {'guard': chr(96+len(reads))*64, 'remaining': remaining,
                    'processed': 0 if len(reads)==1 else 1, 'limit': 256, 'done': remaining==0}})
        page.route('**/monitor/contracts/build', build)
        page.route('**/monitor/contracts/parse-refresh', prepare)
        page.locator('#contractsTab').click()
        if changed:
            expect(page.locator('#contractsMsg')).to_contain_text('Прочитано документов: 1 из 2')
            expect(page.locator('#contractsMsg')).to_contain_text('Источники изменились')
            assert len(builds) == 1
        else:
            expect(page.locator(f'tr[data-contract-id="{CONTRACT}"]')).to_be_visible()
            assert len(builds) == 2 and builds[0]['ticket'] != builds[1]['ticket']
        assert [r['expected_guard'] for r in reads] == ['', 'a'*64, 'b'*64]
        assert len({r['ticket'] for r in reads}) == 3
        assert not errors
