"""Synthetic territory boundaries: applied MO relief cannot follow a new region/site."""
from copy import deepcopy
import io

import pytest
from openpyxl import load_workbook
from xlsx_eval import Evaluator

from tests.test_mo_vri_full_page import served, full_page, KEY
from tests.test_mo_vri_panel import money, stand  # noqa: F401
from tests.test_vri_phase_offset_once import core, project, phasing


def applied():
    cfg = {'schema': 1, 'rows': [
        {'id': 'hotel', 'kind': 'investment', 'object_type': 'hotel_4',
         'area_sqm': 1000, 'index_mode': 'base'}],
        'applied': {'gross_rub': 500e6, 'net_mln': 320}}
    x, t = project(land_rights_cost_mln=320, mo_vri_benefits=cfg, vri_relief_mode='off')
    core.apply_mo_vri_benefits(x, t)
    x['_field_origin'] = {
        'inputs.land_rights_cost_mln': {'source': 'mo_vri_compensation'},
        'inputs.mo_vri_compensation_mln': {'source': 'mo_vri_compensation'}}
    return x, t


def assert_detached(x, fee=500):
    assert x['land_rights_cost_mln'] == fee
    assert not x.get('_mo_vri_relief')
    assert not (x.get('mo_vri_benefits') or {}).get('applied')
    assert not (x.get('mo_vri_benefits') or {}).get('result')
    assert not x.get('mo_vri_compensation_mln')
    assert all(v.get('source') != 'mo_vri_compensation' for v in x.get('_field_origin', {}).values())
    assert x['vri_transfer_offset_mln'] == 30


@pytest.mark.parametrize('region', ['msk', 'other', 'unknown'])
@pytest.mark.parametrize('evidence', ['both', 'proof', 'configuration'])
def test_legacy_payload_normalizes_only_proven_applied_mo_amount(region, evidence):
    x, t = applied()
    x['vri_region'] = region
    if evidence == 'proof':
        del x['mo_vri_benefits']
    if evidence == 'configuration':
        del x['_mo_vri_relief']
    before_tep = deepcopy(t)
    update = core.apply_mo_vri_benefits(x, t)
    assert_detached(x)
    assert update['inputs']['land_rights_cost_mln'] == 500
    assert core.apply_mo_vri_benefits(x, t) == {}
    assert t == before_tep


@pytest.mark.parametrize('fee', [654, 320])
def test_explicit_manual_fee_survives_even_if_it_equals_the_previous_net(fee):
    x, t = applied()
    x.update(vri_region='msk', land_rights_cost_mln=fee)
    x['_field_origin']['inputs.land_rights_cost_mln'] = {'source': 'manual'}
    core.apply_mo_vri_benefits(x, t)
    assert_detached(x, fee)
    x['vri_region'] = 'mo'
    assert core.apply_mo_vri_benefits(x, t) == {}
    assert x['land_rights_cost_mln'] == fee
    assert x['_field_origin']['inputs.land_rights_cost_mln']['source'] == 'manual'


def test_plain_numbers_and_missing_fields_are_not_proof_and_do_not_become_zero():
    for x in ({'vri_region': 'msk', 'land_rights_cost_mln': 320},
              {'vri_region': 'msk', 'mo_vri_benefits': {'schema': 1, 'rows': []}},
              {'vri_region': 'msk', 'mo_vri_compensation_mln': 99,
               '_field_origin': {'inputs.mo_vri_compensation_mln': {'source': 'manual'}}}):
        before = deepcopy(x)
        assert core.normalize_mo_vri_region(x) == {}
        assert x == before


def test_normalizing_a_snapshot_does_not_modify_its_reusable_source(money):
    shown, _, _ = stand(money, '''const saved={inputs:{...inputs,vri_region:'msk',
      land_rights_cost_mln:90,mo_vri_compensation_mln:10,
      mo_vri_benefits:{schema:1,rows:[],applied:{gross_rub:100e6,net_mln:90}},
      _mo_vri_relief:{schema:1,vri:ANSWER.vri,source:{kind:'manual'}}}};
      const before=JSON.stringify(saved);applyProjectSnapshot(saved);
      console.log(JSON.stringify({unchanged:before===JSON.stringify(saved),
        fee:inputs.land_rights_cost_mln,applied:inputs.mo_vri_benefits.applied||null}));''')
    assert shown == {'unchanged': True, 'fee': 100, 'applied': None}


