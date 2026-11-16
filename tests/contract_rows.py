"""Contract rows open the same modal by click, arrow or the Open button."""
from __future__ import annotations


def row(page, contract_id):
    return page.locator(f'tr[data-contract-id="{contract_id}"]')


def named(page, text):
    """Строка договора с текстом `text` и её раскрытые подробности."""
    main = page.locator('tr[data-contract-id]', has_text=text)
    main.wait_for()
    return main, opened(page, main.get_attribute('data-contract-id'))


def opened(page, contract_id=None):
    """Open the modal and its financial evidence for source-consumer assertions.

    Default collapsed-state checks use the modal tests directly. These callers
    inspect financial evidence, so they deliberately open that source section.
    """
    if page.locator('#contractDialog').evaluate('d=>d.open'):
        page.locator('#contractDialogClose').click()
    main = row(page, contract_id) if contract_id else page.locator('tr[data-contract-id]').first
    main.wait_for()
    main.locator('td.party').click()
    page.locator('#contractDialog').wait_for(state='visible')
    page.locator('#contractFinancialSources > summary').click()
    return page.locator('#contractsDetails')
