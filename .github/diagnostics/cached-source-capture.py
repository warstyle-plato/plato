"""Finite saved-source capture: one ephemeral input, three fixed read-only POSTs."""
from __future__ import annotations
import base64
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import signal
import ssl
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request

BASE = 'https://developaid.ru'
API = 'https://api.github.com'
REPOSITORY = 'warstyle-plato/plato'
BRANCH = 'refs/heads/ops/financial-view-root'
ACTOR = 'warstyle-plato'
PREFIX = '/repos/'+REPOSITORY
REF_PATH = PREFIX+'/git/ref/heads/ops/financial-view-root'
DELIVERY_FILE = '.github/diagnostics/cached-source-context.cms'
RECIPIENT = Path(__file__).with_name('contract-audit-recipient.pem')
RECIPIENT_SHA256 = 'e8d6f457f0f3b7bcfdf311dd9277799546a38d8209a3764716883f0b88bb8292'
CONTEXT_SHA256 = 'e52da811132912ad6e31b7c378f2a91d782566781cc6db30b303ab2a22518215'
PLACEHOLDER_SHA256 = 'e9ee14f1c45ed68f0ff5c988f6a8430c51f48f6d3af633200a01bbaeada1fc81'
FINANCE_PATH = '/monitor/audit/sources'
KRT_PATH = '/auctions/krt/audit/cached'
PURPOSES = ('finance_sources_v1','krt_cached_metadata_v1','krt_cached_replay_v1')
POST_PATHS = frozenset((FINANCE_PATH,KRT_PATH))
SOURCE_CUT = '2026-11-09'
WAIT_SECONDS = 900
POLL_SECONDS = 5
HTTP_SECONDS = 60
CAPTURE_SECONDS = 420
MAX_RESPONSE = 23*1024*1024
MAX_INPUT = 16384
MAX_GITHUB_RESPONSE = 2*1024*1024
MAX_CIPHERTEXT_TOTAL = 72*1024*1024
REASONS = frozenset(('setup','input','crypto','fence','deadline','transport','redirect',
    'http','http_auth','http_capacity','response','runtime','secret_echo','source_hash','output'))

PHASES=frozenset(('setup','health','context_wait','finance','krt_metadata','krt_replay','output','done'))

class CaptureError(Exception):
    def __init__(self,code,status=0,*,timeout=False):
        self.code=code if code in REASONS else 'setup'
        self.status=status if type(status) is int and 0<=status<=599 else 0
        self.phase='setup';self.timeout=bool(timeout or code=='deadline')
        super().__init__(self.code)

def digest(value,size=64):
    return isinstance(value,str) and re.fullmatch('[0-9a-f]{'+str(size)+'}',value) is not None

def sha(raw):return hashlib.sha256(raw).hexdigest()

def strict_json(raw):
    def pairs(values):
        result={}
        for key,value in values:
            if key in result:raise CaptureError('response')
            result[key]=value
        return result
    def bad(_):raise CaptureError('response')
    def number(value):
        result=float(value)
        return result if math.isfinite(result) else bad(value)
    try:result=json.loads(raw,object_pairs_hook=pairs,parse_constant=bad,parse_float=number)
    except (ValueError,UnicodeError,RecursionError):raise CaptureError('response') from None
    if not isinstance(result,dict):raise CaptureError('response')
    return result

def contains_secret(value,secret):
    if isinstance(value,str):return secret in value
    if isinstance(value,dict):return any(contains_secret(k,secret) or contains_secret(v,secret) for k,v in value.items())
    if isinstance(value,list):return any(contains_secret(v,secret) for v in value)
    return False

