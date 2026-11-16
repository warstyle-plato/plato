"""Expert estimates are explicit, labelled and independent of task count."""
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

import developaid_monitor as monitor
import developaid_schedule_elements as elements
import developaid_schedule_internal_weights as internal
import developaid_schedule_readiness as ready
from test_schedule_cost_weights import configured_cost_site
from test_schedule_readiness import site, PROJECT, DAY, activate
from test_schedule_readiness_elements import reading
from test_monitor_cumulative_api import api
from test_monitor_cumulative_controls import browser_page, KEY as BROWSER_KEY


@pytest.mark.parametrize('minor_tasks', [1, 3, 20])
def test_expert_estimate_keeps_small_tasks_combined_share(minor_tasks):
    rows = [reading('main', 1)] + [reading(str(i), 0) for i in range(minor_tasks)]
    cfg = dict(id=elements.PROFILE_ID, overrides={}, objects={'Корпус 1': 'residential'},
               assignments={'main': dict(element_id='frame', share=95),
                            **{str(i): dict(element_id='frame', share=5/minor_tasks) for i in range(minor_tasks)}})
    elements.validate(cfg, {r['id']: r for r in rows})
    state = elements.projection(rows, cfg, cut=DAY, confirmed=True)
    assert state['project']['progress'] == pytest.approx(.95)
    assert state['project']['known_weight'] == pytest.approx(25)
    assert state['internal_weight_methods'] == [internal.EXPERT_LABEL]
    # A missing estimate cannot take part of the known work's share.
    cfg['assignments']['0']['share'] = None
    weights, reasons = elements.weights(cfg, {r['id']: r for r in rows})
    assert not weights and reasons


@pytest.mark.parametrize('width', [390, 1440])
def test_editor_can_replace_cost_with_labelled_expert_shares(site, api, monkeypatch, width):
    client, _ = api
    monkeypatch.setenv('DEVELOPAID_ADMIN_KEY', BROWSER_KEY)
    activate(configured_cost_site(site))
    with browser_page(width) as (page, responses, errors):
        def route_readiness(route):
            result = client.post(urlsplit(route.request.url).path, json=route.request.post_data_json)
            route.fulfill(status=result.status_code, json=result.json())
        page.route('**/monitor/readiness/**', route_readiness)
        page.route('**/monitor/daily/summary*', lambda route: route.fulfill(json={}))
        page.route('**/monitor/view', lambda route: route.fulfill(json=monitor.build(PROJECT, DAY)))
        page.locator('#project').fill(PROJECT)
        page.locator('#cut').fill(DAY)
        page.evaluate('(v)=>{currentView=v;renderGantt(v)}', monitor.build(PROJECT, DAY))
        page.locator('#readinessEditor>summary').click()
        details = page.locator('#readinessEditorBody>details').filter(has=page.locator('.readiness-works'))
        details.locator('summary').first.click()
        main = page.locator('.readiness-work').filter(has=page.locator('[data-work-element="1"]'))
        minor = page.locator('.readiness-work').filter(has=page.locator('[data-work-element="2"]'))
        for card, share in [(main, '90'), (minor, '10')]:
            card.locator('[data-work-weight-basis]').select_option('expert')
            expect(card.locator('[data-work-share]')).to_be_editable()
            expect(card.locator('[data-weight-measure]')).to_be_hidden()
            card.locator('[data-work-share]').fill(share)
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.locator('#readinessSave').click()
        expect(page.locator('#readinessSummary .readiness-project-value')).to_have_text('95,0%')
        expect(page.locator('#readinessSummary')).to_contain_text(internal.EXPERT_LABEL)
        state = ready.editor(PROJECT)
        assignments = state['configuration']['element_profile']['assignments']
        assert assignments == {'1': dict(element_id='frame', share=90), '2': dict(element_id='frame', share=10)}
        assert state['history'][-1]['internal_methods'] == [internal.EXPERT_LABEL]
        import developaid_management_report as report
        view = monitor.build(PROJECT, DAY)
        assert report.gantt(view, view['dashboard'])['readiness']['internal_weight_methods'] == [internal.EXPERT_LABEL]
        details.locator('summary').first.click()
        expect(main.locator('[data-work-weight-basis]')).to_have_value('expert')
        expect(main.locator('[data-work-share]')).to_have_value('90')
        main.locator('[data-work-share]').fill('')
        page.locator('#readinessSave').click()
        expect(page.locator('#readinessEditorMsg')).to_contain_text('пустое поле не равно нулю')
        assert ready.editor(PROJECT)['configuration']['element_profile']['assignments'] == assignments
        main.locator('[data-work-weight-basis]').select_option('smr_cost')
        expect(main.locator('[data-work-weight-value]')).to_have_value('')
        expect(main.locator('[data-work-weight-source]')).to_have_value('')
        expect(main.locator('[data-work-weight-full]')).not_to_be_checked()
        assert not errors
