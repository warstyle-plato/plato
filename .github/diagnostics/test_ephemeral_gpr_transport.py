"""No real source, secret, or production request is used by these counterexamples."""
from __future__ import annotations

import base64
import copy
import datetime as dt
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess

import pytest

SCRIPT=Path(__file__).with_name('ephemeral-gpr-transport.py')
spec=importlib.util.spec_from_file_location('ephemeral_transport',SCRIPT)
transport=importlib.util.module_from_spec(spec)
spec.loader.exec_module(transport)
ops=transport.ops
INITIAL='a'*40
DELIVERY='b'*40
RUNTIME='c'*40
CIPHER=b'Synthetic ephemeral ciphertext'


def environment(tmp_path):
    return {'GITHUB_REPOSITORY':ops.REPOSITORY,'GITHUB_ACTOR':ops.ACTOR,
        'GITHUB_TRIGGERING_ACTOR':ops.ACTOR,'GITHUB_REF':ops.BRANCH,
        'GITHUB_EVENT_NAME':'workflow_dispatch','GITHUB_RUN_ATTEMPT':'1',
        'GITHUB_SHA':INITIAL,'GITHUB_WORKFLOW_SHA':INITIAL,'GITHUB_RUN_ID':'123456',
        'EXPECTED_RUNTIME_COMMIT':RUNTIME,'RUNNER_TEMP':str(tmp_path),'GITHUB_TOKEN':'synthetic-repository-token'}


@pytest.fixture
def prepared(monkeypatch,tmp_path):
    monkeypatch.setattr(ops,'trusted_checkout',lambda environment:None)
    env=environment(tmp_path)
    folder=transport.prepare(env)
    return env,folder


def blob_sha(value):
    return hashlib.sha1(b'blob '+str(len(value)).encode()+b'\0'+value).hexdigest()


def responses(cipher=CIPHER):
    return [
        {'ref':ops.BRANCH,'object':{'sha':DELIVERY,'type':'commit'}},
        {'sha':DELIVERY,'parents':[{'sha':INITIAL}],
         'files':[{'filename':transport.DELIVERY_FILE,'status':'modified','sha':blob_sha(cipher)}]},
        {'type':'file','path':transport.DELIVERY_FILE,'encoding':'base64','size':len(cipher),
         'sha':blob_sha(cipher),'content':base64.b64encode(cipher).decode()}]


class Response(io.BytesIO):
    status=200
    def __init__(self,url,value):
        raw=json.dumps(value).encode();super().__init__(raw)
        self.url,self.headers=url,{'Content-Length':str(len(raw))}
    def geturl(self):return self.url


class API:
    def __init__(self,values):self.values,self.calls=list(values),[]
    def open(self,request,timeout):
        assert request.full_url.startswith(transport.API+transport.PREFIX)
        assert request.get_header('Authorization')=='Bearer synthetic-repository-token'
        assert 0<timeout<=15
        self.calls.append((request.full_url,timeout))
        return Response(request.full_url,self.values.pop(0))


def receiver(env,values,clock=lambda:0,sleep=lambda seconds:None):
    api=API(values)
    return transport.Delivery(env,opener=api,clock=clock,sleep=sleep),api


def test_prepare_only_public_files_are_eligible_for_artifact(prepared):
    env,folder=prepared
    assert set(p.name for p in folder.iterdir())=={'private.pem','public.pem','public.json'}
    assert folder.stat().st_mode&0o777==0o700
    assert (folder/'private.pem').stat().st_mode&0o777==0o600
    assert b'PRIVATE KEY' in (folder/'private.pem').read_bytes()
    assert b'PRIVATE KEY' not in (folder/'public.pem').read_bytes()+(folder/'public.json').read_bytes()
    metadata=json.loads((folder/'public.json').read_text())
    assert metadata['workflow_sha']==INITIAL and metadata['expected_runtime_commit']==RUNTIME
    assert metadata['certificate_sha256']==ops.sha((folder/'public.pem').read_bytes())
    assert transport.session(env)[1]<=transport.WAIT_SECONDS