def encoded(value):
    try:return json.dumps(value,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode()
    except (ValueError,TypeError,RecursionError):raise CaptureError('response') from None

def bounded_file(path,limit):
    try:
        if path.is_symlink() or not path.is_file():raise CaptureError('input')
        with path.open('rb') as stream:raw=stream.read(limit+1)
    except OSError:raise CaptureError('input') from None
    if not raw or len(raw)>limit:raise CaptureError('input')
    return raw

def clean_env():return {'PATH':os.environ.get('PATH','/usr/bin:/bin')}

def recipient_ready():
    if sha(bounded_file(RECIPIENT,16384))!=RECIPIENT_SHA256:raise CaptureError('fence')

def trusted_checkout(environment):
    expected={'GITHUB_REPOSITORY':REPOSITORY,'GITHUB_REF':BRANCH,'GITHUB_ACTOR':ACTOR,
        'GITHUB_TRIGGERING_ACTOR':ACTOR,'GITHUB_EVENT_NAME':'workflow_dispatch','GITHUB_RUN_ATTEMPT':'1',
        'GITHUB_WORKFLOW_REF':REPOSITORY+'/.github/workflows/prod-smoke.yml@'+BRANCH}
    if any(environment.get(k)!=v for k,v in expected.items()) or not digest(environment.get('GITHUB_SHA'),40):
        raise CaptureError('setup')
    if (environment.get('GITHUB_WORKFLOW_SHA')!=environment.get('GITHUB_SHA')
            or not digest(environment.get('EXPECTED_RUNTIME_COMMIT'),40)):
        raise CaptureError('setup')
    try:
        here=Path(__file__).resolve().parents[2]
        actual=subprocess.run(['git','rev-parse','HEAD'],cwd=here,stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,timeout=10,env=clean_env())
        changed=subprocess.run(['git','status','--porcelain','--untracked-files=all'],cwd=here,
            stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=10,env=clean_env())
    except (OSError,subprocess.SubprocessError):raise CaptureError('setup') from None
    if actual.returncode or actual.stdout.strip()!=environment['GITHUB_SHA'].encode() or changed.returncode or changed.stdout:
        raise CaptureError('setup')
    recipient_ready()

def validate_context(value):
    if (not isinstance(value,dict) or set(value)!={'schema','project','cut','nonce'}
            or type(value['schema']) is not int or value['schema']!=1
            or not isinstance(value['project'],str) or not 1<=len(value['project'])<=200
            or value['project']!=value['project'].strip()
            or any(c in value['project'] for c in ('/','\\','\0')) or value['project'] in {'.','..'}
            or value['cut']!=SOURCE_CUT or not digest(value['nonce'])):raise CaptureError('fence')
    return dict(value)

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):raise CaptureError('redirect')

def opener():
    return urllib.request.build_opener(urllib.request.ProxyHandler({}),
        urllib.request.HTTPSHandler(context=ssl.create_default_context()),NoRedirect())

def read_response(response,url,limit,remaining):
    if response.geturl()!=url:raise CaptureError('redirect')
    if response.status!=200:raise CaptureError('http',response.status)
    length=response.headers.get('Content-Length')
    if length is not None and (not str(length).isdigit() or int(length)>limit):raise CaptureError('response')
    if response.headers.get('Content-Encoding','identity').lower() not in ('','identity'):raise CaptureError('response')
    chunks=[];size=0;read=getattr(response,'read1',response.read)
    while True:
        remaining()
        chunk=read(min(65536,limit+1-size));remaining()
        if not chunk:break
        size+=len(chunk)
        if size>limit:raise CaptureError('response')
        chunks.append(chunk)
    return b''.join(chunks)

def request_once(client,request,timeout,limit,remaining):
    try:
        allotted=min(timeout,remaining())
        with client.open(request,timeout=allotted) as response:
            raw=read_response(response,request.full_url,limit,remaining)
            headers=response.headers
    except CaptureError:raise
    except urllib.error.HTTPError as exc:
        code='redirect' if exc.code in (301,302,303,307,308) else 'http_auth' if exc.code in (401,403) else 'http_capacity' if exc.code==429 else 'http'
        raise CaptureError(code,exc.code) from None
    except (OSError,ValueError,urllib.error.URLError,TimeoutError) as exc:
        raise CaptureError('transport',timeout=isinstance(exc,TimeoutError) or isinstance(getattr(exc,'reason',None),TimeoutError)) from None
    return raw,headers

