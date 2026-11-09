"""GPR filters verified source copies before any scope/component partition."""
from __future__ import annotations

import copy
import datetime as dt
import io
import hashlib

import openpyxl
import pytest

import developaid_cumulative_progress as progress
import developaid_gpr_cumulative_matching as matching
import developaid_monitor as monitor
import developaid_monitor_ledgers as ledgers
import developaid_schedule_gpr_physical as physical
from test_cumulative_proven_duplicates import duplicate_book
from test_ledger_merged_cost_fields import add_caches
from test_monitor_cumulative_ledgers import archive
from test_gpr_cumulative_matching import source, task

CUT = '2026-11-06'
PROJECT = 'Учебные доказанные копии'


def sources():
    wb = openpyxl.load_workbook(io.BytesIO(duplicate_book()))
    ws = wb.active
    ws.insert_rows(9)
    ws['B9'], ws['C9'] = '1', 'Устройство монолитных железобетонных конструкций надземной части'
    for ri in (10, 12):
        ws.cell(ri, 3, 'Устройство монолитных железобетонных вертикальных конструкций 3-го этажа Корпуса 4')
    ws['G14'], ws['O14'] = '=SUM(G10:G11)', '=SUM(O10:O11)'
    stream = io.BytesIO(); wb.save(stream)
    data = add_caches(stream.getvalue(), {'G14': 1020, 'O14': 400})
    raw = archive([('Учебные копии.xlsx', data)])
    snap = ledgers.parse_archive(raw)
    digest = hashlib.sha256(raw).hexdigest()
    snap.update(taken_at=CUT, snapshot_id=CUT+'-'+digest, sha256=digest)
    plan = source(task('vertical', corpus=4, floor=3),
                  task('package', corpus=4, name='Монолит надземной части', source_format='corpus-gpr-v1'))
    return plan, snap


@pytest.fixture(autouse=True)
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, '_SNAPSHOT_DIR', tmp_path)
    monkeypatch.setattr(physical, '_now', lambda: dt.datetime(2026, 11, 6, 12, tzinfo=dt.timezone.utc))


def ids_by_row(snap):
    return {item['source']['row']: f'{li}:{ii}' for li, ledger in enumerate(snap['ledgers'])
            for ii, item in enumerate(ledger['items'])}


def view(plan, snap, monkeypatch):
    monkeypatch.setattr(physical, '_source', lambda *args: copy.deepcopy(plan))
    monkeypatch.setattr(physical, '_snapshot', lambda *args: copy.deepcopy(snap))
    return physical.catalog(PROJECT, CUT)


def test_auto_binding_and_covered_subtree_share_one_full_source_membership(monkeypatch):
    plan, snap = sources()
    before = copy.deepcopy(snap)
    ids = ids_by_row(snap)
    assert set(ids) == {10, 11, 12, 13}
    assert sum(item.get('is_duplicate') is True for item in snap['ledgers'][0]['items']) == 2
    leaf = dict(plan, tasks={'vertical': plan['tasks']['vertical']})
    auto = matching.suggest(leaf, snap, CUT)
    assert auto['bindings']['vertical']['item_ids'] == [ids[10]]
    assert auto['bindings']['vertical']['metric']['ratio'] == .4
    covered, = matching.covered_subtrees(plan, snap, CUT)
    assert covered['item_ids'] == [ids[10], ids[11]]
    assert not covered['unverified_duplicate_item_ids']
    assert (snap == before)  # all source IDs and proof remain intact
    catalog = view(leaf, snap, monkeypatch)
    assert {item['item_id'] for item in catalog['items']} == set(ids.values())
    assert sum(item.get('is_duplicate') is True for item in catalog['items']) == 2
    assert len(ledgers.aggregation_members(catalog['items'], include_groups=True)) == 2
    repeated = matching.suggest_catalog(catalog, CUT)
    assert repeated['bindings']['vertical']['item_ids'] == [ids[10]]
    assert repeated['bindings']['vertical']['metric']['ratio'] == .4
    assert all(item.get('position_key') is None for key, item in progress.quantity_views(snap, CUT).items()
               if key in (ids[12], ids[13]))


@pytest.mark.parametrize('change', ['proof', 'forged_flag', 'detached'])
def test_unverified_flags_neither_hide_rows_nor_authorize_an_auto_binding(change, monkeypatch):
    plan, snap = sources()
    items = snap['ledgers'][0]['items']
    if change == 'proof':
        duplicate = next(item for item in items if item['source']['row'] == 12)
        duplicate['duplicate_proof']['completed'][0]['formula'] = '=SUM(O10:O12)'
    elif change == 'forged_flag':
        next(item for item in items if item['source']['row'] == 10)['is_duplicate'] = True
    else:
        snap['ledgers'][0]['items'] = [item for item in items if item['source']['row'] != 10]
    count = len(snap['ledgers'][0]['items'])
    catalog = view(plan, snap, monkeypatch)
    assert len(catalog['items']) == count
    leaf = dict(plan, tasks={'vertical': plan['tasks']['vertical']})
    assert matching.suggest(leaf, snap, CUT)['bindings'] == {}
    leaf_catalog = dict(catalog, tasks=[plan['tasks']['vertical']])
    assert matching.suggest_catalog(leaf_catalog, CUT)['bindings'] == {}
    group, = catalog['model']['covered_source_groups']
    assert group['model']['progress'] is None and group['model']['requires_reconciliation']
    assert group['unverified_duplicate_item_ids']


