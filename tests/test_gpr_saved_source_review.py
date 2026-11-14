"""Review a saved source without uploading a workbook or changing history."""
import datetime as dt
import hashlib
import io
import json
import zipfile

import pytest
from openpyxl import load_workbook

import developaid_gpr_corpus as corpus
import developaid_gpr_source_prepare as prepare
import developaid_gpr_source_state as source_state
import developaid_monitor as monitor
import developaid_schedule_versions as versions
from test_gpr_corpus_preview import book
from test_monitor_cumulative_api import api, post

PROJECT = 'Synthetic saved corpus source'


@pytest.fixture
def sources(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, '_SNAPSHOT_DIR', tmp_path/'monitor')
    monkeypatch.setattr(versions, '_now', lambda: dt.datetime(2026, 11, 12, tzinfo=dt.timezone.utc))
    old = book()
    monitor.store_schedule(PROJECT, old, None, '2026-11-06')
    current = monitor._working_baseline_state(PROJECT)
    new = book(bad_date='30.06.2027')
    corpus.store(PROJECT, new, '2026-11-07', corpus.read(new))
    return current, hashlib.sha256(new).hexdigest()


def test_inventory_distinguishes_plan_from_parse_without_raw_and_preserves_history(sources):
    current, correct_sha = sources
    state = source_state.inspect(PROJECT, '2026-11-08')
    assert state['selected_plan']['source_sha256'] == current['source_sha256']
    fact = next(c for c in state['candidates'] if c['kind'] == 'corpus_fact_parse')
    assert fact['source_sha256'] == correct_sha and fact['raw_source_saved'] is False
    assert fact['summary']['invalid_dates'] == 0
    assert state['candidates'][0]['summary']['invalid_dates'] == 1
    assert all('path' not in c and 'data' not in c for c in state['candidates'])
    # Current display never replaces an approved file with the newer parse.
    shown = corpus.for_view(PROJECT, '2026-11-08', baseline_sha256=current['source_sha256'])
    assert shown['sha256'] == current['source_sha256'] and shown['issues'][0]['cell'] == 'G5'


def test_derived_review_is_deterministic_retains_coordinates_unknown_zero_dates_and_provenance(sources):
    current, correct_sha = sources
    before = {str(p): p.read_bytes() for p in monitor._project_dir(PROJECT).rglob('*') if p.is_file()}
    opts = dict(expected_active_sha256=current['source_sha256'], expected_revision=current['revision'])
    one = prepare.prepare(PROJECT, correct_sha, **opts)
    two = prepare.prepare(PROJECT, correct_sha, **opts)
    assert one['data'] == two['data'] and one['manifest'] == two['manifest']
    assert one['manifest']['comparison']['changed_plan_dates'] == 1
    assert one['manifest']['comparison']['changed_percentages'] == 0
    assert one['manifest']['applied'] is False
    wb = load_workbook(io.BytesIO(one['data']), data_only=False)
    assert wb.sheetnames == ['ГПР', 'Происхождение']
    assert wb['ГПР']['H5'].value is None and wb['ГПР']['E6'].value == 0
    assert wb['ГПР']['E5'].value == .25 and wb['ГПР']['G5'].value == '30.06.2027'
    assert wb['Происхождение']['B2'].value == correct_sha
    parsed = corpus.read(one['data'])
    assert parsed['packages'][0]['source_id'] == 'ГПР!B5'
    assert parsed['packages'][0]['scopes'][0]['source_cells']['progress'] == 'E5'
    assert parsed['packages'][0]['scopes'][0]['fact_day'] == '2026-11-06'
    after = {str(p): p.read_bytes() for p in monitor._project_dir(PROJECT).rglob('*') if p.is_file()}
    assert before == after