class Capture:
    def __init__(self,expected,*,transport=None,clock=time.monotonic):
        if not digest(expected,40):raise CaptureError('setup')
        self.expected=expected;self.client=transport or opener();self.clock=clock
        self.deadline=clock()+CAPTURE_SECONDS;self._key='';self._context=None;self.phase='setup'
    def remaining(self):
        left=self.deadline-self.clock()
        if left<=0:raise CaptureError('deadline')
        return left
    def health(self):
        request=urllib.request.Request(BASE+'/health',headers={'Cache-Control':'no-store','Accept':'application/json'})
        try:raw,_=request_once(self.client,request,HTTP_SECONDS,65536,self.remaining)
        except CaptureError as exc:exc.phase='health';raise
        value=strict_json(raw)
        if (value.get('status')!='ok' or value.get('commit')!=self.expected
                or not isinstance(value.get('version'),str) or not re.fullmatch(r'\d+\.\d+\.\d+',value['version'])):
            problem=CaptureError('runtime');problem.phase='health';raise problem
        return {'commit':value['commit'],'version':value['version']}
    def post(self,path,body):
        if not self._context or not self._key or path not in POST_PATHS:raise CaptureError('fence')
        expected=({'purpose':PURPOSES[0],'project':self._context['project'],'cut':SOURCE_CUT,'key':self._key}
                  if path==FINANCE_PATH else {'purpose':body.get('purpose'),'key':self._key})
        if (body!=expected or (path==KRT_PATH and body.get('purpose') not in PURPOSES[1:])):
            raise CaptureError('fence')
        rawbody=encoded(body)
        if len(rawbody)>MAX_INPUT:raise CaptureError('input')
        request=urllib.request.Request(BASE+path,data=rawbody,headers={'Content-Type':'application/json',
            'Accept':'application/json','Cache-Control':'no-store'},method='POST')
        raw,headers=request_once(self.client,request,HTTP_SECONDS,MAX_RESPONSE,self.remaining)
        if ('no-store' not in headers.get('Cache-Control','').lower()
                or headers.get('Content-Type','').split(';',1)[0].strip().lower()!='application/json'):
            raise CaptureError('response')
        value=strict_json(raw)
        if self._key.encode() in raw or contains_secret(value,self._key):raise CaptureError('secret_echo')
        return value
    def validate(self,value,purpose,runtime):
        if (type(value.get('schema')) is not int or value['schema']!=1 or value.get('purpose')!=purpose
                or value.get('runtime')!=runtime or value.get('coherent') is not True
                or value.get('reads_only') is not True or value.get('source_files_written') is not False
                or value.get('evidence_complete') is not False
                or not isinstance(value.get('files'),list) or not isinstance(value.get('gaps'),list)
                or any(not isinstance(x,str) for x in value['gaps'])):raise CaptureError('response')
        identities=set()
        for record in value['files']:
            if (not isinstance(record,dict) or not isinstance(record.get('logical_path'),str)
                    or not record['logical_path'] or len(record['logical_path'])>512
                    or record['logical_path'] in identities
                    or not digest(record.get('sha256')) or type(record.get('bytes')) is not int
                    or record['bytes']<0):raise CaptureError('response')
            identities.add(record['logical_path'])
        if purpose==PURPOSES[0]:
            if (value.get('project')!=self._context['project'] or value.get('cut')!=SOURCE_CUT
                    or value.get('financial_acceptance') is not False
                    or value.get('paid_through_not_inferred_from_upload_or_filename') is not True):raise CaptureError('response')
            seen=set();total=0
            for record in value['files']:
                if not isinstance(record,dict) or record.get('slot') not in {'finance','finance_meta','bank_rss','bank_rss_meta'}:
                    raise CaptureError('response')
                slot=record['slot']
                if slot in seen:raise CaptureError('response')
                seen.add(slot)
                if slot not in {'finance','bank_rss'}:continue
                if not isinstance(record.get('content_base64'),str):raise CaptureError('response')
                try:binary=base64.b64decode(record['content_base64'],validate=True)
                except (ValueError,TypeError):raise CaptureError('response') from None
                if self._key.encode() in binary:raise CaptureError('secret_echo')
                total+=len(binary)
                if (type(record.get('bytes')) is not int or record['bytes']!=len(binary)
                        or record.get('sha256')!=sha(binary) or total>16*1024*1024):raise CaptureError('source_hash')
        elif value.get('production_acceptance') is not False or value.get('models_or_scores_computed') is not False:
            raise CaptureError('response')
        return value
    def run(self,context,key_getter,output):
        self._context=validate_context(context)
        runtime=self.health()  # Before even reading existing admin credential.
        key=key_getter()
        if not isinstance(key,str) or not key.strip() or len(key)>4096:raise CaptureError('setup')
        self._key=key.strip();paths=[];stats=[];observed={};created=False
        try:
            try:output.mkdir(mode=0o700);created=True  # Never reuse an earlier capture directory.
            except OSError:raise CaptureError('output') from None
            for number,purpose in enumerate(PURPOSES,1):
                self.phase='health';current=self.health()
                if current!=runtime:raise CaptureError('runtime')
                body={'purpose':purpose,'key':self._key}
                if number==1:body.update(project=context['project'],cut=SOURCE_CUT)
                self.phase=('finance','krt_metadata','krt_replay')[number-1]
                value=self.validate(self.post(FINANCE_PATH if number==1 else KRT_PATH,body),purpose,runtime)
                # Preserve raw source bytes and all server gaps, never plaintext files.
                record={'schema':1,'health':runtime,'capture':value}
                target=output/('capture-'+str(number)+'.cms')
                self.phase='output'
                stats.append(encrypt(record,target,self.remaining));paths.append(target)
                observed[purpose]=[(f.get('logical_path'),f.get('sha256'),f.get('bytes')) for f in value['files'] if isinstance(f,dict)]
                del value,record
                if sum(item['bytes'] for item in stats)>MAX_CIPHERTEXT_TOTAL:raise CaptureError('output')
            self.phase='health'
            if self.health()!=runtime:raise CaptureError('runtime')
            same=bool(observed[PURPOSES[1]]) and sorted(observed[PURPOSES[1]])==sorted(observed[PURPOSES[2]])
            receipt={'schema':1,'runtime':runtime,'capture_purposes':list(PURPOSES),'encrypted_files':stats,
                'krt_same_sources_between_reads':same,'transport_gaps':[] if same else ['krt_sources_changed_between_captures'],
                'source_acceptance_performed':False,'financial_acceptance_performed':False,'production_writes':False}
            self.phase='output'
            stats.append(encrypt(receipt,output/'receipt.cms',self.remaining));paths.append(output/'receipt.cms')
            if sum(item['bytes'] for item in stats)>MAX_CIPHERTEXT_TOTAL:raise CaptureError('output')
            return {'captured':True,'ciphertext_count':len(stats),'ciphertext_bytes':sum(x['bytes'] for x in stats),
                'ciphertext_sha256':sha(encoded(stats)),'krt_same_sources':same,'acceptance_performed':False}
        except BaseException as exc:
            if isinstance(exc,CaptureError) and exc.phase=='setup':exc.phase=self.phase
            for path in paths:path.unlink(missing_ok=True)
            if created and output.is_dir() and not any(output.iterdir()):output.rmdir()
            raise
        finally:self._key=''

