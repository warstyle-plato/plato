"""The real private Monitor register is usable on a phone and as a working printout.

Fixtures are synthetic; money/identity/matching calculations remain backend-owned.
"""
from __future__ import annotations

import copy
import io

import pytest
from playwright.sync_api import expect
from pypdf import PdfReader

from contract_rows import opened
from test_monitor_cumulative_controls import browser_page, CONTRACT, OTHER, KEY


def business_data(responses):
    data = responses.data
    data.update(cut='2026-11-06', source_date='2026-11-05')
    first, second = data['rows']
    first.update(subject='Монтаж инженерных сетей', source={'filename': 'private-source-marker.xlsx', 'sheet': 'Ведомость', 'row': 41},
                 deadline='2026-11-01', deadline_passed=True)
    first['reconciliation']['daily_evidence'].append({
        'id': 'confirmed-02', 'date': '2026-11-02', 'text': 'Монтаж в корпусе А',
        'match_status': 'confirmed', 'contract_id': CONTRACT, 'link_basis': 'manual'})
    second.update(subject='', physical_items=[], amount=None, completed=None,
                  completion_ratio=None, remaining=None)
    third = copy.deepcopy(second)
    third.update(id='c'*64, contractor='Подрядчик В', contract='Д-03', subject='Отделка',
                 amount=1_000_000, completed=1_000_000, completion_ratio=1.0, remaining=0,
                 deadline=None)
    data['rows'].append(third)
    return data


@pytest.mark.parametrize('width', [390, 1440])
def test_real_business_register_keeps_core_facts_visible_and_sources_closed(width):
    with browser_page(width) as (page, responses, errors):
        business_data(responses)
        page.locator('#contractsTab').click()
        first = page.locator(f'tr[data-contract-id="{CONTRACT}"]')
        # The short row answers the main questions: amount, share done, overrun, term and what needs attention.
        expect(first).to_contain_text('1\u00a0000\u00a0000 ₽')
        expect(first).to_contain_text('197,8%')
        expect(first).to_contain_text('Сумма превышена на 977\u00a0700 ₽')
        expect(first).to_contain_text('01.11.2026')
        expect(first.locator('.contract-attention .contract-risk')).to_have_text(
            ['Сумма превышена', 'Срок прошёл', 'Есть замечания', 'ещё 1'])
        more = page.locator(f'tr[data-contract-detail="{CONTRACT}"]')
        expect(more).to_be_hidden()
        assert first.evaluate('(r)=>r.getBoundingClientRect().height') <= (110 if width < 900 else 80)
        more = opened(page, CONTRACT)
        expect(more).to_contain_text('1\u00a0977\u00a0700 ₽')
        expect(more).to_contain_text('-977\u00a0700 ₽')
        expect(more).to_contain_text('Связей с договором: 1 · проверить: 1')
        expect(more).to_contain_text('Проверить исполнение: срок прошёл. Есть замечания к данным. Проверить связь с работами')
        for shown in (first, more):
            expect(shown).not_to_contain_text('Договор исполнен')
        # Source evidence remains accessible, with no technical filename on the default surface.
        sources = more.locator('.contract-sources')
        assert not sources.evaluate('(el)=>el.open')
        expect(sources.locator('.contract-source').filter(has_text='private-source-marker')).to_be_hidden()
        sources.locator('summary').click()
        expect(sources.locator('.contract-source').filter(has_text='private-source-marker')).to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        # Owner's decision: a table everywhere. On a phone the register keeps its
        # columns and its own wrapper scrolls sideways; the page itself does not.
        assert page.locator('#contractsRows table.contract-register').evaluate(
            '(t)=>getComputedStyle(t).display') == 'table'
        assert first.locator('td').count() == 6
        wrap = page.locator('#contractsRows .contract-register-wrap')
        if width < 900:
            assert wrap.evaluate('(w)=>w.scrollWidth > w.clientWidth')
            expect(page.locator('#contractsRows .contract-scroll-hint')).to_be_visible()
            last = first.locator('td').last
            last.scroll_into_view_if_needed()
            box = last.bounding_box()
            assert box is not None and box['x'] >= -1 and box['x'] < width
            # The opened detail stays on the screen while the table scrolls sideways.
            part = more.locator('.contract-more-part').first.bounding_box()
            assert part is not None and part['x'] >= 0 and part['x'] + part['width'] <= width
        sources.locator('summary').click()
        second = page.locator(f'tr[data-contract-id="{OTHER}"]')
        assert second.locator('.contract-main-money').all_text_contents() == ['—']
        expect(second).to_contain_text('полная сумма не подтверждена')
        expect(second).to_contain_text('выполнение не подтверждено')
        expect(second).to_contain_text('Нужен срок')
        expect(second).to_contain_text('Работы не указаны')
        expect(second).not_to_contain_text('просрочен')
        expect(second).not_to_contain_text('0%')
        # 100% does not erase a missing contractual deadline or promise legal fulfilment.
        third = page.locator('tr[data-contract-id="'+'c'*64+'"]')
        expect(third).to_contain_text('100%')
        expect(third.locator('.contract-attention')).to_have_text('Нужен срок')
        expect(opened(page, 'c'*64)).to_contain_text('Уточнить срок')
        expect(page.locator('#contractsSummary')).to_contain_text('Выполнение 100% суммы договора')
        assert not errors


