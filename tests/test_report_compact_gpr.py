"""Report composition is compact; its dates only read the selected projection."""
import copy
import re
from html.parser import HTMLParser

import pytest
import developaid_report_gantt as gantt
import developaid_management_report as report

CUT='2026-11-15'


def block():
    rows=[];points={};groups=[]
    for index,finish in enumerate(['2028-05-31','2028-05-31','2028-04-19'],1):
        key='source-'+str(index);obj='Корпус '+str(index)
        task=dict(id=key,object=obj,name='Работа с упоминанием корпуса 99',plan_start='2026-01-01',plan_finish='2027-09-30',plan_pace_scenario=dict(finish=finish,source_date=CUT))
        rows.append(dict(task=task))
        points[key]=dict(work_id=key,reference_work_id=key,finish=finish,plan_finish=task['plan_finish'],complete=False,basis='conditional',source_date=CUT)
        groups.append(dict(name=obj,work_ids=[key],progress=.2*index,partial=True))
    rows.append(dict(task=dict(id='parking',object='ПАРКИНГ',name='Корпус 1 в названии',plan_start='2025-01-01',plan_finish='2040-01-01')))
    display=dict(schema=1,basis='readiness_project_forecast',cut=CUT,source_sha256='a'*64,full_source_sha256='a'*64,id_scope='full_source',finish='2028-05-31',total=3,covered=3,reference_total=3,truncated=False,rows=list(points.values()),paragraphs=['Not copied','Not copied'])
    forecast={**{k:display[k]for k in ['source_sha256','full_source_sha256','id_scope','finish','total','covered','reference_total']},'display':display,'excluded':[]}
    state=dict(cut=CUT,source_sha256='a'*64,project=dict(progress=.4,known_readings=3,total=3,source_dates=[CUT],work_ids=list(points),forecast=forecast),corpora=groups,forecast_identity=dict(source_sha256='a'*64,full_source_sha256='a'*64,id_scope='full_source',remaining_ids={key:key for key in points}),matrix=[dict(stage='Конструктив',cells=copy.deepcopy(groups))])
    return dict(readiness=state,calendar=dict(schema=1,cut=CUT,qualified=True,display=copy.deepcopy(display),rows=rows,points=copy.deepcopy(points),issues=[],owner_rnv=dict(date='2027-09-30',source='owner_decision')))


class DOM(HTMLParser):
    def __init__(self,text):
        super().__init__();self.tags=[];self.text=[];self.feed(text)
    def handle_starttag(self,tag,attrs):self.tags.append((tag,dict(attrs)))
    def handle_data(self,data):self.text.append(data)


def test_report_has_three_blocks_visible_corpus_bars_and_readable_full_years():
    value=block();before=copy.deepcopy(value);model=gantt.compact_model(value,CUT);body=report._gantt_html(dict(gantt=value,end=CUT));dom=DOM(body)
    assert model['qualified'] and model['finish']=='2028-05-31'
    assert [a['data-gpr-block']for _,a in dom.tags if 'data-gpr-block'in a]==['forecast','matrix','gantt']
    assert [g['name']for g in model['groups']]==['Корпус 1','Корпус 2','Корпус 3','ПАРКИНГ']
    assert [g['finish']for g in model['groups']]==['2028-05-31','2028-05-31','2028-04-19',None]
    assert body.count('class="rg-plan"')==body.count('class="rg-forecast"')==3
    assert 'Вне выбранного состава проекта'in body and '2040'not in body
    assert {a['data-year']for _,a in dom.tags if 'data-year'in a}=={'2026','2027','2028'}
    assert not any(tag=='details'for tag,_ in dom.tags)and 'cg-work'not in body and 'stages_tree'not in body
    assert 'readiness-summary'not in body and 'gpr-analysis-paragraph'not in body and 'schedule-provenance'not in body
    assert {a['data-project-forecast']for _,a in dom.tags if 'data-project-forecast'in a}=={'2028-05-31'}
    assert 'План РНВ владельца: 30.09.2027'in body
    assert 'Подробные работы и источники — в Мониторе'in body and value==before


