"""Mixed-project landscaping includes each standalone object's applied area.

Every input is synthetic; this regression is separate from storage placement.
"""
from __future__ import annotations
import copy
import io
import re
import sys
from pathlib import Path

import openpyxl
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / 'scripts')]
import main as wrapper
from xlsx_eval import Evaluator

core = wrapper.core
OFFICE_AREA = 2400.0
RETAIL_AREA = 1800.0
GNS_RATE = 1.9


def project(phased=False):
    x = copy.deepcopy(core.DEFAULT_INPUTS)
    x.update(project_start='2027-02-01', ird_months=4, construction_months=18,
             residual_sales_months=6, vri_required=False, land_rights_cost_mln=0,
             landscaping_gns_th_per_sqm=GNS_RATE, storage_placement='underground',
             underground_manual_gns_sqm=1680, underground_manual_spaces=42,
             underground_levels=1, underground_rate_is_level1=False,
             social_mode='Денежная компенсация', social_compensation_mln=0,
             kindergarten_places=0, school_places=0, clinic_capacity=0,
             social_dou_gba_sqm=0, social_school_gba_sqm=0, social_clinic_gba_sqm=0,
             offices_enabled=True, offices_gba_sqm=OFFICE_AREA, offices_saleable_sqm=1500,
             retail_enabled=True, retail_gba_sqm=RETAIL_AREA, retail_saleable_sqm=1140,
             offices_parking_under_spaces=0, retail_parking_under_spaces=0,
             _parking_by_hand=['offices', 'retail'])
    t = copy.deepcopy(core.TEP_DEFAULT)
    for row in t.values():
        for field in ('gns', 'total_area', 'useful', 'saleable', 'transfer', 'units', 'under_gns'):
            if field in row:
                row[field] = 0
    def row(key, gns, total, useful, saleable, units=0, transfer=0):
        t[key].update(gns=gns, total_area=total, useful=useful, saleable=saleable,
                      units=units, transfer=transfer)
    row('apartments', 12000, 10800, 8200, 7900, 110, 300)
    row('ground_commercial', 700, 630, 550, 520, transfer=30)
    row('underground_parking', 1680, 1450, 0, 0, 42)
    row('storage', 260, 210, 185, 165, 20)
    row('offices', OFFICE_AREA, 2160, 1620, 1500)
    row('standalone_retail', RETAIL_AREA, 1620, 1280, 1140)
    p = {} if not phased else {
        'enabled': True, 'user_enabled': True, 'mode': 'phased', 'phase_count': 2,
        'phase_gap_months': 6,
        'discrete': {'offices': 1, 'standalone_retail': 2},
        'phases': [{'name': f'Синтетическая очередь {i+1}', 'start_offset_months': 6*i,
                    'construction_months': 18} for i in range(2)]}
    return x, t, p


@pytest.fixture(scope='module', params=[False, True], ids=['single', 'two-phases'])
def book_case(request):
    sys.setrecursionlimit(max(sys.getrecursionlimit(), 400000))
    x, t, p = project(request.param)
    bundle = core._run_authoritative_model(x, t, [], copy.deepcopy(p))
    hints = core._v4_finance_hints(bundle)
    content, _, meta = core.build_project_workbook(
        x, t, [], copy.deepcopy(p), project_name='Synthetic mixed area', finance_hints=hints)
    assert not meta.get('missing'), meta
    book = openpyxl.load_workbook(io.BytesIO(content))
    phase_results = [item['result'] for item in bundle.get('phases') or []] or [bundle['consolidated']]
    expected_outside = [r['summary']['project_gns_sqm'] - r['tep']['core_above_gns'] for r in phase_results]
    return x, bundle['consolidated'], phase_results, expected_outside, book


def test_applied_object_area_is_in_the_right_queue_once(book_case):
    _, _, phase_results, expected, book = book_case
    ev = Evaluator(book)
    for i, outside in enumerate(expected):
        assert ev.cell('Параметры модели', f'AY{88+i}') == pytest.approx(outside)
        row = core._V4_CAPEX_ARTICLE_ROW['landscaping'] + core._V4_CAPEX_BLOCK_STRIDE*i
        assert ev.cell('CAPEX', f'B{row}') == pytest.approx(phase_results[i]['capex']['landscaping']/1e6, rel=1e-6)
    assert sum(expected) == pytest.approx(OFFICE_AREA + RETAIL_AREA)
    assert sum(ev.cell('Параметры модели', f'AY{88+i}') or 0 for i in range(4)) == pytest.approx(sum(expected))


