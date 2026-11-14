"""Explicit current-saved source scope never becomes historical eligibility."""
import ast
import hashlib
import json
import time

import pytest
from fastapi.testclient import TestClient

import developaid_admin_expenses_source as proof
import developaid_monitor as monitor
import main as wrapper
from test_admin_expenses_source_proof import source, changed, KEY, PROJECT, CUT, RUNTIME  # noqa: F401

ROUTE='/monitor/audit/admin-expenses/saved-snapshot'


def undated(source,value=None):
    path=source[0]/monitor.FINANCE_META
    meta=json.loads(path.read_text())
    if value is None:meta.pop('taken_at',None)
    else:meta['taken_at']=value
    # These timestamps cannot be substituted for an effective source date.
    meta['uploaded_at']='2026-10-01T12:00:00+00:00'
    path.write_text(json.dumps(meta))


def raw():return proof.capture_saved_snapshot(PROJECT,runtime=RUNTIME)


@pytest.mark.parametrize('date',[None,'','not a date','2999-01-01'])
def test_explicit_saved_scope_reads_same_bounded_cells_without_waiving_historical_gate(source,date):
    changed(source,lambda s:setattr(s['B2'],'value','Все суммы в тыс. руб.'))
    undated(source,date)
    before={p.name:p.read_bytes() for p in source[0].iterdir() if p.is_file()}
    historical=proof.capture(PROJECT,CUT,runtime=RUNTIME)
    assert historical['state'] in ('source_date_unknown','source_after_cut') and historical['rows']==[]
    got=raw()
    assert got['purpose']==proof.SAVED_PURPOSE and got['scope']=='raw_saved_snapshot'
    assert got['state']=='raw_saved_snapshot_read'
    assert not got['historical_eligibility_evaluated'] and got['historical_cut'] is None
    assert not got['financial_acceptance'] and got['values_are_raw_cached_cells']
    assert got['source']['selection_basis']=='current_stored_bytes_not_a_historical_cut'
    assert got['source']['version_date']==('2999-01-01' if date=='2999-01-01' else None)
    assert got['source_date_state']==('declared_in_metadata' if date=='2999-01-01' else 'unknown')
    assert got['unit_evidence']['state']=='observed' and got['unit_evidence']['recognized_unit']=='тыс. руб.'
    row,=got['rows'];assert row['code']=='2.4.1'
    assert {k:v['cached_value'] for k,v in row['cells'].items()}=={'total':40,'fact':20,'plan':20}
    assert got['source']['sha256']==hashlib.sha256((source[0]/'finance.xlsx').read_bytes()).hexdigest()
    assert before=={p.name:p.read_bytes() for p in source[0].iterdir() if p.is_file()}
    encoded=json.dumps(got,ensure_ascii=False)
    for secret in ['PRIVATE-METADATA-CANARY','PRIVATE-FILENAME-CANARY','content_base64','bank_rss']:
        assert secret not in encoded


@pytest.mark.parametrize('unit,expected',[('Все суммы в руб.','руб.'),
    ('Все суммы в тыс. руб.','тыс. руб.'),('Все суммы в млн руб.','млн руб.'),
    ('Стоимость: тыс. руб. за 1 м²',None),('',None)])
def test_saved_scope_uses_the_existing_unit_grammar_without_inventing_scale(source,unit,expected):
    changed(source,lambda s:setattr(s['B2'],'value',unit));undated(source)
    assert raw()['unit_evidence']['recognized_unit']==expected


def test_undated_unknown_money_and_formula_stay_unknown_and_formula_text_never_leaves(source):
    changed(source,lambda s:setattr(s['J14'],'value','=HYPERLINK("https://PRIVATE-FORMULA-CANARY","secret")'))
    undated(source)
    got=raw();value=got['rows'][0]['cells']['fact']
    assert value['cached_value'] is None and value['formula']
    assert 'PRIVATE-FORMULA-CANARY' not in json.dumps(got)


