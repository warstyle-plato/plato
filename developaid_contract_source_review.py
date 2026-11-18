"""Fixed, private projections of retained original KS workbooks.

Only the server selects archives, files, worksheets and header cells. Original
bytes are hashed and parsed, never returned or changed. This read does not
create a fact, link, date or model request.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import stat
import zipfile

import developaid_monitor_contracts as contracts
import developaid_monitor_ledgers as ledgers

MAX_ARCHIVES = 32
MAX_TOTAL_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_MATCHES = 64
MAX_ITEMS = 2000
MAX_PERIODS = 10000
MAX_HEADER_CELLS = 4000
MAX_RESULT_BYTES = 3 * 1024 * 1024


class SourceReviewProblem(contracts.ContractProblem):
    pass


class OriginalUnavailable(SourceReviewProblem):
    pass


def _original(project, snapshot_id, *, directory_fd=None):
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}-[0-9a-f]{64}', snapshot_id):
        raise SourceReviewProblem('Неверная версия сохранённого архива; проверка остановлена.')
    if directory_fd is None:
        root = ledgers._root(project)
        path = root / (snapshot_id + '.zip')
        if path.is_symlink() or path.resolve().parent != root.resolve():
            raise SourceReviewProblem('Исходный архив находится вне частного хранилища; проверка остановлена.')
    try:
        handle = path.open('rb') if directory_fd is None else os.fdopen(os.open(
            snapshot_id+'.zip', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd), 'rb')
        with handle:
            if directory_fd is not None and not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise SourceReviewProblem('Исходный архив не является обычным файлом.')
            raw = handle.read(ledgers.MAX_ARCHIVE_BYTES + 1)
    except OSError:
        raise OriginalUnavailable('Оригинал сохранённого архива недоступен. Его даты не объявлены отсутствующими.') from None
    if len(raw) > ledgers.MAX_ARCHIVE_BYTES or hashlib.sha256(raw).hexdigest() != snapshot_id[11:]:
        raise SourceReviewProblem('Сохранённый оригинал изменился или не совпал с SHA версии; проверка остановлена.')
    return raw


def _value(value):
    if value == ledgers._UNCACHED_FORMULA:
        return {'value': None, 'kind': 'formula_without_cached_value'}
    if isinstance(value, (dt.date, dt.datetime)):
        return {'value': value.isoformat(), 'kind': 'date'}
    if isinstance(value, float) and not math.isfinite(value):
        return {'value': None, 'kind': 'invalid_number'}
    if value is None or isinstance(value, (bool, int, float)):
        return {'value': value, 'kind': 'blank' if value is None else 'number'}
    text = str(value)
    return {'value': text[:1000], 'kind': 'text', **({'truncated': True} if len(text) > 1000 else {})}


def _raw_payloads(raw, selected):
    """Read only the fixed archive members whose hashes the parser selected."""
    payloads = {}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        for info in archive.infolist():
            if info.is_dir() or Path(info.filename).suffix.lower() not in ledgers.SUPPORTED:
                continue
            if info.file_size > ledgers.MAX_FILE_BYTES:
                raise SourceReviewProblem('Книга превышает размер безопасного чтения; проверка остановлена.')
            with archive.open(info) as handle:
                data = handle.read(ledgers.MAX_FILE_BYTES + 1)
            if len(data) > ledgers.MAX_FILE_BYTES:
                raise SourceReviewProblem('Книга превышает размер безопасного чтения; проверка остановлена.')
            sha = hashlib.sha256(data).hexdigest()
            if sha in selected:
                if sha in payloads and payloads[sha] != data:
                    raise SourceReviewProblem('Неоднозначный исходник книги; проверка остановлена.')
                payloads[sha] = data
    if set(payloads) != selected:
        raise SourceReviewProblem('Выбранная книга не совпала с проверенным оригиналом; проверка остановлена.')
    return payloads


def _headers(record, rows, siblings):
    """Own sheet header, or own closing-summary section, never a caller range."""
    source = record.get('source') or {}
    global_rows = set()
    if record.get('document_form') == 'closing_summary':
        start = source.get('row')
        if not isinstance(start, int) or start < 1:
            raise SourceReviewProblem('Граница раздела сводной не прочитана; исходные ячейки не выбраны по догадке.')
        starts = sorted({r.get('source', {}).get('row') for r in siblings
                         if r.get('source', {}).get('filename') == source.get('filename')
                         and r.get('source', {}).get('sheet') == source.get('sheet')
                         and type(r.get('source', {}).get('row')) is int})
        next_start = min((v for v in starts if v > start), default=None)
        following = next_start if next_start is not None else start+49
        # Global column labels end before the first contract section.
        top = range(1, min(min(starts, default=1), 13))
        global_rows = set(top)
        endpoints = [start]
        for value in [record.get('reported_total') or {}, *(record.get('acts') or []),
                      *(record.get('reported_amount_versions') or [])]:
            end = (value.get('source') or {}).get('row')
            if type(end) is int and start <= end < following:
                endpoints.append(end)
        known_end = max(endpoints)
        # A printed closing total bounds the last contract too: a following
        # grand total for the project is outside this card's own source.
        end = known_end+1 if known_end > start else next_start if next_start is not None else start+1
        own = range(start, min(end, start+49))
        indices = sorted(set(top) | set(own))
        columns = 24
        truncated = end > start+49 or (known_end == start and next_start is None)
    else:
        points = [item.get('source', {}).get('row') for item in record.get('items') or []
                  if type(item.get('source', {}).get('row')) is int]
        first = min(points, default=1)
        indices = range(1, min(first, 61))
        columns = 64
        truncated = first > 61
    cells = []
    for row_number in indices:
        if row_number > len(rows):
            continue
        row = rows[row_number-1]
        if any(value is not None and str(value).strip() for value in row[columns:]):
            truncated = True
        for column, value in enumerate(row[:columns], 1):
            if row_number in global_rows and not _column_label(value):
                continue
            if value is not None and (not isinstance(value, str) or value.strip()):
                cells.append({'cell': ledgers._cell(column, row_number), **_value(value)})
    return {'cells': cells, 'truncated': truncated}


def _column_label(value):
    """Only fixed semantic column labels can cross a contract-section boundary.

    A project preamble can contain other contracts, balances or grand totals.
    Neither a numeric value nor an arbitrary cell beside a label is evidence
    for this card. Own dates/act numbers are returned inside its own section.
    """
    if not isinstance(value, str):
        return False
    label = re.sub(r'\s+', ' ', value.strip().lower().replace('ё', 'е'))
    return label in {'№', '№ п/п', 'номер', 'дата', 'сумма', 'сумма, руб.',
        'номер акта', 'дата акта', 'дата составления', 'номер документа',
        'отчетный период', 'начало периода', 'окончание периода', 'с', 'по',
        'наименование работ', 'стоимость выполненных работ', 'ндс', 'в том числе ндс'}


def _record(record, snapshot_id, kind, headers):
    items = []
    for item in record.get('items') or []:
        items.append({key: item.get(key) for key in ('position', 'name', 'unit', 'plan_quantity',
                      'completed_quantity', 'planned_amount', 'completed_amount', 'source', 'periods')})
    return {'kind': kind, 'snapshot_id': snapshot_id, 'archive_sha256': snapshot_id[11:],
            'file_sha256': record.get('file_sha256'), 'source': record.get('source'),
            'identity': {k: record.get(k) for k in ('customer', 'contractor', 'contract', 'contract_date')},
            'items': items, 'acts': record.get('acts') or [],
            'periods_scope': 'raw_source_periods_not_filtered_as_fact',
            'reported_total': record.get('reported_total'),
            'reported_amount_versions': record.get('reported_amount_versions') or [],
            'header_cells': headers['cells'], 'headers_truncated': headers['truncated']}


def _review_raw(project, contract_id, cut):
    """Read original KS evidence for one existing card; never calculate a fact."""
    cut = contracts._cut(cut)
    register = contracts.build(project, cut, include_history=False)
    row = contracts.find_raw_row(register, contract_id)
    if row is None:
        raise SourceReviewProblem('Договор не найден в данных выбранного проекта на эту дату.')
    if row.get('source_kind') == 'contract_document':
        return {'contract_id': contract_id, 'cut': cut, 'state': 'read',
                'source_family': 'confirmed_contract_pdf', 'sources': row.get('document_provenance') or [],
                'source_count': len(row.get('document_provenance') or []),
                'archive_count': 0, 'verified_archive_count': 0,
                'unavailable_originals': [], 'identity_exclusions': [], 'note': row['performance_basis']}
    identity = contracts._identity(row)
    if identity is None:
        raise SourceReviewProblem('Реквизиты карточки не подтверждены; исходники не выбраны по совпадению названия.')
    if any(r.get('id') != contract_id and contracts._identity(r) == identity
           for r in contracts.raw_rows(register)):
        raise SourceReviewProblem('Реквизиты подходят нескольким карточкам; исходник не выбран автоматически.')
    snapshots = [s for s in ledgers.list_snapshots(project) if s.get('taken_at', '') <= cut]
    if len(snapshots) > MAX_ARCHIVES:
        raise SourceReviewProblem('Слишком много сохранённых версий для одного чтения; проверка остановлена.')
    result, unavailable, exclusions, total_bytes = [], [], [], 0
    used_items = used_periods = used_cells = used_result_bytes = 0
    for snapshot in snapshots:
        snapshot_id = snapshot['snapshot_id']
        try:
            raw = _original(project, snapshot_id)
        except OriginalUnavailable as exc:
            unavailable.append({'snapshot_id': snapshot_id, 'reason': str(exc)})
            continue
        total_bytes += len(raw)
        if total_bytes > MAX_TOTAL_ARCHIVE_BYTES:
            raise SourceReviewProblem('Объём сохранённых версий превышает безопасный предел; проверка остановлена.')
        # Parse these exact verified bytes, rather than trusting a stale report
        # in which undated periods have already been filtered out of the fact.
        parsed = ledgers.parse_archive(raw)
        candidates = [(r, 'cumulative') for r in parsed.get('ledgers') or []]
        candidates += [(r, 'closing_summary') for r in parsed.get('summary_contracts') or []]
        matched = [(r, kind) for r, kind in candidates if contracts._identity(r) == identity]
        for record, kind in candidates:
            if (contracts._party_norm(record.get('contractor')) == identity[1]
                    and contracts._contract_number(record.get('contract'), reference=True) == identity[2]
                    and (record, kind) not in matched):
                exclusions.append({'snapshot_id': snapshot_id, 'file_sha256': record.get('file_sha256'),
                    'source': record.get('source'), 'identity': {k: record.get(k) for k in
                        ('customer', 'contractor', 'contract', 'contract_date')},
                    'reason': 'Номер и подрядчик похожи, но дата или заказчик не совпали. '
                              'Периоды не присоединены к карточке автоматически.'})
        if len(result) + len(matched) > MAX_MATCHES:
            raise SourceReviewProblem('Слишком много исходников одного договора; проверка остановлена.')
        payloads = _raw_payloads(raw, {r['file_sha256'] for r, _ in matched}) if matched else {}
        books = {}
        for record, kind in matched:
            used_items += len(record.get('items') or [])
            used_periods += sum(len(item.get('periods') or []) for item in record.get('items') or [])
            if used_items > MAX_ITEMS or used_periods > MAX_PERIODS:
                raise SourceReviewProblem('Объём исходных строк превышает предел проверки; результат не усечён молча.')
            sha = record['file_sha256']
            if sha not in books:
                books[sha] = dict(ledgers._read_workbook(record['source']['filename'], payloads[sha]))
            sheet = record['source']['sheet']
            if sheet not in books[sha]:
                raise SourceReviewProblem('Лист исходной книги изменился; проверка остановлена.')
            headers = _headers(record, books[sha][sheet], parsed.get('summary_contracts') or [])
            used_cells += len(headers['cells'])
            if used_cells > MAX_HEADER_CELLS:
                raise SourceReviewProblem('Объём заголовков превышает предел проверки; результат не усечён молча.')
            found = _record(record, snapshot_id, kind, headers)
            used_result_bytes += len(json.dumps(found, ensure_ascii=False, default=str).encode())
            if used_result_bytes > MAX_RESULT_BYTES:
                raise SourceReviewProblem('Результат проверки превышает предел; исходные строки не возвращены частично.')
            result.append(found)
        # A retained source changing during this projection cannot be called a
        # successful read, even though this process still has the earlier bytes.
        if _original(project, snapshot_id) != raw:
            raise SourceReviewProblem('Исходный архив изменился во время чтения; результат не принят.')
    items = sum(len(r['items']) for r in result)
    periods = sum(len(item.get('periods') or []) for r in result for item in r['items'])
    cells = sum(len(r['header_cells']) for r in result)
    if items > MAX_ITEMS or periods > MAX_PERIODS or cells > MAX_HEADER_CELLS:
        raise SourceReviewProblem('Объём исходных строк превышает предел проверки; результат не усечён молча.')
    incomplete = (unavailable or exclusions or not result or any(r['headers_truncated'] or
        any(c.get('truncated') for c in r['header_cells']) for r in result))
    output = {'contract_id': contract_id, 'cut': cut, 'state': 'incomplete' if incomplete else 'read',
              'source_reader_schema': ledgers.PARSER_SCHEMA,
              'source_family': 'retained_cumulative_archives', 'archive_count': len(snapshots),
              'verified_archive_count': len(snapshots)-len(unavailable), 'sources': result,
              'unavailable_originals': unavailable, 'identity_exclusions': exclusions, 'source_count': len(result),
              'note': 'Исходные значения и подписи сохранённых КС. Проверка не назначает даты '
                      'периодов, не создаёт факты и не меняет связи договора.'}
    if row.get('document_provenance'):
        output['document_provenance'] = row['document_provenance']
    if len(json.dumps(output, ensure_ascii=False, default=str).encode()) > MAX_RESULT_BYTES:
        raise SourceReviewProblem('Результат проверки превышает предел; исходные строки не возвращены частично.')
    return output


def review(project, contract_id, cut):
    import developaid_contract_ownership as ownership
    try:
        with ownership.read_scope(project, contracts._cut(cut)):
            return _review_raw(project, contract_id, cut)
    except ownership.OwnershipProblem as exc:
        raise SourceReviewProblem(str(exc)) from None


# Project audit budgets are independent of the one-card projection above.
# At most3200 file observations fit below a bounded inventory reservation;
# details use the remaining space, at most7MiB (native jobs permit16MiB).
PROJECT_MAX_BOOKS = 128
PROJECT_MAX_SHEETS = 512
PROJECT_MAX_CELLS = 2_000_000
PROJECT_MAX_ITEMS = 20_000
PROJECT_MAX_PERIODS = 100_000
PROJECT_MAX_HEADER_CELLS = 20_000
PROJECT_MAX_DETAIL_BYTES = 7 * 1024 * 1024
PROJECT_MAX_RESULT_BYTES = 8 * 1024 * 1024


def _audit_root(project):
    """Reject project/root/manifest symlinks before enumerating any contents."""
    base = Path(ledgers.monitor._SNAPSHOT_DIR)
    if not isinstance(project, str) or not project.strip() or len(project)>200:
        raise SourceReviewProblem('Выберите проект.')
    # _project_dir creates missing directories; this read never needs that.
    project_dir = base / ledgers.monitor._resolved_slug(project)
    root = project_dir / 'cumulative'
    if (root.is_symlink() or project_dir.is_symlink()
            or project_dir.resolve().parent != base.resolve()
            or root.resolve().parent != project_dir.resolve()):
        raise SourceReviewProblem('Каталог исходников находится вне частного хранилища; чтение остановлено.')
    if root.exists():
        for path in root.glob('*.json'):
            if re.fullmatch(r'\d{4}-\d{2}-\d{2}-[0-9a-f]{64}', path.stem) and path.is_symlink():
                raise SourceReviewProblem('Ссылка вместо описания архива; чтение остановлено.')
    return root


def _audit_relative(value, sha):
    """A unique book's row provenance applies to every named byte observation."""
    if isinstance(value, list):
        return [_audit_relative(item, sha) for item in value]
    if isinstance(value, dict):
        result = {key: _audit_relative(item, sha) for key, item in value.items() if key not in {'filename','formula','formulas'}}
        return result
    return value


