"""The native summary calendar keeps the full source and the selected forecast."""
import copy
import html
import io
import re
import socket
from pathlib import Path

import pytest
from pypdf import PdfReader

import developaid_management_report as report
import developaid_schedule_plan_scenario as scenario
from test_gpr_why_page import why_view


def _body(view):
    return report._gantt_html({'gantt':report.gantt(view,{}),'end':view['cut']})


def _rows(body):
    return re.findall(r'<article class="cg-work"(.*?)</article>',body,re.S)


def _row(body,key):
    return next(fragment for fragment in _rows(body) if 'data-work-id="'+html.escape(key,quote=True)+'"'in fragment)


def _tasks(view):
    def walk(nodes):
        for node in nodes:
            if node.get('level')=='task':yield node
            yield from walk(node.get('children')or[])
    return [*walk(view['schedule']['management']),*view['schedule']['undated_works']]


def test_summary_replaces_the_legacy_rollups_with_every_native_work_and_exact_selected_finish():
    view=why_view();before=copy.deepcopy(view);body=_body(view)
    rows=view['schedule']['rows']+view['schedule']['undated_works']
    display=view['schedule']['readiness']['project']['forecast']['display']
    assert len(_rows(body))==len(rows)==9
    for row in rows:
        assert html.escape(row['name'])in _row(body,row['id'])
        assert html.escape(row['object'])in _row(body,row['id'])
    assert body.count('class="gpr-analysis-paragraph"')==2
    assert body.index('gpr-automatic-analysis')<body.index('readiness-summary')<body.index('data-calendar-version="canonical"')
    assert 'class="schedule-article-details'not in body
    assert 'class="gpr-scoped-finish" data-date="'+display['finish']+'"'in body
    for point in display['rows']:
        row=_row(body,point['work_id'])
        assert 'data-forecast-scope="selected"'in row
        assert 'data-finish="'+point['finish']+'"'in row
        assert 'Условное окончание'in row and 'плановый темп, а не измеренная скорость'in row
    outside=_row(body,'why-3')
    assert 'Вне выбранного состава'in outside and 'gpr-forecast-end'not in outside
    assert '2038' in outside and 'По учебному ГПР: 50%'in outside
    assert 'Учебная работа без начала'in body and view==before


@pytest.mark.parametrize('field',['source_sha256','cut','id_scope','full_source_sha256','finish','covered'])
def test_a_foreign_projection_has_a_named_gap_and_keeps_all_plan_and_fact_rows(field):
    view=why_view();display=view['schedule']['readiness']['project']['forecast']['display']
    display[field]={'source_sha256':'f'*64,'cut':'2033-04-19','id_scope':'foreign',
        'full_source_sha256':'b'*64,'finish':'2039-01-01','covered':0}[field]
    before=copy.deepcopy(view);body=_body(view)
    assert len(_rows(body))==9 and 'Общая календарная оценка не подтверждена'in body
    assert 'не совпадают с текущим ГПР'in body and 'gpr-scoped-finish"'not in body
    assert 'class="gpr-analysis-paragraph"'not in body
    assert 'class="readiness-project-forecast"'not in body
    assert 'class="gpr-forecast-end 'not in body
    assert '2033' in _row(body,'why-0')and'По учебному ГПР: 0%'in _row(body,'why-0')
    assert view==before


@pytest.mark.parametrize('mutation',['foreign','duplicate','missing','ambiguous_id'])
def test_one_bad_point_cannot_hide_valid_source_rows_or_attach_a_foreign_date(mutation):
    view=why_view();schedule=view['schedule'];points=schedule['readiness']['project']['forecast']['display']['rows']
    target=points[1]['work_id']
    if mutation=='foreign':points[1]['finish']='2040-02-03'
    elif mutation=='duplicate':points.append(copy.deepcopy(points[1]))
    elif mutation=='missing':points.pop(1)
    else:schedule['rows'].append(copy.deepcopy(next(row for row in schedule['rows']if row['id']==target)))
    before=copy.deepcopy(view);body=_body(view)
    assert len(_rows(body))==9 and 'Общая календарная оценка не подтверждена'in body
    assert 'class="gpr-scoped-finish"'not in body
    assert 'class="readiness-project-forecast"'not in body
    assert 'class="gpr-forecast-end 'in _row(body,points[0]['work_id'])
    assert 'class="gpr-forecast-end 'not in _row(body,target)
    assert 'не подтверждена'in _row(body,target).lower()
    assert 'data-finish="2040-02-03"'not in body and view==before