def test_actual_print_is_a4_landscape_paginated_with_business_fields_only():
    with browser_page(390) as (page, responses, errors):
        data = business_data(responses)
        template = data['rows'][0]
        data['rows'] = []
        for index in range(30):
            row = copy.deepcopy(template)
            row.update(id=f'{index:064x}', contract=f'DEMO-{index:02d}', contractor=f'Подрядчик {index:02d}')
            data['rows'].append(row)
        page.locator('#contractsTab').click()
        expect(page.locator('tr[data-contract-id]')).to_have_count(30)
        # Even opened source evidence, term editor and unmatched details are excluded from print.
        more = opened(page)
        more.locator('.contract-sources summary').click()
        more.locator('.contract-term').click()
        page.locator('#contractsUnmatched > .contract-detail > summary').click()
        pdf = PdfReader(io.BytesIO(page.pdf(prefer_css_page_size=True, print_background=True)))
        assert len(pdf.pages) >= 3
        texts = []
        for sheet in pdf.pages:
            assert float(sheet.mediabox.width) == pytest.approx(841.89, abs=2)
            assert float(sheet.mediabox.height) == pytest.approx(595.28, abs=2)
            text = ' '.join((sheet.extract_text() or '').split())
            texts.append(text)
            assert 'Договор' in text and 'График договора' in text and 'Внимание' in text
        text = ' '.join(texts)
        assert all(f'DEMO-{index:02d}' in text for index in range(30))
        # Print opens the detail of every contract: no business field is left behind a click.
        for necessary in ['Учебный проект', '06.11.2026', '05.11.2026', '1 000 000', '197,8%', '977 700', '01.11.2026', 'не оплата',
                          '1 977 700', 'Связь со стройкой', 'Есть совпадения — проверьте', 'Проверить исполнение: срок прошёл']:
            assert necessary in text
            assert text.count(necessary) >= (30 if necessary.startswith('Проверить') else 1)
        for private_or_control in [KEY, 'private-source-marker', 'Указать срок', 'Изменить срок', 'Сохранить срок', 'Ключ администратора', 'Разделы проекта', 'Открыть']:
            assert private_or_control not in text
        assert not errors


def test_auth_rejection_erases_new_summaries_and_source_evidence():
    with browser_page() as (page, responses, errors):
        business_data(responses)
        page.locator('#contractsTab').click()
        expect(page.locator('#contractsSummary b')).to_have_count(3)
        responses.reject_key = True
        page.locator('#contractsRefresh').click()
        expect(page.locator('#privateArea')).to_be_hidden()
        for host in ['contractsSummary', 'contractsPrintHeading', 'contractsSource', 'contractsWarnings', 'contractsRows', 'contractsDetails', 'contractsUnmatched']:
            assert page.locator('#'+host).text_content() == ''
        assert not errors