def _audit_raw_cells(item, rows):
    source = item.get('source') or {}
    out = {}
    for field in ('unit_cell', 'plan_quantity_cell', 'completed_quantity_cell', 'material_quantity_cell'):
        cell = source.get(field)
        index = ledgers._cell_coordinates(cell) if isinstance(cell, str) else None
        if index:
            column, row = index
            value = rows[row-1][column] if row <= len(rows) and column < len(rows[row-1]) else None
            out[field] = {'cell': cell, **_value(value)}
    return out


def _page_headers(record, rows, siblings):
    """The native first-work boundary, across the sheet's actually used columns."""
    if record.get('document_form') == 'closing_summary':
        return _headers(record, rows, siblings)
    points = [item.get('source', {}).get('row') for item in record.get('items') or []
              if type(item.get('source', {}).get('row')) is int]
    first = min(points, default=1)
    columns = min(ledgers.MAX_COLUMNS, max((column for row in rows
        for column, value in enumerate(row, 1)
        if value is not None and (not isinstance(value, str) or value.strip())), default=0))
    cells = []
    for row_number in range(1, min(first, 61)):
        if row_number <= len(rows):
            for column, value in enumerate(rows[row_number-1][:columns], 1):
                if value is not None and (not isinstance(value, str) or value.strip()):
                    cells.append({'cell': ledgers._cell(column, row_number), **_value(value)})
    beyond_columns = any(value is not None and (not isinstance(value, str) or value.strip())
        for row in rows[:min(first-1, 60)] for value in row[ledgers.MAX_COLUMNS:])
    return {'cells': cells, 'truncated': first > 61 or beyond_columns}


