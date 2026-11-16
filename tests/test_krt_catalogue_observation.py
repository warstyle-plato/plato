"""Passive observations never replace the actual collector or its transport."""
from __future__ import annotations
import ast
from contextlib import nullcontext
import copy
import errno
import hashlib
import http.client as http_client
import importlib.util
import io
import json
from pathlib import Path
import socket
import ssl
from types import SimpleNamespace
from urllib.error import HTTPError, URLError
from urllib.response import addinfourl

import pytest

from krt_baseline_sources import source_bytes

from market_search import http
from market_search import krt_registry as registry
from market_search import krt_catalogue_observation as obs

BASE = 'e31324f813335157efa97e1e162b7f0c8eecb53d'
ROOT = Path(__file__).resolve().parents[1]
SECRET = 'SOURCE-URL-ERROR-BODY-MUST-NOT-LEAVE'
CARD = ('<a href="/projects/{slug}/">'+SECRET+' Подробнее</a>'
    '<div>Округ: САО</div><div>Район: Тест</div>'
    '<div>Статус: Планируемая</div><div>Площадь: 1,0</div>')


def html(slug='one', next_url=None):
    text = CARD.format(slug=slug)
    if next_url:
        text += '<div class="show_more" data-url="'+next_url+'"></div>'
    return text.encode()


def markdown(slug='one'):
    return ('['+SECRET+' Подробнее](https://api.krt.mos.ru/projects/'+slug+')\n'
        'Округ: САО\n\nРайон: Тест\n\nСтатус: Планируемая\n\nПлощадь: 1,0\n\n').encode()


def baseline(name):
    source = source_bytes(BASE, name)
    module_name = 'market_search._observation_baseline_'+name
    spec = importlib.util.spec_from_loader(module_name, loader=None)
    module = importlib.util.module_from_spec(spec)
    # Dataclass needs the genuine module namespace while loading baseline.
    import sys
    sys.modules[module_name] = module
    exec(compile(source, 'git:'+BASE+':'+name, 'exec'), module.__dict__)
    return module, source.decode()


def read_receipt(store):
    view = obs.read_view(store.path.parent)
    assert view['state'] == 'present', view
    assert obs.validate(view['diagnostic'])
    assert len(obs.canonical(view)) <= obs.VIEW_LIMIT
    assert SECRET not in json.dumps(view, ensure_ascii=False)
    return view, view['diagnostic']['latest_attempt']


def test_real_default_request_and_save_bodies_are_literal_base_inverse():
    _, old = baseline('http')
    before = {node.name:node for node in ast.parse(old).body if isinstance(node, ast.FunctionDef)}
    after = {node.name:node for node in ast.parse((ROOT/'market_search/http.py').read_text()).body if isinstance(node, ast.FunctionDef)}
    assert ast.dump(ast.Module(body=after['request_bytes'].body[2:], type_ignores=[]), include_attributes=False) == ast.dump(ast.Module(body=before['request_bytes'].body, type_ignores=[]), include_attributes=False)
    assert ast.dump(ast.Module(body=after['save_json'].body[1:], type_ignores=[]), include_attributes=False) == ast.dump(ast.Module(body=before['save_json'].body, type_ignores=[]), include_attributes=False)
    for name in ('_ascii_url', 'get_json', 'load_json', 'fresh', 'public_url_problem'):
        assert ast.dump(after[name], include_attributes=False) == ast.dump(before[name], include_attributes=False)


