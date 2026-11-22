"""A long physical source work keeps six readable fields in the native modal."""
import pytest
from playwright.sync_api import expect
from tests.test_contract_card_execution_visible import execution_page,no_plan
from tests.test_monitor_cumulative_controls import register

@pytest.mark.parametrize('width',[390,1440])
def test_long_physical_work_keeps_readable_field_width_and_every_value(no_plan,width):
    row=register()['rows'][0]
    item=row['physical_items'][0]
    item.update(name='Устройство кладки марки С-5 толщиной 190 мм из пустотелых блоков ' * 5,
                unit='м³',plan_quantity=134.47,completed_quantity=0,material_quantity=None,
                completion_ratio=0,quantity_date=None)
    row['physical_items']=[item]
    with execution_page(width,row,no_plan)as(page,_,errors):
        page.locator('.contract-physical-open').click()
        source=page.locator('#contractPhysicalSources')
        fields=source.locator('tr.physical-main>td')
        expect(fields).to_have_count(6)
        for field in fields.all():expect(field).to_be_visible()
        expect(fields.nth(0)).to_contain_text(item['name'])
        expect(fields.nth(1)).to_have_text('134,47 м³')
        expect(fields.nth(2)).to_have_text('0 м³')
        expect(fields.nth(3)).to_have_text('—')
        expect(fields.nth(4)).to_have_text('0%')
        box=fields.first.bounding_box()
        assert box['width']>= (280 if width==390 else 140)
        assert box['height']<700
        if width==390:
            for field in fields.all():
                assert field.evaluate('(e)=>getComputedStyle(e,"::before").content')=='"'+field.get_attribute('data-label')+'"'
            assert fields.first.evaluate('(e)=>parseFloat(getComputedStyle(e).fontSize)')>=13
        assert source.evaluate('(e)=>e.scrollWidth<=e.clientWidth+1')
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        assert not errors
