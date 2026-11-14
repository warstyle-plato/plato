"""Actual Monitor UI: one GPR view, separate money/data, and no stale PM facts."""
import pytest

import developaid_schedule_timeline as timeline
from browser import expand_gantt
from test_monitor_cumulative_controls import browser_page


def monitor_view(state='estimate'):
    task = {'id': '1', 'wbs': '1.1', 'level': 'task', 'object': 'Корпус 1',
            'name': 'Монтаж фасада', 'plan_start': '2026-10-01', 'plan_finish': '2026-12-01',
            'pace_progress': .4, 'actual_progress': .4, 'progress_kind': 'gpr_percent',
            'progress_source': {'kind': 'gpr', 'label': 'ГПР', 'date': '2026-11-06'},
            'pace_forecast_method': 'gpr_pace',
            'pace_forecast_known': True, 'forecast_finish': '2026-12-20', 'delta_days': 19}
    unknown = dict(task, id='2', wbs='1.2', name='Внутренние работы', pace_progress=0,
                   actual_progress=0, pace_forecast_method='stalled', pace_forecast_known=False,
                   forecast_finish='2031-01-01')
    legacy = dict(task, id='3', wbs='1.3', name='Старый денежный темп', pace_progress=.99,
                  progress_kind='accepted_cost_ratio', actual_progress=.99, pace_forecast_method='accepted_cost_pace', forecast_finish='2035-01-01', delta_days=2999)
    q = {'basis': 'gpr', 'state': state, 'approved': '2026-12-01',
         'forecast': '2026-12-20' if state == 'estimate' else None,
         'indicative_forecast': '2026-12-20' if state == 'partial' else None,
         'delay_days': 19 if state != 'unknown' else None, 'driving_chain': [],
         'reasons': ['Техническая подробность источника.']}
    block = {'rnv': q, 'rows': [], 'edges': []}
    return {'cut': '2026-11-08', 'schedule': {'management': [
        {'level': 'control', 'name': 'Стройка', 'children': [
            {'level': 'detail', 'name': 'Строительные работы', 'children': [
                {'level': 'rss', 'name': 'Фасады', 'code': '2.2', 'eac': 100, 'accepted': 99,
                 'actual_progress': .99, 'children': [task, unknown, legacy]}]}]}],
        'dependency_timeline': block, 'dependency_timeline_html': timeline.render(block)},
        'dashboard': {'schedule': {'qualified_rnv': q}}}


def render(page, view):
    page.evaluate("(v)=>{currentView=v;msg('viewMsg','');renderDash(v);renderGantt(v)}", view)
    expand_gantt(page)


@pytest.mark.parametrize('width', [390, 1440])
def test_gpr_is_default_and_money_uploads_and_contracts_have_their_own_sections(width):
    from playwright.sync_api import expect
    with browser_page(width) as (page, responses, errors):
        render(page, monitor_view())
        expect(page.get_by_role('tab', name='ГПР: план и факт')).to_have_attribute('aria-selected', 'true')
        expect(page.locator('#ganttCard')).to_be_visible()
        expect(page.locator('#financeCard')).to_be_hidden()
        expect(page.locator('#setupCard')).to_be_hidden()
        expect(page.locator('#monitorPanel')).not_to_contain_text('КС/EAC proxy')
        assert page.locator('#gantt .lvl-rss').count() == 0
        assert page.locator('#gantt .lvl-task').count() == 3
        # Corpus and stage aggregates never turn money into a physical percent.
        assert page.evaluate("managementByCorpus(currentView.schedule.management).every(x=>x.actual_progress===null)")
        expect(page.locator('#gantt')).to_contain_text('Выполнено по ГПР: 40%')
        expect(page.locator('#gantt')).to_contain_text('Работа стоит')
        legacy = page.locator('.g-row.lvl-task', has_text='Старый денежный темп')
        assert legacy.locator('.factbar, .forecastmark, .latebar').count() == 0
        expect(legacy).not_to_contain_text('99%')
        expect(legacy).not_to_contain_text('2035')
        assert page.locator('#scenarioCalculations').is_hidden()
        assert page.locator('#forecastCard').is_hidden()  # shared GPR qualification is the single date block
        assert page.locator('#gantt .funding-zone, #gantt .limit-mark').count() == 0
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path=f'/tmp/plato1041-gpr-{width}.png', full_page=True)
        page.locator('#moneyTab').click()
        expect(page.locator('#dashCard')).to_be_visible()
        expect(page.locator('#ganttCard')).to_be_hidden()
        page.locator('#dataTab').click()
        expect(page.locator('#setupCard')).to_be_visible()
        expect(page.locator('#siteAccessCard')).to_be_visible()
        expect(page.locator('#dashCard')).to_be_hidden()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.locator('#contractsTab').click()
        expect(page.locator('#contractsRows')).to_contain_text('Д-01')
        expect(page.locator('#monitorPanel')).to_be_hidden()
        page.locator('#contractsUploadLink').click()
        expect(page.locator('#dataTab')).to_have_attribute('aria-selected', 'true')
        expect(page.locator('#cumulativeUpload')).to_be_visible()
        assert not errors


