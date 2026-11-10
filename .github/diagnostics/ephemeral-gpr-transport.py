"""Pinned public-key handoff for the one fixed approval; no new repository secret."""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import signal
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request

SCRIPT = Path(__file__).with_name('apply-approved-gpr.py')
spec = importlib.util.spec_from_file_location('approved_gpr_operation', SCRIPT)
ops = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ops)
API = 'https://api.github.com'
PREFIX = '/repos/warstyle-plato/plato'
REF_PATH = PREFIX+'/git/ref/heads/ops/approve-corpus-gpr-once'
DELIVERY_FILE = '.github/diagnostics/gpr-approval-input.cms'
WAIT_SECONDS = 900
POLL_SECONDS = 5
MAX_GITHUB_RESPONSE = 2*1024*1024


def context(environment):
    ops.trusted_checkout(environment)
    ops.input_ready()
    run_id = environment.get('GITHUB_RUN_ID','')
    if (not re.fullmatch('[1-9][0-9]{0,19}',run_id)
            or not ops.digest(environment.get('EXPECTED_RUNTIME_COMMIT'),40)):
        raise ops.ApplyError(ops.SETUP)
    root = Path(environment.get('RUNNER_TEMP',''))
    if not root.is_absolute() or not root.is_dir() or root.is_symlink():
        raise ops.ApplyError(ops.SETUP)
    return root/('gpr-session-'+run_id+'-1')


def run_openssl(arguments):
    try:
        result = subprocess.run(['openssl',*arguments],stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,timeout=30,env={'PATH':os.environ.get('PATH','/usr/bin:/bin')})
    except (OSError,subprocess.SubprocessError):
        raise ops.ApplyError(ops.CRYPTO) from None
    if result.returncode:
        raise ops.ApplyError(ops.CRYPTO)


def prepare(environment):
    folder = context(environment)
    # A rerun, stale session, or symlink cannot consume or replace another key.
    folder.mkdir(mode=0o700)
    private,certificate = folder/'private.pem',folder/'public.pem'
    run_openssl(['genpkey','-algorithm','RSA','-pkeyopt','rsa_keygen_bits:3072','-out',str(private)])
    os.chmod(private,0o600)
    run_openssl(['req','-new','-x509','-sha256','-days','1','-key',str(private),
                 '-out',str(certificate),'-subj','/CN=PLATO-One-Time-GPR-Transport'])
    certificate_bytes = ops.bounded_file(certificate,16384)
    metadata = {'schema':1,'repository':ops.REPOSITORY,'ref':ops.BRANCH,
        'run_id':environment['GITHUB_RUN_ID'],'run_attempt':1,
        'workflow_sha':environment['GITHUB_SHA'],
        'expected_runtime_commit':environment['EXPECTED_RUNTIME_COMMIT'],
        'certificate_sha256':ops.sha(certificate_bytes),'nonce':secrets.token_hex(32),
        'created_utc':dt.datetime.now(dt.timezone.utc).isoformat()}
    (folder/'public.json').write_text(json.dumps(metadata,sort_keys=True)+'\n')
    return folder


def session(environment):
    folder = context(environment)
    if folder.is_symlink() or not folder.is_dir() or stat.S_IMODE(folder.stat().st_mode)!=0o700:
        raise ops.ApplyError(ops.SETUP)
    paths = {name:folder/name for name in ('private.pem','public.pem','public.json')}
    if any(path.is_symlink() or not path.is_file() for path in paths.values()):
        raise ops.ApplyError(ops.SETUP)
    if stat.S_IMODE(paths['private.pem'].stat().st_mode)!=0o600:
        raise ops.ApplyError(ops.SETUP)
    value = ops.strict_json(ops.bounded_file(paths['public.json'],4096))
    required={'schema','repository','ref','run_id','run_attempt','workflow_sha',
              'expected_runtime_commit','certificate_sha256','nonce','created_utc'}
    if (set(value)!=required or type(value['schema']) is not int or value['schema']!=1
            or value['repository']!=ops.REPOSITORY or value['ref']!=ops.BRANCH
            or value['run_id']!=environment['GITHUB_RUN_ID']
            or type(value['run_attempt']) is not int or value['run_attempt']!=1
            or value['workflow_sha']!=environment['GITHUB_SHA']
            or value['expected_runtime_commit']!=environment['EXPECTED_RUNTIME_COMMIT']
            or not ops.digest(value['nonce'])
            or value['certificate_sha256']!=ops.sha(ops.bounded_file(paths['public.pem'],16384))):
        raise ops.ApplyError(ops.FENCE)
    try:
        created=dt.datetime.fromisoformat(value['created_utc'])
        age=(dt.datetime.now(dt.timezone.utc)-created).total_seconds()
    except (TypeError,ValueError):
        raise ops.ApplyError(ops.FENCE) from None
    if created.utcoffset()!=dt.timedelta(0) or not 0<=age<WAIT_SECONDS:
        raise ops.ApplyError(ops.DEADLINE)
    return paths, WAIT_SECONDS-age


