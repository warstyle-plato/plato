"""The legal register starts with cumulative headers, never all RSS contracts."""
from __future__ import annotations

import datetime as dt
import io
import json

import openpyxl
import pytest

import developaid_monitor as monitor
import developaid_monitor_contracts as contracts
import developaid_monitor_ledgers as ledgers
from test_monitor_cumulative_ledgers import archive, book

ARCHIVE_READER = contracts._archive
RSS_READER = contracts._read_rss


def ks(*, number="A-12", date=dt.date(2026, 1, 1), period=None, header="Дата", inline=False):
    wb = openpyxl.load_workbook(io.BytesIO(book()))
    ws = wb.active
    ws['B3'] = f'№ {number} от 01.01.2026' if inline else number
    ws['A4'], ws['B4'] = header, date
    if period == "jan":
        ws.delete_cols(11, 3)
        ws['K9'], ws['L9'] = 2, 200
    elif period == "feb":
        ws.delete_cols(8, 3)
        ws['K9'], ws['L9'] = 2, 200
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def parsed(*files):
    result = ledgers.parse_archive(archive(list(files) or [('KS.xlsx', ks())]))
    return dict(result, taken_at='2026-11-06', snapshot_id='test')


@pytest.fixture
def context(monkeypatch, tmp_path):
    monkeypatch.setattr(monitor, '_SNAPSHOT_DIR', tmp_path)
    monkeypatch.setattr(contracts, '_read_rss', lambda *_: ([], None, []))
    monkeypatch.setattr(contracts, '_archive', lambda *_: None)
    return monkeypatch


def provide(context, snapshot, rss=()):
    context.setattr(contracts, '_archive', lambda *_: snapshot)
    context.setattr(contracts, '_read_rss', lambda *_: (list(rss), '2026-11-06', []))


def rss_contract(*, contract='A-12', contract_date='2026-01-01', customer='ООО «Заказчик»', **kw):
    return {'kind': 'rss', 'customer': customer, 'contractor': 'ООО «Подрядчик»',
            'contract': contract, 'contract_date': contract_date, 'amount': 1000,
            'completed': 900, 'source': {'label': 'РСС', 'sheet': 'Реестр договоров',
                                       'row': 9, 'completed_cell': 'L9'}, **kw}


def test_770_rss_rows_cannot_expand_two_cumulative_contracts(context):
    snapshot = parsed(('One.xlsx', ks()), ('Two.xlsx', ks(number='B-24', date=dt.date(2026, 2, 1))))
    rss = [rss_contract(contract=f'IT-{i}', subject='Лицензия программного обеспечения') for i in range(768)]
    rss += [rss_contract(), rss_contract(contract='B-24', contract_date='2026-02-01')]
    provide(context, snapshot, rss)
    view = contracts.build('Example', '2026-11-06')
    assert len(view['rows']) == 2
    assert view['counts'] == {'contracts_from_cumulative': 2, 'cumulative_sheets': 2, 'unresolved_headers': 0}
    assert {x['contract'] for x in view['rows']} == {'A-12', 'B-24'}
    assert all(x['completed'] == 400 for x in view['rows'])  # Never RSS L=900.
    assert all(x['amount'] == 1000 and x['completion_ratio'] == .4 for x in view['rows'])
    assert 'Общий реестр РСС' in view['scope_note']


def test_rss_only_has_no_fallback_and_does_not_even_read_the_register(context):
    def no_read(*_):
        raise AssertionError('RSS must not create the contract universe')
    context.setattr(contracts, '_read_rss', no_read)
    view = contracts.build('Example', '2026-11-06')
    assert view['rows'] == []
    assert view['counts']['contracts_from_cumulative'] == 0
    assert 'Загрузите архив накопительных' in view['empty_reason']


