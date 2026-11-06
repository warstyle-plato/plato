from __future__ import annotations

import concurrent.futures
import datetime as dt
import io
import stat
import struct
import zipfile

import openpyxl
import pytest

import developaid_monitor as monitor
import developaid_monitor_ledgers as ledgers


def book(*, split=False, actual=4, formula=False, styled=False):
    w = openpyxl.Workbook()
    s = w.active
    s.title = 'Работы'
    s.append(['Генподрядчик', None, 'ООО «Заказчик», ИНН 1234567890'])
    s.append(['Подрядчик', None, 'ООО «Подрядчик», ИНН 0987654321'])
    s.append(['Договор', 'А-12'])
    s.append(['Дата', dt.date(2026, 1, 1)])
    s.append(['Сметная (договорная) стоимость в соответствии с договором', 1000])
    s.append(['№ п/п', '№ позиции по смете', 'Наименование работ и затрат', 'Ед. изм.',
              'Кол-во работ по смете', 'Цена', 'Сметная (договорная) стоимость, руб.', 'Выполнено работ'])
    if split:
        # Total quantities: material N, installation O, separate money P/Q.
        s.cell(7, 8, 'КС-2 № 1')
        s.cell(7, 14, '2026 год')
        for c, text in {8:'Количество (материалы)', 9:'Количество (СМР)', 10:'Стоимость материалы',
                        11:'Стоимость СМР', 12:'Стоимость с начала строительства',
                        14:'Количество (материалы)', 15:'Количество (СМР)',
                        16:'Стоимость материалы', 17:'Стоимость СМР',
                        18:'Остаток количество', 19:'Остаток количество СМР'}.items():
            s.cell(8, c, text)
        s.append([1, '1.1', 'Монтаж каркаса', 'м2', 10, 100, 1000, 8, actual, 500, 200,
                  700, None, 8, actual, 500, 200, -2, None])
    else:
        s.cell(7, 8, 'Выполнение № 1 (01.01.2026 - 31.01.2026)')
        s.cell(7, 11, 'Выполнение № 2 (01.02.2026 - 28.02.2026)')
        s.cell(7, 14, '2026 год')
        for c, text in {8:'Количество',9:'Стоимость',10:'Стоимость с начала строительства',
                        11:'Количество',12:'Стоимость',13:'Стоимость с начала строительства',
                        14:'Количество',15:'Стоимость',16:'Остаток'}.items():
            s.cell(8, c, text)
        s.append([1, '1.1', 'Устройство стены', 'м3', 10, 100, 1000,
                  2, 200, 200, 2, 200, 400, '=H9+K9' if formula else actual, 400, 10-actual])
    s.append([2, '1.2', 'Вторая работа', 'шт', 2, 10, 20, 0, 0, 0, 0, 0, 0,
              0, 0, 0, 0, 0, 0])
    s.append([None, None, 'ИТОГО', 'Х', 12, None, 1020])
    if styled:
        s.cell(400, 1000).number_format = '0.00'
    out = io.BytesIO()
    w.save(out)
    return out.getvalue()


def summary(*, amendment_label='Дополнительные работы', amendment_amount=1500,
            amount_header='Сумма договора/ доп.соглашения', act_header='Сумма по КС'):
    w = openpyxl.Workbook()
    s = w.active
    s.title = 'Закрытие'
    s.append(['ООО «Заказчик»'])
    s.append([])
    s.append(['ООО «Первый подрядчик»', 'Работы выполнены'])
    head = ['Вид работ', '№ договора/ доп.соглашения, дата', amount_header,
            '№ КС', 'Дата КС', act_header, 'Аванс']
    s.append(head)
    s.append(['Работы', 'Договор № П-1 от 01.01.2026', 1000, 1, dt.date(2026, 1, 31), 100])
    s.append([amendment_label, 'ДС № 1 от 01.02.2026', amendment_amount, 2, dt.date(2026, 2, 28), 200])
    s.append(['ИТОГО', None, None, None, None, 300])
    s.append(['ООО «Второй подрядчик»', 'Работы выполнены'])
    s.append(head)
    s.append(['Работы', 'Договор № П-2 от 03.01.2026', 2000, 1, dt.date(2026, 2, 28), 500])
    out = io.BytesIO()
    w.save(out)
    return out.getvalue()