def test_all_undated_work_and_repeated_names_remain_separate_without_invented_scope():
    view=why_view();rows=_tasks(view)
    for row in rows:row['plan_start']=None;row['plan_finish']=None
    rows[1]['name']=rows[0]['name']
    view['schedule']['management']=[];view['schedule']['rows']=[];view['schedule']['undated_works']=rows
    view['schedule'].pop('readiness');view['schedule'].pop('readiness_html')
    before=copy.deepcopy(view);body=_body(view)
    assert len(_rows(body))==9
    assert html.escape(rows[0]['name'])in _row(body,rows[0]['id'])and html.escape(rows[1]['name'])in _row(body,rows[1]['id'])
    assert 'нет подтверждённой календарной проекции'in body
    assert 'class="cg-plan"'not in body and 'class="gpr-forecast-end 'not in body
    assert view==before


def test_a_source_work_missing_from_the_tree_is_preserved_with_a_named_hierarchy_gap():
    view=why_view();tasks=view['schedule']['management'][0]['children'][0]['children'][0]['children']
    tasks[:]=[row for row in tasks if row['id']!='why-1']
    before=copy.deepcopy(view);body=_body(view)
    assert len(_rows(body))==9 and 'Иерархию работы нужно проверить'in _row(body,'why-1')
    assert 'В исходном перечне есть работы без строки в иерархии'in body
    assert 'class="gpr-scoped-finish"'not in body
    assert 'class="gpr-forecast-end 'in _row(body,'why-0')and view==before


@pytest.mark.parametrize('mutation',['scope_shape','status_shape','source_date_shape'])
def test_malformed_calendar_metadata_is_a_visible_gap_with_all_original_rows(mutation):
    view=why_view();state=view['schedule']['readiness'];forecast=state['project']['forecast']
    if mutation=='scope_shape':
        forecast['id_scope']=forecast['display']['id_scope']=state['forecast_identity']['id_scope']=[]
    elif mutation=='status_shape':state['forecast_scope'][state['project']['work_ids'][0]]={'status':[]}
    else:
        forecast['display']['rows'][0]['source_date']=[]
        view['schedule']['rows'][0]['plan_pace_scenario']['source_date']=[]
    before=copy.deepcopy(view);body=_body(view)
    assert len(_rows(body))==9 and 'Общая календарная оценка не подтверждена'in body
    assert 'class="gpr-scoped-finish"'not in body and 'class="gpr-analysis-paragraph"'not in body
    assert 'class="readiness-project-forecast"'not in body and view==before


@pytest.mark.parametrize('with_gpr',[False,True])
def test_monetary_acceptance_never_becomes_a_physical_bar(with_gpr):
    view=why_view()
    for row in [*_tasks(view),*view['schedule']['rows']]:
        if row['id']=='why-3':
            row.update(progress_kind='accepted_cost_ratio',actual_progress=.99,pace_progress=.99,
                display_progress={'value':.99,'label':'Принято, % стоимости','source':'accepted_cost_ratio'})
            if with_gpr:row['gpr_progress']=0
    row=_row(_body(view),'why-3')
    assert '99%'not in row and 'Принято, % стоимости'not in row
    assert ('Выполнено по ГПР: 0%'in row)if with_gpr else ('Выполнение неизвестно'in row and 'class="cg-fact"'not in row)


@pytest.mark.parametrize('actual',[None,'2033-04-19'])
def test_source_completion_does_not_invent_an_actual_finish(actual):
    view=why_view()
    for row in [*_tasks(view),*view['schedule']['rows']]:
        if row['id']=='why-0':
            row['work_done']=True;row['actual_finish']=actual;row['plan_pace_scenario']['complete']=True
    scenario.decorate_readiness(view['schedule']['readiness'],view['schedule']['rows']+view['schedule']['undated_works'])
    row=_row(_body(view),'why-0')
    assert 'gpr-forecast-end'not in row
    if actual:assert 'Фактическое окончание: 19.04.2033'in row
    else:assert 'фактическая дата не подтверждена'in row


def test_calendar_presentation_does_not_call_any_forecast_calculator(monkeypatch):
    view=why_view();before=copy.deepcopy(view)
    def forbidden(*a,**kw):raise AssertionError('presentation tried to recalculate the source')
    monkeypatch.setattr(scenario,'work',forbidden);monkeypatch.setattr(scenario,'group',forbidden)
    body=_body(view)
    assert len(_rows(body))==9 and view==before


@pytest.fixture
def native_summary(tmp_path,monkeypatch):
    import main
    import developaid_monitor as monitor
    from test_management_report_model import PROJECT, _project
    monkeypatch.setenv('DEVELOPAID_ADMIN_KEY','synthetic-calendar-report-admin')
    monkeypatch.setenv('DATA_DIR',str(tmp_path/'data'))
    monkeypatch.setattr(monitor,'_SNAPSHOT_DIR',tmp_path/'monitor')
    monkeypatch.setattr(main.core,'_PLATO_STAGE_DIR',tmp_path/'stage')
    _project()
    view=why_view(3)
    for index,row in enumerate(_tasks(view)):
        row['source_cells']={'progress':'ГПР!G'+str(index+5),'start':'ГПР!H'+str(index+5),'finish':'ГПР!I'+str(index+5)}
    for row in view['schedule']['rows']:
        row['source_cells']=copy.deepcopy(next(item['source_cells']for item in _tasks(view)if item['id']==row['id']))
    before=copy.deepcopy(view)
    monkeypatch.setattr(report,'_monitor_view',lambda *args:copy.deepcopy(view))
    yield main.core,PROJECT,view
    assert view==before