def test_exact_source_scoped_correction_never_normalises_other_dates(sources):
    current, _ = sources
    result = prepare.prepare(PROJECT, current['source_sha256'],
        expected_active_sha256=current['source_sha256'], expected_revision=current['revision'],
        corrections=[{'cell': 'G5', 'expected_raw': '31.06.2027', 'value': '30.06.2027', 'note': 'Explicit synthetic date decision'}])
    assert result['manifest']['corrections'][0]['original_raw'] == '31.06.2027'
    assert result['manifest']['prepared_invalid_dates'] == 0
    assert corpus.read(monitor._working_baseline_file(PROJECT).read_bytes())['issues'][0]['cell'] == 'G5'
    with pytest.raises(versions.ScheduleVersionConflict):
        prepare.prepare(PROJECT, current['source_sha256'], expected_active_sha256=current['source_sha256'],
            expected_revision=current['revision'], corrections=[{'cell':'G5', 'expected_raw':'wrong',
                'value':'30.06.2027', 'note':'decision'}])
    with pytest.raises(ValueError, match='нет источника'):
        prepare.prepare('Another project', current['source_sha256'], expected_active_sha256='', expected_revision=0)


@pytest.mark.parametrize('endpoint', ['saved-source-preview', 'saved-source-approve'])
def test_saved_source_api_checks_auth_before_read(api, monkeypatch, endpoint):
    client, _ = api
    monkeypatch.setattr(prepare, 'prepare', lambda *a, **k: pytest.fail('read before admission'))
    response = post(client, 'schedule/'+endpoint, key='wrong', project=PROJECT,
        source_sha256='a'*64, expected_active_sha256='b'*64, expected_revision=0, effective_from='2026-11-12')
    assert response.status_code == 403 and response.headers['cache-control'] == 'private, no-store'


def test_native_saved_source_preview_and_approval_are_hash_revision_bound_and_keep_originals(api, monkeypatch):
    client, _ = api
    monkeypatch.setattr(versions, '_now', lambda: dt.datetime(2026, 11, 12, tzinfo=dt.timezone.utc))
    monitor.store_schedule(PROJECT, book(), None, '2026-11-06')
    current = monitor._working_baseline_state(PROJECT)
    data = book(bad_date='30.06.2027')
    corpus.store(PROJECT, data, '2026-11-07', corpus.read(data))
    body = dict(project=PROJECT, source_sha256=hashlib.sha256(data).hexdigest(),
        expected_active_sha256=current['source_sha256'], expected_revision=0, effective_from='2026-11-12')
    original = current['path'].read_bytes()
    preview = post(client, 'schedule/saved-source-preview', **body)
    assert preview.status_code == 200, preview.text
    sha = preview.json()['review']['source_sha256']
    assert post(client, 'schedule/saved-source-approve', **body, expected_prepared_sha256='f'*64).status_code == 409
    assert monitor._working_baseline_state(PROJECT)['revision'] == 0
    saved = post(client, 'schedule/saved-source-approve', **body, expected_prepared_sha256=sha)
    assert saved.status_code == 200, saved.text
    assert saved.json()['saved']['revision'] == 1
    assert current['path'].read_bytes() == original
    assert post(client, 'schedule/saved-source-approve', **body, expected_prepared_sha256=sha).status_code == 409
    assert client.post('/monitor/schedule/saved-source-preview',json={**body,'key':'synthetic-cumulative-owner-key','path':'/etc/passwd'}).status_code == 422
    # Concurrent revisions, including re-used hashes, are checked under lock.
    with pytest.raises(versions.ScheduleVersionConflict, match='Ревизия'):
        versions.approve(monitor._project_dir(PROJECT)/'baseline', monitor._legacy_baseline_file(PROJECT),
            monitor._working_baseline_file(PROJECT).read_bytes(), expected_previous_sha256=sha,
            expected_source_sha256=sha, expected_revision=0, effective_from='2026-11-12')


