"""The management article covers every economic AHR row without changing bank money."""
import copy
import datetime as dt
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

import developaid_finance_allocations as bank
import developaid_finance_management as management
import developaid_monitor as monitor
import developaid_monitor_dashboard as dashboard
from test_finance_money_bridge import source
from test_finance_owner_allocations import canonical

DAY = '2026-11-10'
PROJECT = 'Synthetic management AHR'
ANNOTATIONS = {'management_allocation', 'management_article', 'management_article_origin',
               'management_policy_revision'}


def without_annotations(value):
    if isinstance(value, dict):
        return {key: without_annotations(item) for key, item in value.items() if key not in ANNOTATIONS}
    if isinstance(value, list):
        return [without_annotations(item) for item in value]
    return value


@pytest.fixture
def stored(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, '_SNAPSHOT_DIR', tmp_path / 'monitor')
    monkeypatch.setattr(management, '_now', lambda: dt.datetime(2026, 11, 10, 12, tzinfo=dt.timezone.utc))
    raw = source(future_bank='3.1')
    path = monitor._project_dir(PROJECT) / 'baseline' / 'finance.xlsx'
    path.parent.mkdir(parents=True)
    path.write_bytes(raw)
    return path, raw, management.view(PROJECT, DAY)


def apply(state, article='2.6', **overrides):
    data = {'project': PROJECT, 'source_sha256': state['source_sha256'], 'revision': state['revision'],
            'item_ids': [row['item_id'] for row in state['rows']], 'management_article': article,
            'note': 'Owner: all recognised economic AHR, fact and future plan, management article2.6.', 'cut': DAY}
    data.update(overrides)
    return management.apply(**data)


def test_all_ahr_fact_and_future_plan_tagged_bank_sources_and_every_money_field_preserved(stored):
    path, raw, state = stored
    original = dashboard._read_finance_baseline(path)
    before = canonical(original)
    assert state['rows'][0]['bank_source_chapters'] == ['', '2', '3']
    saved = apply(state)
    assert saved['revision'] == 1 and saved['decision']['scope'] == management.SCOPE
    qualified = management.qualify(PROJECT, original, DAY)
    assert without_annotations(qualified) == original
    assert original == dashboard._read_finance_baseline(path)
    assert path.read_bytes() == raw
    comp = qualified['budget_composition']
    for item in comp['admin_items']:
        assert item['management_article'] == '2.6'
        assert item['management_article_origin'] == 'owner_instruction'
        assert item['management_policy_revision'] == 1
        assert set(item['money_allocation']['by_chapter']) == {'', '2', '3'}
    after = canonical(qualified)
    for field in ('budget', 'paid_at_cut', 'bank_limit_total', 'remaining_bank_limit',
                  'available_bank_limit', 'calculated_additional', 'rhs', 'matches'):
        assert before['reconciliation'][field] == after['reconciliation'][field], field
    assert before['admin']['by_chapter'] == after['admin']['by_chapter']
    assert before['admin']['unallocated'] == after['admin']['unallocated']
    presentation = after['reconciliation']['admin_expenses']
    assert presentation['management_article'] == '2.6'
    assert 'Все экономические АХР: факт и план' in presentation['note']
    assert 'Банковские источники сохранены отдельно' in presentation['note']


def test_non_admin_rows_not_tagged_and_caller_copies_never_mutated(stored):
    path, _, state = stored
    apply(state)
    original = dashboard._read_finance_baseline(path)
    original['budget_composition']['budget_items'].append({'code': '2.2.1', 'total': 1, 'source': {}})
    frozen = copy.deepcopy(original)
    result = management.qualify(PROJECT, original, DAY)
    assert original == frozen
    assert 'management_article' not in result['budget_composition']['budget_items'][-1]
    result['budget_composition']['management_allocation']['management_article'] = 'changed'
    assert management.qualify(PROJECT, original, DAY)['budget_composition']['management_allocation']['management_article'] == '2.6'


@pytest.mark.parametrize('change', [{'source_sha256': 'b'*64}, {'revision': 1}, {'revision': True},
                                  {'management_article': '3.1'}, {'management_article': 2.6},
                                  {'item_ids': []}, {'item_ids': ['c'*64]}, {'note': ''}])
def test_invalid_stale_or_partial_policy_cannot_write_an_event(stored, change):
    path, raw, state = stored
    with pytest.raises(management.AllocationProblem):
        apply(state, **change)
    assert path.read_bytes() == raw
    assert not list(management._folder(PROJECT).glob('*.json'))


def test_exact_all_row_membership_is_required_not_a_selected_subset(stored, monkeypatch):
    _, _, state = stored
    candidate = management.candidates
    def two_rows(model):
        rows = candidate(model)
        return rows + [dict(rows[0], item_id='a'*64)]
    monkeypatch.setattr(management, 'candidates', two_rows)
    with pytest.raises(management.AllocationProblem, match='всем'):
        apply(state)