def _audit_record(record, rows, siblings, sha, cut, *, page_headers=False):
    # Unlike effective_snapshot, these records have no confirmations/aliases or
    # date-based fact filtering applied. Known dates only qualify raw periods.
    headers = (_page_headers if page_headers else _headers)(record, rows, siblings)
    value = _audit_relative(record, sha)
    value['file_sha256'] = sha
    value['source_coordinates_scope'] = 'relative_to_this_file_sha256'
    def contains_formula(node):
        return (any(k in {'formula','formulas'} or contains_formula(v) for k,v in node.items()) if isinstance(node,dict)
                else any(contains_formula(v) for v in node) if isinstance(node,list) else False)
    value['formula_text_omitted'] = contains_formula(record)
    value['identity_state'] = 'recognized_source_identity' if contracts._identity(record) else 'unresolved_header'
    contract_date = value.get('contract_date')
    value['contract_date_cut_qualification'] = ('undated' if not contract_date else 'future' if contract_date>cut else 'on_or_before_cut')
    value['source_identity_sha256'] = (hashlib.sha256(json.dumps(contracts._identity(record),
        ensure_ascii=False).encode()).hexdigest() if contracts._identity(record) else None)
    value['header_cells'] = headers['cells']
    value['headers_truncated'] = headers['truncated'] or any(cell.get('truncated') for cell in headers['cells'])
    value['periods_scope'] = 'raw_source_periods_not_filtered_as_fact'
    value['binding_verified'] = None
    for item in value.get('items') or []:
        item['raw_quantity_cells'] = _audit_raw_cells(item, rows)
        for period in item.get('periods') or []:
            end = period.get('date_end')
            period['cut_qualification'] = ('undated' if not end else 'future' if end > cut else 'on_or_before_cut')
    return value


