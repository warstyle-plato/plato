"""Bounded native document stages, with fake transport/provider and temp state."""
from __future__ import annotations

import io
import json
import zipfile
from types import SimpleNamespace

import pytest
from pypdf import PdfWriter

import document_intake
import document_processing as processing
import main
import pdf_ocr

core = main.core


def xlsx(sheet='<row r="1"><c r="A1" t="inlineStr"><is><t>ok</t></is></c></row>', *, missing=False):
    files = {
        'xl/workbook.xml':'<workbook xmlns="'+core._XLSX_MAIN_NS+'" xmlns:r="'+core._XLSX_REL_NS+'"><sheets><sheet name="Data" sheetId="1" r:id="rId1"/></sheets></workbook>',
        'xl/_rels/workbook.xml.rels':'<Relationships xmlns="'+core._XLSX_PKG_REL_NS+'"><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>',
    }
    if not missing:
        files['xl/worksheets/sheet1.xml']='<worksheet xmlns="'+core._XLSX_MAIN_NS+'"><sheetData>'+sheet+'</sheetData></worksheet>'
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
        for name,value in files.items():archive.writestr(name,value)
    return output.getvalue()


def test_existing_small_xlsx_keeps_exact_table_and_max_excel_address_is_valid():
    assert core._xlsx_read_tables(xlsx()) == {'Data':[['ok']]}
    assert core._xlsx_col_index('XFD1048576') == 16383


@pytest.mark.parametrize('cell',['XFE1','A1048577','Z'*80+'1','A0','1','A'])
def test_invalid_excel_addresses_reject_before_dense_allocation(cell):
    with pytest.raises(ValueError):core._xlsx_col_index(cell)


@pytest.mark.parametrize('value',['NaN','Infinity','1e999'])
def test_nonfinite_numeric_cells_never_become_document_values(value):
    data=xlsx('<row r="1"><c r="A1"><v>'+value+'</v></c></row>')
    with pytest.raises(ValueError,match='числовое'):
        core._xlsx_read_tables(data)


@pytest.mark.parametrize('case',['slots','member','members','xml_nodes','missing','duplicate_column'])
def test_xlsx_limits_reject_whole_input_without_a_partial_table(monkeypatch,case):
    data=xlsx()
    if case=='slots':monkeypatch.setattr(core,'_XLSX_MAX_TABLE_SLOTS',0)
    elif case=='member':monkeypatch.setattr(core,'_XLSX_MAX_MEMBER_BYTES',10)
    elif case=='members':monkeypatch.setattr(core,'_XLSX_MAX_MEMBERS',1)
    elif case=='xml_nodes':monkeypatch.setattr(core,'_XLSX_MAX_XML_NODES',1)
    elif case=='missing':data=xlsx(missing=True)
    else:data=xlsx('<row r="1"><c r="A1"><v>1</v></c><c r="A1"><v>2</v></c></row>')
    with pytest.raises(ValueError):core._xlsx_read_tables(data)


def test_encrypted_pdf_names_its_real_failure_without_invoking_ocr(monkeypatch):
    writer=PdfWriter();writer.add_blank_page(width=100,height=100);writer.encrypt('synthetic')
    output=io.BytesIO();writer.write(output)
    monkeypatch.setattr(pdf_ocr,'text',lambda *a,**k:pytest.fail('encrypted source reached OCR'))
    result=document_intake.extract_text(output.getvalue(),'encrypted.pdf')
    assert not result['text'] and 'паролем' in result['reason']


def test_nested_document_stage_does_not_restart_the_overall_budget(monkeypatch):
    now=[0.0];monkeypatch.setattr(processing.time,'monotonic',lambda:now[0])
    with processing.operation(seconds=240):
        now[0]=200
        with processing.operation(seconds=240):
            assert processing.remaining()==40
            now[0]=241
            with pytest.raises(processing.Expired):processing.check()


def test_cancelled_source_is_rejected_before_next_native_stage():
    current=[True]
    with processing.operation(current=lambda:current[0]):
        current[0]=False
        with pytest.raises(processing.Cancelled):processing.check()


def test_native_ocr_subprocess_receives_only_the_remaining_budget(monkeypatch):
    now=[0.0];monkeypatch.setattr(processing.time,'monotonic',lambda:now[0])
    received=[]
    monkeypatch.setattr(pdf_ocr.subprocess,'run',lambda *a,**k:
        received.append(k['timeout']) or SimpleNamespace(returncode=0,stdout=b'Synthetic recognized text'))
    with processing.operation(seconds=240):
        now[0]=237
        assert pdf_ocr._recognized(b'synthetic')=='Synthetic recognized text'
    assert received==[3]


