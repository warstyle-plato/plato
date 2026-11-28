"""Native source-choice feedback follows the server and stays bound to one card."""
import copy

import pytest
from playwright.sync_api import expect

from tests.test_contract_card_disclosures import card, open_card
from tests.test_monitor_cumulative_controls import CONTRACT, OTHER, browser_page

CHOSEN = 'b' * 64
FILENAME = 'Учебный нижний файл ГПР.pdf'
REFERENCE = 'Подпись подрядчика проверена, страница 5'


class ChoiceServer:
    def __init__(self, page):
        self.initial = card()
        self.initial['gpr']['guard'] = 'synthetic-exact-source-guard'
        self.initial['gpr']['pending'].append({
            'title': 'Дополнительное соглашение № 2', 'filename': FILENAME,
            'source': {'sha256': CHOSEN}, 'choice_required': True, 'can_activate': True})
        self.active = copy.deepcopy(self.initial)
        self.active['gpr'].update(source={'sha256': CHOSEN},
                                 schedule=self.active['gpr']['preview']['schedule'],
                                 presentation=self.active['gpr']['preview']['presentation'])
        self.active['gpr'].pop('preview')
        self.active['gpr']['pending'] = self.active['gpr']['pending'][:1]
        self.active['gpr_export'].update(mode='active', draft=False)
        self.calls, self.mutations, self.reloads = [], [], []
        self.documents = 0
        page.route('**/monitor/contracts/documents', self.documents_route)
        page.route('**/monitor/contracts/gpr-change', self.change_route)

    @staticmethod
    def reply(route, dto):
        route.fulfill(json={**copy.deepcopy(dto), 'ticket': route.request.post_data_json['ticket']})

    def documents_route(self, route):
        body = route.request.post_data_json
        self.calls.append(('documents', body))
        self.documents += 1
        if self.documents == 1 or body['contract_id'] != CONTRACT:
            self.reply(route, self.initial)
        else:
            self.reloads.append(route)

    def change_route(self, route):
        self.calls.append(('gpr-change', route.request.post_data_json))
        self.mutations.append(route)


def form(page, index=1):
    return page.locator(f'[data-gpr-pending="{index}"]')


def choose(page, signed=True, note=REFERENCE):
    page.locator('#contractGprChooseSource').click()
    selected = form(page)
    if signed:
        selected.locator('[data-gpr-signed]').check()
    selected.locator('[data-gpr-sign-reference]').fill(note)
    selected.locator('[data-gpr-activate]').click()
    return selected


def finish_mutation(page, server, dto=None):
    server.reply(server.mutations[-1], dto or server.active)
    expect(page.locator('#contractGprChoiceMsg')).to_contain_text('Проверяю источник')
    assert len(server.reloads) == 1


@pytest.mark.parametrize('width', [390, 440, 1440])
def test_loading_is_local_and_success_waits_for_exact_canonical_reload(width):
    with browser_page(width) as (page, _, errors):
        server = ChoiceServer(page)
        open_card(page)
        selected = choose(page)
        button = selected.locator('[data-gpr-activate]')
        expect(button).to_have_text('Сохраняю выбор…')
        expect(selected.locator('[data-gpr-choice-msg]')).to_contain_text(FILENAME)
        expect(selected.locator('[data-gpr-choice-msg]')).to_be_in_viewport()
        assert page.locator('#contractGpr input,#contractGpr button').evaluate_all('(els)=>els.every(e=>e.disabled)')
        expect(page.locator('#contractGprDownload')).to_be_disabled()
        # Invoke the real handler a second time, even though a disabled native
        # button already prevents an ordinary second click.
        page.evaluate('activateContractGpr(1,document.querySelector("[data-gpr-activate=\\"1\\"]"))')
        assert len(server.mutations) == 1
        sent = server.calls[-1][1]
        assert sent['source_sha256'] == CHOSEN and sent['expected_guard'] == 'synthetic-exact-source-guard'
        assert sent['counterparty_signed'] is True and sent['note'] == REFERENCE
        finish_mutation(page, server)
        expect(page.locator('#contractGprChoiceMsg')).not_to_have_class('msg good')
        assert page.evaluate('contractGprChoiceFeedback.pending') is True
        assert page.locator('#contractGpr input,#contractGpr button').evaluate_all('(els)=>els.every(e=>e.disabled)')
        server.reply(server.reloads[-1], server.active)
        status = page.locator('#contractGprChoiceMsg')
        expect(status).to_have_class('msg good')
        expect(status).to_contain_text(FILENAME)
        expect(status).to_contain_text('сохранён и подтверждён')
        expect(status).to_be_in_viewport()
        expect(status).to_have_attribute('role', 'status')
        expect(status).to_have_attribute('aria-live', 'polite')
        assert page.evaluate('contractGprState.source.sha256') == CHOSEN
        assert page.locator('#contractGprDownload').count() == 1
        assert page.locator('#contractGprDownload').evaluate('(e)=>!e.closest("details")')
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        assert not errors


