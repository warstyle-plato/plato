"""Native PAGE consumes qualified KS-6a zeros and preserves physical and cash evidence."""
import copy

import pytest
from playwright.sync_api import expect

from tests.test_contract_ks6_reporting_zero import statement_card
from tests.contract_rds_fixtures import CONTRACT, CUT
from tests.test_monitor_cumulative_controls import browser_page


def open_reporting(page, responses, cached):
    responses.data['rows'][0]['id'] = CONTRACT
    def documents(route):
        route.fulfill(json={**copy.deepcopy(cached), 'ticket': route.request.post_data_json['ticket']})
    page.route('**/monitor/contracts/documents', documents)
    page.locator('#cut').fill(CUT)
    page.locator('#contractsTab').click()
    page.locator(f'tr[data-contract-id="{CONTRACT}"] .contract-open').click()
    page.locator('#contractComparison[aria-busy="false"]').wait_for(state='attached')
    page.locator('#contractExecution > summary').click()


@pytest.mark.parametrize('width', [390, 1440])
@pytest.mark.parametrize('mode', ['cumulative', 'accounted_material_positive', 'independent_cash_zero'])
def test_native_ks6_zero_is_visible_with_its_canonical_basis_and_unchanged_physical_evidence(width, mode):
    cached, _ = statement_card(accounted=mode == 'accounted_material_positive', cash_zero=mode == 'independent_cash_zero')
    raw = copy.deepcopy(cached['rds_comparison']['rows'][0])
    with browser_page(width) as (page, responses, errors):
        open_reporting(page, responses, cached)
        shown = page.locator('#contractComparisonRows [data-rds-position="0:0"]')
        actual = shown.locator('[data-label="Факт по загруженным КС"]')
        expect(actual.locator('.contract-compare-number')).to_have_text('0 м3')
        expect(actual.locator('.contract-ks-reporting-basis')).to_have_text(raw['ks_reporting']['basis_note'])
        expect(actual).to_contain_text('не подтверждённый физический ноль')
        if mode == 'independent_cash_zero':
            expect(actual).to_contain_text('Стоимость работ и поставки: 0 ₽')
            expect(actual).to_contain_text('не выведен из объёма работ')
            expect(shown.locator('[data-label="Отклонение"]')).to_contain_text('-500 ₽')
        elif raw['fact'] is None:
            expect(actual).to_contain_text('Стоимость работ и поставки: Неизвестно')
        else:
            assert raw['fact'] >= 0
            expected = page.evaluate('(value)=>contractMoney(value)', raw['fact'])
            expect(actual).to_contain_text('Стоимость работ и поставки: ' + expected)
        if mode == 'accounted_material_positive':
            assert cached['fact']['statement_components']['cash']['source']['material'] == 100
        expect(shown.locator('[data-label="Прогноз окончания"]')).to_contain_text('нет подтверждённого темпа')
        assert raw['fact_quantity'] is None and raw['day_deviation'] is None and raw['forecast_finish'] is None
        projected = page.evaluate('(row)=>{const before=JSON.stringify(row),value=contractRdsReportingRow(row);return {unchanged:before===JSON.stringify(row),physical:row.fact_quantity,day:row.day_deviation,forecast:row.forecast_finish,fact:value.fact}}', raw)
        assert projected['unchanged'] is True and projected['physical'] is projected['day'] is projected['forecast'] is None
        assert projected['fact'] == (0 if mode == 'independent_cash_zero' else raw['fact'])
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        assert not errors


