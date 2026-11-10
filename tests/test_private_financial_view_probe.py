"""Credential-free checks for the exact finite read-only encrypted source transport."""
import base64
import copy
import datetime as dt
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import stat
import subprocess
import types
import urllib.error
from urllib.parse import urlsplit
import zipfile

import pytest

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/'.github/diagnostics/cached-source-capture.py'
RUNTIME='a'*40
KEY='synthetic-secret-\"-ü-must-not-leak'
PROJECT='Synthetic private project'
CONTEXT={'schema':1,'project':PROJECT,'cut':'2026-11-09','nonce':'b'*64}

@pytest.fixture
def cap():
    spec=importlib.util.spec_from_file_location('capture_under_test',SCRIPT)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module

class Response(io.BytesIO):
    def __init__(self,value,url,*,status=200,headers=None):
        super().__init__(value if isinstance(value,bytes) else json.dumps(value).encode())
        self.status=status;self.url=url
        self.headers={'Cache-Control':'private, no-store','Content-Type':'application/json',**(headers or {})}
    def geturl(self):return self.url
    def read1(self,n):return self.read(n)


def payload(cap,purpose):
    value={'schema':1,'purpose':purpose,'runtime':{'commit':RUNTIME,'version':'0.0.1'},
           'coherent':True,'reads_only':True,'source_files_written':False,'evidence_complete':False,
           'files':[],'gaps':['known_gap']}
    if purpose==cap.PURPOSES[0]:
        value.update(project=PROJECT,cut=CONTEXT['cut'],financial_acceptance=False,
                     paid_through_date=None,paid_through_not_inferred_from_upload_or_filename=True)
        for slot,path in [('finance','baseline/finance.xlsx'),('bank_rss','estimate/2026-11-05.xlsx')]:
            raw=('original synthetic XLSX bytes '+slot).encode()
            value['files'].append({'slot':slot,'logical_path':path,'bytes':len(raw),'sha256':cap.sha(raw),
                                   'content_base64':base64.b64encode(raw).decode()})
    else:
        value.update(production_acceptance=False,models_or_scores_computed=False)
        value['files']=[{'logical_path':'krt/catalogue.json','bytes':19,'sha256':'c'*64,'projection':{}}]
    return value

class Server:
    def __init__(self,cap,change=None):self.cap=cap;self.calls=[];self.change=change
    def open(self,request,timeout):
        self.calls.append(request)
        assert 0<timeout<=60
        assert request.full_url.startswith(self.cap.BASE+'/')
        path=urlsplit(request.full_url).path
        if path=='/health':
            value={'status':'ok','commit':RUNTIME,'version':'0.0.1'}
            if self.change=='health':value['commit']='f'*40
            return Response(value,request.full_url)
        assert request.get_method()=='POST'
        body=json.loads(request.data);assert body['key']==KEY
        value=payload(self.cap,body['purpose'])
        if self.change: value=self.change(value) if callable(self.change) else value
        return Response(value,request.full_url)

@pytest.fixture
def encrypted(cap,monkeypatch):
    captured=[]
    def fake(args,**kwargs):
        assert args[:4]==['openssl','cms','-encrypt','-aes-256-gcm']
        assert args[-2:]==['-keyopt','rsa_mgf1_md:sha256']
        assert set(kwargs['env'])=={'PATH'} and kwargs['timeout']<=30
        value=json.loads(kwargs['input']);captured.append(value)
        assert KEY not in json.dumps(value,ensure_ascii=False)
        kwargs['stdout'].write(b'CiphertextOnly'+str(len(captured)).encode())
        return types.SimpleNamespace(returncode=0)
    monkeypatch.setattr(cap.subprocess,'run',fake)
    return captured


def test_exact_reads_encrypt_original_bytes_and_public_result_is_private(cap,encrypted,tmp_path,capsys):
    server=Server(cap);result=cap.Capture(RUNTIME,transport=server).run(CONTEXT,lambda:KEY,tmp_path/'cipher')
    assert result['captured'] and result['ciphertext_count']==4
    assert not result['acceptance_performed'] and result['krt_same_sources']
    assert len(encrypted)==4
    assert encrypted[0]['capture']['gaps']==['known_gap']
    for record in encrypted[0]['capture']['files']:
        raw=base64.b64decode(record['content_base64'])
        assert record['sha256']==cap.sha(raw) and record['bytes']==len(raw)
    private=json.dumps(result)
    for forbidden in (KEY,PROJECT,CONTEXT['cut'],'original synthetic','catalogue.json'):
        assert forbidden not in private and forbidden not in capsys.readouterr().out
    posts=[r for r in server.calls if r.get_method()=='POST']
    assert [json.loads(r.data)['purpose'] for r in posts]==list(cap.PURPOSES)
    assert [urlsplit(r.full_url).path for r in posts]==[cap.FINANCE_PATH,cap.KRT_PATH,cap.KRT_PATH]
    assert all(r.get_method()=='POST' or r.full_url==cap.BASE+'/health' for r in server.calls)
    assert all(stat.S_IMODE(p.stat().st_mode)==0o600 for p in (tmp_path/'cipher').iterdir())
    assert sorted(p.suffix for p in (tmp_path/'cipher').iterdir())==['.cms']*4

