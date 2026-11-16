"""Lossless compression reduces transfer bytes; raw limits and recovery survive."""
import base64
import gzip
import json
import random

import pytest
from playwright.sync_api import expect

import developaid_management_report_jobs as jobs
from test_contract_register_result_budget import OWNER, PROFILE, PARAMS, terminal
from test_monitor_cumulative_api import api, post, core
from test_monitor_cumulative_controls import browser_page, CONTRACT


def collect(store,ticket,**options):
    parts=[];offset=0;metadata=None
    while True:
        response=store.poll_part(ticket,OWNER,PROFILE,offset,**options)
        value=response['result_part']
        assert value['offset']==offset
        assert len(json.dumps(response))<360000
        part=base64.b64decode(value['content_base64'],validate=True)
        parts.append(part);offset+=len(part);metadata=value
        if offset==value['total_bytes']:break
    return b''.join(parts),metadata


def test_compressed_and_identity_transfers_preserve_every_byte_and_original_budget(tmp_path):
    store=jobs.Store(tmp_path/'jobs')
    payload={'ok':True,'register':{'rows':[{'history':'Источник №42 🚧'*700000}]}}
    ticket=store.start(OWNER,PROFILE,PARAMS,lambda:payload,
        result_limit_bytes=jobs.MAX_EXTENDED_RESULT_BYTES,compress_result=True)['ticket']
    assert terminal(store,ticket)['register']==payload['register']
    raw,identity=collect(store,ticket)
    compressed,encoded=collect(store,ticket,accept_gzip=True)
    assert len(raw)>jobs.MAX_RESULT_BYTES
    assert encoded['encoding']=='gzip' and identity['encoding']=='identity'
    assert encoded['json_bytes']==len(raw)==identity['json_bytes']
    assert gzip.decompress(compressed)==raw
    assert len(compressed)<len(raw)/20
    assert json.loads(raw)==payload
    store._path(ticket,'gzip').unlink()
    with pytest.raises(jobs.JobProblem) as missing:
        store.poll_part(ticket,OWNER,PROFILE,accept_gzip=True)
    assert (missing.value.status,missing.value.code)==(500,'storage_failed')


def test_compression_cannot_bypass_the_uncompressed_result_budget(tmp_path):
    store=jobs.Store(tmp_path/'jobs')
    ticket=store.start(OWNER,PROFILE,PARAMS,lambda:{'text':'x'*jobs.MAX_RESULT_BYTES},
        compress_result=True)['ticket']
    with pytest.raises(jobs.JobProblem):terminal(store,ticket)
    assert not store._path(ticket,'gzip').exists()


def test_legacy_ready_job_is_not_reencoded_or_upgraded_on_retry(tmp_path):
    store=jobs.Store(tmp_path/'jobs')
    ticket=store.start(OWNER,PROFILE,PARAMS,lambda:{'text':'x'*100000})['ticket']
    terminal(store,ticket)
    store.start(OWNER,PROFILE,PARAMS,lambda:pytest.fail('Repeated builder'),ticket,
        include_result=False,compress_result=True)
    _,part=collect(store,ticket,accept_gzip=True)
    assert part['encoding']=='identity' and not store._path(ticket,'gzip').exists()


def test_compressed_artifact_is_removed_by_the_same_retention_sweep(tmp_path):
    store=jobs.Store(tmp_path/'jobs')
    ticket=store.start(OWNER,PROFILE,PARAMS,lambda:{'text':'x'*100000},compress_result=True)['ticket']
    terminal(store,ticket)
    assert store._path(ticket,'gzip').exists()
    with store._locked():
        meta=store._meta(ticket);meta['created']-=jobs.TTL_SECONDS+1;store._save(meta)
    new=store.start(OWNER,PROFILE,{'fresh':True},lambda:{'ok':True})['ticket']
    terminal(store,new)
    for suffix in ('json','result','gzip','run'):
        assert not store._path(ticket,suffix).exists()


def test_part_compression_flag_requires_a_real_boolean(api,monkeypatch):
    client,_=api
    assert post(client,'contracts/result-part',ticket='a'*32,accept_gzip='true').status_code==422


@pytest.mark.parametrize('supported',[True,False])
def test_browser_decodes_compressed_parts_or_uses_identity_and_recovers(supported):
    init='' if supported else 'window.DecompressionStream=undefined;'
    with browser_page(init=init) as (page,responses,errors):
        rng=random.Random(431)
        # Enough entropy for several compressed pieces; deterministic/public.
        responses.data['warnings']=[''.join(rng.choices('abcdefghijklmnopqrstuvwxyz0123456789',k=1300000))]
        raw=json.dumps({'ok':True,'register':responses.data},ensure_ascii=False).encode()
        packed=gzip.compress(raw,compresslevel=5,mtime=0)
        assert len(packed)>jobs.RESULT_PART_BYTES
        calls=[];failed=[]
        def parts(route):
            body=route.request.post_data_json;calls.append(body)
            encoded=body['accept_gzip'];data=packed if encoded else raw
            if body['offset']>0 and not failed:
                failed.append(True);return route.abort('connectionfailed')
            offset=body['offset']
            return route.fulfill(json={'pending':False,'ticket':body['ticket'],'result_part':{
                'offset':offset,'total_bytes':len(data),'json_bytes':len(raw),
                'encoding':'gzip' if encoded else 'identity',
                'content_base64':base64.b64encode(data[offset:offset+jobs.RESULT_PART_BYTES]).decode()}})
        page.route('**/monitor/contracts/result-part',parts)
        page.locator('#contractsTab').click()
        expect(page.locator(f'tr[data-contract-id="{CONTRACT}"]')).to_be_visible(timeout=15000)
        assert failed and all(call['accept_gzip']==supported for call in calls)
        assert page.evaluate('contractRegister.warnings[0]')==responses.data['warnings'][0]
        assert not errors


def test_browser_rejects_decompressed_bytes_beyond_the_declared_bound():
    with browser_page() as (page,_,errors):
        compressed=base64.b64encode(gzip.compress(b'x'*1000000,mtime=0)).decode()
        result=page.evaluate('''async(value)=>{
            const bytes=Uint8Array.from(atob(value),c=>c.charCodeAt(0));
            try{await cumulativeDecodedBytes(bytes,'gzip',100,()=>true);return 'unexpected success'}
            catch(e){return e.message}
        }''',compressed)
        assert 'превышает' in result
        assert not errors
