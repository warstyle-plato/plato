"""Строка таблицы «Договоры» и её раскрытая часть на отрисованной странице.

Строка реестра короткая; подробности договора открываются щелчком по строке. Тест, которому нужны
подробности, раскрывает строку так же, как посетитель, и читает раскрытую часть.
"""
from __future__ import annotations


def row(page, contract_id):
    return page.locator(f'tr[data-contract-id="{contract_id}"]')


def named(page, text):
    """Строка договора с текстом `text` и её раскрытые подробности."""
    main = page.locator('tr[data-contract-id]', has_text=text)
    main.wait_for()
    return main, opened(page, main.get_attribute('data-contract-id'))


def opened(page, contract_id=None):
    """Раскрыть строку договора (без `contract_id` — первую) и вернуть её подробности."""
    main = row(page, contract_id) if contract_id else page.locator('tr[data-contract-id]').first
    main.wait_for()
    toggle = main.locator('.contract-more-toggle')
    if toggle.get_attribute('aria-expanded') != 'true':
        main.locator('td.party').click()
    found = main.get_attribute('data-contract-id')
    more = page.locator(f'tr[data-contract-detail="{found}"]')
    more.wait_for(state='visible')
    return more
