"""Version, historical-cut and concurrency counterexamples for PM confirmation."""
import concurrent.futures
import copy
import datetime as dt
import hashlib
import json

import pytest

import developaid_monitor as monitor
import developaid_monitor_pace as pace
import developaid_monitor_schedule_graph as graph
import developaid_schedule_confirmation as confirmation
import developaid_schedule_timeline as timeline
from test_schedule_dependency_timeline import day, network


@pytest.fixture
def source(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, '_SNAPSHOT_DIR', tmp_path)
    monkeypatch.setattr(confirmation, '_now', lambda: dt.datetime(2026, 11, 6, 12, tzinfo=dt.timezone.utc))
    path = monitor._project_dir('Учебный проект') / 'baseline' / 'pm.xlsx'
    path.parent.mkdir(parents=True)
    path.write_bytes(b'synthetic PM version one')
    return path


def save(project='Учебный проект', **changes):
    state = confirmation.view(project)
    args = {key: state[key] for key in ['source_sha256', 'revision']}
    args.update(calendar_basis='calendar_days', rnv_chain_complete=True, note='Проверил Иван по календарю и перечню этапов.')
    args.update(changes)
    return confirmation.save(project, **args)


def test_missing_is_unknown_and_confirmation_survives_a_fresh_read(source):
    state = confirmation.view('Учебный проект')
    assert state['calendar_basis'] == 'unconfirmed' and state['rnv_chain_complete'] is False
    assert state['revision'] == 0
    saved = save()
    assert saved == confirmation.view('Учебный проект')
    assert saved['source_sha256'] == hashlib.sha256(source.read_bytes()).hexdigest()
    pm = dict(network(), source_sha256=saved['source_sha256'])
    qualified = confirmation.qualify('Учебный проект', pm, '2026-11-06')
    assert qualified['calendar_confirmed'] and qualified['rnv_chain_complete']
    assert not confirmation.view('Другой проект')['rnv_chain_complete']


def test_confirmation_cannot_travel_back_in_time_or_to_another_source(source, monkeypatch):
    saved = save()
    assert not confirmation.view('Учебный проект', '2026-11-05')['rnv_chain_complete']
    assert not confirmation.view('Учебный проект', '2026-11-05')['can_edit']
    source.write_bytes(b'synthetic PM version two')
    changed = confirmation.view('Учебный проект')
    assert changed['calendar_basis'] == 'unconfirmed' and not changed['rnv_chain_complete']
    with pytest.raises(confirmation.ConfirmationProblem, match='изменились'):
        save(source_sha256=saved['source_sha256'])
    # A PM object parsed before a simultaneous replacement remains tied to its
    # actual bytes, not to whichever file happens to be current at read time.
    pm = dict(network(), source_sha256=changed['source_sha256'])
    assert not confirmation.qualify('Учебный проект', pm, '2026-11-06')['calendar_confirmed']


def test_revocation_is_an_event_and_old_cut_keeps_its_original_state(source, monkeypatch):
    first = save()
    monkeypatch.setattr(confirmation, '_now', lambda: dt.datetime(2026, 11, 7, 8, tzinfo=dt.timezone.utc))
    removed = save(calendar_basis='unconfirmed', rnv_chain_complete=False, note='Календарь требует сверки.')
    assert removed['revision'] == first['revision'] + 1
    assert not confirmation.view('Учебный проект')['rnv_chain_complete']
    assert confirmation.view('Учебный проект', '2026-11-06')['rnv_chain_complete']
    assert len(list((source.parent.parent / 'schedule_confirmations').glob('*.json'))) == 2


@pytest.mark.parametrize('change', [dict(calendar_basis='working_days'), dict(note='   '), dict(rnv_chain_complete='false')])
def test_unsupported_calendar_or_implicit_confirmation_is_rejected(source, change):
    with pytest.raises(confirmation.ConfirmationProblem):
        save(**change)
    assert confirmation.view('Учебный проект')['revision'] == 0


def test_simultaneous_editors_cannot_overwrite_each_other(source):
    def attempt(_):
        try:
            return save(revision=0)['revision']
        except confirmation.ConfirmationProblem as exc:
            return exc.status
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt, range(2))) == [1, 409]


def test_corrupt_latest_event_never_restores_older_confirmation(source):
    save()
    saved = save(calendar_basis='unconfirmed', rnv_chain_complete=False)
    path = source.parent.parent / 'schedule_confirmations' / '000000000002.json'
    event = json.loads(path.read_text())
    event['rnv_chain_complete'] = 'false'
    path.write_text(json.dumps(event))
    with pytest.raises(ValueError):
        confirmation.view('Учебный проект')
    got = confirmation.qualify('Учебный проект', dict(network(), source_sha256=saved['source_sha256']), '2026-11-06')
    assert not got['calendar_confirmed'] and not got['rnv_chain_complete']
    assert any('не удалось прочитать' in reason for reason in got['validation_issues'])


