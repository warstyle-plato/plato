"""One contract can cover distinct buildings; uncertainty still needs review."""
import copy
import datetime as dt
import json

import pytest

import developaid_schedule_gpr_physical as physical
import developaid_schedule_physical_review as review
from test_schedule_links_carry import site, save, approve, book, journal, PROJECT, OLD_DAY, TODAY
from test_schedule_scope_revoke import archive, ledger, work, put, config, OLD_ID, NEW_ID


def changed_archive(site, scope):
    old = archive(OLD_ID, [ledger([work('Монтаж', '1', done=100)])])
    put(site, old)
    save(OLD_DAY, config())
    put(site, old, archive(NEW_ID, [ledger([work('Монтаж', '1', done=100),
        work('Кладка стен', '2', scope=scope)])]))


@pytest.mark.parametrize('width', [390, 1440])
@pytest.mark.parametrize('scope,revoked', [('Корп. 2', False), ('', True), ('Корпуса 1 и 2', True)])
def test_actual_page_and_completed_facts_use_the_same_corpus_exclusion(site, monkeypatch, width, scope, revoked):
    from playwright.sync_api import expect
    from test_monitor_cumulative_controls import browser_page
    changed_archive(site, scope)
    monkeypatch.setattr(physical, '_now', lambda: dt.datetime(2026, 11, 9, 12, tzinfo=dt.timezone.utc))
    before = journal(site)
    state = physical.catalog(PROJECT, TODAY)
    assert bool(state['binding_scope_revoked']) is revoked
    assert len(state['model']['completed_facts']['qualified_task_completions']) == int(not revoked)
    group = next(g for g in state['review']['groups'] if g['scope'] == scope)
    assert ('1' in group['known_disjoint_task_ids']) is not revoked
    with browser_page(width) as (page, responses, errors):
        page.evaluate('s=>renderPhysicalSchedule(s)', json.loads(json.dumps(state, default=str)))
        check = page.locator('.physical-scope-check')
        if revoked:
            expect(check).to_be_disabled()
            expect(check).not_to_be_checked()
            expect(page.locator('#physicalReviewScopes')).to_contain_text('Неразобранных объёмов по этим договорам и работам: 1.')
        else:
            expect(check).to_be_enabled()
            expect(check).to_be_checked()
            expect(page.locator('#physicalReviewScopes')).to_contain_text('Неразобранных объёмов по этим договорам и работам: 0.')
        assert not errors
    assert journal(site) == before


def test_many_confirmed_works_share_one_review_pass_and_its_full_universe_proof(site, monkeypatch):
    rows = [(i, 'Учебная работа %d' % i) for i in range(1, 7)]
    approve(book(rows=rows))
    old_rows = [work('Монтаж %d' % i, str(i)) for i in range(6)]
    old = archive(OLD_ID, [ledger(old_rows)])
    put(site, old)
    configuration = {'tasks': [{'task_id': str(i), 'mode': 'quantities', 'scope_confirmed': True,
        'actual_finish': ''} for i in range(1, 7)],
        'components': [{'task_id': str(i), 'component_id': 'Объём %d' % i,
            'item_ids': ['0:%d' % (i-1)]} for i in range(1, 7)], 'note': 'Проверены шесть составов.'}
    monkeypatch.setattr(physical, '_now', lambda: dt.datetime(2026, 11, 9, 8, tzinfo=dt.timezone.utc))
    save(TODAY, configuration)
    put(site, old, archive(NEW_ID, [ledger(copy.deepcopy(old_rows) + [work('Кладка стен', '7')])]))
    calls, proofs = [], []
    original_build, original_component = review.build, review.quantities._component
    def counted_build(*args, **kwargs):
        calls.append(True)
        return original_build(*args, **kwargs)
    def counted_component(*args, **kwargs):
        if '_duplicates' in kwargs:
            proofs.append(kwargs['_duplicates'])
        return original_component(*args, **kwargs)
    monkeypatch.setattr(review, 'build', counted_build)
    monkeypatch.setattr(review.quantities, '_component', counted_component)
    before = journal(site)
    state = physical.build(PROJECT, TODAY)
    assert len(state['binding_scope_revoked']) == 6
    assert len(calls) == 2  # Main view and archived completion evidence, never per task.
    assert len(proofs) == 14  # Seven groups in each of those passes.
    assert proofs[0] is proofs[6] and proofs[7] is proofs[13]
    assert proofs[0] is not proofs[7]
    assert journal(site) == before


@pytest.mark.parametrize('change', ['proved', 'forged', 'detached'])
def test_shared_review_proof_has_the_same_result_as_full_per_component_checks(monkeypatch, change):
    import developaid_cumulative_progress as progress
    from test_gpr_proven_duplicate_membership import sources
    from test_schedule_physical_review import TASKS, EMPTY
    _, source = sources()
    rows = source['ledgers'][0]['items']
    if change == 'forged':
        next(row for row in rows if row['source']['row'] == 10)['is_duplicate'] = True
    elif change == 'detached':
        source['ledgers'][0]['items'] = [row for row in rows if row['source']['row'] != 10]
    items = physical.quantities._items(source)
    views = progress.quantity_views(source, '2026-11-06')
    original = copy.deepcopy(source)
    shared = review.build(items, TASKS, EMPTY, '2026-11-06', snapshot=source, views=views)
    component = physical.quantities._component
    def full_proof(*args, **kwargs):
        kwargs.pop('_duplicates', None)
        return component(*args, **kwargs)
    monkeypatch.setattr(review.quantities, '_component', full_proof)
    uncached = review.build(items, TASKS, EMPTY, '2026-11-06', snapshot=source, views=views)
    assert shared == uncached
    assert source == original
    if change == 'proved':
        assert shared['excluded_duplicate_rows'] == 2
    else:
        assert any(not group['can_bind'] for group in shared['groups'])