def archive(files=None):
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, payload in (files or [('Накопительная.xlsx', book())]):
            z.writestr(name, payload)
    return out.getvalue()


def biff_book():
    """Tiny synthetic BIFF8 workbook, no OLE container or external dependency."""
    def rec(kind, payload=b''):
        return struct.pack('<HH', kind, len(payload)) + payload
    def bof(kind):
        return rec(0x0809, struct.pack('<HHHHII', 0x0600, kind, 0x0DBB, 1996, 0, 0x0600))
    cells = [
        (0, 0, 'Подрядчик'), (0, 2, 'ООО «Подрядчик»'),
        (1, 0, 'Договор'), (1, 1, 'Т-1'),
        (2, 0, 'Дата'), (2, 1, '01.01.2026'),
        (3, 0, '№ п/п'), (3, 1, 'Позиция'), (3, 2, 'Наименование работ'),
        (3, 3, 'Ед. изм.'), (3, 4, 'Кол-во'), (3, 6, 'Сметная (договорная) стоимость'),
        (4, 7, 'Январь'), (4, 10, '2026 год'),
        (5, 7, 'Количество'), (5, 8, 'Стоимость'), (5, 9, 'Стоимость с начала'),
        (5, 10, 'Количество'), (5, 11, 'Стоимость'), (5, 12, 'Остаток'),
        (6, 0, 1), (6, 1, '1.1'), (6, 2, 'Монтаж'), (6, 3, 'шт'),
        (6, 4, 10), (6, 6, 1000), (6, 7, 3), (6, 8, 300), (6, 9, 300),
        (6, 10, 3), (6, 11, 300), (6, 12, 7),
    ]
    sheet = bof(0x0010)
    for r, c, value in cells:
        if isinstance(value, (float, int)):
            sheet += rec(0x0203, struct.pack('<HHHd', r, c, 0, value))
        else:
            sheet += rec(0x0204, struct.pack('<HHHHB', r, c, 0, len(value), 1)+value.encode('utf-16le'))
    sheet += rec(0x000A)
    # BOF + one BOUNDSHEET + EOF; replace the fixed-length sheet offset.
    title = 'Лист'.encode('utf-16le')
    bound_len = 4 + 6 + 2 + len(title)
    prefix = bof(0x0005)
    offset = len(prefix) + bound_len + 4
    return prefix + rec(0x0085, struct.pack('<IBBBB', offset, 0, 0, 4, 1)+title) + rec(0x000A) + sheet


def test_quantities_are_annual_totals_not_sum_of_repeated_cumulative_money():
    parsed = ledgers.parse_archive(archive(), 'Импорт.zip')
    item = parsed['ledgers'][0]['items'][0]
    assert item['plan_quantity'] == 10
    assert item['completed_quantity'] == 4
    assert item['completed_amount'] == 400
    assert [p['amount'] for p in item['periods']] == [200, 200]
    assert item['periods'][1]['date_end'] == '2026-02-28'
    assert item['source']['completed_quantity_cell'] == 'N9'
    assert parsed['ledgers'][0]['amount_scope'] == 'year_or_sheet'
    assert parsed['ledgers'][0]['contract_amount'] == 1000
    assert len(parsed['ledgers'][0]['items']) == 2


def test_delivery_and_installation_never_add_to_physical_completion():
    parsed = ledgers.parse_archive(archive([('Работы.xlsm', book(split=True))]))
    item = parsed['ledgers'][0]['items'][0]
    assert item['completed_quantity'] == 4
    assert item['material_quantity'] == 8
    assert item['quantity_kind'] == 'installation'
    assert item['completed_amount'] == 700
    assert item['source']['completed_quantity_cell'] == 'O9'
    assert any('Поставку' in w for w in parsed['ledgers'][0]['warnings'])