@pytest.mark.parametrize('state', ['estimate', 'partial', 'unknown'])
def test_qualified_dates_keep_their_meaning_and_method_is_disclosed(state):
    from playwright.sync_api import expect
    with browser_page() as (page, responses, errors):
        render(page, monitor_view(state))
        summary = page.locator('#dependencyTimelineBody')
        expect(summary).to_contain_text('Оценка по ГПР')
        if state == 'estimate':
            expect(summary.locator('.schedule-rnv-cards>div:nth-child(2)>strong')).to_have_text('20.12.2026')
            expect(summary.locator('.schedule-rnv-cards>div:nth-child(2)>span')).to_have_text('Оценка по ГПР')
        elif state == 'partial':
            expect(summary.locator('.schedule-rnv-cards')).to_contain_text('неполный')
            expect(summary.locator('.schedule-note').last).to_contain_text('Для части работ нет прогноза')
        else:
            expect(summary.locator('.schedule-rnv-cards')).to_contain_text('недостаточно данных')
        expect(summary.get_by_text('Техническая подробность источника.', exact=True)).to_be_hidden()
        summary.locator('details>summary').last.click()
        expect(summary.get_by_text('Техническая подробность источника.', exact=True)).to_be_visible()
        assert not errors


def test_empty_project_and_keyboard_tabs_keep_the_data_action_and_private_auth():
    from playwright.sync_api import expect
    with browser_page() as (page, responses, errors):
        render(page, {'schedule': {'management': []}})
        expect(page.locator('#gprEmpty')).to_be_visible()
        expect(page.locator('#forecastCard')).to_contain_text('Итоговая дата пока не определена')
        page.locator('#gprDataButton').click()
        expect(page.locator('#dataPanel')).to_be_visible()
        page.locator('#dataTab').press('Home')
        expect(page.locator('#monitorTab')).to_have_attribute('aria-selected', 'true')
        page.locator('#project').fill('Другой проект')
        expect(page.locator('#gprEmpty')).to_contain_text('Нажмите «Обновить»')
        expect(page.locator('#ganttCard')).to_be_hidden()
        page.evaluate("localStorage.removeItem('plato_projects_key');syncAuthUi()")
        expect(page.locator('#privateArea')).to_be_hidden()
        assert not errors


def test_pm_response_is_not_presented_as_current_gpr_forecast():
    from playwright.sync_api import expect
    with browser_page() as (page, responses, errors):
        view = monitor_view()
        view['schedule']['dependency_timeline']['rnv'].pop('basis')
        view['schedule']['dependency_timeline_html'] = '<p>Старый PM прогноз 2035</p>'
        render(page, view)
        expect(page.locator('#dependencyTimelineCard')).to_be_hidden()
        expect(page.locator('#forecastCard')).to_contain_text('Итоговая дата пока не определена')
        expect(page.locator('#monitorPanel')).not_to_contain_text('Старый PM прогноз')
        assert not errors


