"""Material value and delivery cannot act as completed construction work."""
import pytest

import developaid_contract_control as control
import developaid_contract_plan as plan
import developaid_contract_comparison as comparison
import developaid_contract_fact as fact
from tests.test_contract_known_schedule_dates_without_fact import source_card  # noqa: F401


def work(code, labour, material, **extra):
    return {'code': code, 'name': 'Учебная работа '+code, 'start': '2026-03-01',
            'finish': '2026-03-10', 'amount': labour+material, 'planned': labour+material,
            'work_amount': labour, 'material_amount': material,
            'volume': {'unit': 'м2', 'quantity': 10}, **extra}


def calculate(lines, actual):
    current = {'in_force': True, 'start': None, 'lines': lines,
               'total': sum(r['amount'] for r in lines), 'planned': sum(r['planned'] for r in lines)}
    return control.build({'editions': [current]}, {'lines': actual, 'note': ''}, None, '', '2026-03-10')


def test_work_and_material_costs_weight_readiness_while_total_money_stays_unchanged():
    rows = [work('1', 100, 900), work('2', 900, 100)]
    actual = [{'code': '1', 'fact': 1000, 'work_fact': 100, 'material_fact': 900,
               'volumes': [{'unit': 'м2', 'quantity': 10}], 'last': '2026-03-10', 'complete': False}]
    got = calculate(rows, actual)
    assert got['total']['readiness'] == pytest.approx(0.5)
    assert got['components']['work']['readiness'] == pytest.approx(0.1)
    assert got['components']['material']['readiness'] == pytest.approx(0.9)
    assert got['total']['work_amount'] == 1000
    assert (got['total']['amount'], got['total']['fact']) == (2000, 1000)


def test_delivery_only_has_no_weight_or_volume_in_work_readiness():
    rows = [work('1', 0, 1000, supply_only=True), work('2', 900, 100)]
    actual = [{'code': '1', 'fact': 1000, 'work_fact': 0, 'material_fact': 1000,
               'volumes': [], 'last': None, 'complete': False}]
    got = calculate(rows, actual)
    assert got['total']['readiness'] == 0.5 and not got['forecast']['done']
    assert got['components']['work']['readiness'] == 0
    assert [r['code'] for r in got['lines']] == ['2']
    assert got['total']['fact'] == 1000


def test_an_unknown_work_material_split_is_not_an_invented_weight():
    row = work('1', 100, 900)
    row['work_amount'] = None
    got = calculate([row], [])
    assert got['total'] is None and got['forecast'] is None
    assert 'не отделены от материалов' in got['note']


def test_monetary_comparison_and_export_projection_exclude_materials_from_work_fact():
    row = work('1', 100, 900, volume=None)
    actual = [{'code': '1', 'fact': 950, 'work_fact': 50, 'material_fact': 900,
               'volumes': [], 'last': '2026-03-05', 'complete': False}]
    got = calculate([row], actual)
    projected = comparison._row(got['lines'][0], None)
    assert (projected['planned'], projected['fact'], projected['deviation']) == (100, 50, -50)
    assert projected['readiness'] == 0.5 and 'без материалов' in projected['money_fallback']
    assert got['total']['amount'] == 1000 and got['total']['fact'] == 950


def test_material_only_gpr_line_is_not_added_back_as_an_unknown_work():
    lines = [work('1', 0, 1000, supply_only=True), work('2', 900, 100)]
    got = calculate(lines, [])
    current = {'in_force': True, 'lines': lines, 'schedule_sha256': 'a'*64}
    document = {'sha256': 'a'*64, 'title': 'Учебный график', 'schedule': {'lines': lines}}
    view = comparison.build({'control': got, 'plan': {'editions': [current]}, 'fact': {},
                             'documents': [document]}, '2026-03-10')
    assert [r['code'] for r in view['lines']] == ['2', '1', '2::material']
    assert view['lines'][1]['component'] == 'material'
    assert view['coverage']['source_works'] == 2 and view['coverage']['unknown'] == 0


def test_material_statement_uses_material_columns_without_adding_them_to_work_fact():
    found = {'acts': [{'number': '1', 'name': 'Стена', 'unit': 'м2', 'quantity': 20,
                       'quantity_material': 5, 'amount_components': {'work': 200, 'material': 500},
                       'end': '2026-03-01', 'label': 'КС-2 № 1', 'source': {'row': 31, 'sheet': 'КС-6а'}}]}
    statement = fact.statement_materials(found, '2026-03-10')
    assert statement['source'] == 'ks6a' and statement['unknown_count'] == 0
    assert (statement['rows'][0]['quantity'], statement['rows'][0]['amount']) == (5, 500)
    source=statement['rows'][0]['source']
    assert (source['row'],source['sheet']) == (31,'КС-6а')
    assert source['quantity_cell'] is None and source['amount_cell'] is None
    assert source['coordinate_note']
    assert fact.statement_materials(found, '2026-02-28')['rows'] == []


def test_plan_keeps_both_costs_and_removes_material_only_quantity_from_work_volume():
    positions = [{'key': 'installation', 'unit': 'м2', 'quantity': 10, 'amount': 1000,
                  'work_amount': 100, 'material_amount': 900, 'status': 'confirmed',
                  'lines': [{'code': '1', 'share': 1}]},
                 {'key': 'delivery', 'unit': 'м2', 'quantity': 50, 'amount': 500,
                  'work_amount': 0, 'material_amount': 500, 'status': 'confirmed',
                  'lines': [{'code': '1', 'share': 1}]}]
    schedule = {'lines': [{'code': '1', 'parent': None, 'name': 'Стена', 'start': '2026-03-01',
                           'finish': '2026-03-10'}]}
    got = plan.edition([{'scope': 'full', 'links': {'positions': positions}}], schedule, None)['lines'][0]
    assert got['amount'] == 1500 and got['work_amount'] == 100 and got['material_amount'] == 1400
    assert got['volume'] == {'unit': 'м2', 'quantity': 10}
    assert got['material_volume'] == {'unit': 'м2', 'quantity': 60}


@pytest.mark.parametrize('width', [390, 1440])
def test_materials_are_visible_separately_with_their_own_quantity_and_cost(source_card, width):  # noqa: F811
    from playwright.sync_api import expect
    from tests.test_contract_card_shows_its_documents import _serve
    from tests.test_contract_material_fact import accumulated, act_position, build
    from tests.test_monitor_cumulative_controls import CONTRACT, browser_page

    source_card['fact'] = build(accumulated(act_position(work=20, material=5)))
    with browser_page(width) as (page, _, errors):
        _serve(page, source_card, [])
        page.locator('#contractsTab').click()
        page.locator(f'tr[data-contract-id="{CONTRACT}"] .contract-open').click()
        page.locator('#contractExecution > summary').click()
        materials = page.locator('#contractMaterials')
        expect(materials).to_contain_text('Материалы по КС-6а — отдельно от выполнения работ')
        materials.locator('summary').click()
        expect(materials.locator('tbody tr')).to_have_count(1)
        expect(materials.locator('tbody td').nth(2)).to_have_text('5')
        expect(materials.locator('tbody td').nth(3)).to_have_text('500 ₽')
        assert not errors and page.evaluate('document.documentElement.scrollWidth<=innerWidth')
