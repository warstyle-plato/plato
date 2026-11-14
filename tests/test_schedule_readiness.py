"""Whole-scope readiness, explicit weights and source-bound owner decisions."""
import copy
import datetime as dt
import hashlib
import io

import pytest
from openpyxl import load_workbook
from playwright.sync_api import expect

import developaid_monitor as monitor
import developaid_schedule_readiness as ready
import developaid_schedule_versions as versions
from test_monitor_management_gantt import _gpr_book
from test_monitor_cumulative_api import api, post
from test_monitor_cumulative_controls import browser_page

DAY='2026-11-12'
PROJECT='Synthetic readiness'


def book(ids=(1,2,3)):
    data=_gpr_book([(i,'Synthetic work '+str(i), .5 if i==2 else 0,
        dt.date(2026,10,1),dt.date(2026,12,1),'В работе','2.2') for i in ids])
    wb=load_workbook(io.BytesIO(data));ws=wb['ГПР']
    for row in range(5,ws.max_row+1):
        if ws.cell(row,1).value==3:
            ws.cell(row,4,'Корпус 2')
    stream=io.BytesIO();wb.save(stream);wb.close();return stream.getvalue()


@pytest.fixture
def site(tmp_path,monkeypatch):
    monkeypatch.setattr(monitor,'_SNAPSHOT_DIR',tmp_path/'monitor')
    monkeypatch.setattr(versions,'_now',lambda:dt.datetime(2026,11,12,12,tzinfo=dt.timezone.utc))
    full=book();monitor.store_schedule(PROJECT,full,None,'2026-11-06')
    left=book((2,3));v=monitor.schedule_version_preview(PROJECT,left,DAY,baseline_scope='remaining_work')
    monitor.approve_schedule_version(PROJECT,left,DAY,baseline_scope='remaining_work',
        expected_previous_sha256=v['expected_previous_sha256'],expected_source_sha256=v['source_sha256'])
    state=monitor._working_baseline_state(PROJECT)
    config={'label':'Synthetic construction profile','scope_kind':'construction','scope_note':'Explicit synthetic full scope',
        'basis':'estimated_elements','source_reference':'Synthetic expert shares, not a standard table',
        'building_type':'Synthetic residential building','full_source_sha256':hashlib.sha256(full).hexdigest(),
        'effective_from':DAY,'full_scope_confirmed':True,'included_ids':['1','2','3'],'excluded_ids':[],
        'outside_completed_ids':['1'],'owner_note':'Explicit synthetic confirmation of the identified outside work',
        'weights':[{'full_id':'1','value':60},{'full_id':'2','value':20},{'full_id':'3','value':20}]}
    options={'expected_source_sha256':state['source_sha256'],'expected_source_revision':state['revision'],'expected_revision':0}
    return config,options


def activate(site):
    config,options=site
    preview=ready.preview(PROJECT,config,**options)
    ready.save(PROJECT,config,**options,expected_profile_sha256=preview['profile_sha256'])
    return preview


def test_explicit_full_scope_uses_unique_exact_links_and_weighted_progress_with_dates(site):
    cfg,opts=site
    before=monitor._working_baseline_state(PROJECT)['source_sha256']
    preview=activate(site)
    assert preview['review']['automatic_links']==2 and preview['review']['explicit_links']==0
    assert preview['review']['outside_candidate_ids']==['1']
    view=monitor.build(PROJECT,DAY);state=view['schedule']['readiness']
    assert state['project']['progress']==pytest.approx(.7)
    groups={r['name']:r for r in state['corpora']}
    assert groups['Корпус 1']['progress']==pytest.approx(.875) and groups['Корпус 2']['progress']==0
    assert state['project']['progress']!=pytest.approx((.875+0)/2)
    assert state['project']['counts']=={'completed':1,'in_progress':1,'not_started':1,'unknown':0}
    assert state['project']['source_dates']==[DAY]  # This generic fixture has no dated GPR header.
    assert before==monitor._working_baseline_state(PROJECT)['source_sha256']
    assert 'actual_finish' not in preview['profile']
    assert monitor.build(PROJECT,'2026-11-11')['schedule']['readiness']['full_scope_confirmed'] is False


@pytest.mark.parametrize('mutation',[
    lambda c:c.update(crosswalk=[{'remaining_id':[],'full_id':'2'}]),
    lambda c:c.update(crosswalk={'remaining_id':'2','full_id':'2'}),
    lambda c:c.update(crosswalk=[{'remaining_id':'2','full_id':'3'}]),
    lambda c:c['weights'].append(copy.deepcopy(c['weights'][0])),
    lambda c:c['weights'][0].update(value=-1),
    lambda c:c['weights'][0].update(value=True),
    lambda c:c.update(included_ids=['1','2'],excluded_ids=[]),
    lambda c:c.update(effective_from='2026-11-06'),
])
def test_invalid_scope_mapping_weights_and_backdated_confirmation_fail_closed(site,mutation):
    cfg,opts=site;cfg=copy.deepcopy(cfg);mutation(cfg)
    with pytest.raises(ValueError):ready.preview(PROJECT,cfg,**opts)