@pytest.mark.parametrize('missing', ['signature', 'reference'])
def test_validation_is_visible_next_to_the_clicked_form_without_a_request(missing):
    with browser_page(390) as (page, _, errors):
        server = ChoiceServer(page)
        open_card(page)
        selected = choose(page, signed=missing != 'signature', note='' if missing == 'reference' else REFERENCE)
        expect(selected.locator('[data-gpr-choice-msg]')).to_have_class('msg bad')
        expect(selected.locator('[data-gpr-choice-msg]')).to_contain_text('Проверьте подпись')
        expect(selected.locator('[data-gpr-choice-msg]')).to_be_in_viewport()
        expect(selected.locator('[data-gpr-activate]')).to_be_enabled()
        assert len(server.mutations) == 0
        assert not errors


@pytest.mark.parametrize('failure', ['conflict', 'network'])
def test_failure_retains_exact_source_fields_and_allows_retry(failure):
    with browser_page(440) as (page, _, errors):
        server = ChoiceServer(page)
        open_card(page)
        selected = choose(page)
        if failure == 'conflict':
            server.mutations[-1].fulfill(status=409, json={'detail': 'Источники изменились. Проверьте выбранный файл.'})
        else:
            server.mutations[-1].abort('connectionfailed')
        expect(selected.locator('[data-gpr-choice-msg]')).to_have_class('msg bad')
        expect(selected.locator('[data-gpr-choice-msg]')).not_to_have_text('')
        expect(selected.locator('[data-gpr-signed]')).to_be_checked()
        expect(selected.locator('[data-gpr-sign-reference]')).to_have_value(REFERENCE)
        expect(selected.locator('[data-gpr-activate]')).to_be_enabled()
        expect(page.locator('#contractGprChoiceMsg')).not_to_have_class('msg good')
        selected.locator('[data-gpr-activate]').click()
        expect(selected.locator('[data-gpr-activate]')).to_be_disabled()
        assert len(server.mutations) == 2
        finish_mutation(page, server)
        server.reply(server.reloads[-1], server.active)
        expect(page.locator('#contractGprChoiceMsg')).to_have_class('msg good')
        assert not errors


@pytest.mark.parametrize('refresh', ['another_source', 'preview', 'missing_source'])
def test_unconfirmed_refresh_never_reports_success(refresh):
    with browser_page(390) as (page, _, errors):
        server = ChoiceServer(page)
        open_card(page)
        choose(page)
        finish_mutation(page, server)
        confirmed = copy.deepcopy(server.active if refresh == 'another_source' else server.initial)
        if refresh == 'another_source':
            confirmed['gpr']['source'] = {'sha256': 'c' * 64}
        elif refresh == 'missing_source':
            confirmed['gpr'] = None
        server.reply(server.reloads[-1], confirmed)
        status = page.locator('#contractGprChoiceMsg')
        expect(status).to_have_class('msg warn')
        expect(status).to_contain_text('пока не подтвердила выбранный файл')
        expect(form(page).locator('[data-gpr-choice-msg]') if refresh == 'preview' else status).to_be_in_viewport()
        assert page.evaluate('contractGprChoiceFeedback.pending') is False
        assert not errors