def test_duplicate_prepare_cannot_replace_existing_private_key(prepared):
    env,folder=prepared;before=(folder/'private.pem').read_bytes()
    with pytest.raises(FileExistsError):transport.prepare(env)
    assert (folder/'private.pem').read_bytes()==before


@pytest.mark.parametrize('field,value',[('run_id','999'),('run_attempt',True),('workflow_sha','d'*40),
    ('repository','other/repo'),('ref','refs/heads/main'),('expected_runtime_commit','e'*40),
    ('certificate_sha256','f'*64),('nonce','')])
def test_mismatched_session_is_rejected_before_http(prepared,field,value):
    env,folder=prepared;path=folder/'public.json';metadata=json.loads(path.read_text())
    metadata[field]=value;path.write_text(json.dumps(metadata))
    with pytest.raises(ops.ApplyError) as error:transport.session(env)
    assert error.value.code==ops.FENCE


@pytest.mark.parametrize('age',[-1,901])
def test_stale_or_future_session_fails_closed(prepared,age):
    env,folder=prepared;path=folder/'public.json';metadata=json.loads(path.read_text())
    metadata['created_utc']=(dt.datetime.now(dt.timezone.utc)-dt.timedelta(seconds=age)).isoformat()
    path.write_text(json.dumps(metadata))
    with pytest.raises(ops.ApplyError) as error:transport.session(env)
    assert error.value.code==ops.DEADLINE


@pytest.mark.parametrize('target',['private.pem','public.pem','public.json'])
def test_symlink_session_file_rejected(prepared,tmp_path,target):
    env,folder=prepared;path=folder/target;other=tmp_path/'other';other.write_bytes(path.read_bytes())
    path.unlink();path.symlink_to(other)
    with pytest.raises(ops.ApplyError):transport.session(env)


def test_private_key_mode_is_checked(prepared):
    env,folder=prepared;os.chmod(folder/'private.pem',0o644)
    with pytest.raises(ops.ApplyError):transport.session(env)


def test_fixed_delivery_is_one_direct_child_with_one_data_file(prepared):
    env,folder=prepared;delivery,api=receiver(env,responses())
    cipher,key=delivery.receive(Path(env['RUNNER_TEMP']))
    assert cipher==CIPHER and key==(folder/'private.pem').read_text()
    assert [url.removeprefix(transport.API) for url,_ in api.calls]==[
        transport.REF_PATH,transport.PREFIX+'/commits/'+DELIVERY,
        transport.PREFIX+'/contents/'+transport.DELIVERY_FILE+'?ref='+DELIVERY]
    assert delivery.token==''


@pytest.mark.parametrize('mutation',[
    lambda values:values[0]['object'].update(sha='not-a-sha'),
    lambda values:values[0].update(ref='refs/heads/main'),
    lambda values:values[0]['object'].update(type='tag'),
    lambda values:values[1]['parents'][0].update(sha='d'*40),
    lambda values:values[1]['parents'].append({'sha':'e'*40}),
    lambda values:values[1]['files'].append({'filename':'script.py'}),
    lambda values:values[1]['files'][0].update(filename='script.py'),
    lambda values:values[1]['files'][0].update(status='renamed',previous_filename='old'),
    lambda values:values[1].update(sha='e'*40),
    lambda values:values[2].update(path='another.cms'),
    lambda values:values[2].update(type='symlink'),
    lambda values:values[2].update(encoding='raw'),
    lambda values:values[2].update(size=True),
    lambda values:values[2].update(size=ops.MAX_INPUT+1),
    lambda values:values[2].update(size=1),
    lambda values:values[2].update(sha='f'*40),
    lambda values:values[2].update(content='!invalid-base64!'),
    lambda values:values[2].update(content=base64.b64encode(b'tampered').decode()),
])
def test_changed_delivery_boundaries_reject_before_apply(prepared,mutation):
    env,_=prepared;values=responses();mutation(values);delivery,_=receiver(env,values)
    with pytest.raises(ops.ApplyError):delivery.receive(Path(env['RUNNER_TEMP']))
    assert delivery.token==''


