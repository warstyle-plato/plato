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


SOURCE_CHOICE_SCHEMA = 'contract-gpr-source-choice-v1'
MAX_CHOICE_SOURCES = 64
MAX_CHOICE_HISTORY = 2048


def _activation_ok(event):
    return (event.get('action') == 'activate' and event.get('schema') == SCHEMA
        and event.get('counterparty_signed') is True and event.get('origin') == 'manual_document_reference'
        and isinstance(event.get('actor'), str) and bool(event['actor'])
        and isinstance(event.get('note'), str) and 5 <= len(event['note']) <= 1000)


def accepted(record, history):
    if not record.get('gpr_pending'):
        return True  # Existing recognised legacy graphs retain unknown signing status.
    return any(_activation_ok(event) and event.get('source') == source_key(record) for event in history)


def _usable(record):
    # Preserve the existing saved legacy projection, including a graph whose
    # header identity was not parsed. New activations have a stricter boundary.
    from developaid_contract_files import awaits_confirmation
    return bool(isinstance(record.get('sha256'), str) and re.fullmatch(r'[0-9a-f]{64}', record['sha256'])
        and not record.get('removed_at') and not record.get('act')
        and (record.get('schedule') or {}).get('lines') and not awaits_confirmation(record))


def _admissible(record):
    if not _usable(record):
        return False
    contract, agreement, scan = record.get('contract'), record.get('agreement'), record.get('scan')
    confirmed = scan is None
    if isinstance(scan, dict):
        import developaid_contract_identity_store as namespace
        try:
            namespace._timestamp(scan.get('confirmed_at'))
            confirmed = True
        except (ValueError, TypeError):
            confirmed = False
    return bool(isinstance(contract, dict) and isinstance(contract.get('number'), str) and contract['number']
        and day(contract.get('date'))
        and (agreement is None or isinstance(agreement, dict) and isinstance(agreement.get('number'), str)
             and agreement['number'] and day(agreement.get('date')))
        and confirmed)


def _legal_group(source):
    # Ordering alone is not legal identity: e.g. two nonnumeric DS numbers
    # on the same date must never be conflated by _edition's numeric fallback.
    return digest({'contract': source.get('contract'), 'edition': source.get('edition')})


def _source_schedule(record):
    value = copy.deepcopy(record.get('schedule') or {})
    for key in ('source_identity', 'anchor', 'calendar_state', 'unfit'):
        value.pop(key, None)
    if value.get('calendar_basis') == 'relative':
        for line in value.get('lines') or []:
            for key in ('segments', 'start', 'finish', 'bar', 'date_precision', 'dates_from'):
                line.pop(key, None)
        for column in value.get('columns') or []:
            column.pop('start', None); column.pop('finish', None)
        for resource in value.get('resources') or []:
            for cell in resource.get('values') or []:
                cell.pop('start', None); cell.pop('finish', None)
    return value


def _candidate(record):
    return {'source': source_key(record), 'schedule_sha256': digest(_source_schedule(record)),
            'scan_sha256': digest(record.get('scan')), 'signature_evidence_sha256': digest(record.get('signature_evidence')),
            'pending': bool(record.get('gpr_pending'))}


def _latest_candidates(records, cut):
    from developaid_contract_files import _edition, _date
    eligible = [record for record in records if _admissible(record) and _date(record) <= cut]
    if not eligible:
        return []
    latest = max(map(_edition, eligible))
    return sorted((record for record in eligible if _edition(record) == latest), key=lambda record: record['sha256'])


def _history_witness(history):
    from developaid_contract_files import ContractFilesProblem
    identifiers = [event['event_id'] for event in history]
    if len(identifiers) > MAX_CHOICE_HISTORY or len(set(identifiers)) != len(identifiers):
        raise ContractFilesProblem('История выбора ГПР неоднозначна или превышает предел проверки.')
    return sorted(identifiers), digest(sorted(history, key=lambda event: event['event_id']))


