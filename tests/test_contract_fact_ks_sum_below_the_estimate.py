"""Сумма по КС ниже расчётной: факт по цене расчёта, а обе суммы и возможная причина видны в позиции.

Методика не меняется: деньги факта — объём КС, умноженный на цену действующего расчёта. Разница
с суммой акта не прячется: в графе «Стоимость» стоят обе суммы и пояснение полной фразой.
Данные выдуманы: репозиторий публичный.
"""
from __future__ import annotations

import pytest

import developaid_contract_fact as fact
from tests.test_contract_card_confirms_and_chooses_links import CONTRACT, ROW
from tests.test_contract_fact_prices_ks_by_the_edition import _item, card  # noqa: F401

# Стены приняты по КС на 1 000 ₽ при расчётных 4 000 ₽ за тот же объём.
BELOW = {**ROW, "physical_items": [_item("1.1", "Устройство стен", (0.5, 1000, "2026-02-01", "2026-02-03"))]}
WHY = "Сумма по КС меньше расчётной: возможно, работы приняты без материалов. В факт вошла сумма по расчёту."


@pytest.mark.parametrize("width", [390, 1440])
def test_a_ks_sum_below_the_estimate_shows_both_sums_and_why(card, width):  # noqa: F811
    from playwright.sync_api import expect

    from test_monitor_cumulative_controls import browser_page
    from tests.test_contract_card_confirms_and_chooses_links import _serve
    with browser_page(width) as (page, _, errors):
        _serve(page, [], cut="2026-02-04", acts=fact.acts(BELOW))
        page.locator("#contractsTab").click()
        page.locator(f'tr[data-contract-id="{CONTRACT}"] .contract-open').click()
        page.locator('#contractComparisonMethodology > details > summary').click()
        shown=page.locator('.contract-fact-audit')
        expect(page.locator('.contract-comparison-money')).to_contain_text('факт 4 000 ₽')
        expect(shown).to_contain_text('Сумма КС отличается от расчёта в периодах: 1.')
        shown.get_by_text('Позиции факта (1)').click()
        position=shown.locator('.contract-fact-source-positions li').first
        expect(position.locator('.contract-fact-both')).to_have_text('по расчёту 4 000 ₽ · по КС 1 000 ₽')
        expect(position.locator('.contract-fact-why')).to_have_text(WHY)
        if width==390:
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert errors == []
