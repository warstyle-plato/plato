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


@pytest.mark.parametrize(('text','basis','rate'), [
    ('Цена Договора составляет 1 000 рублей. Сумма аванса составляет 500 рублей, включая НДС22%.', 'unspecified', None),
    ('Цена Договора составляет 1 000 рублей с НДС. Окончательный платеж 500 рублей без НДС.', 'with_vat', None),
    ('Цена Договора составляет 1 000 рублей с НДС, окончательный платеж 500 рублей без НДС.', 'with_vat', None),
    ('Цена Договора составляет 1 000 руб. Аванс 500 руб., включая НДС22%.', 'unspecified', None),
    ('Цена Договора составляет 1 000 рублей. В том числе НДС22% — 180.33 руб.', 'with_vat', 22),
    ('Цена Договора составляет 1 000,54 руб. 54 коп., в т. ч. НДС (22%) — 180.43 руб. Аванс 500 руб. без НДС.', 'with_vat', 22),
    ('Цена Договора составляет 1 000,54 руб. 54 коп. В т.ч. НДС (22%) — 180.43 руб. Окончательный платеж без НДС.', 'with_vat', 22),
])
def test_tax_qualification_belongs_to_this_price_not_the_next_obligation(text,basis,rate):
    (got,) = price.read([text])['candidates']
    assert got['value'] in (1000,1000.54) and got['amount_basis'] == basis and got['vat_rate'] == rate
    assert not got['reason']
    assert 'аванс' not in got['vat_text'].lower() and 'платеж' not in got['vat_text'].lower()


@pytest.mark.parametrize('subject', [
    'Цена Договора на первый этап', 'Цена Договора по первому этапу',
    'Стоимость Работ по Договору на первый этап', 'Цена Договора для корпуса1',
    'Цена Договора на 1-й этап', 'Цена Договора для первого корпуса',
])
def test_other_spellings_of_a_partial_scope_never_supply_a_whole_contract_price(subject):
    got = price.read([subject+' составляет 1 000 рублей с НДС.'])
    assert got['changes_price'] and got['candidates'][0]['value'] is None and got['warnings']


def test_an_old_price_quote_does_not_hide_a_separate_delta_on_the_same_page():
    record = _record('Цена Договора по ранее действующему соглашению составляет 1 000 рублей с НДС. '
                     'Увеличить Цену Договора на 100 рублей.')
    got = price.resolve([record],'2026-11-13')
    assert got['amount'] is None and got['state'] == 'conflicting' and got['warnings']


@pytest.mark.parametrize('date',['01.01.2026','1.1.2026','31.02.2026'])
def test_a_contract_date_is_not_a_clause_number(date):
    got = price.read([f'Договор от {date}. Цена Договора составляет 1 000 рублей с НДС.'])
    assert got['candidates'][0]['clause'] == ''


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


def _stored_closing(context,snapshot=None):
    provide(context, snapshot or source_snapshot(reference='Дог. № A-12 от 01.01.26'))
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


@pytest.mark.parametrize('basis',['unspecified',None])
def test_unknown_vat_of_closure_cannot_establish_a_new_percentage(basis):
    observation = {'state':'known','ratio':.2,'planned':1500,'completed':300,
                   'planned_amount_basis':'without_vat','completed_amount_basis':basis,
                   'requires_reconciliation':False}
    condition = price.resolve([_record('Цена Договора составляет 2 000 рублей с НДС.')],'2026-11-13')
    got = price.rebase_summary(observation,condition)
    assert got['planned'] == 2000 and got['planned_amount_basis'] == 'with_vat'
    assert got['ratio'] is None and got['state'] == 'unknown' and not got['monetary_comparable']
    assert got['requires_reconciliation'] and got['basis_signature'] is None
    assert got['reported_observation'] == observation


def test_known_new_price_also_corrects_its_vat_metadata():
    observation = {'state':'known','ratio':.2,'planned':1500,'completed':300,
                   'planned_amount_basis':'without_vat','completed_amount_basis':'with_vat'}
    condition = price.resolve([_record('Цена Договора составляет 2 000 рублей с НДС.')],'2026-11-13')
    got = price.rebase_summary(observation,condition)
    assert got['planned'] == 2000 and got['planned_amount_basis'] == got['completed_amount_basis'] == 'with_vat'
    assert got['ratio'] == .15 and got['reported_observation'] == observation


def test_known_summary_basis_does_not_get_a_warning_from_an_absent_cumulative(context):
    row=_stored_closing(context)
    assert row['source_kind']=='closing_summary'
    assert row['summary_progress']['state']=='known'
    assert row['summary_progress']['monetary_comparable']
    assert row['summary_progress']['ratio']==.15
    assert not any('подтвердить базу НДС' in warning for warning in row['warnings'])