def test_unrelated_summary_rows_do_not_become_contracts(context):
    snapshot = parsed()
    snapshot['summary_contracts'] = [dict(rss_contract(contract='IT'), kind='summary', acts=[])]
    provide(context, snapshot)
    view = contracts.build('Example', '2026-11-06')
    assert len(view['rows']) == 1 and view['rows'][0]['contract'] == 'A-12'
    assert view['rows'][0]['amount'] is None
    assert view['rows'][0]['completion_ratio'] is None


def test_two_cumulative_periods_share_one_contract_without_doubling_plan_or_money(context):
    snapshot = parsed(('Jan.xlsx', ks(period='jan')), ('Feb.xlsx', ks(period='feb')))
    provide(context, snapshot, [rss_contract()])
    row, = contracts.build('Example', '2026-11-06')['rows']
    assert row['completed'] == 400 and row['completion_ratio'] == .4
    assert row['performance_source_count'] == 2
    assert {x['filename'] for x in row['sources']} == {'Jan.xlsx', 'Feb.xlsx'}


def test_identical_cumulative_copies_are_not_two_executions(context):
    provide(context, parsed(('One.xlsx', ks()), ('Copy.xlsx', ks())), [rss_contract()])
    row, = contracts.build('Example', '2026-11-06')['rows']
    assert row['completed'] == 400


def test_same_number_with_different_contract_dates_remains_separate(context):
    provide(context, parsed(('Old.xlsx', ks(date=dt.date(2025, 1, 1))), ('New.xlsx', ks())))
    rows = contracts.build('Example', '2026-11-06')['rows']
    assert len(rows) == 2 and len({x['id'] for x in rows}) == 2
    assert {x['contract_date'] for x in rows} == {'2025-01-01', '2026-01-01'}


def test_act_date_cannot_supply_a_missing_contract_date(context):
    snapshot = parsed(('ActDate.xlsx', ks(header='Дата акта', date=dt.date(2026, 3, 31))))
    provide(context, snapshot)
    view = contracts.build('Example', '2026-11-06')
    assert view['rows'] == [] and len(view['unresolved_sources']) == 1
    assert 'дата договора' in view['unresolved_sources'][0]['reason']
    inline = parsed(('Inline.xlsx', ks(header='Дата акта', date=dt.date(2026, 3, 31), inline=True)))
    assert inline['ledgers'][0]['contract_date'] == '2026-01-01'


def test_invalid_saved_text_date_remains_visible_with_its_source_cell(context):
    provide(context, parsed(('BrokenDate.xlsx', ks(date='03.07.124'))))
    view = contracts.build('Example', '2026-11-06')
    assert view['rows'] == []
    item, = view['unresolved_sources']
    assert item['contract'] == 'A-12' and item['contractor']
    assert item['date_evidence'][0]['raw'] == '03.07.124'
    assert item['date_evidence'][0]['source']['cell'] == 'B4'
    assert item['source']['filename'] == 'BrokenDate.xlsx'


@pytest.mark.parametrize('bad_field', ['customer', 'contractor', 'contract', 'contract_date'])
def test_incomplete_identity_is_visible_and_cannot_guess_a_join(context, bad_field):
    snapshot = parsed()
    snapshot['ledgers'][0][bad_field] = None
    provide(context, snapshot, [rss_contract()])
    view = contracts.build('Example', '2026-11-06')
    assert view['rows'] == [] and len(view['unresolved_sources']) == 1


def _repeated_party_book(header, value):
    wb = openpyxl.load_workbook(io.BytesIO(ks()))
    wb.active['D2'], wb.active['E2'] = header, value
    output = io.BytesIO()
    wb.save(output)
    return output.getvalue()


