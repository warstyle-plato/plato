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
    return page.locator(f'tr[data-contract-detail="{row.get_attribute("data-contract-id")}"]')


@pytest.mark.parametrize('width', [390, 1440])
def test_detail_opens_by_row_and_by_keyboard_and_says_so_to_screen_readers(width):
    with browser_page(width) as (page, responses, errors):
        row = show(page, responses)
        more, toggle = detail(page, row), row.locator('.contract-more-toggle')
        expect(more).to_be_hidden()
        expect(toggle).to_have_attribute('aria-expanded', 'false')
        assert toggle.get_attribute('aria-controls') == more.get_attribute('id')
        row.locator('td.contract-attention').click()
        expect(more).to_be_visible()
        expect(toggle).to_have_attribute('aria-expanded', 'true')
        toggle.focus()
        page.keyboard.press('Enter')
        expect(more).to_be_hidden()
        expect(toggle).to_have_attribute('aria-expanded', 'false')
        page.keyboard.press('Space')
        expect(more).to_be_visible()
        # The button «Открыть» opens the card and leaves the row as it was.
        row.locator('.contract-open').click()
        expect(more).to_be_visible()
        assert not errors


def test_open_detail_stays_open_when_the_search_redraws_the_table():
    with browser_page(1440) as (page, responses, errors):
        row = show(page, responses)
        row.locator('td.party').click()
        expect(detail(page, row)).to_be_visible()
        contract = row.locator('.contract-identity').text_content().split(' · ')[0]
        page.locator('#contractsSearch').fill(contract)
        expect(page.locator('tr[data-contract-id]')).to_have_count(1)
        row = page.locator('tr[data-contract-id]').first
        expect(detail(page, row)).to_be_visible()
        expect(row.locator('.contract-more-toggle')).to_have_attribute('aria-expanded', 'true')
        expect(row).to_have_class('contract-row open')
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
