"""Prepare a server-local, GPR-only review copy from a saved corpus parse.

This module never uploads or applies data. The controller reviews its output
and calls the ordinary schedule-version approval function on the server.
"""
from __future__ import annotations

import copy
import io
import hashlib
import json
import re
import zipfile
from pathlib import Path


def prepare(project: str, source_sha256: str, *, expected_active_sha256: str,
            expected_revision: int, corrections: list[dict] | None = None) -> dict:
    import developaid_monitor as monitor
    import developaid_gpr_corpus as corpus
    import developaid_schedule_versions as versions
    from openpyxl import Workbook
    from openpyxl.utils.cell import coordinate_from_string, column_index_from_string

    if not versions._SHA.fullmatch(source_sha256 or ''):
        raise ValueError('Укажите отпечаток сохранённого источника.')
    active = monitor._working_baseline_state(project)
    if active['source_sha256'] != expected_active_sha256 or active['revision'] != expected_revision:
        raise versions.ScheduleVersionConflict('Выбранный план изменился. Перечитайте состояние источников.')
    matches = []
    parse_refs = []
    raw_source = None
    root = monitor._project_dir(project)
    # Journal identities locate an approved source directly. Unindexed legacy
    # fact files and JSON parses have explicit count/byte budgets.
    raw_paths = [root/'baseline'/'schedule_sources'/(source_sha256+'.xlsx')]
    approved_hashes = {e['source_sha256'] for e in active['versions']}
    raw_paths = raw_paths if source_sha256 in approved_hashes else []
    legacy_sha = active['versions'][0]['previous_source_sha256'] if active['versions'] else active['source_sha256']
    if source_sha256 == legacy_sha and monitor._legacy_baseline_file(project) is not None:
        raw_paths.append(monitor._legacy_baseline_file(project))
    if active['source_sha256'] == source_sha256 and active['path'] is not None:
        raw_paths.insert(0, active['path'])
    for path in dict.fromkeys(raw_paths):
        data = versions._read(path)
        if versions.digest(data) != source_sha256:
            raise ValueError('Отпечаток сохранённого исходника не совпадает с выбранным.')
        raw_source = data
        parsed = corpus.read(data)
        if parsed:
            matches.append(parsed)
        break
    raw_unindexed = sorted((root/'schedule_fact').glob('*.xlsx'), reverse=True)
    parse_paths = sorted((root/'gpr_corpus').glob('*.json'), reverse=True)
    remaining_bytes, omitted = 32*1024*1024, 0
    if raw_source is None:
        for index, path in enumerate(raw_unindexed):
            if not monitor._day(path.stem):
                continue
            size = path.stat().st_size
            if index >= 8 or size > remaining_bytes or size > versions.MAX_BYTES:
                omitted += 1
                continue
            remaining_bytes -= size
            data = versions._read(path)
            if versions.digest(data) == source_sha256:
                raw_source = data
                parsed = corpus.read(data)
                if parsed:
                    matches.append(parsed)
                break
    remaining_bytes = 16*1024*1024
    for index, path in enumerate(parse_paths):
        if not monitor._day(path.stem):
            continue
        size = path.stat().st_size
        if index >= 32 or size > remaining_bytes:
            omitted += 1
            continue
        remaining_bytes -= size
        raw_parse = path.read_bytes()
        try:
            parsed = json.loads(raw_parse)
            if not isinstance(parsed, dict):
                raise ValueError
        except ValueError:
            omitted += 1
            continue
        if parsed.get('sha256') == source_sha256:
            matches.append(parsed)
            parse_refs.append({'snapshot_date': path.stem,
                               'parse_sha256': hashlib.sha256(raw_parse).hexdigest()})
    if not matches:
        raise ValueError('В ограниченном перечне нет источника с этим отпечатком; '+
                         ('часть истории не прочитана из-за лимита диагностики.' if omitted else 'в этом проекте он не найден.'))
    # An equal hash must never select one of disagreeing saved parses by order.
    source = copy.deepcopy(matches[0])
    if source.get('format') != 'corpus-gpr-v1' or source.get('sheet') != 'ГПР':
        raise ValueError('Схема сохранённого разбора не поддерживается: требуется канонический лист ГПР.')
    if any(m.get('packages') != source.get('packages') for m in matches[1:]):
        raise ValueError('Сохранённые разборы одного источника расходятся; требуется проверка администратора.')
    cells = {}
    for package in source['packages']:
        for scope in package['scopes']:
            for key in ('start', 'finish'):
                cell = scope['source_cells'][key]
                if cell in cells:
                    raise ValueError('Координаты источника повторяются.')
                cells[cell] = (scope, key)
    audit = []
    seen = set()
    for c in corrections or []:
        cell = c.get('cell')
        if cell not in cells or cell in seen:
            raise ValueError('Исправление должно относиться к одной существующей ячейке даты этого источника.')
        scope, key = cells[cell]
        if c.get('expected_raw') != scope['raw'].get(key):
            raise versions.ScheduleVersionConflict('Исходное значение ячейки изменилось; исправление не применено.')
        value, note = c.get('value'), c.get('note')
        parsed_date = corpus._date(value)
        if not parsed_date or not isinstance(note, str) or not note.strip() or len(note) > 1000:
            raise ValueError('Для исправления нужны корректная дата и явное основание (до 1000 знаков).')
        audit.append({'cell': cell, 'original_raw': scope['raw'].get(key),
                      'value': value, 'note': note.strip()})
        scope['raw'][key], scope[key] = value, parsed_date
        seen.add(cell)
    # Reconstruct only the selected sheet. No financial sheet or formula is
    # opened, saved or copied. Raw dates, blanks, zeros and coordinates survive.
    wb = Workbook()
    ws = wb.active
    ws.title = source['sheet']
    rows = [p['source_row'] for p in source['packages']]
    header = min(rows)-2
    groups = [p.get('group_source') for p in source['packages'] if p.get('group_source')]
    if groups:
        header = min(header, min(g['source_row'] for g in groups)-2)
    if header < 1:
        raise ValueError('Не удалось восстановить расположение шапки ГПР.')
    ws.cell(header, 1, '№'); ws.cell(header, 2, 'Наименование работ')
    ws.cell(header, 3, 'Стадия'); ws.cell(header, 4, 'Статус')
    for package in source['packages']:
        row = package['source_row']
        ws.cell(row, 1, int(float(package['number_raw'])))
        ws.cell(row, 2, package['name']); ws.cell(row, 3, package.get('stage') or '')
        ws.cell(row, 4, package.get('status') or '')
        group = package.get('group_source')
        if group:
            ws.cell(group['source_row'], 1, group['name'])
        for scope in package['scopes']:
            col_letters, _ = coordinate_from_string(scope['source_cells']['progress'])
            col = column_index_from_string(col_letters)
            ws.cell(header, col, scope['corpus'])
            ws.cell(header+1, col, 'Факт '+scope['fact_day_raw'])
            ws.cell(header+1, col+1, 'Старт'); ws.cell(header+1, col+2, 'Финиш')
            for key, cell in scope['source_cells'].items():
                value = scope['raw'].get(key)
                if value is not None:
                    ws[cell] = value
                    # Source text must remain literal, never an Excel formula.
                    if isinstance(value, str):
                        ws[cell].data_type = 's'
    provenance = wb.create_sheet('Происхождение')
    provenance.append(['Производная копия только листа ГПР из сохранённого разбора; не исходная книга.'])
    provenance.append(['original_upload_sha256', source_sha256])
    provenance.append(['expected_active_sha256', expected_active_sha256])
    provenance.append(['expected_revision', expected_revision])
    for ref in parse_refs:
        provenance.append(['saved_parse', ref['snapshot_date'], ref['parse_sha256']])
    provenance.append(['cell', 'original_raw', 'new_value', 'explicit_basis'])
    for change in audit:
        provenance.append([change['cell'], change['original_raw'], change['value'], change['note']])
    for row in wb.worksheets:
        for cells_row in row:
            for cell in cells_row:
                if isinstance(cell.value, str):
                    cell.data_type = 's'
    stream = io.BytesIO(); wb.save(stream); wb.close()
    # XLSX ZIP and core-property timestamps must not change a review hash
    # between preview and approval on another worker.
    deterministic = io.BytesIO()
    with zipfile.ZipFile(stream) as source_zip, zipfile.ZipFile(deterministic, 'w', zipfile.ZIP_DEFLATED) as target:
        for name in sorted(source_zip.namelist()):
            payload = source_zip.read(name)
            if name == 'docProps/core.xml':
                payload = re.sub(rb'(<dcterms:(?:created|modified)[^>]*>)[^<]+',
                                 rb'\g<1>2000-01-01T00:00:00Z', payload)
            info = zipfile.ZipInfo(name, (2000, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            target.writestr(info, payload)
    data = raw_source if raw_source is not None and not audit else deterministic.getvalue()
    derived = corpus.read(data)
    rebuilt = corpus.as_schedule(derived)
    def signature(parsed):
        return {w['id']: (w['name'], w['object'], w['section'], w['progress'], w['progress_date'],
                          w['start'], w['finish']) for w in parsed['works']}
    expected = signature(corpus.as_schedule(source))
    if signature(rebuilt) != expected:
        raise ValueError('Контрольная сверка производной копии не прошла; версия не подготовлена.')
    # Compare active source by stable cell identity and full labels; never infer
    # correspondence from just row number or spread a cohort into leaves.
    baseline = monitor._read_working_baseline_gpr(project)
    before, after = signature(baseline), signature(rebuilt)
    same = {k for k in before.keys() & after.keys() if before[k][:3] == after[k][:3]}
    manifest = {'kind': 'saved_original_review' if raw_source is not None and not audit else 'derived_gpr_only_review',
        'original_upload_sha256': source_sha256,
        'original_bytes_verified': raw_source is not None, 'saved_parse_refs': parse_refs,
        'scan_incomplete': bool(omitted), 'omitted_sources': omitted,
        'source_sha256': versions.digest(data), 'expected_active_sha256': expected_active_sha256,
        'expected_revision': expected_revision, 'corrections': audit,
        'comparison': {'active_works': len(before), 'prepared_works': len(after),
            'unchanged_identity': len(same), 'added_or_changed_identity': len(after.keys()-same),
            'removed_or_changed_identity': len(before.keys()-same),
            'changed_plan_dates': sum(before[k][5:] != after[k][5:] for k in same),
            'changed_percentages': sum(before[k][3:5] != after[k][3:5] for k in same)},
        'changes': [{'work_id': k, 'before': {'progress': before[k][3], 'progress_date': before[k][4],
                     'start': monitor._iso(before[k][5]), 'finish': monitor._iso(before[k][6])},
                    'after': {'progress': after[k][3], 'progress_date': after[k][4],
                     'start': monitor._iso(after[k][5]), 'finish': monitor._iso(after[k][6])}}
                   for k in sorted(same) if before[k][3:] != after[k][3:]],
        'original_invalid_dates': sum(i.get('code') == 'invalid_date' for i in matches[0].get('issues', [])),
        'prepared_invalid_dates': sum(i.get('code') == 'invalid_date' for i in derived.get('issues', [])),
        'applied': False}
    return {'data': data, 'manifest': manifest}


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True)
    parser.add_argument('--source-sha256', required=True)
    parser.add_argument('--expected-active-sha256', required=True)
    parser.add_argument('--expected-revision', type=int, required=True)
    parser.add_argument('--corrections-json', type=Path)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.project, args.source_sha256,
        expected_active_sha256=args.expected_active_sha256, expected_revision=args.expected_revision,
        corrections=json.loads(args.corrections_json.read_text()) if args.corrections_json else [])
    args.output_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    (args.output_dir/'gpr.xlsx').write_bytes(result['data'])
    (args.output_dir/'review.json').write_text(json.dumps(result['manifest'], ensure_ascii=False, indent=2))
    print(json.dumps({'source_sha256': result['manifest']['source_sha256'], 'applied': False}))


if __name__ == '__main__':
    main()
