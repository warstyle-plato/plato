"""Actual native Monitor DOM with synthetic source-bound component reconciliation."""
import pytest
from tests.test_contract_material_source_components import case,calculate
from tests.test_contract_known_schedule_dates_without_fact import source_card  # noqa:F401


@pytest.mark.parametrize('width',[390,1440])
def test_native_card_and_register_show_cash_separate_from_current_and_historical_basis(source_card,width):
    from playwright.sync_api import expect
    from tests.test_monitor_cumulative_controls import browser_page,CONTRACT
    from tests.test_contract_card_shows_its_documents import _serve
    edition,row=case();actual,measured=calculate(edition,row)
    source_card.update(control=measured,fact=actual)
    with browser_page(width) as (page,responses,errors):
        responses.data['rows'][0]['schedule_control']={'statement_summary':measured['statement_summary']}
        _serve(page,source_card,[])
        page.locator('#contractsTab').click()
        register=page.locator('#contractsRows .contract-statement-reconciliation')
        expect(register).to_contain_text('Всего по исходной ведомости: 300 ₽')
        page.locator(f'tr[data-contract-id="{CONTRACT}"] .contract-open').click()
        detail=page.locator('#contractCardSummary .contract-statement-reconciliation')
        expect(detail).to_contain_text('материалы: 300 ₽')
        detail.locator('summary').click()
        expect(detail).to_contain_text('Взвешенный вклад текущей РДС: 300 ₽')
        expect(detail).to_contain_text('Денежное закрытие по КС — не оплата')
        expect(detail).to_contain_text('Поставка материала — не выполненный объём монтажа')
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth') and not errors