def test_corpus_source_without_baseline_opens_readable_actuals_without_forecast():
    from playwright.sync_api import expect
    import developaid_gpr_corpus as corpus
    from test_gpr_corpus_preview import book
    with browser_page() as (page, responses, errors):
        view = {'schedule': {'management': []}}
        render(page, view)
        html = corpus.render_overview(corpus.read(book(bad_date='30.06.2027', name='Монтаж фасада')), '2026-11-08')
        page.evaluate('(html)=>renderCorpusGprSource({html})', html)
        expect(page.locator('#corpusGprCard')).to_have_attribute('open', '')
        expect(page.locator('#corpusGprCard')).to_contain_text('Корпус')
        expect(page.locator('#gprEmpty')).to_contain_text('Показания ГПР доступны ниже')
        expect(page.locator('#forecastCard')).to_contain_text('Итоговая дата пока не определена')
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path='/tmp/plato1041-source-only-390.png', full_page=True)
        assert not errors


@pytest.mark.parametrize('width', [390, 1440])
def test_multiple_corps_show_works_zero_unknown_and_fact_source_without_extra_clicks(width):
    from playwright.sync_api import expect
    view = monitor_view('partial')
    tasks = view['schedule']['management'][0]['children'][0]['children'][0]['children']
    tasks.extend([dict(tasks[0], id='4', wbs='2.1', object='Корпус 2', name='Кладка стен', actual_progress=None, pace_progress=None, pace_forecast_method='stale', pace_forecast_known=False),
                  dict(tasks[0], id='5', wbs='2.2', object='Корпус 2', name='Подготовка площадки', actual_progress=1, pace_progress=1, pace_forecast_method='done', work_done=True, actual_finish='2026-11-06', forecast_finish='2026-11-06', delta_days=-25),
                  dict(tasks[0], id='6', wbs='2.3', object='Корпус 2', name='Котлован', actual_progress=1, pace_progress=1, pace_forecast_method='done', work_done=True, pace_forecast_known=True, forecast_finish='2026-10-01', observed_complete_by='2026-10-01', delta_days=None),
                  dict(tasks[0], id='7', wbs='2.4', object='Корпус 2', name='Кровля', actual_progress=.5, pace_progress=.5, pace_forecast_method='gpr_pace', pace_forecast_known=True, forecast_finish='2026-12-13', delta_days=12)])
    with browser_page(width) as (page, responses, errors):
        render(page, view)
        expect(page.locator('#gantt')).to_contain_text('Корпус 1')
        expect(page.locator('#gantt')).to_contain_text('Корпус 2')
        assert page.locator('#gantt .lvl-task:visible').count() == 7
        observed = page.locator('.g-row.lvl-task', has_text='Котлован')
        expect(observed).to_contain_text('100% на дату 01.10.2026')
        expect(observed).not_to_contain_text('Позже плана')
        corpus2 = page.locator('.g-row.lvl-corpus', has_text='Корпус 2')
        # Устаревший ГПР — не «нет данных о темпе»: причина та же, что у строки работы.
        expect(corpus2).to_contain_text('Срок корпуса пока не оценить: у 1 работы нет прогноза срока.')
        expect(corpus2).to_contain_text('Без прогноза: Кладка стен — нужен свежий ГПР.')
        expect(corpus2).to_contain_text('Позже своего срока: 1 работа, больше всего — на 12 дн.')
        expect(corpus2).not_to_contain_text('Позже плана')
        done = page.locator('.g-row.lvl-task', has_text='Подготовка площадки')
        expect(done).to_contain_text('План до 01.12.2026. Завершено 06.11.2026')
        assert done.locator('.forecastmark,.latebar,.aheadbar').count() == 0
        expect(done).not_to_contain_text('Оценка 20.12.2026')
        expect(page.locator('#gantt')).to_contain_text('Выполнено по ГПР: 0%')
        expect(page.locator('#gantt')).to_contain_text('Выполнение не указано')
        expect(page.locator('#gantt')).to_contain_text('от 06.11.2026')
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path=f'/tmp/plato1041-multiple-corps-{width}.png', full_page=True)
        assert not errors


