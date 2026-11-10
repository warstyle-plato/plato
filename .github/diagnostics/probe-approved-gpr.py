"""Read-only diagnosis of the fixed schedule endpoint; never approves anything."""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import socket
import time
import urllib.error
import urllib.request

SCRIPT=Path(__file__).with_name('ephemeral-gpr-transport.py')
spec=importlib.util.spec_from_file_location('gpr_probe_transport',SCRIPT)
transport=importlib.util.module_from_spec(spec)
spec.loader.exec_module(transport)
ops=transport.ops
HTTP_SECONDS=60
TOTAL_SECONDS=180
HEALTH_PHASES=frozenset({'health_before_decrypt','health_before_reads','health_after_reads'})
PHYSICAL_PHASES=frozenset({'old_cut','current_cut'})


class ReadOnlyProbe:
    def __init__(self,expected, *, opener=None,clock=time.monotonic,today=lambda:dt.datetime.now(dt.timezone.utc).date()):
        if not ops.digest(expected,40):raise ops.ApplyError(ops.SETUP)
        self.expected,self.clock,self.today=expected,clock,today
        self.deadline=clock()+TOTAL_SECONDS
        self.opener=opener or urllib.request.build_opener(ops.NoRedirect())
        self.results=[]
        self.bundle,self.key,self.effective,self.version=None,'',None,None

    def remaining(self):
        remaining=self.deadline-self.clock()
        if remaining<=0:raise ops.ApplyError(ops.DEADLINE)
        return remaining

    def request(self,phase):
        # Callers provide a fixed phase, never a URL/path or arbitrary request body.
        if not isinstance(phase,str) or phase not in HEALTH_PHASES|PHYSICAL_PHASES:
            raise ops.ApplyError(ops.FENCE)
        path='/health' if phase in HEALTH_PHASES else ops.PHYSICAL
        headers={'Cache-Control':'no-store','User-Agent':'PLATO-Approved-GPR-ReadOnly-Probe/1'}
        raw=None
        if phase in PHYSICAL_PHASES:
            if not self.bundle or not self.key or self.effective!=self.today().isoformat():
                raise ops.ApplyError(ops.FENCE)
            cut=self.bundle['old_cut'] if phase=='old_cut' else self.effective
            raw=json.dumps({'key':self.key,'project':self.bundle['project'],'cut':cut,'offset':0},
                           ensure_ascii=False,allow_nan=False).encode()
            if len(raw)>ops.MAX_INPUT:raise ops.ApplyError(ops.FENCE)
            headers['Content-Type']='application/json'
        self.remaining()
        record={'phase':phase,'http_status':0,'timeout':False,'elapsed_seconds':0,
                'json_known':False,'source_matches_old':False,'source_matches_new':False,
                'snapshot_matches':False,'physical_revision_matches':False,'tasks_known':False}
        self.results.append(record)
        started=self.clock()
        request=urllib.request.Request(ops.BASE+path,data=raw,headers=headers,
                                       method='GET' if raw is None else 'POST')
        try:
            with self.opener.open(request,timeout=min(HTTP_SECONDS,self.remaining())) as response:
                status=response.status
                record['http_status']=status if type(status) is int and 100<=status<=599 else 0
                if response.geturl()!=ops.BASE+path:raise ops.ApplyError(ops.TRANSPORT)
                if record['http_status']!=200:return None
                declared=response.headers.get('Content-Length')
                if declared is not None and (not str(declared).isdigit() or int(declared)>ops.MAX_RESPONSE):
                    raise ops.ApplyError(ops.RESPONSE)
                chunks,size=[],0
                read=getattr(response,'read1',response.read)
                while True:
                    self.remaining()
                    chunk=read(min(65536,ops.MAX_RESPONSE+1-size))
                    self.remaining()
                    if not chunk:break
                    size+=len(chunk)
                    if size>ops.MAX_RESPONSE:raise ops.ApplyError(ops.RESPONSE)
                    chunks.append(chunk)
                result=ops.strict_json(b''.join(chunks))
                if self.key and self.key in json.dumps(result,ensure_ascii=False,allow_nan=False):
                    raise ops.ApplyError(ops.PROOF)
                record['json_known']=True
                if phase in PHYSICAL_PHASES:
                    record.update(source_matches_old=result.get('source_sha256')==ops.OLD_SOURCE_SHA256,
                        source_matches_new=result.get('source_sha256')==ops.SOURCE_SHA256,
                        snapshot_matches=result.get('snapshot_id')==self.bundle['snapshot_id'],
                        physical_revision_matches=(type(result.get('revision')) is int and
                            result['revision']==self.bundle['expected_physical_revision']),
                        tasks_known=isinstance(result.get('tasks'),list))
                return result
        except urllib.error.HTTPError as exc:
            record['http_status']=exc.code if type(exc.code) is int and 100<=exc.code<=599 else 0
            exc.close()
        except (TimeoutError,socket.timeout):record['timeout']=True
        except urllib.error.URLError as exc:
            record['timeout']=isinstance(exc.reason,(TimeoutError,socket.timeout))
        except OSError:pass
        finally:
            record['elapsed_seconds']=max(0,round(self.clock()-started,3))
        return None

    def health(self,phase):
        result=self.request(phase)
        if (not isinstance(result,dict) or result.get('status')!='ok'
                or result.get('commit')!=self.expected or result.get('data_writable') is not True
                or not isinstance(result.get('version'),str)
                or not re.fullmatch(r'\d{1,6}\.\d{1,6}\.\d{1,6}',result['version'])
                or (self.version is not None and result['version']!=self.version)):
            raise ops.ApplyError(ops.RUNTIME)
        self.version=result['version']


