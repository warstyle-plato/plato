"""A tiny task cannot gain weight by being split into more GPR rows."""
import copy
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

import developaid_monitor as monitor
import developaid_schedule_elements as elements
import developaid_schedule_internal_weights as internal
import developaid_schedule_readiness as ready
from test_schedule_readiness import site, PROJECT, DAY, activate
from test_schedule_readiness_elements import reading
from test_monitor_cumulative_api import api, post
from test_monitor_cumulative_controls import browser_page, KEY as BROWSER_KEY


def measure(value, key, *, basis='smr_cost', unit='RUB', valuation='Estimate v1 / current prices', vat='without_vat'):
    return dict(basis=basis, value=value, unit=unit, source_reference='Synthetic full estimate / '+key,
                valuation_key=valuation, cost_basis=vat if basis=='smr_cost' else '',
                position_keys=['synthetic-estimate-v1:'+key], full_scope=True)


def cost_profile(rows):
    return dict(id=elements.PROFILE_ID, overrides={}, objects={'Корпус 1':'residential'},
                assignments={key:dict(element_id='frame',share=None,weight=node) for key,node in rows.items()})


@pytest.mark.parametrize('minor_tasks',[1,3,20])
def test_splitting_minor_surface_tasks_keeps_their_total_contribution(minor_tasks):
    rows=[reading('main',1)]+[reading('minor-'+str(i),0) for i in range(minor_tasks)]
    inputs={'main':measure(19_000_000,'main')}
    inputs.update({'minor-'+str(i):measure(1_000_000/minor_tasks,'minor-'+str(i)) for i in range(minor_tasks)})
    cfg=cost_profile(inputs);index={r['id']:r for r in rows}
    elements.validate(cfg,index);weights,reasons=elements.weights(cfg,index)
    assert not reasons
    assert weights['main']==pytest.approx(23.75)
    assert sum(v for k,v in weights.items() if k!='main')==pytest.approx(1.25)
    state=elements.projection(rows,cfg,cut=DAY,confirmed=True)
    assert state['project']['progress']==pytest.approx(.95)
    assert state['project']['known_weight']==pytest.approx(25)
    assert elements.catalog()[1]['value']==25


@pytest.mark.parametrize('mutation,reason',[
    (lambda c:c['assignments']['minor']['weight'].update(value=None),'Не хватает'),
    (lambda c:c['assignments']['minor']['weight'].update(full_scope=False),'Не подтверждён полный план'),
    (lambda c:c['assignments']['minor']['weight'].update(cost_basis='with_vat'),'НДС'),
    (lambda c:c['assignments']['minor']['weight'].update(valuation_key='Other price date'),'единая база'),
    (lambda c:c['assignments']['minor']['weight'].update(source_reference=''),'источник'),
    (lambda c:c['assignments']['minor']['weight'].update(position_keys=[]),'позиции'),
    (lambda c:c['assignments']['minor'].pop('weight'),'Не для всех'),
])
def test_missing_or_incompatible_plan_never_becomes_zero_or_equal_share(mutation,reason):
    rows={r['id']:r for r in [reading('main',1),reading('minor',0)]}
    cfg=cost_profile({'main':measure(19,'main'),'minor':measure(1,'minor')});mutation(cfg)
    elements.validate(cfg,rows);weights,reasons=elements.weights(cfg,rows)
    assert not weights and len(reasons)==2
    assert all(reason in text for text in reasons.values())


def test_reusing_source_positions_across_tasks_or_buildings_blocks_all_claims():
    rows={r['id']:r for r in [reading('main',1),reading('minor',0,obj='Корпус 2')]}
    cfg=cost_profile({'main':measure(19,'same-position'),'minor':measure(1,'same-position')})
    cfg['objects']['Корпус 2']='residential'
    weights,reasons=elements.weights(cfg,rows)
    assert not weights and all('повторно' in value for value in reasons.values())