@pytest.mark.parametrize('value',['','f'*39,'f'*40+'?x',None,True])
def test_bad_expected_runtime_before_any_transport(cap,value):
    with pytest.raises(cap.CaptureError):cap.Capture(value,transport=object())

@pytest.mark.parametrize('path',['/monitor/view','/monitor/estimate','/auctions/krt/watch','/auctions/krt/ranking',
    '/monitor/audit/sources?x=1','https://evil.invalid/monitor/audit/sources','//evil.invalid'])
def test_no_credential_to_arbitrary_or_mutating_route(cap,path):
    client=cap.Capture(RUNTIME,transport=object());client._key=KEY;client._context=CONTEXT
    with pytest.raises(cap.CaptureError):client.post(path,{'key':KEY,'purpose':cap.PURPOSES[0]})

@pytest.mark.parametrize('change',[{'project':'different'},{'cut':'2026-11-10'},{'purpose':'invalid'},
    {'session':'claimed-owner'},{'url':'https://evil.invalid'},{'offset':1},{'key':'other'}])
def test_fixed_body_cannot_be_extended_or_changed(cap,change):
    runner=cap.Capture(RUNTIME,transport=object());runner._key=KEY;runner._context=CONTEXT
    body={'project':PROJECT,'cut':CONTEXT['cut'],'purpose':cap.PURPOSES[0],'key':KEY};body.update(change)
    with pytest.raises(cap.CaptureError):runner.post(cap.FINANCE_PATH,body)

@pytest.mark.parametrize('change',[{'schema':True},{'cut':'2026-11-10'},{'project':'../x'},{'project':' x '},
    {'key':KEY},{'nonce':'short'}])
def test_pinned_minimal_context_rejects_selectors_and_credentials(cap,change):
    context={**CONTEXT,**change}
    with pytest.raises(cap.CaptureError):cap.validate_context(context)


def test_runtime_gate_before_secret_read(cap,tmp_path):
    server=Server(cap,'health')
    with pytest.raises(cap.CaptureError,match='runtime'):
        cap.Capture(RUNTIME,transport=server).run(CONTEXT,lambda:pytest.fail('secret read'),tmp_path/'cipher')
    assert len(server.calls)==1 and not (tmp_path/'cipher').exists()

@pytest.mark.parametrize('field,value',[('coherent',False),('reads_only',False),('source_files_written',True),
    ('evidence_complete',True),('runtime',{'commit':'f'*40,'version':'0.0.1'}),('purpose','other'),
    ('files',[{}]),('gaps',[1])])
def test_bad_server_contract_stops_once_and_leaves_no_artifact(cap,encrypted,tmp_path,field,value):
    def change(response):response[field]=value;return response
    server=Server(cap,change)
    with pytest.raises(cap.CaptureError):cap.Capture(RUNTIME,transport=server).run(CONTEXT,lambda:KEY,tmp_path/'cipher')
    assert len([r for r in server.calls if r.get_method()=='POST'])==1
    assert not (tmp_path/'cipher').exists()

@pytest.mark.parametrize('kind',['len','hash','base64','echo','escaped_echo','binary_echo'])
def test_raw_binary_hash_and_secret_echo_fences(cap,encrypted,tmp_path,kind):
    def change(value):
        record=value['files'][0]
        if kind=='len':record['bytes']+=1
        if kind=='hash':record['sha256']='0'*64
        if kind=='base64':record['content_base64']='*'
        if kind=='echo':value['private_echo']=KEY
        if kind=='escaped_echo':value['private_echo']={'nested':KEY}
        if kind=='binary_echo':
            raw=KEY.encode();record.update(content_base64=base64.b64encode(raw).decode(),sha256=cap.sha(raw),bytes=len(raw))
        return value
    with pytest.raises(cap.CaptureError):cap.Capture(RUNTIME,transport=Server(cap,change)).run(CONTEXT,lambda:KEY,tmp_path/'cipher')
    assert not encrypted and not (tmp_path/'cipher').exists()

