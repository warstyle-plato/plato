"""Test page «ГПР — новый вид»: the brief arranges the Monitor view, the page shows it."""
import copy
import json

import pytest
from playwright.sync_api import expect

import developaid_gpr_brief as brief
import developaid_monitor_pace as pace
import developaid_gpr_preview_page as preview_page
import test_monitor_cumulative_controls as monitor_page
from developaid_monitor_page import MONITOR_PAGE
from test_gpr_why_page import serve
from test_monitor_cumulative_api import KEY, api, post
from test_schedule_readiness import DAY, PROJECT, activate, site


def row(id_, name, obj, plan, fact, done=False):
    shown = {} if fact is None else {'value': fact, 'date': DAY, 'label': 'Выполнено по ГПР'}
    return {'id': id_, 'name': name, 'object': obj, 'plan_progress': plan, 'display_progress': shown,
            'work_done': done, 'plan_finish': '2026-12-01'}


def view():
    rows = [row('1', 'Монолит', 'Корпус 1', .8, .2), row('2', 'Монолит', 'Корпус 2', .8, .75),
            row('3', 'Фасад', 'Корпус 1', .5, None), row('4', 'Кровля', 'Корпус 2', .3, 1.0),
            row('5', 'Озеленение', 'Корпус 1', .9, .1)]
    cell = lambda ids: {'work_ids': ids, 'progress': None}
    return {'cut': DAY, 'schedule': {'rows': rows, 'readiness': {
        'cut': DAY, 'source_sha256': 'a' * 64,
        'forecast_identity': {'id_scope': 'current_source', 'source_sha256': 'a' * 64,
                              'full_source_sha256': None,
                              'remaining_ids': {r['id']: r['id'] for r in rows}},
        'matrix_objects': ['Корпус 1', 'Корпус 2'],
        # Work 5 sits in no cell: it is outside the matrix, whatever its name says.
        'matrix': [{'stage': 'Каркас', 'cells': [cell(['1']), cell(['2'])]},
                   {'stage': 'Отделка', 'cells': [cell(['3']), cell(['4'])]}],
        'corpora': [{'name': 'Корпус 1', 'progress': .4, 'forecast': {'plan_finish': '2026-12-01'}},
                    {'name': 'Корпус 2', 'progress': .9, 'forecast': {'plan_finish': '2026-11-30'}}],
        'project': {'progress': None, 'work_ids': ['1', '2', '3', '4'], 'total': 4,
                    'reason': 'Нет подтверждённого полного состава и весов.'},
        'reason': 'Нет подтверждённого полного состава и весов.'}},
        'dashboard': {'schedule': {'qualified_rnv': {'plan_date': '2026-12-01', 'plan_label': 'План ввода',
                                                     'reasons': ['Нет подтверждённого полного состава и весов.']}}}}


def test_brief_keeps_absent_fact_apart_and_reads_stages_only_from_the_matrix():
    b = brief.build(view())
    states = {w['id']: w['state'] for s in b['matrix']['stages'] for l in s['lines']
              for ws in l['by_object'].values() for w in ws}
    # 75% against 80% is within the rule; an absent fact is never «behind» or zero.
    assert states == {'1': 'behind', '2': 'on_plan', '3': 'no_reading', '4': 'done'}
    assert b['counts'] == {'total': 4, 'done': 1, 'behind': 1, 'no_reading': 1}
    assert b['outside_matrix'] == 1 and 'Озеленение' not in json.dumps(b, ensure_ascii=False)
    assert [s['stage'] for s in b['matrix']['stages']] == ['Каркас', 'Отделка']
    frame = b['matrix']['stages'][0]
    assert [l['name'] for l in frame['lines']] == ['Монолит']           # one line for both corpora
    assert set(frame['lines'][0]['by_object']) == {'Корпус 1', 'Корпус 2'}
    assert b['attention'] == {'items': [{'name': 'Монолит', 'works': [b['matrix']['stages'][0]['lines'][0]['by_object']['Корпус 1'][0]]}], 'total': 1}
    assert b['plan_finish'] == {'date': '2026-12-01', 'label': 'План ввода'}
    # No approved source in this synthetic view: the single estimate says so, no date is made up.
    assert b['expected_finish']['state'] == 'unknown' and b['expected_finish']['date'] is None
    assert b['progress']['value'] is None
    assert b['notes'] == ['Нет подтверждённого полного состава и весов.']
    assert [(c['name'], c['behind'], c['no_reading']) for c in b['corpora']] == [('Корпус 1', 1, 1), ('Корпус 2', 0, 0)]