def _valid_choice(event, records, history):
    """Persistent choice of exact source components, never graph equivalence."""
    from developaid_contract_files import _edition
    try:
        proof = event.get('source_choice')
        if not _activation_ok(event) or not isinstance(proof, dict) or set(proof) != {
                'schema', 'candidates', 'candidates_sha256', 'guard_before',
                'history_event_ids_before', 'history_sha256_before'} or proof['schema'] != SOURCE_CHOICE_SCHEMA:
            return None
        candidates = proof['candidates']
        if not isinstance(candidates, list) or not 1 <= len(candidates) <= MAX_CHOICE_SOURCES:
            return None
        if digest(candidates) != proof['candidates_sha256'] or not re.fullmatch(r'[0-9a-f]{64}', proof['guard_before']):
            return None
        source = event['source']; group = _legal_group(source)
        wanted = [candidate['source']['sha256'] for candidate in candidates]
        if len(set(wanted)) != len(wanted) or wanted != sorted(wanted) or source['sha256'] not in wanted:
            return None
        current = {record['sha256']: record for record in records if _admissible(record)}
        if any(sha not in current or _candidate(current[sha]) != candidate
               or _legal_group(candidate['source']) != group for sha, candidate in zip(wanted, candidates)):
            return None
        if _candidate(current[source['sha256']])['source'] != source:
            return None
        before = proof['history_event_ids_before']
        by_id = {item['event_id']: item for item in history}
        if (not isinstance(before, list) or len(before) > MAX_CHOICE_HISTORY or before != sorted(set(before))
                or len(by_id) != len(history) or event['event_id'] in before or any(key not in by_id for key in before)
                or event.get('previous') and event['previous'] not in before
                or digest([by_id[key] for key in before]) != proof['history_sha256_before']):
            return None
        order = _edition(current[source['sha256']])
        extras = [record for record in records if _admissible(record) and _edition(record) == order
                  and record['sha256'] not in wanted]
        # Passive discovery of a new unaccepted graph never displaces the
        # selected source. The next explicit choice still guards the COMPLETE
        # new candidate set. Recognised/activated extras require a new choice.
        if any(not record.get('gpr_pending') or accepted(record, history) for record in extras):
            return None
        return {'event': event, 'source_sha256': source['sha256'], 'group': group,
                'before': set(before), 'candidate_set_sha256': proof['candidates_sha256']}
    except (KeyError, TypeError, ValueError, AttributeError):
        return None


def _choices(records, history):
    ever, valid, bound_sources = set(), {}, set()
    for event in history:
        if (event.get('action') == 'activate' and isinstance(event.get('source_choice'), dict)
                and event['source_choice'].get('schema') == SOURCE_CHOICE_SCHEMA):
            ever.add(_legal_group(event.get('source') or {}))
            for candidate in event['source_choice'].get('candidates') or []:
                if isinstance(candidate, dict) and isinstance(candidate.get('source'), dict):
                    sha = candidate['source'].get('sha256')
                    if isinstance(sha, str) and re.fullmatch(r'[0-9a-f]{64}', sha):
                        bound_sources.add(sha)
        choice = _valid_choice(event, records, history)
        if choice:
            valid.setdefault(choice['group'], []).append(choice)
    selected = {}
    for group, choices in valid.items():
        maximal = [choice for choice in choices if not any(choice['event']['event_id'] in other['before']
                   for other in choices if other is not choice)]
        if len(maximal) == 1:
            selected[group] = maximal[0]
    return ever, selected, bound_sources


def _verify_candidate_pdfs(folders, candidates):
    from developaid_contract_files import ContractFilesProblem, MAX_BYTES
    import developaid_contract_identity_store as namespace
    total = 0
    if len(candidates) > MAX_CHOICE_SOURCES:
        raise ContractFilesProblem('Слишком много источников одной редакции ГПР для ограниченной проверки.')
    for record in candidates:
        sha = record['sha256']
        found = [folder/(sha+'.pdf') for folder in folders if (folder/(sha+'.pdf')).exists()]
        if len(found) != 1:
            raise ContractFilesProblem('Точное происхождение PDF источника ГПР неоднозначно или файл отсутствует.')
        raw = namespace.read_bytes(found[0], MAX_BYTES)
        if raw is None or not raw.startswith(b'%PDF') or hashlib.sha256(raw).hexdigest() != sha:
            raise ContractFilesProblem('PDF источника ГПР не соответствует сохранённому SHA256.')
        total += len(raw)
        if total > 64*1024*1024:
            raise ContractFilesProblem('Объём источников одной редакции ГПР превышает предел проверки.')