def test_legacy_snapshot_save_native_queues_and_evaluated_book_share_restored_base():
    x, t = applied()
    x['vri_region'] = 'msk'
    raw = deepcopy(x)
    native = core.calculate(core.CalcRequest(inputs=deepcopy(x), tep=deepcopy(t), rates=[]))
    bundle = core.calculate_phased(core.PhasedCalcRequest(
        inputs=deepcopy(x), tep=deepcopy(t), rates=[], phasing=phasing([40, 60])))
    assert native['vri']['totals']['principal'] == 470e6
    assert bundle['consolidated']['vri']['totals']['principal'] == 470e6
    assert sum(p['result']['vri']['totals']['principal'] for p in bundle['phases']) == 470e6
    content, _, meta = core.build_project_workbook(x, t, [], phasing([40, 60]),
        cache_values=False, project_name='Синтетическая граница региона')
    assert not meta['missing']
    book = load_workbook(io.BytesIO(content))
    evaluator = Evaluator(book)
    principals = [float(evaluator.cell('ВРИ', f'B{core._V4_VRI_PRINCIPAL_ROW + core._V4_VRI_BLOCK_STRIDE*i}'))*1e6
                  for i in range(2)]
    assert sum(principals) == pytest.approx(470e6, abs=.51, rel=0)
    assert [r[1] for r in book['Вводные'].iter_rows(values_only=True)
            if str(r[0] or '').startswith('Плата за изменение ВРИ')] == [500]
    assert 'Гостиница 4' not in str(book['Источники']['I7'].value)
    core.project_save(119600011, 'Синтетический снимок', {'inputs': x, 'tep': t}, project_id='1196ee11aa22')
    saved = core.project_open(119600011, '1196ee11aa22')['payload']['inputs']
    assert_detached(saved)
    assert x == raw  # export/save do not mutate the caller's saved snapshot


def add_hotel(page):
    page.locator('#f_vri_relief_mode').select_option('off')
    page.wait_for_function('calcIdle()')
    page.locator('#moVriBenefitMode').select_option('calculated')
    page.locator('#moVriGross').fill('500')
    page.locator('#moVriBenefitKind').select_option('investment')
    page.get_by_role('button', name='Добавить обязательство', exact=True).click()
    page.get_by_label('Инвестиционный объект', exact=True).select_option('hotel_4')
    page.get_by_label('Общая площадь инвестиционного объекта, м²', exact=True).fill('1000')


def apply_preview(page):
    from playwright.sync_api import expect
    page.locator('#moVriPreviewButton').click()
    expect(page.locator('#moVriApplyButton')).to_be_enabled()
    page.locator('#moVriApplyButton').click()
    page.wait_for_function('calcIdle()')


def hold_preview(page):
    page.evaluate('''()=>{window.boundaryFetch=fetch.bind(window);window.fetch=async(...args)=>{
      const response=await boundaryFetch(...args);if(args[0]==='/mo/vri-compensation')
      await new Promise(resolve=>{window.boundaryRelease=resolve});return response};
      window.boundaryPending=previewMoVriRelief();return true}''')
    page.wait_for_function('typeof window.boundaryRelease==="function"')


def release_preview(page):
    page.evaluate('window.boundaryRelease()')
    page.evaluate('async()=>await window.boundaryPending')
    page.evaluate('applyMoVriRelief()')
    page.evaluate('window.fetch=window.boundaryFetch')


@pytest.mark.parametrize('width', [390, 1440])
def test_page_region_boundary_late_preview_manual_override_and_explicit_reapply(served, width):
    from playwright.sync_api import expect
    with full_page(served, width) as (page, _, __):
        add_hotel(page)
        apply_preview(page)
        assert page.evaluate('inputs.land_rights_cost_mln') == 320
        assert page.evaluate('!!inputs._mo_calc||!!inputs._glavapu_import') is False
        hold_preview(page)
        page.locator('#f_vri_region').select_option('msk')
        page.wait_for_function('calcIdle()')
        before = page.evaluate('JSON.stringify(projectStorePayload().payload)')
        release_preview(page)
        assert page.evaluate('JSON.stringify(projectStorePayload().payload)') == before
        snapshot = page.evaluate('projectStorePayload().payload')
        assert_detached(snapshot['inputs'])
        assert snapshot['tep']['apartments']['transfer'] == 2000
        assert page.evaluate('phaseBundle.consolidated.vri.totals.principal') == 470e6
        expect(page.locator('#moVriReliefPanel')).to_be_hidden()
        response = page.request.post(served[0]+'/report/workbook', data={**snapshot,
            'rates': [], 'access_key': KEY, 'project_name': 'Синтетическая смена региона'}, timeout=120000)
        assert response.status == 200
        book = load_workbook(io.BytesIO(response.body()))
        ev = Evaluator(book)
        assert sum(float(ev.cell('ВРИ', f'B{core._V4_VRI_PRINCIPAL_ROW+core._V4_VRI_BLOCK_STRIDE*i}'))*1e6
                   for i in range(2)) == pytest.approx(470e6, abs=.51, rel=0)
        page.locator('#f_vri_region').select_option('mo')
        page.wait_for_function('calcIdle()')
        assert page.evaluate('inputs.land_rights_cost_mln') == 500
        expect(page.locator('#moVriGross')).to_have_value('500')
        apply_preview(page)  # returning to MO does not apply; a fresh explicit apply does
        assert page.evaluate('inputs.land_rights_cost_mln') == 320
        # Cancel the applied deduction using the existing manual mode and an empty amount.
        page.locator('#moVriBenefitMode').select_option('manual')
        page.locator('#moCompensation').fill('')
        apply_preview(page)
        assert page.evaluate('inputs.land_rights_cost_mln') == 500
        assert page.evaluate('inputs.mo_vri_benefits||null') is None
        add_hotel(page)
        apply_preview(page)
        assert page.evaluate('inputs.land_rights_cost_mln') == 320
        page.evaluate('focusVriFeeField()')
        page.locator('#f_land_rights_cost_mln').fill('654')
        page.locator('#f_land_rights_cost_mln').press('Tab')
        page.wait_for_function('calcIdle()')
        page.evaluate("openTab('vri')")
        for region in ('msk', 'mo'):
            page.locator('#f_vri_region').select_option(region)
            page.wait_for_function('calcIdle()')
            assert page.evaluate('inputs.land_rights_cost_mln') == 654
            assert page.evaluate('phaseBundle.consolidated.vri.totals.principal') == 624e6
        assert not page.evaluate('document.documentElement.scrollWidth>innerWidth+1')