def test_old_ciphertext_cannot_be_mistaken_for_new_delivery(prepared,monkeypatch):
    env,_=prepared;monkeypatch.setattr(ops,'INPUT_SHA256',ops.sha(CIPHER))
    delivery,_=receiver(env,responses())
    with pytest.raises(ops.ApplyError) as error:delivery.receive(Path(env['RUNNER_TEMP']))
    assert error.value.code==ops.INPUT


def test_waiting_for_same_head_expires_without_apply(prepared):
    env,_=prepared;now=[0.0]
    def sleep(seconds):now[0]+=seconds
    same={'ref':ops.BRANCH,'object':{'sha':INITIAL,'type':'commit'}}
    delivery,api=receiver(env,[same]*181,clock=lambda:now[0],sleep=sleep)
    with pytest.raises(ops.ApplyError) as error:delivery.receive(Path(env['RUNNER_TEMP']))
    assert error.value.code==ops.DEADLINE and now[0]<=900
    assert all(url==transport.API+transport.REF_PATH for url,_ in api.calls)


@pytest.mark.parametrize('path',['https://evil.invalid/key',transport.PREFIX+'/contents/other?ref='+DELIVERY,
    transport.PREFIX+'/contents/'+transport.DELIVERY_FILE+'?ref=main',transport.PREFIX+'/actions/secrets'])
def test_credential_cannot_be_sent_to_another_path(tmp_path,path):
    delivery,api=receiver(environment(tmp_path),[])
    with pytest.raises(ops.ApplyError):delivery.get(path,10)
    assert not api.calls


def test_expired_request_never_makes_http(tmp_path):
    delivery,api=receiver(environment(tmp_path),[])
    with pytest.raises(ops.ApplyError) as error:delivery.get(transport.REF_PATH,0)
    assert error.value.code==ops.DEADLINE and not api.calls


def test_redirect_handler_never_follows_authorized_request():
    with pytest.raises(ops.ApplyError) as error:
        ops.NoRedirect().redirect_request(None,None,302,'redirect',{},'https://evil.invalid')
    assert error.value.code==ops.TRANSPORT


@pytest.mark.parametrize('kind',['redirect','oversize-header','oversize-body','duplicate-json'])
def test_github_response_rejects_unsafe_transport(tmp_path,kind):
    class Unsafe:
        def open(self,request,timeout):
            result=Response(request.full_url,{'ok':True})
            if kind=='redirect':result.url='https://evil.invalid'
            if kind=='oversize-header':result.headers['Content-Length']=str(transport.MAX_GITHUB_RESPONSE+1)
            if kind=='oversize-body':
                result=io.BytesIO(b'x'*(transport.MAX_GITHUB_RESPONSE+1))
                result.status=200;result.headers={};result.geturl=lambda:request.full_url
            if kind=='duplicate-json':
                result=io.BytesIO(b'{"ok":true,"ok":false}')
                result.status=200;result.headers={};result.geturl=lambda:request.full_url
            return result
    delivery=transport.Delivery(environment(tmp_path),opener=Unsafe())
    with pytest.raises(ops.ApplyError):delivery.get(transport.REF_PATH,10)