@pytest.mark.parametrize('mode', ['success', 'HTTP_then_success', 'body_then_success', 'fail', 'trust_fail'])
@pytest.mark.parametrize('observing', [False, True, 'broken'])
def test_actual_urllib_call_order_arguments_retries_context_and_outcome_equal_base(monkeypatch,tmp_path,mode,observing):
    old, _ = baseline('http')
    def run(module, active):
        calls=[];context=object();attempts=0
        def trust():
            calls.append(('trust',))
            if mode=='trust_fail':raise ssl.SSLError(SECRET)
            return context
        class Body(io.BytesIO):
            def read(self,*a,**k):
                calls.append(('read',))
                if mode=='body_then_success' and attempts==1:raise TimeoutError(SECRET)
                return super().read(*a,**k)
        def open_response(req,**kw):
            nonlocal attempts
            attempts+=1
            calls.append(('open',req.full_url,req.data,req.get_method(),sorted(req.header_items()),kw['timeout'],kw['context'] is context))
            if mode=='fail' or mode=='HTTP_then_success' and attempts==1:
                raise HTTPError(req.full_url,503,SECRET,{},io.BytesIO(SECRET.encode()))
            return addinfourl(Body(b'known-body'),{},req.full_url,200)
        with monkeypatch.context() as patch:
            patch.setattr(module,'_trust_context',trust)
            patch.setattr(module,'urlopen',open_response)
            patch.setattr(module.time,'sleep',lambda delay:calls.append(('sleep',delay)))
            walk=obs.Walk(tmp_path/'unused/catalogue.json',False) if active else None
            scope=obs.fetch_scope(walk,'official',1) if active else nullcontext()
            if active=='broken':patch.setattr(obs.Fetch,'response',lambda *a:(_ for _ in ()).throw(OSError(SECRET)))
            with scope:
                try:
                    result=module.request_bytes('https://api.krt.mos.ru/путь',params={'x':'two words','skip':None},
                        data=b'data',method='POST',timeout=15,retries=1,headers={'X-Test':'unchanged'})
                    outcome=('returned',result)
                except Exception as exc:
                    outcome=(type(exc).__name__,str(exc),type(exc.__cause__).__name__ if exc.__cause__ else None)
            return calls,outcome
    expected=run(old,False)
    actual=run(http,observing)
    assert actual==expected


@pytest.mark.parametrize('mode',['direct','mixed','renderer','zero','fail','partial'])
@pytest.mark.parametrize('diagnostic',['active','off','write_failure','start_failure'])
def test_actual_base_collector_calls_and_every_saved_catalogue_byte_are_identical(monkeypatch,tmp_path,mode,diagnostic):
    old,_=baseline('krt_registry')
    def run(module,directory,enabled):
        calls=[];writes=[]
        def fetch(url):
            calls.append(url)
            renderer=url.startswith(registry.JINA_PREFIX)
            second='PAGEN_1=2' in url
            if mode=='zero':return b''
            if mode=='fail' or mode=='partial' and (renderer or second):raise OSError(SECRET)
            if mode=='renderer' and not renderer:raise OSError(SECRET)
            if mode=='mixed' and not renderer and second:raise OSError(SECRET)
            if renderer:return markdown('two') if second else markdown('one')
            return html('one', '/projects/?PAGEN_1=2') if not second else html('two')
        native_save=module.save_json
        def save(path,payload,**kwargs):
            result=native_save(path,payload,**kwargs)
            writes.append(Path(path).read_bytes())
            return result
        with monkeypatch.context() as patch:
            patch.setattr(module,'save_json',save)
            patch.setattr(module.time,'time',lambda:1234567890)
            if enabled=='off':patch.setattr(obs,'start',lambda *a:None)
            if enabled=='write_failure':patch.setattr(obs,'write_envelope',lambda *a:(_ for _ in ()).throw(OSError(SECRET)))
            if enabled=='start_failure':patch.setattr(obs,'read_view',lambda *a:(_ for _ in ()).throw(OSError(SECRET)))
            store=module.KrtRegistry(directory,fetch=fetch)
            rows=store.projects(refresh=True,max_pages=3)
        return calls,writes,[row.to_dict() for row in rows]
    assert run(registry,tmp_path/'new',diagnostic)==run(old,tmp_path/'old','off')


