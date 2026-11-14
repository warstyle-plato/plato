"""A current GPR estimate must not open an unrelated historical work list."""
import pytest
from playwright.sync_api import expect
from urllib.parse import urlsplit

import developaid_monitor as monitor
import developaid_schedule_elements as elements
import developaid_schedule_readiness as ready
from test_schedule_readiness import site, PROJECT, DAY, activate, book
from test_monitor_cumulative_api import api, post
from test_monitor_cumulative_controls import browser_page, KEY as BROWSER_KEY


def current_profile():
    editor = ready.editor(PROJECT)
    cfg = editor['configuration']
    cfg.update(included_ids=['2'], excluded_ids=['3'])
    cfg['element_profile'].update(
        overrides={key:0 for key, _, _ in elements.ELEMENTS if key!='frame'},
        objects={'Корпус 1':'residential', 'Корпус 2':'separate'},
        assignments={'2':dict(element_id='frame', share=100)})
    return cfg, editor['options']


def test_default_editor_uses_current_rows_and_can_still_select_full_reference(site):
    original, options = site
    editor = ready.editor(PROJECT)
    assert editor['configuration']['full_source_sha256'] == options['expected_source_sha256']
    assert editor['configuration']['scope_kind'] == ready.CURRENT_ESTIMATE
    assert {row['id'] for row in editor['works']} == {'2','3'}
    assert not editor['unmatched'] and not editor['outside']
    historical = ready.editor(PROJECT, full_source_sha256=original['full_source_sha256'])
    assert {row['id'] for row in historical['works']} == {'1','2','3'}
    assert historical['configuration']['scope_kind'] == 'construction'


def test_saved_current_estimate_renders_values_but_never_certifies_full_readiness(site):
    cfg, opts = current_profile()
    activate((cfg, opts))
    view = monitor.build(PROJECT, DAY)
    state = view['schedule']['readiness']
    assert not state['full_scope_confirmed']
    assert state['estimated']
    assert state['scope_label'] == 'Оценочная готовность по текущему ГПР'
    assert state['corpora'][0]['progress'] == pytest.approx(.5)
    assert state['corpora'][0]['partial']
    assert ready.CURRENT_ESTIMATE_NOTE in state['corpora'][0]['reason']
    assert any(cell['progress'] == .5 for row in state['matrix'] for cell in row['cells'])
    assert view['schedule']['completed_facts']['overall_progress'] is None
    assert state['project']['counts']['completed'] == 0  # Absent historical work1 was not invented as100%.
    assert ready.editor(PROJECT)['configuration']['scope_kind'] == ready.CURRENT_ESTIMATE
    import developaid_management_report as report
    assert report.gantt(view,view['dashboard'])['readiness'] == state


@pytest.mark.parametrize('mutation', [
    lambda cfg, original:cfg.update(full_source_sha256=original['full_source_sha256']),
    lambda cfg, original:cfg.update(full_scope_confirmed=True),
    lambda cfg, original:cfg.update(basis='smr_cost'),
    lambda cfg, original:cfg.pop('element_profile'),
])
def test_current_estimate_cannot_promote_an_archive_or_fake_full_confirmation(site, mutation):
    original, _ = site
    cfg, opts = current_profile()
    mutation(cfg, original)
    with pytest.raises(ValueError): ready.preview(PROJECT, cfg, **opts)


def test_source_change_invalidates_estimate_and_editor_opens_new_current_source(site):
    cfg, opts = current_profile()
    activate((cfg, opts))
    data=book((2,))
    prepared=monitor.schedule_version_preview(PROJECT,data,DAY,baseline_scope='remaining_work')
    monitor.approve_schedule_version(PROJECT,data,DAY,baseline_scope='remaining_work',
        expected_previous_sha256=prepared['expected_previous_sha256'],expected_source_sha256=prepared['source_sha256'])
    state=monitor.build(PROJECT,DAY)['schedule']['readiness']
    assert state['project']['progress'] is None
    editor=ready.editor(PROJECT)
    assert editor['configuration']['full_source_sha256'] == prepared['source_sha256']
    assert {row['id'] for row in editor['works']} == {'2'}
    assert not editor['configuration']['element_profile']['assignments']


