"""Explicit source-role correction over immutable native contract observations.

No aliases or numeric overrides. Raw trees are kept once; active rows reference
selected execution, qualified price and existing legal-document owners.
"""
from __future__ import annotations

import datetime as dt

import developaid_contract_identity as identity
import developaid_contract_identity_store as store

SCHEMA = 'contract-source-correction-v1'
SOURCE_POLICY = 'follow_selected_native_v1'
EXECUTION_FIELDS = ('id', 'source_kind', 'source_date', 'source_snapshot_id', 'physical_items',
                    'completed', 'completed_basis', 'completed_works', 'completed_materials',
                    'works_materials_split', 'reported_performance_sources', 'detail_history')
PRICE_FIELDS = ('amount', 'amount_basis', 'amount_source', 'amount_source_label', 'amount_documents',
                'financial_sources', 'source', 'source_date', 'source_snapshot_id')
HEAVY_FIELDS = {'physical_items', 'raw_observations', 'reconciliation'}
SAVED_EXECUTION = ('completed', 'completed_basis', 'completed_works', 'completed_materials',
                   'works_materials_split', 'source_date', 'source_snapshot_id', 'source_kind',
                   'summary_progress', 'statement_progress', 'reported_performance_sources')
SAVED_PRICE = ('amount', 'amount_basis', 'amount_source', 'amount_source_label', 'amount_documents')
DOCUMENT_EVIDENCE_FIELDS = ('document_sha256', 'price_sha256', 'binding_identity_sha256', 'edition_sha256', 'terms_sha256', 'reader_version_sha256')
ROLE_FIELDS = {'execution_raw_id', 'execution_token', 'price_raw_id', 'price_token', 'documents_raw_id'}


def _hash(value):
    return isinstance(value, str) and bool(store.HASH.fullmatch(value))


def execution_token(row):
    values = {key: row.get(key) for key in EXECUTION_FIELDS}
    values['physical_items'] = [{key: value for key, value in item.items() if key != 'quantity_cut'}
                               for item in row.get('physical_items') or []]
    values['closing_observations'] = [source for source in row.get('financial_sources') or []
                                      if str(source.get('label') or '').startswith('Сводная')]
    return store.digest({'schema': SCHEMA, 'execution': values})


def price_token(row):
    if row.get('amount') is None:
        return None
    return store.digest({'schema': SCHEMA, 'raw_id': row['id'],
                         'price': {key: row.get(key) for key in PRICE_FIELDS}})


def validate_payload(payload):
    fields = {'schema', 'members', 'reviewed_archives', 'inventory_cut', 'inventory_sha256',
              'canonical_source_token', 'roles', 'applies_from', 'note', 'bindings_sha256', 'selected_values', 'source_policy', 'price_document_evidence'}
    bad = store.IdentityProblem('Запись выбора исправленных источников не подтверждена.', 503)
    if not isinstance(payload, dict) or set(payload) != fields or payload['schema'] != SCHEMA or payload.get('source_policy') != SOURCE_POLICY:
        raise bad
    members = payload['members']
    if not isinstance(members, list) or not 2 <= len(members) <= identity.MAX_VERSIONS:
        raise bad
    for member in members:
        store.validate_member(member)
    ids = {member['raw_id'] for member in members}
    if not 2 <= len(ids) <= 8 or len({m['source_token'] for m in members}) != len(members):
        raise bad
    canonical = next((m for m in members if m['source_token'] == payload['canonical_source_token']), None)
    roles = payload['roles']
    if (canonical is None or not isinstance(roles, dict) or set(roles) != ROLE_FIELDS
            or not _hash(roles['execution_raw_id']) or not _hash(roles['documents_raw_id'])
            or roles['execution_raw_id'] not in ids or roles['documents_raw_id'] not in ids
            or not _hash(roles['execution_token'])
            or (roles['price_raw_id'] is None) != (roles['price_token'] is None)
            or roles['price_raw_id'] is not None and (not _hash(roles['price_raw_id']) or roles['price_raw_id'] not in ids or not _hash(roles['price_token']))):
        raise bad
    selected = payload['selected_values']
    if (not isinstance(selected, dict) or set(selected) != {'execution', 'price'}
            or not isinstance(selected['execution'], dict) or set(selected['execution']) != set(SAVED_EXECUTION)
            or not isinstance(selected['price'], dict) or set(selected['price']) != set(SAVED_PRICE)):
        raise bad
    evidence = payload['price_document_evidence']
    if evidence is not None and (not isinstance(evidence, dict) or set(evidence) != set(DOCUMENT_EVIDENCE_FIELDS)
            or any(not _hash(value) for value in evidence.values())):
        raise bad
    if not isinstance(payload['inventory_cut'], str) or store.day(payload['inventory_cut']) != payload['inventory_cut']:
        raise bad
    archives = payload['reviewed_archives']
    if (not isinstance(archives, list) or not 1 <= len(archives) <= identity.MAX_ARCHIVES
            or any(not isinstance(sid, str) or not identity.SNAP.fullmatch(sid)
                   or store.day(sid[:10]) != sid[:10] or sid[:10] > payload['inventory_cut'] for sid in archives)
            or archives != sorted(set(archives))
            or any(m['snapshot_id'] not in archives for m in members)
            or store.day(payload['inventory_cut']) != payload['inventory_cut']
            or store.day(payload['applies_from']) != payload['applies_from']
            or payload['applies_from'] != max(canonical['source_date'],
                max(m['source_date'] for m in members if m['raw_id'] == roles['execution_raw_id']))
            or not _hash(payload['inventory_sha256']) or not _hash(payload['bindings_sha256'])
            or not isinstance(payload['note'], str) or not payload['note'].strip() or len(payload['note']) > 500):
        raise bad


