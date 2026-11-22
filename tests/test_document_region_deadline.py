"""Real loopback HTTP at the file entrypoint; no Telegram/provider requests."""
from __future__ import annotations

import io
import hashlib
import json
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

import document_intake
import document_processing as processing
import main

core = main.core
CHAT = 900000003
NUMBER = '50:12:0030405:678'


@pytest.fixture
def territory_http(monkeypatch):
    import document_source
    resolver=ThreadPoolExecutor(max_workers=2,thread_name_prefix='test-territory-dns')
    monkeypatch.setattr(document_source,'_DNS',resolver)
    state = SimpleNamespace(requests=[],workers=[],closed=threading.Event(),on_chunk=lambda:None)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):
            pass

        def do_POST(self):
            state.workers.append(threading.current_thread())
            self.rfile.read(int(self.headers.get('Content-Length','0')))
            state.requests.append(self.path)
            try:
                if self.path == '/redirect':
                    self.send_response(302)
                    self.send_header('Location','http://user:secret@127.0.0.1/never-follow')
                    self.send_header('Content-Length','0')
                    self.end_headers()
                    return
                if self.path == '/slow':
                    threading.Event().wait(0.6)
                if self.path == '/headers':
                    self.wfile.write(b'HTTP/1.1 200 OK\r\nX-Slow: ')
                    self.wfile.flush()
                elif self.path == '/ready':
                    raw = b'{"territory":{"inside_moscow":true}}'
                    self.send_response(200)
                    self.send_header('Content-Length',str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                    return
                else:
                    self.send_response(200)
                    self.send_header('Content-Length','1000')
                    self.end_headers()
                state.on_chunk()
                for _ in range(40):
                    self.wfile.write(b' ')
                    self.wfile.flush()
                    threading.Event().wait(0.025)
            except (BrokenPipeError,ConnectionResetError,OSError):
                state.closed.set()

    server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=lambda:server.serve_forever(poll_interval=0.01),daemon=True)
    thread.start()
    state.url = 'http://127.0.0.1:'+str(server.server_port)
    try:
        yield state
    finally:
        try:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)
            for worker in state.workers:
                worker.join(timeout=1)
            assert not thread.is_alive() and not any(worker.is_alive() for worker in state.workers)
        finally:
            resolver.shutdown(wait=True,cancel_futures=True)


@pytest.fixture
def file_entrypoint(monkeypatch,tmp_path):
    sent=[]
    monkeypatch.setattr(core,'_PLATO_STAGE_DIR',tmp_path/'stage')
    monkeypatch.setattr(core,'_TELEGRAM_DIALOGS',{})
    monkeypatch.setattr(core,'_telegram_send_message',lambda chat,text,**kw:sent.append((text,kw.get('reply_markup'))))
    monkeypatch.setattr(core,'_telegram_platon_remember_document',lambda *_:'')
    monkeypatch.setattr(core,'usage_track',lambda *a,**kw:None)
    monkeypatch.setattr(main,'_user_to_core',lambda *a,**kw:None)
    monkeypatch.setattr(core,'_telegram_user_allowed',lambda *_:True)
    monkeypatch.setattr(core,'_telegram_file_bytes',lambda *_:b'synthetic')
    monkeypatch.setattr(document_intake,'extract_text',lambda data,name:{
        'filename':name,'pages':1,'text':'[стр. 1]\nКН '+NUMBER})
    monkeypatch.setattr(core,'plato_answer',lambda *_:{'answer':json.dumps({
        'fields':[{'key':'cadastral_numbers','value':[NUMBER],'unit':'список','quote':'КН '+NUMBER}],
        'questions':[],'notes':[]})})
    begin=core._telegram_document_begin
    def short_begin(*args):
        operation=begin(*args)
        operation['deadline']=time.monotonic()+0.15
        return operation
    monkeypatch.setattr(core,'_telegram_document_begin',short_begin)
    def run():
        main._handle_update({'message':{'chat':{'id':CHAT,'type':'private'},'from':{'id':CHAT},
            'document':{'file_id':'synthetic-only','file_name':'source.pdf'}}})
    return sent,run


@pytest.mark.parametrize('route',['core','local'])
@pytest.mark.parametrize('mode',['slow','headers','body'])
def test_file_region_total_deadline_closes_slow_and_trickling_http(
        file_entrypoint,territory_http,monkeypatch,route,mode):
    sent,run=file_entrypoint
    target=territory_http.url+'/'+mode
    monkeypatch.setattr(core,'_core_api_url',lambda *_:target if route=='core' else '')
    monkeypatch.setattr(core,'_GLAVAPU_ANALYSIS_URL',target)
    started=time.monotonic()
    run()
    assert time.monotonic()-started < 0.5
    state=core._telegram_dialog_get(CHAT)
    assert state['document_read']['status']=='failed' and not state.get('intake')
    assert processing.Expired.public_message in sent[-1][0]
    assert all(markup is None for _,markup in sent)
    assert territory_http.requests==['/'+mode]
    assert territory_http.closed.wait(0.8), 'The server must observe client socket cleanup'