@pytest.mark.parametrize('field,header', [('customer', 'Заказчик'), ('contractor', 'Подрядчик')])
def test_conflicting_parties_are_unresolved_with_every_source_cell(context, field, header):
    payload = _repeated_party_book(header, 'ООО «Другой участник»')
    snapshot = parsed(('Conflict.xlsx', payload))
    ledger, = snapshot['ledgers']
    assert not ledger[field]
    assert field not in ledger['identity_source']
    assert len(ledger['party_evidence'][field]) == 2
    assert ledger['party_evidence'][field][1]['raw'] == 'ООО «Другой участник»'
    assert ledger['party_evidence'][field][1]['source']['cell'] == 'E2'
    provide(context, snapshot, [rss_contract()])
    view = contracts.build('Example', '2026-11-06')
    assert view['rows'] == []
    unresolved, = view['unresolved_sources']
    assert 'разные наименования' in unresolved['identity_warnings'][0]
    assert unresolved['party_evidence'] == ledger['party_evidence']


@pytest.mark.parametrize('header,value', [
    ('Заказчик', 'ооо "Заказчик"'),
    ('Подрядчик', 'ооо “Подрядчик”'),
])
def test_equivalent_repeated_party_names_are_not_conflicts(context, header, value):
    snapshot = parsed(('Repeat.xlsx', _repeated_party_book(header, value)))
    provide(context, snapshot, [rss_contract()])
    view = contracts.build('Example', '2026-11-06')
    assert len(view['rows']) == 1 and not view['unresolved_sources']
    assert view['rows'][0]['amount'] == 1000


def test_party_normalization_preserves_equivalent_yo_but_not_business_punctuation():
    rows = [['Подрядчик', 'ООО «Ёлка, Север»'], ['Подрядчик', 'ооо "елка, Север"']]
    assert ledgers._metadata(rows)['contractor'] == 'ООО «Ёлка, Север»'
    rows.append(['Подрядчик', 'ООО «Ёлка Север»'])
    assert not ledgers._metadata(rows)['contractor']


@pytest.mark.parametrize('placeholder', ['""', '« »'])
def test_quote_only_party_is_not_an_identity_candidate(placeholder):
    rows = [['Подрядчик', placeholder]]
    assert not ledgers._metadata(rows)['contractor']
    rows.append(['Подрядчик', 'ООО «Учебный подрядчик»'])
    meta = ledgers._metadata(rows)
    assert meta['contractor'] == 'ООО «Учебный подрядчик»'
    assert meta['identity_source']['contractor']['cell'] == 'B2'
    assert len(meta['party_evidence']['contractor']) == 2


def test_pre_party_evidence_snapshot_is_reparsed_from_immutable_original(context):
    snapshot = ledgers.store_archive('Example', archive([
        ('Conflict.xlsx', _repeated_party_book('Подрядчик', 'ООО «Другой участник»'))]), '2026-11-06')
    path = next(ledgers._root('Example').glob('*.json'))
    saved = json.loads(path.read_text())
    for ledger in saved['ledgers']:
        ledger.pop('party_evidence')
        ledger['contractor'] = 'ООО «Другой участник»'  # The prior last-wins result.
    path.write_text(json.dumps(saved), encoding='utf-8')
    original_bytes = path.read_bytes()
    context.setattr(contracts, '_archive', ARCHIVE_READER)
    view = contracts.build('Example', '2026-11-06')
    assert view['rows'] == [] and len(view['unresolved_sources']) == 1
    assert len(view['unresolved_sources'][0]['party_evidence']['contractor']) == 2
    assert path.read_bytes() == original_bytes


def test_missing_original_cannot_make_old_last_wins_parties_authoritative(context):
    ledgers.store_archive('Example', archive([('Saved.xlsx', ks())]), '2026-11-06')
    path = next(ledgers._root('Example').glob('*.json'))
    saved = json.loads(path.read_text())
    for ledger in saved['ledgers']:
        ledger.pop('party_evidence')
    path.write_text(json.dumps(saved), encoding='utf-8')
    original_bytes = path.read_bytes()
    next(ledgers._root('Example').glob('*.zip')).unlink()
    context.setattr(contracts, '_archive', ARCHIVE_READER)
    view = contracts.build('Example', '2026-11-06')
    assert view['rows'] == []
    unresolved, = view['unresolved_sources']
    assert not unresolved['contractor']
    assert 'Стороны договора не подтверждены' in unresolved['identity_warnings'][0]
    evidence, = unresolved['party_evidence']['contractor']
    assert evidence['raw'] == 'ООО «Подрядчик»'
    assert evidence['origin'] == 'unverified_saved_header'
    assert evidence['source']['cell'] == 'C2'
    assert path.read_bytes() == original_bytes