@pytest.mark.parametrize('kind',['duplicate','blank','badsha','badbytes'])
def test_krt_record_identity_is_real_and_unique(cap,kind):
    value=payload(cap,cap.PURPOSES[1]);runner=cap.Capture(RUNTIME,transport=object());runner._context=CONTEXT
    if kind=='duplicate':value['files'].append(copy.deepcopy(value['files'][0]))
    if kind=='blank':value['files'][0]['logical_path']=''
    if kind=='badsha':value['files'][0]['sha256']=None
    if kind=='badbytes':value['files'][0]['bytes']=True
    with pytest.raises(cap.CaptureError):runner.validate(value,cap.PURPOSES[1],value['runtime'])

@pytest.mark.parametrize('change',['changed','empty'])
def test_two_coherent_captures_do_not_claim_same_cohort_on_drift_or_absence(cap,encrypted,tmp_path,change):
    def mutate(value):
        if value['purpose'] in cap.PURPOSES[1:]:
            if change=='empty':value['files']=[]
            elif value['purpose']==cap.PURPOSES[2]:value['files'][0]['sha256']='d'*64
        return value
    result=cap.Capture(RUNTIME,transport=Server(cap,mutate)).run(CONTEXT,lambda:KEY,tmp_path/'cipher')
    assert not result['krt_same_sources'] and not encrypted[-1]['krt_same_sources_between_reads']
    assert encrypted[-1]['transport_gaps'] and not result['acceptance_performed']

@pytest.mark.parametrize('status',[301,302,303,307,308,401,403,409,413,429,500,503])
def test_http_errors_never_leak_body_or_retry(cap,tmp_path,status):
    calls=[]
    class Bad:
        def open(self,request,timeout):
            calls.append(request);raise urllib.error.HTTPError(request.full_url,status,'PRIVATE '+KEY,{},io.BytesIO(KEY.encode()))
    runner=cap.Capture(RUNTIME,transport=Bad())
    with pytest.raises(cap.CaptureError) as caught:runner.health()
    assert caught.value.status==status and KEY not in str(caught.value) and len(calls)==1

@pytest.mark.parametrize('kind',['url','length','encoding','no_store','content_type','invalid_json','duplicate_json','nonfinite'])
def test_unsafe_transport_and_json_are_rejected(cap,kind):
    runner=cap.Capture(RUNTIME,transport=object());runner._key=KEY;runner._context=CONTEXT
    class Bad:
        def open(self,request,timeout):
            raw=payload(cap,cap.PURPOSES[1]);headers={};url=request.full_url
            if kind=='url':url='https://evil.invalid/'
            if kind=='length':headers['Content-Length']=str(cap.MAX_RESPONSE+1)
            if kind=='encoding':headers['Content-Encoding']='gzip'
            if kind=='no_store':headers['Cache-Control']='public'
            if kind=='content_type':headers['Content-Type']='text/html'
            if kind=='invalid_json':raw=b'bad'
            if kind=='duplicate_json':raw=b'{"x":1,"x":2}'
            if kind=='nonfinite':raw=b'{"x":NaN}'
            return Response(raw,url,headers=headers)
    runner.client=Bad()
    with pytest.raises(cap.CaptureError):runner.post(cap.KRT_PATH,{'key':KEY,'purpose':cap.PURPOSES[1]})

@pytest.mark.parametrize('error',[TimeoutError('PRIVATE '+KEY),urllib.error.URLError(TimeoutError('PRIVATE')),OSError('PRIVATE')])
def test_timeout_is_distinct_and_safe(cap,error):
    class Bad:
        def open(self,*a,**k):raise error
    with pytest.raises(cap.CaptureError) as caught:cap.Capture(RUNTIME,transport=Bad()).health()
    assert caught.value.timeout==isinstance(getattr(error,'reason',error),TimeoutError)
    assert KEY not in str(caught.value)


def test_expired_capture_stops_before_http(cap):
    now=[0];runner=cap.Capture(RUNTIME,transport=object(),clock=lambda:now[0]);now[0]=cap.CAPTURE_SECONDS+1
    with pytest.raises(cap.CaptureError,match='deadline'):runner.health()


def test_wrong_recipient_and_encryption_failure_cannot_publish(cap,monkeypatch,tmp_path):
    wrong=tmp_path/'recipient.pem';wrong.write_text('invalid');monkeypatch.setattr(cap,'RECIPIENT',wrong)
    with pytest.raises(cap.CaptureError):cap.encrypt({},tmp_path/'failed.cms',lambda:10)
    assert not (tmp_path/'failed.cms').exists()


