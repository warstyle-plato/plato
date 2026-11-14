"""On a phone every row of «Договоры» is a card: no sideways scroll, every cell is signed, warnings are whole."""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from test_contract_register_compact import detail, show
from test_monitor_cumulative_controls import browser_page

CELLS = '''(root) => [...root.querySelectorAll('tr.contract-row > td')].filter(td => td.offsetWidth)
    .map(td => ({label: td.dataset.label || '', shown: getComputedStyle(td, '::before').content,
                 display: getComputedStyle(td).display}))'''
# A warning is cut when it is clipped by an ellipsis or pushed outside its own card.
CUT = '''(root) => [...root.querySelectorAll('tr.contract-row :is(.contract-risk,.contract-sub.warn)')]
    .filter(e => e.offsetWidth).filter(e => {
        const card = e.closest('tbody').getBoundingClientRect(), box = e.getBoundingClientRect();
        return e.scrollWidth > e.clientWidth + 1 || box.left < card.left - 1 || box.right > card.right + 1
            || box.right > innerWidth + 1;
    }).map(e => e.textContent)'''


def test_each_register_row_is_a_signed_card_on_a_phone():
    with browser_page(390) as (page, responses, errors):
        responses.data['rows'][0]['contractor'] = 'Общество с ограниченной ответственностью «Строительная компания»'
        row = show(page, responses)
        wrap = page.locator('#contractsRows .contract-register-wrap')
        assert wrap.evaluate('(w) => w.scrollWidth <= w.clientWidth')
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        expect(page.locator('#contractsRows thead')).to_be_hidden()
        cells = page.locator('#contractsRows').evaluate(CELLS)
        assert len(cells) == 3 * 6
        assert all(c['display'] == 'block' or c['display'] == 'flex' for c in cells), cells
        assert all(c['label'] and c['shown'] == f'"{c["label"]}"' for c in cells), cells
        # Cells go top to bottom inside one card.
        tops = row.locator('td').evaluate_all('(tds) => tds.map(td => td.getBoundingClientRect().top)')
        assert tops == sorted(tops) and len(set(tops)) == 6
        warning = row.locator('.contract-sub.warn').filter(has_text='Сумма превышена')
        expect(warning).to_contain_text('Сумма превышена на 977 700 ₽')
        assert page.locator('#contractsRows').evaluate(CUT) == []
        name = row.locator('td.party b')
        assert name.evaluate('(b) => b.scrollWidth <= b.clientWidth + 1 && getComputedStyle(b).textOverflow !== "ellipsis"')
        hint = page.locator('#contractsRows .contract-scroll-hint')
        expect(hint).to_have_text('Нажмите на договор, чтобы увидеть подробности.', use_inner_text=True)
        # The same dialog opens from the row and fits the screen.
        more = detail(page, row)
        row.locator('td.contract-attention').click()
        expect(more).to_be_visible()
        # Loading the documents replaces the summary; measure its settled DOM.
        expect(page.locator('#contractDocumentUpload')).to_be_enabled()
        pill = more.locator('.contract-card-pill').first
        expect(pill).to_be_visible()
        part = pill.bounding_box()
        assert part is not None
        assert part['x'] >= 0 and part['x'] + part['width'] <= 390
        assert wrap.evaluate('(w) => w.scrollWidth <= w.clientWidth')
        page.locator('#contractDialogClose').click()
        expect(more).to_be_hidden()
        assert not errors


@pytest.mark.parametrize('media', ['screen', 'print'])
def test_wide_screen_and_print_keep_the_table(media):
    with browser_page(1440) as (page, responses, errors):
        row = show(page, responses)
        page.emulate_media(media=media)
        table = page.locator('#contractsRows table.contract-register')
        assert table.evaluate('(t) => getComputedStyle(t).display') == 'table'
        assert row.locator('td').evaluate_all('(tds) => tds.filter(td => td.offsetWidth).map(td => getComputedStyle(td).display)') \
            == ['table-cell'] * (6 if media == 'screen' else 5)
        assert row.locator('td').first.evaluate("(td) => getComputedStyle(td, '::before').content") in ('none', 'normal')
        expect(page.locator('#contractsRows thead')).to_be_visible()
        expect(page.locator('#contractsRows .contract-scroll-hint')).to_be_hidden()
        assert not errors
