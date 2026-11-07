"""Above storage is additional GNS; each entered area is counted once.

All inputs here are synthetic and unrelated to owner screenshots.
"""
from __future__ import annotations

import copy
import io
import sys
from functools import lru_cache
from pathlib import Path

import openpyxl
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))

import main as wrapper
from xlsx_eval import Evaluator

core = wrapper.core
STORAGE_AREA = 172.0
FLAT_AREA = 8100.0
SHOP_AREA = 360.0
PARKING_AREA = 1260.0


def project(placement='underground', with_storage=True):
    x = copy.deepcopy(core.DEFAULT_INPUTS)
    x.update(storage_placement=placement, vri_required=False, land_rights_cost_mln=0,
             landscaping_gns_th_per_sqm=1.3,
             underground_manual_gns_sqm=PARKING_AREA, underground_manual_spaces=36,
             underground_levels=1, underground_rate_is_level1=False,
             social_mode='Денежная компенсация', social_compensation_mln=0,
             kindergarten_places=0, school_places=0, clinic_capacity=0,
             social_dou_gba_sqm=0, social_school_gba_sqm=0, social_clinic_gba_sqm=0)
    t = copy.deepcopy(core.TEP_DEFAULT)
    for row in t.values():
        for field in ('gns', 'total_area', 'useful', 'saleable', 'transfer', 'units', 'under_gns'):
            if field in row:
                row[field] = 0

    def row(key, gns, total, useful, saleable, units=0):
        t[key].update(gns=gns, total_area=total, useful=useful, saleable=saleable,
                      transfer=0, units=units)

    row('apartments', FLAT_AREA, 7290, 5600, 5400, 90)
    row('ground_commercial', SHOP_AREA, 324, 291.6, 291.6)
    row('underground_parking', PARKING_AREA, PARKING_AREA, 0, 0, 36)
    row('storage', STORAGE_AREA if with_storage else 0, STORAGE_AREA if with_storage else 0,
        STORAGE_AREA if with_storage else 0, STORAGE_AREA if with_storage else 0,
        40 if with_storage else 0)
    return x, t


@lru_cache(None)
def result(placement='underground', with_storage=True):
    x, t = project(placement, with_storage)
    return core.calculate(core.CalcRequest(inputs=x, tep=t, rates=[]))


def test_above_storage_is_additional_and_total_volume_is_conserved_on_toggle():
    under, above = result(), result('above')
    assert above['summary']['project_gns_sqm'] == FLAT_AREA + SHOP_AREA + STORAGE_AREA
    assert under['summary']['project_gns_sqm'] == FLAT_AREA + SHOP_AREA
    assert above['tep']['core_under_gns'] == PARKING_AREA
    assert under['tep']['core_under_gns'] == PARKING_AREA + STORAGE_AREA
    assert above['summary']['construction_volume_sqm'] == under['summary']['construction_volume_sqm']
    assert above['summary']['construction_volume_sqm'] == FLAT_AREA + SHOP_AREA + PARKING_AREA + STORAGE_AREA
    for key in ('gns', 'total_area', 'useful', 'saleable'):
        assert above['tep']['total'][key] == under['tep']['total'][key]
    assert core._above_ground_sqm(above['tep']) == above['summary']['project_gns_sqm']


def test_each_part_carries_its_full_entered_area_without_subtracting_from_apartments():
    x, t = project('above')
    before = copy.deepcopy(t)
    parts = core.mkd_part_gns(x, t)
    assert parts['above']['apartments'] == FLAT_AREA
    assert parts['above']['storage'] == STORAGE_AREA
    assert sum(parts['above'].values()) == result('above')['tep']['core_above_gns']
    assert t == before
    # An independent storage product is not clipped to a different product's area.
    t['apartments']['gns'] = 0
    assert core.mkd_part_gns(x, t)['above']['storage'] == STORAGE_AREA
    assert core.project_above_gns(t, x) == SHOP_AREA + STORAGE_AREA


def test_cost_bases_follow_area_and_zero_storage_has_no_effect():
    under, above, none = result(), result('above'), result('above', False)
    x, _ = project('above')
    assert above['capex']['main_above'] - none['capex']['main_above'] == pytest.approx(
        STORAGE_AREA * x['main_above_th_per_sqm'] * 1000)
    assert above['capex']['main_under'] == none['capex']['main_under']
    assert above['capex']['main_above'] - under['capex']['main_above'] == pytest.approx(
        STORAGE_AREA * x['main_above_th_per_sqm'] * 1000)
    assert under['capex']['main_under'] - above['capex']['main_under'] == pytest.approx(
        STORAGE_AREA * x['main_under_th_per_sqm'] * 1000)
    assert above['tep']['project_articles_sqm'] - none['tep']['project_articles_sqm'] == STORAGE_AREA
    assert result('above', False)['summary']['project_gns_sqm'] == result('underground', False)['summary']['project_gns_sqm']