def test_missing_formula_cache_is_not_zero_and_overplan_is_not_capped():
    missing = ledgers.parse_archive(archive([('Missing.xlsx', book(formula=True))]))['ledgers'][0]['items'][0]
    assert missing['completed_quantity'] is None
    assert missing['warnings']
    over = ledgers.parse_archive(archive([('Over.xlsx', book(actual=15))]))['ledgers'][0]['items'][0]
    assert over['completed_quantity'] == 15
    assert any('границы' in w for w in over['warnings'])


def test_ambiguous_contract_amendments_invalidate_full_price_and_keep_party_identity():
    rows = ledgers.parse_archive(archive([('Сводная.xlsx', summary())]))['summary_contracts']
    assert len(rows) == 2
    first, second = rows
    assert first['contractor'] == 'ООО «Первый подрядчик»'
    assert first['amount'] is None
    assert first['amount_scope'] == 'ambiguous_amendment'
    assert first['amount_date'] == '2026-02-01'
    assert [v['amount'] for v in first['amount_versions']] == [1000, None]
    assert first['amount_versions'][-1]['stated_amount'] == 1500
    assert [a['amount'] for a in first['acts']] == [100, 200]
    assert second['contractor'] == 'ООО «Второй подрядчик»'
    assert second['contract'] == 'П-2'
    assert second['deadline'] is None


def test_only_explicit_new_whole_contract_price_can_replace_base():
    ambiguous = ledgers.parse_archive(archive([('Summary.xlsx', summary(amendment_amount=200))]))['summary_contracts'][0]
    assert ambiguous['amount'] is None  # Neither 200 nor an invented 1200 nor the stale base 1000.
    assert ambiguous['amount_versions'][-1]['stated_amount'] == 200
    declared = ledgers.parse_archive(archive([('Summary.xlsx', summary(
        amendment_label='Новая полная стоимость договора', amendment_amount=1200))]))['summary_contracts'][0]
    assert declared['amount'] == 1200
    assert declared['amount_scope'] == 'full_contract'


def test_contract_and_act_vat_bases_are_separate_evidence():
    parsed = ledgers.parse_archive(archive([('Summary.xlsx', summary(
        amount_header='Сумма договора с НДС', act_header='Сумма по КС без НДС'))]))['summary_contracts']
    assert parsed[1]['amount_basis'] == 'with_vat'
    assert parsed[1]['amount_versions'][0]['amount_basis'] == 'with_vat'
    assert parsed[1]['acts'][0]['amount_basis'] == 'without_vat'
    assert 'без НДС' in parsed[1]['acts'][0]['source']['amount_header']


def test_vat_qualifier_in_same_column_header_prefix_is_retained():
    w = openpyxl.load_workbook(io.BytesIO(summary()))
    s = w.active
    s.cell(3, 3, 'с НДС')
    s.cell(3, 6, 'без НДС')
    raw = io.BytesIO()
    w.save(raw)
    parsed = ledgers.parse_archive(archive([('Summary.xlsx', raw.getvalue())]))['summary_contracts'][0]
    assert parsed['amount_basis'] == 'with_vat'
    assert parsed['acts'][0]['amount_basis'] == 'without_vat'


def test_xls_biff_is_supported():
    data = ledgers.parse_archive(archive([('Работы.xls', biff_book())]))
    assert data['ledgers'][0]['items'][0]['completed_quantity'] == 3
    assert data['ledgers'][0]['contract'] == 'Т-1'


def test_formatted_empty_columns_do_not_reject_actual_workbook():
    parsed = ledgers.parse_archive(archive([('Формат.xlsx', book(styled=True))]))
    assert parsed['quantity_rows_count'] == 2


