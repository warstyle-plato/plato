"""Synthetic raw duplicate normalization; no actual workbook or operational state."""
from __future__ import annotations

import copy
import hashlib
import json

import pytest

import developaid_contract_duplicate_proof as proof
import developaid_contract_source_review as review
import developaid_monitor_ledgers as ledgers
import developaid_management_report_jobs as jobs
from test_cumulative_proven_duplicates import duplicate_book
from test_monitor_cumulative_api import api, post, poll, KEY, core  # noqa: F401
from test_monitor_cumulative_ledgers import archive
from test_project_ks6_source_audit import PROJECT, CUT, retain, snapshot_bytes, all_records, ks


def stored():
    raw = duplicate_book()
    sid = retain(archive([('Copies.xlsx', raw)]), '2036-07-01')
    audit = review.project_audit(PROJECT, CUT)
    return raw, sid, hashlib.sha256(raw).hexdigest(), review.corpus_token(PROJECT, CUT, audit['archives'])


def read(sha, token):
    return review.project_duplicate_proof(PROJECT, CUT, [sha], token)


def test_closed_normalization_matches_exact_native_and_existing_audit_items(api, monkeypatch):
    import developaid_contract_identity as identity
    import developaid_monitor_contracts as contracts
    import developaid_monitor_header_confirmations as headers
    raw, sid, sha, token = stored()
    before = snapshot_bytes()
    for module, name in [(identity, 'resolve'), (contracts, 'build'), (headers, 'apply')]:
        monkeypatch.setattr(module, name, lambda *a, **k: pytest.fail('raw proof read operational state'))
    result = read(sha, token)
    audit = review.project_audit_page(PROJECT, CUT, [sha], token)
    native = ledgers.parse_archive(archive([('Copies.xlsx', raw)]))['ledgers'][0]['items']
    record, = result['records']
    assert record['native_items_sha256'] == proof._digest(native)
    assert record['audit_items_sha256'] == proof._digest(all_records(audit)[0]['items'])
    assert result['schema'] == proof.SCHEMA and result['proof_count'] == 2
    assert result['source_observations'][0]['snapshot_id'] == sid
    assert record['item_count'] == 4
    assert [(p['locator']['row'], p['canonical_locator']['row']) for p in record['proofs']] == [(11,9),(12,10)]
    for p in record['proofs']:
        assert p['verified_duplicate_source'] is True
        assert p['verified_target'] == p['canonical_locator']
        assert p['plan']['range'] == dict(column=6,start_row=9,end_row=10)
        assert p['completed'][0]['range'] == dict(column=14,start_row=9,end_row=10)
        assert p['plan']['audit_input_sha256'] == proof._digest(all_records(audit)[0]['items'][p['item_index']]['duplicate_proof']['plan'])
    assert result['producer']['current_parser_schema'] == ledgers.PARSER_SCHEMA
    assert result['binding_verified'] is result['financial_complete'] is None
    assert result['native_items_order'] == 'current_book_sheet_then_parser_item_order'
    pin = result.pop('projection_sha256'); assert pin == proof._digest(result)
    def keys(value):
        if isinstance(value,dict):
            assert not {'formula','formulas','value','items','amount','completed_amount','raw_quantity_cells'} & value.keys()
            for child in value.values(): keys(child)
        elif isinstance(value,list):
            for child in value: keys(child)
    keys(result)
    assert '=SUM(' not in json.dumps(result)
    assert snapshot_bytes() == before


@pytest.mark.parametrize('fault', ['formula','value','row','counterpart','order'])
def test_changed_native_input_changes_pins_and_does_not_trust_duplicate_flags(api, fault):
    raw, _, sha, _ = stored()
    record = ledgers.parse_archive(archive([('Copies.xlsx',raw)]))['ledgers'][0]
    # This unit seam intentionally supplies source rows only for the audit's
    # ancillary raw-cell view; native proof values and fingerprints are real.
    sheets=ledgers._read_workbook('Copies.xlsx',raw,dict(text_bytes=0))
    expected=proof._record(record,sheets[0][1],sha,CUT,0)
    changed=copy.deepcopy(record)
    if fault=='formula':changed['items'][2]['duplicate_proof']['plan']['formula']='=SUM(G9:G11)'
    if fault=='value':changed['items'][2]['plan_quantity']=91
    if fault=='row':changed['items'][2]['source']['row']=16
    if fault=='counterpart':changed['items'].pop(0)
    if fault=='order':changed['items'].reverse()
    got=proof._record(changed,sheets[0][1],sha,CUT,0)
    assert got['native_items_sha256']!=expected['native_items_sha256']
    if fault!='order':assert not all(p['verified_duplicate_source']for p in got['proofs'])
    if fault=='formula':
        p=next(p for p in got['proofs']if p['locator']['row']==11)
        assert p['plan']['range']==dict(column=6,start_row=9,end_row=11)


