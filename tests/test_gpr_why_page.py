"""Native PAGE explanation, scope guards, real work navigation and A4 print."""
import copy
import io
import re
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect
from pypdf import PdfReader

import developaid_schedule_elements as elements
import developaid_schedule_groups as groups
import developaid_schedule_plan_scenario as scenario
import developaid_schedule_readiness as ready
from test_gpr_readable_matrix import matrix_view
from test_monitor_cumulative_controls import Responses, browser_page

CUT = '2033-04-20'
OBSERVED = '2033-04-18'
SOURCE = 'a'*64


def why_view(count=2):
    view = matrix_view(count)
    view['cut'] = CUT
    schedule = view['schedule']
    tasks = schedule['management'][0]['children'][0]['children'][0]['children']
    for i, row in enumerate(tasks):
        row.update(id='why-'+str(i), key='task:why-'+str(i), wbs='W.'+str(i),
                   name='Учебная работа '+str(i), section='Учебный этап', construction_work=True,
                   object='Учебный корпус Север' if i < 3 else row['object'],
                   plan_start='2033-01-01', plan_finish='2033-08-01',
                   actual_progress=0 if i == 0 else .5, work_done=False,
                   forecast_known=False, forecast_finish=None,
                   pace_forecast_known=False, pace_forecast_method='plan')
        row['display_progress'] = dict(value=row['actual_progress'], date=OBSERVED,
                                       label='По учебному ГПР', source='gpr_percent')
    tasks[0]['name'] = 'Монтаж <img src=x onerror="window.whyInjected=1">'
    tasks[0]['plan_finish'] = '2033-12-31'
    tasks[3].update(name='Работа вне выбранного состава', plan_finish='2038-12-31')
    for row in tasks:
        row['plan_pace_scenario'] = scenario.work(row, CUT)
    undated = dict(tasks[-1], id='why-undated', key='task:why-undated',
                   name='Учебная работа без начала', plan_start=None)
    undated['plan_pace_scenario'] = scenario.work(undated, CUT)
    all_rows = [*tasks, undated]
    schedule.update(rows=copy.deepcopy(tasks), undated_works=[undated],
                    display_groups=groups.metadata(all_rows))
    facts = {r['id']: dict(r, primary={**r['display_progress'], 'basis': 'gpr_percent'}) for r in all_rows}
    included = [r['id'] for r in tasks[:3]]
    profile = dict(scope_kind=ready.CURRENT_ESTIMATE, full_scope_confirmed=False,
        full_source_sha256=SOURCE, remaining_source_sha256=SOURCE, effective_from=OBSERVED,
        crosswalk=[dict(full_id=k, remaining_id=k) for k in facts], outside_completed_ids=[],
        included_ids=included, excluded_ids=[k for k in facts if k not in included],
        basis='estimated_elements', weights=[], label='Учебная оценка',
        element_profile=dict(id=elements.PROFILE_ID, overrides={},
            objects={'Учебный корпус Север': 'residential'},
            assignments={included[0]: dict(element_id='frame', share=100),
                         included[1]: dict(element_id='underground', share=100)}))
    state = ready.model({'works': facts}, cut=CUT, baseline_scope='remaining_work',
                        source_sha256=SOURCE, profile=profile, full_rows=facts)
    q = dict(basis='gpr', state='unknown', approved='2033-09-22', plan_date='2033-09-22',
             plan_label='Учебный план окончания', forecast=None, indicative_forecast=None,
             delay_days=None, reasons=['Для даты ввода нужна подтверждённая последовательность работ.'])
    scenario.decorate_readiness(state, all_rows, q)
    schedule.update(readiness=state, readiness_html=ready.render(state),
        dependency_timeline=dict(rnv=q, rows=[], edges=[]),
        dependency_timeline_html='<section class="schedule-overview"><h3>Повторная сводка сроков</h3></section>')
    return view


def serve(monkeypatch, view):
    original = Responses.__call__
    def respond(self, route):
        path = urlsplit(route.request.url).path
        if path in {'/monitor/view', '/monitor/gpr-view'}:
            return route.fulfill(json=view)
        if path == '/monitor/daily/summary':
            return route.fulfill(json={'rows': []})
        return original(self, route)
    monkeypatch.setattr(Responses, '__call__', respond)


def show(page, view):
    page.wait_for_function('currentView!==null&&!$("refresh").disabled')
    page.evaluate('(v)=>{document.activeElement?.blur();$("cut").value=v.cut;currentView=v;renderGantt(v)}', view)


