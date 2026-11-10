"""Capture only fixed read-only GPR surfaces and real server PDFs as encrypted proof."""
from __future__ import annotations

import base64
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
spec=importlib.util.spec_from_file_location('gpr_verify_transport',SCRIPT)
transport=importlib.util.module_from_spec(spec);spec.loader.exec_module(transport)
ops=transport.ops
HTTP_SECONDS=120
TOTAL_SECONDS=900
MAX_CAPTURE=24*1024*1024
ROUTES={'monitor':'/monitor/view','report':'/monitor/report','pdf':'/monitor/report.pdf'}
SCHEDULE_KEYS=frozenset({'approved_plan','owner_rnv','baseline_scope','rows','management','corpus_gpr',
    'dependency_timeline','completed_facts','work_fact','fact_source','forecast_method','basis',
    'approved_start','approved_end','forecast_end','baseline_end','reason','reasons','risks','cut'})


def owner_matches(value,bundle):
    if not isinstance(value,dict):return False
    try:
        effective=ops.day(value.get('effective_from'))
        recorded=dt.datetime.fromisoformat(value.get('recorded_at'))
    except (ops.ApplyError,TypeError,ValueError):return False
    return (type(value.get('revision')) is int and value['revision']==1
        and value.get('source')=='owner_decision' and value.get('date')==ops.OWNER_RNV_DATE
        and value.get('note')==bundle['owner_rnv_note']
        and ops.day(bundle['old_cut'])<effective<=dt.datetime.now(dt.timezone.utc).date()
        and recorded.utcoffset()==dt.timedelta(0) and recorded.date()==effective)


def without_raw_ks_positions(value):
    # The qualified completed-work facts and counts stay; raw ledger leaves do not.
    if isinstance(value,dict):
        return {key:without_raw_ks_positions(item) for key,item in value.items()
                if key!='completed_ks_positions'}
    if isinstance(value,list):return [without_raw_ks_positions(item) for item in value]
    return value


def schedule_projection(value):
    if not isinstance(value,dict):raise ops.ApplyError(ops.RESPONSE)
    return without_raw_ks_positions({key:value[key] for key in SCHEDULE_KEYS if key in value})


def schedule_matches(value,bundle):
    plan=value.get('approved_plan') if isinstance(value,dict) else None
    corpus=value.get('corpus_gpr') if isinstance(value,dict) else None
    rows=value.get('rows') if isinstance(value,dict) else None
    return (isinstance(plan,dict) and plan.get('source_sha256')==ops.SOURCE_SHA256
        and type(plan.get('revision')) is int and plan['revision']==1
        and plan.get('baseline_scope')==ops.BASELINE_SCOPE
        and owner_matches(plan.get('owner_rnv'),bundle)
        and (value.get('owner_rnv') is None or owner_matches(value['owner_rnv'],bundle))
        and isinstance(corpus,dict) and corpus.get('sha256')==ops.SOURCE_SHA256
        and isinstance(rows,list) and len(rows)>0 and all(isinstance(row,dict) for row in rows))


def report_projection(value,html):
    if not isinstance(value,dict) or not isinstance(value.get('gantt'),dict):
        raise ops.ApplyError(ops.RESPONSE)
    if not isinstance(html,str) or html.count('<h3>Сроки работ по корпусам</h3>')!=1:
        raise ops.ApplyError(ops.RESPONSE)
    start=html.index('<h3>Сроки работ по корпусам</h3>')
    tail=html[start:]
    stops=[match.start() for match in re.finditer(r'<h2\b|<h3>Фото со стройки',tail)]
    if not stops:raise ops.ApplyError(ops.RESPONSE)
    fragment=tail[:min(stops)]
    if len(fragment.encode())>8*1024*1024:raise ops.ApplyError(ops.RESPONSE)
    return without_raw_ks_positions({'gantt':value['gantt'],'schedule':value.get('schedule'),
            'kind':value.get('kind'),'end':value.get('end'),'schedule_html':fragment})


def report_matches(value,bundle,cut):
    if not isinstance(value,dict) or value.get('kind')!='week' or value.get('end')!=cut:return False
    gantt=value.get('gantt');timeline=gantt.get('dependency_timeline') if isinstance(gantt,dict) else None
    rnv=timeline.get('rnv') if isinstance(timeline,dict) else None
    corpus=gantt.get('corpus_gpr') if isinstance(gantt,dict) else None
    return (isinstance(rnv,dict) and owner_matches(rnv.get('owner_rnv'),bundle)
        and rnv.get('approved')==ops.OWNER_RNV_DATE and rnv.get('approved_source')=='owner_decision'
        and isinstance(corpus,dict) and corpus.get('sha256')==ops.SOURCE_SHA256
        and '30.09.2027' in value.get('schedule_html',''))