@pytest.mark.parametrize('formula', [None,'=G9+G10','=SUM(H9:H10)','=SUM(G10:G9)'])
def test_invalid_normalizations_remain_null_without_a_formula_export(formula):
    result=proof._normalization(dict(cell='G13',formula=formula,value=1020))
    assert result['range'] is None and result['state']=='invalid'
    assert not {'formula','value'} & result.keys()


@pytest.mark.parametrize('key,session',[('',''),('wrong',''),('market-key',''),('','demo'),('','claimed-team')])
def test_admin_is_required_before_source_or_store(api,monkeypatch,key,session):
    client,tmp=api
    monkeypatch.setattr(review,'project_duplicate_proof',lambda *a,**k:pytest.fail('source before admin'))
    monkeypatch.setattr(jobs.Store,'start',lambda *a,**k:pytest.fail('store before admin'))
    response=post(client,'contracts/source-duplicate-proof',project=PROJECT,cut=CUT,book_sha256=['a'*64],corpus_token='b'*64,key=key,session=session)
    assert response.status_code==403 and response.headers['cache-control']=='private, no-store'
    assert not (tmp/'monitor'/'.cumulative_jobs').exists()


@pytest.mark.parametrize('extra',[{'filename':'X.xlsx'},{'sheet':'Work'},{'range':'A1:G13'},{'rows':[11]},
    {'formula':'=SUM(G9:G10)'},{'path':'/tmp/x'},{'url':'https://example.invalid'},{'snapshot_id':'x'}])
def test_strict_route_refuses_free_source_selectors(api,extra):
    client,_=api
    result=client.post('/monitor/contracts/source-duplicate-proof',json=dict(key=KEY,project=PROJECT,cut=CUT,
        book_sha256=['a'*64],corpus_token='b'*64,**extra))
    assert result.status_code==422 and result.headers['cache-control']=='private, no-store'


@pytest.mark.parametrize('selection',[[],['a'*64,'b'*64],['UPPER'],[42],'a'*64])
def test_exactly_one_lowercase_sha_is_required_before_sources(api,monkeypatch,selection):
    monkeypatch.setattr(review,'_audit_root',lambda *a:pytest.fail('bad selector read sources'))
    with pytest.raises(review.SourceReviewProblem): review.project_duplicate_proof(PROJECT,CUT,selection,'b'*64)
    client,_=api
    assert client.post('/monitor/contracts/source-duplicate-proof',json=dict(key=KEY,project=PROJECT,cut=CUT,
        book_sha256=selection,corpus_token='b'*64)).status_code==422


@pytest.mark.parametrize('fault',['token','sha','cut','project'])
def test_foreign_context_is_rejected_before_any_decode(api,monkeypatch,fault):
    _,_,sha,token=stored()
    monkeypatch.setattr(ledgers,'_read_workbook',lambda *a,**k:pytest.fail('decode before corpus/sha check'))
    args=dict(project=PROJECT,cut=CUT,book_sha256=[sha],corpus_token=token)
    args.update({'token':dict(corpus_token='a'*64),'sha':dict(book_sha256=['b'*64]),
        'cut':dict(cut='2036-07-02'),'project':dict(project='Other')}[fault])
    with pytest.raises(review.SourceReviewProblem):review.project_duplicate_proof(**args)


@pytest.mark.parametrize('fault',['bytes','other-bytes','added','removed','alias','root'])
def test_all_source_and_namespace_drift_reject_the_entire_proof(api,monkeypatch,fault):
    import developaid_monitor as monitor
    _,sid,sha,token=stored()
    other=retain(archive([('Other.xlsx',ks('OTHER'))]),'2036-07-02')
    audit=review.project_audit(PROJECT,CUT);token=review.corpus_token(PROJECT,CUT,audit['archives'])
    original=ledgers._read_workbook;root=ledgers._root(PROJECT)
    def changed(*a,**k):
        value=original(*a,**k)
        if fault in {'bytes','other-bytes'}:(root/((other if fault=='other-bytes'else sid)+'.zip')).write_bytes(b'changed')
        if fault=='added':retain(archive([('New.xlsx',ks('NEW'))]),'2036-08-01')
        if fault=='removed':(root/(sid+'.zip')).unlink();(root/(sid+'.json')).unlink()
        if fault=='alias':monkeypatch.setattr(monitor,'_resolved_slug',lambda *a:'other-project')
        if fault=='root':root.rename(root.with_name('removed'));root.mkdir()
        return value
    monkeypatch.setattr(ledgers,'_read_workbook',changed)
    with pytest.raises(review.SourceReviewProblem):read(sha,token)