def test_parent_total_and_its_leaf_are_not_counted_twice():
    cfg=cost_profile({'main':measure(20,'parent'),'minor':measure(1,'minor')})
    cfg['assignments']['main']['weight']['position_keys']=['source:leaf-major','source:leaf-minor']
    cfg['assignments']['minor']['weight']['position_keys']=['source:leaf-minor']
    rows={r['id']:r for r in [reading('main',1),reading('minor',0)]}
    weights,reasons=elements.weights(cfg,rows)
    assert not weights and all('повторно' in value for value in reasons.values())


def test_volumes_require_same_units_and_explicit_homogeneous_work_kind():
    rows={r['id']:r for r in [reading('a',1),reading('b',0)]}
    cfg=cost_profile({'a':measure(9,'a',basis='planned_quantity',unit='м3',valuation='Same concrete operation'),
                      'b':measure(1,'b',basis='planned_quantity',unit='м³',valuation='Same concrete operation')})
    assert elements.weights(cfg,rows)[0]['a']==pytest.approx(22.5)
    cfg['assignments']['b']['weight']['unit']='м2'
    assert not elements.weights(cfg,rows)[0]
    cfg['assignments']['b']['weight']['unit']='м3'
    cfg['assignments']['b']['weight']['valuation_key']='Surface grinding'
    assert not elements.weights(cfg,rows)[0]
    cfg['assignments']['b']['weight']=measure(1,'b')
    assert not elements.weights(cfg,rows)[0]


@pytest.mark.parametrize('bad',[True,-1,float('nan'),float('inf'),1e300,'paid'])
def test_invalid_full_plan_is_rejected(bad):
    with pytest.raises(ValueError):internal.validate(measure(bad,'one'))


@pytest.mark.parametrize('unit',['RUB','руб.','рубля','тыс. руб.','руб./м3','₽'])
def test_money_is_not_accepted_as_a_physical_quantity(unit):
    with pytest.raises(ValueError):
        internal.validate(measure(100,'one',basis='planned_quantity',unit=unit))


def test_paid_amount_field_and_claimed_percent_cannot_replace_full_plan():
    node=measure(19,'one');node['paid']=19
    with pytest.raises(ValueError):internal.validate(node)
    rows={'main':reading('main',1)}
    cfg=cost_profile({'main':measure(19,'one')});cfg['assignments']['main']['share']=100
    with pytest.raises(ValueError):elements.validate(cfg,rows)


def test_zero_cost_unfinished_work_does_not_certify_full_completion():
    rows=[reading('main',1),reading('minor',0)]
    state=elements.projection(rows,cost_profile({'main':measure(19,'main'),'minor':measure(0,'minor')}),cut=DAY,confirmed=True)
    assert state['project']['progress']==1
    assert state['project']['partial']
    assert 'нулевой вес' in state['project']['reason']


def configured_cost_site(site):
    cfg,opts=copy.deepcopy(site)
    cfg.update(included_ids=['1','2'],excluded_ids=['3'])
    cfg['element_profile']=cost_profile({'1':measure(19_000_000,'main'),'2':measure(1_000_000,'minor')})
    cfg['element_profile']['objects']['Корпус 2']='separate'
    return cfg,opts


def test_cost_inputs_round_trip_with_source_and_derived_shares(site):
    activate(configured_cost_site(site))
    view=monitor.build(PROJECT,DAY);state=view['schedule']['readiness']
    assert state['project']['progress']==pytest.approx(.975)
    assert state['project']['coverage']==25
    assert view['schedule']['completed_facts']['overall_progress'] is None
    editor=ready.editor(PROJECT)
    assert {r['id']:r['calculated_share'] for r in editor['works'] if r['id'] in {'1','2'}}=={'1':95,'2':5}
    assert editor['configuration']['element_profile']['assignments']['1']['weight']['value']==19_000_000
    assert editor['history'][-1]['internal_methods']==[internal.LABELS['smr_cost']]
    # The completed main work is outside today's remaining GPR, but still
    # retains 95% of the full element. Minor leftovers never acquire its weight.
    assert {w['full_id']:w['value'] for w in ready._events(PROJECT)[0]['profile']['weights']}=={'1':23.75,'2':1.25}