def test_known_cumulative_progress_survives_unknown_forecast_and_is_not_the_gpr_edit_value():
    from playwright.sync_api import expect
    view = monitor_view('partial')
    task = view['schedule']['management'][0]['children'][0]['children'][0]['children'][0]
    task.update(progress_kind='cumulative_quantities', actual_progress=.5, pace_progress=.5,
                progress_source={'kind': 'cumulative_quantities', 'label': 'Накопительные', 'date': '2026-11-06'},
                gpr_progress=.2, pace_forecast_method='cumulative_unknown', pace_forecast_known=False,
                forecast_finish=None, forecast_reason='Нет свежего датированного темпа накопительных.')
    with browser_page() as (page, responses, errors):
        render(page, view)
        row = page.locator('.g-row.lvl-task', has_text='Монтаж фасада')
        expect(row).to_contain_text('Объём по накопительной: 50%')
        expect(row).to_contain_text('Нет свежего датированного темпа накопительных')
        assert row.locator('.forecastmark,.latebar').count() == 0
        row.click()
        expect(page.locator('#detailGrid')).to_contain_text('Объём по накопительной')
        expect(page.locator('#detailGrid')).to_contain_text('50%')
        expect(page.locator('#wfPct')).to_have_value('20')
        expect(page.locator('#workFactBox')).to_contain_text('Уточнить выполнение в ГПР')
        assert not errors


def test_explicitly_confirmed_completion_is_a_dated_fact_without_a_forecast_tail():
    from playwright.sync_api import expect
    view = monitor_view()
    task = view['schedule']['management'][0]['children'][0]['children'][0]['children'][0]
    task.update(progress_kind='confirmed_completion', actual_progress=1, pace_progress=1,
                progress_source={'kind': 'confirmed_completion', 'label': 'Подтверждённое завершение', 'date': '2026-11-06'},
                gpr_progress=None, pace_forecast_method='confirmed_completion', work_done=True, pace_forecast_known=True,
                forecast_finish='2026-11-06', delta_days=-25)
    with browser_page() as (page, responses, errors):
        render(page, view)
        row = page.locator('.g-row.lvl-task', has_text='Монтаж фасада')
        expect(row).to_contain_text('Завершение подтверждено')
        expect(row).to_contain_text('Завершено 06.11.2026')
        expect(row).to_contain_text('Выполнение подтверждено: 100%')
        assert row.locator('.forecastmark,.latebar,.aheadbar').count() == 0
        row.click()
        expect(page.locator('#wfPct')).to_have_value('')
        expect(page.locator('#detailGrid')).to_contain_text('Фактическое окончание')
        expect(page.locator('#detailGrid')).not_to_contain_text('100% в ГПР на дату')
        page.locator('#wfSave').click()
        expect(page.locator('#wfMsg')).to_contain_text('Введите процент выполнения в ГПР')
        assert not any(path == '/monitor/work-fact' for path, *_ in responses.calls)
        assert not errors


@pytest.mark.parametrize('width', [390, 1440])
def test_gantt_opens_works_and_retains_corpus_and_stage_collapse_controls(width):
    """The matrix shows work progress first; the calendar keeps native controls."""
    from playwright.sync_api import expect
    with browser_page(width) as (page, responses, errors):
        page.evaluate("(v)=>{currentView=v;msg('viewMsg','');renderDash(v);renderGantt(v)}", monitor_view())
        expect(page.locator('#gprFactMatrix [data-work-id]')).to_have_count(3)
        assert page.locator('#gantt .g-row.lvl-task:visible').count() == 0
        page.locator('#gprCalendar>summary').click()
        corpora = page.locator('#gantt .g-row.lvl-corpus')
        expect(corpora.first).to_be_visible()
        page.locator('#ganttExpand').click()
        assert page.locator('#gantt .g-row.lvl-task:visible').count() == 3
        page.locator('#ganttCollapse').click()
        assert page.locator('#gantt .g-row.lvl-task').count() == 0
        expect(corpora.first.locator('.chev')).to_have_text('▸')
        corpora.first.click()
        expect(page.locator('#gantt .g-row.lvl-stage').first).to_be_visible()
        assert page.locator('#gantt .g-row.lvl-task').count() == 0
        page.locator('#gantt .g-row.lvl-stage').first.click()
        expect(page.locator('#gantt .g-row.lvl-task').first).to_be_visible()
        assert not errors