def test_smr_weights_use_full_work_cost_never_payments_and_reject_overlap_or_mixed_basis(site):
    cfg,opts=site;cfg=copy.deepcopy(cfg);cfg['basis']='smr_cost'
    cfg['weights']=[{'full_id':str(i),'value':weight,'planned_cost_split':True,'basis':'with_vat',
        'valuation_key':['Synthetic costs','Sheet',2026],'position_keys':['position-'+str(i)]}
        for i,weight in [(1,600),(2,200),(3,200)]]
    activate((cfg,opts));view=monitor.build(PROJECT,DAY)
    assert view['schedule']['readiness']['project']['progress']==pytest.approx(.7)
    cfg['weights'][1]['position_keys']=['position-1']
    with pytest.raises(ValueError,match='повторяются'):ready.preview(PROJECT,cfg,**dict(opts,expected_revision=1))
    cfg['weights'][1]['position_keys']=['position-2'];cfg['weights'][1]['basis']='without_vat'
    with pytest.raises(ValueError,match='НДС'):ready.preview(PROJECT,cfg,**dict(opts,expected_revision=1))


def test_profile_is_hash_revision_bound_and_source_change_does_not_carry_outside_hundred(site):
    cfg,opts=site;preview=ready.preview(PROJECT,cfg,**opts)
    with pytest.raises(versions.ScheduleVersionConflict):
        ready.save(PROJECT,cfg,**opts,expected_profile_sha256='f'*64)
    activate(site)
    with pytest.raises(versions.ScheduleVersionConflict):
        ready.save(PROJECT,cfg,**opts,expected_profile_sha256=preview['profile_sha256'])
    changed=book((2,));p=monitor.schedule_version_preview(PROJECT,changed,DAY,baseline_scope='remaining_work')
    monitor.approve_schedule_version(PROJECT,changed,DAY,expected_previous_sha256=p['expected_previous_sha256'],
        expected_source_sha256=p['source_sha256'],baseline_scope='remaining_work')
    state=monitor.build(PROJECT,DAY)['schedule']['readiness']
    assert state['project']['total']==1 and state['project']['counts']['completed']==0
    assert state['project']['progress'] is None and not state['full_scope_confirmed']


def test_native_profile_api_keeps_strict_auth_and_does_not_accept_source_rows_or_paths(api,monkeypatch):
    client,_=api
    body=dict(project=PROJECT,configuration={},expected_source_sha256='a'*64,expected_source_revision=0,expected_revision=0)
    for route in ['profile-preview','profile-save']:
        monkeypatch.setattr(ready,'preview',lambda *a,**k:pytest.fail('read before admission'))
        denied=post(client,'readiness/'+route,key='wrong',**body)
        assert denied.status_code==403 and denied.headers['cache-control']=='private, no-store'
    extra=client.post('/monitor/readiness/profile-preview',json={**body,'key':'synthetic-cumulative-owner-key','path':'/etc/passwd'})
    assert extra.status_code==422 and extra.headers['cache-control']=='private, no-store'


@pytest.mark.parametrize('width',[390,1440])
def test_actual_monitor_and_report_share_readiness_without_an_empty_matrix(site,width):
    import developaid_management_report as report
    with browser_page(width) as (page,responses,errors):
        view=monitor.build(PROJECT,DAY)
        page.evaluate('(v)=>{currentView=v;renderGantt(v)}',view)
        summary=page.locator('#readinessSummary')
        expect(summary).to_contain_text('Нет подтверждённого полного состава и весов')
        assert summary.locator('.readiness-grid').count()==0
        assert summary.locator('.readiness-corpus-counts').get_attribute('open') is None
        expect(summary.locator('#gprMatrix')).to_have_count(0)
        expect(summary.locator('.readiness-corpus-table')).to_be_visible()
        activate(site);view=monitor.build(PROJECT,DAY)
        page.evaluate('(v)=>{currentView=v;renderGantt(v)}',view)
        expect(summary.locator('.readiness-project-value')).to_have_text('70,0%')
        expect(summary).to_contain_text('87,5%')
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        assert not errors
        block=report.gantt(view,view['dashboard'])
        markup=report._gantt_html({'gantt':block,'end':DAY})
        page.set_content(markup)
        expect(page.locator('.readiness-project-value')).to_have_text('70,0%')


