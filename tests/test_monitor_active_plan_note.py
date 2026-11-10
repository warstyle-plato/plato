"""The Monitor names the plan version it compares against and why a newer one waits."""
import base64
import json

import pytest

import developaid_monitor as monitor
from test_schedule_completed_facts import site, book, PROJECT, TODAY, OLD_DAY  # noqa: F401

FUTURE = '2026-11-12'


def approve(data, day=TODAY, scope=None):
    preview = monitor.schedule_version_preview(PROJECT, data, day, baseline_scope=scope)
    return monitor.approve_schedule_version(PROJECT, data, day,
        expected_previous_sha256=preview['expected_previous_sha256'],
        expected_source_sha256=preview['source_sha256'], baseline_scope=scope)


def plan(cut):
    return monitor.build(PROJECT, cut)['schedule']['approved_plan']


def test_view_names_the_applied_version_and_the_reason_a_newer_one_waits(site):
    approve(book('Текущий план', .25, '2027-06-30'))
    approve(book('Будущий план', .5, '2027-07-31'), day=FUTURE)
    past, current = plan(OLD_DAY), plan(TODAY)
    assert past['revision'] == 0 and past['latest_revision'] == 2
    assert past['latest_pending'] == 'future' and past['latest_effective_from'] == FUTURE
    assert current['revision'] == 1 and current['effective_from'] == TODAY and current['approved_at']
    assert current['latest_pending'] == 'future' and current['baseline_scope'] == 'full_schedule'
    assert 'latest_pending' not in plan(FUTURE)


def test_past_cut_reports_the_earlier_date_and_a_final_plan_reaches_it(site):
    approve(book('Текущий план', .25, '2027-06-30'))
    past = plan(OLD_DAY)
    assert past['revision'] == 0 and past['latest_revision'] == 1
    assert past['latest_pending'] == 'earlier_cut'
    approve(book('Окончательный план', .3, '2027-08-31'), scope='remaining_work')
    final = plan(OLD_DAY)
    assert final['revision'] == 2 and final['baseline_scope'] == 'remaining_work'
    assert 'latest_pending' not in final


def note(page, value, cut=OLD_DAY):
    return page.evaluate('([p,c])=>{const e=document.createElement("div");e.innerHTML=activePlanNote(p,c);'
                         'return e.textContent}', [value, cut])


def test_real_page_explains_each_plan_state():
    from test_monitor_cumulative_controls import browser_page
    sha = 'c' * 64
    base = {'source_sha256': sha, 'revision': 1, 'effective_from': TODAY, 'approved_at': TODAY+'T12:00:00+00:00',
            'baseline_scope': 'full_schedule', 'latest_revision': 1, 'latest_effective_from': TODAY}
    with browser_page(390) as (page, responses, errors):
        text = note(page, base)
        assert 'версия 1' in text and 'c'*12 in text and 'c'*13 not in text
        assert 'сравнивается с планом, который действовал' in text and 'уже утверждена' not in text
        future = note(page, dict(base, latest_revision=2, latest_effective_from=FUTURE, latest_pending='future'))
        assert 'Версия 2 уже утверждена и начнёт действовать с 12.11.2026' in future
        earlier = note(page, dict(base, revision=0, latest_revision=1, latest_pending='earlier_cut'))
        assert 'первый загруженный ГПР' in earlier and 'выбранная дата 08.11.2026 раньше' in earlier
        assert 'утверждают как окончательный' in earlier
        final = note(page, dict(base, baseline_scope='remaining_work'))
        assert 'окончательный план' in final and 'раньше' not in final
        assert note(page, None) == ''
        assert not errors


