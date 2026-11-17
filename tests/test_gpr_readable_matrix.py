"""The native matrix keeps source facts, qualified dates and every printed work.

Only synthetic observations are kept in git. The owner-source replay remains
private, and does not turn the unweighted project into a confirmed percentage.
"""
import copy
import re
from collections import Counter
from datetime import date

import pytest
from playwright.sync_api import expect
from pypdf import PdfReader

from test_monitor_cumulative_controls import Responses, browser_page
from test_monitor_gpr_sections import monitor_view
from gpr_view_fixtures import legacy_response


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
            return route.fulfill(json=legacy_response(view))
        # The successful view also loads this GET. The general contracts
        # fixture admits POST body keys only; it cannot represent that GET.
        if path.endswith('/monitor/daily/summary'):
            return route.fulfill(json={'rows': []})
        return original(self, route)

    monkeypatch.setattr(Responses, '__call__', response)


def settled(page, view):
    page.wait_for_function('currentView!==null&&!$("refresh").disabled')
    page.locator('#cut').fill(view['cut'])
    page.evaluate('(v)=>{currentView=v;renderGantt(v)}', legacy_response(view))


@pytest.mark.parametrize('stage_count', [1, 2])
def test_expand_all_opens_hidden_work_tails_even_when_all_stages_are_open(monkeypatch, stage_count):
    view = matrix_view(8)
    tasks = view['schedule']['management'][0]['children'][0]['children'][0]['children']
    if stage_count == 1:
        for task in tasks:
            task['section'] = 'Единственный этап'
    serve_view(monkeypatch, view)
    with browser_page() as (page, _, errors):
        settled(page, view)
        stages = page.locator('#gprFactMatrix .gpr-matrix-stage')
        expect(stages).to_have_count(stage_count)
        for stage in stages.all():
            if stage.get_attribute('open') is None:
                stage.locator(':scope > summary').click()
        expect(page.locator('.gpr-matrix-stage[open]')).to_have_count(stage_count)
        expect(page.locator('.gpr-matrix-tail[hidden]')).to_have_count(stage_count)
        assert page.locator('#gprFactMatrix [data-work-id]:visible').count() < len(tasks)
        button = page.get_by_role('button', name='Раскрыть все этапы', exact=True)
        for _ in range(2):
            button.click()
            expect(stages.locator('[data-work-id]:visible')).to_have_count(len(tasks))
            expect(page.locator('.gpr-matrix-stage[open]')).to_have_count(stage_count)
            expect(page.locator('.gpr-matrix-tail[hidden]')).to_have_count(0)
            expect(button).to_have_text('Раскрыть все этапы')
        assert not errors


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
        expect(page.locator('[data-work-id="ПАРКИНГ-0"] .gpr-cell-forecast')).to_have_text('Срок не определён')
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


def capture_next_print_observations(page):
    # beforeprint runs before Chromium switches media itself. Read the effective
    # print layout, including CSS-unhidden tails, rather than screen visibility.
    page.emulate_media(media='print')
    page.evaluate("""()=>window.addEventListener('beforeprint',()=>{
        const visible=e=>!!e.getClientRects().length&&getComputedStyle(e).display!=='none'&&getComputedStyle(e).visibility!=='hidden';
        window.gprPrintedObservations={
            matrix:[...document.querySelectorAll('#gprFactMatrix .gpr-fact-cell[data-work-id]')].map(e=>({
                id:e.dataset.workId,object:e.dataset.object,column:e.closest('[data-matrix-object]').dataset.matrixObject,
                name:e.closest('tr').querySelector('th[scope=row]').textContent,fact:e.querySelector('b').textContent,
                visible:visible(e),dates:[...e.querySelectorAll('.gpr-cell-date')].filter(visible).map(x=>x.textContent)})),
            gantt:[...document.querySelectorAll('#gantt .lvl-task[data-work-id]')].map(e=>({
                id:e.dataset.workId,name:e.querySelector('.title').textContent,
                reference:e.querySelector('.gpr-print-reference').textContent,visible:visible(e),
                readings:[...e.querySelectorAll('.work-progress,.gpr-compact-print-metrics>div:first-child')].filter(visible).map(x=>x.textContent)}))};
    },{once:true})""")


