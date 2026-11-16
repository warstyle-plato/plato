"""The actual Monitor presents canonical server rows, not another money formula."""
import pytest

from test_monitor_cumulative_controls import browser_page


def reconciliation():
    import developaid_funding_reconciliation as module
    own = {'paid': 400_000.0, 'left': 500_000.0, 'limit': 900_000.0,
           'rows': [{'chapter': '2', 'amount': 300_000.0}], 'model_over_schedule': 0.0, 'accounting': 0.0}
    comp = {'total': 1_200_000.0}
    return module, module.build(own, comp, {}, '2026-10-31')


@pytest.mark.parametrize('width', [390, 1440])
def test_real_page_uses_exact_canonical_rows_and_keeps_unknown_separate(width):
    from playwright.sync_api import expect
    module, r = reconciliation()
    r['calculated_additional'] = None
    r['paid_at_cut'] = 0.0
    r['reasons'] = ['АХР <img src=x onerror="window.unsafeFinancial=true"> требуют сверки']
    r['display_rows'] = module.display_rows(r)
    with browser_page(width) as (page, responses, errors):
        page.evaluate('''r=>{
          const funding={known:true,reconciliation:r,paid_actual:9000000,
             bank_remaining:8000000,additional_financing:0,reserve:0};
          currentView={dashboard:{funding,construction:{approved:9000000},sources:{}}};
          renderDash(currentView);selectMonitorTab('money');
        }''', r)
        expect(page.locator('#financeCard')).to_be_visible()
        values = page.locator('#kpis .kpi').evaluate_all(
            "rows=>Object.fromEntries(rows.map(x=>[x.querySelector('.l').textContent,x.querySelector('.n').textContent]))")
        assert values['Утверждённый бюджет'] == '1,2 млн ₽'
        assert values['Оплачено с начала проекта'] == '0 млн ₽'
        assert values['Доступный остаток лимита банка'] == '0,5 млн ₽'
        assert values['Расчётная дополнительная потребность'] == '—'
        assert 'Утверждённый РНВ' in values and 'Прогноз РНВ' in values
        assert 'Продажи' in values
        assert 'Дефицит · РСС' not in values
        expect(page.locator('.funding-reconciliation')).to_contain_text(
            'Финансовая сверка первичных источников не завершена')
        assert page.locator('#fundingCompare .batt').count() == 0
        assert page.locator('#financeBars').text_content() == ''
        assert page.locator('.funding-reconciliation img').count() == 0
        assert not page.evaluate('window.unsafeFinancial===true')
        assert page.locator('#kpis .good').count() == 0
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert not errors
        page.screenshot(path=f'/tmp/plato999-reconciliation-{width}.png', full_page=True)


def test_known_additional_value_is_not_recomputed_from_legacy_limits():
    _, r = reconciliation()
    with browser_page(390) as (page, responses, errors):
        result = page.evaluate('''r=>{
          const f={reconciliation:r,bank_remaining:7000000,additional_financing:0};
          return fundingStructure(f,true,9000000,8000000,1000000);
        }''', r)
        assert '0,3 млн ₽' in result
        assert '7 млн ₽' not in result
        assert 'хватает' not in result
        assert not errors


def test_work_month_detail_uses_the_server_rows_without_guessing_coverage():
    module, r = reconciliation()
    r['need_breakdown']['display_rows'] = [
        {'kind': 'admin', 'name': 'АХР', 'period': 'План финансовой базы',
         'source_plan': 40000., 'to_pay': None, 'covered': None, 'uncovered': None,
         'source': {'sheet': 'cf_1_new', 'row': 12}},
        {'kind': 'schedule_article', 'name': 'Фасады <img src=x onerror="window.xss=true">',
         'period': 'График', 'source_plan': 100000., 'to_pay': None,
         'covered': None, 'uncovered': None, 'source': {'sheet': 'ГФ', 'row': 15}}]
    with browser_page(390) as (page, responses, errors):
        page.evaluate('''r=>{
          currentView={dashboard:{funding:{known:true,reconciliation:r}}};
          renderDash(currentView);selectMonitorTab('money');
        }''', r)
        detail = page.locator('.funding-work-breakdown')
        detail.locator('summary').click()
        assert 'ещё не разобрано и не подтверждено' in detail.text_content()
        assert 'not_read_by_supported_parser' not in detail.text_content()
        rows = detail.locator('tbody tr').all_text_contents()
        assert len(rows) == 2
        assert all(row.count('—') == 3 for row in rows)
        assert 'строка 12' in rows[0] and 'строка 15' in rows[1]
        assert detail.locator('img').count() == 0
        assert not page.evaluate('window.xss===true')
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert not errors