@pytest.mark.parametrize('width', [390, 1440])
def test_conflicting_party_evidence_is_visible_and_escaped_in_real_page(context, width):
    from test_monitor_cumulative_controls import browser_page
    from playwright.sync_api import expect
    marker = '<img src=x onerror="window.partyHeaderXSS=1">'
    snapshot = parsed(('Conflict.xlsx', _repeated_party_book('Подрядчик', marker)))
    provide(context, snapshot)
    register = contracts.build('Example', '2026-11-06')
    with browser_page(width) as (page, responses, errors):
        responses.data = register
        page.locator('#contractsTab').click()
        warning = page.locator('#contractsWarnings')
        expect(warning).to_contain_text('разные наименования подрядчика')
        expect(warning).to_contain_text(marker)
        expect(warning).to_contain_text('E2')
        expect(page.locator('#contractsMsg')).to_contain_text('Договоров из накопительных: 0')
        assert warning.locator('img').count() == 0
        assert page.evaluate('window.partyHeaderXSS') is None
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert not errors


@pytest.mark.parametrize('override', [{'customer': 'ООО «Другой заказчик»'}, {'contract_date': None},
                                      {'contract_date': '2026-01-02'}])
def test_incomplete_or_different_rss_identity_cannot_enrich_price(context, override):
    provide(context, parsed(), [rss_contract(**override)])
    row, = contracts.build('Example', '2026-11-06')['rows']
    assert row['amount'] is None and row['completion_ratio'] is None
    assert row['completed'] == 400
    assert row['financial_sources'] == []


def test_undated_yearly_money_is_visible_reference_not_asof_execution(context):
    snapshot = parsed()
    for item in snapshot['ledgers'][0]['items']:
        for period in item['periods']:
            period['date_start'] = period['date_end'] = None
    provide(context, snapshot, [rss_contract()])
    row, = contracts.build('Example', '2026-11-06')['rows']
    assert row['completed'] is None and row['completion_ratio'] is None
    ref, = row['reported_performance_sources']
    assert ref['completed'] == 400 and ref['period_year'] == 2026
    assert 'период закрытия не установлен' in ref['label']


def test_existing_archive_is_read_with_header_cells_without_reupload(context, tmp_path):
    payload = archive([('KS.xlsx', ks())])
    ledgers.store_archive('Example', payload, '2026-11-06', 'KS.zip')
    path = next(ledgers._root('Example').glob('*.json'))
    saved = json.loads(path.read_text())
    saved.pop('identity_schema', None)
    for item in saved['ledgers']:
        item.pop('identity_source', None)
        item['contract_date'] = '2026-09-09'  # An old parser's untrusted adjacent-date result.
    path.write_text(json.dumps(saved), encoding='utf-8')
    context.setattr(contracts, '_archive', ARCHIVE_READER)
    view = contracts.build('Example', '2026-11-06')
    assert len(view['rows']) == 1
    assert view['rows'][0]['contract_date'] == '2026-01-01'
    assert view['rows'][0]['identity_source']['contract_date']['cell'] == 'B4'
    assert json.loads(path.read_text())['ledgers'][0]['contract_date'] == '2026-09-09'  # Read-only refresh.