def assert_printed_observations(view, coverage, pdf_text):
    rows = [*view['schedule']['management'][0]['children'][0]['children'][0]['children'],
            *view['schedule'].get('undated_works', [])]
    expected = {row['id']: row for row in rows}
    assert len(expected) == len(rows), 'source work identities must be unique'
    for scope in ['matrix', 'gantt']:
        actual = coverage[scope]
        assert Counter(row['id'] for row in actual) == Counter(expected.keys()), scope+' identity mismatch'
        for row in actual:
            source = expected[row['id']]
            observation = date.fromisoformat(source['progress_source']['date']).strftime('%d.%m.%Y')
            fact = f"{source['actual_progress']:.0%}"
            assert row['visible'], scope+' hidden work: '+row['id']
            assert row['name'] == source['name'], scope+' name mismatch: '+row['id']
            if scope == 'matrix':
                assert row['object'] == row['column'] == source['object']
                assert row['fact'] == fact
                assert row['dates'] == [observation], 'matrix observation mismatch: '+row['id']
            else:
                assert row['reference'] == 'Работа '+source['wbs']
                assert len(row['readings']) == 1, 'gantt observation mismatch: '+row['id']
                reading = row['readings'][0]
                assert reading.count(observation) == 1
                assert re.findall(r'(?<![\d.,])\d+(?:[.,]\d+)?%', reading) == [fact]
    # The full, unmodified PDF retains both surfaces. The visible native axis
    # heading separates their actual text; no diagnostic style hides either.
    compact = lambda value: ''.join(value.split())
    axis = 'Корпус, этап и работа'
    assert pdf_text.count(axis) == 1
    matrix_pdf, gantt_pdf = pdf_text.split(axis)
    assert 'Матрицапланаивыполнения' in compact(matrix_pdf)
    observations = Counter(date.fromisoformat(row['progress_source']['date']).strftime('%d.%m.%Y') for row in rows)
    for observation, count in observations.items():
        assert compact(matrix_pdf).count(observation) == count
        assert compact(gantt_pdf).count(observation) == count
        assert compact(pdf_text).count(observation) == count+count
    # Human WBS references bind the printed Gantt to each work, including the
    # undated clone whose real reference intentionally repeats the first WBS.
    expected_refs = Counter(compact('Работа '+row['wbs']) for row in rows)
    printed_lines = Counter(compact(line) for line in gantt_pdf.splitlines())
    assert {ref: printed_lines[ref] for ref in expected_refs} == dict(expected_refs)


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
        capture_next_print_observations(page)
        page.pdf(path=str(pdf), prefer_css_page_size=True, print_background=False)
        reader = PdfReader(pdf)
        assert 1 < len(reader.pages) < 15
        assert all(float(p.mediabox.width)>800 and float(p.mediabox.height)<650 for p in reader.pages)
        pdf_text = '\n'.join(p.extract_text() for p in reader.pages)
        text = ''.join(pdf_text.split())
        assert 'Последняяработабезплановыхдат' in text
        # Every work prints once in each surface, including identical names
        # across objects and the undated row. A global count cannot bind cells.
        assert_printed_observations(view, page.evaluate('gprPrintedObservations'), pdf_text)
        page.emulate_media(media='screen')
        for row in source['schedule']['management'][0]['children'][0]['children'][0]['children']:
            assert ''.join(row['name'].split()) in text
        for obj in ['Корпус1', 'Корпус2', 'Корпус3', 'ПАРКИНГ']:
            assert obj in text
        assert '08.11.2026' in text
        assert page.locator('.gpr-matrix-stage[open]').evaluate_all('(xs)=>xs.map(x=>x.dataset.stage)') == before
        assert page.locator('#gantt .lvl-task').count() == 0
        assert not errors


@pytest.mark.parametrize('mutation', ['hide-object', 'duplicate-cell'])
def test_pdf_observation_oracle_rejects_missing_object_and_replaced_duplicate(monkeypatch, tmp_path, mutation):
    view = matrix_view(22)
    task = view['schedule']['management'][0]['children'][0]['children'][0]['children'][0]
    view['schedule']['undated_works'] = [dict(task, id='undated', name='Последняя работа без плановых дат',
        section='Последний этап', plan_start=None, plan_finish=None, reason='Нет даты в источнике')]
    serve_view(monkeypatch, view)
    with browser_page(390) as (page, _, errors):
        settled(page, view)
        page.evaluate("""mutation=>window.addEventListener('beforeprint',()=>{
            if(mutation==='hide-object'){
                for(const cell of document.querySelectorAll('#gprFactMatrix [data-matrix-object="Корпус 2"]'))cell.style.display='none';
            }else{
                const cell=document.querySelector('#gprFactMatrix [data-work-id="Корпус 1-6"]');
                cell.parentNode.appendChild(cell.cloneNode(true));
                // Compensate the global date count: membership must still fail.
                document.querySelector('#gprFactMatrix [data-work-id="Корпус 2-6"]').style.display='none';
            }
        },{once:true})""", mutation)
        capture_next_print_observations(page)
        pdf = tmp_path/(mutation+'.pdf')
        page.pdf(path=str(pdf), prefer_css_page_size=True, print_background=False)
        pdf_text = '\n'.join(p.extract_text() for p in PdfReader(pdf).pages)
        if mutation == 'duplicate-cell':
            # An aggregate date count alone accepts this missing/replaced cell.
            assert ''.join(pdf_text.split()).count('06.11.2026') == 2*89
        with pytest.raises(AssertionError, match='matrix'):
            assert_printed_observations(view, page.evaluate('gprPrintedObservations'), pdf_text)
        assert not errors
