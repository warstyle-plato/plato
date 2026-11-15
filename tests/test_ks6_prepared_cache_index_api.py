"""Fake local job service, synthetic cache manifests; no originals or external I/O."""
import copy

import pytest

import developaid_contract_prepared_index as proof
import developaid_management_report_jobs as jobs
from test_monitor_cumulative_api import api, post, poll, KEY, core  # noqa: F401
from test_ks6_prepared_cache_index import cache, forbidden_sources  # noqa: F401


@pytest.mark.parametrize('key,session',[('',''),('wrong',''),('market-key',''),('','demo'),('','claimed-team')])
def test_admin_before_source_or_job(api,cache,monkeypatch,key,session):
    client,tmp=api;_,_,args=cache
    monkeypatch.setattr(proof,'project_index',lambda *a,**k:pytest.fail('source before admin'))
    monkeypatch.setattr(jobs.Store,'start',lambda *a,**k:pytest.fail('store before admin'))
    result=post(client,'contracts/source-prepared-index',key=key,session=session,**args)
    assert result.status_code==403 and result.headers['cache-control']=='private, no-store'
    assert not(tmp/'monitor/.cumulative_jobs').exists()


@pytest.mark.parametrize('extra',[{'filename':'Synthetic.xlsx'},{'sheet':'Synthetic'},{'range':'A1:G4'},
    {'path':'/tmp/synthetic'},{'url':'https://example.invalid'},{'rows':[1]},{'items':[]},{'raw_ids':['a'*64]}])
def test_no_arbitrary_source_or_business_selectors(api,cache,extra):
    client,_=api;_,_,args=cache
    result=client.post('/monitor/contracts/source-prepared-index',json=dict(key=KEY,session='',**args,**extra))
    assert result.status_code==422 and result.headers['cache-control']=='private, no-store'


@pytest.mark.parametrize('change',[
    {'snapshot_ids':[]},{'snapshot_ids':['bad']},{'snapshot_ids':'bad'},
    {'snapshot_ids':['2036-01-01-'+'a'*64]*2},
    {'snapshot_ids':['2036-01-01-'+'a'*64]*33},
    {'expected_project_scope':False},{'expected_source_content_sha256':'UPPER'},
    {'caller_reference_corpus_token':42},{'cut':False}])
def test_strict_shape_caps_before_any_source(api,cache,monkeypatch,change):
    client,_=api;_,_,args=cache
    monkeypatch.setattr(proof,'project_index',lambda *a,**k:pytest.fail('malformed source read'))
    result=post(client,'contracts/source-prepared-index',**dict(args,**change))
    assert result.status_code==422 and result.headers['cache-control']=='private, no-store'


def test_job_owner_body_ticket_and_runtime_binding_without_originals(api,cache,monkeypatch):
    client,tmp=api;root,_,args=cache
    for name in ('parse_archive','_current_archive','_read_workbook','read_snapshot','store_archive'):
        monkeypatch.setattr(proof.ledgers,name,lambda *a,**k:pytest.fail('cache-only route read original'))
    snapshots={p.name:p.read_bytes()for p in root.iterdir()}
    ticket='8'*32
    result=post(client,'contracts/source-prepared-index',session='SYN-owner-A',ticket=ticket,**args)
    result=result if result.status_code==200 else poll(client,ticket,session='SYN-owner-A')
    assert result.status_code==200 and result.json()['ok']is True
    value=result.json()['source_prepared_index']
    assert value['original_bytes_read']==value['cache_writes']==0 and value['future_consumer_invoked']is False
    assert value['cached_source_roster_sha256']==args['expected_cached_source_roster_sha256']
    assert result.json()['runtime']==dict(version=core.VERSION,commit=core.COMMIT)
    assert len(proof.canonical(result.json()))<=262144
    for field in ('expected_project_scope','expected_source_content_sha256','expected_cached_source_roster_sha256','caller_reference_corpus_token'):
        changed=copy.deepcopy(args);changed[field]='f'*64
        assert post(client,'contracts/source-prepared-index',session='SYN-owner-A',ticket=ticket,**changed).status_code==409
    assert post(client,'contracts/result',session='SYN-owner-B',ticket=ticket).status_code==404
    assert post(client,'cumulative/result',session='SYN-owner-A',ticket=ticket).status_code==404
    assert post(client,'contracts/build',session='SYN-owner-A',ticket=ticket,project=args['project'],cut=args['cut']).status_code==409
    assert {p.name:p.read_bytes()for p in root.iterdir()}==snapshots
    disk=b''.join(p.read_bytes()for p in(tmp/'monitor/.cumulative_jobs').iterdir()if p.is_file())
    assert KEY.encode()not in disk and b'SYN-owner-A'not in disk


def test_bad_expected_cache_roster_is_a_hold_not_a_reference_echo(api,cache):
    client,_=api;_,_,args=cache;args['expected_cached_source_roster_sha256']='f'*64;ticket='9'*32
    response=post(client,'contracts/source-prepared-index',ticket=ticket,**args)
    response=response if response.status_code==200 else poll(client,ticket)
    assert response.status_code==200 and response.json()['ok']is False
    assert 'source_prepared_index'not in response.json()