@pytest.mark.parametrize('width',[390,1440])
def test_actual_summary_page_keeps_the_new_axis_every_source_work_and_native_pdf(native_summary,tmp_path,width):
    from playwright.sync_api import sync_playwright, expect
    from browser import chromium_or_skip, serve
    from developaid_schedule_visual import date_text
    import pymupdf
    core,project,view=native_summary
    tasks=_tasks(view);display=view['schedule']['readiness']['project']['forecast']['display']
    with socket.socket()as reserved:
        reserved.bind(('127.0.0.1',0));port=reserved.getsockname()[1]
    with serve(core.app,port)as base,sync_playwright()as pw:
        browser=pw.chromium.launch(executable_path=str(chromium_or_skip()))
        page=browser.new_page(viewport={'width':width,'height':960},accept_downloads=True);errors=[];calls=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.on('request',lambda request:calls.append(request.url))
        page.add_init_script("localStorage.setItem('plato_projects_key','synthetic-calendar-report-admin')")
        page.goto(base+'/report',wait_until='domcontentloaded')
        page.wait_for_selector('#project option[value="'+project+'"]',state='attached')
        page.select_option('#project',project);page.fill('#cut',view['cut']);page.click('#reportBtn')
        host=page.locator('#reportBox .report-gpr-calendar[data-cut="'+view['cut']+'"]')
        expect(host).to_be_visible(timeout=30000)
        expect(host.locator('.cg-work')).to_have_count(len(tasks))
        paragraphs=page.locator('#reportBox .gpr-analysis-paragraph')
        assert paragraphs.all_text_contents()==display['paragraphs']
        assert paragraphs.first.evaluate('(el)=>el.compareDocumentPosition(document.querySelector("#reportBox .readiness-summary"))&Node.DOCUMENT_POSITION_FOLLOWING')
        for stage in host.locator('.cg-stage > summary').all():stage.click()
        marker=host.locator('.cg-axis .gpr-scoped-finish')
        expect(marker).to_have_attribute('data-date',display['finish'])
        row=host.locator('.cg-work[data-work-id="why-0"]')
        expect(row.locator('.gpr-forecast-end')).to_have_attribute('data-finish',display['finish'])
        error=page.evaluate('''()=>{const a=document.querySelector('.report-gpr-calendar .cg-axis .gpr-scoped-finish').getBoundingClientRect(),b=document.querySelector('.cg-work[data-work-id="why-0"] .gpr-forecast-end').getBoundingClientRect();return Math.abs(a.left-b.left)}''')
        assert error<1
        expect(host.locator('[data-work-id="why-3"]')).to_contain_text('Вне выбранного состава')
        assert host.locator('[data-work-id="why-3"] .gpr-forecast-end').count()==0
        assert page.locator('#reportBox .schedule-article-tree').count()==0
        assert page.locator('#reportBox img').count()==0 and page.evaluate('window.whyInjected')is None
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        host.screenshot(path=str(tmp_path/f'canonical-report-{width}.png'))
        page.emulate_media(media='print')
        for details in host.locator('.cg-stage').all():details.evaluate('(el)=>el.open=false')
        assert host.locator('.cg-work:visible').count()==len(tasks)
        page.emulate_media(media='screen')
        with page.expect_download(timeout=90000)as download:page.click('#reportPdfBtn')
        raw=Path(download.value.path()).read_bytes()
        (tmp_path/f'canonical-report-{width}.pdf').write_bytes(raw)
        pdf=PdfReader(io.BytesIO(raw));text='\n'.join(item.extract_text()or''for item in pdf.pages)
        tight=lambda value:''.join(value.split())
        assert date_text(display['finish'])in text and 'Условное окончание'in text
        assert 'Вне выбранного состава'in text and 'Учебная работа без начала'in text
        for task in tasks:
            assert tight(task['name'])in tight(text)
            for cell in task['source_cells'].values():assert cell in text
        geometry=pymupdf.open(stream=raw,filetype='pdf')
        for sheet in geometry:
            assert sheet.rect.width==pytest.approx(595,abs=2)
            for word in sheet.get_text('words'):
                assert word[0]>=-1 and word[2]<=sheet.rect.width+1
        assert not errors and not any('/monitor/ask'in url for url in calls)
        browser.close()