def test_source_change_while_reading_raw_scope_is_rejected(source,monkeypatch):
    undated(source);original=proof._cells
    def cells(data):
        got=original(data);changed(source,lambda s:setattr(s['I14'],'value',80));return got
    monkeypatch.setattr(proof,'_cells',cells)
    with pytest.raises(proof.SourceProblem,match='source_changed'):raw()


def test_raw_scope_preserves_original_size_and_output_limits(source,monkeypatch):
    undated(source);monkeypatch.setattr(proof,'MAX_OUTPUT',1)
    with pytest.raises(proof.SourceProblem,match='projection_size_limit'):raw()


@pytest.mark.parametrize('project',[None,'','../outside','bad/path','bad\\path','bad\0name'])
def test_raw_scope_invalid_project_rejected_before_files(monkeypatch,project):
    monkeypatch.setattr(proof,'_copy',lambda *a:pytest.fail('source reader reached'))
    with pytest.raises(proof.SourceProblem,match='request_invalid'):
        proof.capture_saved_snapshot(project,runtime=RUNTIME)


def call(client,suffix='',**body):
    return client.post(ROUTE+suffix,json={'key':KEY,'session':'owner',**body})


def poll(client,ticket,**body):
    end=time.monotonic()+5
    while time.monotonic()<end:
        reply=call(client,'/result',ticket=ticket,**body)
        if reply.status_code!=202:return reply
        time.sleep(.01)
    pytest.fail('Saved snapshot source job did not finish')


def test_native_saved_job_is_admin_only_owner_bound_and_separate_from_historical_profile(source,monkeypatch):
    undated(source)
    monkeypatch.setattr(monitor,'build',lambda *a,**k:pytest.fail('financial widget called'))
    client=TestClient(wrapper.core.app)
    denied=call(client,project=PROJECT,key='wrong')
    assert denied.status_code==403 and denied.headers['cache-control']=='private, no-store'
    assert not (monitor._SNAPSHOT_DIR/'.admin_ahr_source_jobs').exists()
    reply=call(client,project=PROJECT,ticket='b'*32)
    assert reply.status_code==202 and reply.headers['cache-control']=='private, no-store'
    assert poll(client,'b'*32,session='other').status_code==404
    # A ticket for a raw current-saved read cannot be reused as a historical result.
    historical=client.post('/monitor/audit/admin-expenses/result',json={'key':KEY,'session':'owner','ticket':'b'*32})
    assert historical.status_code==404
    got=poll(client,'b'*32)
    assert got.status_code==200 and got.json()['ok']
    assert got.json()['source_projection']['scope']=='raw_saved_snapshot'
    assert got.json()['source_projection']['source']['version_date'] is None
    assert got.headers['cache-control']=='private, no-store'
    meta=(monitor._SNAPSHOT_DIR/'.admin_ahr_source_jobs'/('b'*32+'.json')).read_text()
    assert KEY not in meta and PROJECT not in meta and 'private-source' not in meta
    monkeypatch.setenv('DEVELOPAID_ADMIN_KEY','rotated-saved-key')
    assert poll(client,'b'*32).status_code==403
    assert poll(client,'b'*32,key='rotated-saved-key').status_code==404


@pytest.mark.parametrize('extra',[{'cut':CUT},{'scope':'historical'},{'path':'/etc/passwd'},
    {'sheet':'Other'},{'range':'A1:ZZ99999'},{'url':'https://example.invalid/'},
    {'cells':['J14']},{'content_base64':'secret'},{'purpose':proof.PURPOSE}])
def test_saved_endpoint_rejects_cut_and_arbitrary_selectors(source,extra):
    reply=call(TestClient(wrapper.core.app),project=PROJECT,**extra)
    assert reply.status_code==400 and reply.headers['cache-control']=='private, no-store'
    assert not (monitor._SNAPSHOT_DIR/'.admin_ahr_source_jobs').exists()


def test_saved_endpoint_wrong_key_denied_before_any_capture(source,monkeypatch):
    monkeypatch.setattr(proof,'capture_saved_snapshot',lambda *a,**k:pytest.fail('source reached'))
    reply=call(TestClient(wrapper.core.app),project=PROJECT,key='wrong')
    assert reply.status_code==403