@pytest.mark.parametrize('width', [390, 1440])
def test_work_matrix_and_all_corpora_expand_without_losing_completion(width):
    """The source matrix remains useful before the unweighted calendar opens."""
    from playwright.sync_api import expect
    view = monitor_view('partial')
    control = view['schedule']['management'][0]
    tasks = control['children'][0]['children'][0]['children']
    base = tasks[0]
    tasks.extend([dict(base, id='4', wbs='2.1', object='Корпус 2', name='Кладка стен', actual_progress=None, pace_progress=None, pace_forecast_method='stale', pace_forecast_known=False),
                  dict(base, id='7', wbs='2.4', object='Корпус 2', name='Кровля', actual_progress=.5, pace_progress=.5, pace_forecast_method='gpr_pace', pace_forecast_known=True, forecast_finish='2026-12-13', delta_days=12),
                  dict(base, id='8', wbs='3.1', object='Корпус 3', name='Монолит', actual_progress=1, pace_progress=1, pace_forecast_method='done', work_done=True, actual_finish='2026-10-01', forecast_finish='2026-10-01', delta_days=None)])
    control['children'].insert(0, {'level': 'detail', 'name': 'Проектирование', 'children': [
        {'level': 'rss', 'name': 'Проект', 'code': '1.1', 'children': [
            dict(base, id='9', wbs='0.1', object='Корпус 1', name='Рабочая документация', pace_forecast_method='plan', pace_forecast_known=False, forecast_known=False, forecast_finish=None, delta_days=None)]}]})
    with browser_page(width) as (page, responses, errors):
        page.evaluate("(v)=>{currentView=v;msg('viewMsg','');renderDash(v);renderGantt(v)}", view)
        assert page.locator('#gprMatrix, .gpr-matrix').count() == 0
        expect(page.locator('#gprFactMatrix [data-work-id]')).to_have_count(7)
        assert page.locator('#gantt .g-row.lvl-task:visible').count() == 0
        expand_gantt(page)
        assert page.locator('#gantt .g-row.lvl-task:visible').count() == 7
        done = page.locator('#gantt .g-row.lvl-corpus', has_text='Корпус 3')
        expect(done).to_contain_text('Все работы завершены')
        expect(done).not_to_contain_text('Оценка')
        page.locator('#ganttCollapse').click()
        assert page.locator('#gantt .g-row.lvl-task').count() == 0
        page.locator('#ganttExpand').click()
        expect(page.locator('#gantt .g-row.lvl-task', has_text='Кровля')).to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert not errors


def test_cell_and_corpus_row_agree_on_finished_late_no_forecast_and_current_delay():
    """Владелец (п.3, вариант А): законченная позже плана работа — «Закончено на
    N дн. позже плана» и в клетке сводки, и в строке корпуса; текущим
    опозданием она не считается. Корпус без единого прогноза — «Срок пока не оценить»."""
    from playwright.sync_api import expect
    view = monitor_view('partial')
    base = view['schedule']['management'][0]['children'][0]['children'][0]['children'][0]
    done = dict(base, pace_progress=1, actual_progress=1, pace_forecast_method='confirmed_completion',
                progress_kind='confirmed_completion', work_done=True, observed_complete_by=None)
    view['schedule']['management'][0]['children'][0]['children'][0]['children'] = [
        dict(base, id='1', object='Корпус 1', name='Кладка', pace_forecast_method='stale', pace_forecast_known=False, delta_days=None),
        dict(done, id='2', object='Корпус 2', name='Котлован', actual_finish='2026-11-20', forecast_finish='2026-11-20', delta_days=50, finished_late_days=50),
        dict(base, id='3', object='Корпус 2', name='Монолит', delta_days=0, forecast_finish='2026-12-01'),
        dict(done, id='4', object='Корпус 3', name='Сваи', actual_finish='2026-12-31', forecast_finish='2026-12-31', delta_days=30, finished_late_days=30)]
    with browser_page(1440) as (page, responses, errors):
        page.evaluate("(v)=>{currentView=v;msg('viewMsg','');renderDash(v);renderGantt(v)}", view)
        corpus = lambda name: page.locator('#gantt .g-row.lvl-corpus', has_text=name)
        expect(corpus('Корпус 2')).to_contain_text('По сроку')
        # У корпуса — «среди законченных работ», чтобы не читалось как окончание всего корпуса.
        expect(corpus('Корпус 2')).to_contain_text('Среди законченных работ: закончено на 50 дн. позже плана.')
        expect(corpus('Корпус 2')).not_to_contain_text('Закончено на')
        expect(corpus('Корпус 2')).not_to_contain_text('Позже плана на')
        expect(corpus('Корпус 3')).to_contain_text('Все работы завершены')
        expect(corpus('Корпус 3')).to_contain_text('Среди законченных работ: закончено на 30 дн. позже плана')
        expand_gantt(page)
        expect(page.locator('#gantt .g-row.lvl-task', has_text='Котлован')).to_contain_text('Закончено на 50 дн. позже плана')
        assert not errors