@pytest.mark.parametrize('width', [390, 1440])
def test_real_monitor_shows_cumulative_count_sources_quarantine_and_printed_values(context, width):
    snapshot = parsed(('One.xlsx', ks()), ('Two.xlsx', ks(number='B-24', date=dt.date(2026, 2, 1))),
                      ('Unresolved.xlsx', ks(number='C-1', date='03.07.124')))
    provide(context, snapshot, [rss_contract()])
    view = contracts.build('Example', '2026-11-06')
    from test_monitor_cumulative_controls import browser_page
    from playwright.sync_api import expect
    from pypdf import PdfReader
    with browser_page(width) as (page, responses, errors):
        responses.data = view
        page.locator('#contractsTab').click()
        expect(page.locator('#contractsMsg')).to_contain_text('Договоров из накопительных: 2')
        expect(page.locator('#contractsMsg')).to_contain_text('Листов накопительных: 3')
        expect(page.locator('#contractsWarnings')).to_contain_text('03.07.124')
        expect(page.locator('#contractsWarnings')).to_contain_text('Unresolved.xlsx')
        expect(page.locator('#contractsRows')).to_contain_text('A-12')
        expect(page.locator('#contractsRows')).to_contain_text('B-24')
        expect(page.locator('#contractsRows')).to_contain_text('Дата из шапки')
        expect(page.locator('#contractsRows')).to_contain_text('B4')
        expect(page.locator('#contractsRows')).to_contain_text('400 ₽')
        expect(page.locator('#contractsSource')).to_contain_text('Общий реестр РСС')
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        if width == 1440:
            text = ' '.join(' '.join((x.extract_text() or '').split())
                            for x in PdfReader(io.BytesIO(page.pdf())).pages)
            assert 'A-12' in text and 'B-24' in text
            assert '400' in text and 'по накопительным' in text
            # Technical evidence remains in closed source details, not in the working printout.
            assert 'Номер из шапки' not in text and '03.07.124' not in text
        assert not errors


def test_unknown_archive_keeps_sources_visible_without_rss_fallback_in_browser(context):
    provide(context, None, [rss_contract()])
    view = contracts.build('Example', '2026-11-06')
    from test_monitor_cumulative_controls import browser_page
    from playwright.sync_api import expect
    with browser_page(390) as (page, responses, errors):
        responses.data = view
        page.locator('#contractsTab').click()
        expect(page.locator('#contractsMsg')).to_contain_text('Договоров из накопительных: 0')
        expect(page.locator('#contractsRows')).to_contain_text('Загрузите архив накопительных')
        assert page.locator('tr[data-contract-id]').count() == 0
        assert not errors


def test_rss_header_customer_and_contract_date_allow_exact_enrichment_but_l_is_reference(context):
    snapshot = parsed()
    provide(context, snapshot)
    folder = monitor._project_dir('Example') / 'estimate'
    folder.mkdir(parents=True)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Реестр договоров'
    ws['A1'] = 'Заказчик: ООО «Заказчик»'
    ws['D6'], ws['H6'], ws['L6'] = 'Дата договора', 'Сумма договора с НДС', 'Оплачено'
    ws['B9'], ws['C9'], ws['D9'] = 'ООО «Подрядчик»', 'A-12', dt.date(2026, 1, 1)
    ws['H9'], ws['L9'] = 1000, 900
    wb.save(folder / '2026-11-06.xlsx')
    context.setattr(contracts, '_read_rss', RSS_READER)
    row, = contracts.build('Example', '2026-11-06')['rows']
    assert row['amount'] == 1000 and row['completed'] == 400
    ref, = row['financial_sources']
    assert ref['completed'] == 900 and 'Оплачено' in ref['completed_label']
    assert ref['source']['completed_cell'] == 'L9'
    # A different or unlabelled H cannot silently become the full contract price.
    ws['H6'] = 'Оплачено'
    wb.save(folder / '2026-11-06.xlsx')
    row, = contracts.build('Example', '2026-11-06')['rows']
    assert row['amount'] is None and row['completion_ratio'] is None
    assert row['completed'] == 400


def test_amendment_reference_is_not_the_base_contract_header(context):
    snapshot = parsed(('Amendment.xlsx', ks(number='ДС № 1 от 01.02.2026')))
    provide(context, snapshot)
    view = contracts.build('Example', '2026-11-06')
    assert view['rows'] == [] and len(view['unresolved_sources']) == 1
    assert not snapshot['ledgers'][0]['contract']