def test_full_capex_profit_npv_irr_and_annual_flows_match(book_case):
    x, r, _, _, book = book_case
    import book_engine_parity as parity
    lines = parity._v4_lines(core, book, dict(r, _discount_rate=x['discount_rate_pct']/100))
    assert len(lines) > 100
    assert not [line.text('synthetic_mixed_area') for line in lines if not line.agrees()]


def test_landscaping_tamper_is_caught(book_case):
    x, r, _, _, book = book_case
    cell = book['CAPEX'][f'B{core._V4_CAPEX_ARTICLE_ROW["landscaping"]}']
    old = cell.value
    amount = Evaluator(book).cell('CAPEX', cell.coordinate)
    try:
        cell.value = amount * 1.01
        import book_engine_parity as parity
        lines = parity._v4_lines(core, book, dict(r, _discount_rate=x['discount_rate_pct']/100))
        assert any(not line.agrees() for line in lines)
    finally:
        cell.value = old


def test_editing_object_gns_recalculates_the_area_basis(book_case):
    _, _, phase_results, _, book = book_case
    layout = core._v4_layout('offices')
    source = book['Параметры модели'][core._V4_INPUT_CELLS['offices_gba_sqm']]
    # The technical parameter sheet can alias the user-facing input. Follow
    # only exact cell references to edit the actual numeric input, not a formula.
    for _ in range(8):
        if isinstance(source.value, (int, float)):
            break
        match = re.fullmatch(r"='([^']+)'!([A-Z$]+[0-9$]+)", str(source.value))
        assert match, source.value
        source = book[match[1]][match[2].replace('$', '')]
    old = source.value
    assert isinstance(old, (int, float)) and old > 0
    ev = Evaluator(book)
    applied = ev.cell('ОБЪЕКТЫ', f'B{layout.object_head+6}')
    before = [ev.cell('Параметры модели', f'AY{88+i}') for i in range(len(phase_results))]
    try:
        source.value = old * 1.25
        edited = Evaluator(book)
        assert edited.cell('ОБЪЕКТЫ', f'B{layout.object_head+6}') == pytest.approx(applied * 1.25)
        assert edited.cell('Параметры модели', 'AY88') == pytest.approx(before[0] + applied*.25)
        for i in range(1, len(phase_results)):
            assert edited.cell('Параметры модели', f'AY{88+i}') == pytest.approx(before[i])
        row = core._V4_CAPEX_ARTICLE_ROW['landscaping']
        difference = edited.cell('CAPEX', f'B{row}') - ev.cell('CAPEX', f'B{row}')
        assert difference == pytest.approx(applied * .25 * GNS_RATE / 1000)
    finally:
        source.value = old


def test_changing_object_queue_moves_its_area_without_copying_master_area(book_case):
    _, _, phase_results, _, book = book_case
    if len(phase_results) == 1:
        # No second active queue exists in this scenario; cover disabled
        # queues below without changing the scenario into a different project.
        ev = Evaluator(book)
        assert all(ev.cell('Параметры модели', f'AY{88+i}') == 0 for i in (1, 2, 3))
        return
    layout = core._v4_layout('offices')
    phase = book['ОБЪЕКТЫ'][f'B{layout.object_head+2}']
    old = phase.value
    ev = Evaluator(book)
    before = [ev.cell('Параметры модели', f'AY{88+i}') for i in (0, 1)]
    applied = ev.cell('ОБЪЕКТЫ', f'B{layout.object_head+6}')
    try:
        phase.value = 2
        edited = Evaluator(book)
        after = [edited.cell('Параметры модели', f'AY{88+i}') for i in (0, 1)]
        assert after == pytest.approx([before[0]-applied, before[1]+applied])
        assert sum(after) == pytest.approx(sum(before))
    finally:
        phase.value = old