@pytest.mark.parametrize('changes', [{'project':''}, {'corrections':[{'cell':'G5','expected_raw':None,'value':'2026-11-12','note':'decision'}]*101}])
def test_invalid_metadata_has_private_400_without_reading_a_source(api, monkeypatch, changes):
    client, _ = api
    monkeypatch.setattr(prepare, 'prepare', lambda *a, **k: pytest.fail('source read for invalid metadata'))
    body = dict(project=PROJECT, source_sha256='a'*64, expected_active_sha256='b'*64,
                expected_revision=0, effective_from='2026-11-12')
    body.update(changes)
    response = post(client, 'schedule/saved-source-preview', **body)
    assert response.status_code == 400 and response.headers['cache-control'] == 'private, no-store'


def test_inventory_has_explicit_bounds_and_prepare_does_not_read_unrelated_approved_sources(sources,monkeypatch):
    current,correct_sha=sources
    root=monitor._project_dir(PROJECT)
    for index in range(40):
        day=(dt.date(2026,1,1)+dt.timedelta(days=index)).isoformat()
        # A far archive remains outside a bounded read; this is not an assertion
        # that a source absent from the short inventory is absent from storage.
        (root/'gpr_corpus'/f'{day}.json').write_text(json.dumps(dict(corpus.read(book()),taken_at=day)))
    state=source_state.inspect(PROJECT)
    assert state['incomplete'] and state['omitted_sources']>0
    assert 'прочитана частично' in source_state.render(state)
    assert state['candidates'][0]['selected']
    read=versions._read
    called=[]
    def spy(path):
        called.append(path)
        return read(path)
    monkeypatch.setattr(versions,'_read',spy)
    prepared=prepare.prepare(PROJECT,current['source_sha256'],
        expected_active_sha256=current['source_sha256'],expected_revision=current['revision'])
    assert prepared['data']==current['path'].read_bytes()
    assert all(path==current['path'] for path in called)
    assert prepared['manifest']['scan_incomplete']


def test_native_excel_dates_survive_saved_json_reconstruction_and_explicit_date_correction(sources):
    current,_=sources
    wb=load_workbook(io.BytesIO(book()))
    ws=wb['ГПР']
    dates={'F5':dt.datetime(2026,11,1),'F6':dt.datetime(2026,12,20),
           'G6':dt.datetime(2027,2,1),'I6':dt.datetime(2026,12,1),'J6':dt.datetime(2027,2,1)}
    for cell,value in dates.items():
        ws[cell]=value
    stream=io.BytesIO();wb.save(stream);wb.close()
    raw=stream.getvalue();source=corpus.read(raw)
    saved=corpus.store(PROJECT,raw,'2026-11-08',source)
    path=monitor._project_dir(PROJECT)/'gpr_corpus'/'2026-11-08.json'
    original=path.read_bytes()
    assert saved['packages'][0]['scopes'][0]['raw']['start']=='2026-11-01T00:00:00'
    result=prepare.prepare(PROJECT,source['sha256'],expected_active_sha256=current['source_sha256'],
        expected_revision=current['revision'],corrections=[{'cell':'G5','expected_raw':'31.06.2027',
            'value':'30.06.2027','note':'Explicit synthetic correction'}])
    assert not result['manifest']['original_bytes_verified']
    rebuilt=corpus.as_schedule(corpus.read(result['data']))
    before={w['id']:w for w in corpus.as_schedule(source)['works']}
    after={w['id']:w for w in rebuilt['works']}
    assert before.keys()==after.keys()
    for key in before:
        for field in ['name','object','section','progress','progress_date','source_cells','start']:
            assert before[key][field]==after[key][field]
        if key!='corpus:ГПР!E5':
            assert before[key]['finish']==after[key]['finish']
    assert after['corpus:ГПР!E5']['finish']==dt.date(2027,6,30)
    assert path.read_bytes()==original
    rebuilt_wb=load_workbook(io.BytesIO(result['data']),read_only=True,data_only=False)
    for cell,value in dates.items():
        assert rebuilt_wb['ГПР'][cell].value==value
    rebuilt_wb.close()