def test_historical_cut_revocation_and_replaced_source_do_not_inherit_policy(stored, monkeypatch):
    path, raw, state = stored
    applied = apply(state)
    model = dashboard._read_finance_baseline(path)
    assert management.qualify(PROJECT, model, '2026-11-09') == model
    monkeypatch.setattr(management, '_now', lambda: dt.datetime(2026, 11, 11, 12, tzinfo=dt.timezone.utc))
    apply(applied, '', cut='2026-11-11')
    assert management.qualify(PROJECT, model, '2026-11-11') == model
    assert management.qualify(PROJECT, model, DAY)['budget_composition']['management_allocation']['management_article'] == '2.6'
    path.write_bytes(source(coefficient=.4))
    changed = dashboard._read_finance_baseline(path)
    assert management.qualify(PROJECT, changed, '2026-11-11') == changed
    stale = management.qualify(PROJECT, model, DAY)
    assert 'management_allocation_problem' in stale
    assert stale['approved'] == model['approved']


def test_broken_history_never_falls_back_to_older_policy_or_loses_budget(stored):
    path, _, state = stored
    applied = apply(state)
    apply(applied, '')
    (management._folder(PROJECT) / '000000000002.json').write_text('[]')
    model = dashboard._read_finance_baseline(path)
    result = management.qualify(PROJECT, model, DAY)
    assert result['approved'] == model['approved']
    assert result['budget_composition'] == model['budget_composition']
    assert 'management_allocation_problem' in result
    with pytest.raises(management.AllocationProblem):
        management.view(PROJECT, DAY)


def test_only_one_writer_consumes_source_revision_and_source_race_is_fenced(stored):
    path, raw, state = stored
    def write(_):
        try:
            apply(state)
            return 'saved'
        except management.AllocationProblem:
            return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(write, range(2))) == ['conflict', 'saved']
    assert path.read_bytes() == raw
    assert len(list(management._folder(PROJECT).glob('*.json'))) == 1


def test_external_source_change_during_parse_is_refused_before_commit(stored, monkeypatch):
    path, raw, state = stored
    read = bank._read_model
    def replace_after_parse(data):
        model = read(data)
        path.write_bytes(raw + b' changed')
        return model
    monkeypatch.setattr(bank, '_read_model', replace_after_parse)
    with pytest.raises(management.AllocationProblem, match='изменилась'):
        apply(state)
    assert not list(management._folder(PROJECT).glob('*.json'))


def test_audit_has_only_policy_provenance_no_amount_override(stored):
    _, _, state = stored
    apply(state)
    event = json.loads(next(management._folder(PROJECT).glob('*.json')).read_text())
    assert event['scope'] == management.SCOPE and event['basis'] == 'owner_instruction'
    assert event['source_sha256'] == state['source_sha256']
    assert set(event['item_ids']) == {row['item_id'] for row in state['rows']}
    assert not {'amount', 'fact', 'plan', 'total', 'bank_code'} & set(event)


@pytest.mark.parametrize('width', [390,1440])
def test_one_management_article_is_visible_without_relabeling_bank_rows(stored, width):
    from pathlib import Path
    from test_monitor_cumulative_controls import browser_page
    import developaid_management_report as report
    path, _, state = stored
    apply(state)
    own = canonical(management.qualify(PROJECT, dashboard._read_finance_baseline(path), DAY))
    data = {'known':True,'own_money':own,'reconciliation':own['reconciliation']}
    with browser_page(width) as (page,responses,errors):
        page.evaluate('''f=>{currentView={dashboard:{funding:f}};renderDash(currentView);selectMonitorTab('money');}''',data)
        detail = page.locator('.funding-admin-breakdown')
        assert detail.is_visible()
        assert 'управленческая статья 2.6' in detail.locator('summary').inner_text()
        detail.locator('summary').click()
        assert 'Статьи главы 3' in detail.inner_text()
        assert 'Банковская статья не уточнена' in detail.inner_text()
        assert 'Все экономические АХР: факт и план' in detail.inner_text()
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        assert not errors
        out=Path('/tmp/plato-ahr-completion/management-surfaces');out.mkdir(parents=True,exist_ok=True)
        detail.screenshot(path=str(out/f'management-{width}.png'))
    html = report._funding_html({'kind':'week','funding':{'state':'ok','limit':data,'rss':None,
        'draws':dict.fromkeys(('period','month','total')),'interest':dict.fromkeys(('period','month','total'))}})
    assert 'управленческая статья 2.6' in html
    assert 'Статьи главы 3' in html and 'Банковская статья не уточнена' in html
    assert 'Все экономические АХР: факт и план' in html
