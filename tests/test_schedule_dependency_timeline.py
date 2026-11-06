import datetime as dt

import pytest

import developaid_schedule_timeline as timeline
import developaid_management_report as report


def day(text):
    return dt.date.fromisoformat(text)


def task(tid, name, start, finish, predecessors=(), total=0):
    start, finish = day(start), day(finish)
    return {'id': tid, 'name': name, 'start': start, 'finish': finish,
            'duration_days': (finish-start).days, 'total_float_days': total,
            'free_float_days': total, 'total_float_known': True,
            'predecessors': list(predecessors)}


def network():
    return {'known': True, 'source': 'Учебный PM', 'rnv_id': '4',
            'calendar_confirmed': True, 'rnv_chain_complete': True,
            'tasks': {
                '1': task('1', 'РД', '2026-11-01', '2026-11-20', total=5),
                '2': task('2', 'Поставка', '2026-11-25', '2026-12-25',
                          [{'id': '1', 'type': 'FS', 'lag_days': 0}]),
                '3': task('3', 'Приёмка', '2026-12-25', '2027-01-25',
                          [{'id': '2', 'type': 'FS', 'lag_days': 0}]),
                '4': task('4', 'Получение РНВ', '2027-01-25', '2027-02-01',
                          [{'id': '3', 'type': 'FS', 'lag_days': 0}]),
            }}


def test_reserve_absorbs_five_days_and_inherited_delays_do_not_add():
    got = timeline.model(network(), {'1': day('2026-12-10')}, evidence=True)
    rows = {row['id']: row for row in got['rows']}
    assert rows['1']['own_delay_days'] == 20
    assert rows['2']['own_delay_days'] == 0 and rows['2']['inherited_delay_days'] == 15
    assert rows['3']['inherited_delay_days'] == 15 and rows['4']['inherited_delay_days'] == 15
    assert got['rnv']['delay_days'] == 15
    assert got['rnv']['forecast'] == '2027-02-16'
    assert [r['id'] for r in got['rnv']['driving_chain']] == ['1', '2', '3', '4']


@pytest.mark.parametrize('kind,lag,expected', [('FS', 3, 18), ('SS', 3, 0), ('FF', 3, 0), ('SF', 3, 0)])
def test_all_native_relationship_types_and_lags(kind, lag, expected):
    pm = network()
    pm['tasks']['2']['predecessors'][0].update(type=kind, lag_days=lag)
    got = timeline.model(pm, {'1': day('2026-12-10')}, evidence=True)
    assert got['rows'][1]['inherited_delay_days'] == expected
    assert got['edges'][0]['type'] == kind


def test_parallel_predecessors_take_maximum_constraint():
    pm = network()
    pm['tasks']['5'] = task('5', 'Материалы', '2026-11-01', '2026-11-20')
    pm['tasks']['2']['predecessors'].append({'id': '5', 'type': 'FS', 'lag_days': 0})
    got = timeline.model(pm, {'1': day('2026-12-10'), '5': day('2026-12-15')}, evidence=True)
    assert got['rnv']['delay_days'] == 20
    assert len(got['edges']) == 4


def test_missing_rnv_does_not_use_last_construction_finish():
    pm = network(); pm['rnv_id'] = ''
    got = timeline.model(pm, {'1': day('2026-12-10')}, evidence=True)
    assert got['rnv']['state'] == 'unknown'
    assert got['rnv']['approved'] is None and got['rnv']['forecast'] is None
    assert 'отдельная веха' in ' '.join(got['rnv']['reasons'])


@pytest.mark.parametrize('field', ['calendar_confirmed', 'rnv_chain_complete'])
def test_unknown_calendar_or_chain_cannot_be_complete(field):
    pm = network(); pm.pop(field)
    got = timeline.model(pm, {'1': day('2026-12-10')}, evidence=True)
    assert got['rnv']['state'] == 'partial'
    assert got['rnv']['forecast'] is None and got['rnv']['indicative_forecast']


def test_dangling_link_and_cycle_are_not_silently_approved():
    pm = network()
    pm['tasks']['2']['predecessors'].append({'id': 'missing', 'type': 'FS', 'lag_days': 0})
    assert timeline.model(pm, {'1': day('2026-12-10')}, evidence=True)['rnv']['state'] == 'partial'
    pm['tasks']['1']['predecessors'] = [{'id': '4', 'type': 'FS', 'lag_days': 0}]
    got = timeline.model(pm, {'1': day('2026-12-10')}, evidence=True)
    assert got['rnv']['state'] == 'unknown'
    assert any('цикл' in reason for reason in got['rnv']['reasons'])


def test_no_actual_seed_cannot_rename_plan_as_forecast():
    got = timeline.model(network(), {})
    assert got['rnv']['state'] == 'unknown' and got['rnv']['forecast'] is None
    assert all(row['forecast_finish'] is None for row in got['rows'])


def test_multiple_rnv_milestones_and_missing_dates_never_get_final_date():
    pm = network(); pm['rnv_candidates'] = ['3', '4']
    assert timeline.model(pm, {'1': day('2026-12-10')}, evidence=True)['rnv']['forecast'] is None
    pm = network(); pm['tasks']['4']['finish'] = None
    got = timeline.model(pm, {'1': day('2026-12-10')}, evidence=True)
    assert got['rnv']['state'] == 'unknown' and got['rnv']['approved'] is None


def test_independent_own_and_inherited_components_and_unknown_float():
    pm = network(); pm['tasks']['2']['total_float_known'] = False
    got = timeline.model(pm, {'1': day('2026-12-10'), '2': day('2027-01-04')}, evidence=True)
    row = next(r for r in got['rows'] if r['id'] == '2')
    assert row['own_delay_days'] == 10 and row['inherited_delay_days'] == 5
    assert row['remaining_float_days'] is None
    assert got['rnv']['delay_days'] == 15


def test_no_recursion_limit_for_a_long_valid_network():
    pm = network()
    previous = '4'
    for i in range(5, 1100):
        tid = str(i)
        pm['tasks'][tid] = task(tid, 'Этап', '2027-02-01', '2027-02-01',
                               [{'id': previous, 'type': 'FS', 'lag_days': 0}])
        previous = tid
    pm['rnv_id'] = previous
    assert timeline.model(pm, {'1': day('2026-12-10')}, evidence=True)['rnv']['delay_days'] == 15


def test_monitor_report_html_pdf_share_model_and_escape_data():
    pm = network(); pm['tasks']['1']['name'] = '<img src=x onerror=alert(1)>'
    block = timeline.model(pm, {'1': day('2026-12-10')}, evidence=True)
    html = timeline.render(block)
    assert '<img' not in html and '&lt;img' in html
    assert 'Своя: 0' in html and 'от этапов: 15' in html
    assert 'marker-end="url(#dependency-arrow)"' in html
    wrapped = report._gantt_html({'gantt': {'state': 'missing', 'dependency_timeline': block}})
    assert html in wrapped