def test_ephemeral_ciphertext_still_requires_exact_authenticated_plaintext(prepared,monkeypatch,tmp_path):
    env,folder=prepared
    # The source remains entirely synthetic, including all fixed validation identities.
    data=b'Synthetic only remaining-plan workbook'
    monkeypatch.setattr(ops,'SOURCE_SHA256',ops.sha(data));monkeypatch.setattr(ops,'SOURCE_BYTES',len(data))
    bundle={'schema':2,'project':'Synthetic transport test','old_source_sha256':ops.OLD_SOURCE_SHA256,
        'new_source_sha256':ops.SOURCE_SHA256,'source_base64':base64.b64encode(data).decode(),
        'old_cut':ops.HISTORICAL_CUT,'snapshot_id':ops.HISTORICAL_CUT+'-'+'a'*64,
        'source_as_of':ops.HISTORICAL_CUT,'baseline_proof_sha256':'b'*64,'operation_nonce':'c'*64,
        'expected_physical_revision':7,'owner_rnv_date':ops.OWNER_RNV_DATE,
        'owner_rnv_note':'Synthetic explicit owner decision','expected_owner_rnv_revision':0}
    raw=json.dumps(bundle,sort_keys=True).encode();monkeypatch.setattr(ops,'PLAINTEXT_SHA256',ops.sha(raw))
    result=subprocess.run(['openssl','cms','-encrypt','-aes-256-gcm','-binary','-outform','DER',
        '-recip',str(folder/'public.pem'),'-keyopt','rsa_padding_mode:oaep','-keyopt','rsa_oaep_md:sha256',
        '-keyopt','rsa_mgf1_md:sha256'],input=raw,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,check=True)
    envelope=result.stdout;key=(folder/'private.pem').read_text()
    assert ops.decrypt_bundle(envelope,key,tmp_path,envelope_sha256=ops.sha(envelope))==bundle
    with pytest.raises(ops.ApplyError):ops.decrypt_bundle(envelope,key,tmp_path) # old fixed ciphertext path
    monkeypatch.setattr(ops,'PLAINTEXT_SHA256','f'*64)
    with pytest.raises(ops.ApplyError):ops.decrypt_bundle(envelope,key,tmp_path,envelope_sha256=ops.sha(envelope))
    assert not list(tmp_path.glob('gpr-input-*'))


def test_workflow_reuses_only_existing_admin_secret_and_cleans_private_session():
    import yaml
    workflow=yaml.safe_load((SCRIPT.parents[1]/'workflows/prod-smoke.yml').read_text())
    triggers=workflow.get('on',workflow.get(True))
    assert set(triggers)=={'workflow_dispatch'}
    assert set(triggers['workflow_dispatch']['inputs'])=={'expected_runtime_commit'}
    assert workflow['permissions']=={'contents':'read'}
    job=workflow['jobs']['apply'];steps=job['steps']
    assert job['timeout-minutes']==22
    public=next(step for step in steps if step.get('with',{}).get('name')=='approved-gpr-input-public')
    assert public['with']['path'].splitlines()==[
        '${{ runner.temp }}/gpr-session-${{ github.run_id }}-1/public.pem',
        '${{ runner.temp }}/gpr-session-${{ github.run_id }}-1/public.json']
    apply=next(step for step in steps if step.get('id')=='apply')
    assert apply['env']=={'EXPECTED_RUNTIME_COMMIT':'${{ inputs.expected_runtime_commit }}',
        'GITHUB_TOKEN':'${{ github.token }}','APPLY_ADMIN_KEY':'${{ secrets.DEVELOPAID_ADMIN_KEY }}'}
    assert 'gpr-session-' in steps[-1]['run'] and steps[-1]['if']=='always()'
    assert 'PLATO_GPR_APPROVAL_ONCE_KEY' not in json.dumps(workflow)


def test_streaming_github_body_cannot_overrun_handshake_deadline(tmp_path):
    now=[0.0]
    class SlowBody(io.BytesIO):
        def read1(self,limit):
            now[0]+=2
            return super().read(limit)
    class SlowAPI:
        def open(self,request,timeout):
            result=SlowBody(b'{}');result.status=200;result.headers={}
            result.geturl=lambda:request.full_url
            return result
    delivery=transport.Delivery(environment(tmp_path),opener=SlowAPI(),clock=lambda:now[0])
    with pytest.raises(ops.ApplyError) as error:delivery.get(transport.REF_PATH,1)
    assert error.value.code==ops.DEADLINE