@pytest.mark.parametrize('name', ['../secret.xlsx', '/secret.xlsx', 'A/../secret.xlsx',
                                 'A/./secret.xlsx', 'A//secret.xlsx',
                                 'C:\\secret.xlsx', 'A\\secret.xlsx', 'bad\x00.xlsx'])
def test_archive_paths_are_rejected(name):
    # ZipFile truncates a NUL itself, so exercise the name validator directly.
    if '\x00' in name:
        with pytest.raises(ledgers.LedgerProblem):
            ledgers._safe_name(name)
    else:
        with pytest.raises(ledgers.LedgerProblem):
            ledgers.parse_archive(archive([(name, book())]))


def test_symlinks_nested_archives_duplicate_names_and_unsupported_files_fail():
    link = zipfile.ZipInfo('link.xlsx')
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as z:
        z.writestr(link, b'/private')
    candidates = [out.getvalue(), archive([('Nested.zip', archive())]),
                  archive([('Work.xlsx', book()), ('work.xlsx', book())]),
                  archive([('Readme.txt', b'unsupported')])]
    for data in candidates:
        with pytest.raises(ledgers.LedgerProblem):
            ledgers.parse_archive(data)


def test_outer_and_inner_zip_bombs_and_real_nonempty_far_columns_fail(monkeypatch):
    monkeypatch.setattr(ledgers, 'MAX_RATIO', 5)
    with pytest.raises(ledgers.LedgerProblem):
        ledgers.parse_archive(archive([('Bomb.xlsx', b'0'*10000)]))
    monkeypatch.setattr(ledgers, 'MAX_RATIO', 1000)
    bad = io.BytesIO()
    with zipfile.ZipFile(bad, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('xl/worksheets/sheet1.xml', b'0'*1000000)
    with pytest.raises(ledgers.LedgerProblem):
        ledgers.parse_archive(archive([('Inner.xlsx', bad.getvalue())]))
    w = openpyxl.load_workbook(io.BytesIO(book()))
    w.active.cell(9, 1000, 'actual value outside supported grid')
    raw = io.BytesIO()
    w.save(raw)
    with pytest.raises(ledgers.LedgerProblem):
        ledgers.parse_archive(archive([('Far.xlsx', raw.getvalue())]))


def test_dtd_and_entity_declarations_are_rejected():
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as z:
        z.writestr('xl/worksheets/sheet1.xml', b'<!DOCTYPE x [<!ENTITY a "value">]><x/>')
    with pytest.raises(ledgers.LedgerProblem):
        ledgers.parse_archive(archive([('Entity.xlsx', out.getvalue())]))


def test_failed_import_creates_no_partial_snapshot_and_messages_are_safe(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, '_SNAPSHOT_DIR', tmp_path)
    data = archive([('Valid.xlsx', book()), ('Broken.xlsx', b'private secret error body'), ('Later.xlsx', book())])
    with pytest.raises(ledgers.LedgerProblem) as error:
        ledgers.store_archive('Project', data, '2026-03-01', 'Source.zip')
    assert 'Broken.xlsx' in str(error.value)
    assert 'private secret error body' not in str(error.value)
    assert [(f['filename'], f['status']) for f in error.value.files] == [
        ('Valid.xlsx', 'parsed'), ('Broken.xlsx', 'failed'), ('Later.xlsx', 'not_read')]
    assert not list(tmp_path.rglob('*.json'))
    assert not list(tmp_path.rglob('*.zip'))


def test_immutable_idempotent_snapshots_asof_selection_private_modes(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, '_SNAPSHOT_DIR', tmp_path)
    first = archive()
    stored = ledgers.store_archive('Project', first, '2026-03-01', 'Source.zip')
    same = ledgers.store_archive('Project', first, '2026-03-01', 'Source.zip')
    assert same['duplicate'] is True
    assert same['snapshot_id'] == stored['snapshot_id']
    with pytest.raises(ledgers.LedgerConflict):
        ledgers.store_archive('Project', archive([('Changed.xlsx', book(actual=8))]), '2026-03-01')
    ledgers.store_archive('Project', archive([('New.xlsx', book(actual=8))]), '2026-04-01')
    assert ledgers.latest_snapshot('Project', '2026-02-28') is None
    assert ledgers.latest_snapshot('Project', '2026-03-02')['snapshot_id'] == stored['snapshot_id']
    assert ledgers.latest_snapshot('Project', '2026-04-01')['ledgers'][0]['items'][0]['completed_quantity'] == 8
    assert len(ledgers.list_snapshots('Project')) == 2
    for path in tmp_path.rglob('*'):
        if path.is_file():
            assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(next(tmp_path.glob('*/cumulative')).stat().st_mode) == 0o700


def test_two_workers_import_same_snapshot_once(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, '_SNAPSHOT_DIR', tmp_path)
    data = archive()
    with concurrent.futures.ThreadPoolExecutor(2) as pool:
        values = list(pool.map(lambda _: ledgers.store_archive('Project', data, '2026-03-01'), range(2)))
    assert {v['duplicate'] for v in values} == {True, False}
    assert len(ledgers.list_snapshots('Project')) == 1
    assert len(list(tmp_path.rglob('*.zip'))) == 1


@pytest.mark.parametrize('date', ['2026-02-30', '2026-01-01/../../', '', 'today'])
def test_invalid_snapshot_dates_do_not_write(date, tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, '_SNAPSHOT_DIR', tmp_path)
    with pytest.raises(ledgers.LedgerProblem):
        ledgers.store_archive('Project', archive(), date)
    assert not list(tmp_path.iterdir())


def test_explicit_read_companion_and_unread_lists():
    parsed = ledgers.parse_archive(archive([('Работы.xlsx', book()), ('__MACOSX/._Работы.xlsx', b'metadata')]))
    assert parsed['read_files'] == ['Работы.xlsx']
    assert parsed['companion_files'] == ['__MACOSX/._Работы.xlsx']
    assert parsed['unread_files'] == []


def test_encrypted_member_flags_are_rejected_before_read():
    raw = bytearray(archive())
    local = raw.index(b'PK\x03\x04')
    central = raw.index(b'PK\x01\x02')
    struct.pack_into('<H', raw, local+6, struct.unpack_from('<H', raw, local+6)[0] | 1)
    struct.pack_into('<H', raw, central+8, struct.unpack_from('<H', raw, central+8)[0] | 1)
    with pytest.raises(ledgers.LedgerProblem, match='зашифрованные'):
        ledgers.parse_archive(bytes(raw))


def test_short_source_year_is_valid_but_malformed_year_is_missing():
    assert ledgers._day('ДС № 1 от 14.08.25') == '2025-08-14'
    assert ledgers._day('02.06.125') is None


def test_utf16_xml_declarations_are_also_rejected():
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as z:
        z.writestr('xl/worksheets/sheet1.xml', '<!DOCTYPE x [<!ENTITY a "value">]><x/>'.encode('utf-16'))
    with pytest.raises(ledgers.LedgerProblem, match='XML'):
        ledgers.parse_archive(archive([('Entity.xlsx', out.getvalue())]))


def test_all_files_count_and_expanded_size_are_bounded(monkeypatch):
    monkeypatch.setattr(ledgers, 'MAX_FILES', 1)
    with pytest.raises(ledgers.LedgerProblem, match='много файлов'):
        ledgers.parse_archive(archive([('One.xlsx', book()), ('Two.xlsx', book())]))
    monkeypatch.setattr(ledgers, 'MAX_FILES', 100)
    monkeypatch.setattr(ledgers, 'MAX_UNPACKED_BYTES', 100)
    with pytest.raises(ledgers.LedgerProblem, match='предел'):
        ledgers.parse_archive(archive())


def test_reading_unrelated_or_undated_sources_does_not_guess_contract_deadline():
    row = ledgers.parse_archive(archive())['ledgers'][0]
    assert 'deadline' not in row
    assert row['period_year'] == 2026
    assert row['contract_date'] == '2026-01-01'


def test_party_names_preserve_business_punctuation_but_not_address_fields():
    assert ledgers._party('ООО «Первый, второй», ИНН 1234567890') == 'ООО «Первый, второй»'


def test_store_protocol_preserves_file_sheet_and_row_warnings_without_full_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, '_SNAPSHOT_DIR', tmp_path)
    w = openpyxl.load_workbook(io.BytesIO(book(actual=15)))
    notes = w.create_sheet('Примечания')
    notes.cell(1, 1, 'Сопроводительные сведения')
    raw = io.BytesIO()
    w.save(raw)
    data = archive([('Source.xlsx', raw.getvalue())])
    result = ledgers.store_archive('Project', data, '2026-03-01')
    assert 'ledgers' not in result
    assert any(i['filename'] == 'Source.xlsx' and i['sheet'] == 'Работы' and i['row'] == 9
               and 'границы' in i['message'] for i in result['issues'])
    assert any(i['filename'] == 'Source.xlsx' and 'Примечания' in i['message']
               for i in result['issues'])
    assert any('год' in i['message'] for i in result['issues'])
    assert result['issues_count'] == len(result['issues'])
    assert result['issues_overflow_count'] == 0
    duplicate = ledgers.store_archive('Project', data, '2026-03-01')
    assert duplicate['duplicate'] is True
    assert duplicate['issues'] == result['issues']