def test_fast_gpr_view_has_canonical_facts_and_readiness_without_finance(site, api, monkeypatch):
    cfg, opts = current_profile()
    activate((cfg,opts))
    monkeypatch.setattr(monitor,'build',lambda *a,**k:pytest.fail('full financial view was read'))
    monkeypatch.setattr(monitor.actuals,'read_estimate',lambda *a,**k:pytest.fail('estimate workbook was parsed'))
    client,_=api
    response=post(client,'gpr-view',project=PROJECT,cut=DAY)
    assert response.status_code==200
    assert response.headers['cache-control']=='private, no-store'
    view=response.json()
    assert len(view['schedule']['rows'])==2
    assert len(view['schedule']['work_fact']['works'])==2
    assert view['schedule']['readiness']['corpora'][0]['progress']==pytest.approx(.5)
    assert 'gprMatrix' in view['schedule']['readiness_html']
    assert view['financial_state']['state']=='not_requested'


def test_fast_gpr_view_authentication_happens_before_any_source_read(api, monkeypatch):
    import developaid_monitor_pace as pace
    monkeypatch.setattr(pace,'schedule_view',lambda *a,**k:pytest.fail('source read before authentication'))
    client,_=api
    for key in ('','wrong','market-only-key'):
        response=post(client,'gpr-view',key=key,project='private',cut=DAY)
        assert response.status_code==403
        assert response.headers['cache-control']=='private, no-store'


@pytest.mark.parametrize('width',[390,1440])
def test_estimate_editor_does_not_ask_to_certify_the_full_construction_scope(site, api, monkeypatch, width):
    client,_=api
    monkeypatch.setenv('DEVELOPAID_ADMIN_KEY',BROWSER_KEY)
    with browser_page(width) as (page,responses,errors):
        def route_readiness(route):
            response=client.post(urlsplit(route.request.url).path,json=route.request.post_data_json)
            route.fulfill(status=response.status_code,json=response.json())
        page.route('**/monitor/readiness/**',route_readiness)
        page.locator('#project').fill(PROJECT);page.locator('#cut').fill(DAY)
        page.evaluate('(v)=>{currentView=v;renderGantt(v)}',monitor.build(PROJECT,DAY))
        page.locator('#readinessEditor>summary').click()
        expect(page.locator('[data-work-element]')).to_have_count(2)
        expect(page.locator('#readinessScopeConfirmed')).to_be_hidden()
        expect(page.locator('#readinessEditorBody')).to_contain_text('Полный состав строительства этим не подтверждается')
        assert not errors


def test_saved_estimate_editor_returns_before_the_financial_refresh_finishes(site, api, monkeypatch):
    cfg,opts=current_profile();activate((cfg,opts))
    client,_=api;monkeypatch.setenv('DEVELOPAID_ADMIN_KEY',BROWSER_KEY)
    with browser_page(390) as (page,responses,errors):
        def relay(route):
            answer=client.post(urlsplit(route.request.url).path,json=route.request.post_data_json)
            route.fulfill(status=answer.status_code,json=answer.json())
        held=[]
        page.route('**/monitor/readiness/**',relay)
        page.route('**/monitor/gpr-view',relay)
        page.route('**/monitor/view',lambda route:route.fulfill(status=202,json={'pending':True,'ticket':'c'*32}))
        page.route('**/monitor/view/result',lambda route:held.append(route))
        page.locator('#project').fill(PROJECT);page.locator('#cut').fill(DAY)
        page.evaluate('(v)=>{currentView=v;renderGantt(v)}',monitor.build(PROJECT,DAY))
        page.locator('#readinessEditor>summary').click()
        page.locator('[data-element-weight="frame"]').fill('30')
        page.locator('#readinessSave').click()
        expect(page.locator('#readinessSave')).to_be_enabled()
        expect(page.locator('#refresh')).to_be_disabled()
        expect(page.locator('#readinessScopeConfirmed')).to_be_hidden()
        expect(page.locator('#gprMatrix')).to_be_visible()
        assert len(ready._events(PROJECT))==2
        assert not ready._events(PROJECT)[-1]['profile']['full_scope_confirmed']
        page.unroute('**/monitor/view/result')
        view=monitor.build(PROJECT,DAY)
        page.route('**/monitor/view/result',lambda route:route.fulfill(json={'snapshot':view}))
        for route in held:route.fulfill(json={'snapshot':view})
        expect(page.locator('#refresh')).to_be_enabled()
        assert not errors
