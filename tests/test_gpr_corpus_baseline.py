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
    assert {node['name'] for node in schedule['management']} == {'Фасады'}
    assert all(row['source_format'] == 'corpus-gpr-v1' and row['source_cells'] for row in schedule['rows'])
    qualification = schedule['dependency_timeline']['rnv']
    assert qualification['state'] == 'partial' and qualification['forecast'] is None
    assert qualification['indicative_forecast'] == '2027-02-01'
    assert qualification['approved'] is None and qualification['approved_rnv'] is None
    assert qualification['planned_construction_finish'] == '2027-02-01'
    assert qualification['plan_label'] == 'План окончания работ'
    assert qualification['delay_days'] is None
    assert 'План окончания работ' in schedule['dependency_timeline_html']
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


def test_a_work_with_an_unreadable_date_is_named_with_its_cell_instead_of_leaving_the_gantt():
    import developaid_monitor_page  # installs the real Monitor reader stack
    parsed = corpus.read(construction_book())
    assert any(i['cell'] == 'G5' and '«31.06.2027» не распознана' in i['message'] for i in parsed['issues'])
    monitor.store_schedule(PROJECT, construction_book(), None, '2026-11-09')
    schedule = monitor.build(PROJECT, '2026-11-09')['schedule']
    placed = {(r['object'], r['name']) for r in schedule['rows']}
    undated = schedule['undated_works']
    assert len(undated) == 1 and (undated[0]['object'], undated[0]['name']) not in placed
    assert undated[0]['object'] == 'КОРПУС 1' and undated[0]['section'] == 'Фасады'
    assert undated[0]['reason'] == 'окончание «31.06.2027» не распознано (лист «ГПР», ячейка G5)'


def test_reversed_or_missing_dates_say_which_date_and_cell():
    wb = load_workbook(io.BytesIO(construction_book()))
    ws = wb['ГПР']
    ws['F6'] = '10.02.2027'  # finish 01.02.2027 comes before it
    ws['J6'] = None
    stream = io.BytesIO(); wb.save(stream)
    works = corpus.as_schedule(corpus.read(stream.getvalue()))['works']
    problems = {w['source_cells']['progress']: w['date_problem'] for w in works if w['date_problem']}
    assert problems == {'E5': 'окончание «31.06.2027» не распознано (лист «ГПР», ячейка G5)',
                        'E6': 'окончание 01.02.2027 раньше начала 10.02.2027 (лист «ГПР», ячейки F6 и G6)',
                        'H6': 'окончание не указано (лист «ГПР», ячейка J6)'}
    assert all(not w['date_problem'] for w in works if w['start'] and w['finish'])


def test_the_rss_path_names_the_same_undated_work():
    """With a weekly RSS the Monitor builds rows in _schedule_plan_fact; the
    work with an unreadable date must be named there too."""
    import developaid_monitor_page  # installs the real Monitor reader stack
    import developaid_monitor_manager as manager
    from test_monitor_keeps_every_snapshot import _rss_book
    monitor.store_schedule(PROJECT, construction_book(), None, '2026-11-09')
    monitor.store_estimate(PROJECT, _rss_book(), '2026-11-09')
    called = []
    original = monitor._schedule_plan_fact
    def spy(*args, **kwargs):
        called.append(1)
        return original(*args, **kwargs)
    import pytest as _pytest
    with _pytest.MonkeyPatch.context() as patch:
        patch.setattr(monitor, '_schedule_plan_fact', spy)
        schedule = monitor.build(PROJECT, '2026-11-09')['schedule']
    assert called, 'the RSS path was not taken'
    assert [(w['object'], w['reason']) for w in schedule['undated_works']] == [
        ('КОРПУС 1', 'окончание «31.06.2027» не распознано (лист «ГПР», ячейка G5)')]


REASON = 'В ГПР нет полных корректных дат. Работы и известные проценты доступны; плановые полосы пока построить нельзя.'


@pytest.mark.parametrize('with_rss', [False, True])
def test_a_plan_where_no_work_has_dates_says_so_on_both_paths_and_the_page_prints_it(with_rss):
    """The reason has one owner: both schedule paths set it on the server and
    the page shows exactly that phrase instead of composing its own."""
    import developaid_monitor_page  # installs the real Monitor reader stack
    from test_monitor_cumulative_controls import browser_page
    from playwright.sync_api import expect
    wb = load_workbook(io.BytesIO(construction_book()))
    ws = wb['ГПР']
    for cell in ('G6', 'J6'):
        ws[cell] = '31.06.2027'
    stream = io.BytesIO(); wb.save(stream)
    monitor.store_schedule(PROJECT, stream.getvalue(), None, '2026-11-09')
    called = []
    original = monitor._schedule_plan_fact
    def spy(*args, **kwargs):
        called.append(1)
        return original(*args, **kwargs)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(monitor, '_schedule_plan_fact', spy)
        if with_rss:
            from test_monitor_keeps_every_snapshot import _rss_book
            monitor.store_estimate(PROJECT, _rss_book(), '2026-11-09')
        view = monitor.build(PROJECT, '2026-11-09')
    assert bool(called) == with_rss, 'взят не тот путь графика'
    schedule = view['schedule']
    assert schedule['rows'] == [] and len(schedule['undated_works']) == 3
    assert schedule['reason'] == REASON
    with browser_page(390) as (page, responses, errors):
        page.evaluate('(v)=>{currentView=v;renderGantt(v)}', view)
        notice = page.locator('#gprUndated')
        expect(notice.locator('b').first).to_have_text(REASON)
        # Страница печатает причину сервера, а не свою формулировку.
        page.evaluate("(v)=>{v.schedule.reason='Причина с сервера.';renderGantt(v)}", view)
        expect(notice.locator('b').first).to_have_text('Причина с сервера.')
        expect(notice).not_to_contain_text('ни у одной работы')
        assert not errors


def test_both_paths_leave_the_reason_empty_when_works_are_placed():
    import developaid_monitor_page  # installs the real Monitor reader stack
    from test_monitor_keeps_every_snapshot import _rss_book
    monitor.store_schedule(PROJECT, construction_book(), None, '2026-11-09')
    assert monitor.build(PROJECT, '2026-11-09')['schedule']['reason'] == ''
    monitor.store_estimate(PROJECT, _rss_book(), '2026-11-09')
    schedule = monitor.build(PROJECT, '2026-11-09')['schedule']
    assert schedule['rows'] and schedule['reason'] == ''
