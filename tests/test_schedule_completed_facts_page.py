"""Actual markers survive source changes without bringing archived plan bars."""
from pathlib import Path

import pytest

import developaid_monitor as monitor
import developaid_management_report as report
from test_schedule_completed_facts import site, book, approve, confirm, PROJECT, TODAY, OLD_DAY  # noqa: F401
from browser import open_ks_calculation
from test_monitor_cumulative_controls import browser_page


@pytest.mark.parametrize('width',[390,1440])
@pytest.mark.parametrize('explicit',[False,True])
def test_current_graph_and_pdf_keep_source_qualified_completion_markers(site,width,explicit):
    from playwright.sync_api import expect
    from pypdf import PdfReader
    monitor.store_work_fact(PROJECT,[{'id':'1','progress':1}],OLD_DAY)
    if explicit:
        confirm()
    approve(book('Оставшаяся кровля',.25,'2027-01-15'))
    view=monitor.build(PROJECT,TODAY)
    model=view['schedule']['physical_progress']
    fact,=model['completed_facts']['qualified_task_completions']
    # The existing cohort path must append its cards, not overwrite the facts.
    model['source_cohorts']=[{'cohort_id':'QA','task_ids':['1'],'source_name':'Общий объём',
        'source_scope':'Корпус 1','model':{'progress':.4,'components':[]}}]
    with browser_page(width) as (page,responses,errors):
        page.evaluate('(v)=>{currentView=v;renderGantt(v)}',view)
        open_ks_calculation(page)
        marker=page.locator('#ksSharedGroups .completed-work-marker')
        expect(marker).to_have_count(1)
        expect(marker).to_contain_text('Завершённый фасад')
        expect(marker).to_contain_text('Завершено 2026-11-05' if explicit else '100% на дату '+OLD_DAY)
        assert marker.locator('.completed-actual-point').get_attribute('data-date-basis')==(
            'actual_finish' if explicit else 'observed_complete_by')
        assert marker.locator('.planbar,.factbar,.forecastmark,img,script').count()==0
        expect(page.locator('#gantt')).not_to_contain_text('Завершённый фасад')
        expect(page.locator('#gantt')).not_to_contain_text('2028')
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        marker.screenshot(path=f'/tmp/completed-work-{width}-{explicit}.png')
        # No-calendar views still keep known facts visible.
        page.evaluate('(v)=>{v.schedule.management=[];renderGantt(v)}',view)
        expect(page.locator('#ganttCard')).to_be_visible()
        expect(marker).to_be_visible()
        assert page.locator('#gantt .g-row').count()==0
        block=report.gantt(view,view['dashboard'])
        markup=report._gantt_html({'gantt':block,'end':TODAY})
        # Keep pending Monitor callbacks on their own document while checking the report.
        page=page.context.browser.new_page(viewport=page.viewport_size)
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.set_content('<html><head><meta charset="utf-8"></head><body>'+markup+'</body></html>')
        expect(page.locator('.completed-work-marker')).to_have_count(1)
        if width==1440:
            path=Path(f'/tmp/completed-work-{explicit}.pdf')
            page.pdf(path=str(path),format='A4',print_background=True)
            text=' '.join(p.extract_text() or '' for p in PdfReader(str(path)).pages)
            assert 'Завершённый фасад' in text and '2028' not in text
            assert ('2026-11-05' if explicit else OLD_DAY) in text
        assert not errors


def test_source_position_counts_do_not_create_work_markers_or_large_exec_tables(site):
    from developaid_schedule_completed_facts import render
    value={'qualified_task_completions':[],
           'completed_ks_positions':[{'name':'Private source leaf '+str(i)} for i in range(1000)],
           'counts':{'confirmed_works':0,'ks_positions':1000},'overall_progress':None}
    html=render(value)
    assert '1000' in html and 'class="completed-work-marker"' not in html
    assert 'Private source leaf' not in html and len(html)<1500


@pytest.mark.parametrize('width',[390,1440])
def test_owner_plan_date_is_shared_by_current_past_fact_view_and_pdf(site,width):
    from playwright.sync_api import expect
    from pypdf import PdfReader
    from test_schedule_owner_rnv import approve_owner,TARGET
    monitor.store_work_fact(PROJECT,[{'id':'1','progress':1}],'2026-11-07')
    approve_owner(book('Единственный текущий план',.25,'2027-06-30'),scope='remaining_work')
    view=monitor.build(PROJECT,OLD_DAY)
    with browser_page(width) as (page,responses,errors):
        page.evaluate('(v)=>{currentView=v;renderDash(v);renderGantt(v)}',view)
        expect(page.locator('#kpis')).to_contain_text('30.09.2027')
        expect(page.locator('#kpis')).to_contain_text('решение владельца')
        points=page.locator('#gantt .owner-rnv-plan')
        assert points.count()>0 and all(value==TARGET for value in points.evaluate_all('(p)=>p.map(x=>x.dataset.date)'))
        expect(page.locator('#gantt')).not_to_contain_text('Завершённый фасад')
        expect(page.locator('#gantt')).not_to_contain_text('2028')
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.locator('#ganttCard').screenshot(path=f'/tmp/completed-owner-rnv-{width}.png')
        page.locator('#dataTab').click()
        expect(page.locator('#baselineBtn')).to_be_hidden()
        block=report.gantt(view,view['dashboard'])
        # Keep pending Monitor callbacks on their own document while checking the report.
        page=page.context.browser.new_page(viewport=page.viewport_size)
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.set_content('<html><head><meta charset="utf-8"></head><body>'+
            report._gantt_html({'gantt':block,'end':OLD_DAY})+'</body></html>')
        expect(page.locator('.schedule-rnv-cards')).to_contain_text('30.09.2027')
        expect(page.locator('body')).not_to_contain_text('2028')
        if width==1440:
            path=Path('/tmp/completed-owner-rnv.pdf');page.pdf(path=str(path),format='A4',print_background=True)
            text=' '.join(p.extract_text() or '' for p in PdfReader(str(path)).pages)
            assert '30.09.2027' in text and 'План РНВ владельца' in text and '2028' not in text
        assert not errors