def test_the_page_takes_done_from_the_server_and_keeps_a_100_percent_reading_out_of_the_section_date():
    """«Работа закончена» решает сервер (`work_done`); дата показания 100%
    (`observed_complete_by`) не становится сроком корпуса, как в движке и отчёте."""
    from playwright.sync_api import expect
    view = monitor_view('partial')
    base = view['schedule']['management'][0]['children'][0]['children'][0]['children'][0]
    view['schedule']['management'][0]['children'][0]['children'][0]['children'] = [
        dict(base, id='1', object='Корпус 1', name='Котлован', actual_progress=1, pace_progress=1, pace_forecast_method='done',
             work_done=True, forecast_finish='2026-10-07', observed_complete_by='2026-10-07', delta_days=None),
        dict(base, id='2', object='Корпус 1', name='Монолит', forecast_finish='2026-09-15', delta_days=0),
        # Метод «done» без решения сервера — не законченная работа.
        dict(base, id='3', object='Корпус 2', name='Кровля', actual_progress=1, pace_progress=1, pace_forecast_method='done',
             work_done=False, forecast_finish='2026-12-20', delta_days=19)]
    with browser_page(1440) as (page, responses, errors):
        page.evaluate("(v)=>{currentView=v;msg('viewMsg','');renderDash(v);renderGantt(v)}", view)
        first = page.locator('#gantt .g-row.lvl-corpus', has_text='Корпус 1')
        expect(first).to_contain_text('Оценка 15.09.2026')
        expect(first.locator('.g-metrics')).to_contain_text('Оценка 15.09.2026')
        # Дата показания 100% (07.10) отлична от плановых дат образца и не
        # появляется нигде в строке корпуса, включая подписи дат телефона.
        expect(first).not_to_contain_text('07.10.2026')
        assert page.locator('#gprMatrix').count() == 0
        assert not errors


def test_a_work_with_only_a_plan_and_no_pace_is_not_on_time(tmp_path, monkeypatch):
    """Владелец (п. А): работа только с планом, темп которой неизвестен, — «без
    прогноза», а не «по сроку»: в клетке сводки, в строке корпуса и в сводке
    руководству. «По сроку» — только там, где темп известен."""
    import datetime as dt
    from playwright.sync_api import expect
    import developaid_management_report as report
    import developaid_monitor as monitor
    import developaid_monitor_pace as pace
    import developaid_report_gantt as report_gantt
    from test_monitor_management_gantt import _gpr_book
    project, cut = 'Учебный график', dt.date(2026, 11, 6)
    monkeypatch.setattr(monitor, '_SNAPSHOT_DIR', tmp_path)
    monitor.store_schedule(project, _gpr_book([
        (1, 'Каркас', .2, dt.date(2026, 9, 1), dt.date(2027, 6, 30), 'В работе', '2.2.1.1'),
        (2, 'Кровля', .2, dt.date(2026, 9, 1), dt.date(2027, 5, 31), 'В работе', '2.2.1.1'),
    ]), None, '2026-10-01')
    import developaid_monitor_page  # noqa: F401
    real = pace.gpr_forecast.forecasts

    def plan_and_pace(*args, **kwargs):
        works = real(*args, **kwargs)
        works['1'] = dict(works.get('1') or {}, method='plan', progress=.2, forecast_finish='2027-06-30',
                          reason='Срок по плану ещё не наступил; роста процента за 90 дней нет — показан план.')
        works['2'] = dict(works.get('2') or {}, method='gpr_pace', progress=.2, forecast_finish='2027-05-31')
        return works
    monkeypatch.setattr(pace.gpr_forecast, 'forecasts', plan_and_pace)
    view = monitor.build(project, cut)
    nodes = pace._walk(view['schedule']['management'])
    tasks = {n.get('id'): n for n in nodes if n.get('level') == 'task'}
    assert tasks['1']['forecast_known'] is False and tasks['1']['pace_forecast_known'] is False
    assert tasks['1']['forecast_finish'] is None and tasks['1']['delta_days'] is None
    assert tasks['2']['forecast_known'] is True and tasks['2']['delta_days'] == 0
    assert tasks['1']['pace_status'] == 'Темп неизвестен: прогноза нет'
    for node in nodes:
        if node.get('level') != 'task':
            assert node['forecast_partial'] is True and node['forecast_finish'] == '2027-05-31', node.get('name')
    line = report_gantt.text_lines(report_gantt.model(view['schedule']['management']))[0]
    # Отчёт говорит словами страницы: работа только с планом — «нет данных о темпе».
    assert line.endswith('; срок пока не оценить: у 1 работы нет данных о темпе (остальные идут по сроку).'), line
    assert 'в срок' not in line and 'по известным' not in line
    text = report.render_text(report.build(project, 'week', cut.isoformat()))
    assert 'срок пока не оценить: у 1 работы нет данных о темпе (остальные идут по сроку).' in text
    with browser_page(1440) as (page, responses, errors):
        page.evaluate("(v)=>{currentView=v;msg('viewMsg','');renderGantt(v)}",
                      {'cut': cut.isoformat(), 'schedule': {'management': view['schedule']['management']}})
        assert page.locator('#gprMatrix').count() == 0
        corpus = page.locator('#gantt .g-row.lvl-corpus')
        expect(corpus).to_contain_text('пока не оценить: у 1 работы нет данных о темпе.')
        expect(corpus).to_contain_text('Без данных о темпе: Каркас.')
        expect(corpus).not_to_contain_text('По сроку')
        expand_gantt(page)
        work = page.locator('#gantt .g-row.lvl-task', has_text='Каркас')
        expect(work).to_contain_text('Срок пока не оценить: нет данных о темпе.')
        expect(work).not_to_contain_text('По сроку')
        expect(page.locator('#gantt .g-row.lvl-task', has_text='Кровля')).to_contain_text('По сроку')
        assert not errors


