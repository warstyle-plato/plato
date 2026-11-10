import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import pytest
import developaid_cached_source_audit as audit

NOW=dt.datetime(2026,11,10,9,tzinfo=dt.timezone.utc)
RUNTIME={'commit':'a'*40,'version':'0.28.93'}


def put(root,name,value):
    p=root/name;p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(value,ensure_ascii=False));return p


@pytest.fixture
def saved(tmp_path):
    put(tmp_path,'catalogue.json',{'schema_version':3,'complete':True,
        'retrieved_at':NOW.timestamp()-1800,'projects':[
        {'slug':'running-site','name':'Площадка А','status':'В реализации','last_known_status_kind':'running'},
        {'slug':'planned-site','status':'Планируемый'}]})
    put(tmp_path,'decisions.json',{'schema_version':3,'complete':True,'all':[],
        'skipped':[],'walk':{'pages':60,'pages_announced':60,'seen':598,'announced':598}})
    put(tmp_path,'ranking.json',{'schema_version':1,'catalogue_run_at':audit.TARGET_PERIOD+7200,
        'rows':[{'slug':'running-site','computed_at':audit.TARGET_PERIOD-86400,
            'model_fingerprint':'b'*64,'rules_version':17,'engine_version':'0.28.84',
            'investment_rating_version':'issue-485-krt-rating-4x100-v4',
            'investment_rating_computed_at':audit.TARGET_PERIOD-86400,
            'investment_rating':{'available':True,'score':41.2}}]})
    put(tmp_path,'schedule.json',{'period':audit.TARGET_PERIOD,'total':2,'failed':0,
        'attempted':['running-site','planned-site'],'started_at':audit.TARGET_PERIOD,
        'finished_at':audit.TARGET_PERIOD+7200})
    put(tmp_path,'reports/running-site.json',{'schema_version':1,'slug':'running-site',
        'computed_at':audit.TARGET_PERIOD-86400,
        'project':{'slug':'running-site','status':'В реализации'},
        'screening':{'available':True,'model':{'amount':12345}},
        'prompt':'CANARY-RAW-PROMPT','auth':{'token':'CANARY-AUTH-SECRET'},
        'market':{'private_key':'CANARY-PRIVATE-KEY'}})
    return tmp_path


def collect(root):return audit.capture_krt(root,runtime=RUNTIME,now=NOW)


def test_actual_bytes_and_saved_dates_are_preserved_without_false_production_pass(saved):
    before={str(p.relative_to(saved)):(p.read_bytes(),p.stat().st_mtime_ns) for p in saved.rglob('*') if p.is_file()}
    got=collect(saved)
    after={str(p.relative_to(saved)):(p.read_bytes(),p.stat().st_mtime_ns) for p in saved.rglob('*') if p.is_file()}
    assert before==after
    assert got['reads_only'] and got['coherent'] and not got['production_acceptance']
    assert not got['models_or_scores_computed'] and not got['source_files_written']
    report=next(x for x in got['files'] if x['logical_path']=='krt/reports/running-site.json')
    assert report['sha256']==hashlib.sha256(before['reports/running-site.json'][0]).hexdigest()
    assert report['projection']['computed_at']==audit.TARGET_PERIOD-86400
    assert report['projection']['screening_metadata']['model_known'] is True
    encoded=json.dumps(got)
    assert all(x not in encoded for x in ['CANARY-RAW-PROMPT','CANARY-AUTH-SECRET','CANARY-PRIVATE-KEY'])
    assert not any(k in report['projection'] for k in ['prompt','auth','market','private_key'])


def test_authorization_rejects_before_root_or_runtime_is_read(saved):
    events=[]
    def denied():events.append('auth');raise PermissionError('denied')
    def forbidden():pytest.fail('I/O before authorization')
    with pytest.raises(PermissionError):audit.after_admission(denied,forbidden,forbidden)
    assert events==['auth']


def test_authorized_adapter_preserves_normal_capture(saved):
    events=[]
    def admit():events.append('admitted')
    def root():assert events==['admitted'];events.append('root');return saved
    def runtime():assert events==['admitted','root'];return RUNTIME
    assert audit.after_admission(admit,root,runtime,now=NOW)['target_sunday']=='2026-11-08'


@pytest.mark.parametrize('name',['catalogue.json','reports/running-site.json'])
def test_final_symlink_cannot_read_another_file(saved,tmp_path_factory,name):
    outside=tmp_path_factory.mktemp('outside')/'auth.json';outside.write_text('{"token":"secret"}')
    p=saved/name;p.unlink();p.symlink_to(outside)
    with pytest.raises(audit.AuditError,match='unsafe_file'):collect(saved)


