"""Loaded-act reporting zeros do not become evidence of physical work on site."""
import ast
import copy
import io
import hashlib
from pathlib import Path
import time

import pytest
from openpyxl import load_workbook

import developaid_contract_acts as acts
import developaid_contract_comparison_export as export
import developaid_contract_control as control
import developaid_contract_documents as documents
import developaid_contract_fact as fact
import developaid_contract_files as files
import developaid_contract_gpr_export as gpr_export
import developaid_contract_plan as plan
import developaid_contract_rds as rds
import developaid_management_report_jobs as jobs
from tests.contract_rds_fixtures import native_card


PROJECT, CUT, CONTRACT = 'Учебный проект', '2026-03-05', 'c' * 64


def record(position, *, sha='d', number='1', day=CUT, quantity=6):
    position = copy.deepcopy(position)
    position.update(quantity=quantity, quantity_material=0,
                    amount={'work': quantity * 50, 'material': 0, 'total': quantity * 50},
                    unit_price={'work': 50, 'material': 0, 'total': 50})
    return {'sha256': sha * 64, 'filename': 'Учебный акт.pdf', 'title': 'Учебный акт',
            'act': {'number': number, 'date': day, 'start': '2026-03-01', 'finish': day,
                    'total': quantity * 50, 'positions': [position]}, 'warnings': []}


def card(*, records=None, performed_change=None, positions_change=None, dated=True, bind=True):
    original = native_card()
    documents = copy.deepcopy(original['documents'])
    if positions_change:
        positions_change(documents[0]['estimates'][0]['positions'])
    editions = [{'sha256': 'a'*64, 'estimate_sha256': 'a'*64, 'title': 'Учебная редакция',
                 'date': '2026-02-01', 'estimates': documents[0]['estimates'],
                 'schedule': documents[1]['schedule'], 'schedule_sha256': 'b'*64, 'start': None}]
    if not dated:
        for edition in editions:
            edition['schedule'] = None
            edition['schedule_sha256'] = ''
            for estimate in edition['estimates']:
                estimate['links'] = plan.links.propose(estimate, None)
        documents = [document for document in documents if not document.get('schedule')]
    positions = documents[0]['estimates'][0]['positions']
    if records is None:
        records = [record(positions[0])]
    performed = acts.accumulated(records, CUT)
    if performed_change:
        performed_change(performed)
    inputs = copy.deepcopy((editions, documents, performed))
    planned = plan.build(editions, CUT)
    actual = fact.build(editions, planned['in_force'], None, CUT, performed)
    listed = files._with_control({'contract_id': CONTRACT, 'documents': documents,
                                  'plan': planned, 'fact': actual}, None, CUT)
    assert (editions, documents, performed) == inputs
    cached = {'ok': True, 'pending': False, **listed}
    cached['rds_comparison'] = rds.build(cached)
    if bind:
        cached['comparison_export'] = export.bind_snapshot(PROJECT, CUT, CONTRACT, cached,
            {'contract': 'Т-1', 'contractor': 'Учебный подрядчик'})
    return cached


def workbook(cached, *, full=False):
    if full:
        cached = copy.deepcopy(cached)
        schedule = next(document['schedule'] for document in cached['documents'] if document.get('schedule'))
        cached['gpr'] = {'source': {'sha256': 'b' * 64, 'edition': 'Учебная'},
                         'schedule': schedule, 'overlays': {}, 'cut': CUT,
                         'workforce': {'available': False, 'reason': 'Ресурсный план не загружен.'}}
        meta = {'project': PROJECT, 'cut': CUT, 'contract_id': CONTRACT,
                'label': {'contract': 'Т-1', 'contractor': 'Учебный подрядчик'}}
        raw = gpr_export.workbook(meta, cached)
    else:
        table = cached['rds_comparison']
        raw = export.workbook(cached['comparison_export'], table, table['rows'])
    return load_workbook(io.BytesIO(raw), data_only=True)


