"""The native matrix keeps source facts, qualified dates and every printed work.

Only synthetic observations are kept in git. The owner-source replay remains
private, and does not turn the unweighted project into a confirmed percentage.
"""
import copy

import pytest
from playwright.sync_api import expect
from pypdf import PdfReader

from test_monitor_cumulative_controls import Responses, browser_page
from test_monitor_gpr_sections import monitor_view


def matrix_view(count=4):
    view = monitor_view('unknown')
    tasks = view['schedule']['management'][0]['children'][0]['children'][0]['children']
    base = tasks[0]
    tasks[:] = [dict(base, id=f'{obj}-{i}', wbs=f'{obj}.{i}', object=obj,
                    section='Этап '+str(i % 2), name='Работа '+str(i),
                    actual_progress=0 if i == 0 else .4, plan_progress=.5,
                    pace_forecast_known=False, pace_forecast_method='plan',
                    forecast_finish=None, delta_days=None)
                for obj in ['Корпус 1', 'Корпус 2', 'Корпус 3', 'ПАРКИНГ']
                for i in range(count)]
    # Explicit object is stronger than a neighboring building in a work name.
    tasks[-1]['name'] = 'Примыкание к корпусу 1'
    return view


def serve_view(monkeypatch, view):
    original = Responses.__call__

    def response(self, route):
        path = route.request.url.split('?')[0]
        if path.endswith('/monitor/view'):
            return route.fulfill(json=view)
        # The successful view also loads this GET. The general contracts
        # fixture admits POST body keys only; it cannot represent that GET.
        if path.endswith('/monitor/daily/summary'):
            return route.fulfill(json={'rows': []})
        return original(self, route)

    monkeypatch.setattr(Responses, '__call__', response)


def settled(page, view):
    page.wait_for_function('currentView!==null&&!$("refresh").disabled')
    page.locator('#cut').fill(view['cut'])
    page.evaluate('(v)=>{currentView=v;renderGantt(v)}', view)


@pytest.mark.parametrize('width', [390, 1440])
def test_matrix_keeps_zero_unknown_duplicate_and_explicit_object(monkeypatch, width):
    view = matrix_view()
    tasks = view['schedule']['management'][0]['children'][0]['children'][0]['children']
    tasks.append(dict(tasks[0], id='duplicate', actual_progress=.75))
    tasks.append(dict(tasks[1], id='unknown', name='Без показания', actual_progress=None, pace_progress=None))
    tasks.append(dict(tasks[0], id='other-stage', section='Иной этап', actual_progress=.25))
    before = copy.deepcopy(view)
    serve_view(monkeypatch, view)
    with browser_page(width) as (page, responses, errors):
        settled(page, view)
        cells = page.locator('#gprFactMatrix [data-work-id]')
        expect(cells).to_have_count(19)
        expect(page.locator('[data-work-id="Корпус 1-0"] b')).to_have_text('0%')
        expect(page.locator('[data-work-id="unknown"] b')).to_have_text('Нет показания')
        expect(page.locator('[data-work-id="duplicate"] b')).to_have_text('75%')
        expect(page.locator('[data-work-id="other-stage"] b')).to_have_text('25%')
        parking = page.locator('[data-work-id="ПАРКИНГ-3"]')
        expect(parking).to_have_attribute('data-object', 'ПАРКИНГ')
        expect(parking.locator('..')).to_have_attribute('data-matrix-object', 'ПАРКИНГ')
        assert page.locator('#gantt .lvl-task').count() == 0
        assert page.locator('#gprCalendar').get_attribute('open') is None
        page.locator('#gprMatrixExpand').click()
        parking.click()
        expect(page.locator('#gprCalendar')).to_have_attribute('open', '')
        expect(page.locator('#detailTitle')).to_contain_text('Примыкание к корпусу 1')
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        assert not errors and view == before


