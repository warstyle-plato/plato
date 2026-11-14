"""Element coverage, persisted edits and the real Monitor editor/API."""
import copy
import importlib
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

import developaid_monitor as monitor
import developaid_schedule_readiness as ready
import developaid_schedule_elements as elements
from test_schedule_readiness import site, PROJECT, DAY, activate
from test_monitor_cumulative_api import api, post
from test_monitor_cumulative_controls import browser_page, KEY as BROWSER_KEY


def element_site(site):
    cfg, opts = copy.deepcopy(site)
    cfg['element_profile'] = dict(id=elements.PROFILE_ID,
        overrides={key: 0 for key, _, _ in elements.ELEMENTS if key not in {'underground', 'frame'}},
        objects={'Корпус 1': 'residential', 'Корпус 2': 'separate'},
        assignments={'1': dict(element_id='underground', share=None), '2': dict(element_id='frame', share=None)})
    cfg.update(included_ids=['1','2'], excluded_ids=['3'])
    return cfg, opts


def test_catalog_accepted_values_and_estimates_are_not_a_normative_table():
    assert [weight for _, _, weight in elements.ELEMENTS] == [12,25,5,17,3,7,18,4,5,4]
    assert elements.ACCEPTED_ON == DAY
    assert sum(e['value'] for e in elements.catalog()) == 100
    assert elements.catalog({'frame': 0})[1]['origin'] == 'manual'
    assert elements.catalog({'frame': 0})[1]['value'] == 0
    assert elements.catalog()[1]['origin'] == 'estimate'


def test_real_projection_excludes_separate_parking_and_shares_monitor_report_source(site):
    import developaid_management_report as report
    activate(element_site(site))
    view=monitor.build(PROJECT,DAY)
    state=view['schedule']['readiness']
    assert state['project']['progress'] == pytest.approx((12+25*.5)/37)
    assert state['project']['coverage'] == 100
    assert state['excluded_works'] == 1
    assert state['matrix_objects'] == ['Корпус 1']
    assert state['matrix'][0]['cells'][0]['progress'] == state['project']['progress']
    block=report.gantt(view,view['dashboard'])
    assert block['readiness'] == state
    assert '66,2%' in report._gantt_html({'gantt':block,'end':DAY})
    assert 'gprMatrix' in view['schedule']['readiness_html']


def test_partial_weighted_fraction_is_not_exported_as_overall_completion(site):
    cfg,opts=element_site(site)
    del cfg['element_profile']['assignments']['1']
    activate((cfg,opts))
    schedule=monitor.build(PROJECT,DAY)['schedule']
    assert schedule['readiness']['project']['progress']==pytest.approx(.5)
    assert schedule['readiness']['project']['partial']
    assert schedule['completed_facts']['overall_progress'] is None
    assert 'не сопоставлена' in schedule['completed_facts']['overall_progress_reason']


def reading(key, value, *, obj='Корпус 1', date=DAY, name='Надземный монолит'):
    return dict(id=key, name=name, object=obj, section='Этап', primary=dict(value=value, date=date, label='По ведомости'))


def test_unknown_names_weights_and_internal_shares_are_never_guessed_or_zero():
    config=dict(id=elements.PROFILE_ID, overrides={}, objects={'Корпус 1':'residential'}, assignments={})
    rows=[reading('one',1),reading('two',None)]
    state=elements.projection(rows,config,cut=DAY,confirmed=True)
    assert state['project']['progress'] is None
    assert state['project']['coverage'] == 0
    assert state['project']['counts']['unknown'] == 1
    assert state['project']['eligible_readings'] == 1
    assert state['project']['known_readings'] == 0
    assert 'не сопоставлена' in state['project']['reason']
    config['assignments']={key:dict(element_id='frame',share=None) for key in ('one','two')}
    assert elements.projection(rows,config,cut=DAY,confirmed=True)['project']['progress'] is None
    config['assignments']['one']['share']=40
    config['assignments']['two']['share']=60
    state=elements.projection(rows,config,cut=DAY,confirmed=True)
    assert state['project']['progress'] == 1  # Qualified known fraction, not the entire building.
    assert state['project']['coverage'] == 10
    assert state['project']['partial']
    assert 'по известным данным' in elements.render_matrix(state)
    assert state['matrix'][0]['cells'][0]['coverage'] == 40
    rows[0]['primary']['value']=1.8
    assert elements.projection(rows,config,cut=DAY,confirmed=True)['project']['progress'] == 1
    rows[0]['primary']['requires_reconciliation']=True
    assert elements.projection(rows,config,cut=DAY,confirmed=True)['project']['progress'] is None
    assert 'actual_finish' not in state['project']
    zero_config=copy.deepcopy(config);zero_config['overrides']={k:0 for k,_,_ in elements.ELEMENTS}
    zero=elements.projection([reading('one',1),reading('two',1)],zero_config,cut=DAY,confirmed=True)
    assert zero['project']['progress'] is None
    assert 'Нет положительного веса' in zero['project']['reason']


