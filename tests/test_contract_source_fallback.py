"""Source priority, retained act totals and no mixing; synthetic data only."""
import copy

import pytest

import developaid_contract_acts as acts
import developaid_contract_act_dates as act_dates
import developaid_contract_fact as fact
import developaid_contract_files as files
import developaid_contract_control as control
import developaid_contract_plan as plan
from tests.test_contract_ks6a_primary_fact import EDITION, CUT, build, statement, uploaded
from tests.test_contract_ks2_positions_accumulate import _record as _position_record, WALLS


def _record(*args, **kwargs):
    record = _position_record(*args, **kwargs)
    record['act']['total'] = sum(p['amount']['total'] for p in record['act']['positions'])
    return record


@pytest.mark.parametrize('found', [None, fact.unavailable('Нечитаемый исходник'),
    {'works': 0, 'acts': [], 'items': [], 'unread': []},
    {'works': 0, 'acts': [], 'items': [], 'unread': [{'reason': 'Неизвестны даты'}]}])
def test_only_acts_are_used_when_no_statement_work_is_usable(found):
    performed = uploaded(1, 2)
    original = copy.deepcopy((found, performed))
    got = build(found, performed)
    assert got['source'] == 'ks2' and got['total'] == 20000
    assert got['lines'][0]['volumes'] == [{'unit': 'м2', 'quantity': 200}]
    assert not got['unread'] and not got['reconciliation']
    assert got['confirmation']['state'] == 'acts_only'
    measured = control.build(plan.build([EDITION], CUT), got, None, '', CUT)
    assert measured['total']['incomplete']
    assert measured['source'] == 'ks2' and measured['data_gaps']
    assert original == (found, performed)


def test_a_partly_readable_statement_does_not_take_ks2_for_its_unknown_work():
    found = statement()
    found['unread'] = [{'number': '1', 'name': 'Монтаж', 'unit': 'м2', 'reason': 'Нет даты', 'periods': []}]
    before, after = build(found), build(found, uploaded(1, 2))
    assert after['source'] == 'ks6a' and after['total'] is before['total'] is None
    assert after['lines'] == before['lines'] and after['unread'] == before['unread']


def test_uploading_a_statement_switches_source_instead_of_adding_to_acts():
    performed = uploaded(1, 2)
    only_acts = build(None, performed)
    with_statement = build(statement(), performed)
    assert only_acts['source'] == 'ks2' and only_acts['total'] == 20000
    assert with_statement['source'] == 'ks6a' and with_statement['total'] == 1500
    assert with_statement['reconciliation']['differs'] == 1


def test_an_explicit_zero_in_readable_statement_has_priority_over_acts():
    found = statement()
    found['acts'] = []
    got = build(found, uploaded(2))
    assert got['source'] == 'ks6a' and got['total'] == 0


def test_acts_without_a_plan_keep_document_totals_but_have_no_schedule_fact():
    performed = acts.accumulated([_record('a', '1', '2026-02-28', [(*WALLS, 5, 500)])], CUT)
    got = fact.build([], None, None, CUT, performed)
    assert got['source'] == 'ks2' and got['act_evidence']['total'] == 500
    assert got['total'] is None and got['lines'] == [] and got['note']
    measured = control.build(plan.build([], CUT), got, None, '', CUT)
    assert measured['total'] is None and measured['forecast'] is None
    assert measured['act_evidence'] == performed['evidence']


def test_document_totals_include_unread_acts_but_not_copies_replaced_or_future_acts():
    records = [_record('a', '1', '2026-01-31', [(*WALLS, 5, 500)]),
               _record('b', '1', '2026-01-31', [(*WALLS, 6, 600)], uploaded='2026-02-11'),
               _record('c', '2', '2026-02-28', [], uploaded='2026-03-01'),
               _record('e', '3', '2026-12-31', [(*WALLS, 8, 800)])]
    records[2]['act']['total'] = 200
    records[2]['warnings'] = ['Таблица не прочитана']
    records.append({**records[1], 'sha256': 'd'*64, 'filename': 'copy.pdf', 'uploaded_at': '2026-03-02'})
    before = copy.deepcopy(records)
    got = acts.accumulated(records, CUT)
    assert got['evidence']['count'] == 2 and got['evidence']['total'] == 800
    assert got['evidence']['known_total'] == 800 and got['evidence']['unread_count'] == 1
    assert {row['number'] for row in got['evidence']['acts']} == {'1', '2'}
    assert next(row for row in got['evidence']['acts'] if row['number'] == '2')['warnings'] == ['Таблица не прочитана']
    assert got['positions'][0]['quantity'] == 6 and got['later'] == 1
    assert records == before