def test_unknown_vat_keeps_the_price_visible_but_blocks_new_cumulative_percent(context):  # noqa: F811
    provide(context,parsed(),rss=[rss_contract(amount=1000,amount_basis='with_vat')])
    before, = contracts.build('Example','2026-11-06')['rows']
    files.store('Example',before,'Договор.pdf',_pdf('Договор подряда № A-12 от 01.01.2026',
        '3.1. Цена Договора составляет 2 000 рублей с НДС.'))
    row, = contracts.build('Example','2026-11-06')['rows']
    assert row['amount'] == 2000 and row['completed'] == before['completed']
    assert not row['monetary_comparable'] and row['completion_ratio'] is None and row['remaining'] is None
    assert any('НДС' in warning for warning in row['warnings'])


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
    snapshot = parsed()
    for ledger in snapshot['ledgers']:
        for item in ledger.get('items') or []:
            for period in item.get('periods') or []:
                period['amount_basis'] = 'with_vat'
    provide(context,snapshot,rss=[rss_contract(amount=1000,amount_basis='with_vat')])
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
        expect(more.locator('#contractCardSummary [data-label="Сумма договора"]')).to_contain_text('2 000')
        expect(more).to_contain_text('300 ₽ из 2 000 ₽')
        more.locator('#contractRecordSources > summary').click()
        details = more.locator('summary').filter(has_text='Проверить данные').locator('..')
        details.locator('summary').first.click()
        history = more.locator('summary').filter(has_text='Цена: договор и допсоглашения').locator('..')
        history.locator('summary').click()
        expect(history).to_contain_text('Цена Договора составляет 2 000 рублей с НДС')
        assert not errors and page.evaluate('document.documentElement.scrollWidth<=innerWidth')


@pytest.mark.parametrize('width',[390,1440])
def test_unknown_vat_never_appears_as_a_known_rebased_percentage_on_the_page_or_report(context,width):  # noqa: F811
    import developaid_management_report as report
    from playwright.sync_api import expect
    from tests.test_monitor_cumulative_controls import CONTRACT,browser_page
    from tests.contract_rows import opened
    snapshot = source_snapshot(reference='Дог. № A-12 от 01.01.26')
    snapshot['summary_contracts'][0]['reported_total']['completed_amount_basis'] = 'unspecified'
    row = _stored_closing(context,snapshot)
    assert row['amount'] == 2000 and row['progress']['ratio'] is None
    assert row['summary_progress']['requires_reconciliation']
    assert row['summary_progress']['reported_observation']['ratio'] == .2
    text = report._work_contract_progress(row,include_change=False)
    assert 'Доля неизвестна' in text and 'НДС' in text
    with browser_page(width) as (page,responses,errors):
        row['id'] = CONTRACT
        responses.data['rows'] = [copy.deepcopy(row)]
        page.locator('#contractsTab').click()
        shown = page.locator(f'tr[data-contract-id="{CONTRACT}"]')
        expect(shown.locator('.contract-money')).to_contain_text('2 000')
        expect(shown.locator('.contract-money .contract-done')).to_have_count(0)
        more = opened(page,CONTRACT)
        actual = more.locator('[data-label="Выполнение по документам"]')
        expect(actual).to_contain_text('НДС')
        expect(actual).not_to_contain_text('15 %')
        assert not errors and page.evaluate('document.documentElement.scrollWidth<=innerWidth')


@pytest.mark.parametrize('width',[390,1440])
def test_coverage_percent_keeps_its_own_basis_next_to_a_new_price_in_every_consumer(context,width):  # noqa: F811
    import developaid_management_report as report
    from playwright.sync_api import expect
    from tests.test_monitor_cumulative_controls import CONTRACT,browser_page
    from tests.contract_rows import opened
    provide(context,parsed(),rss=[rss_contract(amount=1000,amount_basis='with_vat')])
    before, = contracts.build('Example','2026-11-06')['rows']
    files.store('Example',before,'Договор.pdf',_pdf('Договор подряда № A-12 от 01.01.2026',
        '3.1. Цена Договора составляет 2 000 рублей с НДС.'))
    row, = contracts.build('Example','2026-11-06')['rows']
    assert row['amount'] == 2000 and row['completion_ratio'] is None
    assert row['statement_progress']['planned'] == 1020 and row['statement_progress']['completed'] == 400
    metric = report._work_contract_progress(row,include_change=False)
    assert 'стоимости работ по ведомостям' in metric and 'база 1 020 ₽' in metric
    markup = report._contract_performance_html({'state':'ok','performance_rows':[row]})
    assert 'стоимости работ по ведомостям' in markup and 'база 1 020 ₽' in markup
    with browser_page(width) as (page,responses,errors):
        row['id'] = CONTRACT
        responses.data['rows'] = [copy.deepcopy(row)]
        page.locator('#contractsTab').click()
        shown = page.locator(f'tr[data-contract-id="{CONTRACT}"]')
        brief = shown.locator('.contract-money')
        expect(brief).to_contain_text('2 000 ₽')
        expect(brief).to_contain_text('39,2%')
        expect(brief.locator('.contract-share-basis')).to_have_text('От стоимости работ по ведомостям · база 1 020 ₽')
        expect(brief.locator('.contract-full-share-unknown')).to_have_text('Доля полной цены договора не подтверждена')
        more = opened(page,CONTRACT)
        detail = more.locator('[data-label="Выполнено по накопительным"]')
        expect(detail).to_contain_text('400 ₽ из 1 020 ₽')
        expect(detail.locator('.contract-share-basis')).to_have_text('От стоимости работ по ведомостям')
        expect(detail.locator('.contract-full-share-unknown')).to_be_visible()
        assert not errors and page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.screenshot(path=f'/tmp/price-basis-labelled-{width}.png',full_page=True)
        page.locator('#contractDialogClose').click()
        page.emulate_media(media='print')
        expect(brief.locator('.contract-share-basis')).to_be_visible()
        expect(brief.locator('.contract-share-basis')).to_contain_text('1 020 ₽')
        expect(brief.locator('.contract-full-share-unknown')).to_be_visible()