def _audit_book(name, payload, sha, budget, used, cut, *, page_headers=False):
    """One native decode per exact byte hash; no financial/source decisions."""
    book = {'file_sha256': sha, 'size_bytes': len(payload), 'state': 'read', 'sheets': [],
            'sheet_count': None, 'omitted_sheets': 0, 'omitted_records': 0}
    if used.get('stop') or budget.get('cell_limit_reached'):
        return dict(book, state='not_read_budget', reason=used.get('stop') or 'Общий предел ячеек.')
    try:
        # Byte-identical observations can have different supported extensions.
        # Select the existing native decoder by its container signature, so a
        # misnamed first observation cannot poison this hash's sole decode.
        parser_name = ('source.xlsx' if payload.startswith(b'PK\x03\x04') else 'source.xls'
            if payload.startswith(b'\xd0\xcf\x11\xe0') or payload[:2] in {b'\x09\x00',b'\x09\x02',b'\x09\x04',b'\x09\x08'} else name)
        sheets = ledgers._read_workbook(parser_name, payload, budget)
    except ledgers.LedgerProblem as exc:
        over_budget=budget.get('cell_limit_reached') or budget['text_bytes']>ledgers.MAX_MATERIALIZED_TEXT_BYTES
        if over_budget:
            used['stop']=str(exc)
        return dict(book, state='not_read_budget' if over_budget else 'unreadable', reason=str(exc))
    book['sheet_count'] = len(sheets)
    for title, rows in sheets:
        if used['sheets'] >= PROJECT_MAX_SHEETS:
            book['state'] = 'not_read_budget'
            book['omitted_sheets'] += 1
            used['stop'] = 'Достигнут общий предел листов.'
            continue
        used['sheets'] += 1
        sheet = {'sheet': title, 'rows_read': len(rows), 'state': 'empty', 'records': []}
        book['sheets'].append(sheet)
        if used.get('stop'):
            sheet.update(state='not_read_budget', reason=used['stop'], parsed_positions=None,
                         parsed_period_values=None)
            book['state']='not_read_budget'
            continue
        # Cached formulas are numbers; unavailable cached values retain a
        # distinct marker. Formula text itself is never returned.
        sheet['formula_without_cached_value_cells'] = sum(value == ledgers._UNCACHED_FORMULA for row in rows for value in row)
        try:
            ledger = ledgers._ledger(name, title, rows)
            summaries = [] if ledger is not None else ledgers._summary(name, title, rows)
            records = [ledger] if ledger is not None else summaries or []
            sheet['state'] = 'ks6' if ledger is not None else 'closing_summary' if summaries is not None else 'not_recognized' if any(ledgers._text(v) for row in rows for v in row) else 'empty'
            if sheet['state']=='not_recognized':
                sheet.update(parsed_positions=None,parsed_period_values=None,
                    identity_evidence=_audit_relative(ledgers._metadata(rows,name,title),sha))
        except ledgers.LedgerProblem as exc:
            sheet.update(state='unreadable', reason=str(exc), identity_evidence=_audit_relative(ledgers._metadata(rows, name, title), sha))
            if book['state']=='read':
                book['state'] = 'incomplete'
            continue
        count = sum(len(record.get('items') or []) for record in records)
        periods = sum(len(item.get('periods') or []) for record in records for item in record.get('items') or [])
        if sheet['state']!='not_recognized':
            sheet.update(parsed_positions=count, parsed_period_values=periods)
        if used['items'] + count > PROJECT_MAX_ITEMS or used['periods'] + periods > PROJECT_MAX_PERIODS:
            sheet.update(state='not_read_budget', omitted_records=len(records), reason='Общий предел позиций или периодов.')
            book['omitted_records'] += len(records)
            book['state'] = 'not_read_budget'
            used['stop'] = sheet['reason']
            continue
        used['items'] += count
        used['periods'] += periods
        for record in records:
            projected = _audit_record(record, rows, summaries or [], sha, cut, page_headers=page_headers)
            cells = len(projected['header_cells'])
            if used['headers'] + cells > PROJECT_MAX_HEADER_CELLS:
                sheet.update(state='not_read_budget', reason='Общий предел исходных ячеек заголовков.')
                sheet['omitted_records'] = len(records)-len(sheet['records'])
                book['omitted_records'] += sheet['omitted_records']
                book['state'] = 'not_read_budget'
                used['stop'] = sheet['reason']
                break
            used['headers'] += cells
            sheet['records'].append(projected)
        if book['state']=='read' and (sheet['state'] in {'not_recognized', 'unreadable'} or any(r['headers_truncated'] for r in sheet['records'])):
            book['state'] = 'incomplete'
    if book['state'] in {'read','incomplete'} and not any(s['state'] in {'ks6','closing_summary'} for s in book['sheets']):
        book['state']='not_recognized'
    return book