@pytest.mark.parametrize('outcome',['cancelled','superseded'])
def test_file_region_transport_stops_old_publication_when_source_changes(
        file_entrypoint,territory_http,monkeypatch,outcome):
    sent,run=file_entrypoint
    monkeypatch.setattr(core,'_core_api_url',lambda *_:territory_http.url+'/body')
    messages_at_change=[]
    def change():
        messages_at_change.append(len(sent))
        if outcome=='cancelled':
            core._telegram_dialog_clear(CHAT)
        else:
            core._telegram_intake_begin(CHAT,'next-source.pdf')
    territory_http.on_chunk=change
    run()
    state=core._telegram_dialog_get(CHAT)
    if outcome=='cancelled':
        assert state is None
    else:
        assert state['document_read']['status']=='loading'
        assert state['document_read']['filename']=='next-source.pdf' and not state.get('intake')
    assert messages_at_change==[len(sent)] and all(markup is None for _,markup in sent)
    assert territory_http.closed.wait(0.5)


def test_file_region_success_publishes_only_its_own_source_card(
        file_entrypoint,territory_http,monkeypatch):
    sent,run=file_entrypoint
    monkeypatch.setattr(core,'_core_api_url',lambda *_:territory_http.url+'/ready')
    run()
    state=core._telegram_dialog_get(CHAT)
    assert state['document_read']['status']=='ready' and state['intake']['id']
    queue=core._intake_queue_load(state['intake']['id'],request=core._telegram_agent_request(CHAT))
    assert queue['source']['kind']=='upload' and queue['filename']=='source.pdf'
    assert territory_http.requests==['/ready']
    assert any(markup is not None for _,markup in sent)


def test_new_file_entrypoint_finishes_while_the_old_territory_reply_is_pending(
        file_entrypoint,territory_http,monkeypatch):
    sent,run=file_entrypoint
    monkeypatch.setattr(core,'_core_api_url',lambda *_:territory_http.url+'/body')
    first_extract=document_intake.extract_text
    first_model=core.plato_answer
    monkeypatch.setattr(core,'_telegram_file_bytes',lambda file_id,*_:
        b'next-source' if file_id=='next-file' else b'synthetic')
    monkeypatch.setattr(document_intake,'extract_text',lambda data,name:
        {'filename':name,'pages':1,'text':'[стр. 1]\nНовый независимый источник'}
        if name=='next-source.pdf' else first_extract(data,name))
    monkeypatch.setattr(core,'plato_answer',lambda req,request:
        {'answer':json.dumps({'fields':[],'questions':[],'notes':[]})}
        if 'Новый независимый источник' in req.message else first_model(req,request))
    after_new=[]
    def new_source():
        main._handle_update({'message':{'chat':{'id':CHAT,'type':'private'},'from':{'id':CHAT},
            'document':{'file_id':'next-file','file_name':'next-source.pdf'},'caption':'посмотри тизер'}})
        after_new.append(len(sent))
    territory_http.on_chunk=new_source
    run()
    state=core._telegram_dialog_get(CHAT)
    assert state['document_read']['status']=='ready'
    assert state['document_read']['filename']=='next-source.pdf'
    queue=core._intake_queue_load(state['intake']['id'],request=core._telegram_agent_request(CHAT))
    assert queue['filename']=='next-source.pdf'
    assert queue['source']['sha256']==hashlib.sha256(b'next-source').hexdigest()
    assert after_new==[len(sent)] and territory_http.requests==['/body']
    assert territory_http.closed.wait(0.5)


def test_document_territory_transport_does_not_follow_redirects(territory_http):
    request=urllib.request.Request(territory_http.url+'/redirect',data=b'{}',method='POST')
    with processing.operation(seconds=1):
        with pytest.raises(urllib.error.HTTPError) as refused:
            processing.post_bytes(request,180)
        assert refused.value.code==302
        refused.value.close()
    assert territory_http.requests==['/redirect']


def test_document_territory_transport_rejects_url_credentials_before_dns(monkeypatch):
    import document_source
    monkeypatch.setattr(document_source,'_resolve',lambda *_:pytest.fail('Credentials reached DNS'))
    request=urllib.request.Request('https://name:secret@example.invalid/territory',data=b'{}')
    with processing.operation(seconds=1),pytest.raises(ValueError,match='настроен некорректно'):
        processing.post_bytes(request,180)


def test_ordinary_core_http_keeps_its_existing_transport_and_timeout(monkeypatch):
    response=io.BytesIO(b'{"existing":true}')
    timeouts=[]
    monkeypatch.setattr(core.urllib.request,'urlopen',lambda request,timeout:
        timeouts.append(timeout) or response)
    monkeypatch.setattr(processing,'post_bytes',lambda *_:pytest.fail('Ordinary core HTTP changed'))
    assert core._core_post('https://example.invalid/territory',{},180)=={'existing':True}
    assert timeouts==[180] and response.closed


def test_local_parcel_probe_workers_inherit_the_document_deadline(territory_http):
    request=urllib.request.Request(territory_http.url+'/body',data=b'{}')
    # The real probe executor must propagate the native context to each child.
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(core,'_glavapu_knows_number',lambda _:
            processing.post_bytes(request,30))
        started=time.monotonic()
        with processing.operation(seconds=0.15):
            core._glavapu_probe_numbers([NUMBER,NUMBER+'0'])
        assert time.monotonic()-started < 0.5
    assert len(territory_http.requests)==2 and territory_http.closed.wait(0.5)