def test_unreported_readable_loaded_act_is_zero_in_report_but_physical_unknown_stays_intact():
    cached = card()
    before = copy.deepcopy(cached)
    known, missing = cached['rds_comparison']['rows']
    assert known['fact_quantity'] == 6 and known['fact'] == 300
    assert missing['fact_quantity'] is None and missing['fact'] is None
    assert missing['physical_audit']['state'] == 'source_missing'
    view = rds.reporting_row(missing)
    assert [view[key] for key in ('fact_quantity', 'fact_quantity_ratio', 'quantity_deviation',
                                   'fact', 'deviation')] == [0, 0, -5, 0, -500]
    assert missing['ks_reporting']['physical_quantity_confirmed'] is False
    assert view['forecast_finish'] is None
    assert 'не подтверждаются' in view['comments']['fact_quantity']
    assert cached == before


@pytest.mark.parametrize('full', [False, True])
def test_native_workbook_writes_zero_and_negative_cached_deviations(full):
    cached = card()
    before = copy.deepcopy(cached)
    book = workbook(cached, full=full)
    sheet = book['Выполнение'] if full else book.active
    assert [sheet.cell(8, column).value for column in (6, 7, 8, 9, 10, 11, 12, 13)] == [
        5, .5, 0, 0, -5, 500, 0, -500]
    assert 'КС' in sheet['H6'].value and 'КС' in sheet['L6'].value
    assert sheet['H8'].data_type == 'n' and sheet['J8'].number_format.startswith('#,##0.')
    assert 'физический ноль' in sheet['H6'].comment.text
    assert all(cell.data_type != 'e' for page in book for row in page for cell in row)
    if full:
        assert book.sheetnames == ['ГПР', 'Выполнение', 'Численность подрядчика']
        assert all(page.freeze_panes is None for page in book)
    assert cached == before


def test_unknown_schedule_does_not_get_a_negative_variance_against_an_invented_plan():
    view = rds.reporting_row(card(dated=False)['rds_comparison']['rows'][1])
    assert view['fact_quantity'] == view['fact'] == 0
    assert view['plan_quantity'] is view['planned'] is None
    assert view['quantity_deviation'] is view['deviation'] is None


@pytest.mark.parametrize('kind', ['no_source', 'unread_act', 'partial_row', 'undated_act', 'missing_quantity'])
def test_missing_or_unreadable_loaded_source_does_not_become_a_reporting_zero(kind):
    original = native_card()
    position = original['documents'][0]['estimates'][0]['positions'][0]
    records = [record(position)]
    change = None
    if kind == 'no_source':
        records = []
    elif kind == 'unread_act':
        extra = record(position, sha='e', number='2')
        extra['act']['positions'] = []
        records.append(extra)
    elif kind == 'undated_act':
        extra = record(position, sha='e', number='2')
        extra['act'].update(date=None, start=None, finish=None)
        records.append(extra)
    elif kind == 'partial_row':
        records[0]['warnings'] = ['В акте не прочитана строка с единицей, но без количества.']
    else:
        def change(performed):
            performed['positions'][0]['parts'][0].update(quantity=None, quantity_material=None)
    cached = card(records=records, performed_change=change)
    row = cached['rds_comparison']['rows'][1]
    assert 'ks_reporting' not in row and rds.reporting_row(row)['fact_quantity'] is None
    assert workbook(cached).active['H8'].value is None


def test_unit_conflict_stays_unknown_but_unrelated_extra_act_does_not_hide_other_absence():
    original = native_card()
    first, second = original['documents'][0]['estimates'][0]['positions']
    wrong = record({**second, 'unit': 'шт'}, sha='e', number='2')
    conflicting = card(records=[record(first), wrong])['rds_comparison']['rows'][1]
    assert 'ks_reporting' not in conflicting and conflicting['fact_quantity'] is None
    outside = record({**first, 'number': '99', 'name': 'Отдельная дополнительная работа'}, sha='e', number='2')
    absent = card(records=[record(first), outside])['rds_comparison']['rows'][1]
    assert rds.reporting_row(absent)['fact_quantity'] == 0


