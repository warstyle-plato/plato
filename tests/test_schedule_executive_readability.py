"""The real renderers must remain readable at production-sized schedule density."""
from __future__ import annotations

import copy
import datetime as dt
import io
import re

import pytest

import developaid_management_report as report
import developaid_report_gantt as gantt
import developaid_schedule_timeline as timeline
from browser import expand_gantt
from test_schedule_dependency_timeline import network, task, day
from test_schedule_physical_print_summary import gpr_sources


def dense_schedule():
    pm = network()
    history, actual = {}, {}
    for i in range(1096):
        tid = 'history-'+str(i)
        start = day('2023-01-01')+dt.timedelta(days=i % 300)
        finish = start+dt.timedelta(days=7)
        history[tid] = task(tid, 'Историческая техническая работа '+str(i),
                            start.isoformat(), finish.isoformat())
        actual[tid] = finish
    pm['tasks'] = {**history, **pm['tasks']}
    block = timeline.model(pm, {'1': day('2026-12-10')}, evidence=True, actual_finishes=actual)
    roots = []
    for corpus in range(1, 5):
        articles = []
        for i in range(25):
            articles.append({'level': 'rss', 'code': f'2.2.{i}', 'name': 'Укрупнённый этап '+str(i),
                             'children': [{'level': 'task', 'name': 'Пакет работ '+str(i),
                                           'object': 'Корпус '+str(corpus),
                                           'plan_start': '2026-09-01', 'plan_finish': '2027-01-20',
                                           'forecast_finish': '2027-02-04',
                                           'pace_forecast_known': True}]})
        roots.append({'level': 'control', 'name': 'Объект '+str(corpus), 'children': [
            {'level': 'detail', 'name': 'Основные работы', 'children': articles}]})
    grouped = gantt.model(roots)
    grouped['dependency_timeline'] = block
    return block, roots, grouped


def executive_html(block, grouped):
    return report._gantt_html({'gantt': grouped, 'end': '2026-11-06',
                              'schedule': {**block['rnv'], 'state': 'ok'}})


def test_dense_network_is_calculated_fully_but_history_cannot_crowd_out_delay_origin():
    block, _, grouped = dense_schedule()
    before = copy.deepcopy(block)
    selected, note = timeline.overview_rows(block)
    assert len(block['rows']) == 1100
    assert [row['id'] for row in selected] == ['1', '2', '3', '4']
    assert selected[1]['inherited_delay_days'] == 15
    assert block['rnv']['forecast'] == '2027-02-16'
    html = executive_html(block, grouped)
    assert 'history-1095' not in html and 'Историческая техническая' not in html
    assert 'schedule-technical' not in html.split('</style>')[-1]
    # Owner's decision: no dependency drawing and no technical network view;
    # the full model stays in the cut and the RNV cards keep the dates.
    assert 'от предыдущих этапов' not in html
    assert block == before
    monitor_html = timeline.render(block)
    assert 'data-network-task' not in monitor_html and 'schedule-technical' not in monitor_html.split('</style>')[-1]
    assert 'Показаны первые 60' not in monitor_html


@pytest.mark.parametrize('state', ['partial', 'unknown'])
def test_incomplete_rnv_never_gets_a_confirmed_date_and_history_is_not_invented(state):
    block, _, grouped = dense_schedule()
    block['rnv'].update(state=state, forecast=None, indicative_forecast='2027-02-16',
                        reasons=['Календарь не подтверждён.', 'Полнота цепочки не подтверждена.'])
    html = executive_html(block, grouped)
    expected = ('<span>Оценка по части работ</span><strong>16.02.2027</strong>' if state == 'partial'
                else '<span>Оценка окончания</span><strong>Не определена</strong>')
    assert expected in html
    if state == 'partial':
        assert 'не подтверждает дату получения разрешения на ввод' in html
    else:
        assert 'Окончание работ пока не оценено.' in html
    assert 'Календарь не подтверждён.' in html
    assert 'Сравнение версий ГПР пока не рассчитано.' in html
    assert '<span>Прогноз ввода</span><strong>16.02.2027' not in html
    assert block['rnv']['forecast'] is None