class Delivery:
    def __init__(self, environment, *, opener=None, clock=time.monotonic, sleep=time.sleep):
        self.environment, self.clock, self.sleep = environment,clock,sleep
        self.opener = opener or urllib.request.build_opener(ops.NoRedirect())
        token=environment.get('GITHUB_TOKEN','')
        if not isinstance(token,str) or not token or len(token)>4096:
            raise ops.ApplyError(ops.SETUP)
        self.token=token

    def get(self,path,remaining):
        if remaining<=0:
            raise ops.ApplyError(ops.DEADLINE)
        # Only these exact, structured paths can receive the repository credential.
        if not (path==REF_PATH or re.fullmatch(re.escape(PREFIX)+'/commits/[0-9a-f]{40}',path)
                or re.fullmatch(re.escape(PREFIX+'/contents/'+DELIVERY_FILE)+'\\?ref=[0-9a-f]{40}',path)):
            raise ops.ApplyError(ops.FENCE)
        deadline=self.clock()+remaining
        request=urllib.request.Request(API+path,headers={
            'Authorization':'Bearer '+self.token,'Accept':'application/vnd.github+json',
            'X-GitHub-Api-Version':'2022-11-28','Cache-Control':'no-store',
            'User-Agent':'PLATO-Approved-GPR-Transport/1'})
        try:
            with self.opener.open(request,timeout=min(15,max(0.01,remaining))) as response:
                if response.status!=200 or response.geturl()!=API+path:
                    raise ops.ApplyError(ops.TRANSPORT)
                length=response.headers.get('Content-Length')
                if length is not None and (not length.isdigit() or int(length)>MAX_GITHUB_RESPONSE):
                    raise ops.ApplyError(ops.RESPONSE)
                chunks=[]
                size=0
                read=getattr(response,'read1',response.read)
                while True:
                    if self.clock()>=deadline:
                        raise ops.ApplyError(ops.DEADLINE)
                    chunk=read(min(16384,MAX_GITHUB_RESPONSE+1-size))
                    if not chunk:
                        break
                    chunks.append(chunk);size+=len(chunk)
                    if size>MAX_GITHUB_RESPONSE:
                        raise ops.ApplyError(ops.RESPONSE)
                raw=b''.join(chunks)
                if self.clock()>=deadline:
                    raise ops.ApplyError(ops.DEADLINE)
        except ops.ApplyError:
            raise
        except (OSError,ValueError,urllib.error.URLError):
            raise ops.ApplyError(ops.TRANSPORT) from None
        if len(raw)>MAX_GITHUB_RESPONSE:
            raise ops.ApplyError(ops.RESPONSE)
        return ops.strict_json(raw)

    def receive(self,temporary):
        paths,remaining=session(self.environment)
        deadline=self.clock()+remaining
        initial=self.environment['GITHUB_SHA']
        def expired(signum,frame):
            raise ops.ApplyError(ops.DEADLINE)
        previous=signal.signal(signal.SIGALRM,expired)
        signal.setitimer(signal.ITIMER_REAL,remaining)
        try:
            while True:
                left=deadline-self.clock()
                if left<=0:
                    raise ops.ApplyError(ops.DEADLINE)
                ref=self.get(REF_PATH,left)
                candidate=ref.get('object',{}).get('sha') if isinstance(ref.get('object'),dict) else None
                if not ops.digest(candidate,40) or ref.get('ref')!=ops.BRANCH or ref['object'].get('type')!='commit':
                    raise ops.ApplyError(ops.FENCE)
                if candidate==initial:
                    self.sleep(min(POLL_SECONDS,max(0,deadline-self.clock())))
                    continue
                commit=self.get(PREFIX+'/commits/'+candidate,deadline-self.clock())
                parents,files=commit.get('parents'),commit.get('files')
                if (commit.get('sha')!=candidate or not isinstance(parents,list) or len(parents)!=1
                        or not isinstance(parents[0],dict) or parents[0].get('sha')!=initial
                        or not isinstance(files,list) or len(files)!=1 or not isinstance(files[0],dict)
                        or files[0].get('filename')!=DELIVERY_FILE or files[0].get('status')!='modified'
                        or 'previous_filename' in files[0]):
                    raise ops.ApplyError(ops.FENCE)
                payload=self.get(PREFIX+'/contents/'+DELIVERY_FILE+'?ref='+candidate,deadline-self.clock())
                if (payload.get('type')!='file' or payload.get('path')!=DELIVERY_FILE
                        or payload.get('encoding')!='base64' or type(payload.get('size')) is not int
                        or not 0<payload['size']<=ops.MAX_INPUT
                        or not ops.digest(payload.get('sha'),40)
                        or payload['sha']!=files[0].get('sha') or not isinstance(payload.get('content'),str)):
                    raise ops.ApplyError(ops.FENCE)
                try:
                    envelope=base64.b64decode(''.join(payload['content'].splitlines()),validate=True)
                except (ValueError,TypeError):
                    raise ops.ApplyError(ops.INPUT) from None
                blob=hashlib.sha1(b'blob '+str(len(envelope)).encode()+b'\0'+envelope).hexdigest()
                if (len(envelope)!=payload['size'] or blob!=payload['sha']
                        or ops.sha(envelope)==ops.INPUT_SHA256):
                    raise ops.ApplyError(ops.INPUT)
                if self.clock()>=deadline:
                    raise ops.ApplyError(ops.DEADLINE)
                private=ops.bounded_file(paths['private.pem'],8192).decode('ascii')
                return envelope,private
        finally:
            signal.setitimer(signal.ITIMER_REAL,0)
            signal.signal(signal.SIGALRM,previous)
            self.token=''


def main():
    try:
        os.umask(0o077)
        if sys.argv[1:]==['prepare']:
            prepare(os.environ)
            print('{"transport_prepared":true}')
            return 0
        if sys.argv[1:]==['apply']:
            # Existing main performs trusted checkout again; only this provider may wait.
            return ops.main(Delivery(os.environ).receive)
        raise ops.ApplyError(ops.SETUP)
    except ops.ApplyError as exc:
        print(json.dumps({'transport_prepared':False,'error_code':exc.code},sort_keys=True))
        return 1
    except Exception:
        print('{"transport_prepared":false,"error_code":1}')
        return 1


if __name__=='__main__':
    sys.exit(main())
