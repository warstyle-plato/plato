"""KS-6a quantities remain primary while KS-2 confirms, reconciles and dates them."""
import copy

import pytest

import developaid_contract_fact as fact
import developaid_contract_control as control
import developaid_contract_plan as plan
import developaid_contract_schedule_links as links


POSITION = {'number': '1', 'name': 'Монтаж', 'unit': 'м2', 'quantity': 100,
            'unit_price': {'work': 100, 'material': 0, 'total': 100},
            'amount': {'work': 10000, 'material': 0, 'total': 10000}}
EDITION = {'sha256': 'a'*64, 'title': 'Расчёт', 'date': '2026-01-01', 'start': None,
           'schedule': {'lines': [{'code': '1', 'name': 'Монтаж', 'start': '2026-01-01',
                                  'finish': '2026-12-31', 'parent': None}]},
           'estimates': [{'scope': 'full', 'positions': [POSITION], 'links': {'positions': [
               {'key': links.position_key(POSITION), 'status': 'confirmed',
                'amount': 10000, 'unit': 'м2', 'quantity': 100,
                'lines': [{'code': '1', 'share': 1}]}]}}]}
CUT = '2026-11-19'


def statement(heading='КС-2 № {}'):
    return fact.acts({'physical_items': [{'position': '1', 'name': 'Монтаж', 'unit': 'м2',
        'plan_quantity': 100, 'completed_quantity': 15, 'reported_completed_quantity': 15,
        'periods': [{'label': heading.format(n), 'quantity': n, 'amount': 100*n,
                     'work_amount': 100*n, 'material_amount': 0,
                     'date_start': f'2026-0{n}-01', 'date_end': f'2026-0{n}-28'} for n in range(1, 6)]}]})


def uploaded(*numbers):
    return {'acts': [{'number': str(n), 'day': f'2026-0{n}-28'} for n in numbers],
            'positions': [{'number': '1', 'name': 'Монтаж', 'unit': 'м2', 'parts': [
                {'act': str(n), 'quantity': 100, 'amount': 10000, 'name': 'Монтаж',
                 'day': f'2026-0{n}-28', 'preliminary': False} for n in numbers]}]}


def build(found, performed=None):
    return fact.build([EDITION], EDITION['sha256'], found, CUT, performed)


@pytest.mark.parametrize('heading', ['КС-2 № {}', 'КС2-{}'])
def test_missing_ks2_one_and_five_do_not_exclude_statement_execution_or_change_percentages(heading):
    found = statement(heading)
    before = copy.deepcopy(found)
    no_ks2, partial = build(found), build(found, uploaded(2, 3, 4))
    assert partial['source'] == 'ks6a' and partial['total'] == no_ks2['total'] == 1500
    assert partial['lines'] == no_ks2['lines']
    assert partial['lines'][0]['volumes'] == [{'unit': 'м2', 'quantity': 15}]
    assert partial['confirmation']['missing_acts'] == ['1', '5']
    assert partial['confirmation']['message'] == 'Загрузите КС-2 № 1, 5 для подтверждения.'
    assert partial['reconciliation']['differs'] == 1
    planned = plan.build([EDITION], CUT)
    controls = [control.build(planned, result, None, '', CUT) for result in (no_ks2, partial)]
    assert controls[0]['total'] == controls[1]['total']
    assert controls[1]['total']['readiness'] == pytest.approx(.15)
    assert controls[1]['data_gaps'] == []
    assert found == before


@pytest.mark.parametrize('heading', ['КС-2 № {}', 'КС2-{}'])
def test_without_any_ks2_all_named_periods_request_confirmation_without_losing_fact(heading):
    got = build(statement(heading))
    assert got['total'] == 1500 and got['note'] == ''
    assert got['confirmation']['missing_acts'] == ['1', '2', '3', '4', '5']
    assert got['confirmation']['state'] == 'pending'


@pytest.mark.parametrize('heading', ['КС-2 № {}', 'КС2-{}'])
def test_matching_complete_ks2_set_confirms_the_statement_without_changing_quantities(heading):
    performed = uploaded(1, 2, 3, 4, 5)
    for part in performed['positions'][0]['parts']:
        part.update(quantity=int(part['act']), amount=100*int(part['act']))
    got = build(statement(heading), performed)
    assert got['confirmation']['state'] == 'confirmed'
    assert not got['confirmation']['upload_required']
    assert got['total'] == 1500