def test_unknown_document_total_stays_unknown_while_known_subtotal_survives():
    records = [_record('a', '1', '2026-01-31', [(*WALLS, 5, 500)]),
               _record('b', '2', '2026-02-28', [(*WALLS, 6, 600)])]
    records[1]['act']['total'] = None
    evidence = acts.accumulated(records, CUT)['evidence']
    assert evidence['total'] is None and evidence['known_total'] == 500 and evidence['count'] == 2


def test_a_future_revision_and_its_copy_cannot_erase_the_act_on_an_earlier_cut():
    earlier = _record('a', '1', '2026-01-31', [(*WALLS, 5, 500)])
    later = _record('b', '1', '2026-02-28', [(*WALLS, 6, 600)])
    duplicate = {**later, 'sha256': 'c'*64, 'uploaded_at': '2026-03-02'}
    records = [earlier, later, duplicate]
    old = acts.accumulated(records, '2026-01-31')
    assert old['evidence']['total'] == 500 and old['positions'][0]['quantity'] == 5
    assert old['replaced'] == {} and old['later'] == 1
    current = acts.accumulated(records, '2026-02-28')
    assert current['evidence']['total'] == 600 and current['positions'][0]['quantity'] == 6
    assert 'a'*64 in current['replaced'] and current['later'] == 0


def test_future_revisions_do_not_move_named_statement_periods_out_of_the_cut():
    early = '2026-01-31'
    row = {'physical_items': [{'position': '1', 'name': 'Монтаж', 'unit': 'м2', 'plan_quantity': 100,
        'completed_quantity': None, 'reported_completed_quantity': 5, 'periods': [],
        'undated_periods': [{'label': 'КС-2 № 1', 'quantity': 5, 'amount': 500}]}]}
    records = [_record('a', '1', early, [('1', 'Монтаж', 'м2', 5, 500)]),
               _record('b', '1', '2026-02-28', [('1', 'Монтаж', 'м2', 6, 600)])]
    resolved = act_dates.resolve(fact.acts(row), records, early)
    performed = acts.accumulated(records, early)
    got = fact.build([EDITION], EDITION['sha256'], resolved, early, performed)
    assert resolved['act_dates'][0]['end'] == early
    assert got['source'] == 'ks6a' and got['total'] == 500
    assert performed['evidence']['total'] == 500


def test_future_summary_dates_cannot_change_an_earlier_named_statement_period():
    from tests.test_contract_fact_dates_ks6_periods_by_acts import _work, _period, _row
    row = _row(_work('1.1', 'Стены', _period('КС-2 № 1', 5, 500)),
               summary=[('1', '2026-01-31', 500), ('1', '2026-02-28', 600)])
    resolved = act_dates.resolve(fact.acts(row), [], '2026-01-31')
    assert resolved['act_dates'][0]['end'] == '2026-01-31'


def test_undated_and_future_only_acts_cannot_create_zero_fact():
    records = [_record('a', '1', None, [(*WALLS, 5, 500)], date=None),
               _record('b', '2', '2026-12-31', [(*WALLS, 6, 600)])]
    performed = acts.accumulated(records, CUT)
    got = build(None, performed)
    assert performed['evidence']['count'] == 0 and performed['evidence']['total'] is None
    assert got['total'] is None and got['source'] is None


def test_read_zero_act_is_a_known_zero_rather_than_absent_evidence():
    records = [_record('a', '1', '2026-01-31', [('1', 'Монтаж', 'м2', 0, 0)])]
    performed = acts.accumulated(records, CUT)
    got = build(None, performed)
    assert got['source'] == 'ks2' and got['total'] == 0 and not got['note']


def test_register_and_comparison_use_the_same_act_evidence(monkeypatch, tmp_path):
    import developaid_monitor as monitor
    from tests.test_contract_card_confirms_and_chooses_links import ROW
    from tests.test_contract_fact_dates_ks6_periods_by_acts import act_pdf
    monkeypatch.setattr(monitor, '_SNAPSHOT_DIR', tmp_path/'monitor')
    files.store('Учебный', ROW, 'synthetic.pdf', act_pdf())
    register = {'rows': [copy.deepcopy(ROW)]}
    listing = files.listing('Учебный', ROW['id'], CUT)
    registered = files.register_control('Учебный', register, CUT)['rows'][0]
    assert listing['fact']['act_evidence']['total'] == 4000
    assert listing['comparison']['act_evidence'] == registered['schedule_control']['act_evidence']
    assert registered['schedule_control']['source'] == 'ks2'