def test_matrix_forecast_uses_native_qualification_and_shows_actual_forecast_date(monkeypatch):
    view = matrix_view(1)
    tasks = view['schedule']['management'][0]['children'][0]['children'][0]['children']
    tasks[0].update(pace_forecast_known=True, pace_forecast_method='gpr_pace',
                    forecast_finish='2027-02-03', delta_days=None, forecast_partial=True)
    tasks[1].update(pace_forecast_known=True, pace_forecast_method='gpr_pace',
                    forecast_finish='2027-02-04', delta_days=19)
    tasks[2].update(work_done=True, observed_complete_by='2026-11-06',
                    forecast_finish='2026-11-06', finished_late_days=8)
    # A plan date alone is not a forecast, nor is a legacy monetary method.
    tasks[3].update(forecast_finish='2035-01-01', pace_forecast_known=True,
                    pace_forecast_method='accepted_cost_pace')
    serve_view(monkeypatch, view)
    with browser_page() as (page, _, errors):
        settled(page, view)
        first = page.locator('[data-work-id="Корпус 1-0"] .gpr-cell-forecast')
        expect(first).to_have_text('Прогноз · 03.02.2027 · частичный')
        expect(first).not_to_contain_text('По сроку')
        expect(page.locator('[data-work-id="Корпус 2-0"] .gpr-cell-forecast')).to_have_text('+19 дн. · 04.02.2027')
        done = page.locator('[data-work-id="Корпус 3-0"]')
        expect(done.locator('.gpr-cell-forecast')).to_have_text('Готово')
        assert 'Закончено на 8 дн. позже плана' in done.get_attribute('title')
        expect(done.locator('.gpr-cell-forecast')).not_to_contain_text('06.11.2026')
        expect(page.locator('[data-work-id="ПАРКИНГ-0"] .gpr-cell-forecast')).to_have_text('Нет прогноза')
        expect(page.locator('#gprFactMatrix')).not_to_contain_text('2035')
        assert not errors


@pytest.mark.parametrize('context_change', ['none', 'project', 'key', 'clear'])
def test_late_afterprint_cannot_restore_another_context(monkeypatch, context_change):
    view = matrix_view()
    serve_view(monkeypatch, view)
    with browser_page() as (page, _, errors):
        settled(page, view)
        page.evaluate("()=>{expanded.add('corpus:Корпус 1');beginGprPrint()}")
        assert page.evaluate("document.body.classList.contains('gpr-print-mode')")
        if context_change != 'none':
            page.evaluate("(change)=>{if(change==='project')$('project').value='Другой проект';if(change==='key')localStorage.setItem(ADMIN_KEY,'another-synthetic-key');if(change==='clear')clearReadiness();expanded.clear();expanded.add('new-context-choice')}", context_change)
        page.evaluate("window.dispatchEvent(new Event('afterprint'))")
        assert not page.evaluate("document.body.classList.contains('gpr-print-mode')")
        assert page.evaluate('[...expanded]') == (['corpus:Корпус 1'] if context_change == 'none' else ['new-context-choice'])
        if context_change == 'clear':
            expect(page.locator('#gprFactMatrix [data-work-id]')).to_have_count(0)
        assert not errors


def test_a4_pdf_includes_closed_stages_hidden_tail_and_undated_work(monkeypatch, tmp_path):
    view = matrix_view(22)
    source = copy.deepcopy(view)
    task = view['schedule']['management'][0]['children'][0]['children'][0]['children'][0]
    view['schedule']['undated_works'] = [dict(task, id='undated', name='Последняя работа без плановых дат',
        section='Последний этап', plan_start=None, plan_finish=None, reason='Нет даты в источнике')]
    serve_view(monkeypatch, view)
    with browser_page(390) as (page, _, errors):
        settled(page, view)
        before = page.locator('.gpr-matrix-stage[open]').evaluate_all('(xs)=>xs.map(x=>x.dataset.stage)')
        assert page.locator('.gpr-matrix-tail[hidden]').count() > 0
        pdf = tmp_path/'matrix.pdf'
        page.pdf(path=str(pdf), prefer_css_page_size=True, print_background=False)
        reader = PdfReader(pdf)
        assert 1 < len(reader.pages) < 15
        assert all(float(p.mediabox.width)>800 and float(p.mediabox.height)<650 for p in reader.pages)
        text = ''.join(''.join(p.extract_text().split()) for p in reader.pages)
        assert 'Последняяработабезплановыхдат' in text
        # Each task prints its own observation once, including identical names
        # across objects and the row with no plan dates. Name membership alone
        # would pass if a whole object's cells silently disappeared.
        assert text.count('06.11.2026') == 89
        for row in source['schedule']['management'][0]['children'][0]['children'][0]['children']:
            assert ''.join(row['name'].split()) in text
        for obj in ['Корпус1', 'Корпус2', 'Корпус3', 'ПАРКИНГ']:
            assert obj in text
        assert '08.11.2026' in text
        assert page.locator('.gpr-matrix-stage[open]').evaluate_all('(xs)=>xs.map(x=>x.dataset.stage)') == before
        assert page.locator('#gantt .lvl-task').count() == 0
        assert not errors