@pytest.mark.parametrize('inside',[True,False])
def test_directory_symlink_is_refused_even_if_destination_is_inside_root(saved,tmp_path_factory,inside):
    source=saved/'reports';source.rename(saved/'reports-original')
    target=saved/'reports-original' if inside else tmp_path_factory.mktemp('other')
    source.symlink_to(target,target_is_directory=True)
    with pytest.raises(audit.AuditError,match='unsafe_directory'):collect(saved)


def test_root_symlink_is_refused(saved,tmp_path):
    link=saved.parent/(saved.name+'-alias');link.symlink_to(saved,target_is_directory=True)
    with pytest.raises(audit.AuditError,match='unsafe_root'):collect(link)


def test_hardlink_is_not_accepted_as_a_regular_saved_report(saved,tmp_path_factory):
    outside=tmp_path_factory.mktemp('hardlink')/'auth.json';outside.write_text('{"token":"secret"}')
    p=saved/'reports/running-site.json';p.unlink();os.link(outside,p)
    with pytest.raises(audit.AuditError,match='not_regular'):collect(saved)


def test_fifo_is_rejected_without_blocking(saved):
    p=saved/'ranking.json';p.unlink();os.mkfifo(p)
    with pytest.raises(audit.AuditError,match='not_regular'):collect(saved)


@pytest.mark.parametrize('path',['../auth.json','/proc/self/environ','reports/../../auth.json',
    'unknown.json','cards/a.json','reports/auth.json','reports/credentials.json'])
def test_only_fixed_relative_files_can_be_opened(saved,path):
    r=audit.Reader(saved)
    try:
        with pytest.raises(audit.AuditError,match='invalid_path'):r.read(path)
    finally:r.close()


@pytest.mark.parametrize('filename',['auth.json','credentials.json','secrets.json','tokens.json','config.json'])
def test_credential_named_files_in_report_directory_are_not_opened(saved,filename):
    put(saved,'reports/'+filename,{'token':'CANARY-NOT-READ'})
    with pytest.raises(audit.AuditError,match='unexpected_directory_entry'):collect(saved)


@pytest.mark.parametrize('raw',[b'{"rows":[],"rows":[1]}',b'{"computed_at":NaN}',b'{"computed_at":1e999}',b'not JSON'])
def test_invalid_or_ambiguous_json_cannot_be_accepted(saved,raw):
    (saved/'ranking.json').write_bytes(raw)
    with pytest.raises(audit.AuditError,match='invalid_json'):collect(saved)


def test_per_file_limit_prevents_oversize_read(saved,monkeypatch):
    monkeypatch.setattr(audit,'MAX_FILE_BYTES',8)
    with pytest.raises(audit.AuditError,match='file_too_large'):collect(saved)


def test_total_budget_applies_to_both_coherence_passes(saved,monkeypatch):
    actual=sum(p.stat().st_size for p in saved.rglob('*.json'))
    monkeypatch.setattr(audit,'MAX_TOTAL_READ_BYTES',actual+8)
    with pytest.raises(audit.AuditError,match='read_budget'):collect(saved)


def test_new_file_between_passes_is_detected(saved,monkeypatch):
    real=audit.Reader.paths;calls=0
    def changing(reader):
        nonlocal calls
        calls+=1
        if calls==2:put(saved,'reports/new-site.json',{'slug':'new-site'})
        return real(reader)
    monkeypatch.setattr(audit.Reader,'paths',changing)
    with pytest.raises(audit.AuditError,match='file_set_changed'):collect(saved)


def test_changed_bytes_between_passes_are_detected(saved,monkeypatch):
    real=audit.Reader.paths;calls=0
    def changing(reader):
        nonlocal calls
        calls+=1
        if calls==2:put(saved,'ranking.json',{'schema_version':1,'rows':[]})
        return real(reader)
    monkeypatch.setattr(audit.Reader,'paths',changing)
    with pytest.raises(audit.AuditError,match='snapshot_changed'):collect(saved)


def test_missing_data_is_not_zero_or_evidence_complete(tmp_path):
    got=collect(tmp_path)
    assert set(got['missing_files'])==set(audit.FIXED_FILES)
    assert got['files']==[] and not got['evidence_complete']
    assert 'required_saved_files_missing' in got['gaps']
    assert 'sunday_input_revision_not_proven' in got['gaps']
    assert 'excluded_models_before_after_not_proven' in got['gaps']


def test_filesystem_timestamp_does_not_refresh_old_embedded_catalogue(saved):
    value=json.loads((saved/'catalogue.json').read_text());value['retrieved_at']=NOW.timestamp()-35*86400
    put(saved,'catalogue.json',value)
    got=collect(saved)
    assert 'catalogue_stale_or_timestamp_unknown' in got['gaps']
    assert not got['production_acceptance']


