"""An explicitly approved corpus plan keeps source pairs and observation dates."""
from __future__ import annotations

import datetime as dt
import hashlib
import io

import pytest
from openpyxl import load_workbook

import developaid_gpr_corpus as corpus
import developaid_monitor as monitor
import developaid_schedule_gpr_forecast as forecast
import developaid_schedule_gpr_physical as physical
from test_gpr_corpus_preview import book
from test_monitor_management_gantt import _gpr_book

PROJECT = 'Учебный корпусный план'


def construction_book():
    wb = load_workbook(io.BytesIO(book()))
    ws = wb['ГПР']
    # A heading can have a residual name cell. Its own label is authoritative.
    ws['A4'] = 'Фасады'
    ws['B4'] = 'Оставшаяся подпись другого раздела'
    ws['B5'] = 'Монтаж НВФ'
    ws['C5'] = 'СМР'
    stream = io.BytesIO(); wb.save(stream)
    return stream.getvalue()


@pytest.fixture(autouse=True)
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, '_SNAPSHOT_DIR', tmp_path)


def test_residual_name_does_not_hide_a_non_numeric_group_heading():
    parsed = corpus.read(construction_book())
    assert [p['group'] for p in parsed['packages']] == ['Фасады', 'Фасады']
    assert parsed['packages'][0]['group_source'] == {'name': 'Фасады', 'source_row': 4, 'cell': 'A4'}
    schedule = corpus.as_schedule(parsed)
    assert len(schedule['works']) == 3
    assert len({w['id'] for w in schedule['works']}) == 3
    assert all(w['construction_work'] and not w['wbs'] and not w['estimate_code'] for w in schedule['works'])
    first = schedule['works'][0]
    assert first['object'] == 'КОРПУС 1' and first['progress'] == .25
    assert first['start'] == dt.date(2026, 11, 1) and first['finish'] is None
    assert first['progress_date'] == '2026-11-06'
    assert first['source_cells'] == {'progress': 'E5', 'start': 'F5', 'finish': 'G5'}
    assert all(w['object'] != 'ПАРКИНГ' for w in schedule['works'])  # zero without dates is not applicability
    assert parsed['packages'][0]['scopes'][0]['raw']['finish'] == '31.06.2027'


def test_only_explicit_baseline_upload_approves_corpus_pairs_and_preserves_raw_bytes():
    data = construction_book()
    before = hashlib.sha256(data).hexdigest()
    saved = monitor.store_schedule(PROJECT, data, None, '2026-11-09')
    assert saved['works'] == 3 and saved['baseline']
    assert monitor._baseline_file(PROJECT).read_bytes() == data
    source = physical._source(PROJECT, '2026-11-09')
    assert source['state'] == 'approved_gpr' and source['source_sha256'] == before
    assert len(source['tasks']) == 3 and len(source['calendar_missing']) == 1
    view = corpus.for_view(PROJECT, '2026-11-09', baseline_sha256=before)
    assert view['baseline_approved'] and view['working_source_state'] == 'approved'
    assert 'используется как утверждённый' in corpus.render_overview(view, '2026-11-09')
    with pytest.raises(FileExistsError):
        monitor.store_schedule(PROJECT, data, None, '2026-11-09')


def test_header_observation_date_is_not_replaced_by_upload_date():
    monitor.store_schedule(PROJECT, construction_book(), None, '2026-11-09')
    points = forecast.history(PROJECT, dt.date(2026, 11, 9))
    assert {point[0] for values in points.values() for point in values} == {dt.date(2026, 11, 6)}
    assert forecast.history(PROJECT, dt.date(2026, 11, 8)) == {}  # approved version unavailable at this cut
    assert corpus.for_view(PROJECT, '2026-11-08', baseline_sha256='a'*64) is None
    with pytest.raises(ValueError, match='раньше даты факта'):
        monitor.store_schedule('Другой проект', construction_book(), None, '2026-11-05')
    assert monitor._baseline_file('Другой проект') is None


def test_stored_source_only_corpus_does_not_silently_replace_an_existing_wbs_plan():
    data = _gpr_book([(1, 'Ранее утверждённая работа', .2, dt.date(2026, 10, 1),
                      dt.date(2026, 12, 1), 'В работе', '2.2.1.1')])
    monitor.store_schedule(PROJECT, data, None, '2026-10-01')
    monitor.store_schedule_fact(PROJECT, construction_book(), '2026-11-09')
    source = physical._source(PROJECT, '2026-11-09')
    assert set(source['tasks']) == {'1'} and source['source_sha256'] == hashlib.sha256(data).hexdigest()
    assert 'другую версию' in source['reason']
    visible = corpus.for_view(PROJECT, '2026-11-09', baseline_sha256=source['source_sha256'])
    assert visible['working_source_state'] == 'different_baseline' and not visible['baseline_approved']
    html = corpus.render_overview(visible, '2026-11-09')
    assert 'показания ниже уже доступны' in html and '31.06.2027' in html


def test_invalid_construction_dates_block_a_complete_rnv_estimate_without_hiding_known_progress():
    import developaid_monitor_page  # installs the real Monitor reader stack
    monitor.store_schedule(PROJECT, construction_book(), None, '2026-11-09')
    view = monitor.build(PROJECT, '2026-11-09')
    schedule = view['schedule']
    assert len(schedule['rows']) == 2
    assert [r['actual_progress'] for r in schedule['rows']] == [0, .5]
    assert {r['progress_source']['date'] for r in schedule['rows']} == {'2026-11-06'}
    assert all(r['construction_work'] for r in schedule['rows'])
    qualification = schedule['dependency_timeline']['rnv']
    assert qualification['state'] == 'partial' and qualification['forecast'] is None
    assert qualification['indicative_forecast'] == '2027-02-01'
    assert any('даты неполны' in reason for reason in qualification['reasons'])
    source = schedule['corpus_gpr']
    assert source['baseline_approved'] and source['packages'][0]['scopes'][0]['progress'] == .25
    assert '31.06.2027' in schedule['corpus_gpr_html']


@pytest.mark.parametrize('package,part', [
    ('Монолит надземной части', 'Устройство монолитных железобетонных вертикальных конструкций 3-го этажа'),
    ('ИТП', 'Монтаж ИТП. Тепломеханическая часть'),
    ('Монтаж НВФ', 'Устройство отделки фасадов (вертикальная часть)'),
])
def test_a_found_package_component_is_a_candidate_and_never_the_whole_package_percent(package, part):
    import developaid_gpr_cumulative_matching as matching
    from test_gpr_cumulative_matching import source, snapshot, task
    plan = source(task('package', corpus=4, name=package, source_format='corpus-gpr-v1'))
    snap = snapshot(corpus=4)
    snap['ledgers'][0]['items'][0].update(name=part, scope='Корпус 4')
    result = matching.suggest(plan, snap, '2026-11-06')
    assert result['bindings'] == {} and result['cohorts'] == []
    assert result['configuration']['tasks'] == []
    assert result['candidates'][0]['candidate_task_ids'] == ['package']