def test_multiple_stages_share_the_one_element_weight_and_oldest_positive_reading():
    rows=[reading('one',.5,date='2026-11-05'),reading('two',1,date='2026-11-06')]
    rows[1]['section']='Другой этап'
    config=dict(id=elements.PROFILE_ID,overrides={},objects={'Корпус 1':'residential'},
                assignments={'one':dict(element_id='frame',share=40),'two':dict(element_id='frame',share=60)})
    state=elements.projection(rows,config,cut=DAY,confirmed=True)
    assert state['project']['progress'] == pytest.approx(.8)
    assert state['project']['coverage'] == 25
    assert state['project']['oldest_date']=='2026-11-05'
    assert sum(c['known_weight'] for row in state['matrix'] for c in row['cells'])==25
    assert elements.projection(rows,config,cut=DAY,confirmed=False)['project']['progress'] is None


@pytest.mark.parametrize('total',[90,110])
def test_non_hundred_shares_are_saved_and_normalized(site,total):
    cfg,opts=copy.deepcopy(site)
    for w in cfg['weights']:w['value']*=total/100
    activate((cfg,opts))
    assert monitor.build(PROJECT,DAY)['schedule']['readiness']['project']['progress'] == pytest.approx(.7)


@pytest.mark.parametrize('bad',[None, '', -1, True, float('inf'), float('nan')])
def test_element_input_is_strict_and_blank_is_not_zero(site,bad):
    cfg,opts=element_site(site)
    cfg['element_profile']['overrides']['frame']=bad
    with pytest.raises(ValueError):ready.preview(PROJECT,cfg,**opts)


def test_editor_reads_disk_and_reset_restores_estimate_with_revision_conflict(site):
    cfg,opts=element_site(site);activate((cfg,opts))
    state=ready.editor(PROJECT)
    assert state['options']['expected_revision']==1
    cfg=state['configuration'];cfg['element_profile']['overrides']['frame']=50
    p=ready.preview(PROJECT,cfg,**state['options'])
    ready.save(PROJECT,cfg,**state['options'],expected_profile_sha256=p['profile_sha256'],author='Synthetic reviewer')
    with pytest.raises(ready.versions.ScheduleVersionConflict):
        ready.save(PROJECT,cfg,**state['options'],expected_profile_sha256=p['profile_sha256'])
    second=importlib.reload(ready)
    loaded=second.editor(PROJECT)
    e=next(e for e in loaded['elements'] if e['id']=='frame')
    assert e['origin']=='manual' and e['value']==50 and e['author']=='Synthetic reviewer'
    assert len(loaded['history'])==2
    del loaded['configuration']['element_profile']['overrides']['frame']
    p=second.preview(PROJECT,loaded['configuration'],**loaded['options'])
    second.save(PROJECT,loaded['configuration'],**loaded['options'],expected_profile_sha256=p['profile_sha256'])
    e=next(e for e in second.editor(PROJECT)['elements'] if e['id']=='frame')
    assert e['value']==25 and e['origin']=='estimate'


def test_admin_route_rejects_wrong_key_and_demo_before_read_and_writes(site,api,monkeypatch):
    client,_=api
    monkeypatch.setattr(ready,'editor',lambda *a,**k:pytest.fail('read before admin check'))
    for key in ('','wrong','market-key'):
        r=post(client,'readiness/editor',key=key,project=PROJECT)
        assert r.status_code==403 and r.headers['cache-control']=='private, no-store'


@pytest.mark.parametrize('width',[390,1440])
def test_real_page_edit_save_recompute_reset_and_history(site,api,monkeypatch,width,tmp_path):
    client,_=api
    monkeypatch.setenv('DEVELOPAID_ADMIN_KEY', BROWSER_KEY)
    activate(element_site(site))
    with browser_page(width) as (page,responses,errors):
        def route_readiness(route):
            r=client.post(urlsplit(route.request.url).path,json=route.request.post_data_json)
            route.fulfill(status=r.status_code,json=r.json())
        page.route('**/monitor/readiness/**',route_readiness)
        page.route('**/monitor/daily/summary*',lambda route:route.fulfill(json={}))
        page.route('**/monitor/view',lambda route:route.fulfill(json=monitor.build(PROJECT,DAY)))
        page.locator('#project').fill(PROJECT);page.locator('#cut').fill(DAY)
        page.evaluate('(v)=>{currentView=v;renderGantt(v)}',monitor.build(PROJECT,DAY))
        expect(page.locator('#gprMatrix')).to_be_visible()
        expect(page.locator('#gprMatrix')).to_contain_text('66,2%')
        page.locator('#readinessEditor>summary').click()
        share=page.locator('[data-element-weight="frame"]')
        expect(share).to_have_value('25')
        share.fill('50')
        expect(page.locator('#readinessTotal')).to_contain_text('Сумма отличается')
        page.locator('#readinessSave').click()
        expect(page.locator('#readinessSummary .readiness-project-value')).to_have_text('59,7%')
        expect(page.locator('[data-origin="frame"]')).to_contain_text('Изменено вручную')
        expect(page.locator('#gprMatrix')).to_contain_text('59,7%')
        page.locator('[data-reset-element="frame"]').click()
        page.locator('#readinessSave').click()
        expect(page.locator('#readinessSummary .readiness-project-value')).to_have_text('66,2%')
        expect(page.locator('[data-origin="frame"]')).to_contain_text('Оценка: 25%')
        expect(page.locator('#readinessEditorBody')).to_contain_text('История профиля (3)')
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.screenshot(path=str(tmp_path/f'readiness-{width}.png'),full_page=True)
        assert not errors


