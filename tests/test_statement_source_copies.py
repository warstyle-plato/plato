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


def versions():
    sources, references = [], []
    first = {'label': 'КС-2 № 1', 'quantity': 1, 'material_quantity': 0,
             'amount': 100, 'work_amount': 100, 'material_amount': 0}
    for index, day in enumerate((FIRST, SECOND), 1):
        origin = {'filename': 'KS.xlsx', 'sheet': 'Работы', 'snapshot_id': day,
                  'source_date': day, 'file_sha256': str(index)*64}
        item = {'position': '1', 'name': 'Монтаж', 'unit': 'м2', 'plan_quantity': 10,
                'planned_amount': 1000, 'completed_quantity': index, 'completed_amount': 100*index,
                'source': {'row': 9}, 'periods': [copy.deepcopy(first)]}
        if index == 2:
            item['periods'].append(dict(first, label='КС-2 № 2'))
        ledger = {'source': origin, 'archive_snapshot_id': day, 'source_date': day,
                  'file_sha256': origin['file_sha256'], 'period_year': 2026, 'items': [item]}
        sources.append((ledger, []))
        references.append({'source': origin, 'source_date': day, 'source_complete': True,
                           'planned': 1000, 'completed': 100*index})
    return references, sources


@pytest.mark.parametrize('field,value', [('file_sha256', None), ('snapshot_id', None),
                                        ('source_date', None), ('source_date', 'not-a-date')])
def test_a_covered_version_without_verified_provenance_is_not_hidden(field, value):
    from developaid_monitor_statement_sources import unique_statement_sources
    references, sources = versions()
    references[0]['source'][field] = value
    if field == 'source_date':
        references[0]['source_date'] = value
    sources[0][0][{'snapshot_id': 'archive_snapshot_id'}.get(field, field)] = value
    assert len(unique_statement_sources(references, sources)) == 2


@pytest.mark.parametrize('field', ['material_quantity', 'material_amount'])
@pytest.mark.parametrize('value', [None, 1])
def test_covered_nonzero_period_cannot_lose_or_change_a_known_zero_component(field, value):
    from developaid_monitor_statement_sources import unique_statement_sources
    references, sources = versions()
    assert len(unique_statement_sources(references, sources)) == 1
    sources[1][0]['items'][0]['periods'][0][field] = value
    assert len(unique_statement_sources(references, sources)) == 2


def test_statement_family_proof_is_per_call_and_does_not_modify_cached_observations():
    from developaid_monitor_statement_sources import statement_family_map
    from developaid_monitor_statement_union import _source
    references, sources = versions()
    for ledger, _ in sources:
        ledger['source_complete'] = True
    before = copy.deepcopy(sources)
    families = statement_family_map(sources)
    assert families[_source(references[0]['source'])] == families[_source(references[1]['source'])]
    assert sources == before
    assert statement_family_map(sources[:1]) == {}


def test_simultaneous_different_observations_do_not_get_a_shared_statement_family():
    from developaid_monitor_statement_sources import statement_family_map
    _, sources = versions()
    for ledger, _ in sources:
        ledger.update(source_complete=True, source_date=SECOND)
        ledger['source']['source_date'] = SECOND
    assert statement_family_map(sources) == {}


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


def test_new_cumulative_book_keeps_covered_previous_edition_in_history_not_current_sources(context):
    context.setattr(contracts, '_archive', ARCHIVE_READER)
    save(FIRST, 'KS.xlsx', ks(period='jan'))
    save(MIDDLE, 'KS.xlsx', ks())
    save(SECOND, 'Renamed.xlsx', ks())
    row, = contracts.build(PROJECT, SECOND, include_history=False)['rows']
    reference, = row['reported_performance_sources']
    assert row['performance_source_count'] == 1 and reference['completed'] == 400
    previous, = reference['source_versions']
    assert previous['completed'] == 200 and previous['source_date'] == FIRST
    assert len(reference['source_copies']) == 1
    assert all(source['source_date'] != FIRST for source in reference['source_copies'])
    assert row['completed'] == 400 and len(row['physical_items'][0]['history_sources']) == 3


def test_incremental_period_is_not_mistaken_for_a_complete_replacement(context):
    context.setattr(contracts, '_archive', ARCHIVE_READER)
    save(FIRST, 'KS.xlsx', ks(period='jan'))
    save(SECOND, 'KS.xlsx', ks(period='feb'))
    row, = contracts.build(PROJECT, SECOND, include_history=False)['rows']
    assert len(row['reported_performance_sources']) == 2
    assert row['completed'] == 400
    assert not any(source.get('source_versions') for source in row['reported_performance_sources'])


def test_renamed_proven_copies_keep_named_periods_readable_for_summary_dates(context):
    import developaid_contract_fact as fact
    import developaid_contract_act_dates as dates
    context.setattr(contracts, '_archive', ARCHIVE_READER)
    content = book(split=True)
    save(FIRST, 'Original.xlsx', content)
    save(MIDDLE, 'Renamed.xlsx', content)
    save(SECOND, 'Current.xlsx', content)
    row, = contracts.build(PROJECT, SECOND, include_history=False)['rows']
    found = fact.acts(row)
    work = next(work for work in found['unread'] if work['number'] == '1.1')
    assert work['reported_quantity'] == 4
    assert len(work['periods']) == 1
    found['summary_acts'] = [{'number': '1', 'date': FIRST, 'amount': 700}]
    resolved = dates.resolve(found, [])
    assert not resolved['unread'] and any(period.get('quantity') == 4 for period in resolved['acts'])
    earlier, = contracts.build(PROJECT, FIRST, include_history=False)['rows']
    assert len(earlier['physical_items'][0].get('history_sources') or []) <= 1


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