@pytest.mark.parametrize('final', [False, True])
def test_real_page_sends_the_final_plan_choice_to_preview_and_approval(final):
    from playwright.sync_api import expect
    from test_gpr_corpus_baseline import construction_book
    from test_monitor_cumulative_controls import browser_page
    data = construction_book()
    with browser_page(1440) as (page, responses, errors):
        calls = []
        def handle(route):
            body = route.request.post_data_json
            calls.append(body)
            scope = body.get('baseline_scope', 'full_schedule')
            if route.request.url.endswith('version-preview'):
                route.fulfill(json={'works': 3, 'source_sha256': 'b'*64, 'baseline_scope': scope,
                                    'expected_previous_sha256': 'a'*64, 'requires_initial_baseline': False})
            else:
                route.fulfill(json={'revision': 2, 'baseline_scope': scope})
        page.route('**/monitor/schedule/version-*', handle)
        page.locator('#dataTab').click()
        if 'open' not in (page.locator('#setupCard').get_attribute('class') or ''):
            page.locator('#setupHead').click()
        page.locator('#baselineDate').fill(TODAY)
        page.locator('#gpr').set_input_files({'name': 'Approved.xlsx', 'mimeType':
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'buffer': data})
        expect(page.locator('#baselineFinal')).to_be_visible()
        if final:
            page.locator('#baselineFinal').check()
        page.locator('#baselinePreviewBtn').click()
        expect(page.locator('#baselineApproveBtn')).to_be_visible()
        expect(page.locator('#baselineMsg')).to_contain_text('Окончательный план' if final else 'Прежние планы сохранятся')
        page.locator('#baselineApproveBtn').click()
        expect(page.locator('#baselineMsg')).to_contain_text(
            'Окончательный план утверждён' if final else 'Новая версия утверждена')
        assert len(calls) == 2 and base64.b64decode(calls[1]['gpr_base64']) == data
        for body in calls:
            assert body.get('baseline_scope') == ('remaining_work' if final else 'full_schedule')
        assert not errors


def test_real_page_drops_a_review_when_the_final_plan_choice_changes():
    from playwright.sync_api import expect
    from test_gpr_corpus_baseline import construction_book
    from test_monitor_cumulative_controls import browser_page
    with browser_page(390) as (page, responses, errors):
        calls = []
        def handle(route):
            calls.append(route.request.url)
            route.fulfill(json={'works': 3, 'source_sha256': 'b'*64, 'baseline_scope': 'full_schedule',
                                'expected_previous_sha256': 'a'*64, 'requires_initial_baseline': False})
        page.route('**/monitor/schedule/version-*', handle)
        page.locator('#dataTab').click()
        if 'open' not in (page.locator('#setupCard').get_attribute('class') or ''):
            page.locator('#setupHead').click()
        page.locator('#gpr').set_input_files({'name': 'Approved.xlsx', 'mimeType':
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'buffer': construction_book()})
        page.locator('#baselinePreviewBtn').click()
        expect(page.locator('#baselineApproveBtn')).to_be_visible()
        page.locator('#baselineFinal').check()
        expect(page.locator('#baselineApproveBtn')).to_be_hidden()
        assert len(calls) == 1 and not errors


def test_real_page_renders_the_plan_line_from_a_built_view(site):
    from playwright.sync_api import expect
    from test_monitor_cumulative_controls import browser_page
    approve(book('Текущий план', .25, '2027-06-30'))
    view = json.loads(json.dumps(monitor.build(PROJECT, OLD_DAY), default=str, ensure_ascii=False))
    with browser_page(1440) as (page, responses, errors):
        page.route('**/monitor/view', lambda route: route.fulfill(json=view))
        page.locator('#cut').fill(OLD_DAY)
        page.locator('#refresh').click()
        expect(page.locator('#activePlan')).to_contain_text('первый загруженный ГПР')
        expect(page.locator('#activePlan')).to_contain_text('Версия 1 действует с 09.11.2026')
        expect(page.locator('#activePlan')).to_contain_text('выбранная дата 08.11.2026 раньше')


@pytest.mark.parametrize('width', [390, 1440])
def test_final_plan_is_visible_in_the_schedule_and_money_tabs(site, width):
    from pathlib import Path
    from playwright.sync_api import expect
    from test_monitor_cumulative_controls import browser_page
    source = book('Действующий окончательный план', .4, '2027-06-30')
    approve(source, scope='remaining_work')
    view = json.loads(json.dumps(monitor.build(PROJECT, OLD_DAY), default=str, ensure_ascii=False))
    with browser_page(width) as (page, responses, errors):
        page.route('**/monitor/view', lambda route: route.fulfill(json=view))
        # This GET is ancillary to the real view; the generic fixture admits POSTs only.
        page.route('**/monitor/daily/summary**', lambda route: route.fulfill(json={}))
        page.locator('#cut').fill(OLD_DAY)
        page.locator('#refresh').click()
        expect(page.locator('#monitorPanel')).to_be_visible()
        expect(page.locator('#activePlan')).to_be_visible()
        expect(page.locator('#activePlan')).to_contain_text('версия 1')
        expect(page.locator('#activePlan')).to_contain_text('окончательный план')
        expect(page.locator('#activePlan')).to_contain_text(view['schedule']['approved_plan']['source_sha256'][:12])
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        folder = Path('/tmp/plato-pr1060-ui-repair')
        folder.mkdir(exist_ok=True)
        page.screenshot(path=str(folder / f'active-plan-gpr-{width}.png'))
        page.locator('#moneyTab').click()
        expect(page.locator('#activePlan')).to_be_visible()
        page.locator('#cut').fill(TODAY)
        expect(page.locator('#activePlan')).to_be_hidden()
        assert not errors