@pytest.mark.parametrize('fault',['missing','crosscut','crosssource','crossscope','duplicate_id','missing_reference','foreign_point','duplicate_corpus_membership'])
def test_missing_or_foreign_canonical_projection_never_becomes_a_plan_forecast(fault):
    value=block();calendar=value['calendar'];state=value['readiness']
    if fault=='missing':value.pop('calendar')
    elif fault=='crosscut':calendar['cut']='2026-11-16'
    elif fault=='crosssource':calendar['display']['source_sha256']='f'*64
    elif fault=='crossscope':state['forecast_identity']['id_scope']='current_source'
    elif fault=='duplicate_id':calendar['rows'].append(copy.deepcopy(calendar['rows'][0]))
    elif fault=='missing_reference':state['forecast_identity']['remaining_ids'].pop('source-1')
    elif fault=='foreign_point':calendar['points']['source-1']['reference_work_id']='parking'
    else:state['corpora'][1]['work_ids'].append('source-1')
    before=copy.deepcopy(value);model=gantt.compact_model(value,CUT);body=gantt.render_compact(model)
    assert not model['qualified'] and model['finish']is None
    assert all(g['selected']is None for g in model['groups']if g['total'])
    assert '0 из'not in body and 'None'not in body
    assert all(g['finish']is None and g['plan_finish']is None for g in model['groups'])
    assert 'class="rg-forecast"'not in body and 'class="rg-plan"'not in body
    assert 'Пока не определён'in body and 'Оценка: <b>30.09.2027'not in body
    assert report._report_gpr_summary(dict(gantt=value,end=CUT))['finish']is None
    assert value==before


def test_unknown_point_is_not_zero_or_plan_fallback_and_keeps_qualified_partial_project_date():
    value=block();key='source-3'
    value['calendar']['rows'][2]['task']['plan_pace_scenario']['finish']=None
    for point in [value['calendar']['points'][key],value['calendar']['display']['rows'][2],value['readiness']['project']['forecast']['display']['rows'][2]]:
        point['finish']=None;point['basis']='unknown'
    for display in [value['calendar']['display'],value['readiness']['project']['forecast']['display'],value['readiness']['project']['forecast']]:display['covered']=2
    model=gantt.compact_model(value,CUT);assert model['qualified']and model['finish']=='2028-05-31'
    assert model['covered']==2 and model['groups'][2]['finish']is None and model['groups'][2]['unknown']
    assert model['groups'][2]['plan_finish']=='2027-09-30'
    body=gantt.render_compact(model);assert 'Окончание неизвестно'in body and body.count('class="rg-forecast"')==2


def test_same_reference_join_wins_over_names_and_source_object_spelling():
    value=block();value['calendar']['rows'][0]['task']['object']='Секция А';value['calendar']['rows'][0]['task']['name']='Только Корпус 999'
    model=gantt.compact_model(value,CUT)
    assert model['qualified']and model['groups'][0]['name']=='Корпус 1'and model['groups'][0]['finish']=='2028-05-31'
    assert all(g['name']!='Корпус 999'for g in model['groups'])


def test_forecast_advances_from_its_canonical_value_never_a_hardcoded_day():
    value=block()
    value['calendar']['rows'][0]['task']['plan_pace_scenario']['finish']='2028-06-01'
    value['calendar']['points']['source-1']['finish']='2028-06-01'
    for display in [value['calendar']['display'],value['readiness']['project']['forecast']['display']]:display['rows'][0]['finish']='2028-06-01';display['finish']='2028-06-01'
    value['readiness']['project']['forecast']['finish']='2028-06-01'
    body=report._gantt_html(dict(gantt=value,end=CUT));assert '01.06.2028'in body
    assert report._report_gpr_summary(dict(gantt=value,end=CUT))['finish']=='2028-06-01'


def test_full_report_does_not_duplicate_gpr_facts_and_preserves_other_findings():
    value=dict(project='Synthetic compact report',kind='week',start='2026-11-09',end=CUT,gantt=block(),
               findings=[dict(topic='Натуральный факт',text='DO_NOT_COPY_GPR_FACT',source='source'),
                         dict(topic='Срок',text='DO_NOT_COPY_OLD_FORECAST',source='source'),
                         dict(topic='Продажи',text='KEEP_SALES_FINDING',source='sales')])
    value['gantt']['dependency_timeline']={'rnv':{'forecast':'2027-09-30'}}
    before=copy.deepcopy(value);body=report.render_html(value)
    assert body.count('data-gpr-block=')==3 and 'DO_NOT_COPY_'not in body and 'KEEP_SALES_FINDING'in body
    assert 'report-source-appendix'not in body and 'gpr-broader-physical'not in body
    assert 'gpr-analysis-paragraph'not in body and 'readiness-summary'not in body
    assert value==before


