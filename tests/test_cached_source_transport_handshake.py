"""Synthetic ephemeral RSA delivery: never reads the existing owner private key."""
import base64
import datetime as dt
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import types
import zipfile

import pytest
from test_private_financial_view_probe import cap,CONTEXT,RUNTIME,KEY,Server,Response  # noqa:F401

ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture(scope='module')
def synthetic_crypto(tmp_path_factory):
    folder=tmp_path_factory.mktemp('synthetic-ephemeral-transport')
    private=folder/'private.pem';cert=folder/'public.pem'
    for command in (
        ['openssl','genpkey','-algorithm','RSA','-pkeyopt','rsa_keygen_bits:3072','-out',str(private)],
        ['openssl','req','-new','-x509','-sha256','-days','1','-key',str(private),'-out',str(cert),'-subj','/CN=Synthetic-Only'],
    ):
        subprocess.run(command,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30)
    private.chmod(0o600)
    return private,cert


def environment(tmp_path):
    return {'GITHUB_REPOSITORY':'warstyle-plato/plato','GITHUB_REF':'refs/heads/ops/financial-view-root',
      'GITHUB_ACTOR':'warstyle-plato','GITHUB_TRIGGERING_ACTOR':'warstyle-plato',
      'GITHUB_EVENT_NAME':'workflow_dispatch','GITHUB_RUN_ATTEMPT':'1','GITHUB_SHA':'e'*40,
      'GITHUB_WORKFLOW_SHA':'e'*40,
      'GITHUB_WORKFLOW_REF':'warstyle-plato/plato/.github/workflows/prod-smoke.yml@refs/heads/ops/financial-view-root',
      'GITHUB_RUN_ID':'12345','EXPECTED_RUNTIME_COMMIT':RUNTIME,'RUNNER_TEMP':str(tmp_path),
      'GITHUB_TOKEN':'synthetic-github-token','CAPTURE_ADMIN_KEY':KEY}

@pytest.fixture
def prepared(cap,monkeypatch,tmp_path,synthetic_crypto):
    env=environment(tmp_path)
    monkeypatch.setattr(cap,'trusted_checkout',lambda _:None)
    folder=cap.context_folder(env);folder.mkdir(mode=0o700)
    private,cert=synthetic_crypto
    shutil.copyfile(private,folder/'private.pem');(folder/'private.pem').chmod(0o600)
    shutil.copyfile(cert,folder/'public.pem')
    meta={'schema':1,'repository':cap.REPOSITORY,'ref':cap.BRANCH,'run_id':env['GITHUB_RUN_ID'],
        'run_attempt':1,'workflow_sha':env['GITHUB_SHA'],'expected_runtime_commit':RUNTIME,
        'certificate_sha256':cap.sha(cert.read_bytes()),'nonce':'d'*64,'created_utc':dt.datetime.now(dt.timezone.utc).isoformat()}
    (folder/'public.json').write_text(json.dumps(meta))
    monkeypatch.setattr(cap,'CONTEXT_SHA256',cap.sha(cap.encoded(CONTEXT)))
    return env,folder,meta


def seal_to(cap,cert,value):
    result=subprocess.run(['openssl','cms','-encrypt','-aes-256-gcm','-binary','-outform','DER',
        '-recip',str(cert),'-keyopt','rsa_padding_mode:oaep','-keyopt','rsa_oaep_md:sha256',
        '-keyopt','rsa_mgf1_md:sha256'],input=cap.encoded(value),stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,timeout=20,env=cap.clean_env(),check=True)
    return result.stdout