def _audit_counts(archives, books):
    records = [record for book in books for sheet in book['sheets'] for record in sheet['records']]
    items = [item for record in records for item in record.get('items') or []]
    periods = [period for item in items for period in item.get('periods') or []]
    files = [item for archive in archives for item in archive['files']]
    other_headers=[s['identity_evidence'] for b in books for s in b['sheets'] if 'identity_evidence' in s]
    recognized={r['source_identity_sha256'] for r in records if r['source_identity_sha256']}
    recognized.update(hashlib.sha256(json.dumps(contracts._identity(r),ensure_ascii=False).encode()).hexdigest()
                      for r in other_headers if contracts._identity(r))
    positions_by_sha={b['file_sha256']:sum(len(r.get('items') or []) for s in b['sheets'] for r in s['records']) for b in books}
    return dict(file_observations=len(files), eligible_book_observations=sum(f.get('file_sha256') is not None for f in files),
        unique_book_fingerprints=len({f['file_sha256'] for f in files if f.get('file_sha256')}),
        decoded_unique_books=sum(b['sheet_count'] is not None for b in books),
        read_unique_sheets=sum(len(b['sheets']) for b in books),
        recognized_ks6_sheets=sum(s['state']=='ks6' for b in books for s in b['sheets']),
        closing_summary_sheets=sum(s['state']=='closing_summary' for b in books for s in b['sheets']),
        retained_unique_positions=len(items), retained_raw_period_values=len(periods),
        retained_position_observations=sum(positions_by_sha.get(f.get('file_sha256'),0) for f in files),
        recognized_source_identities=len(recognized),
        unresolved_source_headers=sum(r['identity_state']=='unresolved_header' for r in records)+sum(contracts._identity(r) is None for r in other_headers),
        unknown_units=sum(not item.get('unit') for item in items),
        unknown_plan_quantities=sum(item.get('plan_quantity') is None for item in items),
        unknown_completed_quantities=sum(item.get('completed_quantity') is None for item in items),
        unknown_period_dates=sum(p['cut_qualification']=='undated' for p in periods),
        future_raw_period_values=sum(p['cut_qualification']=='future' for p in periods),
        dated_raw_period_values_on_or_before_cut=sum(p['cut_qualification']=='on_or_before_cut' for p in periods),
        formula_without_cached_value_cells=sum(s.get('formula_without_cached_value_cells',0) for b in books for s in b['sheets']),
        reused_same_hash_observations=sum(f['status']=='reused_same_hash' for f in files),
        unsupported_file_observations=sum(f['status']=='unsupported' for f in files),
        unrecognized_sheets=sum(s['state']=='not_recognized' for b in books for s in b['sheets']),
        omitted_sheets=sum(b['omitted_sheets'] for b in books), omitted_records=sum(b['omitted_records'] for b in books))


def _project_audit(project, cut, root, directory_fd, guard, snapshots):
    """Inventory every eligible retained KS archive, independent of current cards.

    Counts concern source observations/retained raw rows, never summed physical
    quantities, cumulative money, document editions or financial acceptance.
    """
    cut = contracts._cut(cut)
    if any(not re.fullmatch(r'\d{4}-\d{2}-\d{2}-[0-9a-f]{64}', str(s.get('snapshot_id','')))
           or s.get('taken_at') != s['snapshot_id'][:10] for s in snapshots):
        raise SourceReviewProblem('Описание версии не совпало с датой и отпечатком сохранённого архива.')
    for snapshot in snapshots:
        ledgers._iso(snapshot['taken_at'])
    eligible = [s for s in snapshots if s.get('taken_at','') <= cut]
    future = [s for s in snapshots if s.get('taken_at','') > cut]
    archives, books, by_sha = [], [], {}
    total_bytes = detail_bytes = 0
    # Includes worst-case UTF-8 member names and every per-file status. This
    # leaves useful detail capacity for a small corpus without risking a large
    # inventory being silently cut to make room for work rows.
    detail_limit=max(0,min(PROJECT_MAX_DETAIL_BYTES,PROJECT_MAX_RESULT_BYTES-
        (64*1024+len(eligible)*ledgers.MAX_FILES*2048)))
    budget = {'text_bytes':0, 'materialized_cells':0, 'max_materialized_cells':PROJECT_MAX_CELLS}
    used = dict(sheets=0, items=0, periods=0, headers=0)
    for snapshot in eligible[:MAX_ARCHIVES]:
        sid = snapshot.get('snapshot_id','')
        entry = {'snapshot_id':sid, 'taken_at':snapshot.get('taken_at'), 'archive_sha256':sid[11:],
                 'manifest_present':snapshot.get('manifest_present',True),
                 'archive_date_basis':'native_snapshot_manifest' if snapshot.get('manifest_present',True) else 'snapshot_id_only_manifest_missing',
                 'state':'not_read_budget', 'original_sha_verified':False,'source_stable_verified':False,
                 'files_inventory_complete':False, 'files':[]}
        archives.append(entry)
        if len(eligible) > MAX_ARCHIVES:
            entry['reason'] = 'Архивов больше общего предела; оригиналы не открывались.'
            continue
        try:
            guard()
            try:
                info=os.stat(sid+'.zip',dir_fd=directory_fd,follow_symlinks=False)
            except FileNotFoundError:
                info=None
            if info is not None and not stat.S_ISREG(info.st_mode):
                raise SourceReviewProblem('Исходный архив не является обычным файлом; чтение остановлено.')
            if info is not None and total_bytes + info.st_size > MAX_TOTAL_ARCHIVE_BYTES:
                entry['reason'] = 'Достигнут общий предел байтов исходных архивов.'
                continue
            raw = _original(project, sid, directory_fd=directory_fd)
            entry['original_sha_verified']=True
            total_bytes += len(raw)
            if total_bytes > MAX_TOTAL_ARCHIVE_BYTES:
                entry['reason'] = 'Объём источника изменился и превысил общий предел байтов.'
                continue
            members = ledgers._zip_members(raw, skip_unsupported=True)
            entry.update(state='verified', files_inventory_complete=True, size_bytes=len(raw))
            for name, payload in members:
                observation = {'filename':name, 'status':'unsupported', 'file_sha256':None}
                entry['files'].append(observation)
                if payload is None:
                    observation['reason'] = 'Служебный или неподдерживаемый файл. Содержимое не открывалось.'
                    continue
                sha = hashlib.sha256(payload).hexdigest()
                observation.update(file_sha256=sha, size_bytes=len(payload))
                if sha in by_sha:
                    observation.update(status='reused_same_hash', read_state=by_sha[sha]['state'], duplicate_proof='same_sha256_and_size')
                    if by_sha[sha]['size_bytes'] != len(payload):
                        raise SourceReviewProblem('Неоднозначный отпечаток исходной книги; чтение остановлено.')
                    continue
                if len(books) >= PROJECT_MAX_BOOKS:
                    observation.update(status='not_read_budget', read_state='not_read_budget', reason='Общий предел уникальных книг.')
                    continue
                book = _audit_book(name, payload, sha, budget, used, cut)
                encoded = json.dumps(book,ensure_ascii=False,allow_nan=False).encode()
                if detail_bytes + len(encoded) > detail_limit:
                    omitted_records = sum(len(s['records'])+s.get('omitted_records',0) for s in book['sheets'])
                    book = {key:book[key] for key in ('file_sha256','size_bytes','sheet_count')}
                    book.update(state='not_read_budget', reason='Общий предел подробностей результата.', sheets=[],
                                omitted_sheets=book['sheet_count'] or 0, omitted_records=omitted_records)
                    used['stop'] = book['reason']
                    encoded = json.dumps(book,ensure_ascii=False).encode()
                detail_bytes += len(encoded)
                books.append(book)
                by_sha[sha] = book
                observation.update(status=book['state'], read_state=book['state'])
            # Hash verification is required even when all books were reused.
            guard()
            if _original(project,sid,directory_fd=directory_fd) != raw:
                raise SourceReviewProblem('Исходный архив изменился во время чтения.')
            entry['source_stable_verified']=True
        except (SourceReviewProblem,ledgers.LedgerProblem,OSError) as exc:
            entry.update(state='unavailable' if isinstance(exc,OriginalUnavailable) else 'error', reason=str(exc) if not isinstance(exc,OSError) else 'Оригинал архива недоступен.')
            for observation in entry['files']:
                observation['read_state'] = 'source_verification_failed'
    counts = _audit_counts(archives,books)
    counts.update(eligible_archives=len(eligible), future_archives=len(future),
        missing_archive_manifests=sum(not a['manifest_present'] for a in archives),
        inventoried_archives=len(archives), omitted_archives=max(0,len(eligible)-MAX_ARCHIVES),
        verified_archives=sum(a['state']=='verified' for a in archives), verified_original_bytes=total_bytes,
        original_sha_verified_archives=sum(a['original_sha_verified'] for a in archives),
        materialized_cell_reads=budget['materialized_cells'])
    complete = (len(eligible)<=MAX_ARCHIVES and all(a['state']=='verified' and a['files_inventory_complete'] and a['manifest_present'] for a in archives)
                and all(f.get('read_state')=='read' for a in archives for f in a['files'])
                and all(b['state']=='read' for b in books))
    identity_complete = not counts['unresolved_source_headers'] and not counts['unrecognized_sheets']
    quality = any(counts[k] for k in ('unresolved_source_headers','unknown_units','unknown_plan_quantities',
        'unknown_completed_quantities','unknown_period_dates','future_raw_period_values','formula_without_cached_value_cells'))
    output = dict(schema=1, project=project, cut=cut, source_family='retained_cumulative_archives',
        source_reader_schema=ledgers.PARSER_SCHEMA, read_complete=complete,
        counts_complete=complete, counts_scope='all_eligible_source_observations' if complete else 'retained_read_sources_only_not_the_whole_corpus',
        recognition_complete=complete and identity_complete, financial_complete=None, binding_verified=None,
        state='partial' if not complete else 'read_with_issues' if quality else 'read' if eligible else 'empty',
        counts=counts, archives=archives, books=books,
        future_archives=[{'snapshot_id':s['snapshot_id'],'taken_at':s['taken_at'],'state':'not_read_after_cut'} for s in future[:MAX_ARCHIVES]],
        omitted_future_archives=max(0,len(future)-MAX_ARCHIVES),
        limits=dict(archives=MAX_ARCHIVES,original_bytes=MAX_TOTAL_ARCHIVE_BYTES,unique_books=PROJECT_MAX_BOOKS,
            sheets=PROJECT_MAX_SHEETS,materialized_cells=PROJECT_MAX_CELLS,positions=PROJECT_MAX_ITEMS,
            period_values=PROJECT_MAX_PERIODS,header_cells=PROJECT_MAX_HEADER_CELLS,
            detail_bytes=detail_limit,result_bytes=PROJECT_MAX_RESULT_BYTES),
        note='Исходные КС всех сохранённых архивов на выбранную дату. Повторения определены только отпечатком байтов, '
             'а не именем файла. Периоды и количества показаны как исходные значения, не как подтверждённый факт проекта. '
             'Периоды, итоги разных версий, деньги СМР и материалов и разные единицы не суммируются. '
             'Решения об идентичности, финансовом источнике, датах и привязках не проверялись и не менялись.')
    if len(json.dumps(output,ensure_ascii=False,allow_nan=False).encode()) > PROJECT_MAX_RESULT_BYTES:
        # Keep deterministic source inventory, never an apparently complete
        # answer whose trailing books or archive observations vanished.
        output.update(state='partial', read_complete=False, recognition_complete=False, counts_complete=False,
                      counts_scope='retained_read_sources_only_not_the_whole_corpus',
                      omitted_book_details=len(books), books=[], overflow_reason='Предел размера результата: подробности книг не возвращены.')
        if len(json.dumps(output,ensure_ascii=False,allow_nan=False).encode()) > PROJECT_MAX_RESULT_BYTES:
            output.update(omitted_archive_file_details=sum(len(a['files']) for a in archives))
            for entry in archives:
                entry.update(omitted_files=len(entry['files']),files=[],files_inventory_complete=False)
    if len(json.dumps(output,ensure_ascii=False,allow_nan=False).encode()) > PROJECT_MAX_RESULT_BYTES:
        raise SourceReviewProblem('Предел размера результата не вмещает даже сокращённую опись; полное чтение не подтверждено.')
    return output