def test_later_reopening_of_an_owned_outside_work_invalidates_readiness(site):
    cfg,_=site;activate(site)
    folder=monitor._project_dir(PROJECT)/'work_fact';folder.mkdir(exist_ok=True)
    import json
    (folder/'2026-11-13.json').write_text(json.dumps({'source_sha256':cfg['full_source_sha256'],
        'rows':[{'id':'1','progress':.2}]}))
    state=monitor.build(PROJECT,'2026-11-13')['schedule']['readiness']
    assert state['project']['progress'] is None
    assert state['project']['counts']['unknown']==1 and state['project']['counts']['completed']==0


def test_unknown_zero_weight_work_and_unfinished_zero_weight_work_never_certify_hundred(site):
    cfg,opts=site;cfg=copy.deepcopy(cfg)
    cfg['weights']=[{'full_id':'1','value':100},{'full_id':'2','value':0},{'full_id':'3','value':0}]
    activate((cfg,opts));view=monitor.build(PROJECT,DAY)
    assert view['schedule']['readiness']['project']['progress'] is None
    assert 'нулевым весом' in view['schedule']['readiness']['reason']
    full=ready._catalog(PROJECT,cfg['full_source_sha256'],full=True)
    profile=ready._events(PROJECT)[0]['profile']
    wf=copy.deepcopy(view['schedule']['work_fact']);wf['works']['3']['primary']['value']=None
    state=ready.model(wf,cut=DAY,baseline_scope='remaining_work',source_sha256=opts['expected_source_sha256'],profile=profile,full_rows=full)
    assert state['project']['progress'] is None and state['project']['counts']['unknown']==1


def test_profile_revision_exposes_pending_and_past_cuts_do_not_get_owner_hundred(site):
    cfg,opts=site;cfg=copy.deepcopy(cfg);cfg['effective_from']='2026-11-13'
    activate((cfg,opts));state=monitor.build(PROJECT,DAY)['schedule']['readiness']
    assert state['profile_revision']==0 and state['latest_profile_revision']==1
    assert state['pending_profile']=='future' and state['latest_profile_sha256']
    assert state['project']['total']==2 and state['project']['counts']['completed']==0
    assert 'ещё не действует' in state['reason']


def test_full_catalog_cannot_use_a_source_effective_after_the_profile(site):
    future=book((1,))
    p=monitor.schedule_version_preview(PROJECT,future,'2026-11-13',baseline_scope='full_schedule')
    monitor.approve_schedule_version(PROJECT,future,'2026-11-13',expected_previous_sha256=p['expected_previous_sha256'],
        expected_source_sha256=p['source_sha256'],baseline_scope='full_schedule')
    with pytest.raises(ValueError,match='ещё не действует'):
        ready._catalog(PROJECT,p['source_sha256'],full=True,effective_from=DAY)


def test_profile_limit_refuses_before_append_and_a_bad_profile_does_not_hide_gantt(site):
    import json
    cfg,opts=site;activate(site)
    path=monitor._project_dir(PROJECT)/'readiness_profiles.json'
    first=ready._events(PROJECT)[0]
    events=[dict(first,revision=i) for i in range(1,101)]
    path.write_text(json.dumps({'schema':1,'events':events}))
    original=path.read_bytes()
    review=ready.preview(PROJECT,cfg,**dict(opts,expected_revision=100))
    with pytest.raises(ValueError,match='предел'):
        ready.save(PROJECT,cfg,**dict(opts,expected_revision=100),expected_profile_sha256=review['profile_sha256'])
    assert path.read_bytes()==original
    path.write_text('invalid synthetic history')
    view=monitor.build(PROJECT,DAY)
    assert len(view['schedule']['rows'])==2
    assert 'не прочитан' in view['schedule']['readiness']['reason']


def test_native_profile_preview_save_binds_only_ids_and_never_writes_on_preview(api,site):
    client,_=api;cfg,opts=site
    body={'project':PROJECT,'configuration':cfg,**opts}
    before=monitor._working_baseline_state(PROJECT)['source_sha256']
    response=post(client,'readiness/profile-preview',**body)
    assert response.status_code==200,response.text
    assert not response.json()['applied'] and 'profile' not in response.json()
    assert ready._events(PROJECT)==[]
    invalid=post(client,'readiness/profile-save',**body,expected_profile_sha256='f'*64)
    assert invalid.status_code==409 and ready._events(PROJECT)==[]
    saved=post(client,'readiness/profile-save',**body,expected_profile_sha256=response.json()['profile_sha256'])
    assert saved.status_code==200,saved.text
    assert saved.json()['revision']==1 and saved.headers['cache-control']=='private, no-store'
    assert monitor._working_baseline_state(PROJECT)['source_sha256']==before
    changed=copy.deepcopy(body);changed['expected_revision']=1;changed['configuration']['path']='/etc/passwd'
    assert post(client,'readiness/profile-preview',**changed).status_code==400