def _raw_register(project, cut):
    import developaid_contract_ownership as ownership
    import developaid_monitor_contracts as contracts
    with ownership.raw_history():
        return contracts.build(project, cut, include_history=False)


def _inventory(project, raw_ids, cut):
    import developaid_monitor_contracts as contracts
    ids = identity.correction_ids(raw_ids)
    if len(ids) < 2:
        raise store.IdentityProblem('Выберите не меньше двух исходных карточек.', 400)
    cut = contracts._cut(cut)
    state = store.load(project)
    versions, archives = identity._source_inventory(project, cut, ids, correction=True)
    if {m['raw_id'] for m in versions} != set(ids):
        raise store.IdentityProblem('Одна из карточек не подтверждена в источниках проекта.', 404)
    register = _raw_register(project, cut)
    rows = {row['id']: row for row in register['rows'] if row['id'] in ids}
    if set(rows) != set(ids):
        raise store.IdentityProblem('На выбранную дату представлены не все исходные карточки.', 409)
    candidates = []
    for identifier in ids:
        row = rows[identifier]
        candidates.append({'raw_id': identifier, 'identity': {key: row.get(key) for key in
            ('contract', 'contract_date', 'customer', 'contractor')},
            'execution_token': execution_token(row), 'price_token': price_token(row),
            'amount': row.get('amount'), 'amount_basis': row.get('amount_basis'),
            'amount_source': row.get('amount_source') or row.get('source'),
            'completed': row.get('completed'), 'completed_basis': row.get('completed_basis'),
            'physical_items': len(row.get('physical_items') or []),
            'progress': {key: (row.get('progress') or row.get('summary_progress') or {}).get(key)
                         for key in ('state', 'ratio', 'basis', 'reason')},
            'source_date': row.get('source_date')})
    result = {'schema': SCHEMA, 'source_policy': SOURCE_POLICY, 'project_scope': store.project_scope(project), 'cut': cut,
              'raw_ids': ids, 'revision': state['revision'], 'decision_head': state['head'],
              'source_versions': versions, 'reviewed_archives': archives,
              'bindings': identity.metadata_inventory(project, ids, correction=True),
              'candidates': candidates, 'financial_acceptance_required': False}
    result['inventory_sha256'] = store.digest(result)
    if len(store.canonical(result)) > identity.MAX_OUTPUT_BYTES:
        raise store.IdentityProblem('Проверка источников превышает ограниченный размер.', 413)
    return result, rows


@store.in_namespace
def inventory(project, raw_ids, cut):
    return _inventory(project, raw_ids, cut)[0]