def test_manual_other_area_columns_are_preserved_and_missing_placement_is_underground():
    x, t = project('above')
    t['storage'].update(total_area=0, useful=None, saleable=0)
    before = copy.deepcopy(t)
    assert core.project_above_gns(t, x) == FLAT_AREA + SHOP_AREA + STORAGE_AREA
    assert core.mkd_part_gns(x, t)['above']['storage'] == STORAGE_AREA
    assert t == before
    x.pop('storage_placement')
    assert core.project_above_gns(t, x) == core.project_above_gns(t) == FLAT_AREA + SHOP_AREA
    assert core.underground_products(x) == ('underground_parking', 'storage')


def test_manual_storage_area_is_not_replaced_by_the_default_area_per_unit():
    x, t = project('above')
    t['storage'].update(gns=91, units=7, total_area=0, useful=0, saleable=0)
    before = copy.deepcopy(t)
    r = core.calculate(core.CalcRequest(inputs=x, tep=t, rates=[]))
    storage = next(row for row in r['tep']['rows'] if row['key'] == 'storage')
    assert storage['gns'] == 91 and storage['units'] == 7
    assert storage['total_area'] == storage['useful'] == storage['saleable'] == 0
    assert r['summary']['project_gns_sqm'] == FLAT_AREA + SHOP_AREA + 91
    assert t == before


@pytest.mark.parametrize('region', ['msk', 'mo'])
def test_storage_adds_no_residents_or_social_load(region):
    cases = []
    for placement, with_storage in [('underground', False), ('underground', True), ('above', True)]:
        x, t = project(placement, with_storage)
        x.update(vri_region=region, social_mode='Строительство',
                 kindergarten_places=18, school_places=45, clinic_capacity=5,
                 social_dou_gba_sqm=1000, social_school_gba_sqm=3000,
                 social_clinic_gba_sqm=500)
        r = core.calculate(core.CalcRequest(inputs=x, tep=t, rates=[]))
        rows = {row['key']: row for row in r['tep']['rows']}
        population, _ = core.project_population(rows, region)
        assert population > 0 and r['capex']['social'] > 0
        assert r['summary']['social_required']['available']
        cases.append((population, r['summary']['social_required'],
                      r['summary']['social_program'], r['capex']['social']))
    assert cases[0] == cases[1] == cases[2]


def test_two_phases_sum_their_full_storage_areas_once():
    x, t = project('above')
    phasing = {'enabled': True, 'mode': 'phased', 'phase_count': 2, 'user_enabled': True,
               'phase_gap_months': 6,
               'phases': [{'name': f'Корпус {i + 1}', 'start_offset_months': 6 * i,
                           'construction_months': 24} for i in range(2)]}
    bundle = core.calculate_phased(core.PhasedCalcRequest(inputs=x, tep=t, rates=[], phasing=phasing))
    consolidated = bundle['consolidated']
    expected = sum(p['result']['summary']['project_gns_sqm'] for p in bundle['phases'])
    assert consolidated['summary']['project_gns_sqm'] == pytest.approx(expected)
    assert consolidated['tep']['above_gns'] == pytest.approx(expected)
    assert core._above_ground_sqm(consolidated['tep']) == pytest.approx(expected)
    assert consolidated['summary']['project_gns_sqm'] == pytest.approx(FLAT_AREA + SHOP_AREA + STORAGE_AREA, abs=1)


def test_two_standalone_objects_keep_their_own_underground_area():
    outputs = []
    for placement in ('underground', 'above'):
        x, t = project(placement)
        x.update(offices_enabled=True, offices_gba_sqm=2200, offices_saleable_sqm=1400,
                 retail_enabled=True, retail_gba_sqm=1700, retail_saleable_sqm=1190,
                 offices_parking_under_spaces=10, retail_parking_under_spaces=8,
                 _parking_by_hand=['offices', 'retail'])
        t['offices'].update(gns=2200, total_area=2000, useful=1400, saleable=1400)
        t['standalone_retail'].update(gns=1700, total_area=1530, useful=1190, saleable=1190)
        r = core.calculate(core.CalcRequest(inputs=x, tep=t, rates=[]))
        rows = {row['key']: row for row in r['tep']['rows']}
        assert rows['offices']['gns'] > 0 and rows['standalone_retail']['gns'] > 0
        own_under = sum(float(row.get('under_gns') or 0) for row in rows.values())
        assert own_under > 0
        assert r['summary']['underground_gns_sqm'] == pytest.approx(r['tep']['core_under_gns'] + own_under)
        assert r['summary']['construction_volume_sqm'] == pytest.approx(
            sum(float(row.get('gns') or 0) for row in rows.values()) + own_under)
        assert r['tep']['site_massing']['above_gns_sqm'] == r['summary']['project_gns_sqm']
        outputs.append(r)
    under, above = outputs
    assert above['summary']['project_gns_sqm'] - under['summary']['project_gns_sqm'] == STORAGE_AREA
    assert above['summary']['construction_volume_sqm'] == under['summary']['construction_volume_sqm']