def test_observed_native_request_records_status_body_and_parse_without_lower_success_claims(monkeypatch,tmp_path):
    calls=[];body=html()
    def opener(req,**kwargs):
        calls.append((req.full_url,kwargs['timeout']))
        return addinfourl(io.BytesIO(body),{},'https://api.krt.mos.ru/projects/?secret='+SECRET,200)
    monkeypatch.setattr(http,'urlopen',opener);monkeypatch.setattr(http,'_trust_context',lambda:None)
    store=registry.KrtRegistry(tmp_path)
    rows=store.projects(refresh=True)
    view,receipt=read_receipt(store)
    assert len(rows)==1 and calls==[(registry.CATALOGUE_URL,15)]
    page=receipt['page_receipts'][0]
    assert page==['official',1,1,200,'official_https',len(body),hashlib.sha256(body).hexdigest(),True,'complete','complete',1,1]
    assert receipt['HTTP_attempts_seen']==1 and receipt['fetches_seen']==1
    assert all(receipt['last_failure_phases']['phases'][key]=='not_observed' for key in ('dns','tcp','tls'))
    assert receipt['walk_result']['completion_basis']=='existing_direct_termination'
    assert view['current_catalogue_binding_check']=='stat_identity_matches'
    binding=view['diagnostic']['current_catalogue_binding'];raw=store.path.read_bytes()
    assert binding['written_payload_sha256']==hashlib.sha256(raw).hexdigest() and binding['written_bytes']==len(raw)
    current=view['diagnostic']['current_catalogue_acquisition']
    assert binding['acquisition_receipt_sha256']==hashlib.sha256(obs.canonical(current)).hexdigest()


@pytest.mark.parametrize('error,kind,phase',[(socket.gaierror(1,SECRET),'dns_resolution','dns'),
    (ConnectionRefusedError(errno.ECONNREFUSED,SECRET),'tcp_refused','tcp'),
    (OSError(errno.EHOSTUNREACH,SECRET),'tcp_unreachable','tcp'),
    (ssl.SSLCertVerificationError(1,SECRET),'tls_verification','tls'),
    (ssl.SSLError(1,SECRET),'tls_error','tls'),(TimeoutError(SECRET),'timeout',None),
    (OSError(errno.EIO,SECRET),'unknown',None)])
def test_typed_open_failures_do_not_invent_endpoint_or_handshake_timings(monkeypatch,tmp_path,error,kind,phase):
    monkeypatch.setattr(http,'_trust_context',lambda:None)
    monkeypatch.setattr(http,'urlopen',lambda *a,**k:(_ for _ in ()).throw(URLError(error)))
    monkeypatch.setattr(http.time,'sleep',lambda *a:None)
    store=registry.KrtRegistry(tmp_path);assert store.projects(refresh=True,max_pages=1)==[]
    _,receipt=read_receipt(store)
    assert receipt['HTTP_attempts_seen']==4
    sample=receipt['failure_samples'][-1]
    assert sample['boundary']=='open_response' and sample['kind']==kind
    assert sample['endpoint_attribution']=='origin_or_proxy_unknown'
    phases=receipt['last_failure_phases']['phases']
    assert phases['HTTP']=='not_observed' and phases['body']=='not_observed'
    for key in ('dns','tcp','tls'):assert phases[key]==('failed' if key==phase else 'not_observed')
    for page in receipt['page_receipts']:
        assert page[3] is None and page[5:9]==[None,None,False,'not_observed']


def test_HTTPError_is_observed_response_and_its_error_body_is_never_read(monkeypatch,tmp_path):
    class NotRead(io.BytesIO):
        def read(self,*a):pytest.fail('diagnostics read HTTPError body')
    monkeypatch.setattr(http,'_trust_context',lambda:None)
    monkeypatch.setattr(http,'urlopen',lambda req,**k:(_ for _ in ()).throw(HTTPError(req.full_url,503,SECRET,{},NotRead(b'private'))))
    monkeypatch.setattr(http.time,'sleep',lambda *a:None)
    store=registry.KrtRegistry(tmp_path);store.projects(refresh=True,max_pages=1)
    _,receipt=read_receipt(store)
    assert receipt['last_failure_phases']['phases']['HTTP']=='response_observed'
    assert receipt['failure_samples'][-1]['kind']=='HTTP_status'
    assert all(page[3]==503 and page[5:8]==[None,None,False] for page in receipt['page_receipts'])