def test_real_crypto_rejects_ciphertext_from_previous_ephemeral_key(prepared,tmp_path):
    env,folder=prepared
    other=tmp_path/'other-private.pem'
    transport.run_openssl(['genpkey','-algorithm','RSA','-pkeyopt','rsa_keygen_bits:3072','-out',str(other)])
    result=subprocess.run(['openssl','cms','-encrypt','-aes-256-gcm','-binary','-outform','DER',
        '-recip',str(folder/'public.pem'),'-keyopt','rsa_padding_mode:oaep','-keyopt','rsa_oaep_md:sha256',
        '-keyopt','rsa_mgf1_md:sha256'],input=b'Synthetic private input',stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,check=True)
    with pytest.raises(ops.ApplyError) as error:
        ops.decrypt_bundle(result.stdout,other.read_text(),tmp_path,envelope_sha256=ops.sha(result.stdout))
    assert error.value.code==ops.CRYPTO
    assert not list(tmp_path.glob('gpr-input-*'))


def test_prepare_rejects_untrusted_github_context_before_key_creation(monkeypatch,tmp_path):
    def reject(environment):raise ops.ApplyError(ops.SETUP)
    monkeypatch.setattr(ops,'trusted_checkout',reject)
    with pytest.raises(ops.ApplyError):transport.prepare(environment(tmp_path))
    assert not list(tmp_path.iterdir())


def test_wait_is_before_operation_clock_and_admin_is_read_only_after_decrypt(monkeypatch,tmp_path,capsys):
    # Import the old full synthetic server harness; no real source/HTTP is allowed.
    oldspec=importlib.util.spec_from_file_location('old_harness',SCRIPT.with_name('test_apply_approved_gpr.py'))
    old=importlib.util.module_from_spec(oldspec);oldspec.loader.exec_module(old)
    env=environment(tmp_path)
    for key,value in env.items():monkeypatch.setenv(key,value)
    monkeypatch.setenv('APPLY_ADMIN_KEY',old.KEY)
    monkeypatch.setattr(ops,'trusted_checkout',lambda environment:None)
    monkeypatch.setattr(ops,'SOURCE_SHA256',ops.sha(old.SOURCE));monkeypatch.setattr(ops,'SOURCE_BYTES',len(old.SOURCE))
    monkeypatch.setattr(ops,'OLD_SOURCE_SHA256',old.OLD)
    old.ops=ops
    recipient=tmp_path/'recipient.pem';recipient.write_bytes(b'Synthetic output certificate')
    monkeypatch.setattr(ops,'PUBLIC_RECIPIENT',recipient)
    monkeypatch.setattr(ops,'RECIPIENT_SHA256',ops.sha(recipient.read_bytes()))
    server=old.Server()
    events=[]
    original=ops.Operation
    def operation(expected):
        events.append('operation')
        return original(old.COMMIT,opener=server,today=lambda:dt.date.fromisoformat(old.TODAY))
    monkeypatch.setattr(ops,'Operation',operation)
    def provider(temporary):
        assert not events
        events.append('wait_finished')
        return b'Synthetic dynamic envelope','Synthetic transport private key'
    def decrypt(*args,**kwargs):
        assert events==['wait_finished','operation']
        assert os.environ['APPLY_ADMIN_KEY']==old.KEY
        events.append('decrypted')
        return old.bundle()
    monkeypatch.setattr(ops,'decrypt_bundle',decrypt)
    monkeypatch.setattr(ops,'encrypt_proof',lambda *args,**kwargs:None)
    assert ops.main(provider)==0
    assert events==['wait_finished','operation','decrypted']
    assert 'APPLY_ADMIN_KEY' not in os.environ
    result=json.loads(capsys.readouterr().out)
    assert result['ok'] and result['postflight_verified'] and server.approvals==1
    assert old.KEY not in json.dumps(result) and env['GITHUB_TOKEN'] not in json.dumps(result)