@pytest.mark.parametrize('width', [390, 1440])
def test_native_why_is_scoped_readable_and_opens_the_real_work(monkeypatch, width):
    view = why_view()
    before = copy.deepcopy(view)
    serve(monkeypatch, view)
    with browser_page(width) as (page, responses, errors):
        show(page, view)
        why = page.locator('#gprWhy')
        expect(why.get_by_role('heading', name='Что влияет на срок')).to_be_visible()
        expect(why).not_to_contain_text('Повторная сводка сроков')
        expect(why.locator('.gpr-why-scope')).to_contain_text('к 3 работам')
        expect(why.locator('.gpr-why-scope')).to_contain_text('нет пропусков')
        expect(why).to_contain_text('Измеренного прогноза по этим работам нет')
        expect(why).to_contain_text('Оценочная готовность')
        expect(why).not_to_contain_text('Работа вне выбранного состава')
        assert page.locator('#gprWhy img').count() == 0
        assert page.evaluate('window.whyInjected') is None
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        why.screenshot(path=f'/tmp/gpr-why-block-{width}.png')
        why.locator('.gpr-why-limits > summary').click()
        expect(why).to_contain_text('В полном перечне ГПР — 9 работ')
        expect(why).to_contain_text('с неполными плановыми датами — 1')
        expect(why).to_contain_text('не подтверждает дату разрешения')
        why.locator('[data-why-open="why-0"]').click()
        expect(page.locator('#gprCalendar')).to_have_attribute('open', '')
        expect(page.locator('#detailTitle')).to_contain_text('Монтаж <img')
        page.locator('#detailClose').click()
        calls = sum(path == '/monitor/ask' for path, _, _ in responses.calls)
        page.locator('#gprWhyAsk').click()
        expect(page.locator('#scenarioQuestion')).to_have_value(re.compile('Поясни оценку сроков'))
        assert sum(path == '/monitor/ask' for path, _, _ in responses.calls) == calls
        assert view == before and not errors
        page.screenshot(path=f'/tmp/gpr-why-native-{width}.png', full_page=True)


@pytest.mark.parametrize('mutation', ['source', 'cut', 'outside', 'complete', 'schema',
                                    'full_source', 'scope', 'count', 'date', 'duplicate'])
def test_wrong_or_stale_explanation_never_promotes_other_work(monkeypatch, mutation):
    view = why_view()
    explanation = view['schedule']['readiness']['project']['forecast']['explanation']
    if mutation == 'source': explanation['source_sha256'] = 'c'*64
    elif mutation == 'cut': explanation['cut'] = '2033-04-19'
    elif mutation == 'outside': explanation['rows'][0].update(work_id='why-3', reference_work_id='why-3')
    elif mutation == 'complete': view['schedule']['rows'][0]['work_done'] = True
    elif mutation == 'schema': explanation['schema'] = 99
    elif mutation == 'full_source': explanation['full_source_sha256'] = 'f'*64
    elif mutation == 'scope': explanation['id_scope'] = 'current_source'
    elif mutation == 'count': explanation['covered'] -= 1
    elif mutation == 'date': explanation['rows'][0]['finish'] = '2037-01-01'
    elif mutation == 'duplicate': explanation['rows'].append(copy.deepcopy(explanation['rows'][0]))
    serve(monkeypatch, view)
    with browser_page() as (page, _, errors):
        show(page, view)
        expect(page.locator('.gpr-why-unavailable')).to_be_visible()
        assert page.locator('[data-why-open]').count() == 0
        assert page.locator('.readiness-project-value').text_content()
        assert not errors


def test_print_keeps_every_work_and_the_why_without_a_duplicate_bottom_forecast(monkeypatch):
    view = why_view(18)
    serve(monkeypatch, view)
    with browser_page(1440) as (page, _, errors):
        show(page, view)
        page.evaluate('beginGprPrint()')
        page.emulate_media(media='print')
        expect(page.locator('#gprWhy')).to_be_visible()
        assert page.locator('#gprFactMatrix [data-work-id]:visible').count() == 73
        pdf = page.pdf(format='A4', landscape=True, print_background=True, prefer_css_page_size=True)
        reader = PdfReader(io.BytesIO(pdf))
        text = '\n'.join(p.extract_text() or '' for p in reader.pages)
        assert len(reader.pages) >= 2
        assert 'Что влияет на срок' in text and 'Учебная работа без начала' in text
        assert 'Работа вне выбранного состава' in text  # Source work remains in the full matrix.
        assert 'Повторная сводка сроков' not in text
        assert all(float(p.mediabox.height) < 1000 for p in reader.pages)
        page.evaluate("window.dispatchEvent(new Event('afterprint'))")
        page.emulate_media(media='screen')
        assert not page.evaluate("document.body.classList.contains('gpr-print-mode')")
        with open('/tmp/gpr-why-native-matrix.pdf', 'wb') as f: f.write(pdf)
        assert not errors


def test_context_reset_clears_why_and_old_actions_cannot_open_or_ask(monkeypatch):
    view = why_view()
    serve(monkeypatch, view)
    with browser_page() as (page, responses, errors):
        show(page, view)
        page.evaluate('()=>{window.oldWhyAsk=$("gprWhyAsk").onclick;window.oldWhyOpen=document.querySelector("[data-why-open]").onclick}')
        page.evaluate('$("project").value="Другой учебный проект";clearReadiness();oldWhyAsk();oldWhyOpen()')
        expect(page.locator('#dependencyTimelineCard')).to_be_hidden()
        assert page.locator('#dependencyTimelineBody').text_content() == ''
        assert page.locator('#scenarioQuestion').input_value() == ''
        assert not errors