def test_distinct_source_dates_remain_a_set_instead_of_becoming_a_new_measurement_date(site):
    cfg,opts=site;prepared=ready.preview(PROJECT,cfg,**opts)
    activate(site);wf=copy.deepcopy(monitor.build(PROJECT,DAY)['schedule']['work_fact'])
    for work in wf['works'].values():work['primary']['date']='2026-11-06'
    result=ready.model(wf,cut=DAY,baseline_scope='remaining_work',source_sha256=opts['expected_source_sha256'],
        profile=prepared['profile'],full_rows=ready._catalog(PROJECT,cfg['full_source_sha256'],full=True))
    assert result['project']['source_dates']==['2026-11-06',DAY]
    assert result['project']['progress']==pytest.approx(.7)


def test_actual_page_clears_ready_percentage_on_project_change_and_binding_invalidation(site):
    activate(site);view=monitor.build(PROJECT,DAY)
    with browser_page(390) as (page,responses,errors):
        page.evaluate('(v)=>{currentView=v;renderGantt(v)}',view)
        expect(page.locator('#readinessSummary')).to_contain_text('70,0%')
        page.locator('#project').fill('Another synthetic project')
        assert page.locator('#readinessSummary').inner_text()==''
        page.evaluate('(v)=>{currentView=v;renderGantt(v);invalidatePhysicalForecast()}',view)
        assert page.locator('#readinessSummary').inner_text()==''
        assert page.evaluate('!currentView.schedule.readiness&&!currentView.schedule.readiness_html')
        assert not errors


@pytest.mark.parametrize('bad',[None,'invalid',[],{'schema':1,'events':[None]},{'schema':1,'events':['invalid']}])
def test_structurally_corrupt_profile_is_visible_but_does_not_hide_work_rows(site,bad):
    import json
    (monitor._project_dir(PROJECT)/'readiness_profiles.json').write_text(json.dumps(bad))
    view=monitor.build(PROJECT,DAY)
    assert len(view['schedule']['rows'])==2
    assert view['schedule']['readiness']['project']['progress'] is None
    assert 'не прочитан' in view['schedule']['readiness']['reason']


def test_summary_uses_statement_primary_and_never_money_or_the_secondary_gpr_value():
    import developaid_schedule_work_fact as work_fact
    row={'id':'one','name':'Synthetic work','object':'Корпус 1','actual_progress':.4,'gpr_progress':.8,
         'gpr_progress_date':'2026-11-05','progress_kind':'cumulative_statement',
         'progress_source':{'label':'Synthetic statement','date':'2026-11-06'}}
    facts=work_fact.model([row],{})
    profile={'full_scope_confirmed':True,'remaining_source_sha256':'a'*64,'effective_from':DAY,
        'scope_kind':'construction','basis':'estimated_elements','label':'Synthetic','source_reference':'Synthetic',
        'included_ids':['one'],'excluded_ids':[],'outside_completed_ids':[],
        'crosswalk':[{'remaining_id':'one','full_id':'one'}],'weights':[{'full_id':'one','value':100}]}
    state=ready.model(facts,cut=DAY,baseline_scope='remaining_work',source_sha256='a'*64,profile=profile,full_rows={'one':row})
    assert state['project']['progress']==pytest.approx(.4)
    assert state['project']['source_dates']==['2026-11-06']
    assert state['project']['sources']==['По ведомости']
    row['progress_kind']='accepted_cost_ratio';row['actual_progress']=.99
    row.pop('gpr_progress')
    assert work_fact.primary_fact(row)['value'] is None


def gpr_all_configuration(site):
    cfg,opts=site;cfg=copy.deepcopy(cfg)
    cfg['scope_kind']='gpr_all';cfg['basis']='smr_cost'
    cfg['weights']=[{'full_id':str(i),'value':weight,'planned_cost_split':True,'basis':'with_vat',
        'valuation_key':['Synthetic full GPR costs',2026],'position_keys':['full-cost-'+str(i)]}
        for i,weight in [(1,600),(2,200),(3,200)]]
    return cfg,opts


def test_whole_gpr_scope_cannot_exclude_a_work_and_inflate_the_project_percentage(site):
    cfg,opts=gpr_all_configuration(site)
    cfg['included_ids']=['1','2'];cfg['excluded_ids']=['3'];cfg['weights']=cfg['weights'][:2]
    with pytest.raises(ValueError,match='весь полный'):
        ready.preview(PROJECT,cfg,**opts)
    assert ready._events(PROJECT)==[]


def test_whole_gpr_scope_without_exclusions_uses_the_entire_declared_source(site):
    cfg,opts=gpr_all_configuration(site)
    activate((cfg,opts));state=monitor.build(PROJECT,DAY)['schedule']['readiness']
    assert state['full_scope_confirmed'] and state['scope_label']=='Готовность работ по ГПР'
    assert state['excluded_works']==0 and state['project']['total']==3
    assert state['project']['progress']==pytest.approx(.7)
