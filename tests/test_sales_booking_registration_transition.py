"""A named registration section explains a booking's departure, without inventing a sale."""
import pytest

from market_search import sales_questions, salesroom
import developaid_management_report as report


FIRST = "квартира № 31, башня Север, 6 этаж, 91,2 кВ.м."
OTHER = "квартира № 48, башня Север, 4 этаж, 61.7 кВ.м."
ORAL = "квартира № 17, башня Юг, 7 этаж, 51,6 кв.м."


def text(registering, bookings, *, registration_count=None):
    count = len(registering) if registration_count is None else registration_count
    return ("Отчёт. ЦО за день - 1. Встречи за день - 0.\n"
            f"ДДУ на регистрации: {count}\n" + "\n".join('- '+s for s in registering)
            + f"\nТекущих броней: {len(bookings)}\n" + "\n".join('- '+s for s in bookings)
            + f"\nТекущих устных броней: 1 шт.\n- {ORAL}\nПлан встреч на завтра: 2")


def history(current):
    previous = text([], [FIRST+' Подписано, ждём оплаты СБР.', OTHER])
    read = salesroom.append_message(None, '2026-11-19', 'Дежурный', previous)
    return salesroom.append_message(read, '2026-11-20', 'Дежурный', current)


def test_explicit_registration_reaches_booking_outcomes_questions_and_report():
    read = history(text([FIRST], [OTHER]))
    result = salesroom.booking_outcomes(read, [], None, '2026-11-19', '2026-11-20')
    gone, = result['period']
    assert gone['apartment'] == '31' and gone['outcome'] == 'registering'
    assert result['total'] == {'deal': 0, 'dropped': 0, 'unknown': 0, 'registering': 1}
    assert [lot['apartment'] for lot in result['held']] == ['48']
    assert not [q for q in sales_questions.questions(read, None, None, '2026-11-20') if q['kind']=='dropped']
    line = report._bookings_line(result, 'week')
    assert '1 передано на регистрацию по отчёту отдела продаж' in line
    assert 'снята' not in line and 'стала договором' not in line


@pytest.mark.parametrize('registration', [FIRST.replace('31', '32'), FIRST.replace('Север', 'Юг')])
def test_other_apartment_or_tower_does_not_answer_a_missing_booking(registration):
    read = history(text([registration], [OTHER]))
    found = sales_questions.questions(read, None, None, '2026-11-20')
    assert [q['kind'] for q in found] == ['dropped']
    assert '№ 31' in found[0]['text']


@pytest.mark.parametrize('current', [text([], [OTHER]), text([FIRST], [OTHER], registration_count=0),
                                    text([FIRST], [OTHER], registration_count=2)])
def test_count_without_named_lot_or_inconsistent_registration_does_not_hide_a_question(current):
    found = sales_questions.questions(history(current), None, None, '2026-11-20')
    assert [q['kind'] for q in found] == ['dropped']


def test_sections_do_not_borrow_lots_from_oral_bookings_or_the_neighbouring_list():
    message = text([FIRST], [OTHER])
    assert [lot['apartment'] for lot in salesroom.registering_lots(message)] == ['31']
    assert [lot['apartment'] for lot in salesroom.booked_lots(message)] == ['48']
    assert salesroom.registering_lots(text([], [FIRST, OTHER])) == []
    assert salesroom.registering_lots('Текущих броней: 1\n- '+FIRST) is None


def test_a_later_contract_takes_priority_over_the_reported_registration():
    read = history(text([FIRST], [OTHER]))
    deal = {'unit': 'корп 1 кв.31', 'area': 91.2, 'signed': '2026-11-20'}
    result = salesroom.booking_outcomes(read, [deal], '2026-11-20', '2026-11-19', '2026-11-20')
    assert result['period'][0]['outcome']=='deal'