def project_records(records, history):
    """A copy only: original cells, financial facts and saved parses are untouched."""
    from developaid_contract_files import _edition
    result = copy.deepcopy(records)
    anchors = {event['source']['sha256']: event for event in history if event['action'] == 'anchor'}
    ever, selected, bound_sources = _choices(result, history)
    editions = {}
    for record in result:
        if _usable(record) and accepted(record, history):
            editions.setdefault(_edition(record), []).append(record['sha256'])
    for record in result:
        schedule = record.get('schedule')
        if not schedule:
            continue
        record['_gpr_candidate_witness'] = _candidate(record)
        group = _legal_group(source_key(record))
        choice = selected.get(group)
        record['gpr_status'] = 'accepted' if _usable(record) and accepted(record, history) else 'pending_signed_confirmation'
        if group in ever or record['sha256'] in bound_sources:
            if choice and choice['source_sha256'] == record['sha256']:
                record['gpr_status'] = 'accepted'
                record['gpr_choice_event_id'] = choice['event']['event_id']
            elif record['gpr_status'] == 'accepted' or not choice:
                record['gpr_status'] = 'conflicting_edition'
        elif len(editions.get(_edition(record), [])) > 1 and record['gpr_status'] == 'accepted':
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
    from developaid_contract_files import _schedule_identity, _edition, _date, awaits_confirmation
    eligible = counted(records)
    active = _schedule_identity(eligible, cut)
    selected = source_key(active) if active else None
    candidates = _latest_candidates(records, cut)
    legal = len({_legal_group(source_key(record)) for record in candidates}) == 1
    activatable = {record['sha256'] for record in candidates} if legal else set()
    schedule = (active or {}).get('schedule')
    pending = [record for record in records if record.get('gpr_status') in
               {'pending_signed_confirmation', 'conflicting_edition'}]
    previews = [record for record in pending if not record.get('removed_at') and not awaits_confirmation(record)
                and _date(record) and _date(record) <= cut]
    preview = max(previews, key=_edition) if previews and active is None else None
    if preview:
        import developaid_contract_gpr_export as exporter
        preview = {'source': source_key(preview), 'schedule': preview['schedule'],
                   'presentation': exporter.presentation(preview['schedule'], {}, cut),
                   'note': 'Предварительный просмотр обнаруженного ГПР. Редакция ещё не принята; '
                           'в расчёт, прогноз и выгрузку действующего графика не включена.'}
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
            'preview': preview,
            'activation_candidate_set': [record.get('_gpr_candidate_witness') or _candidate(record) for record in candidates],
            'conditions': conditions,
            'signature_evidence': (active or {}).get('signature_evidence') or
                {'state': 'unknown', 'cryptographically_validated': False},
            'pending': [{'source': source_key(record), 'title': record.get('title'), 'filename': record.get('filename'),
                         'signature_evidence': record.get('signature_evidence'), 'state': record['gpr_status'],
                         'can_activate': record['sha256'] in activatable,
                         'choice_required': len(candidates) > 1 or record['gpr_status'] == 'conflicting_edition',
                         'discovery': record.get('gpr_discovery')}
                        for record in pending],
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
            candidates = _latest_candidates(records, cut)
            if record not in candidates:
                raise ContractFilesProblem('Выберите источник последней допустимой редакции ГПР на дату среза.')
            if len({_legal_group(source_key(candidate)) for candidate in candidates}) != 1:
                raise ContractFilesProblem('Последние источники имеют разные реквизиты договора или редакции. Сначала проверьте их принадлежность.')
            if counterparty_signed is not True:
                raise ContractFilesProblem('Подтвердите подпись контрагента по документу и укажите её основание.')
            _verify_candidate_pdfs(folders, candidates)
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
        if action == 'activate':
            before_ids, before_hash = _history_witness(history)
            candidate_set = [_candidate(candidate) for candidate in candidates]
            event['source_choice'] = {'schema': SOURCE_CHOICE_SCHEMA, 'candidates': candidate_set,
                'candidates_sha256': digest(candidate_set), 'guard_before': expected_guard,
                'history_event_ids_before': before_ids, 'history_sha256_before': before_hash}
        if guard(folders) != expected_guard:
            raise ContractFilesProblem('Источники или история ГПР изменились во время проверки. Обновите карточку.')
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
    from collections import Counter
    binding_counts = Counter((item['estimate'], item['index']) for item in current.get('position_links') or [])
    links = {(item['estimate'], item['index']): item for item in current.get('position_links') or []}
    collected = {}
    for row in rds.get('rows') or []:
        if binding_counts[(row.get('estimate'), row.get('index'))] != 1:
            continue
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
                        'source': rds.get('source'), 'basis': 'cumulative_quantity_at_cut',
                        'note': 'Накопленный физический объём на дату среза. '
                                'Он не подтверждает даты или непрерывность производства работ.'}
    return result