@pytest.mark.parametrize('width', [390, 1440])
def test_works_left_out_for_unreadable_dates_are_named_above_the_gantt(width):
    from playwright.sync_api import expect
    view = monitor_view()
    view['schedule']['undated_works'] = [
        {'id': 'corpus:ГПР!E45', 'object': 'КОРПУС 1', 'section': 'Фасады', 'name': 'Каркас / Утеплитель',
         'reason': 'окончание «31.06.2027» не распознано (лист «ГПР», ячейка G45)'},
        {'id': 'corpus:ГПР!H45', 'object': 'КОРПУС 2', 'section': 'Фасады', 'name': 'Каркас / Утеплитель',
         'reason': 'окончание «31.06.2027» не распознано (лист «ГПР», ячейка J45)'}]
    with browser_page(width) as (page, responses, errors):
        render(page, view)
        notice = page.locator('#gprUndated')
        expect(notice).to_be_visible()
        expect(notice).to_contain_text('У 2 работ нужно проверить плановые даты.')
        expect(notice).to_contain_text('КОРПУС 1 · Фасады · Каркас / Утеплитель: '
                                       'окончание «31.06.2027» не распознано (лист «ГПР», ячейка G45).')
        expect(notice).to_contain_text('лист «ГПР», ячейка J45')
        box = notice.bounding_box()
        assert box['x'] >= 0 and box['x'] + box['width'] <= width + 1
        render(page, monitor_view())
        expect(notice).to_be_hidden()
        assert not errors


def test_one_undated_work_reads_in_the_singular_and_an_empty_plan_has_one_reason():
    from playwright.sync_api import expect
    undated = [{'object': 'КОРПУС 1', 'section': 'Фасады', 'name': 'Монтаж НВФ',
                'reason': 'окончание «31.06.2027» не распознано (лист «ГПР», ячейка G45)'}]
    with browser_page(1440) as (page, responses, errors):
        view = monitor_view()
        view['schedule']['undated_works'] = undated
        render(page, view)
        notice = page.locator('#gprUndated')
        expect(notice).to_contain_text('У 1 работы нужно проверить плановые даты.')
        expect(notice).to_contain_text('Работы и известное выполнение показаны ниже.')
        expect(notice).not_to_contain_text('ни у одной работы')
        empty = {'cut': '2026-11-08', 'schedule': {'management': [], 'rows': [], 'undated_works': undated,
                 'reason': 'В ГПР нет полных корректных дат. Работы и известные проценты доступны; плановые полосы пока построить нельзя.'}}
        render(page, empty)
        expect(notice).to_be_visible()
        expect(page.locator('#gantt .lvl-task')).to_contain_text('Монтаж НВФ')
        expect(page.locator('#gprEmpty')).to_be_hidden()
        assert 'нет работ утверждённого ГПР' not in page.locator('#monitorPanel').inner_text()
        assert not errors


