"""Synthetic source scope and typed-money boundaries; no provider calls."""
import json

import pytest

import document_intake as di
import teaser_card as tc

ROUTES = ['В цену сделки', 'В социальную нагрузку']


def transfer(question='Передача 73 м² — куда отнести?', quote='', choices=None):
    return di.question_card({'key': '', 'question': question, 'source_quote': quote,
                             'choices': choices or ROUTES})


def test_verified_context_purchase_is_not_the_transfer_valuation():
    quote = 'Передача 73 м²; отдельная покупка стоит 19 млн руб.'
    extraction = di.parse_intake(json.dumps({'questions': [{
        'key': '', 'question': quote+' Куда отнести передачу?', 'quote': quote,
        'options': ROUTES}]}))
    state = tc.start(extraction, {'text': quote}, 'synthetic.txt', presets={}, current_class='')
    card = state['cards'][0]
    assert all(o['value'] is None for o in card['options'])
    assert card['requires_manual'] and di.area_transfer(card)
    inputs = {'purchase_price_mln': 0, 'social_compensation_mln': 0}
    before = dict(inputs)
    got = tc.answer(state, inputs, {}, index=0, action='answer', choice=1,
                    spp_split={}, presets={})
    assert got['invalid'] and state['index'] == 0
    assert inputs == before and not tc.replay(state, inputs, {}, spp_split={}, presets={})['origins']


def test_explicit_model_choice_does_not_bypass_transfer_source_scope():
    card = transfer(quote='Передача 73 м²; отдельная покупка стоит 19 млн руб.',
                    choices=[{'label': label, 'value': 19, 'unit': 'млн ₽'} for label in ROUTES])
    assert all(o['value'] is None for o in card['options'])


@pytest.mark.parametrize('quote', [
    'Передача 73 м² оценена в 11 млн руб.',
    'Денежная оценка передачи 73 м²: 11 млн руб.',
    'Стоимость передаваемых площадей: 11 млн руб.',
])
def test_own_explicit_source_valuation_can_supply_the_money(quote):
    card = transfer(quote=quote)
    assert [o['value'] for o in card['options']] == [11, 11]
    assert not card['requires_manual']


def test_unrelated_scale_is_not_borrowed_but_cash_obligation_scale_is_kept():
    unrelated = transfer('Передача 73 м². Цена земли 1,4 млрд руб. Куда отнести передачу?')
    cash = di.question_card({'key': '', 'question': 'Платёж 1,4 млрд руб. — куда отнести?', 'options': ROUTES})
    assert di.answer_card(unrelated, {}, {}, choice=1, typed='1,4', ledger={})['inputs']['social_compensation_mln'] == 1.4
    assert di.answer_card(cash, {}, {}, choice=1, typed='1,4', ledger={})['inputs']['social_compensation_mln'] == 1400


@pytest.mark.parametrize('text', ['Передача 4,5 млн м²', 'Аренда 7 млн руб. в год',
                                 'Стоимость 8 млн USD', 'Стоимость 8 млн ₽/м²'])
def test_area_rate_and_foreign_currency_are_not_total_ruble_amounts(text):
    assert di.question_amounts(text) == []


@pytest.mark.parametrize('typed,expected', [
    ('2400000 руб.', 2.4), ('2 400 000 ₽', 2.4), ('2\u202f400\u202f000 ₽', 2.4), ('2400 тыс руб.', 2.4),
    ('2400 тыс', 2.4), ('2,4 млн ₽', 2.4), ('0,004 млрд руб.', 4),
    ('2,4', 2.4), ('0', 0),
])
def test_explicit_manual_unit_overrides_field_hint(typed, expected):
    got = di.answer_card(transfer(), {'social_compensation_mln': 0}, {}, choice=1, typed=typed, ledger={})
    assert not got['refused']
    assert got['inputs']['social_compensation_mln'] == pytest.approx(expected)


@pytest.mark.parametrize('typed', ['73 м²', '4 га', '9 USD', '2 млн EUR', '3 CNY',
                                  '7 млн руб. в год', '2+4', '1 23', '-2', '−2', ',', '.', 'не знаю'])
def test_invalid_manual_literal_never_becomes_money(typed):
    inputs = {'purchase_price_mln': 0}
    got = di.answer_card(transfer(), inputs, {}, choice=0, typed=typed, ledger={})
    assert not got['applied'] and got['refused']
    assert got['inputs'] == inputs


def test_manual_source_validation_cannot_restore_discarded_quote_numbers():
    card = di.question_card({'key': '', 'question': 'Укажите сумму и решение',
                             'quote': 'Передача 73 м² оценена в 11 млн руб.',
                             'requires_manual': True, 'options': ROUTES})
    assert all(o['value'] is None for o in card['options'])


@pytest.mark.parametrize('question', ['Благоустройство $9 млн — куда отнести?',
                                   'Платёж USD 9 млн — куда отнести?',
                                   'Платёж 2 млн USD и 7 млн руб. — куда отнести?'])
def test_foreign_or_mixed_obligation_is_not_an_automatic_partial_ruble_total(question):
    card = di.question_card({'key': '', 'question': question, 'options': ROUTES})
    assert all(o['value'] is None for o in card['options'])
    assert card['requires_manual']
    manual = di.answer_card(card, {}, {}, choice=1, typed='4 млн ₽', ledger={})
    assert manual['inputs']['social_compensation_mln'] == 4


def test_model_ruble_choice_cannot_relabel_foreign_source_amount():
    card = di.question_card({'key': '', 'question': 'Платёж USD 9 млн — куда отнести?',
        'choices': [{'label': label, 'value': 9, 'unit': 'млн ₽'} for label in ROUTES]})
    assert all(o['value'] is None for o in card['options'])