def encrypt(value,target,remaining):
    recipient_ready();remaining()
    raw=encoded(value)
    if len(raw)>MAX_RESPONSE+65536:raise CaptureError('output')
    created=False
    try:
        descriptor=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);created=True
        with os.fdopen(descriptor,'wb') as stream:
            result=subprocess.run(['openssl','cms','-encrypt','-aes-256-gcm','-binary','-outform','DER',
                '-recip',str(RECIPIENT),'-keyopt','rsa_padding_mode:oaep','-keyopt','rsa_oaep_md:sha256',
                '-keyopt','rsa_mgf1_md:sha256'],input=raw,stdout=stream,stderr=subprocess.DEVNULL,
                timeout=min(30,remaining()),env=clean_env())
        remaining()
        if result.returncode:raise CaptureError('crypto')
        cipher=bounded_file(target,MAX_RESPONSE+65536)
        return {'bytes':len(cipher),'sha256':sha(cipher)}
    except CaptureError:
        if created:target.unlink(missing_ok=True)
        raise
    except (OSError,subprocess.SubprocessError) as exc:
        if created:target.unlink(missing_ok=True)
        raise CaptureError('crypto',timeout=isinstance(exc,subprocess.TimeoutExpired)) from None

def context_folder(environment):
    trusted_checkout(environment)
    run_id=environment.get('GITHUB_RUN_ID','')
    root=Path(environment.get('RUNNER_TEMP',''))
    if not re.fullmatch('[1-9][0-9]{0,19}',run_id) or not root.is_absolute() or not root.is_dir() or root.is_symlink():
        raise CaptureError('setup')
    return root/('source-session-'+run_id+'-1')

def run_openssl(arguments):
    try:
        result=subprocess.run(['openssl',*arguments],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
            timeout=30,env=clean_env())
    except (OSError,subprocess.SubprocessError):raise CaptureError('crypto') from None
    if result.returncode:raise CaptureError('crypto')