def probe(environment, *, input_provider=None,opener=None,clock=time.monotonic,today=lambda:dt.datetime.now(dt.timezone.utc).date()):
    summary={'ok':False,'probe_only':True,'write_attempted':False,'outcome_unknown':False,
             'input_verified':False,'runtime_verified':False,'error_code':ops.SETUP,'results':[]}
    instance=None
    previous=None
    try:
        os.umask(0o077)
        ops.trusted_checkout(environment)
        ops.input_ready()
        temporary=Path(environment.get('RUNNER_TEMP',''))
        if not temporary.is_absolute() or not temporary.is_dir() or temporary.is_symlink():
            raise ops.ApplyError(ops.SETUP)
        provider=input_provider or transport.Delivery(environment).receive
        envelope,transport_key=provider(temporary)
        instance=ReadOnlyProbe(environment.get('EXPECTED_RUNTIME_COMMIT',''),opener=opener,clock=clock,today=today)
        summary['results']=instance.results
        def expired(signum,frame):raise ops.ApplyError(ops.DEADLINE)
        previous=signal.signal(signal.SIGALRM,expired)
        signal.setitimer(signal.ITIMER_REAL,TOTAL_SECONDS)
        instance.health('health_before_decrypt')
        bundle=ops.decrypt_bundle(envelope,transport_key,temporary,envelope_sha256=ops.sha(envelope))
        transport_key=''
        summary['input_verified']=True
        key=environment.pop('APPLY_ADMIN_KEY','')
        if not isinstance(key,str) or not key.strip() or len(key)>4096:raise ops.ApplyError(ops.SETUP)
        instance.bundle,instance.key,instance.effective=bundle,key.strip(),instance.today().isoformat()
        key=''
        if not ops.day(bundle['old_cut'])<ops.day(instance.effective) or ops.day(bundle['source_as_of'])>ops.day(instance.effective):
            raise ops.ApplyError(ops.FENCE)
        instance.health('health_before_reads')
        old=instance.request('old_cut')
        current=instance.request('current_cut')
        instance.health('health_after_reads')
        summary['runtime_verified']=True
        summary['ok']=isinstance(old,dict) and isinstance(current,dict)
        summary['error_code']=0 if summary['ok'] else ops.HTTP
    except ops.ApplyError as exc:summary['error_code']=exc.code
    except Exception:summary['error_code']=ops.SETUP
    finally:
        if previous is not None:
            signal.setitimer(signal.ITIMER_REAL,0)
            signal.signal(signal.SIGALRM,previous)
        if instance is not None:instance.key='';instance.bundle=None
    return summary


def main():
    result=probe(os.environ)
    print(json.dumps(result,sort_keys=True,allow_nan=False))
    return 0 if result['ok'] else 1


if __name__=='__main__':raise SystemExit(main())