@pytest.mark.parametrize('basis', ['work', 'material'])
def test_positive_delivery_with_zero_or_unreported_installation_keeps_its_native_cash(basis):
    first, second = native_card()['documents'][0]['estimates'][0]['positions']
    supplied = record(second, sha='e', number='2', quantity=0)
    supplied['act']['positions'][0].update(quantity=0 if basis == 'work' else 7,
        quantity_basis=basis, quantity_material=7,
        unit_price={'work': 60, 'material': 40, 'total': 100},
        amount={'work': 0, 'material': 280, 'total': 280})
    supplied['act']['total'] = 280
    def price(positions):
        positions[1].update(unit_price={'work': 60, 'material': 40, 'total': 100},
                            amount={'work': 600, 'material': 400, 'total': 1000})
    cached = card(records=[record(first), supplied], positions_change=price)
    row = cached['rds_comparison']['rows'][1]
    assert 'ks_reporting' not in row
    assert rds.reporting_row(row)['fact_quantity'] == (0 if basis == 'work' else None)
    assert rds.reporting_row(row)['fact'] == 280
    assert cached['rds_comparison']['rows'][0]['fact_quantity'] == 6


def test_real_parent_with_quantity_and_children_is_not_an_unreported_leaf():
    def parent(positions):
        positions[1]['number'] = '3'
    row = card(positions_change=parent)['rds_comparison']['rows'][1]
    assert row['contract_quantity'] == 10 and row['unit'] == 'м2'
    assert 'ks_reporting' not in row and row['fact_quantity'] is None


@pytest.mark.parametrize('value', [None, True, float('inf'), float('nan')])
def test_nonpositive_or_nonfinite_contract_base_is_not_a_reporting_zero(value):
    def base(positions):
        positions[1]['quantity'] = value
    cached = card(positions_change=base, bind=False)
    row = cached['rds_comparison']['rows'][1]
    assert 'ks_reporting' not in row and rds.reporting_row(row)['fact_quantity'] is None
    if type(value) is float:
        with pytest.raises(ValueError, match='Out of range'):
            export.bind_snapshot(PROJECT, CUT, CONTRACT, cached, {})


def test_only_future_loaded_acts_do_not_import_future_work_or_money_on_the_cut():
    position = native_card()['documents'][0]['estimates'][0]['positions'][0]
    cached = card(records=[record(position, day='2026-03-20')])
    assert all(row['fact_quantity'] is None and row['fact'] is None
               and 'ks_reporting' not in row for row in cached['rds_comparison']['rows'])


@pytest.mark.parametrize('workers,itr', [(8, 1), (0, None)])
def test_three_sheet_book_preserves_contract_plan_fact_and_separate_company_history(workers, itr):
    cached = card()
    schedule = next(document['schedule'] for document in cached['documents'] if document.get('schedule'))
    personnel = {'available': True, 'contract': 'Т-1', 'contractor': 'Учебный подрядчик',
        'rows': [{'date': CUT, 'workers_plan': 10, 'workers_fact': workers, 'workers_delta': workers-10,
                  'itr_plan': 2, 'itr_fact': itr, 'itr_delta': itr-2 if itr is not None else None, 'reasons': [],
                  'candidates': [], 'sources': []}],
        'company_rows': [{'date': CUT, 'workers': 20, 'itr': 3, 'candidates': [],
                          'reason': 'Общая бригада; по договорам не распределена.'}]}
    cached['gpr'] = {'source': {'sha256': 'b'*64, 'edition': 'Учебная'},
                     'schedule': schedule, 'overlays': {}, 'cut': CUT, 'workforce': personnel}
    snapshot = copy.deepcopy(cached)
    raw = gpr_export.workbook({'project': PROJECT, 'cut': CUT, 'contract_id': CONTRACT,
        'label': {'contract': 'Т-1'}}, cached)
    book = load_workbook(io.BytesIO(raw), data_only=True)
    assert book.sheetnames == ['ГПР', 'Выполнение', 'Численность подрядчика']
    sheet = book['Численность подрядчика']
    assert [sheet.cell(6, c).value for c in range(2, 8)] == [10, workers, workers-10, 2, itr, itr-2 if itr is not None else None]
    company = next(row for row in sheet.iter_rows(min_row=7)
                   if row[2].value == 20 and row[5].value == 3)
    assert [company[c-1].value for c in (2, 4, 5, 7)] == [None, None, None, None]
    assert 'без распределения' in '\n'.join(str(c.value) for row in sheet for c in row)
    assert 'contractor_unallocated' in company[7].comment.text
    assert cached == snapshot