def test_rss_without_a_stated_customer_completes_the_contract_and_says_why(context):
    provide(context, parsed(), [rss_contract(customer='')])
    view = contracts.build('Example', '2026-11-06')
    row, = view['rows']
    assert row['amount'] == 1000 and row['rss_match']['status'] == 'matched'


@pytest.mark.parametrize('rss_contractor,rss_number', [
    ('Общество с ограниченной ответственностью «Подрядчик»', 'A-12'),
    ('ООО «Подрядчик»', 'Договор подряда № A-12'),
    ('ооо  "ПОДРЯДЧИК"', '№A-12')])
def test_explicit_legal_form_and_number_sign_normalisation(context, rss_contractor, rss_number):
    provide(context, parsed(), [rss_contract(contract=rss_number, contractor=rss_contractor)])
    row, = contracts.build('Example', '2026-11-06')['rows']
    assert row['amount'] == 1000


# These ids were produced by the released 48e8ac68 reader. They address
# persisted manual deadlines and daily-work confirmations, not RSS aliases.
PERSISTED_IDENTITIES = [
    ('Общество с ограниченной ответственностью «Подрядчик»', 'A-12',
     'b8a9a3a62ab41d4f927426ae440d3f890b9a49828242dc51a90d894fa4148f81'),
    ('ООО «Подрядчик»', 'Договор подряда № A-12',
     '5ea3642ee3ab40e395546ce6a176f8e4be646082d30d2d08c2185cae71754e76'),
]


@pytest.mark.parametrize('party,number,persisted_id', PERSISTED_IDENTITIES)
def test_reference_aliases_preserve_persisted_contract_id_and_manual_deadline(
        context, party, number, persisted_id):
    snapshot = parsed()
    snapshot['ledgers'][0].update(contractor=party, contract=number)
    provide(context, snapshot, [rss_contract()])
    path = contracts._terms_path('Example')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({persisted_id: {
        'deadline': '2026-12-31', 'note': 'Срок по отдельному основанию',
        'updated_at': '2026-11-01T12:00:00+00:00'}}, ensure_ascii=False))
    original = path.read_bytes()

    row, = contracts.build('Example', '2026-11-06')['rows']

    assert row['id'] == persisted_id
    assert row['deadline'] == '2026-12-31'
    assert row['manual_deadline_reference']['applicable_to_cut']
    assert row['manual_deadline_reference']['note'] == 'Срок по отдельному основанию'
    assert row['amount'] == 1000 and row['rss_match']['status'] == 'matched'
    assert path.read_bytes() == original  # Reading does not migrate private state.


@pytest.mark.parametrize('party,number,persisted_id', PERSISTED_IDENTITIES)
def test_reference_aliases_preserve_saved_manual_work_confirmation(
        context, party, number, persisted_id):
    import developaid_monitor_contract_links as links

    snapshot = parsed()
    snapshot['ledgers'][0].update(contractor=party, contract=number)
    provide(context, snapshot, [rss_contract()])
    folder = monitor._project_dir('Example') / 'daily'
    folder.mkdir(parents=True)
    (folder / '2026-11-05.json').write_text(json.dumps({
        'date': '2026-11-05', 'parsed': {
            'contractors': [{'name': party}],
            'works': [{'contractor': party, 'line': 'Устройство стены'}]}}, ensure_ascii=False))
    register = contracts.build('Example', '2026-11-06')
    item, = links._evidence('Example', register, '2026-11-06')
    path = links._path('Example')
    path.write_text(json.dumps({'version': 1, 'links': {item['id']: {
        'contract_id': persisted_id, 'evidence_id': item['id'],
        'signature': item['signature'], 'confirmed': True,
        'confirmed_at': '2026-11-05T12:00:00+00:00',
        'source_date': '2026-11-05', 'basis': 'manual',
        'candidate_contract_ids': [persisted_id]}}}, ensure_ascii=False))
    original = path.read_bytes()

    result = links.enrich('Example', contracts.build('Example', '2026-11-06'), '2026-11-06')

    row, = result['rows']
    linked, = row['reconciliation']['daily_evidence']
    assert row['id'] == persisted_id
    assert linked['contract_id'] == persisted_id and linked['link_basis'] == 'manual'
    assert linked['match_status'] == 'confirmed'
    assert result['unmatched_works'] == []
    assert path.read_bytes() == original