def test_page_configures_a_saved_full_source_explicitly_and_reports_conflict(site,api,monkeypatch):
    client,_=api
    monkeypatch.setenv('DEVELOPAID_ADMIN_KEY',BROWSER_KEY)
    with browser_page(390) as (page,responses,errors):
        def route_readiness(route):
            r=client.post(urlsplit(route.request.url).path,json=route.request.post_data_json)
            route.fulfill(status=r.status_code,json=r.json())
        page.route('**/monitor/readiness/**',route_readiness)
        page.route('**/monitor/daily/summary*',lambda route:route.fulfill(json={}))
        page.route('**/monitor/view',lambda route:route.fulfill(json=monitor.build(PROJECT,DAY)))
        page.locator('#project').fill(PROJECT);page.locator('#cut').fill(DAY)
        page.evaluate('(v)=>{currentView=v;renderGantt(v)}',monitor.build(PROJECT,DAY))
        page.locator('#readinessEditor>summary').click()
        # The new editor opens today's remaining source, not an unrelated old
        # full book. This case deliberately chooses the historical reference.
        expect(page.locator('[data-work-element]')).to_have_count(2)
        page.locator('#readinessFullSource').select_option(site[0]['full_source_sha256'])
        expect(page.locator('[data-work-element]')).to_have_count(3)
        expect(page.locator('[data-element-weight="frame"]')).to_have_value('25')
        for key,_,_ in elements.ELEMENTS:
            if key not in {'underground','frame'}:
                page.locator(f'[data-element-weight="{key}"]').fill('0')
        page.locator('#readinessEditorBody>details').filter(has=page.locator('.readiness-works')).locator('summary').first.click()
        page.locator('[data-readiness-object="Корпус 1"]').select_option('residential')
        page.locator('[data-readiness-object="Корпус 2"]').select_option('separate')
        page.locator('[data-work-element="1"]').select_option('underground')
        page.locator('[data-work-element="2"]').select_option('frame')
        page.locator('[data-work-element="3"]').select_option('__excluded__')
        page.locator('#readinessScopeConfirmed').check()
        page.locator('#readinessEditorBody>details').filter(has=page.locator('#readinessOutsideConfirmed')).locator('summary').first.click()
        page.locator('#readinessOutsideConfirmed').check()
        page.locator('#readinessOwnerNote').fill('Synthetic explicit outside completion')
        page.locator('#readinessSave').click()
        expect(page.locator('#readinessSummary .readiness-project-value')).to_have_text('66,2%')
        expect(page.locator('#readinessSave')).to_be_enabled()
        assert ready._events(PROJECT)[0]['profile']['element_profile']['assignments']=={
            '1':dict(element_id='underground',share=None),'2':dict(element_id='frame',share=None)}
        page.route('**/monitor/readiness/profile-save',lambda route:route.fulfill(status=409,json={'detail':'Профиль изменён другим администратором.'}))
        page.locator('[data-element-weight="frame"]').fill('50')
        page.locator('#readinessSave').click()
        expect(page.locator('#readinessEditorMsg')).to_contain_text('Перечитайте сохранённые')
        expect(page.locator('#readinessSummary .readiness-project-value')).to_have_text('66,2%')
        assert len(ready._events(PROJECT))==1
        assert not errors


@pytest.mark.parametrize('width',[390,1440])
def test_multi_building_matrix_is_readable_and_known_unweighted_facts_are_not_missing(width):
    rows=[reading(str(i),.5,obj='Корпус '+str(i)) for i in range(1,5)]
    config=dict(id=elements.PROFILE_ID,overrides={},assignments={},objects={})
    wf={'works':{r['id']:r for r in rows}}
    state=ready.model(wf,cut=DAY,baseline_scope='full_schedule',source_sha256='a'*64)
    # A saved draft has dated observations even before weights are assigned.
    state.update(elements.projection(rows,config,cut=DAY,confirmed=False))
    markup=ready.render(state)
    with browser_page(width) as (page,responses,errors):
        from test_monitor_gpr_sections import monitor_view
        view=monitor_view();view['schedule']['readiness_html']=markup
        page.evaluate('(v)=>{currentView=v;renderGantt(v)}',view)
        expect(page.locator('#readinessSummary')).to_contain_text('Пригодные показания: 4 из 4')
        expect(page.locator('#readinessSummary')).to_contain_text('включено во взвешенный расчёт: 0')
        expect(page.locator('#readinessSummary #gprMatrix')).to_have_count(0)
        rows=page.locator('.readiness-corpus-table tbody tr')
        expect(rows).to_have_count(4)
        for i in range(4):
            expect(rows.nth(i)).to_contain_text('Корпус '+str(i+1))
            expect(rows.nth(i).locator('td').first).to_have_text('1')
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        assert not errors
