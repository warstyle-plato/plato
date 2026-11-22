"""Калькулятор по основаниям в настоящей странице, сохранение и очереди."""
import pytest
from tests.test_mo_vri_full_page import served, full_page  # noqa: F401


@pytest.mark.parametrize('width', [390, 1440])
def test_calculated_investment_benefit_is_applied_saved_and_not_doubled_by_queues(served, width):
    from playwright.sync_api import expect
    with full_page(served, width) as (page, requests, accesses):
        page.locator('#moVriBenefitMode').select_option('calculated')
        page.locator('#moVriGross').fill('2000')
        page.locator('#moVriBenefitKind').select_option('investment')
        page.get_by_role('button', name='Добавить обязательство', exact=True).click()
        page.get_by_label('Инвестиционный объект', exact=True).select_option('hotel_4')
        page.get_by_label('Общая площадь инвестиционного объекта, м²', exact=True).fill('10000')
        expect(page.locator('#moVriBenefitRows')).to_contain_text('180')
        page.locator('#moVriPreviewButton').click()
        expect(page.locator('#moVriApplyButton')).to_be_enabled()
        expect(page.locator('#moVriBenefitBreakdown')).to_contain_text('Гостиница 4★')
        expect(page.locator('#moVriBenefitBreakdown')).to_contain_text('933-ПП')
        expect(page.locator('#moVriBenefitBreakdown')).to_contain_text('1\u00a0800\u00a0000\u00a0000')
        page.locator('#moVriApplyButton').click()
        page.wait_for_function('calcIdle()')
        state = page.evaluate('''()=>({fee:inputs.land_rights_cost_mln,
            configuration:inputs.mo_vri_benefits,phases:phasing,
            net:phaseBundle?.consolidated?.vri?.totals?.principal,
            overflow:document.documentElement.scrollWidth>innerWidth+1})''')
        assert state['fee'] == 200
        assert state['configuration']['rows'][0]['object_type'] == 'hotel_4'
        assert state['configuration']['result']['total_rub'] == 1_800_000_000
        assert not state['overflow']
        # Настоящее восстановление снимка; ставки и состав не становятся ручной суммой.
        page.evaluate('''()=>{const snapshot=JSON.parse(JSON.stringify({inputs,tep,phasing,scenario:'base'}));
            applyProjectSnapshot(snapshot);openTab('vri')}''')
        expect(page.locator('#moVriBenefitMode')).to_have_value('calculated')
        expect(page.get_by_label('Общая площадь инвестиционного объекта, м²', exact=True)).to_have_value('10000')
        expect(page.locator('#moVriBenefitBreakdown')).to_contain_text('Гостиница 4★')
        assert '/mo/vri-compensation' in requests


def test_unfinished_row_and_a_changed_area_cannot_apply_a_stale_estimate(served):
    from playwright.sync_api import expect
    with full_page(served, 1440) as (page, requests, accesses):
        page.locator('#moVriBenefitMode').select_option('calculated')
        page.locator('#moVriGross').fill('2000')
        page.locator('#moVriBenefitKind').select_option('investment')
        page.get_by_role('button', name='Добавить обязательство', exact=True).click()
        page.locator('#moVriPreviewButton').click()
        expect(page.locator('#moVriBenefitBreakdown')).to_contain_text('нужны данные')
        expect(page.locator('#moVriApplyButton')).to_be_disabled()
        page.get_by_label('Общая площадь инвестиционного объекта, м²', exact=True).fill('1000')
        page.locator('#moVriPreviewButton').click()
        expect(page.locator('#moVriApplyButton')).to_be_enabled()
        page.get_by_label('Общая площадь инвестиционного объекта, м²', exact=True).fill('2000')
        expect(page.locator('#moVriApplyButton')).to_be_disabled()
        expect(page.locator('#moVriBenefitBreakdown')).to_be_empty()
        assert page.evaluate('inputs.land_rights_cost_mln') == 1000