def test_old_full_workbook_binding_is_rejected_after_three_sheet_schema_change(monkeypatch):
    cached = card()
    schedule = next(document['schedule'] for document in cached['documents'] if document.get('schedule'))
    cached['gpr'] = {'source': {'sha256': 'b'*64, 'edition': 'Учебная'}, 'schedule': schedule}
    with monkeypatch.context() as old:
        old.setattr(gpr_export, 'SCHEMA', 'contract-gpr-performance-xlsx-v11')
        cached['gpr_export'] = gpr_export.bind_snapshot(PROJECT, CUT, CONTRACT, cached, {})
    meta = cached['gpr_export']
    with pytest.raises(export.ExportProblem, match='Версия ГПР изменилась'):
        gpr_export.select_snapshot(cached, PROJECT, CUT, CONTRACT, meta['revision'])


def act_rows(rows):
    act = {'positions': [], 'warnings': [], 'unread_positions': []}
    state = {'section': None, 'group': None, 'table_total': None, 'heading': None}
    columns = {'order': 0, 'number': 1, 'name': [2], 'unit': 3,
               'work': 4, 'material': None, 'money': [5, 6]}
    documents._act_rows(rows, columns, 1, act, state)
    documents._settle_heading(act, state)
    return act


def test_zero_cost_heading_needs_following_hierarchical_child_proof():
    heading = ['10', '2', 'Комплекс вспомогательных работ', '', '', '', '0.00']
    child = ['11', '2.1', 'Работа', 'м2', '3', '50', '150']
    parsed = act_rows([heading, child])
    assert len(parsed['positions']) == 1 and parsed['positions'][0]['number'] == '2.1'
    assert parsed['positions'][0]['group'] is None
    assert parsed['warnings'] == parsed['unread_positions'] == []
    unknown = act_rows([heading, [*child[:1], '3', *child[2:]]])
    assert len(unknown['unread_positions']) == 1
    assert unknown['unread_positions'][0]['number'] == '2'
    assert 'не распознана' in unknown['warnings'][0]


def test_partially_unread_leaf_blocks_its_candidate_but_not_an_unrelated_absence():
    original = native_card()
    first = original['documents'][0]['estimates'][0]['positions'][0]
    loaded = record(first)
    missing = act_rows([['2', '3.2', 'Работа с нулевым фактом', 'м2', '', '100', '0']])
    loaded['act']['unread_positions'] = missing['unread_positions']
    loaded['warnings'] = missing['warnings']
    blocked = card(records=[loaded])['rds_comparison']['rows'][1]
    assert 'ks_reporting' not in blocked and blocked['fact_quantity'] is None
    missing = act_rows([['2', '99', 'Отдельная дополнительная работа', 'м2', '', '100', '0']])
    loaded['act']['unread_positions'] = missing['unread_positions']
    loaded['warnings'] = missing['warnings']
    unrelated = card(records=[loaded])['rds_comparison']['rows'][1]
    assert rds.reporting_row(unrelated)['fact_quantity'] == 0


def test_reader_revision_qualifies_old_retained_text_act_for_the_normal_refresh():
    old = {'reader': 17, 'act': {'positions': [{'number': '1'}]}, 'scan': None}
    assert documents.READER_VERSION > old['reader'] and files._requires_refresh(old)
    assert not files._requires_refresh({**old, 'reader': documents.READER_VERSION})
    assert not files._requires_refresh({**old, 'scan': {'confirmed_at': '2026-01-01'}})