@pytest.mark.parametrize('error',[http_client.IncompleteRead(b'PRIVATE',10),ssl.SSLError(1,SECRET),TimeoutError(SECRET)])
def test_body_read_failure_keeps_returned_status_but_never_hashes_partial_body(monkeypatch,tmp_path,error):
    class Broken(io.BytesIO):
        def read(self,*a):raise error
    monkeypatch.setattr(http,'_trust_context',lambda:None)
    monkeypatch.setattr(http,'urlopen',lambda req,**k:addinfourl(Broken(),{},req.full_url,200))
    monkeypatch.setattr(http.time,'sleep',lambda *a:None)
    store=registry.KrtRegistry(tmp_path)
    if isinstance(error,http_client.IncompleteRead):
        with pytest.raises(http_client.IncompleteRead):store.projects(refresh=True,max_pages=1)
    else:
        store.projects(refresh=True,max_pages=1)
    _,receipt=read_receipt(store)
    assert receipt['last_failure_phases']['phases']['body']=='failed'
    assert receipt['failure_samples'][-1]['boundary']=='body'
    assert all(page[3]==200 and page[5:8]==[None,None,False] for page in receipt['page_receipts'])


def test_custom_fetch_parse_zero_and_decode_failure_are_not_fresh_empty_source_claims(tmp_path,monkeypatch):
    store=registry.KrtRegistry(tmp_path/'zero',fetch=lambda url:b'not a catalogue')
    assert store.projects(refresh=True,max_pages=1)==[]
    _,receipt=read_receipt(store)
    assert receipt['HTTP_attempts_seen'] is None
    assert all(page[2:8]==[None,None,'unknown',None,None,False] and page[8:]==['complete','zero_rows',0,0] for page in receipt['page_receipts'])
    assert receipt['walk_result']['acquisition']=='none' and receipt['walk_result']['source_updated_at'] is None
    class BadBytes:
        def decode(self,*a,**k):raise UnicodeError(SECRET)
    broken=registry.KrtRegistry(tmp_path/'broken',fetch=lambda url:BadBytes())
    assert broken.projects(refresh=True,max_pages=1)==[]
    _,receipt=read_receipt(broken)
    assert all(page[8:]==['failed','not_observed',None,None] for page in receipt['page_receipts'])
    assert receipt['failure_samples'][-1]['boundary']=='decode'


def test_previous_known_generation_survives_later_failed_and_zero_walks_and_cache_hits(tmp_path,monkeypatch):
    store=registry.KrtRegistry(tmp_path,fetch=lambda url:html())
    store.projects(refresh=True)
    before=store.path.read_bytes();oldview,oldreceipt=read_receipt(store)
    sidecar=store.path.parent/obs.NAME;first=sidecar.read_bytes()
    assert store.projects() and sidecar.read_bytes()==first
    for fetch in (lambda url:(_ for _ in ()).throw(OSError(SECRET)),lambda url:b''):
        store.fetch=fetch
        assert store.projects(refresh=True,max_pages=1)
        view,receipt=read_receipt(store)
        assert store.path.read_bytes()==before
        assert view['current_catalogue_binding_check']=='stat_identity_matches'
        assert view['diagnostic']['current_catalogue_acquisition']==oldview['diagnostic']['current_catalogue_acquisition']
        assert view['diagnostic']['current_catalogue_binding']['state']=='retained_prior_known'
        assert receipt['walk_result']['prior_catalogue_retained'] and not receipt['walk_result']['catalogue_written']


def test_old_catalogue_without_metadata_never_gets_invented_provenance(tmp_path,monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(obs,'start',lambda *a:None)
        store=registry.KrtRegistry(tmp_path,fetch=lambda url:html());store.projects(refresh=True)
    store.fetch=lambda url:b'';store.projects(refresh=True,max_pages=1)
    view,receipt=read_receipt(store)
    assert view['diagnostic']['current_catalogue_acquisition'] is None
    assert view['diagnostic']['current_catalogue_binding']['state']=='prior_unknown'
    assert view['current_catalogue_binding_check']=='unknown'