@pytest.mark.parametrize('response,error',[
    ({'status':'incomplete'},'incomplete'),
    ({'status':'failed'},'failed'),
    ({'error':{'message':'UNTRUSTED_PROVIDER_TEXT'}},'failed'),
    ({'status':'completed','output':[{'type':'message','content':[{'type':'refusal','refusal':'UNTRUSTED_PROVIDER_TEXT'}]}]},'refusal'),
    ({'status':'completed','output':[]},None),
])
def test_document_outcome_keeps_typed_reason_without_provider_text(response,error):
    assert document_intake.model_error(response)==error
    if error:assert 'UNTRUSTED_PROVIDER_TEXT' not in document_intake.DOCUMENT_MODEL_ERRORS[error]


class Response(io.BytesIO):
    def __init__(self,data,declared):
        super().__init__(data)
        self.headers={} if declared is None else {'Content-Length':str(declared)}
        self.timeouts=[]
        self.fp=SimpleNamespace(raw=SimpleNamespace(_sock=SimpleNamespace(settimeout=self.timeouts.append)))


@pytest.mark.parametrize('data,declared,limit,ok',[
    (b'abcd',4,4,True),(b'abcd',None,4,True),(b'abc',4,4,False),
    (b'abcde',None,4,False),(b'',0,4,False),(b'abcd',5,4,False),
])
def test_telegram_transport_checks_declared_actual_and_empty_bytes(monkeypatch,data,declared,limit,ok):
    received=[];response=Response(data,declared)
    monkeypatch.setattr(core,'_telegram_api',lambda method,payload,**kwargs:
        received.append((method,kwargs['timeout'])) or {'file_path':'documents/synthetic.pdf'})
    monkeypatch.setattr(core,'_telegram_token',lambda:'synthetic-only')
    monkeypatch.setattr(core.urllib.request,'urlopen',lambda *a,**k:response)
    if ok:assert core._telegram_file_bytes('synthetic',limit)==data
    else:
        with pytest.raises(ValueError):core._telegram_file_bytes('synthetic',limit)
    assert received[0][0]=='getFile' and 0 < received[0][1] <= 15
    assert response.closed


@pytest.fixture
def document_chat(monkeypatch,tmp_path):
    assert all(callable(getattr(core,name,None))for name in
        ('_telegram_intake_begin','_telegram_intake_current','_telegram_intake_commit')), (
        'The loader component requires the native durable dialogue component in composition')
    monkeypatch.setattr(core,'_PLATO_STAGE_DIR',tmp_path/'stage')
    monkeypatch.setattr(core,'_TELEGRAM_DIALOGS',{})
    monkeypatch.setenv('DEVELOPAID_ADMIN_KEY','synthetic-loader-key')
    monkeypatch.setattr(core,'_telegram_platon_remember_document',lambda *_:'')
    sent=[]
    monkeypatch.setattr(core,'_telegram_send_message',lambda chat,text,**kwargs:
        sent.append((text,kwargs.get('reply_markup'))))
    monkeypatch.setattr(document_intake,'extract_text',lambda data,name:
        {'text':'[стр. 1]\nSynthetic readable document','pages':1,'filename':name})
    monkeypatch.setattr(core,'plato_answer',lambda *_:{'answer':json.dumps({'fields':[],'questions':[],'notes':[]})})
    return sent


def test_new_document_queue_is_owner_bound_schema2_and_has_source_pinned_action(document_chat):
    chat=900000003
    core._telegram_handle_intake_document(chat,b'synthetic','source.pdf')
    dialog=core._telegram_dialog_get(chat)
    queue=core._intake_queue_load(dialog['intake']['id'],request=core._telegram_agent_request(chat))
    assert queue['callback_schema']==2
    assert dialog['document_read']['status']=='ready'
    assert dialog['document_read']['source_sha256']
    assert document_chat[0][0].startswith('<b>Документ принят')
    action=document_chat[-1][1]['inline_keyboard'][0][0]['callback_data']
    assert queue['id'] in action and len(action.encode('utf-8'))<=64
    assert action==core._telegram_intake_callback_data(queue['id'],'questions')