NEW_TERRITORY = '''async()=>{moResult={query:'Синтетический новый участок',
  inputs:{vri_region:'mo',land_rights_cost_mln:777,mo_vri_compensation_mln:0},
  territory:{district:'Синтетический округ',site_area_ha:1},tep:JSON.parse(JSON.stringify(TEP_DEFAULT)),
  vri:{payment_before_compensation_rub:777e6,payment_used_rub:777e6,payment_used_mln:777,
       compensation_rub:null},warnings:[]};await applyMo();openTab('vri')}'''


@pytest.mark.parametrize('width', [390, 1440])
def test_page_new_territory_with_same_uid_drops_old_draft_and_late_preview(served, width):
    from playwright.sync_api import expect
    with full_page(served, width) as (page, _, __):
        add_hotel(page)
        apply_preview(page)
        uid = page.evaluate('inputs._project_uid')
        page.locator('#moVriBenefitMode').select_option('manual')
        page.locator('#moCompensation').fill('99')
        hold_preview(page)
        page.evaluate(NEW_TERRITORY)
        assert page.evaluate('inputs._project_uid') == uid
        expect(page.locator('#moVriBenefitRows')).to_be_empty()
        expect(page.locator('#moCompensation')).to_have_value('')
        expect(page.locator('#moVriGross')).to_have_value('777')
        assert page.evaluate('moVriBenefitsDraft') == []
        assert page.evaluate('inputs.mo_vri_benefits||null') is None
        before = page.evaluate('JSON.stringify(projectStorePayload().payload)')
        release_preview(page)
        assert page.evaluate('JSON.stringify(projectStorePayload().payload)') == before
        page.evaluate('async()=>await previewMoVriRelief()')
        assert page.evaluate('moVriReliefPreview?.vri?.compensation_rub??null') in (None, 0)
        assert page.evaluate('inputs.land_rights_cost_mln') == 777
        assert not page.evaluate('document.documentElement.scrollWidth>innerWidth+1')


@pytest.mark.parametrize('consumer', ['calculateMo', 'applyNormativeTep'])
@pytest.mark.parametrize('boundary', ['region_roundtrip', 'new_parcel'])
def test_late_mo_calculation_cannot_restore_a_previous_territory(served, consumer, boundary):
    from playwright.sync_api import expect
    # The source response is synthetic; both consumers are the real PAGE code.
    data = {'query': 'Синтетическая прежняя территория',
            'inputs': {'vri_region': 'mo', 'land_rights_cost_mln': 111},
            'tep': deepcopy(core.TEP_DEFAULT), 'vri': {}, 'territory': {'site_area_ha': 1}}
    with full_page(served, 1440) as (page, _, __):
        page.route('**/mo/calculate', lambda route: route.fulfill(status=200, json=data))
        page.evaluate('''()=>{inputs.site_area_ha=1;document.getElementById('moArea').value='1';
          window.territoryFetch=fetch.bind(window);window.fetch=async(...args)=>{
            const response=await territoryFetch(...args);if(args[0]==='/mo/calculate')
            await new Promise(resolve=>{window.territoryRelease=resolve});return response}}''')
        page.evaluate("()=>{window.territoryPending=" + consumer + "();return true}")
        page.wait_for_function('typeof window.territoryRelease==="function"')
        if boundary == 'region_roundtrip':
            for region in ('msk', 'mo'):
                page.locator('#f_vri_region').select_option(region)
                page.wait_for_function('calcIdle()')
        else:
            page.evaluate(NEW_TERRITORY)
        read = 'JSON.stringify({inputs,tep,moResult})'
        before = page.evaluate(read)
        page.evaluate('window.territoryRelease()')
        page.evaluate('async()=>await window.territoryPending')
        assert page.evaluate(read) == before
        expect(page.locator('#cadastralAnalyzeButton')).to_be_enabled()
