"""A broken transfer resumes one immutable job; no financial rows are pruned."""
import base64
import json
import threading
import time

import pytest
from playwright.sync_api import expect

import developaid_management_report_jobs as jobs
from test_contract_register_result_budget import OWNER, PROFILE, PARAMS, terminal
from test_monitor_cumulative_api import api, post, core
from test_monitor_cumulative_controls import browser_page, CONTRACT


def test_large_multibyte_result_is_bounded_repeatable_and_complete(tmp_path):
    store = jobs.Store(tmp_path / 'jobs')
    payload = {'ok': True, 'register': {'rows': [{'text': 'Источник №42 🚧' * 500000}],
                                     'raw_rows': [{'history': 'Сохранено' * 500000}]}}
    assert len(json.dumps(payload, ensure_ascii=False).encode()) > jobs.MAX_RESULT_BYTES
    calls = []
    def build():
        calls.append(1)
        return payload
    ticket = store.start(OWNER, PROFILE, PARAMS, build, result_limit_bytes=jobs.MAX_EXTENDED_RESULT_BYTES)['ticket']
    expected = terminal(store, ticket)
    parts = []
    offset = 0
    while True:
        part = store.poll_part(ticket, OWNER, PROFILE, offset)
        assert part == jobs.Store(store.root).poll_part(ticket, OWNER, PROFILE, offset)
        assert len(json.dumps(part).encode()) < 360000
        value = part['result_part']
        assert value['offset'] == offset
        raw = base64.b64decode(value['content_base64'], validate=True)
        parts.append(raw)
        offset += len(raw)
        if offset == value['total_bytes']:
            break
    assert len(parts) > 30
    assert {'pending': False, 'ticket': ticket, **json.loads(b''.join(parts))} == expected
    assert len(calls) == 1
    # Retrying admission after completion returns only a small pointer.
    retry = store.start(OWNER, PROFILE, PARAMS, build, ticket,
                        result_limit_bytes=jobs.MAX_EXTENDED_RESULT_BYTES, include_result=False)
    assert retry == {'pending': False, 'ticket': ticket, 'result_ready': True}
    assert len(calls) == 1


def test_part_pending_errors_owner_and_storage_are_not_weakened(tmp_path):
    store = jobs.Store(tmp_path / 'jobs')
    entered, release = threading.Event(), threading.Event()
    def build():
        entered.set()
        assert release.wait(5)
        return {'ok': True}
    ticket = store.start(OWNER, PROFILE, PARAMS, build,
                        result_limit_bytes=jobs.MAX_EXTENDED_RESULT_BYTES)['ticket']
    try:
        assert entered.wait(1)
        assert store.poll_part(ticket, OWNER, PROFILE)['pending']
        for owner, profile in [('another', PROFILE), (OWNER, 'another')]:
            with pytest.raises(jobs.JobProblem) as denied:
                store.poll_part(ticket, owner, profile)
            assert denied.value.status == 404
    finally:
        release.set()
    terminal(store, ticket)
    for offset in (-1, True, 1.2, jobs.MAX_EXTENDED_RESULT_BYTES + 1, 10000):
        with pytest.raises(jobs.JobProblem) as invalid:
            store.poll_part(ticket, OWNER, PROFILE, offset)
        assert invalid.value.status == 400
    store._path(ticket, 'result').unlink()
    with pytest.raises(jobs.JobProblem) as missing:
        store.poll_part(ticket, OWNER, PROFILE)
    assert (missing.value.status, missing.value.code) == (500, 'storage_failed')


def test_authenticated_part_route_and_pinned_admission(api, monkeypatch):
    client, _ = api
    calls = []
    payload = {'ok': True, 'register': {'rows': [{'text': 'Договор' * 50000}]}}
    def build(*args):
        calls.append(1)
        return payload
    monkeypatch.setattr(core, '_monitor_cumulative_execute', build)
    params = dict(project='Fixture', cut='2026-11-16', ticket='9'*32, chunked=True)
    response = post(client, 'contracts/build', **params)
    ticket = response.json()['ticket']
    result = bytearray()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        response = post(client, 'contracts/result-part', ticket=ticket, offset=len(result))
        assert response.headers['cache-control'] == 'private, no-store'
        if response.status_code == 202:
            time.sleep(.005)
            continue
        assert response.status_code == 200
        part = response.json()['result_part']
        result.extend(base64.b64decode(part['content_base64']))
        if len(result) == part['total_bytes']:
            break
    import developaid_contract_control as control
    assert json.loads(result) == {**payload,'contract_calculation_revision':control.CALCULATION_REVISION}
    assert 'contract_calculation_revision' not in payload, 'Fresh stamping must not change producer inputs.'
    assert post(client, 'contracts/build', **params).json() == {
        'pending': False, 'ticket': ticket, 'result_ready': True}
    assert len(calls) == 1
    for key in ['', 'wrong']:
        assert post(client, 'contracts/result-part', key=key, ticket=ticket, offset=0).status_code == 403
    assert post(client, 'contracts/result-part', session='another', ticket=ticket, offset=0).status_code == 404
    for offset in [-1, True, '0', 64*1024*1024+1]:
        assert post(client, 'contracts/result-part', ticket=ticket, offset=offset).status_code == 422