@pytest.mark.parametrize('party,number,persisted_id', PERSISTED_IDENTITIES)
def test_reference_aliases_do_not_merge_prior_contracts_or_choose_one_for_rss(
        context, party, number, persisted_id):
    snapshot = parsed(('Decorated.xlsx', ks()), ('Plain.xlsx', ks()))
    snapshot['ledgers'][0].update(contractor=party, contract=number)
    provide(context, snapshot, [rss_contract()])

    view = contracts.build('Example', '2026-11-06')

    assert len(view['rows']) == 2
    assert {row['id'] for row in view['rows']} == {
        persisted_id, 'f09d26b1916c812e61460a12fe188ed72dd15c9aff7053bdc03cd43a947a7385'}
    assert all(row['amount'] is None and row['rss_match']['status'] == 'differs'
               for row in view['rows'])
    assert all(row['performance_source_count'] == 1 for row in view['rows'])
    assert any('сразу к нескольким договорам' in warning for warning in view['warnings'])


@pytest.mark.parametrize('rss_contractor,rss_number', [('ООО «Подрядчик-2»', 'A-12'), ('ООО «Подрядчик»', 'A-121')])
def test_similar_but_different_party_or_number_is_not_joined(context, rss_contractor, rss_number):
    provide(context, parsed(), [rss_contract(contract=rss_number, contractor=rss_contractor)])
    row, = contracts.build('Example', '2026-11-06')['rows']
    assert row['amount'] is None


def test_unmatched_contract_names_the_attribute_that_differed(context):
    provide(context, parsed(), [rss_contract(contract_date='2026-01-02')])
    row, = contracts.build('Example', '2026-11-06')['rows']
    match = row['rss_match']
    assert match['status'] == 'differs' and match['candidates'][0]['differences'] == ['дата договора']
    assert 'дата договора' in match['text']


def test_rss_row_fitting_two_cumulative_contracts_is_joined_to_neither(context):
    snapshot = parsed(('One.xlsx', ks()), ('Two.xlsx', ks()))
    snapshot['ledgers'][1]['customer'] = 'ООО «Второй заказчик»'
    provide(context, snapshot, [rss_contract(customer='')])
    view = contracts.build('Example', '2026-11-06')
    assert len(view['rows']) == 2 and all(r['amount'] is None for r in view['rows'])
    assert any('сразу к нескольким договорам' in w for w in view['warnings'])


@pytest.mark.parametrize('width', [390, 1440])
def test_real_page_is_a_table_and_shows_why_rss_did_not_complete(context, width):
    from playwright.sync_api import expect
    from test_monitor_cumulative_controls import browser_page
    provide(context, parsed(), [rss_contract(contract_date='2026-01-02')])
    view = contracts.build('Example', '2026-11-06')
    with browser_page(width) as (page, responses, errors):
        responses.data = view
        page.locator('#contractsTab').click()
        table = page.locator('#contractsRows table.contract-register')
        expect(table).to_be_visible()
        assert table.evaluate('(t)=>getComputedStyle(t).display') == 'table'
        assert table.evaluate('(t)=>getComputedStyle(t.querySelector("thead")).position') != 'absolute'
        expect(page.locator('#contractsRows .contract-rss-why')).to_contain_text('не совпало')
        expect(page.locator('#contractsRows .contract-rss-why')).to_contain_text('дата договора')
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path=f'/tmp/contracts-table-{width}.png', full_page=True)
        assert not errors