def test_calendar_confirmation_does_not_turn_cost_proxy_into_physical_rnv(source, monkeypatch):
    saved = save()
    pm = dict(network(), source_sha256=saved['source_sha256'])
    monkeypatch.setattr(graph, '_load_pm', lambda _: copy.deepcopy(pm))
    view = {'schedule': {'rows': [{'id': '1', 'name': 'РД', 'plan_start': '2026-11-01',
            'plan_finish': '2026-11-20', 'rss_accepted_ratio': .25, 'rss_act_cost_rate_3m': .5}],
            'management': []}, 'dashboard': {'schedule': {}}}
    got = pace._apply_pace('Учебный проект', view, day('2026-11-06'))
    block = got['schedule']['dependency_timeline']
    assert block['confirmation']['rnv_chain_complete']
    assert block['rnv']['forecast'] is None and block['rnv']['state'] == 'partial'
    assert 'Натуральная выработка КС' in ' '.join(block['rnv']['reasons'])
    assert not any('календарь не подтверждён' in reason for reason in block['rnv']['reasons'])
    assert got['dashboard']['schedule']['qualified_rnv'] == block['rnv']


def test_confirmed_calendar_cannot_hide_cycle_or_missing_milestone(source):
    saved = save()
    pm = dict(network(), source_sha256=saved['source_sha256'])
    pm['rnv_id'] = ''
    qualified = confirmation.qualify('Учебный проект', pm, '2026-11-06')
    assert timeline.model(qualified, {'1': day('2026-12-10')}, evidence=True)['rnv']['state'] == 'unknown'
    pm['rnv_id'] = '4'
    pm['tasks']['1']['predecessors'] = [{'id': '4', 'type': 'FS', 'lag_days': 0}]
    qualified = confirmation.qualify('Учебный проект', pm, '2026-11-06')
    assert timeline.model(qualified, {'1': day('2026-12-10')}, evidence=True)['rnv']['state'] == 'unknown'


def test_pm_cache_and_confirmation_track_bytes_even_when_size_and_mtime_are_kept(source, monkeypatch):
    import os
    stamp = source.stat()
    def parse(path, *, data):
        return dict(network(), source_sha256=hashlib.sha256(data).hexdigest())
    monkeypatch.setattr(graph, '_read_pm', parse)
    before = graph._load_pm('Учебный проект')
    save()
    source.write_bytes(b'x' * stamp.st_size)
    os.utime(source, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    after = graph._load_pm('Учебный проект')
    assert after['source_sha256'] != before['source_sha256']
    assert not confirmation.qualify('Учебный проект', after, '2026-11-06')['calendar_confirmed']


def test_confirmation_provenance_is_shared_by_monitor_and_report_and_escaped(source):
    import developaid_management_report as report
    saved = save(note='<img src=x onerror=alert(1)>')
    pm = confirmation.qualify('Учебный проект', dict(network(), source_sha256=saved['source_sha256']), '2026-11-06')
    block = timeline.model(pm, {'1': day('2026-12-10')}, evidence=True)
    markup = timeline.render(block, context='report')
    assert '&lt;img' in markup and '<img' not in markup
    assert '06.11.2026' in markup
    assert markup in report._gantt_html({'gantt': {'state': 'missing', 'dependency_timeline': block}})


def test_failed_publish_preserves_previous_event_and_removes_temporary_file(source, monkeypatch):
    first = save()
    def fail(*args):
        raise OSError('synthetic interrupted disk write')
    monkeypatch.setattr(confirmation.os, 'replace', fail)
    with pytest.raises(OSError):
        save(calendar_basis='unconfirmed', rnv_chain_complete=False)
    assert confirmation.view('Учебный проект') == first
    folder = source.parent.parent / 'schedule_confirmations'
    assert len(list(folder.glob('*.json'))) == 1
    assert not list(folder.glob('.event-*'))


def test_real_pm_parser_reports_hash_of_the_bytes_it_read(source):
    from openpyxl import Workbook
    wb = Workbook()
    sheet = wb.active
    sheet.append(['ИД', 'Название задачи', 'Начало', 'Окончание', 'Предшественники'])
    sheet.append([1, 'Учебный этап', day('2026-11-01'), day('2026-11-10'), ''])
    sheet.append([2, 'Получение РНВ', day('2026-11-10'), day('2026-11-20'), '1'])
    wb.save(source)
    pm = graph._load_pm('Учебный проект')
    assert pm['source_sha256'] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert pm['rnv_id'] == '2' and len(pm['tasks']) == 2