def prepare(environment):
    folder=context_folder(environment)
    # No admin credential is injected into this public-key preparation step.
    Capture(environment['EXPECTED_RUNTIME_COMMIT']).health()
    folder.mkdir(mode=0o700)
    private,certificate=folder/'private.pem',folder/'public.pem'
    run_openssl(['genpkey','-algorithm','RSA','-pkeyopt','rsa_keygen_bits:3072','-out',str(private)])
    os.chmod(private,0o600)
    run_openssl(['req','-new','-x509','-sha256','-days','1','-key',str(private),'-out',str(certificate),
        '-subj','/CN=PLATO-One-Time-Source-Capture'])
    metadata={'schema':1,'repository':REPOSITORY,'ref':BRANCH,'run_id':environment['GITHUB_RUN_ID'],
        'run_attempt':1,'workflow_sha':environment['GITHUB_SHA'],
        'expected_runtime_commit':environment['EXPECTED_RUNTIME_COMMIT'],
        'certificate_sha256':sha(bounded_file(certificate,16384)),'nonce':secrets.token_hex(32),
        'created_utc':dt.datetime.now(dt.timezone.utc).isoformat()}
    (folder/'public.json').write_bytes(encoded(metadata))
    return folder

def session(environment):
    folder=context_folder(environment)
    if folder.is_symlink() or not folder.is_dir() or stat.S_IMODE(folder.stat().st_mode)!=0o700:raise CaptureError('setup')
    paths={name:folder/name for name in ('private.pem','public.pem','public.json')}
    if any(p.is_symlink() or not p.is_file() for p in paths.values()):raise CaptureError('setup')
    if stat.S_IMODE(paths['private.pem'].stat().st_mode)!=0o600:raise CaptureError('setup')
    value=strict_json(bounded_file(paths['public.json'],4096))
    fields={'schema','repository','ref','run_id','run_attempt','workflow_sha','expected_runtime_commit','certificate_sha256','nonce','created_utc'}
    if (set(value)!=fields or type(value['schema']) is not int or value['schema']!=1
            or value['repository']!=REPOSITORY or value['ref']!=BRANCH
            or value['run_id']!=environment['GITHUB_RUN_ID'] or type(value['run_attempt']) is not int or value['run_attempt']!=1
            or value['workflow_sha']!=environment['GITHUB_SHA']
            or value['expected_runtime_commit']!=environment['EXPECTED_RUNTIME_COMMIT']
            or not digest(value['nonce']) or value['certificate_sha256']!=sha(bounded_file(paths['public.pem'],16384))):
        raise CaptureError('fence')
    try:
        created=dt.datetime.fromisoformat(value['created_utc']);age=(dt.datetime.now(dt.timezone.utc)-created).total_seconds()
    except (TypeError,ValueError):raise CaptureError('fence') from None
    if created.utcoffset()!=dt.timedelta(0) or not 0<=age<WAIT_SECONDS:raise CaptureError('deadline')
    return paths,WAIT_SECONDS-age

class Delivery:
    def __init__(self,environment,*,transport=None,clock=time.monotonic,sleep=time.sleep):
        self.environment=environment;self.client=transport or opener();self.clock=clock;self.sleep=sleep
        token=environment.get('GITHUB_TOKEN','')
        if not isinstance(token,str) or not token or len(token)>4096:raise CaptureError('setup')
        self.token=token
    def get(self,path,remaining):
        if remaining<=0:raise CaptureError('deadline')
        if not (path==REF_PATH or re.fullmatch(re.escape(PREFIX)+'/commits/[0-9a-f]{40}',path)
                or re.fullmatch(re.escape(PREFIX+'/contents/'+DELIVERY_FILE)+r'\?ref=[0-9a-f]{40}',path)):
            raise CaptureError('fence')
        deadline=self.clock()+remaining
        def left():
            value=deadline-self.clock()
            if value<=0:raise CaptureError('deadline')
            return value
        request=urllib.request.Request(API+path,headers={'Authorization':'Bearer '+self.token,
            'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28','Cache-Control':'no-store'})
        raw,_=request_once(self.client,request,15,MAX_GITHUB_RESPONSE,left)
        return strict_json(raw)
    def receive(self):
        paths,remaining=session(self.environment);deadline=self.clock()+remaining;initial=self.environment['GITHUB_SHA']
        def expired(signum,frame):raise CaptureError('deadline')
        previous=signal.signal(signal.SIGALRM,expired);signal.setitimer(signal.ITIMER_REAL,remaining)
        try:
            while True:
                left=deadline-self.clock()
                ref=self.get(REF_PATH,left)
                candidate=ref.get('object',{}).get('sha') if isinstance(ref.get('object'),dict) else None
                if not digest(candidate,40) or ref.get('ref')!=BRANCH or ref['object'].get('type')!='commit':raise CaptureError('fence')
                if candidate==initial:
                    self.sleep(min(POLL_SECONDS,max(0,deadline-self.clock())));continue
                commit=self.get(PREFIX+'/commits/'+candidate,deadline-self.clock());parents=commit.get('parents');files=commit.get('files')
                if (commit.get('sha')!=candidate or not isinstance(parents,list) or len(parents)!=1
                        or not isinstance(parents[0],dict) or parents[0].get('sha')!=initial
                        or not isinstance(files,list) or len(files)!=1 or not isinstance(files[0],dict)
                        or files[0].get('filename')!=DELIVERY_FILE or files[0].get('status')!='modified'
                        or 'previous_filename' in files[0]):raise CaptureError('fence')
                payload=self.get(PREFIX+'/contents/'+DELIVERY_FILE+'?ref='+candidate,deadline-self.clock())
                if (payload.get('type')!='file' or payload.get('path')!=DELIVERY_FILE or payload.get('encoding')!='base64'
                        or type(payload.get('size')) is not int or not 0<payload['size']<=MAX_INPUT
                        or not digest(payload.get('sha'),40) or payload['sha']!=files[0].get('sha')
                        or not isinstance(payload.get('content'),str)):raise CaptureError('fence')
                try:envelope=base64.b64decode(''.join(payload['content'].splitlines()),validate=True)
                except (ValueError,TypeError):raise CaptureError('input') from None
                blob=hashlib.sha1(b'blob '+str(len(envelope)).encode()+b'\0'+envelope).hexdigest()
                if len(envelope)!=payload['size'] or blob!=payload['sha'] or sha(envelope)==PLACEHOLDER_SHA256:raise CaptureError('input')
                if self.clock()>=deadline:raise CaptureError('deadline')
                # Preparation can be fifteen minutes old: recheck exact runtime before decryption.
                Capture(self.environment['EXPECTED_RUNTIME_COMMIT']).health()
                return decrypt_context(envelope,paths['private.pem'])
        finally:
            signal.setitimer(signal.ITIMER_REAL,0);signal.signal(signal.SIGALRM,previous);self.token=''