def project_audit(project, cut):
    """Pin the existing native project namespace and a readonly directory FD.

    Native merge takes EX on this same namespace lock. No source, alias or
    identity decision is written. Uncooperative retargets fail the pre/post
    token checks; original reads always use the initially pinned directory.
    """
    import developaid_contract_identity_store as identity_store
    try:
        with identity_store.namespace(project):
            root=_audit_root(project)
            descriptor=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW) if root.exists() else None
            try:
                location=(os.fstat(descriptor).st_dev,os.fstat(descriptor).st_ino) if descriptor is not None else None
                def guard():
                    identity_store.assert_namespace(project)
                    current=_audit_root(project)
                    actual=current.stat() if current.exists() else None
                    if current!=root or ((actual.st_dev,actual.st_ino) if actual else None)!=location:
                        raise identity_store.IdentityProblem('Каталог исходников изменился во время чтения.')
                def inventory():
                    guard()
                    values=ledgers.list_snapshots(project) if root.exists() else []
                    known={s.get('snapshot_id') for s in values}
                    # A retained native-named original without its manifest is
                    # evidence to inspect, never an omitted/empty contract.
                    for path in root.glob('*.zip') if root.exists() else []:
                        if re.fullmatch(r'\d{4}-\d{2}-\d{2}-[0-9a-f]{64}',path.stem) and path.stem not in known:
                            values.append(dict(snapshot_id=path.stem,taken_at=path.stem[:10],manifest_present=False))
                    values=sorted(values,key=lambda s:(s.get('taken_at',''),s.get('snapshot_id','')))
                    guard()
                    return values
                snapshots=inventory()
                result=_project_audit(project,cut,root,descriptor,guard,snapshots)
                if inventory()!=snapshots:
                    raise SourceReviewProblem('Состав сохранённых архивов изменился во время чтения; результат не принят.')
                return result
            finally:
                if descriptor is not None:os.close(descriptor)
    except identity_store.IdentityProblem as exc:
        raise SourceReviewProblem(str(exc)) from None