def test_no_corpus_mapping_keeps_known_pm_dates_and_explains_the_gap():
    block, _, _ = dense_schedule()
    html = executive_html(block, {'state': 'missing', 'reason': 'Привязка к корпусам не подтверждена.',
                                  'dependency_timeline': block})
    assert '16.02.2027' in html and 'от предыдущих этапов' not in html
    assert 'Привязка к корпусам не подтверждена.' in html
    assert 'Историческая техническая работа' not in html


def test_finished_delay_origin_is_kept_in_the_explanation():
    pm = network()
    block = timeline.model(pm, {'1': day('2026-12-10')}, evidence=True,
                           actual_finishes={'1': day('2026-12-10')})
    rows, _ = timeline.overview_rows(block)
    assert rows[0]['id'] == '1' and rows[0]['actual_finish'] == '2026-12-10'
    # The explanation stays in the model; the drawing is not rendered (owner).
    assert 'schedule-lane' not in timeline.render(block, context='report').split('</style>')[-1]


def test_unconfirmed_pm_still_shows_supplied_plan_without_renaming_it_forecast():
    block = timeline.model(network(), {}, evidence=False)
    html = timeline.render(block, context='report')
    assert '<span>Оценка окончания</span><strong>Не определена</strong>' in html
    assert 'Окончание работ пока не оценено.' in html
    assert block['rnv']['forecast'] is None
    assert '01.02.2027' in html
    assert 'class="schedule-bar schedule-forecast"' not in html


def test_source_only_corpus_fallback_displays_raw_progress_without_approving_it():
    import developaid_gpr_corpus as corpus
    from test_gpr_corpus_preview import book
    source = corpus.read(book(name='Учебный фасад'))
    before = copy.deepcopy(source)
    block = {'state': 'missing', 'reason': 'Нет утверждённой привязки.', 'corpus_gpr': source}
    html = report._gantt_html({'gantt': block, 'end': '2026-11-06'})
    assert 'Исходные показания ГПР по корпусам' in html
    assert 'Показание исходного ГПР: 50.0%' in html
    assert '01.02.2027' in html and 'Все пакеты исходного файла (2)' in html
    # The warning follows the actual source qualification, rather than an old
    # hard-coded sentence. Raw readings never become approval or a forecast.
    import html as html_text
    assert html_text.escape(source['reason'],quote=True) in html
    assert 'проценты не меняют утверждённый график' in source['reason']
    assert 'не дают темп или прогноз РНВ' in source['reason']
    assert 'class="schedule-bar schedule-forecast"' not in html
    assert source == before and not source['baseline_approved'] and not source['quantity_mapping_confirmed']


def test_partial_corpus_delay_uses_comparable_work_delta_not_aggregate_date_difference():
    from developaid_schedule_visual import lanes
    partial = {'id': 'partial', 'name': 'Корпус 1', 'plan_start': '2026-01-01',
               'plan_finish': '2027-12-01', 'forecast_finish': '2027-02-01',
               'forecast_partial': True, 'delta_days': 15}
    html = lanes([partial])
    assert 'Сдвиг работ с рассчитанным прогнозом: +15 дн.' in html
    assert 'это не завершение всего корпуса' in html
    assert 'class="schedule-forecast-point"' in html
    assert 'class="schedule-bar schedule-forecast"' not in html


def test_calendar_axis_labels_months_once_at_their_actual_coordinates():
    from developaid_schedule_visual import lanes
    html = lanes([{'name': 'Работа', 'plan_start': '2026-11-01', 'plan_finish': '2027-02-16'}])
    labels = re.findall(r'<span class="schedule-tick"[^>]*>([^<]+)</span>', html)
    assert labels == ['11.26', '12.26', '01.27', '02.27']