def test_act_date_or_amount_warnings_prevent_a_false_successful_confirmation():
    found = statement()
    found['act_dates'] = [{'warnings': ['Итог акта отличается от периода ведомости.']}]
    result = fact.confirmation(uploaded(1, 2, 3, 4, 5), found, CUT,
                               {'differs': 0, 'only_ks2': 0, 'only_ks6a': 0})
    assert result['state'] == 'differs' and result['issues']


def test_ks2_supplies_fact_when_the_statement_is_absent_or_unreadable():
    for found in (None, fact.unavailable('Исходник не прочитан.')):
        got = build(found, uploaded(2))
        assert got['total'] == 10000 and not got['note'] and got['source'] == 'ks2'
        assert got['source_incomplete'] and 'Полнота комплекта' in got['source_note']
        assert got['lines'][0]['volumes'] == [{'unit': 'м2', 'quantity': 100}]


@pytest.mark.parametrize('heading', ['КС-2 № {}', 'КС2-{}'])
def test_undated_statement_is_not_given_invented_dates(heading):
    found = statement(heading)
    periods = [{**row, 'start': None, 'end': None} for row in found['acts']]
    found.update(acts=[], works=0, items=[], unread=[{
        'number': '1', 'name': 'Монтаж', 'unit': 'м2', 'periods': periods,
        'reason': 'Периоды без дат.', 'reported_quantity': 15}])
    got = build(found)
    assert got['total'] is None and 'даты' in got['note']
    assert got['confirmation']['missing_acts'] == ['1', '2', '3', '4', '5']


def test_confirmation_keeps_full_numbers_and_ignores_future_periods():
    found = statement()
    found['acts'][0]['label'] = 'КС-2 № 01/2026'
    found['acts'][-1]['label'] = 'КС2-5'
    found['acts'][-1]['end'] = '2026-12-01'
    done = uploaded(1, 2, 3, 4)
    got = build(found, done)
    assert got['confirmation']['missing_acts'] == ['1/2026']


@pytest.mark.parametrize('label', ['КС2-2026-11-05', 'Примечание КС2-5', 'КС2-5/2026',
    'КС2-5 от 19.11.2026', 'КС2-5, КС2-6', 'Период № 5', '2026-11-05'])
def test_confirmation_does_not_extract_compact_numbers_from_dates_or_mentions(label):
    found = {'acts': [{'label': label, 'quantity': 1, 'end': '2026-11-18'}]}
    before = copy.deepcopy(found)
    got = fact.confirmation(uploaded(2), found, CUT)
    assert got['missing_acts'] == [] and not got['upload_required']
    assert found == before


@pytest.mark.parametrize('width', [390, 1440])
def test_confirmation_note_opens_the_existing_upload_picker_without_blocking_the_card(width, card):
    from playwright.sync_api import expect
    from test_monitor_cumulative_controls import browser_page
    from tests.test_contract_card_confirms_and_chooses_links import CONTRACT, _serve
    from tests.test_contract_fact_dates_ks6_periods_by_acts import _row, WALLS

    row = _row(WALLS, summary=[('1', '2026-01-31', 2000), ('2', '2026-02-03', 4000)])
    with browser_page(width) as (page, _, errors):
        _serve(page, [], cut='2026-02-04', acts=fact.acts(row))
        page.locator('#contractsTab').click()
        page.locator(f'tr[data-contract-id="{CONTRACT}"] .contract-open').click()
        note = page.locator('.contract-ks2-confirmation')
        expect(note.locator('summary')).to_have_text('Загрузите КС-2 № 1, 2 для подтверждения.')
        expect(page.locator('#contractComparisonInfo')).to_contain_text('Факт по накопительной КС-6а.')
        expect(page.locator('#contractCardSummary')).to_contain_text('40 %')
        note.locator('summary').click()
        with page.expect_file_chooser() as chooser:
            note.get_by_role('button', name='Загрузить КС-2', exact=True).click()
        chooser.value.set_files([])
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert not errors


from tests.test_contract_fact_prices_ks_by_the_edition import card  # noqa: E402,F401