PAGE_MAX_BOOKS = 8
CORPUS_TOKEN_SCHEMA = 'ks6-retained-corpus-v1'


def corpus_token(project, cut, archives):
    """Reproducible from an existing v1 audit; no parse-dependent fields."""
    projected = []
    for archive in sorted(archives, key=lambda a: (a['taken_at'], a['snapshot_id'])):
        projected.append({**{key: archive[key] for key in ('snapshot_id', 'taken_at',
            'archive_sha256', 'manifest_present', 'size_bytes')},
            'files': [{key: item[key] for key in ('filename', 'file_sha256', 'size_bytes')
                       if key in item} for item in archive['files']]})
    value = dict(schema=CORPUS_TOKEN_SCHEMA, project=project, cut=cut, archives=projected)
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def _page_inventory(project, snapshots, directory_fd, guard, selected):
    """Verify every original before decoding; retain bytes only for selected SHA."""
    if len(snapshots) > MAX_ARCHIVES:
        raise SourceReviewProblem('Состав архивов превышает предел страницы; корпус не подтверждён.')
    archives, payloads, sizes = [], {}, {}
    total = 0
    for snapshot in snapshots:
        sid = snapshot['snapshot_id']
        guard()
        info = os.stat(sid+'.zip', dir_fd=directory_fd, follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode):
            raise SourceReviewProblem('Исходный архив не является обычным файлом; чтение остановлено.')
        if total + info.st_size > MAX_TOTAL_ARCHIVE_BYTES:
            raise SourceReviewProblem('Достигнут общий предел байтов исходных архивов.')
        raw = _original(project, sid, directory_fd=directory_fd)
        total += len(raw)
        if total > MAX_TOTAL_ARCHIVE_BYTES:
            raise SourceReviewProblem('Объём источника изменился и превысил общий предел байтов.')
        entry = dict(snapshot_id=sid, taken_at=snapshot['taken_at'], archive_sha256=sid[11:],
            manifest_present=snapshot.get('manifest_present', True), size_bytes=len(raw),
            archive_date_basis='native_snapshot_manifest' if snapshot.get('manifest_present', True)
                else 'snapshot_id_only_manifest_missing', state='verified',
            original_sha_verified=True, source_stable_verified=False, files_inventory_complete=True, files=[])
        archives.append(entry)
        for name, payload in ledgers._zip_members(raw, skip_unsupported=True):
            item = dict(filename=name, file_sha256=None, status='unsupported')
            entry['files'].append(item)
            if payload is None:
                item['reason'] = 'Служебный или неподдерживаемый файл. Содержимое не открывалось.'
                continue
            sha = hashlib.sha256(payload).hexdigest()
            item.update(file_sha256=sha, size_bytes=len(payload),
                        status='selected' if sha in selected else 'not_selected')
            if sha in sizes:
                if sizes[sha] != len(payload):
                    raise SourceReviewProblem('Неоднозначный отпечаток исходной книги; чтение остановлено.')
                item.update(status='reused_same_hash', duplicate_proof='same_sha256_and_size')
            else:
                sizes[sha] = len(payload)
                if len(sizes) > PROJECT_MAX_BOOKS:
                    raise SourceReviewProblem('Состав книг превышает общий предел; корпус не подтверждён.')
                if sha in selected:
                    payloads[sha] = (name, payload)
        guard()
        if _original(project, sid, directory_fd=directory_fd) != raw:
            raise SourceReviewProblem('Исходный архив изменился во время проверки описи страницы.')
        entry['source_stable_verified'] = True
    return archives, payloads, sizes