def test_brief_moves_a_work_when_the_matrix_moves_it():
    moved = view()
    stages = moved['schedule']['readiness']['matrix']
    stages[0]['cells'][0]['work_ids'], stages[1]['cells'][0]['work_ids'] = ['3'], ['1']
    b = brief.build(moved)
    assert [l['name'] for l in b['matrix']['stages'][0]['lines']] == ['Фасад', 'Монолит']
    assert [(s['behind'], s['no_reading'], s['done']) for s in b['matrix']['stages']] == [(0, 1, 0), (1, 0, 1)]


def brief_works(result):
    return [work for stage in result['matrix']['stages'] for line in stage['lines']
            for values in line['by_object'].values() for work in values]


def translated_view(ids=('f1', 'f2', 'r1', 'r2')):
    from test_schedule_summary_identity import record, full_state
    f1, f2, r1, r2 = ids
    state = full_state({key: record(key) for key in (f1, f2)},
                       {key: record(key) for key in (r1, r2)}, {f1: r1, f2: r2})
    return {'cut': DAY, 'schedule': {'readiness': state,
        'rows': [row(r1, 'Первая работа', 'Корпус 1', .8, .2),
                 row(r2, 'Вторая работа', 'Корпус 1', .8, .7)]}}


@pytest.mark.parametrize('ids', [('f1', 'f2', 'r1', 'r2'), ('1', '2', '2', '3')])
def test_full_source_matrix_follows_canonical_translation_even_when_namespaces_overlap(ids):
    source = translated_view(ids)
    before = copy.deepcopy(source)
    result = brief.build(source)
    assert [(item['reference_work_id'], item['id'], item['fact']) for item in brief_works(result)] == [
        (ids[0], ids[2], .2), (ids[1], ids[3], .7)]
    assert result['counts']['total'] == 2
    assert result['expected_finish']['date'] is None
    assert source == before


@pytest.mark.parametrize('problem', ['missing_translation', 'duplicate_translation', 'missing_row',
                                   'duplicate_row', 'duplicate_reference', 'outside_current', 'source_mismatch'])
def test_unresolved_canonical_members_remain_unknown_in_the_matrix_denominator(problem):
    source = translated_view()
    state, rows = source['schedule']['readiness'], source['schedule']['rows']
    mapping = state['forecast_identity']['remaining_ids']
    if problem == 'missing_translation':
        mapping.pop('f2')
    elif problem == 'duplicate_translation':
        mapping['f2'] = 'r1'
    elif problem == 'missing_row':
        rows.pop()
    elif problem == 'duplicate_row':
        rows.append(copy.deepcopy(rows[-1]))
    elif problem == 'duplicate_reference':
        state['matrix'][0]['cells'][0]['work_ids'] = ['f1', 'f1']
    elif problem == 'outside_current':
        mapping['f2'] = None
    else:
        state['forecast_identity']['source_sha256'] = 'c' * 64
    before = copy.deepcopy(source)
    result = brief.build(source)
    unresolved = [item for item in brief_works(result) if item['id'] is None]
    assert result['counts']['total'] == 2
    assert unresolved and all(item['state'] == 'no_reading' and item['fact'] is None for item in unresolved)
    assert all(item['reason_code'] != 'unknown_time' for item in unresolved)
    assert result['outside_matrix'] is None
    assert any('Проверьте привязки' in note for note in result['notes'])
    assert source == before


@pytest.mark.parametrize('gap, state', [(9.950738916, 'on_plan'), (9.99, 'on_plan'),
                                     (10.0, 'behind'), (10.04, 'behind')])
def test_lag_threshold_uses_raw_points_before_display_rounding(gap, state):
    item = brief.work(row('1', 'Работа', 'Корпус 1', .5 + gap / 100, .5))
    assert item['state'] == state
    if state == 'behind':
        assert item['gap_pp'] == 10.0


@pytest.mark.parametrize('value', [float('nan'), float('inf'), True, -.1])
def test_invalid_direct_observations_are_not_a_zero_or_behind(value):
    item = brief.work(row('1', 'Работа', 'Корпус 1', .8, value))
    assert item['fact'] is None and item['state'] == 'no_reading'


@pytest.mark.parametrize('date', [None, 'не дата', '2099-01-01'])
def test_a_missing_invalid_or_future_date_cannot_supply_a_dated_fact(date):
    source = row('1', 'Работа', 'Корпус 1', .8, .2)
    source['display_progress']['date'] = date
    item = brief.work(source, DAY)
    assert item['fact'] is None and item['fact_date'] is None and item['state'] == 'no_reading'