def test_daily_candidates_do_not_inherit_confirmation_for_another_contract():
    with browser_page() as (page, responses, errors):
        business_data(responses)
        evidence = responses.data['rows'][0]['reconciliation']['daily_evidence']
        evidence[1].update(contract_id=OTHER, link_basis='explicit_number')
        page.locator('#contractsTab').click()
        first = page.locator(f'tr[data-contract-id="{CONTRACT}"]')
        expect(first.locator('.contract-attention .contract-risk').last).to_have_attribute('title', 'Сверить с работами')
        more = opened(page, CONTRACT)
        expect(more).to_contain_text('Есть совпадения — проверьте')
        expect(more).not_to_contain_text('Связей с договором:')
        first.locator('.contract-open').click()
        expect(page.locator('#contractsDetails')).to_contain_text('Сообщение связано с другим договором')
        assert page.locator('#contractsDetails .evidence-remove').count() == 0
        # Only the unconfirmed candidate has an editable choice; the foreign link is untouched.
        assert page.locator('#contractsDetails .evidence-choice').count() == 1
        assert responses.links == []
        evidence[1].update(contract_id=CONTRACT)
        page.locator('#contractsRefresh').click()
        first.locator('.contract-open').click()
        expect(page.locator('#contractsDetails')).to_contain_text('Договор определён по номеру в сообщении')
        assert page.locator('#contractsDetails .evidence-remove').count() == 1
        assert not errors


@pytest.mark.parametrize('width', [390, 1440])
def test_passed_contract_deadline_stays_in_attention_count_filter_and_next_step(width):
    with browser_page(width) as (page, responses, errors):
        row = responses.data['rows'][0]
        row.update(amount=1_000_000, completed=500_000, completion_ratio=.5,
                   remaining=500_000, deadline='2026-11-01', deadline_passed=True,
                   warnings=[])
        row['reconciliation'] = {'issues': [], 'daily_evidence': [{
            'id': 'own-confirmed', 'date': '2026-11-02', 'text': 'Работы по договору',
            'match_status': 'confirmed', 'contract_id': CONTRACT, 'link_basis': 'manual'}]}
        future = copy.deepcopy(row)
        future.update(id=OTHER, deadline='2026-12-01', deadline_passed=False)
        future['reconciliation']['daily_evidence'][0]['contract_id'] = OTHER
        responses.data['rows'] = [row, future]
        page.locator('#contractsTab').click()
        expect(page.locator('#contractsSummary b').nth(1)).to_have_text('1')
        passed = page.locator(f'tr[data-contract-id="{CONTRACT}"]')
        expect(passed.locator('.contract-attention')).to_have_text('Срок прошёл')
        more = opened(page, CONTRACT)
        expect(more.locator('.contract-next')).to_have_text(
            'Проверить исполнение: срок прошёл')
        expect(more).to_contain_text('Срок прошёл; проверьте исполнение')
        for shown in (passed, more):
            expect(shown).not_to_contain_text('Договор не исполнен')
            expect(shown).not_to_contain_text('Нарушение договора')
        page.locator('#contractsFilter').select_option('warnings')
        expect(page.locator('tr[data-contract-id]')).to_have_count(1)
        expect(passed).to_be_visible()
        # A known future deadline alone does not require checking or become a missing term.
        page.locator('#contractsFilter').select_option('no-term')
        expect(page.locator('tr[data-contract-id]')).to_have_count(0)
        row.update(deadline='2026-12-01', deadline_passed=False)
        page.locator('#contractsRefresh').click()
        expect(page.locator('#contractsSummary b').nth(1)).to_have_text('0')
        page.locator('#contractsFilter').select_option('warnings')
        expect(page.locator('tr[data-contract-id]')).to_have_count(0)
        assert not errors
