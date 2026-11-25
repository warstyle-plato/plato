"""Source-bound contract GPR calendar, decisions and current graph identity.

PDF parses remain immutable inputs. Manual dates are append-only events in
the native card namespace, serialized by the same cross-worker card locks as
document uploads. Every reader uses this projection before plan/fact linking.
"""
from __future__ import annotations

import contextlib
import copy
import datetime as dt
import hashlib
import json
import math
import re
import stat

SCHEMA = 'contract-gpr-calendar-v1'
EVENTS = 'gpr-events.json'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                                     separators=(',', ':')).encode()).hexdigest()


def day(value):
    if not value:
        return None
    try:
        result = dt.date.fromisoformat(value)
        return result if result.isoformat() == value else None
    except (TypeError, ValueError):
        return None


def events(folder):
    from developaid_contract_files import ContractFilesProblem
    import developaid_contract_identity_store as namespace
    path = folder / EVENTS
    raw = namespace.read_bytes(path, 4*1024*1024)
    if raw is None:
        return []
    try:
        stored = json.loads(raw)
        if not isinstance(stored, list) or len(stored) > 10000:
            raise ValueError
        previous = ''
        for index, event in enumerate(stored, 1):
            body = {key: value for key, value in event.items() if key != 'event_id'}
            if event.get('sequence') != index or event.get('previous') != previous or digest(body) != event.get('event_id'):
                raise ValueError
            previous = event['event_id']
        return stored
    except (ValueError, TypeError, OSError):
        raise ContractFilesProblem('История дат и редакций ГПР повреждена. Проверьте хранилище проекта.') from None


def source_key(record):
    identity = record.get('agreement') or record.get('contract') or {}
    return {'sha256': record['sha256'], 'contract': record.get('contract'),
            'edition': {'kind': 'agreement' if record.get('agreement') else 'contract', **identity}}


def guard(folders):
    """Current native metadata and source inventory, including anchor history.

    Relative paths and metadata bytes bind the card; absolute private paths
    never leave this process. The actual selected PDF is hash-verified at
    download, rather than trusting a timestamp as document identity.
    """
    from developaid_contract_files import ContractFilesProblem, MAX_BYTES
    import developaid_contract_identity_store as namespace
    inventory, entries = [], 0
    for folder in folders:
        if folder.is_symlink() or folder.parent.is_symlink():
            raise ContractFilesProblem('Происхождение источников ГПР не подтверждено.')
        for path in sorted(folder.glob('*.json')):
            if re.fullmatch(r'[0-9a-f]{64}\.json', path.name) or path.name in {EVENTS, 'links.json'}:
                raw = namespace.read_bytes(path, 4*1024*1024)
                if raw is None:
                    raise ContractFilesProblem('Состав источников ГПР изменился во время чтения.')
                inventory.append([folder.name, path.name, hashlib.sha256(raw).hexdigest()])
                entries += 1
        for path in sorted(folder.glob('*.pdf')):
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_BYTES:
                raise ContractFilesProblem('Источник ГПР не подходит для ограниченной проверки.')
            inventory.append([folder.name, path.name, info.st_size, info.st_mtime_ns])
            entries += 1
        if entries > 256:
            raise ContractFilesProblem('Число источников ГПР превышает предел одной карточки.')
    return digest(inventory)


def accepted(record, history):
    if not record.get('gpr_pending'):
        return True  # Existing saved graphs retain their explicit unknown signing status.
    return any(event['action'] == 'activate' and event['source'] == source_key(record) for event in history)


