"""Named KS periods keep native work/material columns without doubling archive versions."""
import copy

import pytest

from developaid_contract_detail_history import compose
from tests.test_contract_detail_history import source


def period(number, quantity=None, material_quantity=None, *, work=None, material=None):
    work = quantity*10 if work is None and quantity is not None else work
    material = material_quantity*100 if material is None and material_quantity is not None else material
    return {'label': f'КС-2 № {number}', 'quantity': quantity, 'material_quantity': material_quantity,
            'work_amount': work, 'material_amount': material,
            'amount': None if work is None or material is None else work+material,
            'amount_split': work is not None and material is not None,
            'amount_basis': 'with_vat', 'date_start': None, 'date_end': None,
            'source': {'filename': 'KS.xlsx', 'sheet': 'Работы', 'row': 9}}


def view(*periods, **changes):
    result = {'position': '1.1', 'name': 'Монтаж стены', 'scope': 'Этаж 2', 'unit': 'м2',
              'period_year': 2026, 'plan_quantity': 100, 'planned_amount': 11000,
              'planned_work_amount': 1000, 'planned_material_amount': 10000,
              'completed_quantity': None, 'completed_amount': None, 'material_quantity': None,
              'reported_completed_quantity': sum(p.get('quantity') or 0 for p in periods),
              'reported_completed_amount': sum(p.get('amount') or 0 for p in periods),
              'reported_material_quantity': sum(p.get('material_quantity') or 0 for p in periods),
              'periods': [], 'undated_periods': list(periods), 'warnings': [],
              'section_path': [{'position': '1', 'name': 'Корпус 1'}],
              'context_headings': ['Система А'],
              'source': {'filename': 'KS.xlsx', 'sheet': 'Работы', 'row': 9}}
    result.update(changes)
    return result


def only(sources):
    item, = compose(sources, '2026-12-31')['items']
    return item


def test_identical_named_acts_are_deduplicated_and_new_act_and_native_totals_survive():
    supplied = period(1, material_quantity=10, work=0)
    installed = period(2, quantity=2, material=0)
    new_work = period(3, quantity=1, material_quantity=1)
    old = source('2026-11-01', view(supplied, installed))
    new = source('2026-11-12', view(supplied, installed, new_work), sha='b')
    sources = [old, new]
    before = copy.deepcopy(sources)
    got = only(sources)
    assert sources == before
    assert [p['label'] for p in got['undated_periods']] == ['КС-2 № 1', 'КС-2 № 2', 'КС-2 № 3']
    assert sum(p['amount'] for p in got['undated_periods']) == 1130
    assert got['reported_completed_quantity'] == 3 and got['reported_material_quantity'] == 11
    assert got['reported_completed_amount'] == 1130
    assert got['detail_history_problems'] == ['undated']
    assert got['completed_quantity'] is None  # Act labels still do not invent dates.
    supply = got['undated_periods'][0]
    assert supply['quantity'] == 0 and supply['material_quantity'] == 10
    assert 'положительной цене' in supply['quantity_basis']
    assert len(supply['history_sources']) == 2
    assert supply['selected_source']['source_date'] == '2026-11-12'


def test_deduplicated_periods_can_be_dated_by_the_actual_act_headers():
    import developaid_contract_fact as fact
    import developaid_contract_act_dates as dates
    supplied = period(1, material_quantity=10, work=0)
    installed = period(2, quantity=2, material=0)
    got = only([source('2026-11-01', view(supplied, installed)),
                source('2026-11-12', view(supplied, installed), sha='b')])
    found = fact.acts({'physical_items': [got]})
    records = [{'sha256': str(number)*64, 'act': {'number': str(number), 'date': f'2026-0{number+1}-28',
        'start': f'2026-0{number+1}-01', 'finish': f'2026-0{number+1}-28', 'total': amount}}
               for number, amount in ((1, 1000), (2, 20))]
    resolved = dates.resolve(found, records)
    assert resolved['unread'] == [] and len(resolved['acts']) == 2
    supply = next(a for a in resolved['acts'] if a['label'] == 'КС-2 № 1')
    assert supply['quantity'] == 0 and supply['quantity_material'] == 10
    assert supply['amount_components'] == {'work': 0, 'material': 1000, 'total': 1000}
    import developaid_contract_schedule_links as links
    position = {'number': '1.1', 'name': 'Монтаж стены', 'unit': 'м2', 'quantity': 100,
                'unit_price': {'work': 10, 'material': 100, 'total': 110},
                'amount': {'work': 1000, 'material': 10000, 'total': 11000}}
    editions = [{'sha256': 'f'*64, 'title': 'Учебная РДС', 'date': '2026-01-01', 'start': None,
        'estimates': [{'scope': 'full', 'positions': [position], 'links': {'positions': [{
            'key': links.position_key(position), 'status': 'confirmed', 'lines': [{'code': '1', 'share': 1}]}]}}],
        'schedule': {'lines': [{'code': '1', 'parent': None, 'name': 'Стена',
                               'start': '2026-01-01', 'finish': '2026-12-31'}]}}]
    result = fact.build(editions, 'f'*64, resolved, '2026-12-31')
    assert result['source'] == 'ks6a' and result['review'] == []
    assert result['total'] == 1020
    assert result['lines'][0]['volumes'] == [{'unit': 'м2', 'quantity': 2}]
    assert result['lines'][0]['material_volumes'] == [{'unit': 'м2', 'quantity': 10}]