def test_project_budget_edits_keep_the_ncs_fee_in_both_model_and_form(served):
    from playwright.sync_api import expect
    with full_page(served, 1440) as (page, requests, accesses):
        page.evaluate('''()=>{inputs.school_cost_mln_per_place=3;renderInputs()}''')
        page.locator('#moVriBenefitMode').select_option('calculated')
        page.locator('#moVriGross').fill('500')
        page.locator('#moVriBenefitKind').select_option('school')
        page.get_by_role('button', name='Добавить обязательство', exact=True).click()
        page.get_by_label('Нормативная потребность, мест', exact=True).fill('100')
        page.get_by_label('Проектная мощность, мест', exact=True).fill('125')
        page.get_by_label('Тип объекта по НЦС', exact=True).select_option('03-03-001')
        page.locator('#moVriPreviewButton').click()
        expect(page.locator('#moVriApplyButton')).to_be_enabled()
        page.locator('#moVriApplyButton').click()
        page.wait_for_function('calcIdle()')
        assert page.evaluate('inputs.land_rights_cost_mln') == 461.648
        page.evaluate('''async()=>{document.getElementById('f_school_cost_mln_per_place').value='4';await settledCalculate()}''')
        assert page.evaluate('inputs.land_rights_cost_mln') == 461.648
        expect(page.locator('#f_land_rights_cost_mln')).to_have_value('461.648')
        page.evaluate('async()=>{await settledCalculate()}')
        assert page.evaluate('inputs.land_rights_cost_mln') == 461.648


def test_project_cost_edit_keeps_the_ncs_preview_and_hidden_manual_input_is_ignored(served):
    from playwright.sync_api import expect
    with full_page(served, 1440) as (page, requests, accesses):
        page.locator('#moCompensation').fill('-1')
        page.locator('#moVriBenefitMode').select_option('calculated')
        page.locator('#moVriGross').fill('500')
        page.locator('#moVriBenefitKind').select_option('school')
        page.get_by_role('button', name='Добавить обязательство', exact=True).click()
        page.get_by_label('Нормативная потребность, мест', exact=True).fill('100')
        page.get_by_label('Проектная мощность, мест', exact=True).fill('125')
        page.get_by_label('Тип объекта по НЦС', exact=True).select_option('03-03-001')
        page.locator('#moVriPreviewButton').click()
        expect(page.locator('#moVriApplyButton')).to_be_enabled()
        page.evaluate('()=>{inputs.school_cost_mln_per_place=4;renderMoVriRelief()}')
        expect(page.locator('#moVriApplyButton')).to_be_enabled()
        assert page.evaluate('inputs.land_rights_cost_mln') == 1000


@pytest.mark.parametrize('width', [390, 1440])
def test_ncs_source_selection_and_saved_calculation_are_visible(served, width):
    from playwright.sync_api import expect
    with full_page(served, width) as (page, _, _):
        page.locator('#moVriBenefitMode').select_option('calculated')
        page.locator('#moVriGross').fill('500')
        page.locator('#moVriBenefitKind').select_option('kindergarten')
        page.get_by_role('button', name='Добавить обязательство', exact=True).click()
        page.get_by_label('Нормативная потребность, мест', exact=True).fill('200')
        page.get_by_label('Проектная мощность, мест', exact=True).fill('250')
        page.locator('#moVriPreviewButton').click()
        expect(page.locator('#moVriApplyButton')).to_be_disabled()
        page.get_by_label('Тип объекта по НЦС', exact=True).select_option('03-01-001')
        page.locator('#moVriPreviewButton').click()
        expect(page.locator('#moVriApplyButton')).to_be_enabled()
        expect(page.locator('#moVriBenefitBreakdown')).to_contain_text('НЦС 81-02-03-2026')
        expect(page.locator('#moVriBenefitBreakdown')).to_contain_text('без НДС')
        expect(page.get_by_role('link', name='НЦС-2026 — скан сборника')).to_have_attribute(
            'href', 'https://k-css.ru/f/19032026_167_pr_sbornik_3.pdf')
        page.locator('#moVriApplyButton').click()
        page.wait_for_function('calcIdle()')
        assert page.evaluate('inputs.mo_vri_benefits.result.total_rub') == 68_220_000
        page.evaluate('''()=>{const snapshot=JSON.parse(JSON.stringify({inputs,tep,phasing,scenario:'base'}));
            applyProjectSnapshot(snapshot);openTab('vri')}''')
        expect(page.get_by_label('Тип объекта по НЦС', exact=True)).to_have_value('03-01-001')
        expect(page.locator('#moVriBenefitBreakdown')).to_contain_text('03-01-001')
        assert not page.evaluate('document.documentElement.scrollWidth>innerWidth+1')
        bounds = page.locator('#moVriBenefitBreakdown tbody td:last-child').evaluate(
            '(node)=>{const r=node.getBoundingClientRect();return {left:r.left,right:r.right,width:innerWidth}}')
        assert bounds['left'] >= 0 and bounds['right'] <= bounds['width']
        assert 'ставка бюджета проекта' not in page.locator('#moVriReliefPanel').inner_text()