@pytest.mark.parametrize('width',[390,1440])
def test_real_editor_uses_full_cost_and_missing_cost_stays_unknown(site,api,monkeypatch,width):
    client,_=api;monkeypatch.setenv('DEVELOPAID_ADMIN_KEY',BROWSER_KEY)
    activate(configured_cost_site(site))
    with browser_page(width) as (page,responses,errors):
        def route_readiness(route):
            result=client.post(urlsplit(route.request.url).path,json=route.request.post_data_json)
            route.fulfill(status=result.status_code,json=result.json())
        page.route('**/monitor/readiness/**',route_readiness)
        page.route('**/monitor/daily/summary*',lambda route:route.fulfill(json={}))
        page.route('**/monitor/view',lambda route:route.fulfill(json=monitor.build(PROJECT,DAY)))
        page.locator('#project').fill(PROJECT);page.locator('#cut').fill(DAY)
        page.evaluate('(v)=>{currentView=v;renderGantt(v)}',monitor.build(PROJECT,DAY))
        expect(page.locator('#readinessSummary .readiness-project-value')).to_have_text('97,5%')
        page.locator('#readinessEditor>summary').click()
        page.locator('#readinessEditorBody>details').filter(has=page.locator('.readiness-works')).locator('summary').first.click()
        main=page.locator('.readiness-work').filter(has=page.locator('[data-work-element="1"]'))
        minor=page.locator('.readiness-work').filter(has=page.locator('[data-work-element="2"]'))
        expect(main.locator('[data-work-weight-basis]')).to_have_value('smr_cost')
        expect(main.locator('[data-work-weight-value]')).to_have_value('19000000')
        expect(main.locator('[data-work-calculated-share]')).to_contain_text('95%')
        main.locator('[data-work-weight-value]').fill('9000000')
        page.locator('#readinessSave').click()
        expect(page.locator('#readinessSummary .readiness-project-value')).to_have_text('95,0%')
        page.locator('#readinessEditorBody>details').filter(has=page.locator('.readiness-works')).locator('summary').first.click()
        expect(main.locator('[data-work-calculated-share]')).to_contain_text('90%')
        main.locator('[data-work-weight-basis]').select_option('planned_quantity')
        expect(main.locator('[data-work-weight-value]')).to_have_value('')
        expect(main.locator('[data-work-weight-source]')).to_have_value('')
        expect(main.locator('[data-work-weight-full]')).not_to_be_checked()
        page.locator('#readinessReload').click()
        expect(main.locator('[data-work-weight-basis]')).to_have_value('smr_cost')
        page.locator('#readinessEditorBody>details').filter(has=page.locator('.readiness-works')).locator('summary').first.click()
        minor.locator('[data-work-weight-value]').fill('')
        page.locator('#readinessSave').click()
        expect(page.locator('#readinessSummary .readiness-project-value')).to_have_count(0)
        expect(page.locator('#readinessSummary')).to_contain_text('Не хватает полной плановой стоимости')
        assert ready.editor(PROJECT)['configuration']['element_profile']['assignments']['2']['weight']['value'] is None
        expect(page.locator('#readinessSave')).to_be_enabled()
        page.locator('#readinessEditorBody>details').filter(has=page.locator('.readiness-works')).locator('summary').first.click()
        page.locator('[data-readiness-object="Корпус 1"]').select_option('separate')
        page.locator('[data-readiness-object="Корпус 2"]').select_option('residential')
        page.locator('[data-work-element="3"]').select_option('masonry')
        page.locator('#readinessSave').click()
        expect(page.locator('#readinessSummary .readiness-project-value')).to_have_text('0,0%')
        saved=ready.editor(PROJECT)['configuration']
        assert set(saved['element_profile']['assignments'])=={'3'}
        assert set(saved['excluded_ids'])=={'1','2'}
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        assert not errors