def test_split_remaining_warning_is_visible_in_store_protocol(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, '_SNAPSHOT_DIR', tmp_path)
    result = ledgers.store_archive('Project', archive([('Stages.xlsx', book(split=True))]), '2026-03-01')
    assert any(i['filename'] == 'Stages.xlsx' and i['sheet'] == 'Работы' and i['row'] == 9
               and 'Остаток в книге' in i['message'] for i in result['issues'])


def test_protocol_caps_issues_but_reports_total_and_omitted_count():
    snapshot = {'files': [{'filename': 'Source.xlsx', 'warnings': ['File issue']}],
                'warnings': ['File issue'],
                'ledgers': [{'source': {'filename': 'Source.xlsx', 'sheet': 'Работы', 'row': 8},
                             'warnings': ['General issue'],
                             'items': [{'source': {'filename': 'Source.xlsx', 'sheet': 'Работы', 'row': i},
                                        'warnings': ['Row issue']} for i in range(1, 121)]}]}
    result = ledgers._import_result(snapshot, duplicate=False)
    assert len(result['issues']) == 100
    assert result['issues_count'] == 122
    assert result['issues_overflow_count'] == 22
    assert all(i['message'] == 'Row issue' for i in result['issues'])


def test_materialized_text_budget_is_shared_between_workbooks(monkeypatch):
    single = book()
    captured = {'text_bytes': 0}
    ledgers._read_workbook('One.xlsx', single, captured)
    monkeypatch.setattr(ledgers, 'MAX_MATERIALIZED_TEXT_BYTES', captured['text_bytes']+1)
    # Each workbook fits on its own, but a ZIP must share one aggregate budget.
    with pytest.raises(ledgers.LedgerProblem, match='объём текстовых ячеек'):
        ledgers.parse_archive(archive([('One.xlsx', single), ('Two.xlsx', single)]))


def test_oversized_individual_text_cell_is_rejected_before_ledger_normalization(monkeypatch):
    w = openpyxl.load_workbook(io.BytesIO(book()))
    w.active.cell(9, 3, 'а'*20001)
    raw = io.BytesIO()
    w.save(raw)
    called = []
    monkeypatch.setattr(ledgers, '_ledger', lambda *args: called.append(True))
    with pytest.raises(ledgers.LedgerProblem, match='длинная текстовая ячейка'):
        ledgers.parse_archive(archive([('Long.xlsx', raw.getvalue())]))
    assert not called