def test_ks6_projection_rejects_unqualified_quantity_and_never_masks_raw_positive_cash():
    cached, _ = statement_card(cash_zero=True)
    original = cached['rds_comparison']['rows'][0]
    rejected = []
    def invalid(change):
        row = copy.deepcopy(original)
        change(row)
        rejected.append(row)
    invalid(lambda r: r['ks_reporting'].update(schema='unknown'))
    invalid(lambda r: r['ks_reporting'].update(state='unreported_zero'))
    invalid(lambda r: r['ks_reporting'].update(basis='other_source'))
    invalid(lambda r: r['ks_reporting'].update(physical_quantity_confirmed=True))
    invalid(lambda r: r['ks_reporting'].pop('quantity_deviation'))
    invalid(lambda r: r['ks_reporting'].update(fact_quantity='0'))
    invalid(lambda r: r['ks_reporting'].update(fact_quantity_ratio=False))
    invalid(lambda r: r['ks_reporting'].update(quantity_deviation='unknown'))
    invalid(lambda r: r['ks_reporting'].update(sources=[]))
    invalid(lambda r: r['ks_reporting']['sources'][0].update(file_sha256='foreign'))
    invalid(lambda r: r['ks_reporting']['sources'][0].update(completed_quantity_cell='AV999'))
    invalid(lambda r: r['ks_reporting'].update(basis_note=''))
    invalid(lambda r: r.update(fact_quantity=3))
    quantity_only = []
    def no_cash(change):
        row = copy.deepcopy(original)
        change(row)
        quantity_only.append(row)
    no_cash(lambda r: r['ks_reporting'].pop('cash_zero'))
    no_cash(lambda r: r['ks_reporting']['cash_zero'].update(schema='unknown'))
    no_cash(lambda r: r['ks_reporting']['cash_zero'].update(amount=1))
    no_cash(lambda r: r['ks_reporting']['cash_zero'].update(basis='quantity_times_price'))
    no_cash(lambda r: r['ks_reporting']['cash_zero']['source'].update(file_sha256='e'*64))
    no_cash(lambda r: r['ks_reporting']['cash_zero']['source'].update(completed_amount_cell='AW999'))
    no_cash(lambda r: r['ks_reporting'].update(fact=False))
    no_cash(lambda r: r['ks_reporting'].update(deviation='unknown'))
    no_cash(lambda r: r['ks_reporting'].pop('deviation'))
    no_cash(lambda r: r.update(fact=29, deviation=-471))
    with browser_page(390) as (page, responses, errors):
        open_reporting(page, responses, cached)
        result = page.evaluate('''({rejected,quantityOnly})=>({
            rejected:rejected.map(row=>contractRdsReportingRow(row)===row),
            quantityOnly:quantityOnly.map(row=>{const before=JSON.stringify(row),value=contractRdsReportingRow(row);return {quantity:value.fact_quantity,ratio:value.fact_quantity_ratio,fact:value.fact,deviation:value.deviation,expectedFact:row.fact,expectedDeviation:row.deviation,note:value.ks_reporting_note,unchanged:before===JSON.stringify(row)}})
        })''', {'rejected': rejected, 'quantityOnly': quantity_only})
        assert all(result['rejected'])
        for value in result['quantityOnly']:
            assert value['quantity'] == value['ratio'] == 0
            assert value['fact'] == value['expectedFact'] and value['deviation'] == value['expectedDeviation']
            assert value['unchanged'] is True
            assert 'Полная стоимость работ и материалов' not in value['note']
        # Even a cash-zero claim in a malformed response cannot mask a known
        # positive row value on the actual rendered surface.
        page.evaluate('''row=>renderContractComparison({lines:[],cut:'2026-03-05'},null,null,{available:true,layout:'rds-plan-fact-v3',cut:'2026-03-05',rows:[row]})''', quantity_only[-1])
        actual = page.locator('#contractComparisonRows [data-label="Факт по загруженным КС"]')
        expect(actual).to_contain_text('Стоимость работ и поставки: 29 ₽')
        expect(actual).not_to_contain_text('Полная стоимость работ и материалов')
        assert not errors


def test_unknown_plan_stays_unknown_and_loaded_ks2_keeps_its_existing_strict_contract():
    cached, _ = statement_card()
    raw = copy.deepcopy(cached['rds_comparison']['rows'][0])
    raw['ks_reporting']['quantity_deviation'] = None
    raw['plan_quantity'] = None
    legacy = {'fact_quantity': None, 'fact_quantity_ratio': None, 'quantity_deviation': None,
              'fact': None, 'deviation': None, 'ks_reporting': {
                  'schema': 'rds-loaded-ks-reporting-v1', 'basis': 'loaded_ks2', 'state': 'unreported_zero',
                  'fact_quantity': 0, 'fact_quantity_ratio': 0, 'quantity_deviation': -1, 'fact': 0, 'deviation': -10}}
    incomplete = copy.deepcopy(legacy)
    incomplete['ks_reporting'].pop('fact')
    with browser_page(390) as (page, responses, errors):
        open_reporting(page, responses, cached)
        result = page.evaluate('''({raw,legacy,incomplete})=>({
            known:contractRdsReportingRow(raw),legacy:contractRdsReportingRow(legacy),incompleteRejected:contractRdsReportingRow(incomplete)===incomplete
        })''', {'raw': raw, 'legacy': legacy, 'incomplete': incomplete})
        assert result['known']['fact_quantity'] == 0 and result['known']['quantity_deviation'] is None
        assert result['legacy']['fact'] == 0 and result['legacy']['deviation'] == -10
        assert result['incompleteRejected'] is True
        assert not errors
