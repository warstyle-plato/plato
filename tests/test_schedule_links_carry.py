"""A new plan version keeps verified KS links only for works defined the same way."""
import copy
import datetime as dt
import hashlib
import io

import pytest
from openpyxl import load_workbook

import developaid_monitor as monitor
import developaid_schedule_gpr_physical as physical
import developaid_schedule_versions as versions
from test_monitor_management_gantt import _gpr_book
from test_schedule_physical import snapshot

PROJECT = 'Учебный перенос привязок'
OLD_DAY, TODAY = '2026-11-08', '2026-11-09'
FACADE, ROOF = 'Фасад корпуса', 'Кровля корпуса'


def book(rows=((1, FACADE), (2, ROOF)), finish='2028-01-01', progress=.3, cells=None):
    blob = _gpr_book([(rid, name, progress, dt.date(2026, 10, 1), dt.date.fromisoformat(finish),
                       'В работе', '2.2.1.%d' % rid) for rid, name in rows])
    if not cells:
        return blob
    data = load_workbook(io.BytesIO(blob))
    for ref, value in cells.items():
        data.active[ref] = value
    out = io.BytesIO()
    data.save(out)
    return out.getvalue()


@pytest.fixture
def site(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, '_SNAPSHOT_DIR', tmp_path)
    monkeypatch.setattr(versions, '_now', lambda: dt.datetime(2026, 11, 9, 12, tzinfo=dt.timezone.utc))
    monkeypatch.setattr(physical, '_now', lambda: dt.datetime(2026, 11, 8, 12, tzinfo=dt.timezone.utc))
    source = book()
    monitor.store_schedule(PROJECT, source, None, '2026-11-01')
    archive = {'current': snapshot()}
    monkeypatch.setattr(physical.ledgers, 'effective_snapshot',
                        lambda project, cut='', snapshot=None: copy.deepcopy(snapshot or archive['current']))
    monkeypatch.setattr(physical.ledgers, 'read_snapshot', lambda project, sid: copy.deepcopy(archive[sid]))
    archive[archive['current']['snapshot_id']] = archive['current']
    return tmp_path, archive, source


def config(finish=''):
    return {'tasks': [{'task_id': '1', 'mode': 'completed' if finish else 'quantities', 'scope_confirmed': True,
                       'actual_finish': finish},
                      {'task_id': '2', 'mode': 'plan_duration', 'scope_confirmed': True, 'actual_finish': ''}],
            'components': [] if finish else [{'task_id': '1', 'component_id': 'Полный объём', 'item_ids': ['0:0']}],
            'note': 'Проверены работа, участок и полный состав.'}


def save(cut, configuration):
    state = physical.catalog(PROJECT, cut)
    return physical.save(PROJECT, **{k: state[k] for k in
        ('source_kind', 'source_sha256', 'snapshot_id', 'revision')}, configuration=configuration)


def approve(data):
    preview = monitor.schedule_version_preview(PROJECT, data, TODAY)
    return monitor.approve_schedule_version(PROJECT, data, TODAY,
        expected_previous_sha256=preview['expected_previous_sha256'],
        expected_source_sha256=preview['source_sha256'])


def journal(site):
    return {str(p): p.read_bytes() for p in site[0].rglob('gpr_physical_links/*.json')}


def test_identical_works_keep_links_with_new_dates_until_saved_under_the_new_version(site, monkeypatch):
    save(OLD_DAY, config())
    before = journal(site)
    new = book(finish='2027-03-01', progress=.6)
    approve(new)
    state = physical.catalog(PROJECT, TODAY)
    assert state['source_sha256'] == hashlib.sha256(new).hexdigest()
    assert state['binding_carried_from_source_sha256'] == hashlib.sha256(site[2]).hexdigest()
    assert not state['source_changed'] and state['binding_not_carried'] == []
    assert [t['task_id'] for t in state['configuration']['tasks']] == ['1', '2']
    assert state['model']['physical_evidence'] and state['model']['tasks'][0]['progress'] is not None
    assert journal(site) == before
    built = physical.build(PROJECT, TODAY)
    assert built['evidence_status']['state'] != 'source_changed'
    assert built['binding_carried_from_source_sha256'] == state['binding_carried_from_source_sha256']
    monkeypatch.setattr(physical, '_now', lambda: dt.datetime(2026, 11, 9, 12, tzinfo=dt.timezone.utc))
    save(TODAY, state['configuration'])
    saved = physical.catalog(PROJECT, TODAY)
    assert saved['binding_carried_from_source_sha256'] is None and saved['recorded_at'][:10] == TODAY
    assert physical._history(PROJECT)[-1]['source_sha256'] == state['source_sha256']


