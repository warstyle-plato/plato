"""Repeated uploads are one statement, with source copies retained as evidence."""
from __future__ import annotations

import copy
import io

import openpyxl
import pytest

import developaid_monitor_contracts as contracts
import developaid_monitor_ledgers as ledgers
from developaid_monitor_statement_union import statement_union
from test_contracts_archive_union import FIRST, MIDDLE, SECOND, PROJECT
from test_contracts_from_cumulative_headers import ARCHIVE_READER, archive, context, ks  # noqa: F401
from test_monitor_cumulative_ledgers import book


def save(day, name, content):
    return ledgers.store_archive(PROJECT, archive([(name, content)]), day)


@pytest.mark.parametrize('undated', [False, True])
def test_three_identical_archives_have_one_current_statement_and_unchanged_imports(context, undated):
    context.setattr(contracts, '_archive', ARCHIVE_READER)
    content = book(split=True) if undated else ks()
    save(FIRST, 'KS.xlsx', content)
    save(MIDDLE, 'Renamed.xlsx', content)
    latest = save(SECOND, 'KS.xlsx', content)
    root = ledgers._root(PROJECT)
    before = {path.name: path.read_bytes() for path in root.iterdir() if path.is_file()}
    row, = contracts.build(PROJECT, SECOND, include_history=False)['rows']
    reference, = row['reported_performance_sources']
    assert row['performance_source_count'] == 1
    assert reference['source']['snapshot_id'] == latest['snapshot_id']
    assert reference['source_date'] == SECOND
    assert len(reference['source_copies']) == 2
    assert {item['source_date'] for item in reference['source_copies']} == {FIRST, MIDDLE}
    assert len(row['sources']) == 3  # Original archive evidence is not deleted.
    assert len(row['physical_items'][0]['history_sources']) == 3
    if undated:
        assert reference['completed'] == 700 and reference['planned'] == 1020
        assert row['completed'] is None and row['statement_progress']['ratio'] is None
    else:
        assert row['completed'] == 400
        assert row['statement_progress']['completed'] == 400
        assert row['statement_progress']['source_count'] == 1
        assert statement_union(row)['ratio'] == row['statement_progress']['ratio']
    earlier, = contracts.build(PROJECT, FIRST, include_history=False)['rows']
    old_reference, = earlier['reported_performance_sources']
    assert old_reference['source_date'] == FIRST and not old_reference.get('source_copies')
    assert {path.name: path.read_bytes() for path in root.iterdir() if path.is_file()} == before


@pytest.mark.parametrize('cell,value', [
    ('C9', 'Самостоятельная работа'), ('D9', 'м2'), ('G9', 2000),
    ('H7', 'Выполнение № 3 (01.03.2026 - 31.03.2026)'),
    ('I9', 100), ('N7', '2025 год'),
])
def test_equal_total_or_filename_does_not_hide_changed_work_plan_year_or_period(context, cell, value):
    context.setattr(contracts, '_archive', ARCHIVE_READER)
    save(FIRST, 'KS.xlsx', ks())
    workbook = openpyxl.load_workbook(io.BytesIO(ks()))
    workbook.active[cell] = value
    content = io.BytesIO()
    workbook.save(content)
    save(SECOND, 'KS.xlsx', content.getvalue())
    row, = contracts.build(PROJECT, SECOND, include_history=False)['rows']
    assert row['performance_source_count'] == len(row['reported_performance_sources']) == 2
    assert all(not ref.get('source_copies') for ref in row['reported_performance_sources'])


def test_union_accepts_projected_rows_bound_to_an_older_identical_copy(context):
    context.setattr(contracts, '_archive', ARCHIVE_READER)
    save(FIRST, 'KS.xlsx', ks())
    old, = contracts.build(PROJECT, FIRST, include_history=False)['rows']
    save(SECOND, 'Renamed.xlsx', ks())
    row, = contracts.build(PROJECT, SECOND, include_history=False)['rows']
    row['physical_items'] = copy.deepcopy(old['physical_items'])
    result = statement_union(row)
    assert result['state'] == 'known' and result['source_count'] == 1
    assert result['completed'] == 400 and result['planned'] == 1020


@pytest.mark.parametrize('width', [390, 1440])
def test_card_shows_one_statement_after_three_uploads(context, width):
    from playwright.sync_api import expect
    from contract_rows import opened
    from test_monitor_cumulative_controls import browser_page

    context.setattr(contracts, '_archive', ARCHIVE_READER)
    content = book(split=True)
    for day in (FIRST, MIDDLE, SECOND):
        save(day, 'KS.xlsx', content)
    register = contracts.build(PROJECT, SECOND, include_history=False)
    with browser_page(width) as (page, responses, errors):
        responses.data = register
        page.locator('#contractsTab').click()
        details = opened(page)
        statements = details.locator('[data-label="Выполнено по накопительным"] .contract-reported-money')
        expect(statements).to_have_count(1)
        expect(statements).to_contain_text('Ведомость 1')
        assert 'Ведомость 2' not in details.inner_text()
        assert 'Ведомость 3' not in details.inner_text()
        assert not errors