def test_persistence_failure_has_no_unpublished_id_or_continue_action(document_chat,monkeypatch):
    chat=900000003
    monkeypatch.setattr(core,'_intake_queue_save',lambda *_:(_ for _ in ()).throw(OSError('synthetic disk full')))
    core._telegram_handle_intake_document(chat,b'synthetic','source.pdf')
    dialog=core._telegram_dialog_get(chat)
    assert not dialog.get('intake') and dialog['document_read']['status']=='failed'
    assert all(markup is None for _,markup in document_chat)
    assert 'сохранить' in document_chat[-1][0]


def test_document_api_metadata_and_body_use_the_same_remaining_deadline(monkeypatch):
    now=[0.0];monkeypatch.setattr(processing.time,'monotonic',lambda:now[0])
    body=b'{"ok":true,"result":{"file_path":"documents/synthetic.pdf"}}'
    response=Response(body,len(body));timeouts=[]
    monkeypatch.setattr(core,'_telegram_token',lambda:'synthetic-only')
    monkeypatch.setattr(core.urllib.request,'urlopen',lambda request,timeout:
        timeouts.append(timeout) or response)
    with processing.operation(seconds=240):
        now[0]=239
        assert core._telegram_api('getFile',{'file_id':'synthetic'})['file_path']=='documents/synthetic.pdf'
    assert timeouts==[1] and response.timeouts and all(value<=1 for value in response.timeouts)
    assert response.closed


def test_trickle_response_cannot_reset_the_document_deadline(monkeypatch):
    now=[0.0];monkeypatch.setattr(processing.time,'monotonic',lambda:now[0])
    class Trickle(Response):
        def read1(self,limit):
            now[0]+=1
            return b'x'
    response=Trickle(b'',None)
    monkeypatch.setattr(core,'_telegram_api',lambda *a,**k:{'file_path':'documents/synthetic.pdf'})
    monkeypatch.setattr(core,'_telegram_token',lambda:'synthetic-only')
    monkeypatch.setattr(core.urllib.request,'urlopen',lambda *a,**k:response)
    with processing.operation(seconds=2):
        with pytest.raises(processing.Expired):core._telegram_file_bytes('synthetic',16)
    assert response.closed and now[0]<=2


def test_large_pdf_raster_is_rejected_before_allocating_pixmap(monkeypatch):
    import pymupdf
    closed=[]
    page=SimpleNamespace(rect=SimpleNamespace(width=100000,height=100000),
        get_pixmap=lambda **kwargs:pytest.fail('Oversized page allocated a raster'))
    class Document:
        page_count=1
        def __getitem__(self,index):return page
        def close(self):closed.append(True)
    monkeypatch.setattr(pymupdf,'open',lambda **kwargs:Document())
    monkeypatch.setattr(pdf_ocr,'unavailable_reason',lambda:'')
    with pytest.raises(pdf_ocr.Unavailable,match='слишком велика'):
        pdf_ocr.text(b'synthetic',page_indices=[0])
    assert closed==[True]


def test_cancel_between_chunks_never_publishes_the_old_last_button(document_chat,monkeypatch):
    chat=900000003
    operation=core._telegram_document_begin(chat,'synthetic.pdf')
    calls=[]
    def send(identifier,text,**kwargs):
        calls.append(kwargs.get('reply_markup'))
        core._telegram_dialog_clear(chat)
    monkeypatch.setattr(core,'_telegram_send_message',send)
    assert core._telegram_document_reply(operation,'<b>'+('я'*9000)+'</b>',
        reply_markup={'inline_keyboard':[[{'text':'Synthetic','callback_data':'synthetic'}]]}) is False
    assert calls==[None]


def test_persisted_pending_document_expires_after_restart_without_replaying_provider(document_chat,monkeypatch):
    now=[1000.0];monkeypatch.setattr(core.time,'time',lambda:now[0])
    chat=900000003
    nonce=core._telegram_intake_begin(chat,'source.pdf')
    read=core._telegram_dialog_get(chat)['document_read']
    assert read['started_at']==1000 and read['deadline_at']==1240
    monkeypatch.setattr(core,'_TELEGRAM_DIALOGS',{})  # another native worker
    monkeypatch.setattr(core,'plato_answer',lambda *_:pytest.fail('Resume retried a provider'))
    now[0]=1241
    resumed=core._telegram_dialog_get(chat)
    assert resumed['document_read']['status']=='interrupted'
    assert resumed['step']=='intake_document_failed'
    assert not core._telegram_intake_current(chat,nonce)
    assert core._telegram_intake_current(chat,nonce,allow_failed=True)
    accepted,_=core._telegram_intake_commit(chat,nonce,lambda _:pytest.fail('Expired source committed'))
    assert accepted is False