def plain(value):
    return json.loads(json.dumps(value, default=str))


def test_the_monitor_view_carries_the_brief_of_its_own_schedule(api, site, monkeypatch):
    client, _ = api
    shown = post(client, 'gpr-view', project=PROJECT, cut=DAY).json()
    assert shown['schedule']['brief']['counts']['total'] > 0
    again = pace.schedule_view(PROJECT, DAY)
    own = again['schedule'].pop('brief')
    # Arranged from this very schedule: rebuilding it from the view gives the same brief.
    assert plain(own) == plain(brief.build(again)) == shown['schedule']['brief']
    denied = post(client, 'gpr-view', key='wrong-key', project=PROJECT, cut=DAY)
    assert denied.status_code == 403 and 'brief' not in denied.text
    # A failing brief is named on the page and does not take the Monitor's schedule down.
    monkeypatch.setattr(brief, 'build', lambda view: 1 / 0)
    broken = pace.schedule_view(PROJECT, DAY)
    assert broken['schedule']['rows'] and broken['schedule']['brief'] == {
        'error': brief.FAILED + ' (ZeroDivisionError).'}
    page = client.get('/gpr-preview')
    assert page.status_code == 200 and 'ГПР — новый вид' in page.text and '__VERSION__' not in page.text
    assert '/* gpr-new-view */' in page.text and '/* gpr-new-view */' not in client.get('/monitor').text


def open_preview(monkeypatch, value, width):
    monkeypatch.setattr(monitor_page, 'MONITOR_PAGE', preview_page.page(MONITOR_PAGE))
    serve(monkeypatch, value)
    return monitor_page.browser_page(width)


def show(page, value):
    page.wait_for_function('currentView!==null&&!$("refresh").disabled')
    page.evaluate('(v)=>{document.activeElement?.blur();$("project").value=v.project||$("project").value;'
                  '$("cut").value=v.cut;currentView=v;renderDash(v);renderGantt(v)}', value)


def monitor_panel_ids(page):
    return set(page.evaluate("[...document.querySelectorAll('#monitorPanel [id]')].map(e=>e.id)"))


@pytest.mark.parametrize('width', [390, 1440])
def test_new_tab_keeps_every_block_of_the_current_gpr_tab(monkeypatch, site, width):
    activate(site)
    value = plain(pace.schedule_view(PROJECT, DAY))
    serve(monkeypatch, value)
    with monitor_page.browser_page(width) as (page, _, errors):
        show(page, value)
        current = monitor_panel_ids(page)
        assert not errors
    with open_preview(monkeypatch, value, width) as (page, _, errors):
        show(page, value)
        # Mechanical comparison: nothing of the current tab is left behind.
        assert current - monitor_panel_ids(page) == set()
        for block in ('ganttCard', 'gprCalendar', 'gprUndated', 'ksSharedBox', 'dependencyTimelineCard',
                      'forecastCard', 'corpusGprCard', 'peopleCard', 'scenarioCard', 'detailCard',
                      'gprAutomaticAnalysis', 'readinessSummary', 'readinessEditor'):
            assert block in current, block
        assert not errors