def project_records(records, history):
    """A copy only: original cells, financial facts and saved parses are untouched."""
    from developaid_contract_files import _edition
    result = copy.deepcopy(records)
    anchors = {event['source']['sha256']: event for event in history if event['action'] == 'anchor'}
    editions = {}
    for record in result:
        if (record.get('schedule') or {}).get('lines') and not record.get('removed_at') and accepted(record, history):
            editions.setdefault(_edition(record), []).append(record['sha256'])
    for record in result:
        schedule = record.get('schedule')
        if not schedule:
            continue
        record['gpr_status'] = 'accepted' if accepted(record, history) else 'pending_signed_confirmation'
        if len(editions.get(_edition(record), [])) > 1:
            record['gpr_status'] = 'conflicting_edition'
        schedule['source_identity'] = source_key(record)
        schedule['anchor'] = anchors.get(record['sha256'])
        if schedule.get('calendar_basis') != 'relative':
            continue
        anchor = schedule['anchor']
        begin = day((anchor or {}).get('handover_date'))
        schedule['calendar_state'] = 'anchored' if begin else 'relative'
        for column in schedule.get('columns') or []:
            column['start'] = (begin+dt.timedelta(days=column['start_day']-1)).isoformat() if begin else None
            column['finish'] = (begin+dt.timedelta(days=column['finish_day']-1)).isoformat() if begin else None
        for line in schedule.get('lines') or []:
            projected = []
            for segment in line.get('relative_segments') or []:
                projected.append({**segment,
                    'start': (begin+dt.timedelta(days=segment['start_day']-1)).isoformat() if begin else None,
                    'finish': (begin+dt.timedelta(days=segment['finish_day']-1)).isoformat() if begin else None})
            line['segments'] = projected
            line['start'] = min((part['start'] for part in projected), default=None) if begin else None
            line['finish'] = max((part['finish'] for part in projected), default=None) if begin else None
            line['bar'] = {'start': line['start'], 'finish': line['finish']} if line['start'] else None
            line['date_precision'] = 'relative_bar_estimate'
            line['dates_from'] = {'start': 'manual_handover_relative_bar', 'finish': 'manual_handover_relative_bar'}
        for resource in schedule.get('resources') or []:
            columns = {column['period']: column for column in schedule.get('columns') or []}
            for value in resource.get('values') or []:
                column = columns.get(value['period']) or {}
                value.update(start=column.get('start'), finish=column.get('finish'))
    return result


def counted(records):
    """Pending or conflicting new graphs cannot replace the accepted graph."""
    return [{**record, 'schedule': None} if record.get('gpr_status') in
            {'pending_signed_confirmation', 'conflicting_edition'} else record for record in records]


def view(project, contract_id, records, folders, cut):
    from developaid_contract_files import _schedule_identity
    eligible = counted(records)
    active = _schedule_identity(eligible, cut)
    selected = source_key(active) if active else None
    schedule = (active or {}).get('schedule')
    anchor = (schedule or {}).get('anchor') or {}
    conditions = []
    for candidate in ((active or {}).get('terms') or {}).get('candidates') or []:
        if not candidate.get('duration_days'):
            continue
        starts = {'signed_site_handover': day(anchor.get('handover_date')),
                  'paid_advance': day(anchor.get('advance_date'))}
        required = candidate.get('start_conditions') or []
        missing = [name for name in required if not starts.get(name)]
        begin = max((starts[name] for name in required), default=None) if not missing else None
        finish = (begin+dt.timedelta(days=candidate['duration_days'])).isoformat() if begin and candidate.get('days_kind') != 'working' else None
        conditions.append({**candidate, 'missing_triggers': missing, 'reference_finish': finish,
                           'reference_only': True, 'start': begin.isoformat() if begin else None,
                           'note': 'Расчёт по вручную указанным основаниям. Это отдельное условие договора; '
                                   'полосы ГПР не подтверждают оплату аванса или подписание акта. '
                                   'Правила исчисления срока требуют проверки по документу.'})
    return {'schema': SCHEMA, 'project': project, 'contract_id': contract_id, 'cut': cut,
            'guard': guard(folders), 'source': selected, 'schedule': schedule,
            'conditions': conditions,
            'signature_evidence': (active or {}).get('signature_evidence') or
                {'state': 'unknown', 'cryptographically_validated': False},
            'pending': [{'source': source_key(record), 'title': record.get('title'),
                         'signature_evidence': record.get('signature_evidence'), 'state': record['gpr_status']}
                        for record in records if record.get('gpr_status') in
                        {'pending_signed_confirmation', 'conflicting_edition'}],
            'history': [event for folder in folders for event in events(folder)]}


def require_current(binding, *, verify_pdf=False):
    from developaid_contract_files import _folders, ContractFilesProblem
    try:
        folders = _folders(binding['project'], binding.get('documents_raw_id') or binding['contract_id'],
                           {'document_source_ids': binding.get('document_source_ids') or []})
        if guard(folders) != binding['guard']:
            raise ContractFilesProblem('ГПР или дата его начала изменились. Откройте карточку заново.')
        source = binding.get('source')
        if verify_pdf and source:
            found = [folder / (source['sha256']+'.pdf') for folder in folders
                     if (folder / (source['sha256']+'.pdf')).is_file()]
            import developaid_contract_identity_store as namespace
            from developaid_contract_files import MAX_BYTES
            raw = namespace.read_bytes(found[0], MAX_BYTES) if len(found) == 1 else None
            if raw is None or hashlib.sha256(raw).hexdigest() != source['sha256']:
                raise ContractFilesProblem('Исходный PDF ГПР не соответствует сохранённой версии. Обновите карточку.')
    except (KeyError, OSError):
        raise ContractFilesProblem('Источники ГПР недоступны. Откройте карточку заново.') from None


