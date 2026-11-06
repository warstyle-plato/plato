"""Storage integration with the mixed-workbook area fix supplied by PR 1003."""
from __future__ import annotations

import copy
import io
import sys

import openpyxl
import pytest

from test_mixed_workbook_landscaping_gns import core, project
from xlsx_eval import Evaluator
import book_engine_parity as parity


@pytest.fixture(scope='module', params=[(False, 'underground'), (False, 'above'),
                                     (True, 'underground'), (True, 'above')],
                ids=['single-under', 'single-above', 'phased-under', 'phased-above'])
def mixed_storage(request):
    sys.setrecursionlimit(max(sys.getrecursionlimit(), 400000))
    phased, placement = request.param
    x, t, p = project(phased)
    x['storage_placement'] = placement
    bundle = core._run_authoritative_model(x, t, [], copy.deepcopy(p))
    content, _, meta = core.build_project_workbook(
        x, t, [], copy.deepcopy(p), project_name='Synthetic mixed storage',
        finance_hints=core._v4_finance_hints(bundle))
    assert not meta.get('missing'), meta
    return x, t, p, bundle, openpyxl.load_workbook(io.BytesIO(content))


def assert_parity(book, result, x):
    lines = parity._v4_lines(core, book, dict(result, _discount_rate=x['discount_rate_pct'] / 100))
    assert len(lines) > 100
    assert not [line.text('mixed_storage') for line in lines if not line.agrees()]


def test_storage_and_object_areas_are_counted_once_in_every_phase(mixed_storage):
    x, _, _, bundle, book = mixed_storage
    phases = [p['result'] for p in bundle.get('phases') or []] or [bundle['consolidated']]
    ev = Evaluator(book)
    for index, phase in enumerate(phases):
        queue_row = core._V4_CF_QUEUE_ENABLED_ROW + index
        outside = ev.cell('Параметры модели', f'{core._V4_QUEUE_OUTSIDE_ABOVE_COL}{queue_row}')
        assert outside == pytest.approx(phase['summary']['project_gns_sqm'] - phase['tep']['core_above_gns'])
        row = core._V4_CAPEX_ARTICLE_ROW['landscaping'] + core._V4_CAPEX_BLOCK_STRIDE * index
        assert ev.cell('CAPEX', f'B{row}') == pytest.approx(phase['capex']['landscaping'] / 1e6)
    assert_parity(book, bundle['consolidated'], x)


def test_editing_placement_keeps_full_mixed_book_parity(mixed_storage):
    x, t, p, _, book = mixed_storage
    sheet = book['Параметры модели']
    label = next(cell for row in sheet for cell in row if cell.value == 'Размещение кладовых')
    choice = sheet.cell(label.row, 2)
    original = choice.value
    opposite = 'above' if x['storage_placement'] == 'underground' else 'underground'
    edited = dict(x, storage_placement=opposite)
    expected = core._run_authoritative_model(edited, t, [], copy.deepcopy(p))['consolidated']
    try:
        choice.value = dict(core.STORAGE_PLACEMENT_OPTIONS)[opposite]
        assert_parity(book, expected, edited)
    finally:
        choice.value = original


def test_mixed_storage_cost_tamper_breaks_parity(mixed_storage):
    x, _, _, bundle, book = mixed_storage
    cell = book['CAPEX'][f'B{core._V4_CAPEX_ARTICLE_ROW["main_above"]}']
    original = cell.value
    amount = Evaluator(book).cell('CAPEX', cell.coordinate)
    try:
        cell.value = amount * 1.01
        lines = parity._v4_lines(core, book, dict(bundle['consolidated'], _discount_rate=x['discount_rate_pct'] / 100))
        assert any(not line.agrees() for line in lines)
    finally:
        cell.value = original