@pytest.mark.parametrize('width', [390, 1440])
def test_new_tab_shows_the_brief_above_the_monitor_gantt_and_opens_a_work(monkeypatch, site, width):
    activate(site)
    value = plain(pace.schedule_view(PROJECT, DAY))
    b = value['schedule']['brief']
    with open_preview(monkeypatch, value, width) as (page, _, errors):
        show(page, value)
        expect(page.locator('#gbTest')).to_contain_text('Тестовый вид вкладки «ГПР: план и факт»')
        shown = b['expected_finish']['date']
        expect(page.locator('#expected b')).to_have_text(shown[8:10] + '.' + shown[5:7] + '.' + shown[:4])
        expect(page.locator('#deadlines')).to_contain_text(f"{b['counts']['behind']} из {b['counts']['total']}")
        expect(page.locator('#corpora .gb-corpora tbody tr')).to_have_count(len(b['corpora']))
        # The old headline and fact matrix are folded away, not repeated next to the new blocks.
        expect(page.locator('#readinessSummary .canonical-work-forecast')).to_be_hidden()
        expect(page.locator('#gprFactMatrix')).to_be_hidden()
        expect(page.locator('#gbReadiness')).to_be_attached()
        assert page.locator('#gbReadiness #readinessSummary').count() == 1
        # The Gantt is part of the tab and open; it stays below the summary.
        expect(page.locator('#gprCalendar')).to_have_attribute('open', '')
        expect(page.locator('#gantt .g-row').first).to_be_visible()
        top = lambda sel: page.locator(sel).first.evaluate('e=>e.getBoundingClientRect().top+scrollY')
        assert top('#deadlines') < top('#corpora') < top('#matrix') < top('#gprCalendar')
        stage = b['matrix']['stages'][0]
        work = next(w for line in stage['lines'] for ws in line['by_object'].values() for w in ws if w['id'])
        page.locator('#matrix td.gb-stage', has_text=stage['stage']).first.click()
        if width <= 700 and len(b['matrix']['objects']) > 1:
            page.locator(f'#objectSwitch [data-object="{work["object"]}"]').click()
        page.locator(f'#matrix [data-work="{work["id"]}"][data-object="{work["object"]}"]').first.click()
        expect(page.locator('#detailCard')).to_be_visible()
        expect(page.locator('#detailTitle')).to_have_text(work['name'])
        expect(page.locator('#gantt .g-row.selected')).to_have_count(1)
        # Closing the Gantt by hand is respected by the next redraw.
        page.locator('#detailClose').click()
        page.locator('#gprCalendar > summary').click()
        page.evaluate('renderGantt(currentView)')
        expect(page.locator('#gprCalendar')).not_to_have_attribute('open', '')
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        assert page.evaluate("[...document.querySelectorAll('#gprBrief .gb-scroll')].every(e=>e.scrollWidth<=e.clientWidth)")
        assert not errors


def test_new_tab_names_a_missing_or_failed_brief(monkeypatch, site):
    value = plain(pace.schedule_view(PROJECT, DAY))
    value['schedule']['brief'] = {'error': brief.FAILED + ' (ZeroDivisionError).'}
    with open_preview(monkeypatch, value, 390) as (page, _, errors):
        show(page, value)
        expect(page.locator('#deadlines')).to_contain_text(brief.FAILED)
        expect(page.locator('#corpora')).to_be_hidden()
        expect(page.locator('#gantt .g-row').first).to_be_attached()
        empty = dict(value, schedule=dict(value['schedule'], brief=plain(brief.build({'schedule': {}}))))
        show(page, dict(empty, cut='2026-11-13'))
        expect(page.locator('#deadlines')).to_contain_text('В графике работ нет ни одной работы.')
        assert not errors


def test_expected_finish_is_the_monitor_single_estimate_for_project_and_corpora(site, monkeypatch):
    import developaid_gpr_work_forecast as forecast
    for step in ('legacy catalog', 'active profile'):
        if step == 'active profile':
            activate(site)
        source = pace.schedule_view(PROJECT, DAY)
        summary, value = forecast.current(source['schedule'], DAY)
        b = brief.build(source)
        assert summary and b['expected_finish']['date'] == summary['finish'], step
        assert b['expected_finish']['label'] == summary['forecast_label']
        corpora = {c['name']: (c.get('forecast') or {}).get('finish') for c in (value or {}).get('corpora') or []}
        assert {c['name']: c['expected_finish'] for c in b['corpora']} == {
            c['name']: corpora.get(c['name']) for c in b['corpora']}
    # A different single estimate moves every date of the page; nothing is computed here.
    fake = dict(summary, finish='2031-05-07', forecast_label='Оценка окончания учтённых работ',
                forecast_text='Оценка окончания учтённых работ: 07.05.2031. Подставлено тестом.', delta_days=3,
                delta_text='+3 дн. к плану того же состава.')
    fake_value = {'state': 'partial', 'project': {'forecast': {}},
                  'corpora': [{'name': 'Корпус 1', 'forecast': {'finish': '2031-04-01'}}]}
    monkeypatch.setattr(forecast, 'current', lambda schedule, cut: (fake, fake_value))
    b = brief.build(source)
    assert (b['expected_finish']['date'], b['expected_finish']['text']) == ('2031-05-07', 'Подставлено тестом.')
    assert {c['name']: c['expected_finish'] for c in b['corpora']} == {'Корпус 1': '2031-04-01', 'Корпус 2': None}
    import developaid_monitor_dashboard as dashboard
    assert '07.05.2031' in dashboard._work_schedule_summary(source)
    monkeypatch.setattr(forecast, 'current', lambda schedule, cut: (None, None))
    assert brief.build(source)['expected_finish'] == dict(brief.build(source)['expected_finish'],
                                                          state='unknown', date=None, text=brief.EXPECTED_UNKNOWN)