@pytest.mark.parametrize('next_card', [CONTRACT, OTHER])
def test_closed_or_replaced_card_ignores_old_mutation_response(next_card):
    with browser_page(390) as (page, _, errors):
        server = ChoiceServer(page)
        open_card(page)
        choose(page)
        page.locator('#contractDialogClose').click()
        page.locator(f'tr[data-contract-id="{next_card}"] .contract-open').click()
        if next_card == CONTRACT:
            # This is a fresh open request, rather than the operation's
            # canonical confirmation request; return the unchanged preview.
            assert len(server.reloads) == 1
            server.reply(server.reloads.pop(), server.initial)
        page.locator('#contractGprBody[aria-busy="false"]').wait_for(state='attached')
        server.reply(server.mutations[-1], server.active)
        page.evaluate('()=>new Promise(requestAnimationFrame)')
        expect(page.locator('#contractGprChoiceMsg')).to_have_text('')
        assert page.evaluate('contractDocumentsState.id') == next_card
        assert page.evaluate('contractGprState.source') is None
        assert page.evaluate('contractGprChoiceFeedback') is None
        assert len(server.reloads) == 0
        assert not errors


def test_replacement_candidate_does_not_inherit_signature_or_reference_after_error():
    with browser_page(390) as (page, _, errors):
        server = ChoiceServer(page)
        open_card(page)
        choose(page)
        server.mutations[-1].fulfill(status=409, json={'detail': 'Состав источников изменился.'})
        expect(form(page).locator('[data-gpr-choice-msg]')).to_have_class('msg bad')
        page.evaluate('()=>{void loadContractDocuments(contractDocumentsState.id)}')
        expect(page.locator('#contractDocumentUpload')).to_be_disabled()
        assert len(server.reloads) == 1
        replacement = copy.deepcopy(server.initial)
        replacement['gpr']['pending'][1]['source']['sha256'] = 'c' * 64
        server.reply(server.reloads[-1], replacement)
        expect(form(page).locator('[data-gpr-signed]')).not_to_be_checked()
        expect(form(page).locator('[data-gpr-sign-reference]')).to_have_value('')
        assert not errors


def test_pending_canonical_reload_keeps_loading_until_the_server_finishes():
    with browser_page(390) as (page, _, errors):
        server = ChoiceServer(page)
        polls = []
        page.route('**/monitor/contracts/result', lambda route: polls.append(route))
        open_card(page)
        choose(page)
        finish_mutation(page, server)
        with page.expect_request('**/monitor/contracts/result'):
            server.reloads[-1].fulfill(status=202, json={
                'pending': True, 'ticket': server.reloads[-1].request.post_data_json['ticket']})
        expect(page.locator('#contractGprChoiceMsg')).not_to_have_class('msg good')
        assert page.evaluate('contractGprChoiceFeedback.pending') is True
        assert len(polls) == 1
        server.reply(polls[0], server.initial)
        expect(page.locator('#contractGprChoiceMsg')).to_contain_text('пока не подтвердила выбранный файл')
        expect(form(page).locator('[data-gpr-signed]')).to_be_checked()
        expect(form(page).locator('[data-gpr-sign-reference]')).to_have_value(REFERENCE)
        expect(form(page).locator('[data-gpr-activate]')).to_be_enabled()
        assert not errors


@pytest.mark.parametrize('refresh', ['changed_source', 'missing_source', 'missing_gpr', 'same_source'])
def test_completed_success_stays_affine_to_the_current_canonical_source(refresh):
    with browser_page(390) as (page, _, errors):
        server = ChoiceServer(page)
        open_card(page)
        choose(page)
        finish_mutation(page, server)
        server.reply(server.reloads[-1], server.active)
        status = page.locator('#contractGprChoiceMsg')
        expect(status).to_have_class('msg good')
        confirmed = copy.deepcopy(server.active)
        if refresh == 'changed_source':
            confirmed['gpr']['source'] = {'sha256': 'c' * 64}
        elif refresh == 'missing_source':
            confirmed = copy.deepcopy(server.initial)
        elif refresh == 'missing_gpr':
            confirmed['gpr'] = None
        page.evaluate('()=>{void loadContractDocuments(contractDocumentsState.id)}')
        expect(page.locator('#contractDocumentUpload')).to_be_disabled()
        assert len(server.reloads) == 2
        server.reply(server.reloads[-1], confirmed)
        expect(page.locator('#contractDocumentUpload')).to_be_enabled()
        if refresh == 'same_source':
            expect(status).to_have_class('msg good')
            expect(status).to_contain_text(FILENAME)
        else:
            expect(status).to_have_text('')
            expect(status).not_to_have_class('msg good')
            assert page.evaluate('contractGprChoiceFeedback') is None
        assert not errors