def _project_audit_page(project, cut, selected, expected_token, directory_fd, guard, inventory):
    snapshots = inventory()
    eligible = [s for s in snapshots if s['taken_at'] <= cut]
    archives, payloads, sizes = _page_inventory(project, eligible, directory_fd, guard, selected)
    token = corpus_token(project, cut, archives)
    if token != expected_token:
        raise SourceReviewProblem('Корпус исходников изменился или не совпал с доказательством предыдущего чтения.')
    if not selected <= sizes.keys() or selected != payloads.keys():
        raise SourceReviewProblem('Выбранный SHA книги отсутствует в подтверждённом корпусе проекта на эту дату.')
    if [s for s in inventory() if s['taken_at'] <= cut] != eligible:
        raise SourceReviewProblem('Состав сохранённых архивов изменился до чтения страницы.')
    detail_limit = max(0, min(PROJECT_MAX_DETAIL_BYTES, PROJECT_MAX_RESULT_BYTES-
        (64*1024+len(eligible)*ledgers.MAX_FILES*2048)))
    budget = dict(text_bytes=0, materialized_cells=0, max_materialized_cells=PROJECT_MAX_CELLS)
    used = dict(sheets=0, items=0, periods=0, headers=0)
    books, detail_bytes = [], 0
    for sha in sorted(selected):
        name, payload = payloads.pop(sha)
        book = _audit_book(name, payload, sha, budget, used, cut, page_headers=True)
        encoded = json.dumps(book, ensure_ascii=False, allow_nan=False).encode()
        if detail_bytes + len(encoded) > detail_limit:
            omitted = sum(len(s['records'])+s.get('omitted_records', 0) for s in book['sheets'])
            book = dict(file_sha256=sha, size_bytes=len(payload), sheet_count=book['sheet_count'],
                state='not_read_budget', reason='Общий предел подробностей результата.', sheets=[],
                omitted_sheets=book['sheet_count'] or 0, omitted_records=omitted)
            used['stop'] = book['reason']
            encoded = json.dumps(book, ensure_ascii=False).encode()
        detail_bytes += len(encoded)
        books.append(book)
    # Verify all originals again, including books not selected/decoded here.
    after = inventory()
    if [s for s in after if s['taken_at'] <= cut] != eligible:
        raise SourceReviewProblem('Состав сохранённых архивов изменился во время чтения страницы.')
    verified, _, verified_sizes = _page_inventory(project, eligible, directory_fd, guard, set())
    if corpus_token(project, cut, verified) != token or verified_sizes != sizes:
        raise SourceReviewProblem('Исходники изменились во время чтения страницы; результат не принят.')
    if [s for s in inventory() if s['taken_at'] <= cut] != eligible:
        raise SourceReviewProblem('Состав сохранённых архивов изменился после проверки страницы.')
    for entry in archives:
        entry['source_stable_verified'] = True
    selected_archives = [{**a, 'files': [f for f in a['files'] if f.get('file_sha256') in selected]}
                         for a in archives]
    counts = _audit_counts(selected_archives, books)
    counts['selected_unique_books'] = len(selected)
    counts['materialized_cell_reads'] = budget['materialized_cells']
    complete = all(b['state'] == 'read' for b in books)
    future = [s for s in after if s['taken_at'] > cut]
    output = dict(schema=1, kind='selected_ks6_source_page', project=project, cut=cut,
        source_family='retained_cumulative_archives', source_reader_schema=ledgers.PARSER_SCHEMA,
        corpus_token_schema=CORPUS_TOKEN_SCHEMA, corpus_token=token,
        selected_book_sha256=sorted(selected), selected_read_complete=complete,
        selected_recognition_complete=complete and not counts['unresolved_source_headers']
            and not counts['unrecognized_sheets'], corpus_read_complete=None,
        financial_complete=None, binding_verified=None,
        state='read_selected' if complete else 'partial_selected', counts=counts,
        counts_complete=complete, counts_scope='retained_selected_books_only_not_the_whole_corpus',
        inventory_counts=dict(eligible_archives=len(archives), unique_book_fingerprints=len(sizes),
            file_observations=sum(len(a['files']) for a in archives),
            verified_original_bytes=sum(a['size_bytes'] for a in archives),
            missing_archive_manifests=sum(not a['manifest_present'] for a in archives)),
        archives=archives, books=books,
        continuation=dict(not_selected_book_sha256=sorted(sizes.keys()-selected),
            incomplete_selected_book_sha256=[b['file_sha256'] for b in books if b['state'] != 'read'],
            max_selected_books=PAGE_MAX_BOOKS),
        future_archives=[dict(snapshot_id=s['snapshot_id'], taken_at=s['taken_at'],
            state='not_read_after_cut') for s in future[:MAX_ARCHIVES]],
        omitted_future_archives=max(0, len(future)-MAX_ARCHIVES),
        limits=dict(archives=MAX_ARCHIVES, original_bytes=MAX_TOTAL_ARCHIVE_BYTES,
            unique_books=PROJECT_MAX_BOOKS, selected_books=PAGE_MAX_BOOKS, sheets=PROJECT_MAX_SHEETS,
            materialized_cells=PROJECT_MAX_CELLS, positions=PROJECT_MAX_ITEMS,
            period_values=PROJECT_MAX_PERIODS, header_cells=PROJECT_MAX_HEADER_CELLS,
            detail_bytes=detail_limit, result_bytes=PROJECT_MAX_RESULT_BYTES),
        note='Страница содержит только выбранные книги. Полнота страницы не подтверждает чтение всего корпуса. '
             'Периоды и количества исходные; это не подтверждённый факт, финансовая приёмка или привязка договора.')
    if len(json.dumps(output, ensure_ascii=False, allow_nan=False).encode()) > PROJECT_MAX_RESULT_BYTES:
        raise SourceReviewProblem('Предел размера страницы не вмещает опись и выбранные книги; результат не принят.')
    return output


def _selected_source_read(project, cut, book_sha256, corpus_token, projection):
    """A bounded selection from the corpus already evidenced by a v1 audit."""
    import developaid_contract_identity_store as identity_store
    if (not isinstance(book_sha256, list) or not 1 <= len(book_sha256) <= PAGE_MAX_BOOKS
            or any(not isinstance(sha, str) or not re.fullmatch(r'[0-9a-f]{64}', sha) for sha in book_sha256)
            or not isinstance(corpus_token, str) or not re.fullmatch(r'[0-9a-f]{64}', corpus_token)):
        raise SourceReviewProblem('Неверный ограниченный выбор SHA книг или доказательство корпуса.')
    cut = contracts._cut(cut)
    try:
        with identity_store.namespace(project):
            root = _audit_root(project)
            descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW) if root.exists() else None
            try:
                location = (os.fstat(descriptor).st_dev, os.fstat(descriptor).st_ino) if descriptor is not None else None
                def guard():
                    identity_store.assert_namespace(project)
                    current = _audit_root(project)
                    actual = current.stat() if current.exists() else None
                    if current != root or ((actual.st_dev, actual.st_ino) if actual else None) != location:
                        raise SourceReviewProblem('Каталог исходников изменился во время чтения.')
                def inventory():
                    guard()
                    values = ledgers.list_snapshots(project) if root.exists() else []
                    known = {s.get('snapshot_id') for s in values}
                    for path in root.glob('*.zip') if root.exists() else []:
                        if re.fullmatch(r'\d{4}-\d{2}-\d{2}-[0-9a-f]{64}', path.stem) and path.stem not in known:
                            values.append(dict(snapshot_id=path.stem, taken_at=path.stem[:10], manifest_present=False))
                    for snapshot in values:
                        sid = snapshot.get('snapshot_id', '')
                        if (not isinstance(sid, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}-[0-9a-f]{64}', sid)
                                or snapshot.get('taken_at') != sid[:10]):
                            raise SourceReviewProblem('Описание версии не совпало с датой и отпечатком архива.')
                        ledgers._iso(snapshot['taken_at'])
                    guard()
                    return sorted(values, key=lambda s: (s['taken_at'], s['snapshot_id']))
                return projection(project, cut, set(book_sha256), corpus_token, descriptor, guard, inventory)
            finally:
                if descriptor is not None:
                    os.close(descriptor)
    except (identity_store.IdentityProblem, OSError, ledgers.LedgerProblem) as exc:
        raise SourceReviewProblem(str(exc) if not isinstance(exc, OSError)
            else 'Оригинал архива недоступен; корпус страницы не подтверждён.') from None


def project_audit_page(project, cut, book_sha256, corpus_token):
    return _selected_source_read(project, cut, book_sha256, corpus_token, _project_audit_page)


def project_duplicate_proof(project, cut, book_sha256, corpus_token):
    """Raw native duplicate normalization only; no binding or financial choice."""
    if not isinstance(book_sha256, list) or len(book_sha256) != 1:
        raise SourceReviewProblem('Выберите ровно один SHA книги для проверки копий.')
    from developaid_contract_duplicate_proof import project_proof
    return _selected_source_read(project, cut, book_sha256, corpus_token, project_proof)