@pytest.mark.parametrize('change,cells,rows,reason', [
    ('renamed', {'E5': 'Фасад с новой отделкой'}, None, 'изменились название'),
    ('moved', {'D5': 'Корпус 2'}, None, 'изменились название, объект'),
    ('section', {'C5': 'Наружные сети'}, None, 'раздел'),
    ('wbs', {'B5': '9'}, None, 'WBS'),
    ('missing', None, ((3, 'Другая работа'), (2, ROOF)), 'Работы нет'),
])
def test_changed_or_missing_work_is_named_and_not_carried(site, change, cells, rows, reason):
    save(OLD_DAY, config())
    approve(book(rows or ((1, FACADE), (2, ROOF)), cells=cells))
    state = physical.catalog(PROJECT, TODAY)
    assert [t['task_id'] for t in state['configuration']['tasks']] == ['2']
    assert state['configuration']['components'] == []
    skipped, = state['binding_not_carried']
    assert skipped['task_id'] == '1' and reason in skipped['reason']


def test_nothing_carried_stays_a_changed_source_with_the_reason(site):
    one = {'tasks': [config()['tasks'][0]], 'components': config()['components'], 'note': 'Проверено.'}
    save(OLD_DAY, one)
    approve(book(cells={'E5': 'Фасад с новой отделкой'}))
    state = physical.catalog(PROJECT, TODAY)
    assert state['source_changed'] and state['binding_carried_from_source_sha256'] is None
    assert physical.build(PROJECT, TODAY)['evidence_status']['state'] == 'source_changed'
    assert state['binding_not_carried'][0]['name'] == 'Фасад с новой отделкой'


def test_explicit_revoke_carries_nothing(site):
    save(OLD_DAY, config())
    save(OLD_DAY, {'tasks': [], 'components': [], 'note': 'Привязки сняты.'})
    approve(book(finish='2027-03-01'))
    state = physical.catalog(PROJECT, TODAY)
    assert state['source_changed'] and state['binding_carried_from_source_sha256'] is None
    assert state['configuration']['tasks'] == [] and state['binding_not_carried'] == []


def positioned(snap):
    snap['ledgers'][0]['customer'] = 'ООО «Учебный заказчик»'
    snap['ledgers'][0]['items'][0]['position'] = '1.1'
    return snap


def test_a_new_archive_reuses_the_position_check(site):
    archive = site[1]
    positioned(archive['current'])
    save(OLD_DAY, config())
    moved = positioned(snapshot())
    moved['snapshot_id'] = TODAY + '-' + 'c' * 64
    archive['current'] = archive[moved['snapshot_id']] = moved
    approve(book(finish='2027-03-01'))
    state = physical.catalog(PROJECT, TODAY)
    assert state['snapshot_id'] == moved['snapshot_id'] and state['binding_carried_from_source_sha256']
    assert state['configuration']['components'][0]['item_ids'] == ['0:0']
    assert state['binding_projection_unresolved_tasks'] == []
    moved['ledgers'][0]['items'][0]['name'] = 'Совсем другая позиция'
    state = physical.catalog(PROJECT, TODAY)
    assert state['configuration']['components'] == []
    assert state['binding_projection_unresolved_tasks'] == ['1']


def test_work_confirmed_in_two_versions_is_one_completed_fact(site, monkeypatch):
    save(OLD_DAY, config('2026-11-05'))
    approve(book(finish='2027-03-01'))
    monkeypatch.setattr(physical, '_now', lambda: dt.datetime(2026, 11, 9, 12, tzinfo=dt.timezone.utc))
    save(TODAY, config('2026-11-07'))
    facts = physical.catalog(PROJECT, TODAY)['model']['completed_facts']
    fact, = facts['qualified_task_completions']
    assert facts['counts']['confirmed_works'] == 1 and fact['actual_finish'] == '2026-11-05'


def test_a_later_partial_reading_in_the_new_version_removes_the_old_hundred_percent(site, monkeypatch):
    save(OLD_DAY, config('2026-11-05'))
    approve(book(finish='2027-03-01'))
    assert physical.catalog(PROJECT, TODAY)['model']['completed_facts']['counts']['confirmed_works'] == 1
    site[1]['current']['ledgers'][0]['items'][0].update(completed_quantity=60, periods=[])
    monkeypatch.setattr(physical, '_now', lambda: dt.datetime(2026, 11, 9, 12, tzinfo=dt.timezone.utc))
    save(TODAY, config())
    assert physical.catalog(PROJECT, TODAY)['model']['tasks'][0]['progress'] == pytest.approx(.6)
    assert physical.catalog(PROJECT, TODAY)['model']['completed_facts']['qualified_task_completions'] == []
    assert physical.catalog(PROJECT, OLD_DAY)['model']['completed_facts']['counts']['confirmed_works'] == 1


def test_real_page_says_what_was_carried_and_what_was_not(site):
    from test_monitor_cumulative_controls import browser_page
    save(OLD_DAY, config())
    approve(book(rows=((1, FACADE), (2, ROOF)), cells={'E6': 'Кровля с утеплением'}))
    import json
    state = json.loads(json.dumps(physical.catalog(PROJECT, TODAY), default=str, ensure_ascii=False))
    with browser_page(390) as (page, responses, errors):
        text = page.evaluate('s=>{renderPhysicalSchedule(s);return document.getElementById("physicalScheduleState").textContent}', state)
        assert 'перенесены привязки работ, у которых не изменились код, название, объект, раздел и WBS: 1.' in text
        assert 'Не перенесены с прежней версии (1): «Кровля с утеплением» — В новой версии ГПР изменились' in text
        assert not errors