def save(project, row, cut, source_sha256, expected_guard, action, note, actor,
         handover_date='', advance_date='', counterparty_signed=False, acts=None):
    from developaid_contract_files import (_folders, _all_records, _locked, _json, _now, _same_contract,
                                          _edition, _date, awaits_confirmation, listing, ContractFilesProblem)
    if action not in {'anchor', 'activate'} or not isinstance(actor, str) or not actor:
        raise ContractFilesProblem('Не удалось установить автора изменения ГПР.')
    if not isinstance(note, str) or not 5 <= len(note.strip()) <= 1000:
        raise ContractFilesProblem('Укажите основание изменения ГПР: документ или проверенный источник.')
    for value in (handover_date, advance_date):
        if value and not day(value):
            raise ContractFilesProblem('Укажите корректную дату в формате ГГГГ-ММ-ДД.')
    folders = _folders(project, row['id'], acts)
    with contextlib.ExitStack() as locks:
        for folder in sorted(folders):
            locks.enter_context(_locked(folder))
        records = _all_records(folders)
        if guard(folders) != expected_guard:
            raise ContractFilesProblem('Источники или дата начала ГПР изменились. Обновите карточку перед сохранением.')
        record = next((record for record in records if record['sha256'] == source_sha256), None)
        if (record is None or record.get('removed_at') or awaits_confirmation(record)
                or not (record.get('schedule') or {}).get('lines') or not _date(record) or _date(record) > cut):
            raise ContractFilesProblem('Эта редакция ГПР недоступна на выбранную дату.')
        if _same_contract(record.get('contract'), row) or not record.get('contract'):
            raise ContractFilesProblem('Принадлежность ГПР этому договору не подтверждена по исходному документу.')
        history = [event for folder in folders for event in events(folder)]
        projected = project_records(records, history)
        if action == 'anchor':
            current = view(project, row['id'], projected, folders, cut)
            if current.get('source') != source_key(record):
                raise ContractFilesProblem('Выбрана прежняя редакция ГПР. Обновите карточку перед изменением даты.')
            if record['schedule'].get('calendar_basis') != 'relative':
                raise ContractFilesProblem('Этот ГПР содержит календарные даты; дата передачи площадки его не сдвигает.')
        else:
            candidates = [r for r in records if (r.get('schedule') or {}).get('lines') and not r.get('removed_at')
                          and not awaits_confirmation(r) and _date(r) and _date(r) <= cut]
            latest = max(map(_edition, candidates))
            if _edition(record) != latest or sum(_edition(r) == latest for r in candidates) != 1:
                raise ContractFilesProblem('Действующая редакция ГПР неоднозначна. Проверьте документы этой редакции.')
            if counterparty_signed is not True:
                raise ContractFilesProblem('Подтвердите подпись контрагента по документу и укажите её основание.')
        stored = events(folders[0])
        event = {'sequence': len(stored)+1, 'previous': stored[-1]['event_id'] if stored else '',
                 'schema': SCHEMA, 'project': project, 'contract_id': row['id'], 'source': source_key(record),
                 'action': action, 'recorded_at': _now(), 'actor': actor,
                 'origin': 'manual_document_reference', 'note': note.strip(),
                 'handover_date': handover_date if action == 'anchor' else '',
                 'advance_date': advance_date if action == 'anchor' else '',
                 'counterparty_signed': counterparty_signed if action == 'activate' else None,
                 'counterparty': row.get('contractor') or '', 'cryptographically_validated': False,
                 'signature_evidence': record.get('signature_evidence') if action == 'activate' else None}
        event['event_id'] = digest(event)
        _json(folders[0]/EVENTS, [*stored, event])
        return listing(project, row['id'], cut, acts)