@pytest.mark.parametrize('change', ['quantity', 'material_quantity', 'work_amount', 'material_amount'])
def test_changed_act_content_is_a_conflict_and_is_never_silently_replaced(change):
    old_period = period(1, quantity=2, material_quantity=3)
    changed = copy.deepcopy(old_period)
    changed[change] += 1
    old = source('2026-11-01', view(old_period))
    new = source('2026-11-12', view(changed), sha='b')
    got = only([old, new])
    assert 'conflict' in got['detail_history_problems']
    assert got['reported_completed_quantity'] is None and got['reported_completed_amount'] is None
    assert len(got['undated_periods']) == 2 and len(got['history_sources']) == 2


def test_same_label_in_different_native_workbooks_is_not_deduplicated():
    first = view(period(1, quantity=2, material_quantity=3))
    other = copy.deepcopy(first)
    other['source']['filename'] = 'Другая книга.xlsx'
    got = only([source('2026-11-01', first), source('2026-11-12', other, sha='b')])
    assert len(got['undated_periods']) == 2 and 'overlap' in got['detail_history_problems']
    assert got['reported_completed_quantity'] is None


def test_different_years_and_different_positions_are_not_one_history():
    first = view(period(1, quantity=2, material_quantity=3))
    other_position = view(period(1, quantity=2, material_quantity=3), position='1.2')
    next_year = view(period(1, quantity=2, material_quantity=3), period_year=2027)
    sources = [source('2026-11-01', first, other_position),
               source('2026-11-12', next_year, sha='b', period_year=2027)]
    got = compose(sources, '2027-12-31')['items']
    assert len(got) == 3 and all(len(v['undated_periods']) == 1 for v in got)
    assert all(v['reported_completed_quantity'] == 2 for v in got)


def test_empty_placeholder_does_not_conflict_with_a_new_act():
    previous = view(period(1, quantity=2, material_quantity=3), period(2))
    latest = view(period(1, quantity=2, material_quantity=3), period(2, quantity=1, material_quantity=1))
    got = only([source('2026-11-01', previous), source('2026-11-12', latest, sha='b')])
    assert len(got['undated_periods']) == 2 and got['reported_completed_quantity'] == 3


def test_unreconciled_native_total_is_not_promoted_by_composition():
    wrong = view(period(1, quantity=2, material_quantity=3), reported_completed_quantity=9)
    got = only([source('2026-11-12', wrong)])
    assert got['reported_completed_quantity'] is None and 'incomplete' in got['detail_history_problems']


def test_non_act_labels_and_missing_work_cost_do_not_invent_zero_work():
    unidentified = period(1, material_quantity=3, work=0)
    unidentified['label'] = 'Период № 1'
    got = only([source('2026-11-12', view(unidentified))])
    assert got['reported_completed_quantity'] is None
    got = only([source('2026-11-12', view(period(1, material_quantity=3, work=0), planned_work_amount=None))])
    assert got['undated_periods'][0]['quantity'] is None and got['reported_completed_quantity'] is None


def test_empty_zero_observations_remain_known_zero_without_execution_dates():
    zero = view(period(1, work=0, material=0))
    got = only([source('2026-11-01', zero), source('2026-11-12', zero, sha='b')])
    assert got['detail_history_state'] == 'known' and got['completed_quantity'] == 0
    assert got['completed_amount'] == 0 and got['undated_periods'] == []


def test_repeated_named_period_inside_one_native_row_is_not_a_proven_version_duplicate():
    repeated = period(1, quantity=2, material_quantity=3)
    got = only([source('2026-11-12', view(repeated, repeated))])
    assert 'duplicate' in got['detail_history_problems'] and got['reported_completed_quantity'] is None
    assert len(got['undated_periods']) == 2


def test_full_act_numbers_keep_their_year_suffix_in_one_work_history():
    got = only([source('2026-11-12', view(period('1/2025', quantity=2, material_quantity=3),
                                        period('1/2026', quantity=1, material_quantity=1)))])
    assert len(got['undated_periods']) == 2 and got['reported_completed_quantity'] == 3