def _selection(checked, rows, canonical_source_token, execution_token_value, price_token_value, documents_raw_id):
    canonical = next((m for m in checked['source_versions'] if m['source_token'] == canonical_source_token), None)
    execution = [row for row in rows.values() if execution_token(row) == execution_token_value]
    prices = [row for row in rows.values() if price_token_value is not None and price_token(row) == price_token_value]
    if (canonical is None or len(execution) != 1 or price_token_value is not None and len(prices) != 1
            or documents_raw_id not in rows):
        raise store.IdentityProblem('Выберите точные проверенные источники реквизитов, выполнения, цены и документов.', 409)
    roles = dict(execution_raw_id=execution[0]['id'], execution_token=execution_token_value,
                 price_raw_id=prices[0]['id'] if prices else None, price_token=price_token_value,
                 documents_raw_id=documents_raw_id)
    return canonical, roles


@store.in_namespace
def preview(project, raw_ids, cut, *, canonical_source_token, execution_token, price_token, documents_raw_id):
    checked, rows = _inventory(project, raw_ids, cut)
    canonical, roles = _selection(checked, rows, canonical_source_token, execution_token, price_token, documents_raw_id)
    checked['preview'] = {'canonical_identity': canonical['identity'], 'logical_id': canonical['raw_id'],
        'roles': roles, 'old_identities': [candidate['identity'] for candidate in checked['candidates']],
        'consequences': ['Исходные карточки и документы сохраняются по прежним адресам.',
                         'Выполнение и цена берутся из выбранных источников без сложения копий.',
                         'Срок, ГПР и выборы позиций читаются из выбранной карточки документов.',
                         'Новые КС с точными исправленными реквизитами и проверенные ДС этой карточки читаются штатно.',
                         'Процент и остаток требуют совместимых оснований; оплаты и связи работ не переносятся.']}
    checked['preview_sha256'] = store.digest(checked)
    return checked


@store.in_namespace
def confirm(project, raw_ids, cut, *, expected_revision, expected_decision_head, inventory_sha256,
            preview_sha256, source_tokens, canonical_source_token, execution_token, price_token,
            documents_raw_id, note, actor):
    if (not isinstance(note, str) or not note.strip() or len(note) > 500
            or not isinstance(source_tokens, list) or any(not _hash(token) for token in source_tokens)
            or len(source_tokens) != len(set(source_tokens))):
        raise store.IdentityProblem('Укажите все проверенные версии и основание исправления.', 400)
    with store.locked(project), identity._binding_locks(project, raw_ids, correction=True):
        selection = dict(canonical_source_token=canonical_source_token, execution_token=execution_token,
                         price_token=price_token, documents_raw_id=documents_raw_id)
        checked = preview(project, raw_ids, cut, **selection)
        if (type(expected_revision) is not int or checked['revision'] != expected_revision
                or checked['decision_head'] != expected_decision_head
                or checked['inventory_sha256'] != inventory_sha256 or checked['preview_sha256'] != preview_sha256
                or set(source_tokens) != {m['source_token'] for m in checked['source_versions']}):
            raise store.IdentityProblem('Источники, выборы или журнал изменились. Обновите предварительный просмотр.', 409)
        roles = checked['preview']['roles']
        canonical = next(m for m in checked['source_versions'] if m['source_token'] == canonical_source_token)
        current_rows = {row['id']: row for row in _raw_register(project, cut)['rows']}
        selected_execution = current_rows[roles['execution_raw_id']]
        selected_price = current_rows.get(roles['price_raw_id']) or {}
        price_sha = (selected_price.get('amount_source') or {}).get('sha256')
        price_card = next((card for card in checked['bindings']['cards'] if card['raw_id'] == roles['price_raw_id']), {})
        price_document = next((doc for doc in price_card.get('documents') or [] if doc['document_sha256'] == price_sha), None)
        payload = {'schema': SCHEMA, 'source_policy': SOURCE_POLICY,
            'price_document_evidence': {key: price_document[key] for key in DOCUMENT_EVIDENCE_FIELDS} if price_document else None,
            'selected_values': {'execution': {key: selected_execution.get(key) for key in SAVED_EXECUTION},
                                'price': {key: selected_price.get(key) for key in SAVED_PRICE}}, 'members': checked['source_versions'],
            'reviewed_archives': checked['reviewed_archives'], 'inventory_cut': checked['cut'],
            'inventory_sha256': inventory_sha256, 'canonical_source_token': canonical_source_token,
            'roles': roles, 'bindings_sha256': store.digest(checked['bindings']), 'note': note.strip(),
            'applies_from': max(canonical['source_date'], max(m['source_date'] for m in checked['source_versions']
                                                           if m['raw_id'] == roles['execution_raw_id']))}
        validate_payload(payload)
        if preview(project, raw_ids, cut, **selection)['preview_sha256'] != preview_sha256:
            raise store.IdentityProblem('Данные изменились во время проверки. Решение не сохранено.', 409)
        return store.append_locked(project, expected_revision=expected_revision, actor=actor,
                                   action='correct_sources', payload=payload)