@pytest.mark.parametrize('width',[390,1440])
def test_native_report_page_shows_compact_blocks_bars_and_nonoverlapping_years(width):
    from playwright.sync_api import sync_playwright,expect
    from browser import chromium_or_skip
    from developaid_report_page import REPORT_PAGE
    from urllib.parse import urlsplit
    value=dict(project='Synthetic compact report',kind='week',start='2026-11-09',end=CUT,gantt=block())
    body=report.render_html(value)
    with sync_playwright()as pw:
        browser=pw.chromium.launch(executable_path=str(chromium_or_skip()),args=['--no-sandbox'])
        try:
            page=browser.new_page(viewport=dict(width=width,height=1000));page.set_default_timeout(10000)
            def route(r):
                path=urlsplit(r.request.url).path
                if r.request.method=='GET'and path=='/report':return r.fulfill(content_type='text/html',body=REPORT_PAGE)
                if r.request.method=='POST'and path=='/monitor/report/projects':return r.fulfill(json=dict(projects=[dict(project=value['project'])]))
                if r.request.method=='POST'and path=='/monitor/report/build':return r.fulfill(json=dict(html=body,report=value))
                r.abort('blockedbyclient')
            page.route('**/*',route)
            hint={'version':1,'current':{'project':value['project'],'cut':CUT},'scopes':[{'project':value['project'],'cut':CUT,'view':'monitor','monitor':{},'report':{'reportKind':'week'}}]}
            import json
            page.add_init_script('localStorage.setItem("plato_projects_key","SYNTHETIC_COMPACT_KEY");sessionStorage.setItem("developaid_monitor_navigation_v1",'+json.dumps(json.dumps(hint))+');')
            page.goto('https://developaid.ru/report')
            host=page.locator('#reportBox .report-gpr-compact');expect(host).to_be_visible()
            expect(host.locator('[data-gpr-block]')).to_have_count(3)
            assert host.locator('[data-gpr-block]').evaluate_all('es=>es.map(e=>e.dataset.projectForecast)')==['2028-05-31']*3
            expect(host.locator('.rg-corpus')).to_have_count(4)
            expect(host.locator('.rg-forecast')).to_have_count(3)
            assert host.locator('details,.cg-work').count()==0
            years=host.locator('.rg-years [data-year]').evaluate_all('es=>es.map(e=>{const r=e.getBoundingClientRect();return {text:e.textContent,left:r.left,right:r.right,font:parseFloat(getComputedStyle(e).fontSize)}})')
            assert years and all(re.fullmatch('[0-9]{4}',y['text'])and y['font']>=12 for y in years)
            assert all(a['right']<=b['left']for a,b in zip(years,years[1:]))
            assert all(y['left']>=0 and y['right']<=width for y in years)
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
            page.emulate_media(media='print')
            expect(host.locator('.rg-corpus:visible')).to_have_count(4)
        finally:browser.close()


def test_compact_presentation_never_calls_a_forecast_calculator(monkeypatch):
    import developaid_schedule_plan_scenario as scenario
    value=block();before=copy.deepcopy(value)
    def forbidden(*args,**kwargs):raise AssertionError('presentation recalculated forecast')
    monkeypatch.setattr(scenario,'work',forbidden);monkeypatch.setattr(scenario,'group',forbidden)
    body=report._gantt_html(dict(gantt=value,end=CUT))
    assert '31.05.2028'in body and value==before


@pytest.mark.parametrize('fault',['unattested_exclusion','future_source_date'])
def test_compact_uses_the_native_calendar_guard_for_scope_and_point_dates(fault):
    value=block();projection=value['calendar'];state=value['readiness'];forecast=state['project']['forecast']
    if fault=='unattested_exclusion':
        key='source-3';projection['points'].pop(key);state['forecast_identity']['remaining_ids'].pop(key)
        forecast['excluded']=[dict(work_id=key,kind='separate_scope')]
        for display in [projection['display'],forecast['display']]:
            display['rows']=[p for p in display['rows']if p['work_id']!=key]
            display['total']=display['covered']=2
        forecast['total']=forecast['covered']=2
    else:
        for point in [projection['points']['source-1'],projection['display']['rows'][0],forecast['display']['rows'][0]]:
            point['source_date']='2099-01-01'
    tasks=[dict(row['task'],level='task')for row in projection['rows']]
    checked=gantt.calendar(dict(rows=tasks,management=tasks,readiness=state),CUT)
    assert not checked['qualified']and checked['issues']
    before=copy.deepcopy(value);model=gantt.compact_model(value,CUT)
    assert not model['qualified']and model['finish']is None and value==before
    assert all(group['finish']is None for group in model['groups'])