def test_a_detached_catalog_copy_cannot_be_reclassified_as_an_independent_work(monkeypatch):
    plan, snap = sources()
    catalog = view(plan, snap, monkeypatch)
    item = next(item for item in catalog['items'] if item['source']['row'] == 12)
    assert item['duplicate_proof'] and item['duplicate_view_fingerprint'] and item['duplicate_marker_present']
    catalog['items'] = [item]
    catalog['tasks'] = [plan['tasks']['vertical']]
    got = matching.suggest_catalog(catalog, CUT)
    assert got['bindings'] == {} and got['configuration']['tasks'] == []
    assert got['candidates'][0]['reason'] == 'unverified_duplicate_marker'


def test_saved_manual_copy_selection_is_retained_for_review_not_reassigned():
    plan, snap = sources()
    ids = ids_by_row(snap)
    config = {'tasks': [{'task_id': 'vertical', 'mode': 'quantities', 'scope_confirmed': True, 'actual_finish': ''}],
              'components': [{'component_id': 'Сохранённый выбор', 'task_id': 'vertical', 'item_ids': [ids[12]]}],
              'note': 'Старая ручная связь.'}
    before = copy.deepcopy(config)
    state = physical._view_model(PROJECT, CUT, plan, snap, config)
    measured = next(task for task in state['tasks'] if task['task_id'] == 'vertical')
    assert measured['progress'] is None and not measured['known']
    assert measured['components'][0]['excluded_duplicate_item_ids'] == [ids[12]]
    assert measured['components'][0]['requires_reconciliation']
    assert config == before and not state['seeds'] and not state['actual_finishes']
    # If the source universe itself is incomplete, the flag still cannot turn
    # into an independent physical fraction merely because its original is absent.
    snap['ledgers'][0]['items'] = [next(item for item in snap['ledgers'][0]['items'] if item['source']['row'] == 12)]
    config['components'][0]['item_ids'] = ['0:0']
    state = physical._view_model(PROJECT, CUT, plan, snap, config)
    measured = next(task for task in state['tasks'] if task['task_id'] == 'vertical')
    assert measured['progress'] is None and measured['components'][0]['unverified_duplicate_item_ids'] == ['0:0']


@pytest.mark.parametrize('width', [390, 1440])
def test_saved_suspect_copy_keeps_its_id_and_an_explanation_in_the_real_page(monkeypatch, width):
    from playwright.sync_api import expect
    from test_monitor_cumulative_controls import browser_page
    plan, snap = sources()
    ids = ids_by_row(snap)
    duplicate = next(item for item in snap['ledgers'][0]['items'] if item['source']['row'] == 12)
    duplicate['duplicate_proof']['completed'][0]['formula'] = '=SUM(O10:O12)'
    configuration = {'tasks': [{'task_id': 'vertical', 'mode': 'quantities', 'scope_confirmed': True, 'actual_finish': ''}],
        'components': [{'component_id': 'Сохранённая связь', 'task_id': 'vertical', 'item_ids': [ids[12]]}], 'note': 'Проверить источник.'}
    state = view(plan, snap, monkeypatch)
    state['configuration'] = configuration
    state['model'] = physical._view_model(PROJECT, CUT, plan, snap, configuration)
    with browser_page(width) as (page, responses, errors):
        page.evaluate('(value)=>renderPhysicalSchedule(value)', state)
        expect(page.locator('#physicalBindings')).to_contain_text('Отметка о копии строки требует проверки')
        option = page.locator(f'#physicalItems option[value="{ids[12]}"]')
        expect(option).to_contain_text('Отметка о копии требует проверки')
        assert page.evaluate('physicalDraft.components[0].item_ids[0]') == ids[12]
        assert '0%' not in page.locator('#physicalBindings').inner_text()
        assert not errors


def test_proven_copies_do_not_break_canonical_projection_or_redirect_manual_copy_ids():
    _plan, snap = sources()
    ids = ids_by_row(snap)
    config = {'tasks': [{'task_id': 'vertical', 'mode': 'quantities', 'scope_confirmed': True, 'actual_finish': ''}],
              'components': [{'component_id': 'Старая связь', 'task_id': 'vertical', 'item_ids': [ids[10]]}], 'note': ''}
    assert progress.project_configuration(snap, copy.deepcopy(snap), config) == config
    copy_config = copy.deepcopy(config)
    copy_config['components'][0]['item_ids'] = [ids[12]]
    assert progress.project_configuration(snap, copy.deepcopy(snap), copy_config) is None
    changed = copy.deepcopy(snap)
    duplicate = next(item for item in changed['ledgers'][0]['items'] if item['source']['row'] == 12)
    duplicate['duplicate_proof']['completed'][0]['formula'] = '=SUM(O10:O12)'
    assert progress.project_configuration(snap, changed, config) is None
    assert progress.project_configuration(changed, snap, config) is None


def test_a_detached_or_forged_marker_cannot_supply_a_historical_quantity_point():
    _plan, snap = sources()
    ids = ids_by_row(snap)
    assert progress._observation(progress.quantity_views(snap, CUT)[ids[10]])['ratio'] == .4
    duplicate = next(item for item in snap['ledgers'][0]['items'] if item['source']['row'] == 12)
    snap['ledgers'][0]['items'] = [duplicate]
    view = progress.quantity_views(snap, CUT)['0:0']
    assert view['duplicate_marker_present'] and not view['is_duplicate']
    assert progress._observation(view) is None
