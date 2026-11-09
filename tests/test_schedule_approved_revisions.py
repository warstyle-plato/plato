"""An explicit plan revision preserves old cuts and never inherits equal-ID facts."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import base64
import datetime as dt
import hashlib
import json

import pytest

import developaid_monitor as monitor
import developaid_monitor_manager as manager
import developaid_schedule_gpr_physical as physical
import developaid_schedule_versions as versions
from test_gpr_corpus_baseline import construction_book
from test_monitor_management_gantt import _gpr_book
from test_schedule_gpr_physical import config
from test_schedule_physical import snapshot
from test_monitor_cumulative_api import api, post

PROJECT = 'Учебный пересмотр плана'
TODAY = '2026-11-09'


def book(name='Ранее утверждённая работа', progress=.2):
    return _gpr_book([(1, name, progress, dt.date(2026, 10, 1),
                       dt.date(2026, 12, 1), 'В работе', '2.2.1.1')])


@pytest.fixture(autouse=True)
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, '_SNAPSHOT_DIR', tmp_path)
    monkeypatch.setattr(versions, '_now', lambda: dt.datetime(2026, 11, 9, 12, tzinfo=dt.timezone.utc))
    return tmp_path


def approve(data, day=TODAY, **changes):
    preview = monitor.schedule_version_preview(PROJECT, data, day)
    args = dict(expected_previous_sha256=preview['expected_previous_sha256'],
                expected_source_sha256=preview['source_sha256'])
    args.update(changes)
    return monitor.approve_schedule_version(PROJECT, data, day, **args)


def test_preview_is_read_only_and_explicit_approval_keeps_original_and_past_cuts(storage):
    old, new = book(), construction_book()
    monitor.store_schedule(PROJECT, old, None, '2026-10-01')
    before = {str(p): p.read_bytes() for p in storage.rglob('*') if p.is_file()}
    preview = monitor.schedule_version_preview(PROJECT, new, TODAY)
    assert preview['works'] == 3 and preview['source_format'] == 'corpus-gpr-v1'
    assert before == {str(p): p.read_bytes() for p in storage.rglob('*') if p.is_file()}
    saved = approve(new)
    assert saved['revision'] == 1 and not saved['unchanged']
    assert (monitor._project_dir(PROJECT)/'baseline'/'gpr.xlsx').read_bytes() == old
    assert monitor._baseline_file(PROJECT, '2026-11-08').read_bytes() == old
    assert monitor._baseline_file(PROJECT, TODAY).read_bytes() == new
    assert physical._source(PROJECT, '2026-11-08')['tasks'].keys() == {'1'}
    assert len(physical._source(PROJECT, TODAY)['tasks']) == 3
    assert manager._baseline_status(PROJECT, '2026-11-08')['1']['progress'] == .2
    assert '1' not in manager._baseline_status(PROJECT, TODAY)


def test_stale_review_and_changed_file_fail_without_replacing_a_source(storage):
    monitor.store_schedule(PROJECT, book(), None, '2026-10-01')
    first, second = book('Новая работа'), book('Другая работа')
    review = monitor.schedule_version_preview(PROJECT, first, TODAY)
    with pytest.raises(versions.ScheduleVersionConflict, match='Файл изменился'):
        approve(second, expected_source_sha256=review['source_sha256'])
    approve(first)
    before = (monitor._project_dir(PROJECT)/'baseline'/'schedule_versions.json').read_bytes()
    with pytest.raises(versions.ScheduleVersionConflict, match='другим запросом'):
        approve(second, expected_previous_sha256=review['expected_previous_sha256'])
    assert (monitor._project_dir(PROJECT)/'baseline'/'schedule_versions.json').read_bytes() == before


def test_only_one_concurrent_approval_can_consume_the_same_previous_sha():
    monitor.store_schedule(PROJECT, book(), None, '2026-10-01')
    first, second = book('Новая работа'), book('Другая работа')
    previous = monitor.schedule_version_preview(PROJECT, first, TODAY)['expected_previous_sha256']
    def run(data):
        try:
            approve(data, expected_previous_sha256=previous)
            return 'saved'
        except versions.ScheduleVersionConflict:
            return 'stale'
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(run, [first, second])) == ['saved', 'stale']
    assert len(monitor._baseline_state(PROJECT)['versions']) == 1


def test_one_read_keeps_one_source_while_another_worker_commits_a_new_version():
    old, new = book(), construction_book()
    monitor.store_schedule(PROJECT, old, None, '2026-10-01')
    @monitor.approved_schedule_read
    def read():
        assert monitor._baseline_file(PROJECT, TODAY).read_bytes() == old
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(approve, new).result()
        assert monitor._baseline_file(PROJECT, TODAY).read_bytes() == old
        assert manager._baseline_status(PROJECT, TODAY)['1']['progress'] == .2
    read()
    assert monitor._baseline_file(PROJECT, TODAY).read_bytes() == new


def test_a_revision_cannot_rewrite_past_cuts_and_a_future_plan_waits_for_its_date():
    old, new = book(), construction_book()
    monitor.store_schedule(PROJECT, old, None, '2026-10-01')
    with pytest.raises(ValueError, match='прежние срезы'):
        approve(new, '2026-11-08')
    approve(new, '2026-11-12')
    assert monitor._baseline_file(PROJECT, '2026-11-11').read_bytes() == old
    assert monitor._baseline_file(PROJECT, '2026-11-12').read_bytes() == new
    assert monitor._baseline_file(PROJECT).read_bytes() == old


def test_same_id_manual_and_weekly_facts_cannot_cross_a_plan_revision(storage):
    old, new = book(), book('Другая работа с тем же номером', .1)
    monitor.store_schedule(PROJECT, old, None, '2026-10-01')
    monitor.store_work_fact(PROJECT, [{'id':'1', 'progress': .9}], '2026-11-08')
    monitor.store_schedule_fact(PROJECT, book(progress=.8), '2026-11-08')
    files = {str(p): p.read_bytes() for p in storage.rglob('*') if p.is_file() and 'work_fact' in str(p)}
    approve(new)
    assert files == {str(p): p.read_bytes() for p in storage.rglob('*') if p.is_file() and 'work_fact' in str(p)}
    assert manager._baseline_status(PROJECT, '2026-11-08')['1']['progress'] == .9
    assert manager._baseline_status(PROJECT, TODAY)['1']['progress'] == .1
    with pytest.raises(ValueError, match='план изменился'):
        monitor.store_work_fact(PROJECT, [{'id':'1', 'progress': .3}], TODAY)
    monitor.store_work_fact(PROJECT, [{'id':'1', 'progress': .3}], TODAY,
                            expected_source_sha256=hashlib.sha256(new).hexdigest())
    assert manager._baseline_status(PROJECT, TODAY)['1']['progress'] == .3
    assert monitor.work_facts(PROJECT, '2026-11-08')['1']['progress'] == .9


def test_legacy_unbound_facts_are_confined_to_the_legacy_source():
    monitor.store_schedule(PROJECT, book(), None, '2026-10-01')
    folder = monitor._project_dir(PROJECT)/'work_fact'
    folder.mkdir()
    (folder/'2026-11-08.json').write_text(json.dumps({'rows':[{'id':'1','progress':.9}]}))
    assert manager._baseline_status(PROJECT, '2026-11-08')['1']['progress'] == .9
    approve(book('Другая работа', .1))
    assert manager._baseline_status(PROJECT, TODAY)['1']['progress'] == .1


def test_weekly_equal_ids_do_not_authorize_another_work_definition():
    old, new = book(), book('Другая работа', .1)
    monitor.store_schedule(PROJECT, old, None, '2026-10-01')
    approve(new)
    sha = hashlib.sha256(new).hexdigest()
    with pytest.raises(ValueError, match='другому составу'):
        monitor.store_schedule_fact(PROJECT, old, TODAY, expected_source_sha256=sha)
    monitor.store_schedule_fact(PROJECT, book('Другая работа', .3), TODAY,
                               expected_source_sha256=sha)
    assert manager._baseline_status(PROJECT, TODAY)['1']['progress'] == .3


def test_saved_ks_binding_is_retained_but_not_reassigned_to_a_new_equal_id(monkeypatch, storage):
    monitor.store_schedule(PROJECT, book(), None, '2026-10-01')
    snap = snapshot()
    monkeypatch.setattr(physical.ledgers, 'latest_snapshot', lambda project, cut='': snap)
    monkeypatch.setattr(physical, '_now', lambda: dt.datetime(2026,11,6,12,tzinfo=dt.timezone.utc))
    state = physical.catalog(PROJECT, '2026-11-06')
    physical.save(PROJECT, **{key:state[key] for key in ('source_kind','source_sha256','snapshot_id','revision')},
                  configuration=config())
    before = {str(p):p.read_bytes() for p in storage.rglob('gpr_physical_links/*.json')}
    approve(book('Другой фасад с тем же номером'))
    after = physical.catalog(PROJECT, TODAY)
    assert after['source_changed'] and not after['model']['physical_evidence']
    assert before == {str(p):p.read_bytes() for p in storage.rglob('gpr_physical_links/*.json')}
    assert physical.catalog(PROJECT, '2026-11-08')['model']['physical_evidence']


def test_corrupt_approved_bytes_and_broken_chain_fail_closed():
    monitor.store_schedule(PROJECT, book(), None, '2026-10-01')
    approve(book('Новая работа'))
    path = monitor._baseline_file(PROJECT, TODAY)
    path.write_bytes(book('Подмена'))
    with pytest.raises(ValueError, match='Отпечаток'):
        monitor._baseline_file(PROJECT, TODAY)
    assert monitor._baseline_file(PROJECT, '2026-11-08') is not None


def test_initial_upload_is_still_immutable_and_source_only_is_not_approval():
    old = book()
    monitor.store_schedule(PROJECT, old, None, '2026-10-01')
    monitor.store_schedule_fact(PROJECT, construction_book(), TODAY)
    assert monitor._baseline_file(PROJECT, TODAY).read_bytes() == old
    with pytest.raises(FileExistsError):
        monitor.store_schedule(PROJECT, construction_book(), None, TODAY)


@pytest.mark.parametrize('path', ['version-preview', 'version-approve'])
@pytest.mark.parametrize('key,session', [('', ''), ('wrong', ''), ('', 'telegram'), ('market', 'demo')])
def test_version_api_admission_precedes_source_reads(api, monkeypatch, path, key, session):
    client, _ = api
    monkeypatch.setattr(monitor, 'schedule_version_preview', lambda *_: pytest.fail('read before admission'))
    response = post(client, 'schedule/'+path, key=key, session=session, project=PROJECT,
                    effective_from=TODAY, gpr_base64='bm90LWEtZmlsZQ==',
                    expected_previous_sha256='a'*64, expected_source_sha256='b'*64)
    assert response.status_code == 403
    assert response.headers['cache-control'] == 'private, no-store'


def test_api_preview_and_exact_approval_apply_to_an_existing_project(api):
    client, _ = api
    old, new = book(), construction_book()
    monitor.store_schedule(PROJECT, old, None, '2026-10-01')
    body = dict(project=PROJECT, effective_from=TODAY, gpr_base64=base64.b64encode(new).decode())
    review = post(client, 'schedule/version-preview', **body)
    assert review.status_code == 200 and review.json()['works'] == 3
    assert monitor._baseline_file(PROJECT).read_bytes() == old
    response = post(client, 'schedule/version-approve', **body,
                    expected_previous_sha256=review.json()['expected_previous_sha256'],
                    expected_source_sha256=review.json()['source_sha256'])
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'private, no-store'
    assert monitor._baseline_file(PROJECT, TODAY).read_bytes() == new
    assert monitor._baseline_file(PROJECT, '2026-11-08').read_bytes() == old
    changed_bytes = book('Другой файл')
    changed = dict(body, gpr_base64=base64.b64encode(changed_bytes).decode())
    stale = post(client, 'schedule/version-approve', **changed,
                 expected_previous_sha256=review.json()['expected_previous_sha256'],
                 expected_source_sha256=hashlib.sha256(changed_bytes).hexdigest())
    assert stale.status_code == 409


def test_corpus_view_keeps_one_selected_plan_across_another_workers_approval(api, monkeypatch):
    client, _ = api
    monitor.store_schedule(PROJECT, book(), None, '2026-10-01')
    new = construction_book()
    original = monitor._baseline_file
    switched = []

    def select_then_approve(project, cut=''):
        selected = original(project, cut)
        if not switched:
            switched.append(True)
            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(approve, new).result()
        return selected

    monkeypatch.setattr(monitor, '_baseline_file', select_then_approve)
    first = post(client, 'gpr-corpus/view', project=PROJECT, cut=TODAY)
    assert first.status_code == 200
    assert first.json() == {'source': None, 'html': ''}
    assert first.headers['cache-control'] == 'private, no-store'
    next_read = post(client, 'gpr-corpus/view', project=PROJECT, cut=TODAY)
    assert next_read.status_code == 200
    assert next_read.json()['source']['sha256'] == hashlib.sha256(new).hexdigest()
    assert next_read.json()['source']['baseline_approved']
    assert next_read.json()['source']['working_source_state'] == 'approved'


@pytest.mark.parametrize('width', [390, 1440])
def test_real_page_reviews_exact_bytes_before_showing_explicit_approval(width):
    from playwright.sync_api import expect
    from test_monitor_cumulative_controls import browser_page
    data = construction_book()
    sha = hashlib.sha256(data).hexdigest()
    with browser_page(width) as (page, responses, errors):
        calls = []
        def handle(route):
            body = route.request.post_data_json
            calls.append((route.request.url, body))
            if route.request.url.endswith('version-preview'):
                route.fulfill(json={'works':3, 'source_sha256':sha,
                                    'expected_previous_sha256':'a'*64, 'requires_initial_baseline':False})
            else:
                route.fulfill(json={'revision':1})
        page.route('**/monitor/schedule/version-*', handle)
        page.locator('#dataTab').click()
        if 'open' not in (page.locator('#setupCard').get_attribute('class') or ''):
            page.locator('#setupHead').click()
        page.locator('#baselineDate').fill(TODAY)
        page.locator('#gpr').set_input_files({'name':'Approved.xlsx', 'mimeType':
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'buffer':data})
        expect(page.locator('#baselineApproveBtn')).to_be_hidden()
        page.locator('#baselinePreviewBtn').click()
        expect(page.locator('#baselineApproveBtn')).to_be_visible()
        expect(page.locator('#baselineMsg')).to_contain_text('работ 3')
        assert len(calls) == 1 and base64.b64decode(calls[0][1]['gpr_base64']) == data
        page.locator('#baselineApproveBtn').click()
        expect(page.locator('#baselineApproveBtn')).to_be_hidden()
        expect(page.locator('#baselineMsg')).to_contain_text('версия утверждена')
        assert len(calls) == 2
        assert calls[1][1]['expected_source_sha256'] == sha
        assert calls[1][1]['expected_previous_sha256'] == 'a'*64
        assert base64.b64decode(calls[1][1]['gpr_base64']) == data
        assert not errors


def test_real_page_discards_a_review_when_project_or_file_changes():
    from playwright.sync_api import expect
    from test_monitor_cumulative_controls import browser_page
    with browser_page(390) as (page, responses, errors):
        calls = []
        def handle(route):
            calls.append(route.request.url)
            route.fulfill(json={'works':3, 'source_sha256':'b'*64,
                                'expected_previous_sha256':'a'*64, 'requires_initial_baseline':False})
        page.route('**/monitor/schedule/version-*', handle)
        page.locator('#dataTab').click()
        if 'open' not in (page.locator('#setupCard').get_attribute('class') or ''):
            page.locator('#setupHead').click()
        page.locator('#gpr').set_input_files({'name':'Approved.xlsx', 'mimeType':
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'buffer':construction_book()})
        page.locator('#baselinePreviewBtn').click()
        expect(page.locator('#baselineApproveBtn')).to_be_visible()
        page.locator('#project').fill('Другой проект')
        expect(page.locator('#baselineApproveBtn')).to_be_hidden()
        assert len(calls) == 1 and not errors