def test_failed_encrypt_removes_only_its_created_file(cap,monkeypatch,tmp_path):
    def fail(*a,**k):k['stdout'].write(b'partial');return types.SimpleNamespace(returncode=1)
    monkeypatch.setattr(cap.subprocess,'run',fail)
    target=tmp_path/'failed.cms'
    with pytest.raises(cap.CaptureError):cap.encrypt({},target,lambda:10)
    assert not target.exists()
    target.write_bytes(b'prior')
    with pytest.raises(cap.CaptureError):cap.encrypt({},target,lambda:10)
    assert target.read_bytes()==b'prior'


def test_existing_output_not_reused_or_deleted(cap,encrypted,tmp_path):
    out=tmp_path/'cipher';out.mkdir()
    with pytest.raises(cap.CaptureError):cap.Capture(RUNTIME,transport=Server(cap)).run(CONTEXT,lambda:KEY,out)
    assert out.is_dir() and not list(out.iterdir())


def test_workflow_only_has_existing_admin_secret_and_fixed_modes(cap):
    text=(ROOT/'.github/workflows/prod-smoke.yml').read_text()
    assert text.count('secrets.')==1 and 'secrets.DEVELOPAID_ADMIN_KEY' in text
    assert 'prepare' in text and ' capture' in text and ' probe' not in text and ' apply' not in text
    assert 'private.pem' not in text and 'source-audit-cipher/*.cms' in text
    assert 'public.pem' in text and 'public.json' in text and 'retention-days: 1' in text
    assert 'github.run_attempt == 1' in text and 'persist-credentials: false' in text
    assert 'contents: read' in text and 'contents: write' not in text
    assert cap.POST_PATHS==frozenset(('/monitor/audit/sources','/auctions/krt/audit/cached'))
    assert 'project:' not in text and 'cut:' not in text

@pytest.mark.parametrize('mode',[[],['apply'],['probe'],['verify'],['capture','anything']])
def test_no_default_or_legacy_mode(cap,mode,capsys):
    assert cap.main({},mode)==1
    result=json.loads(capsys.readouterr().out)
    assert result['captured'] is False and result['error_code']=='setup'

@pytest.mark.parametrize('stage',[2,3])
def test_later_unknown_transport_stops_once_and_removes_prior_ciphertexts(cap,encrypted,tmp_path,stage):
    class Later(Server):
        def open(self,request,timeout):
            if request.get_method()=='POST' and len([r for r in self.calls if r.get_method()=='POST'])+1==stage:
                self.calls.append(request);raise TimeoutError('PRIVATE '+KEY)
            return super().open(request,timeout)
    server=Later(cap);runner=cap.Capture(RUNTIME,transport=server)
    with pytest.raises(cap.CaptureError) as caught:runner.run(CONTEXT,lambda:KEY,tmp_path/'cipher')
    assert caught.value.phase==('krt_metadata' if stage==2 else 'krt_replay') and caught.value.timeout
    assert len([r for r in server.calls if r.get_method()=='POST'])==stage
    assert not (tmp_path/'cipher').exists() and runner._key==''


def test_final_health_drift_prevents_any_ciphertext_publication(cap,encrypted,tmp_path):
    class Drift(Server):
        def open(self,request,timeout):
            response=super().open(request,timeout)
            if request.full_url.endswith('/health') and len(self.calls)==8:
                return Response({'status':'ok','commit':RUNTIME,'version':'0.0.2'},request.full_url)
            return response
    with pytest.raises(cap.CaptureError,match='runtime'):
        cap.Capture(RUNTIME,transport=Drift(cap)).run(CONTEXT,lambda:KEY,tmp_path/'cipher')
    assert not (tmp_path/'cipher').exists()


def test_streaming_response_over_cap_or_deadline_is_not_accepted(cap):
    now=[0];runner=cap.Capture(RUNTIME,transport=object(),clock=lambda:now[0])
    class Slow(Response):
        def read1(self,n):now[0]=cap.CAPTURE_SECONDS+1;return b'{}'
    class Fake:
        def open(self,request,timeout):return Slow({},request.full_url)
    runner.client=Fake()
    with pytest.raises(cap.CaptureError,match='deadline'):runner.health()
    with pytest.raises(cap.CaptureError):
        cap.read_response(Response(b'x'*100,cap.BASE+'/health'),cap.BASE+'/health',16,lambda:10)


def test_reads_slower_than_old_fifteen_second_limit_complete_exactly_once(cap,encrypted,tmp_path):
    now=[0]
    class Slow(Server):
        def open(self,request,timeout):
            assert timeout>17
            response=super().open(request,timeout);now[0]+=18.5;return response
    server=Slow(cap);result=cap.Capture(RUNTIME,transport=server,clock=lambda:now[0]).run(CONTEXT,lambda:KEY,tmp_path/'cipher')
    assert result['captured'] and len([r for r in server.calls if r.get_method()=='POST'])==3