def test_unchecked_choice_roundtrips_as_an_ordinary_version_after_a_final_plan(site):
    from playwright.sync_api import expect
    from test_monitor_cumulative_controls import browser_page
    approve(book('Предыдущий окончательный план', .25, '2027-06-30'), scope='remaining_work')
    data = book('Новая обычная версия', .4, '2027-07-31')
    with browser_page(1440) as (page, responses, errors):
        calls = []
        def handle(route):
            body = route.request.post_data_json
            calls.append(body)
            raw = base64.b64decode(body['gpr_base64'])
            if route.request.url.endswith('version-preview'):
                result = monitor.schedule_version_preview(PROJECT, raw, body['effective_from'],
                    baseline_scope=body.get('baseline_scope'))
            else:
                result = monitor.approve_schedule_version(PROJECT, raw, body['effective_from'],
                    baseline_scope=body.get('baseline_scope'),
                    expected_previous_sha256=body['expected_previous_sha256'],
                    expected_source_sha256=body['expected_source_sha256'])
            route.fulfill(json=result)
        page.route('**/monitor/schedule/version-*', handle)
        page.locator('#dataTab').click()
        page.locator('#project').fill(PROJECT)
        page.locator('#baselineDate').fill(TODAY)
        page.locator('#gpr').set_input_files({'name': 'Ordinary.xlsx', 'mimeType':
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'buffer': data})
        expect(page.locator('#baselineFinal')).not_to_be_checked()
        page.locator('#baselinePreviewBtn').click()
        expect(page.locator('#baselineApproveBtn')).to_be_visible()
        assert calls[0].get('baseline_scope') == 'full_schedule'
        expect(page.locator('#baselineMsg')).to_contain_text('Прежние планы сохранятся')
        page.locator('#baselineApproveBtn').click()
        expect(page.locator('#baselineMsg')).to_contain_text('Новая версия утверждена')
        assert len(calls) == 2 and calls[1]['baseline_scope'] == 'full_schedule'
        assert monitor._baseline_state(PROJECT, TODAY)['baseline_scope'] == 'full_schedule'
        assert not errors


@pytest.mark.parametrize('existing_scope', ['full_schedule', 'remaining_work'])
def test_same_file_does_not_change_its_scope_in_either_direction(site, existing_scope):
    from playwright.sync_api import expect
    from test_monitor_cumulative_controls import browser_page
    source = book('Уже утверждённый план', .4, '2027-06-30')
    approve(source, scope=existing_scope)
    requested = 'remaining_work' if existing_scope == 'full_schedule' else 'full_schedule'
    before = {str(path): path.read_bytes() for path in site[0].rglob('*') if path.is_file()}
    with browser_page(390) as (page, responses, errors):
        calls = []
        def handle(route):
            assert route.request.url.endswith('version-preview')
            body = route.request.post_data_json
            calls.append(body)
            result = monitor.schedule_version_preview(PROJECT, base64.b64decode(body['gpr_base64']),
                body['effective_from'], baseline_scope=body['baseline_scope'])
            assert result['already_approved'] is True
            route.fulfill(json=result)
        page.route('**/monitor/schedule/version-*', handle)
        page.locator('#dataTab').click()
        page.locator('#project').fill(PROJECT)
        page.locator('#baselineDate').fill(TODAY)
        page.locator('#gpr').set_input_files({'name': 'Same.xlsx', 'mimeType':
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'buffer': source})
        page.locator('#baselineFinal').set_checked(requested == 'remaining_work')
        page.locator('#baselinePreviewBtn').click()
        expect(page.locator('#baselineMsg')).to_contain_text('Повторное утверждение не меняет область его действия')
        expect(page.locator('#baselineApproveBtn')).to_be_hidden()
        assert len(calls) == 1 and calls[0]['baseline_scope'] == requested
        assert monitor._baseline_state(PROJECT, TODAY)['baseline_scope'] == existing_scope
        assert not errors
    assert before == {str(path): path.read_bytes() for path in site[0].rglob('*') if path.is_file()}