def resolve(project, event, cut, *, register=None, cache=None, active=True):
    import developaid_monitor_contracts as contracts
    payload = event['payload']
    validate_payload(payload)
    cut = contracts._cut(cut)
    ids = sorted({m['raw_id'] for m in payload['members']})
    canonical = next(m for m in payload['members'] if m['source_token'] == payload['canonical_source_token'])
    result = {'resolution_kind': 'source_correction', 'status': 'source_conflict', 'logical_id': canonical['raw_id'],
              'member_ids': ids, 'decision_id': event['event_id'], 'decision_recorded_at': event['recorded_at'],
              'applies_from': payload['applies_from'],
              'canonical_identity': canonical['identity'], 'canonical_number': canonical['identity']['contract'],
              'roles': payload['roles'], 'financial_acceptance_required': False,
              'source_policy': SOURCE_POLICY, 'role_freshness': {'execution': False, 'price': False},
              'selected_values': payload['selected_values'], 'membership_confirmed': active and cut >= payload['applies_from'],
              'reason': 'Выбранные источники изменились. Обновите проверку; исходные показатели сохранены.'}
    if not active or cut < payload['applies_from']:
        return dict(result, status='revoked' if not active else 'historical_raw', reason='')
    cache = cache if cache is not None else {}
    versions, archives = identity._source_inventory(project, cut, ids, correction=True, cache=cache)
    approved = [m for m in payload['members'] if m['source_date'] <= cut]
    roles = payload['roles']
    key = lambda m: store.digest({field: m[field] for field in ('raw_id', 'identity', 'sources')})
    approved_keys = {key(m) for m in approved}
    originals_intact = ({m['source_token'] for m in approved} <= {m['source_token'] for m in versions}
                        and set(payload['reviewed_archives']) <= set(archives))
    new_versions = [m for m in versions if key(m) not in approved_keys]
    # Only a selected canonical execution source may advance normally. Replayed
    # identical observations are evidence copies, never extra money.
    canonical_key = contracts._identity(canonical['identity'])
    lawful_execution = lambda m: (m['raw_id'] == roles['execution_raw_id'] == canonical['raw_id']
                                  and canonical_key is not None
                                  and contracts._identity(m['identity']) == canonical_key)
    safe_sources = originals_intact and all(lawful_execution(m) for m in new_versions)
    references = {contracts._reference_key(m['identity']) for m in approved}
    extra_archives_safe = True
    for sid in set(archives) - set(payload['reviewed_archives']):
        observations = cache.get(('identities', sid))
        if (observations is None or cache.get(('unresolved', sid))
                or any(tuple(item['reference']) in references and item['raw_id'] not in ids for item in observations)):
            safe_sources = False
            extra_archives_safe = False
    register = register if register is not None else _raw_register(project, cut)
    rows = {row['id']: row for row in contracts.raw_rows(register) if row['id'] in ids}
    execution, price = rows.get(roles['execution_raw_id']), rows.get(roles['price_raw_id'])
    new_execution = [m for m in new_versions if m['raw_id'] == roles['execution_raw_id']]
    execution_fresh = bool(originals_intact and execution is not None and
        (not new_execution or extra_archives_safe and all(lawful_execution(m) for m in new_execution)))
    evidence = payload['price_document_evidence']
    document_evidence_intact = True
    if evidence is not None:
        bindings = cache.get(('bindings', tuple(ids)))
        if bindings is None:
            bindings = identity.metadata_inventory(project, ids, correction=True)
        card = next((card for card in bindings['cards'] if card['raw_id'] == roles['price_raw_id']), {})
        document = next((doc for doc in card.get('documents') or [] if doc['document_sha256'] == evidence['document_sha256']), None)
        document_evidence_intact = bool(document and all(document.get(key) == evidence[key] for key in DOCUMENT_EVIDENCE_FIELDS))
        if not document_evidence_intact:
            import developaid_contract_price_provenance as provenance
            continuity = (document or {}).get(provenance.FIELD)
            document_evidence_intact = provenance.accepts(continuity, event, price)
            result['price_reader_provenance'] = continuity or {'state': 'unsupported',
                'reason': 'unsupported_reader_price_evidence'}
            if not document_evidence_intact:
                result['reason'] = ('Сохранённое подтверждение цены не содержит проверяемого свидетельства '
                    'исходного разбора до смены версии либо значимые данные документа изменились. '
                    'Прежнее решение и значения сохранены; автоматическое восстановление не выполнено.')
    native_document_price = bool(document_evidence_intact and price and roles['price_raw_id'] == roles['documents_raw_id']
        and (price.get('amount_documents') or {}).get('state') == 'known'
        and (price.get('amount_source') or {}).get('kind') == 'contract_document'
        and price.get('amount') is not None)
    price_fresh = roles['price_raw_id'] is None or bool(price and
        document_evidence_intact and (price_token(price) == roles['price_token'] or originals_intact and native_document_price))
    result['role_freshness'] = {'execution': execution_fresh, 'price': price_fresh}
    result['current_price_token'] = price_token(price) if price else None
    result['current_execution_token'] = execution_token(execution) if execution is not None else None
    confirmed = safe_sources and execution_fresh and price_fresh and roles['documents_raw_id'] in rows
    return dict(result, status='confirmed' if confirmed else 'source_conflict',
                logical_id=canonical['raw_id'], reason='' if confirmed else result['reason'])


