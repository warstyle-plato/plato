"""The explicit full contract price, its amendments and VAT own every monetary denominator."""
import copy

import pytest

import developaid_contract_documents as documents
import developaid_contract_files as files
import developaid_contract_price as price
import developaid_monitor_contracts as contracts
from tests.test_contract_deadline_follows_its_agreements import _pdf
from tests.test_contracts_from_cumulative_headers import context, parsed, provide, rss_contract  # noqa: F401
from tests.test_closing_summary_contracts import source_snapshot


def _record(text, number=None, day='2026-01-01'):
    return {'contract': {'number': 'A-12', 'date': '2026-01-01'}, 'title': f'Документ {number or 0}',
            'agreement': {'number': str(number), 'date': day} if number is not None else None,
            'sha256': str(number or 0)*64, 'price': price.read([text])}


@pytest.mark.parametrize(('text','expected','basis'), [
    ('Цена Договора составляет 10 123 (Десять тысяч сто двадцать три) рубля 54 копейки, в том числе НДС.', 10123.54, 'with_vat'),
    ('Цена Договора составляет 10 123,54 (Десять тысяч сто двадцать три) рубля 54 копейки, в том числе НДС (22 %).', 10123.54, 'with_vat'),
    ('Стоимость Работ по Договору (Цена Договора) определена в Расчете и составляет 1 000 рублей без НДС.', 1000, 'without_vat'),
    ('Цена Договора составляет 0 рублей, в том числе НДС.', 0, 'with_vat'),
    ('Цена Договора составляет 1 000 рублей.', 1000, 'unspecified'),
])
def test_the_declared_whole_price_and_kopecks_are_read_exactly(text,expected,basis):
    result = documents.read(_pdf('Договор подряда № A-12 от 01.01.2026', '3.1. '+text))
    (candidate,) = result['price']['candidates']
    assert (candidate['value'], candidate['amount_basis'], candidate['page'], candidate['clause']) == (expected,basis,1,'3.1')
    assert candidate['quote'] and not candidate['reason']


@pytest.mark.parametrize('text', [
    'Расчёт договорной стоимости на завершение работ. Итого 900 000 рублей с НДС.',
    'Стоимость дополнительных работ составляет 900 000 рублей с НДС.',
    'Акт КС-2 № 1. Общая стоимость выполненных работ составляет 900 000 рублей.',
    'Цена одного места составляет 900 000 рублей.',
    'Цена Договора является твердой и изменению не подлежит.',
])
def test_an_act_remaining_estimate_section_or_generic_phrase_is_not_the_full_price(text):
    assert not price.read([text])['changes_price']


def test_the_declared_gross_total_is_not_replaced_by_an_accepted_or_remaining_subtotal():
    text = ('3.1. Цена Договора составляет 1 500 рублей, в том числе НДС, и определена на основании расчетов: '
            'на выполненные и принятые работы — 500 рублей, в том числе НДС 20%; '
            'на завершение работ — 1 000 рублей, в том числе НДС 22%.')
    got = price.read([text])['candidates'][0]
    assert got['value'] == 1500 and got['amount_basis'] == 'with_vat' and got['vat_rate'] is None


@pytest.mark.parametrize('text', [
    'Цена Договора составляет 1 000,53 рублей 54 копейки с НДС.',
    'Цена Договора составляет 1O00 рублей с НДС.',
    'Цена Договора составляет -1 000 рублей с НДС.',
    'Цена Договора составляет 1 000 рублей без НДС, включая НДС.',
    'Предварительная Цена Договора составляет 1 000 рублей с НДС.',
])
def test_an_unread_or_internally_inconsistent_new_price_does_not_revive_the_previous_price(text):
    base = _record('Цена Договора составляет 800 рублей с НДС.')
    later = _record(text,1,'2026-02-01')
    got = price.resolve([base,later],'2026-11-13')
    assert got['amount'] is None and got['warnings'] and got['state'] == 'conflicting'


def test_later_price_changes_keep_their_own_date_and_other_amendments_preserve_the_price():
    base = _record('Цена Договора составляет 1 000 рублей с НДС.')
    changed = _record('3.1. Цена Договора составляет 2 000 рублей с НДС.',1,'2026-02-01')
    unrelated = _record('2.3.2. Окончание Работ – 30.04.2027 г.',2,'2026-03-01')
    assert price.resolve([changed,base,unrelated],'2026-01-31')['amount'] == 1000
    got = price.resolve([changed,base,unrelated],'2026-11-13')
    assert got['amount'] == 2000 and len(got['history']) == 2
    assert got['source']['agreement']['number'] == '1' and got['source']['clause'] == '3.1'
    delta = _record('Увеличить Цену Договора на 100 рублей.',3,'2026-04-01')
    assert price.resolve([base,changed,delta],'2026-11-13')['amount'] is None


def test_removed_unconfirmed_and_conflicting_twins_are_not_selected_by_upload_order():
    base = _record('Цена Договора составляет 1 000 рублей с НДС.')
    later = _record('Цена Договора составляет 2 000 рублей с НДС.',1,'2026-02-01')
    for marker in ({'removed_at':'today'}, {'scan':{'confirmed_at':None}}):
        ignored = {**later, **marker}
        assert price.resolve([base,ignored],'2026-11-13')['amount'] == 1000
    twin = _record('Цена Договора составляет 3 000 рублей с НДС.',1,'2026-02-01')
    assert price.resolve([base,later,twin],'2026-11-13')['amount'] is None