def test_other_week_is_not_the_requested_sunday(saved):
    put(saved,'schedule.json',{'period':audit.TARGET_PERIOD+7*86400,'attempted':[]})
    assert 'saved_schedule_is_not_target_sunday' in collect(saved)['gaps']


def test_unknown_model_timestamp_is_none_not_zero(saved):
    put(saved,'reports/running-site.json',{'computed_at':'unknown','available':None})
    projection=next(v['projection'] for v in collect(saved)['files'] if v['logical_path'].endswith('/running-site.json'))
    assert projection['computed_at'] is None and projection['available'] is None


@pytest.mark.parametrize('bad',['-----BEGIN PRIVATE KEY-----','Bearer abc123','secret=abc','sk-proj-SYNTHETIC'])
def test_credential_markers_in_allowed_text_fields_fail_closed(saved,bad):
    put(saved,'reports/running-site.json',{'slug':'running-site','engine_version':bad})
    with pytest.raises(audit.AuditError,match='sensitive_field'):collect(saved)


def test_capture_limit_is_enforced_after_projection(saved,monkeypatch):
    monkeypatch.setattr(audit,'MAX_CAPTURE_BYTES',8)
    with pytest.raises(audit.AuditError,match='source_size_limit'):collect(saved)


def test_unsupported_saved_schema_is_an_explicit_gap(saved):
    value=json.loads((saved/'catalogue.json').read_text());value['schema_version']=99
    put(saved,'catalogue.json',value)
    assert 'catalogue_schema_unknown_or_unsupported' in collect(saved)['gaps']


def test_decision_identity_is_projected_without_document_bodies(saved):
    put(saved,'decisions.json',{'schema_version':3,'all':[{'id':'337332220','title':'Проект решения',
        'address':'Учебный адрес','published_at':1234,'raw_pdf_base64':'CANARY-DOCUMENT'}]})
    got=collect(saved)
    row=next(v['projection']['all'][0] for v in got['files'] if v['logical_path']=='krt/decisions.json')
    assert row['id']=='337332220' and row['published_at']==1234
    assert 'CANARY-DOCUMENT' not in json.dumps(got)


def test_absent_optional_settings_are_not_mislabeled_required_cache_loss(saved):
    got=collect(saved)
    assert got['missing_required_files']==[]
    assert set(got['missing_optional_files'])=={'first_seen.json','watch_seen.json','rating_settings.json'}
    assert 'required_saved_files_missing' not in got['gaps']
    assert 'optional_saved_files_absent' in got['gaps']


def test_rating_target_is_observed_without_choosing_a_default(saved):
    put(saved,'rating_settings.json',{'schema_version':1,'price_target_rub_sqm':600000})
    target=next(x['projection'] for x in collect(saved)['files'] if x['logical_path']=='krt/rating_settings.json')
    assert target['price_target_rub_sqm']==600000


def test_decision_replay_identity_keeps_official_fields_without_document_text(saved):
    url='https://www.mos.ru/dgi/documents/view/337332220/'
    put(saved,'decisions.json',{'schema_version':3,'all':[{'id':'337332220',
        'title':'Решение','address':'Учебная улица','okrug':'ЮАО','department':'ДГИ',
        'url':url,'published_at':1234,'text':'CANARY-DOCUMENT-TEXT'}]})
    row=next(v['projection']['all'][0] for v in collect(saved)['files']
             if v['logical_path']=='krt/decisions.json')
    assert row['url']==url and row['okrug']=='ЮАО' and row['department']=='ДГИ'
    assert 'CANARY-' not in json.dumps(row)


@pytest.mark.parametrize('url',[
    'https://user:pass@www.mos.ru/document',
    'https://www.mos.ru/document?access_token=CANARY',
    'https://unrelated-provider.example/document',
])
def test_authenticated_or_unexpected_source_urls_cannot_escape(saved,url):
    put(saved,'decisions.json',{'schema_version':3,'all':[{'id':'337332220','url':url}]})
    with pytest.raises(audit.AuditError):collect(saved)


def test_worker_refresh_observation_does_not_claim_global_completion(saved):
    got=audit.capture_krt(saved,runtime=RUNTIME,now=NOW,
        process={'catalogue_refreshing':False,'decisions_refreshing':True})
    assert 'runtime_refresh_flags_not_captured' not in got['gaps']
    assert 'observed_worker_refreshing' in got['gaps']
    assert 'other_worker_refresh_state_not_observed' in got['gaps']
    assert not got['production_acceptance']
