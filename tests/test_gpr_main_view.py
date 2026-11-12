"""The main work rows retain source facts independently of calendar/pace."""
import copy
import datetime as dt

import pytest
from playwright.sync_api import expect

import developaid_gpr_corpus as corpus
import developaid_monitor as monitor
from test_gpr_corpus_preview import book
from test_monitor_cumulative_controls import browser_page
from test_monitor_gpr_sections import monitor_view


@pytest.mark.parametrize('width', [390, 1440])
def test_initial_work_rows_show_known_zero_partial_unknown_and_bad_dates_before_reference(width):
    view = monitor_view('unknown')
    tasks = view['schedule']['management'][0]['children'][0]['children'][0]['children']
    base = copy.deepcopy(tasks[0])
    tasks[:] = [dict(base, id=str(i), name=name, actual_progress=p, pace_progress=p,
        pace_forecast_known=False, pace_forecast_method='plan', forecast_finish=None)
        for i, name, p in [(1,'Известный ноль',0), (2,'Известное выполнение',.9), (3,'Нет показания',None)]]
    view['schedule']['undated_works'] = [dict(tasks[1], id='4', name='Ошибочная дата',
        plan_finish=None, reason='Окончание не распознано, лист ГПР, ячейка G5')]
    with browser_page(width) as (page, responses, errors):
        page.evaluate('(v)=>{currentView=v;renderDash(v);renderGantt(v)}',view)
        assert page.locator('#gprMatrix,.gpr-matrix').count() == 0
        assert page.locator('#gantt .lvl-task:visible').count() == 4
        for name, pct in [('Известный ноль','0%'),('Известное выполнение','90%'),('Ошибочная дата','90%')]:
            row = page.locator('#gantt .lvl-task',has_text=name)
            expect(row.locator('.work-progress')).to_contain_text(pct)
            expect(row.locator('.work-progress')).to_contain_text('06.11.2026')
            assert row.locator('.forecastmark,.latebar,.aheadbar').count() == 0
        assert page.locator('#gantt .lvl-task',has_text='Известное выполнение').locator('.planbar,.factbar').count() == 2
        bad = page.locator('#gantt .lvl-task',has_text='Ошибочная дата')
        assert bad.locator('.planbar,.factbar').count() == 0
        bad.locator('summary').click()
        expect(bad).to_contain_text('ячейка G5')
        expect(page.locator('#gantt .lvl-task',has_text='Нет показания')).not_to_contain_text('0%')
        assert page.evaluate("$('monitorPanel').querySelector('.card:not(.hidden)').id") == 'ganttCard'
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        assert not errors


def test_server_undated_work_retains_known_fact_and_calendar_warning(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor,'_SNAPSHOT_DIR',tmp_path/'monitor')
    monitor.store_schedule('Synthetic date warning',book(),None,'2026-11-06')
    view=monitor.build('Synthetic date warning','2026-11-08')
    row=next(w for w in view['schedule']['undated_works'] if w['id']=='corpus:ГПР!E5')
    assert row['actual_progress']==.25 and row['gpr_progress']==.25
    assert row['progress_source']['date']=='2026-11-06'
    assert 'G5' in row['reason'] and not row['forecast_known']
    assert view['schedule']['dependency_timeline']['rnv']['state']!='complete'


@pytest.mark.parametrize('width',[390,1440])
def test_new_all_undated_source_replaces_previous_calendar_without_inventing_plan_dates(width):
    first=monitor_view()
    second={'cut':'2026-11-12','schedule':{'management':[],'approved_plan':{'source_sha256':'b'*64},
        'undated_works':[{'id':'new-work','name':'Новый известный факт','object':'Корпус 9',
            'section':'Новый этап','actual_progress':.9,'gpr_progress':.9,'gpr_progress_date':'2026-11-06',
            'progress_kind':'gpr_percent','pace_forecast_known':False,'pace_forecast_method':'unknown',
            'reason':'Обе даты отсутствуют, источник ГПР'}]}}
    with browser_page(width) as (page,responses,errors):
        page.evaluate('(v)=>{currentView=v;renderGantt(v)}',first)
        assert page.locator('#gantt .planbar').count()>0
        page.evaluate('(v)=>{currentView=v;renderGantt(v)}',second)
        expect(page.locator('#gantt .lvl-task')).to_be_visible()
        expect(page.locator('#gantt .lvl-task')).to_contain_text('90%')
        expect(page.locator('#gantt')).not_to_contain_text('Монтаж фасада')
        assert page.locator('#gantt .planbar,#gantt .factbar,#gantt .forecastmark').count()==0
        expect(page.locator('#gprUndated')).to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        assert not errors
