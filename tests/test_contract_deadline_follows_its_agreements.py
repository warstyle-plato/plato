"""Work-completion dates come from the actual clause, amended independently of prices."""
import copy

import pymupdf
import pytest

import developaid_contract_documents as documents
import developaid_contract_files as files
import developaid_contract_terms as terms
import developaid_monitor_contracts as contracts
from tests.test_contract_documents_are_read_from_their_tables import _page, _text
from tests.test_contracts_from_cumulative_headers import context, parsed, provide  # noqa: F401


def _pdf(*lines):
    with pymupdf.open() as doc:
        page = _page(doc)
        for y, line in enumerate(lines):
            _text(page, 20, 30+y*15, line)
        return doc.tobytes()


def _record(number=None, day='2026-01-01', text='2.3.2. окончание Работ – 20.03.2027 г.'):
    return {'contract': {'number': 'A-12', 'date': '2026-01-01'},
            'agreement': {'number': str(number), 'date': day} if number is not None else None,
            'sha256': str(number or 0)*64, 'title': f'Документ {number or 0}',
            'terms': terms.read([text])}


def test_pdf_reader_keeps_a_clause_page_and_conditions_not_only_the_date():
    got = documents.read(_pdf('Договор подряда № A-12 от 01.01.2026',
        '2.3.2. окончание Работ – 20.03.2027 г., при условии своевременной выплаты авансов.'))
    date = got['terms']['deadline']
    assert (date['value'], date['page'], date['clause'], date['conditional']) == ('2027-03-20', 1, '2.3.2', True)
    assert 'при условии своевременной выплаты авансов' in date['quote']


@pytest.mark.parametrize('text', [
    'Срок действия договора – 31.12.2028 г.',
    'Аванс перечислить до 12.02.2027 г.; гарантийный срок истекает 20.03.2030 г.',
    'За 5 дней до окончания работ уведомить заказчика, не позднее 20.03.2027 г.',
    '2.4 Эксплуатация башенного крана. Дата расчета: 20.03.2027.',
    'Дата окончания Работ может быть изменена при задержке аванса от 20.03.2027.',
])
def test_other_dates_are_not_used_as_a_completion_deadline(text):
    got = terms.read([text])
    assert not got['changes_deadline'] and got['deadline'] is None


def test_only_the_later_condition_changes_and_the_cut_keeps_earlier_editions():
    base = _record()
    first = _record(1, '2026-08-21', '2.3.2. окончание Работ – 30.04.2027 г.')
    price = _record(2, '2026-09-11', 'Изменить цену Договора. Остальные условия остаются без изменений.')
    records = [price, first, base]  # upload/file order has no authority
    old = terms.resolve(records, '2026-08-20')
    new = terms.resolve(records, '2026-11-13')
    assert old['deadline'] == '2027-03-20' and len(old['history']) == 1
    assert new['deadline'] == '2027-04-30' and len(new['history']) == 2
    assert new['source']['sha256'] == first['sha256'] and new['source']['agreement']['number'] == '1'
    assert new['source']['page'] == 1 and new['source']['clause'] == '2.3.2'


@pytest.mark.parametrize('change', [{'removed_at': '2026-01-01'}, {'scan': {'confirmed_at': None}}])
def test_removed_or_unconfirmed_later_documents_do_not_amend_the_deadline(change):
    later = _record(1, '2026-02-01', 'окончание Работ – 30.04.2027 г.')
    later.update(change)
    assert terms.resolve([_record(), later], '2026-11-13')['deadline'] == '2027-03-20'


def test_conflicting_twins_or_invalid_new_dates_do_not_keep_the_old_deadline():
    one = _record(1, '2026-02-01', 'окончание Работ – 30.04.2027 г.')
    twin = copy.deepcopy(one)
    twin['terms'] = terms.read(['окончание Работ – 15.05.2027 г.'])
    got = terms.resolve([_record(), one, twin], '2026-11-13')
    assert got['deadline'] is None and got['state'] == 'conflicting' and got['warnings']
    invalid = _record(2, '2026-02-02', 'окончание Работ – 31.02.2027 г.')
    assert terms.resolve([_record(), invalid], '2026-11-13')['deadline'] is None


def test_a_relative_replacement_requires_its_trigger_instead_of_keeping_an_old_date():
    later = _record(1, '2026-02-01', 'окончание Работ – через 120 дней после передачи площадки.')
    got = terms.resolve([_record(), later], '2026-11-13')
    assert got['deadline'] is None and got['state'] == 'unknown' and got['warnings']