def position_projections(listed, rds, schedule):
    """Expose RDS operations without summing them into a construction percent.

    The RDS reader already decides whether a physical observation is attributable.
    Its day predicate is retained; the exact accepted link supplies the source
    GPR segments, including gaps. Dates or similar position numbers are not links.
    """
    if not rds.get('available'):
        return []
    from collections import Counter
    current = next((e for e in listed.get('plan', {}).get('editions') or [] if e.get('in_force')), {})
    binding_counts = Counter((b['estimate'], b['index']) for b in current.get('position_links') or [])
    bindings = {(b['estimate'], b['index']): b for b in current.get('position_links') or []}
    source_lines = schedule.get('lines') or []
    counts = Counter(line['code'] for line in source_lines)
    source = {line['code']: line for line in source_lines}
    identities = Counter((r.get('estimate'), r.get('index')) for r in rds.get('rows') or [])
    headings = {h['before_position']: h['name'] for h in rds.get('headings') or [] if not h.get('number')}
    result, section = [], ''
    for index, row in enumerate(rds.get('rows') or []):
        section = headings.get(index, section)
        identity = (row.get('estimate'), row.get('index'))
        binding = (bindings.get(identity) or {}) if binding_counts[identity] == 1 else {}
        targets = binding.get('lines') or [] if binding.get('status') in ('confirmed', 'proposed') else []
        target = targets[0] if len(targets) == 1 and targets[0].get('share') == 1 else {}
        parent = source.get(target.get('code')) if counts[target.get('code')] == 1 else None
        line = copy.deepcopy(parent) if parent else {}
        key = 'rds:'+str(identity[0])+':'+str(identity[1])
        line.update(code=key, name=row.get('name') or '', number=row.get('number') or '',
                    section=section, gpr_code=(parent or {}).get('code'), position_key=list(identity))
        quantity, total, ready = row.get('fact_quantity'), row.get('contract_quantity'), row.get('fact_quantity_ratio')
        numeric = lambda value: type(value) in (int, float) and math.isfinite(value)
        known = (numeric(quantity) and quantity >= 0 and numeric(total) and total > 0 and
                 numeric(ready) and ready >= 0 and math.isclose(ready, quantity/total, abs_tol=1e-9))
        line['quantity'] = {'fact_quantity': quantity, 'contract_quantity': total,
                            'unit': row.get('unit') or '', 'fraction': ready} if known else None
        line['physical'] = None
        if (known and parent and row.get('unit') and numeric(row.get('day_deviation')) and identities[identity] == 1 and
                day(row.get('start')) and day(row.get('finish')) and
                (row['start'], row['finish']) == (parent.get('start'), parent.get('finish'))):
            planned = row.get('plan_quantity_ratio')
            line['physical'] = {**line['quantity'], 'fact_fraction': min(ready, 1),
                'planned_fraction': min(max(planned, 0), 1) if numeric(planned) else None,
                'lag_days': max(row['day_deviation'], 0), 'source': rds.get('source'),
                'basis': 'cumulative_quantity_at_cut', 'note': 'Накопленный объём отдельной операции по РДС. '
                    'Он не задаёт календарных интервалов. Операции не складываются в общий физический процент конструкции.'}
        line['note'] = ((row.get('comments') or {}).get('fact_quantity') or
                        'Известный объём отдельной операции; это не общий процент строки ГПР.')
        result.append(line)
    return result