def test_legacy_loading_without_a_deadline_is_interrupted_on_resume(document_chat,monkeypatch):
    chat=900000003
    path=core._telegram_dialog_path(chat);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps({'updated_at':int(core.time.time()),'step':'intake_document_reading',
        'document_read':{'id':'a'*32,'status':'loading','filename':'legacy.pdf'}}))
    monkeypatch.setattr(core,'_TELEGRAM_DIALOGS',{})
    resumed=core._telegram_dialog_get(chat)
    assert resumed['document_read']['status']=='interrupted'
    assert resumed['step']=='intake_document_failed'


def test_url_source_uses_the_same_native_generation_card_and_preserves_lineage(document_chat,monkeypatch):
    import document_source
    chat=900000003
    source={'kind':'url','sha256':'a'*64,'url':'https://example.invalid/synthetic'}
    observed=[]
    def load(url,**kwargs):
        observed.append((bool(document_chat),kwargs['timeout']))
        return {'filename':'source.html','text':'Synthetic source text','source':source}
    monkeypatch.setattr(document_source,'read_url',load)
    core._telegram_handle_intake_url(chat,'https://example.invalid/synthetic')
    dialog=core._telegram_dialog_get(chat)
    queue=core._intake_queue_load(dialog['intake']['id'],request=core._telegram_agent_request(chat))
    assert observed[0][0] and 0 < observed[0][1] <= 20
    assert queue['source']==source and queue['filename']=='source.html'
    assert dialog['document_read']['status']=='ready'


def test_cancelled_url_download_cannot_create_a_card(document_chat,monkeypatch):
    import document_source
    chat=900000003
    def load(url,**kwargs):
        core._telegram_dialog_clear(chat)
        return {'filename':'source.html','text':'Synthetic source text',
                'source':{'kind':'url','sha256':'a'*64}}
    monkeypatch.setattr(document_source,'read_url',load)
    core._telegram_handle_intake_url(chat,'https://example.invalid/synthetic')
    assert core._telegram_dialog_get(chat) is None
    assert all(markup is None for _,markup in document_chat)


@pytest.mark.parametrize('source_kind',['url','pdf'])
@pytest.mark.parametrize('active_conversation',[False,True])
def test_new_source_entrypoint_claims_and_acknowledges_before_io(
        document_chat,monkeypatch,source_kind,active_conversation):
    import document_source
    chat=900000003
    monkeypatch.setattr(core,'usage_track',lambda *a,**k:None)
    monkeypatch.setattr(main,'_user_to_core',lambda *a,**k:None)
    monkeypatch.setattr(core,'_telegram_user_allowed',lambda *_:True)
    monkeypatch.setattr(main,'_dialog_active',lambda *_:active_conversation)
    monkeypatch.setattr(main,'_run_agent',lambda *_:pytest.fail('New source reached the old conversation'))
    loaded=[]
    def before_io():
        assert document_chat, 'The source must be acknowledged before its first IO'
        state=core._telegram_dialog_get(chat) or {}
        assert (state.get('document_read') or {}).get('status')=='loading'
        assert processing.deadline() is not None
        assert core._TELEGRAM_INTAKE_LOCKED.get() is None
        loaded.append(True)
    def load_url(url,**kwargs):
        before_io()
        assert 0 < kwargs['timeout'] <= 20
        return {'filename':'source.html','text':'Synthetic readable source',
                'source':{'kind':'url','sha256':'a'*64}}
    def load_file(file_id,max_bytes):
        before_io()
        return b'synthetic'
    monkeypatch.setattr(document_source,'read_url',load_url)
    monkeypatch.setattr(core,'_telegram_file_bytes',load_file)
    message={'chat':{'id':chat,'type':'private'},'from':{'id':chat}}
    if source_kind=='url':
        message['text']='https://example.invalid/synthetic'
    else:
        message['document']={'file_id':'synthetic','file_name':'source.pdf'}
    main._handle_update({'message':message})
    state=core._telegram_dialog_get(chat)
    assert loaded==[True]
    assert state['document_read']['status']=='ready' and state['intake']['id']