class GitHub:
    def __init__(self,cap,env,envelope,mutation=None):
        self.cap=cap;self.env=env;self.envelope=envelope;self.mutation=mutation;self.calls=[]
    def open(self,request,timeout):
        self.calls.append(request)
        assert request.get_header('Authorization')=='Bearer '+self.env['GITHUB_TOKEN']
        assert request.full_url.startswith(self.cap.API+'/repos/warstyle-plato/plato/') and request.get_method()=='GET'
        candidate='f'*40
        blob=hashlib.sha1(b'blob '+str(len(self.envelope)).encode()+b'\0'+self.envelope).hexdigest()
        if request.full_url==self.cap.API+self.cap.REF_PATH:
            value={'ref':self.cap.BRANCH,'object':{'type':'commit','sha':candidate}}
        elif '/commits/' in request.full_url:
            value={'sha':candidate,'parents':[{'sha':self.env['GITHUB_SHA']}],
                   'files':[{'filename':self.cap.DELIVERY_FILE,'status':'modified','sha':blob}]}
        else:
            value={'path':self.cap.DELIVERY_FILE,'type':'file','encoding':'base64','size':len(self.envelope),
                   'sha':blob,'content':base64.b64encode(self.envelope).decode()}
        if self.mutation:value=self.mutation(request,value)
        return Response(value,request.full_url)


def test_real_crypto_exact_child_decrypts_only_after_fresh_health(prepared,cap,monkeypatch):
    env,folder,meta=prepared
    envelope=seal_to(cap,folder/'public.pem',CONTEXT);server=GitHub(cap,env,envelope);events=[]
    original=cap.decrypt_context
    monkeypatch.setattr(cap.Capture,'health',lambda self:events.append('health') or {'commit':RUNTIME,'version':'0.0.1'})
    monkeypatch.setattr(cap,'decrypt_context',lambda *args:events.append('decrypt') or original(*args))
    result=cap.Delivery(env,transport=server).receive()
    assert result==CONTEXT and events==['health','decrypt'] and len(server.calls)==3
    assert not any('/monitor/' in r.full_url for r in server.calls)

@pytest.mark.parametrize('field,value',[('ref','other'),('workflow_sha','0'*40),('expected_runtime_commit','1'*40),
    ('run_id','other'),('run_attempt',True),('certificate_sha256','0'*64),('nonce','bad')])
def test_mismatched_session_fails_before_any_http(prepared,cap,field,value):
    env,folder,meta=prepared;meta[field]=value;(folder/'public.json').write_text(json.dumps(meta))
    with pytest.raises(cap.CaptureError):cap.Delivery(env,transport=object()).receive()

@pytest.mark.parametrize('age',[-5,901])
def test_session_age_fails_closed(prepared,cap,age):
    env,folder,meta=prepared
    meta['created_utc']=(dt.datetime.now(dt.timezone.utc)-dt.timedelta(seconds=age)).isoformat()
    (folder/'public.json').write_text(json.dumps(meta))
    with pytest.raises(cap.CaptureError):cap.session(env)

@pytest.mark.parametrize('name',['private.pem','public.pem','public.json'])
def test_symlink_and_mode_fail_before_delivery(prepared,cap,tmp_path,name):
    env,folder,meta=prepared;path=folder/name;other=tmp_path/'other';other.write_bytes(path.read_bytes());path.unlink();path.symlink_to(other)
    with pytest.raises(cap.CaptureError):cap.session(env)


def test_private_key_mode_is_not_public(prepared,cap):
    env,folder,meta=prepared;(folder/'private.pem').chmod(0o644)
    with pytest.raises(cap.CaptureError):cap.session(env)

