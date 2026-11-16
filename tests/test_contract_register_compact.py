"""Compact rows of «Договоры»: the detail opens by the row, by the keyboard and stays open on redraw."""
from __future__ import annotations

import copy

import pytest
from playwright.sync_api import expect

from test_contracts_business_view import business_data
from test_monitor_cumulative_controls import browser_page


def show(page, responses):
    business_data(responses)
    page.locator('#contractsTab').click()
    page.locator('tr[data-contract-id]').first.wait_for()
    return page.locator('tr[data-contract-id]').first


def detail(page, row):
    return page.locator('#contractDialog')


@pytest.mark.parametrize('width', [390, 1440])
def test_detail_opens_by_row_and_by_keyboard_and_says_so_to_screen_readers(width):
    with browser_page(width) as (page, responses, errors):
        row = show(page, responses)
        modal, toggle = detail(page,row),row.locator('.contract-more-toggle')
        expect(modal).to_be_hidden()
        expect(toggle).to_have_attribute('aria-haspopup','dialog')
        assert toggle.get_attribute('aria-controls')==modal.get_attribute('id')
        row.locator('td.contract-attention').click()
        expect(modal).to_be_visible()
        page.keyboard.press('Escape')
        expect(modal).to_be_hidden()
        toggle.focus()
        page.keyboard.press('Enter')
        expect(modal).to_be_visible()
        page.locator('#contractDialogClose').click()
        expect(toggle).to_be_focused()
        page.keyboard.press('Space')
        expect(modal).to_be_visible()
        page.locator('#contractDialogClose').click()
        row.locator('.contract-open').click()
        expect(modal).to_be_visible()
        assert not errors


def test_search_redraw_happens_after_the_modal_is_closed():
    with browser_page(1440) as (page,responses,errors):
        row=show(page,responses)
        row.locator('td.party').click()
        expect(detail(page,row)).to_be_visible()
        contract=row.locator('.contract-identity').text_content().split(' · ')[0]
        page.locator('#contractDialogClose').click()
        page.locator('#contractsSearch').fill(contract)
        expect(page.locator('tr[data-contract-id]')).to_have_count(1)
        expect(page.locator('#contractDialog')).to_be_hidden()
        expect(page.locator('#contractsDetails')).to_be_empty()
        assert not errors


def test_header_stays_on_screen_while_a_long_register_scrolls():
    with browser_page(1440) as (page, responses, errors):
        data = business_data(responses)
        for number in range(12):
            extra = copy.deepcopy(data['rows'][2])
            extra.update(id=f'{number:02d}' * 32, contract=f'Д-{10 + number}')
            data['rows'].append(extra)
        page.locator('#contractsTab').click()
        rows = page.locator('tr[data-contract-id]')
        expect(rows).to_have_count(15)
        rows.nth(10).scroll_into_view_if_needed()
        page.mouse.wheel(0, 200)
        page.wait_for_timeout(100)
        head = page.locator('.contract-register th').first.bounding_box()
        first = rows.first.bounding_box()
        assert first['y'] + first['height'] < 0, 'the register must scroll past its first row'
        assert -1 <= head['y'] <= 2, head
        assert not errors


def test_print_does_not_cut_a_short_row_with_an_ellipsis():
    with browser_page(1440) as (page, responses, errors):
        data = business_data(responses)
        data['rows'][0]['subject'] = 'Монтаж инженерных сетей и других работ по длинному перечню ' * 4
        page.locator('#contractsTab').click()
        expect(page.locator('tr[data-contract-id]')).to_have_count(3)
        cut = '''() => [...document.querySelectorAll('tr.contract-row *')]
            .filter(e => e.offsetWidth && e.scrollWidth > e.clientWidth + 1 && getComputedStyle(e).textOverflow === 'ellipsis')
            .map(e => e.textContent)'''
        assert page.evaluate(cut), 'on screen the long list of works is shortened'
        page.emulate_media(media='print')
        assert page.evaluate(cut) == []
        assert not errors