@pytest.mark.parametrize('outcome',['cancelled','expired'])
def test_url_entrypoint_closes_without_a_card_after_download_stops(
        document_chat,monkeypatch,outcome):
    import document_source
    chat=900000003
    monkeypatch.setattr(core,'usage_track',lambda *a,**k:None)
    monkeypatch.setattr(main,'_user_to_core',lambda *a,**k:None)
    monkeypatch.setattr(core,'_telegram_user_allowed',lambda *_:True)
    def load(url,**kwargs):
        assert document_chat and processing.deadline() is not None
        if outcome=='cancelled':
            core._telegram_dialog_clear(chat)
            raise processing.Cancelled()
        raise processing.Expired()
    monkeypatch.setattr(document_source,'read_url',load)
    main._handle_update({'message':{'chat':{'id':chat,'type':'private'},
        'from':{'id':chat},'text':'https://example.invalid/synthetic'}})
    state=core._telegram_dialog_get(chat)
    if outcome=='cancelled':
        assert state is None
    else:
        assert state['document_read']['status']=='failed' and not state.get('intake')
        assert processing.Expired.public_message in document_chat[-1][0]
    assert all(markup is None for _,markup in document_chat)


@pytest.mark.parametrize('failure',['refusal','incomplete','failed'])
def test_typed_model_failure_reaches_the_user_after_the_source_is_closed(document_chat,monkeypatch,failure):
    calls=[]
    monkeypatch.setattr(core,'plato_answer',lambda *_:
        calls.append(True) or {'answer':'','document_error':failure})
    core._telegram_handle_intake_document(900000003,b'synthetic','source.pdf')
    dialog=core._telegram_dialog_get(900000003)
    assert dialog['document_read']['status']=='failed'
    assert document_intake.DOCUMENT_MODEL_ERRORS[failure] in document_chat[-1][0]
    assert calls==[True] and all(markup is None for _,markup in document_chat)


@pytest.mark.parametrize('reason',['Synthetic OCR unavailable','PDF защищён паролем'])
def test_unread_document_has_a_terminal_notice_inside_the_original_source_context(document_chat,monkeypatch,reason):
    monkeypatch.setattr(document_intake,'extract_text',lambda *a,**k:
        {'text':'','pages':1,'reason':reason})
    monkeypatch.setattr(core,'plato_answer',lambda *_:pytest.fail('Unread source called model'))
    core._telegram_handle_intake_document(900000003,b'synthetic','source.pdf')
    assert reason in document_chat[-1][0]
    assert core._telegram_dialog_get(900000003)['document_read']['status']=='failed'


def test_failure_notification_never_reopens_the_source_budget(document_chat,monkeypatch):
    current=[True]
    request=core._telegram_agent_request(900000003)
    monkeypatch.setattr(core,'plato_answer',lambda *_:pytest.fail('Notification retried provider'))
    monkeypatch.setattr(core,'_telegram_token',lambda:'synthetic')
    with processing.operation(current=lambda:current[0]):
        current[0]=False
        with processing.notification(current=lambda:True):
            assert 0 < processing.delivery_remaining() <= 15
            with pytest.raises(processing.Cancelled):processing.check()
            with pytest.raises(processing.Cancelled):
                core.document_intake_read({'text':'Synthetic source'},request)
            with pytest.raises(processing.Cancelled):
                core._telegram_api('getFile',{'file_id':'synthetic'})
        with pytest.raises(processing.Cancelled):processing.check()


def test_failure_notice_requires_closed_status_and_the_current_nonce(document_chat):
    operation=core._telegram_document_begin(900000003,'source.pdf')
    before=len(document_chat)
    assert core._telegram_document_reply(operation,'not a failure',allow_failed=True) is False
    assert len(document_chat)==before
    core._telegram_document_publish(operation,'source.pdf')
    assert core._telegram_document_reply(operation,'not a failure',allow_failed=True) is False
    core._telegram_dialog_clear(900000003)
    assert core._telegram_document_reply(operation,'cancelled',allow_failed=True) is False
    assert len(document_chat)==before


def test_telegram_rate_limit_does_not_trigger_a_second_failure_message(document_chat,monkeypatch):
    calls=[]
    def limited(chat,text,**kwargs):
        calls.append(text)
        raise RuntimeError('Telegram API: HTTP 429: Too Many Requests')
    monkeypatch.setattr(core,'_telegram_send_message',limited)
    monkeypatch.setattr(core,'_telegram_handle_update',lambda update:
        core._telegram_handle_intake_document(900000003,b'synthetic','source.pdf'))
    core._telegram_process_update({'message':{'chat':{'id':900000003,'type':'private'}}})
    assert len(calls)==1
    assert '429' in core._TELEGRAM_RUNTIME['last_error']
    assert core._telegram_dialog_get(900000003)['document_read']['status']=='failed'