def materialize(register, row):
    """Ephemeral read view: physical trees stay once in the serialized register."""
    correction = row.get('source_correction')
    if not correction:
        return row
    import developaid_contract_ownership as ownership
    execution = ownership.find_raw_row(register, correction['roles']['execution_raw_id'])
    if not correction.get('role_freshness', {}).get('execution', correction.get('fresh', True)):
        raise store.IdentityProblem('Источник выполнения требует обновления; прежние показатели и исходные карточки сохранены.', 409)
    if execution is None:
        raise store.IdentityProblem('Выбранный источник выполнения отсутствует. Обновите реестр.', 409)
    return {**execution, **row, 'physical_items': execution.get('physical_items') or []}


def project_row(register, resolution):
    import developaid_contract_ownership as ownership
    import developaid_monitor_contracts as contracts
    import developaid_monitor_contract_risk as risk
    raw = {row['id']: row for row in ownership.raw_rows(register)}
    roles = resolution['roles']
    execution = raw.get(roles['execution_raw_id']) or {}
    price = raw.get(roles['price_raw_id'])
    documents = raw.get(roles['documents_raw_id']) or {}
    row = {key: value for key, value in execution.items() if key not in HEAVY_FIELDS}
    if not resolution['role_freshness']['execution']:
        row.update(resolution['selected_values']['execution'])
    row.update(resolution['canonical_identity'])
    if not row.get('subject'):
        names = [item.get('name') for item in execution.get('physical_items') or []
                 if item.get('name') and not item.get('is_duplicate') and not item.get('is_group')]
        row['subject'] = '; '.join(dict.fromkeys(names[:2]))[:180] or None
    row.update(id=resolution['logical_id'], logical_id=resolution['logical_id'],
               contract_identity_kind='owner_corrected_sources', raw_member_ids=resolution['member_ids'],
               source_correction={'decision_id': resolution['decision_id'], 'roles': roles,
                                  'recorded_at': resolution['decision_recorded_at'], 'fresh': resolution['status'] == 'confirmed',
                                  'warning': resolution.get('reason') or '', 'role_freshness': resolution['role_freshness'],
                                  'source_policy': SOURCE_POLICY},
               logical_ownership={'resolution_kind': 'source_correction', 'resolution_status': resolution['status'],
                                  'decision_id': resolution['decision_id'], 'financial_acceptance_required': False})
    for key in ('amount', 'amount_basis', 'amount_source', 'amount_source_label', 'amount_documents'):
        row[key] = (price.get(key) if price is not None else None) if resolution['role_freshness']['price'] else resolution['selected_values']['price'].get(key)
    row['amount_basis'] = row.get('amount_basis') or 'unspecified'
    row['document_source_ids'] = documents.get('document_source_ids') or []
    # Closing references identify expected acts; they are never execution money.
    references = list(execution.get('financial_sources') or [])
    if resolution['status'] == 'confirmed':
        seen = {store.digest(source) for source in references}
        for source in documents.get('financial_sources') or []:
            if str(source.get('label') or '').startswith('Сводная') and store.digest(source) not in seen:
                references.append(source)
                seen.add(store.digest(source))
    row['financial_sources'] = references
    for key in ('deadline', 'deadline_source', 'deadline_documents', 'manual_deadline_reference'):
        row[key] = documents.get(key)
    row['deadline_passed'] = bool(row.get('deadline') and row['deadline'] < register['cut'])
    same_operands = (row.get('amount'), row.get('amount_basis')) == (execution.get('amount'), execution.get('amount_basis'))
    comparable = (execution.get('monetary_comparable') is True if roles['price_raw_id'] == execution.get('id') else
                  row.get('amount_basis') == row.get('completed_basis') and row.get('amount_basis') in {'with_vat', 'without_vat'})
    comparable = comparable and resolution['role_freshness']['execution'] and resolution['role_freshness']['price']
    row['monetary_comparable'] = comparable
    amount, completed = row.get('amount'), row.get('completed')
    row['completion_ratio'] = completed / amount if comparable and amount is not None and amount > 0 and completed is not None else None
    row['remaining'] = amount - completed if comparable and amount is not None and completed is not None else None
    if not same_operands or not all(resolution['role_freshness'].values()):
        # Reuse native source qualification. Never divide unknown/incompatible bases.
        import developaid_monitor_contract_history as history
        view = {**row, 'physical_items': execution.get('physical_items') or []}
        row['progress'] = history._observation(view, register)
        row['progress']['series'] = []
        if row['completion_ratio'] is None:
            row['progress'] = dict(row['progress'], ratio=None, state='unknown',
                reason='Цена и выполнение сохранены из выбранных источников; основание общего процента не подтверждено.')
    dated, parts = [], {}
    contracts._cumulative_money(execution.get('physical_items') or [], [], parts, dated)
    row['risk'] = risk.forecast(amount=amount, completed=completed, comparable=comparable, periods=dated,
        cut=dt.date.fromisoformat(register['cut']), deadline=dt.date.fromisoformat(row['deadline']) if row.get('deadline') else None,
        works=row.get('completed_works') if row.get('works_materials_split') else None,
        materials=row.get('completed_materials') if row.get('works_materials_split') else None)
    # Payments/worklinks remain the execution source's own observations, not aliases.
    row.pop('schedule_control', None)
    if resolution['status'] != 'confirmed':
        row['warnings'] = list(row.get('warnings') or []) + [resolution['reason']]
    row['source_correction']['provenance'] = {
        'execution': {'raw_id': roles['execution_raw_id'], 'token': (resolution.get('current_execution_token') or roles['execution_token']) if resolution['role_freshness']['execution'] else roles['execution_token'],
                      'source_snapshot_id': execution.get('source_snapshot_id')},
        'price': {'raw_id': roles['price_raw_id'], 'token': (resolution.get('current_price_token') or roles['price_token']) if resolution['role_freshness']['price'] else roles['price_token'],
                  'source': (price.get('amount_source') or price.get('source') if price else None) if resolution['role_freshness']['price'] else resolution['selected_values']['price'].get('amount_source')},
        'documents': {'raw_id': roles['documents_raw_id']}}
    return row