def test_changed_component_amounts_with_equal_combined_total_are_still_a_conflict():
    first = period(1, quantity=2, material_quantity=3)
    changed = dict(first, work_amount=first['work_amount']+5, material_amount=first['material_amount']-5)
    got = only([source('2026-11-01', view(first)), source('2026-11-12', view(changed), sha='b')])
    assert 'conflict' in got['detail_history_problems'] and got['reported_completed_amount'] is None


@pytest.mark.parametrize('heading', ['КС2-{}', 'КС-2-{}', ' кс 2 – 0{} '])
def test_compact_act_headings_survive_history_and_are_dated_once_by_summary(heading):
    import developaid_contract_act_dates as dates
    import developaid_contract_fact as fact

    movements = [dict(period(n, quantity=n, material=0), label=heading.format(n)) for n in (1, 2, 3)]
    raw = view(*movements)
    sources = [source('2026-11-01', raw), source('2026-11-12', raw, sha='b')]
    before = copy.deepcopy(sources)
    got = only(sources)
    assert sources == before
    assert got['detail_history_problems'] == ['undated']
    assert got['completed_quantity'] is None  # A number supplies no execution date.
    assert got['reported_completed_quantity'] == 6 and got['reported_completed_amount'] == 60
    assert len(got['undated_periods']) == 3
    summary = [{'number': str(n), 'date': f'2026-0{n+1}-28', 'amount': n*10} for n in (1, 2, 3)]
    found = fact.acts({'physical_items': [got], 'financial_sources': [{'acts': summary}]})
    assert found['period_amounts'] == {heading.format(n): n*10 for n in (1, 2, 3)}
    resolved = dates.resolve(found, [])
    assert resolved['unread'] == [] and len(resolved['acts']) == 3
    assert [(a['quantity'], a['end']) for a in resolved['acts']] == [
        (1, '2026-02-28'), (2, '2026-03-28'), (3, '2026-04-28')]
    assert all(a['start'] is None and a['dated_by'].startswith('Дата подписания акта')
               for a in resolved['acts'])
    assert all(a['preliminary'] is True for a in resolved['acts'])
    missing = dates.resolve(fact.acts({'physical_items': [got]}), [])
    assert missing['unread'] and not missing['acts']


@pytest.mark.parametrize('heading', ['КС2-1', 'КС-2-01'])
def test_compact_heading_does_not_hide_changed_execution_in_retained_imports(heading):
    first = dict(period(1, quantity=2, material=0), label=heading)
    changed = dict(first, quantity=3, amount=30, work_amount=30)
    got = only([source('2026-11-01', view(first)), source('2026-11-12', view(changed), sha='b')])
    assert 'conflict' in got['detail_history_problems']
    assert got['reported_completed_quantity'] is None and got['reported_completed_amount'] is None


@pytest.mark.parametrize('heading', ['КС2-1 от 01.02.2026', 'КС2-1/2026', 'КС2-1.02.2026',
                                     'Период КС2-1', 'КС2-1 и КС2-2', 'КС-2 от 01.02.2026'])
def test_compact_heading_recognizer_does_not_extract_an_act_from_dates_or_mentions(heading):
    import developaid_contract_act_dates as dates
    assert dates.compact_number(heading) is None
    assert dates.number(heading) is None


@pytest.mark.parametrize('statement,estimate', [('смен', 'смена'), ('штук', 'шт'),
                                               ('чел-час', 'человеко-час'),
                                               ('человеко-час', 'человеко- час'),
                                               ('чел - час', 'человеко-час')])
def test_grammatical_unit_variants_match_the_same_estimate_position(statement, estimate):
    import developaid_contract_fact as fact
    position = {'number': '1.1', 'name': 'Учебная работа', 'unit': estimate}
    work = dict(position, unit=statement)
    assert fact.match(work, [{'positions': [position]}]) == (0, 0, 'number')
    # These are names of the same unit, never a conversion between units.
    work['unit'] = 'маш-смена' if estimate == 'смена' else 'м2'
    assert isinstance(fact.match(work, [{'positions': [position]}]), str)


def test_spacing_at_a_hyphen_never_changes_unit_dimensions_or_confirms_a_schedule_link():
    from developaid_contract_detail_history import normalize_unit
    import developaid_contract_fact as fact
    units = ['м2', 'м3', 'шт', 'смена', 'маш-смена', 'человеко-час']
    assert len({normalize_unit(unit) for unit in units}) == len(units)
    for source in units:
        for target in units:
            position = {'number': '2.2', 'name': 'Учебная работа', 'unit': target}
            result = fact.match(dict(position, unit=source), [{'positions': [position]}])
            assert (isinstance(result, tuple)) == (source == target)