@pytest.mark.parametrize('phase', ['admission', 'first_part', 'later_part'])
def test_browser_recovers_broken_transfer_without_rebuilding_or_losing_rows(phase):
    with browser_page() as (page, responses, errors):
        responses.data['rows'][0]['subject'] = 'Полный объём договора '
        responses.data['warnings'] = ['Источник 🚧' * 100000]
        failed = []
        offsets = []
        tickets = []
        def intercept(route):
            body = route.request.post_data_json
            if route.request.url.endswith('/build'):
                tickets.append(body['ticket'])
                if phase == 'admission' and not failed:
                    failed.append(True)
                    # The request reached the server but its response was lost.
                    responses.jobs[body['ticket']] = ('/monitor/contracts/build', body)
                    return route.abort('connectionfailed')
            else:
                offsets.append(body['offset'])
                if not failed and ((phase == 'first_part' and body['offset'] == 0) or
                                   (phase == 'later_part' and body['offset'] > 0)):
                    failed.append(True)
                    return route.abort('connectionfailed')
            return responses(route)
        page.route('**/monitor/contracts/build', intercept)
        page.route('**/monitor/contracts/result-part', intercept)
        page.locator('#contractsTab').click()
        expect(page.locator(f'tr[data-contract-id="{CONTRACT}"]')).to_be_visible(timeout=15000)
        assert failed and len(set(tickets)) == 1
        assert len(tickets) == (2 if phase == 'admission' else 1)
        assert offsets[-1] > 256*1024
        assert page.evaluate('contractRegister.rows.length') == len(responses.data['rows'])
        assert page.evaluate('contractRegister.warnings[0]') == responses.data['warnings'][0]
        assert 'Связь прервалась' not in page.locator('#contractsMsg').inner_text()
        assert not errors


def test_browser_refresh_after_exhausted_retries_reuses_job_and_context_change_clears_it():
    with browser_page() as (page, responses, errors):
        failed = True
        tickets = []
        offsets = []
        responses.data['warnings'] = ['Сохранённая часть реестра ' * 30000]
        def intercept(route):
            body = route.request.post_data_json
            if route.request.url.endswith('/build'):
                tickets.append(body['ticket'])
            else:
                offsets.append(body['offset'])
                if failed and body['offset'] > 0:
                    return route.abort('connectionfailed')
            return responses(route)
        page.route('**/monitor/contracts/build', intercept)
        page.route('**/monitor/contracts/result-part', intercept)
        page.locator('#contractsTab').click()
        expect(page.locator('#contractsMsg')).to_have_class('msg bad', timeout=15000)
        failed = False
        page.locator('#contractsRefresh').click()
        expect(page.locator(f'tr[data-contract-id="{CONTRACT}"]')).to_be_visible(timeout=10000)
        assert len(tickets) == 1  # Resume polls the old job without admission.
        assert offsets.count(0) == 1  # Already received bytes survive the red error.
        assert page.evaluate('contractRegister.warnings[0]') == responses.data['warnings'][0]
        page.locator('#project').fill('Другой проект')
        expect(page.locator('#contractsSource')).to_contain_text('Срез:', timeout=10000)
        assert tickets[-1] != tickets[0]
        assert not errors


@pytest.mark.parametrize('status',[404,500])
def test_permanent_job_failure_allows_a_fresh_build(status):
    with browser_page() as (page,responses,errors):
        failed=True
        tickets=[]
        def intercept(route):
            body=route.request.post_data_json
            if route.request.url.endswith('/build'):
                tickets.append(body['ticket'])
            elif failed:
                return route.fulfill(status=status,json={'detail':'Предыдущая сборка недоступна.'})
            return responses(route)
        page.route('**/monitor/contracts/build',intercept)
        page.route('**/monitor/contracts/result-part',intercept)
        page.locator('#contractsTab').click()
        expect(page.locator('#contractsMsg')).to_have_class('msg bad',timeout=10000)
        failed=False
        page.locator('#contractsRefresh').click()
        expect(page.locator(f'tr[data-contract-id="{CONTRACT}"]')).to_be_visible(timeout=10000)
        assert tickets[0]!=tickets[1]
        assert not errors



def test_expired_partial_result_is_not_rebuilt_under_its_old_ticket_or_mixed_with_new_bytes():
    with browser_page() as (page,responses,errors):
        state='broken'
        tickets=[]
        responses.data['warnings']=['СТАРЫЙ реестр '+('А'*800000)]
        def intercept(route):
            body=route.request.post_data_json
            if route.request.url.endswith('/build'):
                tickets.append(body['ticket'])
            elif state=='broken' and body['offset']>0:
                return route.abort('connectionfailed')
            elif state=='expired':
                return route.fulfill(status=404,json={'detail':'Сборка уже удалена.'})
            return responses(route)
        page.route('**/monitor/contracts/build',intercept)
        page.route('**/monitor/contracts/result-part',intercept)
        page.locator('#contractsTab').click()
        expect(page.locator('#contractsMsg')).to_have_class('msg bad',timeout=15000)
        assert page.evaluate('contractPendingJob.offset')>0
        old_ticket=tickets[0]
        # Expiration/sweep removed this job. A new builder could return different
        # source bytes of the same size: admitting the old ticket would mix them.
        responses.jobs.clear()
        responses.data['warnings']=['НОВЫЙ  реестр '+('Б'*800000)]
        state='expired'
        page.locator('#contractsRefresh').click()
        expect(page.locator('#contractsMsg')).to_contain_text('Сборка уже удалена.',timeout=10000)
        assert tickets==[old_ticket]
        assert page.evaluate('contractPendingJob') is None
        state='fresh'
        page.locator('#contractsRefresh').click()
        expect(page.locator(f'tr[data-contract-id="{CONTRACT}"]')).to_be_visible(timeout=10000)
        assert len(tickets)==2 and tickets[1]!=old_ticket
        assert page.evaluate('contractRegister.warnings[0]')==responses.data['warnings'][0]
        assert not errors
