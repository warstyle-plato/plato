"""A fixed, private projection of one card's retained original KS workbooks.

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
from pathlib import Path
import re
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


def _original(project, snapshot_id):
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}-[0-9a-f]{64}', snapshot_id):
        raise SourceReviewProblem('Неверная версия сохранённого архива; проверка остановлена.')
    root = ledgers._root(project)
    path = root / (snapshot_id + '.zip')
    if path.is_symlink() or path.resolve().parent != root.resolve():
        raise SourceReviewProblem('Исходный архив находится вне частного хранилища; проверка остановлена.')
    try:
        with path.open('rb') as handle:
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


def review(project, contract_id, cut):
    """Read original KS evidence for one existing card; never calculate a fact."""
    cut = contracts._cut(cut)
    register = contracts.build(project, cut, include_history=False)
    row = next((r for r in register.get('rows') or [] if r.get('id') == contract_id), None)
    if row is None:
        raise SourceReviewProblem('Договор не найден в данных выбранного проекта на эту дату.')
    identity = contracts._identity(row)
    if identity is None:
        raise SourceReviewProblem('Реквизиты карточки не подтверждены; исходники не выбраны по совпадению названия.')
    if any(r.get('id') != contract_id and contracts._identity(r) == identity
           for r in register.get('rows') or []):
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
    if len(json.dumps(output, ensure_ascii=False, default=str).encode()) > MAX_RESULT_BYTES:
        raise SourceReviewProblem('Результат проверки превышает предел; исходные строки не возвращены частично.')
    return output