class SurfaceReader:
    def __init__(self,expected, *, opener=None,clock=time.monotonic,today=lambda:dt.datetime.now(dt.timezone.utc).date()):
        if not ops.digest(expected,40):raise ops.ApplyError(ops.SETUP)
        self.expected,self.clock,self.today=expected,clock,today
        self.deadline=clock()+TOTAL_SECONDS
        self.opener=opener or urllib.request.build_opener(ops.NoRedirect())
        self.results=[];self.bundle=None;self.key='';self.effective=None;self.version=None

    def remaining(self):
        left=self.deadline-self.clock()
        if left<=0:raise ops.ApplyError(ops.DEADLINE)
        return left

    def request(self,kind,label='health'):
        # Neither URLs, paths, bodies, projects nor dates come from the caller.
        if not isinstance(kind,str) or not isinstance(label,str):raise ops.ApplyError(ops.FENCE)
        if kind=='health' and label=='health':path='/health';raw=None
        elif kind in ROUTES and label in {'old_cut','current_cut'}:
            if not self.bundle or not self.key or self.effective!=self.today().isoformat():
                raise ops.ApplyError(ops.FENCE)
            cut=self.bundle['old_cut'] if label=='old_cut' else self.effective
            body={'key':self.key,'project':self.bundle['project']}
            if kind=='monitor':body['cut']=cut
            else:body.update(kind='week',end=cut)
            raw=json.dumps(body,ensure_ascii=False,allow_nan=False).encode();path=ROUTES[kind]
        else:raise ops.ApplyError(ops.FENCE)
        self.remaining()
        record={'phase':kind+'_'+label,'http_status':0,'timeout':False,'elapsed_seconds':0,
                'response_known':False,'bytes':0}
        self.results.append(record);started=self.clock()
        headers={'Cache-Control':'no-store','User-Agent':'PLATO-GPR-ReadOnly-Surface-Verify/1'}
        if raw is not None:headers['Content-Type']='application/json'
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
                chunks,size=[],0;read=getattr(response,'read1',response.read)
                while True:
                    self.remaining();chunk=read(min(65536,ops.MAX_RESPONSE+1-size));self.remaining()
                    if not chunk:break
                    chunks.append(chunk);size+=len(chunk)
                    if size>ops.MAX_RESPONSE:raise ops.ApplyError(ops.RESPONSE)
                payload=b''.join(chunks);record['bytes']=len(payload)
                if b'-----BEGIN PRIVATE KEY-----' in payload or (self.key and self.key.encode() in payload):
                    raise ops.ApplyError(ops.PROOF)
                if kind=='pdf':
                    content_type=response.headers.get('Content-Type','').split(';')[0].strip().lower()
                    if content_type!='application/pdf' or not payload.startswith(b'%PDF-') or not payload.rstrip().endswith(b'%%EOF'):
                        raise ops.ApplyError(ops.RESPONSE)
                    result=payload
                else:result=ops.strict_json(payload)
                record['response_known']=True
                return result
        except urllib.error.HTTPError as exc:
            record['http_status']=exc.code if type(exc.code) is int and 100<=exc.code<=599 else 0
            exc.close()
        except (TimeoutError,socket.timeout):record['timeout']=True
        except urllib.error.URLError as exc:record['timeout']=isinstance(exc.reason,(TimeoutError,socket.timeout))
        except OSError:pass
        finally:record['elapsed_seconds']=max(0,round(self.clock()-started,3))
        return None

    def health(self):
        value=self.request('health')
        if (not isinstance(value,dict) or value.get('status')!='ok' or value.get('commit')!=self.expected
                or value.get('data_writable') is not True or not isinstance(value.get('version'),str)
                or not re.fullmatch(r'\d{1,6}\.\d{1,6}\.\d{1,6}',value['version'])
                or (self.version is not None and self.version!=value['version'])):
            raise ops.ApplyError(ops.RUNTIME)
        self.version=value['version']