def _stored_closing(context):
    provide(context, source_snapshot(reference='Дог. № A-12 от 01.01.26'))
    row, = contracts.build('Example','2026-11-06')['rows']
    files.store('Example',row,'Договор.pdf',_pdf('Договор подряда № A-12 от 01.01.2026',
        '3.1. Цена Договора составляет 1 000 рублей с НДС.'))
    files.store('Example',row,'ДС 1.pdf',_pdf('Дополнительное соглашение № 1 от 01.10.2026',
        'к Договору подряда № A-12 от 01.01.2026','3.1. Цена Договора составляет 2 000 рублей с НДС.'))
    return contracts.build('Example','2026-11-06')['rows'][0]


def test_real_register_and_history_use_current_price_without_changing_a_source_total(context):  # noqa: F811
    row = _stored_closing(context)
    assert row['amount'] == 2000 and row['amount_basis'] == 'with_vat'
    assert row['amount_source']['agreement']['number'] == '1'
    assert row['progress']['ratio'] == row['summary_progress']['ratio'] == .15
    assert row['progress']['planned'] == 2000 and row['progress']['completed'] == 300
    assert row['summary_progress']['reported_observation']['planned'] == 1500
    assert row['summary_progress']['reported_observation']['ratio'] == .2
    assert row['completed'] is None and row['completion_ratio'] is None  # no invented execution dates
    assert row['risk']['forecast_finish'] is None
    assert len(row['amount_documents']['history']) == 2


def test_mismatched_vat_blocks_the_new_percentage_and_keeps_the_printed_observation():
    observation = {'state':'known','ratio':.2,'planned':1500,'completed':300,'completed_amount_basis':'without_vat'}
    condition = price.resolve([_record('Цена Договора составляет 2 000 рублей с НДС.')],'2026-11-13')
    got = price.rebase_summary(observation,condition)
    assert got['ratio'] is None and got['state'] == 'unknown'
    assert got['reported_observation'] == observation


def test_a_partial_price_named_inside_a_contract_price_phrase_is_not_a_new_full_total():
    got = price.read(['Цена Договора по этапу 1 составляет 5 000 рублей с НДС.'])
    assert got['candidates'][0]['value'] is None and got['warnings']


def test_unread_new_price_blocks_a_stale_summary_denominator(context):  # noqa: F811
    row = _stored_closing(context)
    files.store('Example',row,'ДС 2.pdf',_pdf('Дополнительное соглашение № 2 от 15.10.2026',
        'к Договору подряда № A-12 от 01.01.2026','Увеличить Цену Договора на 100 рублей.'))
    changed, = contracts.build('Example','2026-11-06')['rows']
    assert changed['amount'] is None and changed['progress']['ratio'] is None
    assert changed['summary_progress']['reported_observation']['ratio'] == .2


def test_cumulative_percent_remaining_and_risk_share_the_new_price(context):  # noqa: F811
    provide(context,parsed(),rss=[rss_contract(amount=1000,amount_basis='with_vat')])
    before, = contracts.build('Example','2026-11-06')['rows']
    files.store('Example',before,'Договор.pdf',_pdf('Договор подряда № A-12 от 01.01.2026',
        '3.1. Цена Договора составляет 2 000 рублей с НДС.'))
    row, = contracts.build('Example','2026-11-06')['rows']
    assert row['amount'] == 2000 and row['completed'] == before['completed']
    assert row['completion_ratio'] == row['completed']/2000
    assert row['remaining'] == 2000-row['completed']
    assert row['progress']['ratio'] == row['completion_ratio']


@pytest.mark.parametrize('width',[390,1440])
def test_page_and_management_report_show_the_same_new_price_and_percentage(context,width):  # noqa: F811
    import developaid_management_report as report
    from playwright.sync_api import expect
    from tests.test_monitor_cumulative_controls import CONTRACT,browser_page
    from tests.contract_rows import opened
    row = _stored_closing(context)
    text = report._work_contract_progress(row,include_change=False)
    assert '15' in text and 'суммы договора' in text
    with browser_page(width) as (page,responses,errors):
        row['id'] = CONTRACT
        responses.data['rows'] = [copy.deepcopy(row)]
        page.locator('#contractsTab').click()
        shown = page.locator(f'tr[data-contract-id="{CONTRACT}"]')
        expect(shown.locator('.contract-money')).to_contain_text('2 000')
        expect(shown.locator('.contract-money')).to_contain_text('15')
        more = opened(page,CONTRACT)
        expect(more.locator('[data-label="Сумма договора"]')).to_contain_text('2 000')
        expect(more).to_contain_text('300 ₽ из 2 000 ₽')
        details = more.locator('summary').filter(has_text='Проверить данные').locator('..')
        details.locator('summary').first.click()
        history = more.locator('summary').filter(has_text='Цена: договор и допсоглашения').locator('..')
        history.locator('summary').click()
        expect(history).to_contain_text('Цена Договора составляет 2 000 рублей с НДС')
        assert not errors and page.evaluate('document.documentElement.scrollWidth<=innerWidth')