@pytest.mark.parametrize('kind',['parent','extra_parent','extra_file','renamed','status','path','blob','size','type'])
def test_foreign_or_mutating_child_never_decrypts(prepared,cap,monkeypatch,kind):
    env,folder,meta=prepared;envelope=seal_to(cap,folder/'public.pem',CONTEXT)
    def mutation(request,value):
        if '/commits/' in request.full_url:
            if kind=='parent':value['parents'][0]['sha']='0'*40
            if kind=='extra_parent':value['parents'].append({'sha':'0'*40})
            if kind=='extra_file':value['files'].append({'filename':'other','status':'modified'})
            if kind=='renamed':value['files'][0]['previous_filename']='other'
            if kind=='status':value['files'][0]['status']='added'
        elif '/contents/' in request.full_url:
            if kind=='path':value['path']='other'
            if kind=='blob':value['sha']='0'*40
            if kind=='size':value['size']+=1
            if kind=='type':value['type']='symlink'
        return value
    monkeypatch.setattr(cap,'decrypt_context',lambda *a:pytest.fail('decryption before fence'))
    with pytest.raises(cap.CaptureError):cap.Delivery(env,transport=GitHub(cap,env,envelope,mutation)).receive()

@pytest.mark.parametrize('path',['/user','/repos/elsewhere/x','https://evil.invalid/',
    '/repos/warstyle-plato/plato/actions/secrets','/repos/warstyle-plato/plato/contents/private.pem?ref='+'a'*40])
def test_github_credential_has_fixed_paths_only(cap,tmp_path,path):
    with pytest.raises(cap.CaptureError):cap.Delivery(environment(tmp_path),transport=object()).get(path,10)


def test_fresh_runtime_failure_cannot_decrypt_context(prepared,cap,monkeypatch):
    env,folder,meta=prepared;envelope=seal_to(cap,folder/'public.pem',CONTEXT)
    def wrong(self):raise cap.CaptureError('runtime')
    monkeypatch.setattr(cap.Capture,'health',wrong)
    monkeypatch.setattr(cap,'decrypt_context',lambda *a:pytest.fail('decrypt on changed runtime'))
    with pytest.raises(cap.CaptureError):cap.Delivery(env,transport=GitHub(cap,env,envelope)).receive()


def test_wrong_plaintext_pin_and_wrong_ephemeral_key_rejected(prepared,cap,tmp_path,synthetic_crypto):
    _,folder,_=prepared
    with pytest.raises(cap.CaptureError):cap.decrypt_context(seal_to(cap,folder/'public.pem',{**CONTEXT,'project':'different'}),folder/'private.pem')
    random_private=tmp_path/'wrong.pem'
    subprocess.run(['openssl','genpkey','-algorithm','RSA','-pkeyopt','rsa_keygen_bits:3072','-out',str(random_private)],
        check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30)
    with pytest.raises(cap.CaptureError):cap.decrypt_context(seal_to(cap,folder/'public.pem',CONTEXT),random_private)

@pytest.mark.parametrize('field,value',[('GITHUB_ACTOR','other'),('GITHUB_TRIGGERING_ACTOR','other'),
    ('GITHUB_RUN_ATTEMPT','2'),('GITHUB_REF','refs/heads/main'),('GITHUB_REPOSITORY','other/repo'),
    ('GITHUB_WORKFLOW_SHA','f'*40),('GITHUB_WORKFLOW_REF','other'),('GITHUB_EVENT_NAME','push')])
def test_untrusted_context_before_local_io(cap,monkeypatch,tmp_path,field,value):
    env=environment(tmp_path);env[field]=value
    monkeypatch.setattr(cap.subprocess,'run',lambda *a,**k:pytest.fail('subprocess before context fence'))
    with pytest.raises(cap.CaptureError):cap.trusted_checkout(env)


def test_prepare_has_public_artifact_only_and_duplicate_cannot_replace(cap,monkeypatch,tmp_path,synthetic_crypto):
    env=environment(tmp_path);private,cert=synthetic_crypto
    monkeypatch.setattr(cap,'trusted_checkout',lambda _:None)
    monkeypatch.setattr(cap.Capture,'health',lambda self:{'commit':RUNTIME,'version':'0.0.1'})
    def fake(args):
        if args[0]=='genpkey':shutil.copyfile(private,Path(args[args.index('-out')+1]))
        else:shutil.copyfile(cert,Path(args[args.index('-out')+1]))
    monkeypatch.setattr(cap,'run_openssl',fake)
    folder=cap.prepare(env);first=(folder/'private.pem').read_bytes()
    assert sorted(p.name for p in folder.iterdir())==['private.pem','public.json','public.pem']
    with pytest.raises(OSError):cap.prepare(env)
    assert (folder/'private.pem').read_bytes()==first
    workflow=(ROOT/'.github/workflows/prod-smoke.yml').read_text()
    assert 'private.pem' not in workflow