@pytest.fixture(scope='module', params=['underground', 'above'])
def book_case(request):
    placement = request.param
    x, t = project(placement)
    bundle = core._run_authoritative_model(x, t, [], None)
    content, _, meta = core.build_project_workbook(
        x, t, [], None, project_name='Синтетическая площадь',
        finance_hints=core._v4_finance_hints(bundle))
    book = openpyxl.load_workbook(io.BytesIO(content))
    return placement, x, bundle['consolidated'], book, meta


def test_book_area_cost_and_dashboard_formulas_match_engine(book_case):
    placement, x, r, book, meta = book_case
    assert not meta.get('missing'), meta
    ev = Evaluator(book)
    above = placement == 'above'
    assert ev.cell('ОТЧЕТ', f'B{core._V4_REPORT_STORAGE_ROW}') == (STORAGE_AREA if above else 0)
    assert ev.cell('ОТЧЕТ', f'{core._V4_UNDER_COLUMN}{core._V4_REPORT_STORAGE_ROW}') == (0 if above else STORAGE_AREA)
    for key in ('main_above', 'main_under', 'ird', 'design_p', 'design_rd', 'preparation', 'utilities', 'commissioning', 'site_maintenance'):
        row = core._V4_CAPEX_ARTICLE_ROW[key]
        assert ev.cell('CAPEX', f'B{row}') == pytest.approx(r['capex'][key] / 1e6, rel=1e-6), key
    # Full numerical comparison includes NPV/IRR and annual tax/debt/equity flows.
    import book_engine_parity as parity
    checked = dict(r, _discount_rate=x['discount_rate_pct'] / 100)
    lines = parity._v4_lines(core, book, checked)
    assert len(lines) > 100
    assert not [line.text('synthetic_storage') for line in lines if not line.agrees()]


def test_book_placement_edit_moves_area_and_costs_without_rebuilding(book_case):
    placement, _, _, book, _ = book_case
    sheet = book['Параметры модели']
    label = next(cell for row in sheet for cell in row if cell.value == 'Размещение кладовых')
    choice = sheet.cell(label.row, 2)
    original = choice.value
    opposite = 'above' if placement == 'underground' else 'underground'
    try:
        choice.value = dict(core.STORAGE_PLACEMENT_OPTIONS)[opposite]
        ev = Evaluator(book)
        expected = result(opposite)
        for key in ('main_above', 'main_under', 'landscaping', 'ird'):
            row = core._V4_CAPEX_ARTICLE_ROW[key]
            assert ev.cell('CAPEX', f'B{row}') == pytest.approx(expected['capex'][key] / 1e6, rel=1e-6), key
        import v4_dashboard
        for key, field in [('core_above_sqm', 'core_above_gns'), ('core_under_sqm', 'core_under_gns')]:
            assert ev.cell(v4_dashboard.DATA_SHEET, f'C{v4_dashboard.DATA_ROWS[key]}') == pytest.approx(expected['tep'][field])
        assert ev.cell('ОТЧЕТ', f'B{core._V4_REPORT_STORAGE_ROW}') == (STORAGE_AREA if opposite == 'above' else 0)
        storage_row = v4_dashboard.product_rows()['storage']
        assert ev.cell(v4_dashboard.DATA_SHEET, f'C{storage_row}') == (STORAGE_AREA if opposite == 'above' else 0)
        assert ev.cell(v4_dashboard.DATA_SHEET, f'L{storage_row}') == (0 if opposite == 'above' else STORAGE_AREA)
    finally:
        choice.value = original