@pytest.mark.parametrize('cap',['MAX_SHEETS','MAX_RECORDS','MAX_ITEMS','MAX_PERIODS','MAX_PROOFS','MAX_PROOF_CELLS','MAX_CELLS','MAX_RESULT_BYTES'])
def test_every_projection_cap_refuses_instead_of_partial_success(api,monkeypatch,cap):
    _,_,sha,token=stored()
    monkeypatch.setattr(proof,cap,0 if cap!='MAX_RESULT_BYTES'else 1)
    with pytest.raises(review.SourceReviewProblem):read(sha,token)


def test_native_job_keeps_exact_context_owner_and_runtime_without_source_writes(api):
    client,tmp=api
    _,_,sha,token=stored();before=snapshot_bytes();ticket='8'*32
    values=dict(project=PROJECT,cut=CUT,book_sha256=[sha],corpus_token=token,ticket=ticket)
    result=post(client,'contracts/source-duplicate-proof',session='owner-A',**values)
    result=result if result.status_code==200 else poll(client,ticket,session='owner-A')
    assert result.json()['source_duplicate_proof']['proof_count']==2
    assert result.json()['runtime']==dict(version=core.VERSION,commit=core.COMMIT)
    for change in [dict(corpus_token='a'*64),dict(book_sha256=['b'*64]),dict(cut='2036-08-18'),dict(project='Other')]:
        assert post(client,'contracts/source-duplicate-proof',session='owner-A',**dict(values,**change)).status_code==409
    assert post(client,'contracts/result',session='owner-B',ticket=ticket).status_code==404
    assert post(client,'contracts/source-audit-page',session='owner-A',**values).status_code==409
    stored_result=jobs.Store(tmp/'monitor'/'.cumulative_jobs').poll(ticket,
        jobs.owner_binding(KEY,'owner-A','monitor-cumulative-v1:contracts'),'monitor-cumulative-v1:contracts')
    assert stored_result['source_duplicate_proof']==result.json()['source_duplicate_proof']
    assert snapshot_bytes()==before


def test_changed_producer_pin_holds_before_return(api, monkeypatch):
    _,_,sha,token=stored()
    original=proof._producer;calls=[]
    def changed():
        result=original();calls.append(True)
        if len(calls)>1:result['current_parser_schema']+=1
        return result
    monkeypatch.setattr(proof,'_producer',changed)
    with pytest.raises(review.SourceReviewProblem,match='Код обработчика'):read(sha,token)
    assert calls==[True,True]


def test_projection_pin_binds_context_and_every_proof_not_only_row_numbers(api):
    _,_,sha,token=stored();result=read(sha,token)
    actual=result.pop('projection_sha256')
    assert proof._digest(result)==actual
    for field,value in [('project','Other'),('cut','2036-08-18'),('book_sha256','a'*64),('corpus_token','b'*64)]:
        other=copy.deepcopy(result);other[field]=value
        assert proof._digest(other)!=actual
    for change in ('order','locator','normalization','verdict','audit_input','native_input','snapshot'):
        other=copy.deepcopy(result);p=other['records'][0]['proofs'][0]
        if change=='order':other['records'][0]['proofs'].reverse()
        if change=='locator':p['locator']['row']+=1
        if change=='normalization':p['plan']['range']['end_row']+=1
        if change=='verdict':p['verified_duplicate_source']=False
        if change=='audit_input':p['audit_item_sha256']='c'*64
        if change=='native_input':p['native_item_sha256']='d'*64
        if change=='snapshot':other['source_observations'][0]['snapshot_id']='2036-07-01-'+'e'*64
        assert proof._digest(other)!=actual


def test_renamed_same_bytes_have_explicit_observation_pins_and_a_stable_audit_view(api):
    raw,_,sha,_=stored()
    retain(archive([('Renamed.xlsx',raw)]),'2036-07-02')
    audit=review.project_audit(PROJECT,CUT);token=review.corpus_token(PROJECT,CUT,audit['archives'])
    result=read(sha,token)
    assert len(result['source_observations'])==2
    assert len({v['filename_sha256']for v in result['source_observations']})==2
    assert result['parser_filename_sha256']==result['source_observations'][0]['filename_sha256']
    page=review.project_audit_page(PROJECT,CUT,[sha],token)
    assert result['records'][0]['audit_items_sha256']==proof._digest(all_records(page)[0]['items'])
    assert result['proof_count']==2 and all(p['verified_duplicate_source']for p in result['records'][0]['proofs'])


def test_future_source_is_not_read_or_added_to_current_pin(api,monkeypatch):
    _,_,sha,token=stored();before=read(sha,token)
    future=retain(archive([('Future.xlsx',ks('FUTURE'))]),'2036-12-01')
    original=review._original
    def guarded(project,sid,**kwargs):
        assert sid!=future
        return original(project,sid,**kwargs)
    monkeypatch.setattr(review,'_original',guarded)
    assert read(sha,token)==before
