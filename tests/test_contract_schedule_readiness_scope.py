"""Readiness of matched schedule works never claims a whole-contract percentage."""
import json

import pytest

import developaid_monitor_page as page
from tests import page_blocks


CONTROL = {'documents': 2, 'state': 'behind', 'lag_days': 3, 'ahead_days': 0,
           'readiness': 0.001, 'plan_done': 0.001, 'planned': 1000, 'fact': 1,
           'deviation': -999, 'percent': -0.999, 'deadline': '2026-03-01',
           'finish': '2026-03-04', 'from_register': True, 'days_over': 3, 'threat': True}


def rendered(control, source=None):
    row = {'monetary_comparable': False, 'completion_ratio': None, 'schedule_control': control}
    out, taken = page_blocks.run(
        'const row=' + json.dumps(row) + ';const before=JSON.stringify(row);',
        'console.log(JSON.stringify({brief:contractScheduleBrief(row),parts:contractScheduleParts(row),'
        'unchanged:before===JSON.stringify(row)}))', page=source or page.MONITOR_PAGE)
    assert 'contractScheduleBrief' in taken
    return json.loads(out)


def assert_matched_scope(result):
    assert 'Сверить с КС-6а' in result['brief']
    assert '0,1 %' not in result['brief']
    assert 'готовность сопоставленных работ' in result['parts']
    assert 'готовность договора' not in result['parts']
    assert result['unchanged']


def test_low_schedule_readiness_is_named_as_matched_scope_without_changing_financial_unknowns():
    assert_matched_scope(rendered(CONTROL))


def test_scope_assertion_rejects_the_previous_whole_contract_wording():
    old = page.MONITOR_PAGE.replace('готовность сопоставленных работ ${contractShare(s.readiness)}',
                                    'готовность ${contractShare(s.readiness)}').replace(
        '<div class="contract-sub">готовность сопоставленных работ</div>',
        '<div class="contract-sub">готовность договора</div>')
    with pytest.raises(AssertionError):
        assert_matched_scope(rendered(CONTROL, old))


def test_unknown_schedule_readiness_is_not_rendered_as_zero():
    result = rendered(dict(CONTROL, readiness=None, plan_done=None))
    assert 'готовность' not in result['brief']
    assert 'готовность сопоставленных работ' not in result['parts']
    assert '0 %' not in result['parts']
    assert result['unchanged']


def test_partial_coverage_and_remaining_start_are_visible_next_to_the_measured_readiness():
    c = dict(CONTROL, forecast_scope='matched_works', whole_contract_finish=None,
             coverage={'source_known': True, 'calculated': 2, 'source_works': 5, 'unknown': 3,
                       'partial': True, 'calculation_start': '2026-02-01', 'prior_periods': 7})
    result = rendered(c)
    assert 'Сверить с КС-6а' in result['brief']
    for html in (result['parts'],):
        assert 'В расчёте 2 из 5 работ ГПР. Проценты относятся к этим работам.' in html
        assert 'Выполнение остальных работ не определено.' in html
        assert 'Расчёт с 01.02.2026.' in html
        assert 'Периоды КС до этой даты учтены отдельно: 7.' in html
        assert 'Прогноз всего договора не определён.' in html
        assert 'Оценка сопоставленных работ: 04.03.2026.' in html
    assert result['unchanged']


def test_complete_known_scope_keeps_its_finish_visible():
    c = dict(CONTROL, forecast_scope='matched_works', whole_contract_finish=CONTROL['finish'],
             coverage={'source_known': True, 'calculated': 2, 'source_works': 2,
                       'unknown': 0, 'partial': False})
    result = rendered(c)
    assert 'Есть отставание' in result['brief']
    for html in (result['parts'],):
        assert '04.03.2026' in html
        assert 'Прогноз всего договора не определён' not in html
        assert 'В расчёте 2 из 2 работ ГПР. Проценты относятся к этим работам.' in html
    assert result['unchanged']