def decrypt_context(envelope,private):
    if not envelope or len(envelope)>MAX_INPUT:raise CaptureError('input')
    try:
        result=subprocess.run(['openssl','cms','-decrypt','-binary','-inform','DER','-inkey',str(private)],
            input=envelope,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=20,env=clean_env())
    except (OSError,subprocess.SubprocessError):raise CaptureError('crypto') from None
    if result.returncode or len(result.stdout)>MAX_INPUT or sha(result.stdout)!=CONTEXT_SHA256:raise CaptureError('crypto')
    return validate_context(strict_json(result.stdout))

def main(environment=None,argv=None):
    environment=os.environ if environment is None else environment
    argv=sys.argv[1:] if argv is None else argv
    started=time.monotonic();phase='setup'
    try:
        os.umask(0o077)
        if argv==['prepare']:
            prepare(environment);print('{"transport_prepared":true}');return 0
        if argv!=['capture']:raise CaptureError('setup')
        context_folder(environment)
        # Delivery waits on GitHub before the finite source-capture budget starts.
        phase='context_wait';context=Delivery(environment).receive()
        def expired(signum,frame):raise CaptureError('deadline')
        previous=signal.signal(signal.SIGALRM,expired);signal.setitimer(signal.ITIMER_REAL,CAPTURE_SECONDS)
        try:
            result=Capture(environment['EXPECTED_RUNTIME_COMMIT']).run(context,
                lambda:environment.get('CAPTURE_ADMIN_KEY',''),Path(environment['RUNNER_TEMP'])/'source-audit-cipher')
        finally:
            signal.setitimer(signal.ITIMER_REAL,0);signal.signal(signal.SIGALRM,previous)
        output=environment.get('GITHUB_OUTPUT')
        if output:
            with open(output,'a',encoding='utf-8') as stream:stream.write('proof_created=true\n')
        result['elapsed_seconds']=int(max(0,time.monotonic()-started))
        print(json.dumps(result,sort_keys=True));return 0
    except CaptureError as exc:
        print(json.dumps({'captured':False,'error_code':exc.code,'http_status':exc.status,
            'phase':(exc.phase if exc.phase!='setup' else phase) if (exc.phase if exc.phase!='setup' else phase) in PHASES else 'setup','timeout':exc.timeout,
            'elapsed_seconds':int(max(0,time.monotonic()-started))},sort_keys=True));return 1
    except Exception:
        print(json.dumps({'captured':False,'error_code':'setup','http_status':0,'phase':phase,
            'timeout':False,'elapsed_seconds':int(max(0,time.monotonic()-started))},sort_keys=True));return 1

if __name__=='__main__':sys.exit(main())