def verify(environment, *, input_provider=None,opener=None,clock=time.monotonic,today=lambda:dt.datetime.now(dt.timezone.utc).date()):
    summary={'ok':False,'probe_only':True,'write_attempted':False,'outcome_unknown':False,
        'input_verified':False,'runtime_verified':False,'encrypted_proof_created':False,
        'monitor_verified':False,'report_verified':False,'server_pdfs_received':0,'error_code':ops.SETUP,'results':[]}
    proof={'schema':1,'purpose':'readonly_gpr_surface_verification','cuts':{}}
    reader=None;previous=None;target=None;key='';token='';temporary=None
    try:
        os.umask(0o077);ops.trusted_checkout(environment);ops.input_ready()
        temporary=Path(environment.get('RUNNER_TEMP',''))
        if not temporary.is_absolute() or not temporary.is_dir() or temporary.is_symlink():raise ops.ApplyError(ops.SETUP)
        target=temporary/'approved-gpr-apply-proof.cms'
        if target.exists():raise ops.ApplyError(ops.SETUP)
        recipient=ops.bounded_file(ops.PUBLIC_RECIPIENT,16384)
        if ops.sha(recipient)!=ops.RECIPIENT_SHA256:raise ops.ApplyError(ops.INPUT)
        provider=input_provider or transport.Delivery(environment).receive
        envelope,transport_key=provider(temporary)
        reader=SurfaceReader(environment.get('EXPECTED_RUNTIME_COMMIT',''),opener=opener,clock=clock,today=today)
        summary['results']=reader.results
        def expired(signum,frame):raise ops.ApplyError(ops.DEADLINE)
        previous=signal.signal(signal.SIGALRM,expired);signal.setitimer(signal.ITIMER_REAL,TOTAL_SECONDS)
        reader.health()
        bundle=ops.decrypt_bundle(envelope,transport_key,temporary,envelope_sha256=ops.sha(envelope))
        transport_key='';summary['input_verified']=True
        key=environment.pop('APPLY_ADMIN_KEY','');token=environment.get('GITHUB_TOKEN','')
        if not isinstance(key,str) or not key.strip() or len(key)>4096:raise ops.ApplyError(ops.SETUP)
        key=key.strip();reader.bundle,reader.key,reader.effective=bundle,key,reader.today().isoformat()
        if not ops.day(bundle['old_cut'])<ops.day(reader.effective) or ops.day(bundle['source_as_of'])>ops.day(reader.effective):
            raise ops.ApplyError(ops.FENCE)
        reader.health();monitor_ok=[];report_ok=[]
        for label,cut in [('old_cut',bundle['old_cut']),('current_cut',reader.effective)]:
            record={'cut':cut};proof['cuts'][label]=record
            monitor=reader.request('monitor',label)
            if not isinstance(monitor,dict) or not isinstance(monitor.get('snapshot'),dict):raise ops.ApplyError(ops.RESPONSE)
            record['monitor_schedule']=schedule_projection(monitor['snapshot'].get('schedule'))
            monitor_ok.append(schedule_matches(record['monitor_schedule'],bundle))
            report=reader.request('report',label)
            if not isinstance(report,dict):raise ops.ApplyError(ops.RESPONSE)
            record['report_schedule']=report_projection(report.get('report'),report.get('html'))
            report_ok.append(report_matches(record['report_schedule'],bundle,cut))
            pdf=reader.request('pdf',label)
            if not isinstance(pdf,bytes):raise ops.ApplyError(ops.RESPONSE)
            record['server_pdf_base64']=base64.b64encode(pdf).decode('ascii')
            summary['server_pdfs_received']+=1
            if len(json.dumps(proof,ensure_ascii=False,allow_nan=False).encode())>min(MAX_CAPTURE,ops.MAX_PROOF):
                raise ops.ApplyError(ops.PROOF)
        reader.health();summary['runtime_verified']=True
        summary['monitor_verified']=len(monitor_ok)==2 and all(monitor_ok)
        summary['report_verified']=len(report_ok)==2 and all(report_ok)
        summary['ok']=summary['monitor_verified'] and summary['report_verified'] and summary['server_pdfs_received']==2
        summary['error_code']=0 if summary['ok'] else ops.FENCE
    except ops.ApplyError as exc:summary['error_code']=exc.code
    except Exception:summary['error_code']=ops.SETUP
    finally:
        if previous is not None:
            signal.setitimer(signal.ITIMER_REAL,0);signal.signal(signal.SIGALRM,previous)
        proof['result']={name:value for name,value in summary.items() if name!='encrypted_proof_created'}
        if summary['input_verified'] and proof['cuts'] and temporary is not None and target is not None:
            try:
                if len(json.dumps(proof,ensure_ascii=False,allow_nan=False).encode())>min(MAX_CAPTURE,ops.MAX_PROOF):
                    raise ops.ApplyError(ops.PROOF)
                ops.encrypt_proof(proof,recipient,target,temporary,secrets=(key,token))
                summary['encrypted_proof_created']=True
            except Exception:summary.update(ok=False,error_code=ops.PROOF)
        if reader is not None:reader.key='';reader.bundle=None
        key='';token=''
    return summary


def main():
    result=verify(os.environ)
    output=os.environ.get('GITHUB_OUTPUT')
    if output:
        with open(output,'a',encoding='utf-8') as stream:
            stream.write('proof_created='+str(result['encrypted_proof_created']).lower()+'\n')
    print(json.dumps(result,sort_keys=True,allow_nan=False))
    return 0 if result['ok'] else 1


if __name__=='__main__':raise SystemExit(main())