def test_ordinary_local_reader_refresh_upgrades_retained17_once_without_changing_source(tmp_path, monkeypatch):
    from tests.test_contract_documents_are_read_from_their_tables import schedule_pdf
    raw = schedule_pdf()
    sha = hashlib.sha256(raw).hexdigest()
    folder = tmp_path / ('c'*64)
    folder.mkdir()
    (folder / (sha+'.pdf')).write_bytes(raw)
    retained = files._record(sha, 'Учебный график.pdf', raw, '2026-01-01T00:00:00Z')
    retained.update(reader=17, gpr_pending=True, removed_at='2026-02-01T00:00:00Z')
    files._json(folder / (sha+'.json'), retained)
    reader, calls = documents.read, []
    def read(content):
        calls.append(hashlib.sha256(content).hexdigest())
        return reader(content)
    monkeypatch.setattr(documents, 'read', read)
    fresh = files._current(folder, sha)
    assert fresh['reader'] == documents.READER_VERSION and calls == [sha]
    assert fresh['gpr_pending'] is True and fresh['removed_at'] == retained['removed_at']
    assert (folder / (sha+'.pdf')).read_bytes() == raw
    assert files._current(folder, sha) == fresh and calls == [sha]


def test_old_consumer_without_reporting_projection_fails_zero_expectation(monkeypatch):
    monkeypatch.setattr(export, 'reporting_row', lambda row: row)
    sheet = workbook(card()).active
    with pytest.raises(AssertionError):
        assert sheet['H8'].value == 0 and sheet['J8'].value == -5


def _current_guard():
    source = (Path(fact.__file__).parent / 'engine/monitor_cumulative.py').read_text()
    node = next(node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef)
                and node.name == '_monitor_contract_gpr_current')
    namespace = {}
    exec(compile(ast.Module(body=[node], type_ignores=[]), 'native_contract_current_guard', 'exec'), namespace)
    return namespace[node.name]


def _completed(store, ticket, owner, purpose):
    for _ in range(200):
        result = store.poll(ticket, owner, purpose)
        if not result.get('pending'):
            return result
        time.sleep(.01)
    raise AssertionError('Native local job did not complete')


def test_retained_v8_ticket_is_rejected_immutable_and_fresh_click_executes_current_producer(tmp_path):
    current = card()
    current['contract_calculation_revision'] = control.CALCULATION_REVISION
    old = copy.deepcopy(current)
    old['comparison_export']['schema'] = 'contract-rds-plan-fact-export-v8'
    old['rds_comparison'].pop('ks_reporting', None)
    for row in old['rds_comparison']['rows']:
        row.pop('ks_reporting', None)
    store, owner, purpose = jobs.Store(tmp_path), 'synthetic-owner', 'monitor-cumulative-v1:contracts'
    old_ticket, fresh_ticket = 'a' * 32, 'b' * 32
    old_params = {'operation': 'documents', 'click': old_ticket, 'contract_id': CONTRACT,
                  'contract_calculation_revision': control.CALCULATION_REVISION}
    store.start(owner, purpose, old_params, lambda: copy.deepcopy(old), old_ticket)
    retained = _completed(store, old_ticket, owner, purpose)
    frozen = copy.deepcopy(store._meta(old_ticket))
    calls = []
    def produce():
        calls.append(True)
        return card() | {'contract_calculation_revision': control.CALCULATION_REVISION}
    resumed = store.start(owner, purpose, old_params, produce, old_ticket)
    assert not calls and resumed['rds_comparison'] == retained['rds_comparison']
    with pytest.raises(jobs.JobProblem) as error:
        _current_guard()(resumed)
    assert error.value.status == 409 and error.value.code == 'source_changed'
    assert store._meta(old_ticket) == frozen
    fresh_params = {**old_params, 'click': fresh_ticket}
    store.start(owner, purpose, fresh_params, produce, fresh_ticket)
    refreshed = _completed(store, fresh_ticket, owner, purpose)
    assert calls == [True] and refreshed['comparison_export']['schema'] == export.SCHEMA
    _current_guard()(refreshed)
    assert rds.reporting_row(refreshed['rds_comparison']['rows'][1])['fact_quantity'] == 0
    assert store._meta(old_ticket) == frozen
