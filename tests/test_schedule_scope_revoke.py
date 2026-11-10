"""A new unbound volume of a confirmed work withdraws its full-scope mark (owner decision 4 А)."""
import datetime as dt
import json

import pytest

import developaid_schedule_gpr_physical as physical
from test_schedule_physical import item
from test_schedule_links_carry import site, save, journal, PROJECT, OLD_DAY, TODAY  # noqa: F401

OLD_ID, NEW_ID = '2026-11-06-' + 'b' * 64, TODAY + '-' + 'c' * 64


def ledger(rows, contract='Д-1', year=2026):
    return {'period_year': year, 'customer': 'ООО «Учебный заказчик»', 'contractor': 'Учебный подрядчик',
            'contract': contract, 'contract_date': '2025-01-01', 'items': rows}


def work(name, position, **changes):
    return item(name=name, position=position, **changes)


def archive(sid, ledgers):
    return {'snapshot_id': sid, 'ledgers': ledgers}


def config():
    return {'tasks': [{'task_id': '1', 'mode': 'quantities', 'scope_confirmed': True, 'actual_finish': ''},
                      {'task_id': '2', 'mode': 'plan_duration', 'scope_confirmed': True, 'actual_finish': ''}],
            'components': [{'task_id': '1', 'component_id': 'Монтаж', 'item_ids': ['0:0']}],
            'note': 'Проверены работа, участок и полный состав.'}


def put(site, *snapshots):
    store = site[1]
    for snap in snapshots:
        store[snap['snapshot_id']] = snap
    store['current'] = snapshots[-1]


def confirmed(state):
    return {t['task_id']: t['scope_confirmed'] for t in state['configuration']['tasks']}


def test_a_volume_visible_at_confirmation_keeps_the_mark(site):
    old = archive(OLD_ID, [ledger([work('Монтаж', '1'), work('Кладка стен', '2')])])
    put(site, old)
    save(OLD_DAY, config())
    # A fresh row of another contract does not make the old one new.
    new = archive(NEW_ID, [ledger([work('Монтаж', '1', done=70), work('Кладка стен', '2')]),
                           ledger([work('Кровля', '1')], contract='Д-2')])
    put(site, old, new)
    state = physical.catalog(PROJECT, TODAY)
    assert state['binding_projected'] and state['binding_scope_revoked'] == []
    assert confirmed(state) == {'1': True, '2': True}
    assert state['model']['tasks'][0]['progress'] is not None


@pytest.mark.parametrize('extra,named', [
    # Another work of a contract already bound to the confirmed work.
    (lambda: [ledger([work('Монтаж', '1'), work('Кладка стен', '2')])], 'Кладка стен'),
    # The next year of the bound work itself.
    (lambda: [ledger([work('Монтаж', '1')]), ledger([work('Монтаж', '1', year=2027)], year=2027)], 'Монтаж'),
    # Another contract whose work the review proposes for the confirmed one.
    (lambda: [ledger([work('Монтаж', '1')]), ledger([work('Фасад корпуса', '1')], contract='Д-2')], 'Фасад корпуса'),
])
def test_a_new_related_volume_withdraws_the_mark_without_writing(site, extra, named):
    old = archive(OLD_ID, [ledger([work('Монтаж', '1')])])
    put(site, old)
    save(OLD_DAY, config())
    before = journal(site)
    put(site, old, archive(NEW_ID, extra()))
    state = physical.catalog(PROJECT, TODAY)
    assert confirmed(state) == {'1': False, '2': True}
    revoked, = state['binding_scope_revoked']
    assert revoked['task_id'] == '1' and revoked['name'] == 'Фасад корпуса'
    assert named in [w['name'] for w in revoked['works']]
    assert 'появились непривязанные объёмы' in revoked['reason']
    task = state['model']['tasks'][0]
    assert task['progress'] is None and task['reason'] == revoked['reason']
    built = physical.build(PROJECT, TODAY)
    assert built['binding_scope_revoked'] == state['binding_scope_revoked']
    assert built['tasks'][0]['forecast_finish'] is None and built['tasks'][0]['reason'] == revoked['reason']
    assert journal(site) == before


