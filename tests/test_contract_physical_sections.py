"""Raw КС-6а volumes keep their source rows and explicit object sections."""
import copy
import pytest

import developaid_monitor_contracts as contracts


def physical_items():
    scopes=['Корпус 1 этаж 2-13','Корпус 2 этаж 1-3','Корпус 1 этаж 14-16',
            'Автостоянка','Корпуса 1-3','Общая работа']
    return [{'position':f'4.1.{i+1}','name':f'Учебная операция {i+1}','scope':scope,
             'unit':'м2','plan_quantity':100+i,'completed_quantity':20+i,'material_quantity':5+i,
             'completion_ratio':(20+i)/(100+i),'source':{'sheet':'Учебная КС-6а','row':10+i},
             'warnings':[]} for i,scope in enumerate(scopes)]


def test_shared_object_reader_adds_sections_without_touching_any_source_value():
    items=physical_items();before=copy.deepcopy(items)
    projected=contracts.physical_sections(items)
    assert [x['physical_section'] for x in projected]==[
        'Корпус 1','Корпус 2','Корпус 1','Автостоянка','','']
    assert [{k:v for k,v in x.items() if k!='physical_section'} for x in projected]==items==before
    # Unknown/ambiguous rows keep their own object state; there is no fill-forward.
    assert projected[-1]['physical_section']==''


@pytest.mark.parametrize('width',[390,1440])
def test_native_raw_volume_table_groups_and_filters_explicit_objects(width):
    from playwright.sync_api import expect
    from tests.test_monitor_cumulative_controls import browser_page,CONTRACT,KEY
    from tests.test_contract_comparison_export import native_card
    from tests.test_contract_comparison_export_ui import _browser_export
    items=contracts.physical_sections(physical_items())
    with browser_page(width) as (page,responses,errors):
        responses.data['rows'][0]['physical_items']=items
        _browser_export(page,native_card(),CONTRACT,KEY,[])
        page.locator('.contract-physical-open').click()
        headers=page.locator('#contractPhysicalRows .physical-section')
        expect(headers).to_have_text(['Корпус 1','Корпус 2','Автостоянка','Корпус или объект не определён'])
        rows=page.locator('#contractPhysicalRows [data-physical-index]')
        expect(rows).to_have_count(6)
        assert rows.evaluate_all('rs=>rs.map(r=>Number(r.dataset.physicalIndex))')==[0,2,1,3,4,5]
        expect(rows.nth(0)).to_contain_text('4.1.1')
        expect(rows.nth(0)).to_contain_text('100 м2')
        expect(page.locator('#contractPhysicalRows .physical-scope').first).to_have_text('Корпус 1 этаж 2-13')
        page.locator('#contractPhysicalSection').select_option('Корпус 2')
        expect(headers).to_have_text(['Корпус 2'])
        expect(rows).to_have_count(1)
        expect(rows).to_contain_text('101 м2')
        page.locator('#contractPhysicalSection').select_option('__unknown__')
        expect(rows).to_have_count(2)
        page.locator('#contractPhysicalSection').select_option('')
        page.locator('#contractPhysicalSearch').fill('4.1.3')
        expect(headers).to_have_text(['Корпус 1'])
        expect(rows).to_have_count(1)
        expect(rows).to_contain_text('102 м2')
        expect(rows.locator('details > summary')).to_have_text('Проверить данные')
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        assert not errors