def staffing(schedule, actual=(), date=''):
    """Preserve source categories and missingness; never allocate a company crew.

    Only exact contract/scope/category matching decided upstream may supply
    actual rows. No people are summed across work bars or repeated ITR rows.
    """
    resources = (schedule or {}).get('resources') or []
    result = {'date': date, 'state': 'needs_scope_mapping', 'rows': [],
              'note': 'План и ежедневный отчёт сравниваются только за одну дату, категорию и объём работ. '
                      'Общая бригада и общие ИТР не распределяются между работами без подтверждённого основания.'}
    for resource in resources:
        for value in resource.get('values') or []:
            if value.get('start') and value['start'] <= date <= value['finish']:
                result['rows'].append({'category': resource['category'], 'source_label': resource['name'],
                                       'plan': value['value'], 'fact': None, 'fact_present': False,
                                       'source': resource.get('source'), 'scope': resource.get('scope')})
    return result


def workforce_sources(project, row, register, date, schedule):
    """Dated raw report evidence beside, rather than allocated to, plan rows.

    Legacy parsed zeroes are re-read from the raw message with presence flags.
    Repeated company names/scopes and combined plan categories stay unresolved.
    """
    import developaid_monitor_daily as daily
    import developaid_monitor_crew as crew
    result = staffing(schedule, date=date)
    reports = [report for report in daily._load_reports(project) if report.get('date') == date]
    result.update(report_present=bool(reports), actual_candidates=[], matched=False)
    target = crew.name_key(row.get('contractor'))
    if not target:
        return result
    peers = [other for other in register.get('rows') or [] if crew.name_key(other.get('contractor')) == target]
    for report in reports:
        raw = str(report.get('text') or '')
        # Re-read source labels: old saved parsers used 0 for an absent label.
        for original in raw.splitlines():
            itr, workers = daily._ITR.search(original), daily._WORKERS.search(original)
            if not itr and not workers:
                continue
            end = min(match.start() for match in (itr, workers) if match)
            name = daily._LEAD_NUM.sub('', original[:end]).strip(' \t:—–-.,;')
            if crew.name_key(name) != target:
                continue
            result['actual_candidates'].append({'date': date, 'party': name, 'raw': original,
                'workers': int(workers[1]) if workers else None, 'workers_present': bool(workers),
                'itr': int(itr[1]) if itr else None, 'itr_present': bool(itr),
                'source': {'kind': 'daily_report', 'date': date, 'text_sha256': hashlib.sha256(raw.encode()).hexdigest()},
                'status': 'needs_contract_scope' if len(peers) != 1 else 'needs_resource_scope',
                'reason': 'Численность сообщения не распределена между договорами и строками ГПР. '
                          'Нужно совпадение состава работ и отдельной категории персонала.'})
    return result


def physical_overlays(listed, rds):
    """Use the reviewed RDS attribution gate, never a money readiness ratio."""
    current = next((edition for edition in listed.get('plan', {}).get('editions') or [] if edition.get('in_force')), {})
    links = {(item['estimate'], item['index']): item for item in current.get('position_links') or []}
    collected = {}
    for row in rds.get('rows') or []:
        binding = links.get((row.get('estimate'), row.get('index'))) or {}
        targets = binding.get('lines') or []
        if len(targets) != 1 or targets[0].get('share') != 1:
            continue
        code = targets[0]['code']
        collected.setdefault(code, []).append(row)
    result = {}
    for code, rows in collected.items():
        row = rows[0]
        # day_deviation is set only by the shared full-share, unit/quantity,
        # unique source/control/position evidence predicate in contract_rds.
        if len(rows) != 1 or row.get('day_deviation') is None or row.get('fact_quantity_ratio') is None:
            continue
        ready = row['fact_quantity_ratio']
        planned = row.get('plan_quantity_ratio')
        if not isinstance(ready, (int, float)) or not math.isfinite(ready):
            continue
        result[code] = {'fact_fraction': min(max(ready, 0), 1),
                        'planned_fraction': min(max(planned, 0), 1) if isinstance(planned, (int, float)) else None,
                        'fact_quantity': row['fact_quantity'], 'contract_quantity': row['contract_quantity'],
                        'unit': row['unit'], 'lag_days': max(row['day_deviation'], 0),
                        'source': rds.get('source'), 'basis': 'physical_cut_projection',
                        'note': 'Доля физического выполнения на дату среза показана на исходной полосе. '
                                'Это проекция накопительного объёма, а не ежедневная история производства.'}
    return result
