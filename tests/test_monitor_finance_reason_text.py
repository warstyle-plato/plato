"""Financial reason/availability labels are plain text at every KPI sink."""
import pytest
from playwright.sync_api import expect

import developaid_admin_expenses as admin
from test_monitor_cumulative_controls import browser_page


MARKER = 'A & B <svg onload="window.financeReasonExecuted=true"></svg>'


@pytest.mark.parametrize('width', [390, 1440])
@pytest.mark.parametrize('field', ['reason', 'availability'])
def test_financial_fallback_labels_are_literal_text_without_markup(width, field):
    projection = {
        'source': {'sha256': 'a' * 64, 'version_date': None},
        'unit_evidence': {'state': 'observed', 'recognized_unit': 'руб.'},
        'rows': [{'code': '2.4.1', 'row': 14, 'cells': {
            key: {'cell': cell, 'cached_value': value}
            for key, cell, value in [('total', 'I14', 40), ('fact', 'J14', 20),
                                     ('plan', 'K14', 20)]}}],
    }
    model = admin._projection_model(projection, '2026-11-13')
    model['availability_note'] = MARKER if field == 'availability' else 'A & B'
    funding = {'known': False, 'reason': MARKER if field == 'reason' else ''}
    view = {'admin_expenses': model, 'admin_expenses_html': admin.render(model),
            'dashboard': {'funding': funding, 'construction': {}}}
    with browser_page(width) as (page, responses, errors):
        page.evaluate('v=>{currentView=v;renderDash(v);selectMonitorTab("money")}', view)
        kpis = page.locator('#kpis')
        assert kpis.locator('svg, img').count() == 0
        expect(kpis).to_contain_text(MARKER)
        assert page.evaluate('window.financeReasonExecuted || false') is False
        # The composed view preserves the actual reason before availability;
        # both cases retain MARKER literally, without HTML-encoding textContent.
        expect(page.locator('#financeBars')).to_have_text(MARKER)
        assert page.locator('#financeBars svg, #financeBars img').count() == 0
        card = page.locator('#adminExpensesCard')
        expect(card).to_be_visible()
        assert card.locator('.admin-expenses > div > div').count() == 3
        assert not errors