def test_corpus_names_why_each_work_has_no_forecast_with_the_work_row_words():
    """Проверка интерфейса #1078: «нет данных о темпе» — только для работ с одним
    планом; стоящая работа и устаревший ГПР называются своей причиной — той
    же, что пишет строка самой работы."""
    from playwright.sync_api import expect
    view = monitor_view('partial')
    base = view['schedule']['management'][0]['children'][0]['children'][0]['children'][0]
    none = dict(base, pace_forecast_known=False, forecast_finish=None, delta_days=None)
    view['schedule']['management'][0]['children'][0]['children'][0]['children'] = [
        dict(none, id='1', name='Фасад', pace_forecast_method='plan'),
        dict(none, id='2', name='Окна', pace_forecast_method='stalled'),
        dict(none, id='3', name='Лифты', pace_forecast_method='stale'),
        dict(base, id='4', name='Кровля', delta_days=0, forecast_finish='2026-12-01')]
    with browser_page(1440) as (page, responses, errors):
        page.evaluate("(v)=>{currentView=v;msg('viewMsg','');renderDash(v);renderGantt(v)}", view)
        assert page.locator('#gprMatrix').count() == 0
        corpus = page.locator('#gantt .g-row.lvl-corpus')
        expect(corpus).to_contain_text('Срок корпуса пока не оценить: у 3 работ нет прогноза срока.')
        expect(corpus).to_contain_text(
            'Без прогноза: Фасад — нет данных о темпе; Окна — работа стоит; Лифты — нужен свежий ГПР.')
        expect(corpus).not_to_contain_text('По сроку')
        expand_gantt(page)
        work = lambda name: page.locator('#gantt .g-row.lvl-task', has_text=name).locator('.m-main')
        expect(work('Фасад')).to_have_text('Срок пока не оценить: нет данных о темпе.')
        expect(work('Окна')).to_have_text('Работа стоит. Прогноз неизвестен.')
        expect(work('Лифты')).to_have_text('Нужно свежее выполнение ГПР.')
        expect(work('Кровля')).to_contain_text('По сроку')
        assert not errors
    # Только «план» и «стоит»: стоящая работа не прячется в «нет данных о темпе».
    view['schedule']['management'][0]['children'][0]['children'][0]['children'] = [
        dict(none, id='1', name='Фасад', pace_forecast_method='plan'),
        dict(none, id='2', name='Окна', pace_forecast_method='stalled')]
    with browser_page(1440) as (page, responses, errors):
        page.evaluate("(v)=>{currentView=v;msg('viewMsg','');renderDash(v);renderGantt(v)}", view)
        assert page.locator('#gprMatrix').count() == 0
        corpus = page.locator('#gantt .g-row.lvl-corpus')
        expect(corpus).to_contain_text('Без прогноза: Фасад — нет данных о темпе; Окна — работа стоит.')
        assert not errors


def test_detail_card_names_a_100_percent_reading_as_a_reading_not_an_actual_finish():
    from playwright.sync_api import expect
    view = monitor_view()
    task = view['schedule']['management'][0]['children'][0]['children'][0]['children'][0]
    task.update(actual_progress=1, pace_progress=1, pace_forecast_method='done', work_done=True,
                pace_forecast_known=True, forecast_finish='2026-11-06', observed_complete_by='2026-11-06', delta_days=None)
    with browser_page(1440) as (page, responses, errors):
        render(page, view)
        page.locator('.g-row.lvl-task', has_text='Монтаж фасада').click()
        expect(page.locator('#detailGrid')).to_contain_text('100% в ГПР на дату')
        expect(page.locator('#detailGrid')).not_to_contain_text('Фактическое окончание')
        assert not errors