@pytest.mark.parametrize('width', [390, 1440])
def test_actual_executive_renderer_keeps_fonts_bars_and_height_at_realistic_density(width):
    from playwright.sync_api import sync_playwright, expect
    import browser
    block, _, grouped = dense_schedule()
    with sync_playwright() as pw:
        engine = pw.chromium.launch(executable_path=str(browser.chromium_or_skip()))
        page = engine.new_page(viewport={'width': width, 'height': 1000})
        page.set_content('<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><body style="margin:12px">'+executive_html(block, grouped)+'</body></html>')
        expect(page.locator('.schedule-rnv-cards')).to_contain_text('16.02.2027')
        # Corpus lanes only: the RNV dependency lanes are not drawn (owner).
        assert page.locator('.schedule-lane:visible').count() == 4
        assert page.locator('.schedule-article-leaf').count() == 4
        assert page.locator('.schedule-article-details[open]').count() == 0
        assert page.locator('svg').count() == 0
        bounds = page.evaluate('''() => ({
          overflow:document.documentElement.scrollWidth>innerWidth,
          height:document.body.scrollHeight,
          fonts:[...document.querySelectorAll('.schedule-label,.schedule-dates')].filter(e=>e.checkVisibility()).map(e=>parseFloat(getComputedStyle(e).fontSize)),
          bars:[...document.querySelectorAll('.schedule-forecast')].filter(e=>e.checkVisibility()).map(e=>e.getBoundingClientRect().width)
        })''')
        assert not bounds['overflow']
        assert bounds['height'] < (2000 if width == 390 else 1500), bounds
        assert min(bounds['fonts']) >= 12
        assert min(bounds['bars']) > 8
        page.locator('.schedule-article-tree>summary').click()
        page.locator('.schedule-article-leaf>summary').first.click()
        assert page.locator('.schedule-lane:visible').count() == 29
        expect(page.locator('.schedule-article-leaf').first).to_contain_text('Укрупнённый этап 24')
        engine.close()


def test_real_monitor_rejects_pm_dates_and_keeps_current_gpr_dates_and_works(gpr_sources):
    from playwright.sync_api import expect
    from test_monitor_cumulative_controls import browser_page
    block, roots, _ = dense_schedule()
    view = {'cut': '2026-11-06', 'schedule': {'management': roots,
             'dependency_timeline': block, 'dependency_timeline_html': timeline.render(block)}}
    with browser_page(390) as (page, responses, errors):
        page.evaluate('(v)=>renderGantt(v)', view)
        expand_gantt(page)
        # A supplied PM response cannot become the default GPR forecast.
        assert page.locator('#dependencyTimelineBody .schedule-rnv-cards').count() == 0
        expect(page.locator('#forecastCard')).to_contain_text('Недостаточно данных')
        expect(page.locator('#monitorPanel')).not_to_contain_text('16.02.2027')
        expect(page.locator('#monitorPanel')).to_contain_text('Пакет работ 24')
        assert page.get_by_text('Пакет работ 24', exact=True).count() == 4
        # Positive control: a real saved GPR and confirmed natural mapping
        # reaches the same production script with its own qualified dates.
        current = gpr_sources(view=True)
        page.evaluate('(v)=>renderGantt(v)', current)
        cards = page.locator('#dependencyTimelineBody .schedule-rnv-cards')
        expect(cards).to_contain_text('31.10.2026')
        expect(cards).to_contain_text('06.01.2027')
        expect(cards).to_contain_text('Оценка по ГПР')
        assert current['schedule']['dependency_timeline']['rnv']['state'] == 'estimate'
        # Owner's decision: no dependency lanes and no technical network view.
        assert page.locator('#dependencyTimelineBody .schedule-lane').count() == 0
        assert page.locator('.schedule-technical').count() == 0
        assert page.locator('[data-network-task]').count() == 0
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert not errors


def test_real_a4_print_does_not_expand_raw_network_or_article_detail():
    from playwright.sync_api import sync_playwright
    from pypdf import PdfReader
    import browser
    block, _, grouped = dense_schedule()
    with sync_playwright() as pw:
        engine = pw.chromium.launch(executable_path=str(browser.chromium_or_skip()))
        page = engine.new_page(viewport={'width': 1440, 'height': 1000})
        page.set_content(executive_html(block, grouped))
        page.locator('.schedule-article-details').evaluate_all('(items)=>items.forEach(e=>e.open=true)')
        pdf = page.pdf(format='A4', print_background=True)
        engine.close()
    document = PdfReader(io.BytesIO(pdf))
    text = ' '.join(' '.join(page.extract_text() for page in document.pages).split())
    assert len(document.pages) <= 3
    assert '16.02.2027' in text and 'Корпус 4' in text
    assert 'Историческая техническая' not in text
    assert 'Укрупнённый этап 24' not in text
    assert 'от предыдущих этапов' not in text