def test_book_tamper_with_above_cost_is_detected(book_case):
    _, x, r, book, _ = book_case
    cell = book['CAPEX'][f'B{core._V4_CAPEX_ARTICLE_ROW["main_above"]}']
    old = cell.value
    amount = Evaluator(book).cell('CAPEX', cell.coordinate)
    try:
        cell.value = amount * 1.01
        import book_engine_parity as parity
        lines = parity._v4_lines(core, book, dict(r, _discount_rate=x['discount_rate_pct'] / 100))
        assert any(not line.agrees() for line in lines), 'An altered construction cost must break parity'
    finally:
        cell.value = old


BROWSER_STATE = r"""() => {
 const value=id=>Number((document.getElementById(id).textContent||'').replace(/[^0-9,.-]/g,'').replace(',','.'));
 const footer=document.querySelector('#reportTep tfoot tr');
 return {checked:document.getElementById('tep_storage_placement').checked,
   placement:inputs.storage_placement,apartment:tep.apartments.gns,storage:tep.storage.gns,
   total:value('ta'),useful:value('tu'),saleable:value('ts'),above:value('tg'),
   reportAbove:Number(footer.children[1].textContent.replace(/\s/g,'').replace(',','.')),
   engineAbove:lastResult.summary.project_gns_sqm,
   volume:lastResult.summary.construction_volume_sqm,
   aboveCost:lastResult.capex.main_above};
}"""


@pytest.fixture(scope='module')
def browser_cases():
    import browser
    from playwright.sync_api import sync_playwright
    x, t = project()
    output = []
    with browser.serve(core.app, 18946) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(browser.chromium_or_skip())) as engine:
            for width in (390, 1440):
                page = engine.new_page(viewport={'width': width, 'height': 1000})
                errors = []
                page.on('pageerror', lambda e: errors.append(str(e)))
                page.goto(base, wait_until='domcontentloaded')
                browser.wait_for_result(page)
                page.evaluate("async data => {applyProjectSnapshot(data); await settledCalculate();}",
                              {'inputs': x, 'tep': t, 'phasing': {'enabled': False, 'user_enabled': False}})
                page.locator('button[data-tab="tep"]').click()
                before = page.evaluate(BROWSER_STATE)
                page.locator('#tep_storage_placement').check()
                page.evaluate('async () => {await settledCalculate();}')
                after = page.evaluate(BROWSER_STATE)
                page.evaluate('() => persistLocalSilently()')
                page.reload(wait_until='domcontentloaded')
                browser.wait_for_result(page)
                page.evaluate('async () => {await settledCalculate();}')
                page.locator('button[data-tab="tep"]').click()
                restored = page.evaluate(BROWSER_STATE)
                page.locator('#tep_storage_placement').uncheck()
                page.evaluate('async () => {await settledCalculate();}')
                back = page.evaluate(BROWSER_STATE)
                output.append({'width': width, 'before': before, 'after': after, 'restored': restored,
                               'back': back, 'errors': errors})
                page.close()
    return output


def test_real_page_updates_totals_preserves_saved_state_and_reverses_toggle(browser_cases):
    for case in browser_cases:
        before, after, restored, back = (case[k] for k in ('before', 'after', 'restored', 'back'))
        assert not case['errors']
        assert before['checked'] is False and after['checked'] is True
        assert after['above'] == before['above'] + STORAGE_AREA
        assert after['above'] == after['reportAbove'] == after['engineAbove']
        for key in ('apartment', 'storage', 'total', 'useful', 'saleable', 'volume'):
            assert after[key] == before[key], (case['width'], key)
            assert restored[key] == after[key], (case['width'], key, 'restore')
        assert restored['checked'] and restored['above'] == after['above']
        assert back['checked'] is False
        for key in ('above', 'total', 'useful', 'saleable', 'apartment', 'storage', 'volume', 'aboveCost'):
            assert back[key] == before[key], (case['width'], key, 'reverse')


def test_real_pdf_contains_complete_area_total():
    from pypdf import PdfReader
    x, t = project('above')
    bundle = core._run_authoritative_model(x, t, [], {})
    r = bundle['consolidated']
    content = core._build_developaid_pdf({'result': r, 'phases': bundle.get('phases') or [],
        'inputs': x, 'tep': t, 'rates': [], 'phasing': {}, 'scenario': 'base', 'cadastral_numbers': []})
    text = ' '.join(' '.join(p.extract_text() for p in PdfReader(io.BytesIO(content)).pages).split())
    assert 'Кладовые' in text and core._pdf_num(STORAGE_AREA, 0) in text
    assert core._pdf_num(r['summary']['construction_volume_sqm'], 0) in text
    assert r['summary']['construction_volume_sqm'] == FLAT_AREA + SHOP_AREA + PARKING_AREA + STORAGE_AREA