def test_real_output_cms_roundtrip_uses_only_synthetic_key(cap,monkeypatch,tmp_path,synthetic_crypto):
    private,cert=synthetic_crypto
    monkeypatch.setattr(cap,'RECIPIENT',cert);monkeypatch.setattr(cap,'RECIPIENT_SHA256',cap.sha(cert.read_bytes()))
    value={'raw_sources':'synthetic only','acceptance':False};target=tmp_path/'proof.cms'
    cap.encrypt(value,target,lambda:20)
    result=subprocess.run(['openssl','cms','-decrypt','-binary','-inform','DER','-inkey',str(private)],
        input=target.read_bytes(),stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=20,check=True)
    assert json.loads(result.stdout)==value


def controller_module():
    spec=importlib.util.spec_from_file_location('sealer_under_test',ROOT/'.github/diagnostics/seal-cached-source-context.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def test_sealer_pins_artifact_session_plaintext_and_uses_only_public_cert(prepared,cap,monkeypatch,tmp_path):
    env,folder,meta=prepared;sealer=controller_module()
    manifest=tmp_path/'synthetic-context.json';manifest.write_bytes(cap.encoded(CONTEXT))
    monkeypatch.setattr(sealer,'PRIVATE_CONTEXT',manifest)
    monkeypatch.setattr(sealer.capture,'CONTEXT_SHA256',cap.sha(manifest.read_bytes()))
    archive=tmp_path/'public.zip'
    with zipfile.ZipFile(archive,'w') as z:
        for name in ('public.pem','public.json'):z.write(folder/name,name)
    result=sealer.seal(archive,cap.sha(archive.read_bytes()),env['GITHUB_RUN_ID'],env['GITHUB_SHA'],RUNTIME,tmp_path/'sealed')
    assert result['sealed'] and PROJECT_NOT_IN(result,CONTEXT['project'])
    assert cap.decrypt_context((tmp_path/'sealed/cached-source-context.cms').read_bytes(),folder/'private.pem')==CONTEXT


def PROJECT_NOT_IN(result,project):return project not in json.dumps(result)


def test_repository_recipient_matches_pin_and_is_a_3072_bit_rsa_certificate(cap):
    cap.recipient_ready()
    certificate=cap.RECIPIENT.read_bytes()
    public=subprocess.run(['openssl','x509','-in',str(cap.RECIPIENT),'-pubkey','-noout'],
        stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,check=True,timeout=20)
    details=subprocess.run(['openssl','pkey','-pubin','-text','-noout'],input=public.stdout,
        stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,check=True,timeout=20)
    assert b'Public-Key: (3072 bit)' in details.stdout
    assert b'Exponent: 65537' in details.stdout
    assert b'PRIVATE KEY' not in certificate


def test_another_valid_recipient_is_rejected_before_output_or_crypto(cap,monkeypatch,tmp_path,synthetic_crypto):
    _,other_certificate=synthetic_crypto
    assert cap.sha(other_certificate.read_bytes())!=cap.RECIPIENT_SHA256
    monkeypatch.setattr(cap,'RECIPIENT',other_certificate)
    monkeypatch.setattr(cap.subprocess,'run',lambda *a,**k:pytest.fail('crypto with unpinned recipient'))
    target=tmp_path/'proof.cms'
    with pytest.raises(cap.CaptureError,match='fence'):
        cap.encrypt({'synthetic':'recipient mismatch'},target,lambda:20)
    assert not target.exists()