def test_an_unrelated_new_volume_keeps_the_mark(site):
    old = archive(OLD_ID, [ledger([work('Монтаж', '1')])])
    put(site, old)
    save(OLD_DAY, config())
    # The other contract's work matches only the plan-duration work.
    put(site, old, archive(NEW_ID, [ledger([work('Монтаж', '1')]), ledger([work('Кровля', '1')], contract='Д-2')]))
    state = physical.catalog(PROJECT, TODAY)
    assert state['binding_scope_revoked'] == [] and confirmed(state) == {'1': True, '2': True}


def test_the_withdrawn_mark_is_saved_and_a_new_confirmation_holds(site, monkeypatch):
    old = archive(OLD_ID, [ledger([work('Монтаж', '1')])])
    put(site, old)
    save(OLD_DAY, config())
    put(site, old, archive(NEW_ID, [ledger([work('Монтаж', '1'), work('Кладка стен', '2')])]))
    monkeypatch.setattr(physical, '_now', lambda: dt.datetime(2026, 11, 9, 12, tzinfo=dt.timezone.utc))
    state = physical.catalog(PROJECT, TODAY)
    save(TODAY, state['configuration'])
    saved = physical.catalog(PROJECT, TODAY)
    assert saved['binding_scope_revoked'] == [] and confirmed(saved) == {'1': False, '2': True}
    again = dict(saved['configuration'], tasks=[dict(t, scope_confirmed=True) for t in saved['configuration']['tasks']])
    save(TODAY, again)
    assert confirmed(physical.catalog(PROJECT, TODAY)) == {'1': True, '2': True}


def test_an_unreadable_confirmation_archive_withdraws_the_mark_with_that_reason(site, monkeypatch):
    old = archive(OLD_ID, [ledger([work('Монтаж', '1'), work('Кладка стен', '2')])])
    put(site, old)
    save(OLD_DAY, config())
    put(site, old, archive(NEW_ID, [ledger([work('Монтаж', '1'), work('Кладка стен', '2')])]))
    real = physical._fresh_rows
    monkeypatch.setattr(physical, '_fresh_rows', lambda *a: None)
    state = physical.catalog(PROJECT, TODAY)
    assert confirmed(state)['1'] is False
    assert 'сейчас не читается' in state['binding_scope_revoked'][0]['reason']
    monkeypatch.setattr(physical, '_fresh_rows', real)
    assert confirmed(physical.catalog(PROJECT, TODAY))['1'] is True


def test_real_page_names_the_withdrawn_work_and_its_new_volumes(site):
    from test_monitor_cumulative_controls import browser_page
    old = archive(OLD_ID, [ledger([work('Монтаж', '1')])])
    put(site, old)
    save(OLD_DAY, config())
    put(site, old, archive(NEW_ID, [ledger([work('Монтаж', '1'), work('Кладка стен', '2')])]))
    state = json.loads(json.dumps(physical.catalog(PROJECT, TODAY), default=str, ensure_ascii=False))
    with browser_page(390) as (page, responses, errors):
        text = page.evaluate('s=>{renderPhysicalSchedule(s);return document.getElementById("physicalScheduleState").textContent}', state)
        assert 'Снята отметка полного состава у работ графика (1): «Фасад корпуса» — объёмы: Корпус 1, Кладка стен.' in text
        assert 'разберите эти объёмы и подтвердите состав заново' in text
        assert not errors


def test_a_work_with_a_new_volume_is_no_longer_a_completed_fact(site):
    old = archive(OLD_ID, [ledger([work('Монтаж', '1', done=100)])])
    put(site, old)
    save(OLD_DAY, config())
    same = archive(NEW_ID, [ledger([work('Монтаж', '1', done=100)])])
    put(site, old, same)
    facts = physical.catalog(PROJECT, TODAY)['model']['completed_facts']
    assert [f['source_task_id'] for f in facts['qualified_task_completions']] == ['1']
    put(site, old, archive(NEW_ID, [ledger([work('Монтаж', '1', done=100), work('Кладка стен', '2')])]))
    facts = physical.catalog(PROJECT, TODAY)['model']['completed_facts']
    assert facts['qualified_task_completions'] == []