def test_an_explicit_completion_reference_uses_the_current_annex_with_both_sources():
    base = _record()
    later = _record(1, '2026-02-01', 'Срок окончания Работ установлен в Графике производства Работ '
                    '(Приложение № 2) в новой редакции.')
    graph = _record(1, '2026-02-01', 'График производства работ')
    graph['sha256'] = 'd'*64
    graph['schedule'] = {'pages': [2], 'lines': [{'start': '2026-02-01', 'finish': '2027-05-31'}]}
    got = terms.resolve([base, later, graph], '2026-11-13')
    assert got['deadline'] == '2027-05-31'
    assert got['source']['sha256'] == later['sha256'] and got['source']['schedule_sha256'] == graph['sha256']
    assert got['source']['basis'] == 'contract_schedule_reference'
    # Replacing an annex by itself supplies a plan, without rewriting the explicit clause.
    unchanged = terms.resolve([base, graph], '2026-11-13')
    assert unchanged['deadline'] == '2027-03-20'
    assert unchanged['schedule_comparison']['schedule_finish'] == '2027-05-31'
    assert unchanged['schedule_comparison']['schedule_sha256'] == graph['sha256']
    assert unchanged['warnings']
    assert not terms.read(['Сроки окончания отдельных видов работ установлены в Графике производства Работ.'])['changes_deadline']


def test_an_explicit_reference_does_not_choose_a_missing_future_or_conflicting_annex():
    later = _record(1, '2026-02-01', 'Окончание Работ – согласно Графику производства работ.')
    graph = _record(2, '2026-03-01', 'График производства работ')
    graph['schedule'] = {'lines': [{'start': '2026-02-01', 'finish': '2027-05-31'}]}
    got = terms.resolve([_record(), later, graph], '2026-02-15')
    assert got['deadline'] is None and got['warnings']
    # A newer agreement may amend the annex while leaving the clause's reference intact.
    assert terms.resolve([_record(), later, graph], '2026-11-13')['deadline'] == '2027-05-31'
    twin = copy.deepcopy(graph)
    twin['sha256'] = 'f'*64
    twin['schedule']['lines'][0]['finish'] = '2027-06-30'
    assert terms.resolve([_record(), later, graph, twin], '2026-11-13')['deadline'] is None


def test_individual_building_dates_in_the_gpr_do_not_conflict_with_the_overall_clause():
    condition = terms.read(['2.3.2. окончание Работ – 30.04.2027 г. '
        'Точные сроки выполнения отдельных видов работ, а также сроки окончания работ по каждому '
        'Корпусу установлены в Графике производства Работ (Приложение № 2 к Договору).'])
    assert condition['deadline']['value'] == '2027-04-30'
    assert len(condition['candidates']) == 1


def test_the_register_uses_saved_pdfs_and_keeps_an_explicit_manual_override(context):  # noqa: F811
    provide(context, parsed())
    row, = contracts.build('Example', '2026-11-06')['rows']
    files.store('Example', row, 'Договор.pdf', _pdf('Договор подряда № A-12 от 01.01.2026',
                '2.3.2. окончание Работ – 20.03.2027 г.'))
    files.store('Example', row, 'ДС 1.pdf', _pdf('Дополнительное соглашение № 1 от 21.08.2026',
                'к Договору подряда № A-12 от 01.01.2026',
                '2.3.2. окончание Работ – 30.04.2027 г.'))
    files.store('Example', row, 'ДС 2.pdf', _pdf('Дополнительное соглашение № 2 от 11.09.2026',
                'к Договору подряда № A-12 от 01.01.2026', 'Изменить цену договора.'))
    updated, = contracts.build('Example', '2026-11-06')['rows']
    assert updated['deadline'] == '2027-04-30' and updated['deadline_source']['agreement']['number'] == '1'
    assert len(updated['deadline_documents']['history']) == 2
    context.setattr(contracts, '_read_terms', lambda *_: {row['id']: {
        'deadline': '2027-05-15', 'note': 'Подтверждено владельцем', 'updated_at': '2026-10-01T00:00:00Z'}})
    manual, = contracts.build('Example', '2026-11-06')['rows']
    assert manual['deadline'] == '2027-05-15' and manual['deadline_source']['label'] == 'Указан вручную'
    assert manual['deadline_documents']['deadline'] == '2027-04-30'


def test_a_source_date_does_not_need_an_estimate_or_fact(context):  # noqa: F811
    provide(context, parsed())
    row, = contracts.build('Example', '2026-11-06')['rows']
    files.store('Example', row, 'Договор.pdf', _pdf('Договор подряда № A-12 от 01.01.2026',
                '2.3.2. окончание Работ – 20.03.2027 г.'))
    listed = files.listing('Example', row['id'], '2026-11-06')
    assert listed['control']['total'] is None
    assert listed['terms']['deadline'] == '2027-03-20'
    assert listed['terms']['source']['clause'] == '2.3.2'
