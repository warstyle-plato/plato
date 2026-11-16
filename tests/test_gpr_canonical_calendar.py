"""The upper date, automatic analysis and Gantt use one explicit member scope."""
import copy
import io
import re

import pytest
from playwright.sync_api import expect
from pypdf import PdfReader

import developaid_gpr_summary as summary
import developaid_management_report as report
import developaid_schedule_plan_scenario as scenario
import developaid_schedule_readiness as readiness
from test_gpr_why_page import why_view, serve, show
from test_monitor_cumulative_controls import browser_page


def test_display_points_are_the_exact_canonical_members_not_the_broader_roster():
    view = why_view()
    state = view['schedule']['readiness']
    forecast = state['project']['forecast']
    display = forecast['display']
    assert display['finish'] == forecast['finish']
    assert {p['reference_work_id'] for p in display['rows']} == set(state['project']['work_ids'])
    assert len(display['rows']) == display['total'] == 3
    assert all(p['basis'] == 'conditional' for p in display['rows'])
    assert 'why-3' not in {p['work_id'] for p in display['rows']}
    assert len(display['paragraphs']) == 2
    text = summary.render_analysis(display)
    assert text.count('class="gpr-analysis-paragraph"') == 2
    assert 'Платон' in text and 'без обращения к языковой модели' in text
    assert 'Работа вне выбранного состава' not in text
    native_report = report._gantt_html({'gantt': {'readiness': state}, 'end': view['cut']})
    assert native_report.index(text) < native_report.index('readiness-summary')
    assert 'Монтаж &lt;img' in native_report


def test_unknown_reading_counts_are_labelled_without_python_none():
    state = why_view()['schedule']['readiness']
    state['project']['progress'] = None
    state['project']['known_readings'] = None
    state['project']['total'] = None
    value = summary.gpr_summary(state, state['cut'])
    assert 'None' not in value['readiness_text'] and 'неизвестно' in value['readiness_text']
    assert value['progress'] is None and value['total'] is None


def test_native_known_completion_date_is_not_replaced_with_unknown(monkeypatch):
    view = why_view()
    rows = view['schedule']['rows']+view['schedule']['undated_works']
    row = next(r for r in rows if r['id'] == 'why-0')
    row.update(work_done=True, actual_finish='2033-04-19')
    row['plan_pace_scenario']['complete'] = True
    # Apply the same source record to the native management leaf used by Gantt.
    def leaves(items):
        for item in items:
            if item.get('children'): yield from leaves(item['children'])
            else: yield item
    target = next(r for r in leaves(view['schedule']['management']) if r['id'] == row['id'])
    target.update(copy.deepcopy(row))
    state = view['schedule']['readiness']
    scenario.decorate_readiness(state, rows)
    view['schedule']['readiness_html'] = readiness.render(state)
    serve(monkeypatch, view)
    with browser_page() as (page, _, errors):
        show(page, view)
        page.locator('#gprCalendar > summary').click()
        page.locator('#ganttExpand').click()
        task = page.locator('#gantt .g-row[data-work-id="why-0"]')
        expect(task).to_contain_text('Фактическое окончание: 19.04.2033')
        assert task.locator('.gpr-forecast-end').count() == 0
        assert not errors


@pytest.mark.parametrize('width', [390, 1440])
def test_native_gantt_shows_conditional_dates_and_automatic_analysis_first(monkeypatch, width):
    view = why_view()
    before = copy.deepcopy(view)
    finish = view['schedule']['readiness']['project']['forecast']['finish']
    serve(monkeypatch, view)
    with browser_page(width) as (page, responses, errors):
        show(page, view)
        automatic = page.locator('#gprAutomaticAnalysis')
        expect(automatic).to_be_visible()
        assert automatic.locator('.gpr-analysis-paragraph').count() == 2
        assert page.evaluate('$("gprAutomaticAnalysis").compareDocumentPosition($("readinessSummary"))&Node.DOCUMENT_POSITION_FOLLOWING')
        assert not [c for c in responses.calls if c[0] == '/monitor/ask']
        page.locator('#gprCalendar > summary').click()
        page.locator('#ganttExpand').click()
        marker = page.locator('#gantt .gpr-scoped-finish').first
        expect(marker).to_have_attribute('data-date', finish)
        row = page.locator('#gantt .g-row[data-work-id="why-0"]')
        expect(row.locator('.gpr-forecast-end')).to_have_attribute('data-finish', finish)
        expect(row).to_contain_text('Условное окончание')
        assert 0 < float(row.locator('.gpr-forecast-end').evaluate('(e)=>parseFloat(e.style.left)')) < 100
        expect(page.locator('#gantt .g-row[data-work-id="why-3"]')).to_have_attribute('data-forecast-scope', 'outside')
        assert page.locator('#gantt .g-row[data-work-id="why-3"] .gpr-forecast-end').count() == 0
        assert page.locator('#gantt .g-row[data-work-id]').count() == 9
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.locator('#gprWhyAsk').click()
        page.locator('#scenarioAsk').click()
        page.wait_for_function('$("scenarioMsg").textContent.length>0')
        messages = [body['message'] for path, body, _ in responses.calls if path == '/monitor/ask']
        assert len(messages) == 1 and len(messages[0]) <= 4000
        assert 'Вопрос:' in messages[0] and view['cut'] in messages[0]
        assert view == before and not errors


@pytest.mark.parametrize('mutation', ['source', 'scope', 'finish', 'outside', 'unknown'])
def test_wrong_display_scope_is_never_drawn_as_the_upper_forecast(monkeypatch, mutation):
    view = why_view()
    display = view['schedule']['readiness']['project']['forecast']['display']
    if mutation == 'source': display['source_sha256'] = 'c'*64
    elif mutation == 'scope': display['id_scope'] = 'current_source'
    elif mutation == 'finish': display['finish'] = '2038-01-01'
    elif mutation == 'outside': display['rows'][0]['work_id'] = 'why-3'
    else: display['rows'][0]['finish'] = None
    serve(monkeypatch, view)
    with browser_page() as (page, _, errors):
        show(page, view)
        assert page.locator('#gprAutomaticAnalysis').text_content() == ''
        assert page.locator('#gantt .gpr-scoped-finish').count() == 0
        assert not errors


def test_native_print_contains_the_gantt_and_every_original_row(monkeypatch):
    view = why_view(18)
    serve(monkeypatch, view)
    with browser_page(1440) as (page, _, errors):
        show(page, view)
        page.evaluate('beginGprPrint()')
        page.emulate_media(media='print')
        expect(page.locator('#gprAutomaticAnalysis')).to_be_visible()
        expect(page.locator('#gantt')).to_be_visible()
        assert page.locator('#gantt .g-row[data-work-id]:visible').count() == 73
        pdf = page.pdf(format='A4', landscape=True, print_background=True, prefer_css_page_size=True)
        text = '\n'.join(p.extract_text() or '' for p in PdfReader(io.BytesIO(pdf)).pages)
        assert 'Платон: пояснение' in text and 'Условное окончание' in text
        assert 'Работа вне выбранного состава' in text and 'Учебная работа без начала' in text
        assert not errors
