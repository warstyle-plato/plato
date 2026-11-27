"""Read-only logical ownership after the unchanged raw archive register.

Identity confirmation never chooses a financial edition or a raw binding.
Absent overlay returns the former register; every original raw card survives.
"""
from __future__ import annotations

import contextlib
import contextvars
import datetime as dt
import hashlib
import stat
from pathlib import Path

MAX_RELEVANT_PAIRS = 8
MAX_ARCHIVES = 32
MAX_VERIFIED_READ_BYTES = 128 * 1024 * 1024
_CONTEXT = contextvars.ContextVar('contract_ownership_read', default=None)
_RAW_HISTORY = contextvars.ContextVar('contract_ownership_raw_history', default=False)
GAP = 'financial_source_choice_required'
WHY = ('Владелец подтвердил принадлежность исходных карточек одному договору. '
       'Финансовый источник, срок и расчёт риска для единого договора не выбраны; '
       'данные каждой исходной карточки сохранены отдельно.')


class OwnershipProblem(ValueError):
    pass


def has_raw_views(register):
    return 'raw_rows' in register or 'raw_source_rows' in register


def raw_rows(register):
    if 'raw_source_rows' in register:
        indexed = {row['id']: row for row in register['raw_source_rows']}
        for row in register.get('rows') or []:
            if row.get('source_correction'):
                continue
            # A legacy parent already contains its original raw observations.
            # Reuse them once instead of treating the unknown parent as raw.
            for original in row.get('raw_observations') or [row]:
                indexed[original['id']] = original
        return [indexed[identifier] for identifier in register['raw_source_order'] if identifier in indexed]
    return register.get('raw_rows', register.get('rows') or [])


def raw_view(register):
    result = dict(register, rows=raw_rows(register))
    result.pop('raw_rows', None)
    result.pop('raw_source_rows', None)
    result.pop('raw_source_order', None)
    result.pop('logical_ownership', None)
    return result


def find_raw_row(register, identifier):
    selected = [row for row in raw_rows(register) if row.get('id') == identifier]
    return selected[0] if len(selected) == 1 else None


@contextlib.contextmanager
def raw_history():
    token = _RAW_HISTORY.set(True)
    try:
        yield
    finally:
        _RAW_HISTORY.reset(token)


def is_raw_history():
    return _RAW_HISTORY.get()


def require_unpinned_refresh(raw_id):
    """A late lazy reader upgrade cannot write through an existing pin."""
    context = _CONTEXT.get()
    if context is not None and context.pairs.get(raw_id) in context.binding_pins:
        raise OwnershipProblem('Исходные привязки изменились после проверки документов. Обновите реестр.')


class ReadContext:
    def __init__(self, project, cut):
        import developaid_contract_identity_store as store
        self.project, self.cut = project.strip(), cut
        self.root = store.project_root(self.project)
        self.state = store.load(self.project)
        self.head = self.state['head']
        self.present = bool(self.state['events'])
        self.cache, self.members, self.roster, self.binding_pins = {}, {}, None, {}
        self.header = None
        self.header_digest = None
        self.paths = {}
        self.pairs = {}
        self.corrections = {}
        self.source_cache = {}
        self.parse_refresh_budget = {'files': 0, 'bytes': 0, 'metadata_files': 0, 'metadata_bytes': 0}
        for event in self.state['events']:
            if event['action'] in {'confirm', 'correct_sources'}:
                pair = tuple(sorted({member['raw_id'] for member in event['payload']['members']}))
                if event['action'] == 'correct_sources':
                    self.corrections[pair] = event
                else:
                    self.corrections.pop(pair, None)
                for identifier in pair:
                    self.pairs[identifier] = pair
        self.active_events = {tuple(sorted({member['raw_id'] for member in event['payload']['members']})): event
                              for event in self.state['active']}
        self.active = set(self.active_events)

    def _roster(self):
        import developaid_monitor_ledgers as ledgers
        import developaid_monitor_contracts as contracts
        roster = []
        for item in ledgers.list_snapshots(self.project):
            day = contracts._date(item.get('taken_at'))
            if not day or item['taken_at'] > self.cut:
                continue
            sid = item.get('snapshot_id')
            if not isinstance(sid,str) or sid[:10] != item['taken_at']:
                raise OwnershipProblem('Дата сохранённого архива не совпала с его идентичностью.')
            roster.append(sid)
        return sorted(roster)

    def _binding_inventory(self, pair):
        """One aggregate metadata budget for initial, nested and final seals."""
        import developaid_contract_identity as identity
        found = identity.metadata_inventory(self.project, list(pair), correction=pair in self.corrections)
        self._charge_inventory(found)
        return found

    def _charge_inventory(self, found):
        import developaid_contract_identity as identity
        self.parse_refresh_budget['metadata_files'] += found['metadata_files_read']
        self.parse_refresh_budget['metadata_bytes'] += found['metadata_bytes_read']
        self.parse_refresh_budget['files'] += found.get('price_source_files_read', 0)
        self.parse_refresh_budget['bytes'] += found.get('price_source_bytes_read', 0)
        import developaid_contract_files as files
        if (self.parse_refresh_budget['metadata_files'] > identity.MAX_FILES or
                self.parse_refresh_budget['metadata_bytes'] > identity.MAX_METADATA_BYTES or
                self.parse_refresh_budget['files'] > files.MAX_PARSE_REFRESH_FILES or
                self.parse_refresh_budget['bytes'] > files.MAX_PARSE_REFRESH_BYTES):
            raise OwnershipProblem('Общий объём метаданных уточнений превышает предел одной сборки.')

    def capture(self, composition):
        if not self.present:
            return
        import developaid_monitor_contracts as contracts
        import developaid_contract_identity_store as store
        identifiers = {identifier for identifier, _ in contracts._groups(composition['primary'], self.project)}
        relevant = {self.pairs[identifier] for identifier in identifiers if identifier in self.pairs}
        if len(relevant) > MAX_RELEVANT_PAIRS:
            raise OwnershipProblem('Слишком много уточнений реквизитов для одной ограниченной сборки. Реестр не собран частично.')
        if is_raw_history() and relevant <= self.binding_pins.keys():
            # Raw history does not apply ownership or consume bindings. The
            # outer read already pinned these groups and freshly seals them
            # on exit; repeating that seal for every archive spends the
            # aggregate IO budget without proving an additional result.
            return
        active_passes = len(relevant & self.active)
        if relevant:
            import developaid_contract_identity as identity
            import developaid_contract_files as files
            # Reader upgrades write derived JSON. Finish only the bounded,
            # relevant upgrades before capturing a group's FIRST binding pin.
            # Already captured groups keep their strict CAS, including on a
            # nested capture; owner/source changes are never rebased away.
            if self.binding_pins:
                self.check()
            fresh = relevant-set(self.binding_pins)
            if fresh:
                approvals = {pair: event for pair, event in self.corrections.items()
                    if self.active_events.get(pair, {}).get('event_id') == event['event_id']
                    and self.active_events[pair]['action'] == 'correct_sources'}
                files.refresh_parse_cache(self.project, [(pair, pair in self.corrections) for pair in sorted(fresh)],
                                          self.parse_refresh_budget, approvals)
            # Raw-history enrichment can reach the parser before the main
            # operational capture. Its source inventory must be pinned too:
            # an owner edit during that first enrichment is concurrent drift.
            metadata_bytes = 0
            for pair in relevant:
                bindings = self._binding_inventory(pair)
                metadata_bytes += bindings['metadata_bytes_read']
                if metadata_bytes > identity.MAX_METADATA_BYTES:
                    raise OwnershipProblem('Общий объём метаданных уточнений превышает предел одной сборки.')
                observed = store.digest(bindings)
                if pair in self.binding_pins and self.binding_pins[pair] != observed:
                    raise OwnershipProblem('Исходные привязки изменились во время чтения. Обновите реестр.')
                self.binding_pins[pair] = observed
                self.source_cache.setdefault(('bindings', pair), bindings)
        if is_raw_history():
            return  # Do not fold or adopt a historical archive composition.
        if active_passes:
            self.roster = self._roster()
            if len(self.roster) > MAX_ARCHIVES or len(set(self.roster)) != len(self.roster):
                raise OwnershipProblem('Состав архивов превышает предел проверки уточнений. Частичное объединение не выполнено.')
            total = 0
            for sid in self.roster:
                if not isinstance(sid, str) or len(sid) != 75 or store.day(sid[:10]) != sid[:10] or not store.HASH.fullmatch(sid[11:]):
                    raise OwnershipProblem('Идентичность сохранённого архива не подтверждена.')
                path = self.root/'cumulative'/(sid+'.zip')
                try:
                    info = path.lstat()
                except OSError:
                    raise OwnershipProblem('Сохранённый архив недоступен для проверки уточнения.') from None
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 20*1024*1024:
                    raise OwnershipProblem('Исходный архив не подходит для ограниченной проверки уточнения.')
                total += info.st_size
                self.paths[sid] = path
            strict_passes = len((relevant & self.active) - set(self.corrections))
            if (2*strict_passes+3)*total > MAX_VERIFIED_READ_BYTES:
                raise OwnershipProblem('Объём повторной проверки источников превышает предел одной сборки. Частичное объединение не выполнено.')
            self.header = store.read_bytes(self.root/'cumulative_header_dates.json', 4*1024*1024)
            self.header_digest = store.digest(self.header.hex() if self.header is not None else None)
        for identifier, items in contracts._groups(composition['primary'], self.project):
            if identifier not in self.pairs or self.pairs[identifier] not in relevant:
                continue
            snapshots = {item.get('archive_snapshot_id') for item in items}
            if self.pairs[identifier] in self.corrections:
                self.members[identifier] = {'raw_id': identifier, 'source_snapshots': sorted(snapshots)}
                continue
            if len(snapshots) != 1:
                # Incremental KS history may legitimately use several source
                # archives. A former one-snapshot identity decision does not
                # authorize this new composition: retain the raw cards and
                # expose a source conflict, rather than hiding the register.
                self.members[identifier] = {'raw_id': identifier,
                    'history_snapshots': sorted(str(sid or '') for sid in snapshots)}
                continue
            sid = next(iter(snapshots))
            archive = composition['by_snapshot'].get(sid) or {}
            files = {}
            for file in archive.get('files') or []:
                files.setdefault(file.get('filename'), []).append(file.get('sha256'))
            refs = []
            for item in items:
                source = item.get('source') or {}
                candidates = files.get(source.get('filename'), [])
                file_sha = item.get('file_sha256') or (candidates[0] if len(candidates) == 1 else None)
                refs.append({'file_sha256':file_sha, 'source_locator_sha256':store.digest(source), 'kind':item.get('kind')})
            self.members[identifier] = {'raw_id':identifier, 'snapshot_id':sid,
                'identity':{key:items[0].get(key) for key in ('customer','contractor','contract','contract_date')},
                'sources':sorted(refs,key=store.digest)}

    def resolve(self, pair, register=None):
        if pair in self.cache:
            return self.cache[pair]
        import developaid_contract_identity as identity
        import developaid_contract_identity_store as store
        observed = [identifier for identifier in pair
                    if identifier in self.members and self.pairs.get(identifier) == pair]
        if not observed:
            return None
        if pair in self.corrections:
            import developaid_contract_correction as correction
            event = self.corrections[pair]
            resolved = correction.resolve(self.project, event, self.cut, register=register,
                cache=self.source_cache, active=self.active_events.get(pair, {}).get('event_id') == event['event_id']
                and self.active_events[pair]['action'] == 'correct_sources')
            self.cache[pair] = resolved
            return resolved
        if any(self.members[identifier].get('history_snapshots') for identifier in observed):
            resolved = {'status': 'source_conflict', 'logical_id': None,
                'member_ids': list(pair),
                'reason': 'История КС содержит несколько исходных архивов. Прежнее уточнение реквизитов не подтверждает новый состав; исходные карточки сохранены отдельно.'}
            self.cache[pair] = resolved
            return resolved
        try:
            resolved = identity.resolve(self.project, observed[0], self.cut)
        except identity.IdentityProblem:
            resolved = {'status':'source_conflict', 'logical_id':None,
                        'member_ids':list(pair), 'reason':'Сохранённые версии уточнения не подтверждены.'}
        bindings = resolved.get('bindings')
        if bindings is not None:
            # resolve already performed a fresh native inventory. Charge and
            # compare that exact proof instead of reading the group twice.
            self._charge_inventory(bindings)
        if sorted(resolved.get('member_ids') or []) != list(pair):
            resolved = {'status':'source_conflict', 'logical_id':None,
                        'member_ids':list(pair), 'reason':'Состав уточнения не совпал с исходными карточками.'}
        if resolved.get('status') == 'confirmed':
            versions = resolved.get('source_versions') or []
            for identifier in observed:
                expected = self.members[identifier]
                matched = [member for member in versions if member['raw_id'] == identifier
                           and member['snapshot_id'] == expected['snapshot_id']
                           and member['identity'] == expected['identity'] and member['sources'] == expected['sources']]
                if len(matched) != 1:
                    resolved = dict(resolved,status='source_conflict',logical_id=None,
                                    reason='Используемая исходная версия не совпала с подтверждённым уточнением.')
                    break
            if self.binding_pins[pair] != store.digest(bindings):
                raise OwnershipProblem('Исходные привязки изменились во время сборки. Обновите реестр.')
        self.cache[pair] = resolved
        return resolved

    def pin(self):
        import developaid_contract_identity_store as store
        return {'cut':self.cut, 'journal_head':self.head,
                'namespace_sha256':store.digest(str(self.root)),
                'archives':self.roster, 'header_sha256':self.header_digest,
                'bindings':[{'member_ids':list(pair),'sha256':digest}
                            for pair,digest in sorted(self.binding_pins.items())]}

    def adopt(self, register):
        """A later raw enrichment must still belong to the original read."""
        import developaid_contract_identity_store as store
        pin = register['logical_ownership']['read_guard']
        if any(pin.get(key) != self.pin().get(key)
               for key in ('cut','journal_head','namespace_sha256')):
            raise OwnershipProblem('Состав проекта или уточнения изменились после сборки. Обновите реестр.')
        if self.roster is None and pin.get('archives') is not None:
            roster = pin['archives']
            if not isinstance(roster,list) or len(roster) > MAX_ARCHIVES or len(set(roster)) != len(roster):
                raise OwnershipProblem('Состав проверенных источников неоднозначен. Обновите реестр.')
            self.roster, self.header_digest = roster, pin.get('header_sha256')
            total = 0
            for sid in roster:
                if not isinstance(sid,str) or len(sid) != 75 or store.day(sid[:10]) != sid[:10] or not store.HASH.fullmatch(sid[11:]):
                    raise OwnershipProblem('Идентичность проверенного архива не подтверждена.')
                path = self.root/'cumulative'/(sid+'.zip')
                try:
                    info = path.lstat()
                except OSError:
                    raise OwnershipProblem('Сохранённый архив недоступен для проверки уточнения.') from None
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 20*1024*1024:
                    raise OwnershipProblem('Исходный архив не подходит для ограниченной проверки уточнения.')
                total += info.st_size
                self.paths[sid] = path
            if total > MAX_VERIFIED_READ_BYTES:
                raise OwnershipProblem('Объём повторной проверки источников превышает предел одной сборки.')
        elif self.roster != pin.get('archives') or self.header_digest != pin.get('header_sha256'):
            raise OwnershipProblem('Источники изменились после сборки. Обновите реестр.')
        for item in pin.get('bindings') or []:
            pair = tuple(item['member_ids'])
            if pair in self.binding_pins and self.binding_pins[pair] != item['sha256']:
                raise OwnershipProblem('Исходные привязки изменились после сборки. Обновите реестр.')
            self.binding_pins[pair] = item['sha256']

    def require_current(self, register):
        if has_raw_views(register):
            self.adopt(register)
        elif any(row.get('id') in self.pairs for row in raw_rows(register)):
            raise OwnershipProblem('Уточнения появились после сборки исходных карточек. Обновите реестр.')

    def check(self):
        import developaid_contract_identity_store as store
        if store.project_root(self.project) != self.root or store.load(self.project)['head'] != self.head:
            raise OwnershipProblem('Уточнения реквизитов изменились во время чтения. Обновите реестр.')
        store.assert_namespace(self.project)
        if self.roster is not None:
            header = store.read_bytes(self.root/'cumulative_header_dates.json',4*1024*1024)
            if self._roster() != self.roster or store.digest(header.hex() if header is not None else None) != self.header_digest:
                raise OwnershipProblem('Источники или подтверждения шапок изменились во время чтения. Обновите реестр.')
            for sid, path in self.paths.items():
                raw = store.read_bytes(path,20*1024*1024)
                if raw is None or hashlib.sha256(raw).hexdigest() != sid[11:]:
                    raise OwnershipProblem('Исходная версия изменилась во время чтения; логическое объединение не подтверждено.')
        if self.binding_pins:
            import developaid_contract_identity as identity
            if any(store.digest(self._binding_inventory(pair)) != digest
                   for pair,digest in self.binding_pins.items()):
                raise OwnershipProblem('Исходные привязки изменились во время чтения. Обновите реестр.')


@contextlib.contextmanager
def read_scope(project, cut):
    current = _CONTEXT.get()
    if current is not None:
        if project.strip() != current.project:
            raise OwnershipProblem('Сборка уточнения относится к другому проекту.')
        if cut != current.cut and not is_raw_history():
            raise OwnershipProblem('Сборка уточнения относится к другому срезу.')
        yield current
        return
    import developaid_monitor as monitor
    import developaid_contract_identity_store as store
    namespace = store.namespace(project) if Path(monitor._SNAPSHOT_DIR).is_dir() else contextlib.nullcontext()
    try:
        with namespace:
            context = ReadContext(project,cut)
            token = _CONTEXT.set(context)
            try:
                yield context
                context.check()
            finally:
                _CONTEXT.reset(token)
    except (store.IdentityProblem, OSError):
        raise OwnershipProblem('Состояние уточнений или источников не подтверждено. Обновите реестр.') from None


def capture(composition):
    context = _CONTEXT.get()
    if context is not None:
        context.capture(composition)


def unknown_row(raw, identifier, *, resolution, members, cut):
    import developaid_monitor_contract_risk as risk
    from developaid_monitor_contracts import _reference_key
    reason = WHY if resolution.get('status') == 'confirmed' else 'Принадлежность исходных карточек одному договору сейчас не подтверждена. Данные источников показаны отдельно; финансовый итог не выбран.'
    anchor = next((row for row in raw if row['id'] == identifier),raw[0])
    row = {key:anchor.get(key) for key in ('contractor','customer','contract_date')}
    row['subject'] = None
    row.update(id=identifier,contract=resolution.get('canonical_number') if resolution.get('status') == 'confirmed' else anchor.get('contract'),
        source_kind='logical_ownership',contract_identity_kind='owner_confirmed_logical' if resolution.get('status') == 'confirmed' else 'ownership_unknown',
        logical_id=resolution.get('logical_id'),raw_observations=raw,raw_member_ids=members,
        logical_ownership=dict(resolution_status=resolution.get('status'),decision_id=resolution.get('decision_id'),
            decision_recorded_at=resolution.get('decision_recorded_at'),binding_resolution=resolution.get('binding_resolution'),
            binding_conflicts=resolution.get('binding_conflicts') or [],financial_acceptance=False,gap=GAP),
        amount=None,completed=None,remaining=None,completion_ratio=None,completed_works=None,completed_materials=None,
        amount_basis='unspecified',completed_basis='unspecified',monetary_comparable=False,works_materials_split=False,
        amount_source_label=reason,works_materials_note=reason,deadline=None,deadline_source=None,manual_deadline_reference=None,
        deadline_passed=False,source={'label':'Исходные карточки показаны отдельно.'},source_date=None,source_snapshot_id=None,
        sources=[],financial_sources=[],reported_performance_sources=[],physical_items=[],scope=[],
        date_evidence=[],date_confirmations=[],identity_source={},requires_reconciliation=True,warnings=[reason],
        performance_basis=reason,performance_source_count=0,rss_match={'status':'not_combined','text':reason,'candidates':[]},
        progress={'state':'unknown','ratio':None,'reason':reason,'series':[]},
        observation_forecast={'state':'unknown','eligible':False,'forecast_finish':None,'reason':reason},
        schedule_control={'state':'unknown','documents':None,'finish':None,'deadline':None,'note':reason})
    row['risk'] = risk.forecast(amount=None,completed=None,comparable=False,periods=[],cut=dt.date.fromisoformat(cut),deadline=None)
    row['risk']['reason'] = reason
    row['advance'] = risk.advance(row,None,reference_key=_reference_key,completed_basis='unspecified')
    row['advance']['reason'] = reason
    return row


def fold(register, states):
    import developaid_monitor_contract_risk as risk
    originals = raw_rows(register)
    if any(state.get('resolution_kind') == 'source_correction' for state in states.values()):
        return fold_corrections(register, states)
    result = dict(register,raw_rows=originals)
    done, rows = set(), []
    unresolved = 0
    for row in originals:
        identifier = row['id']
        resolved = states.get(identifier)
        if resolved is None:
            rows.append(row)
            continue
        pair = tuple(resolved['member_ids'])
        if resolved.get('status') == 'confirmed':
            if pair in done:
                continue
            done.add(pair)
            observed = [item for item in originals if item['id'] in pair]
            # A future raw card is never manufactured at an earlier cut.
            if len(observed) == 1:
                rows.append(row)
            else:
                rows.append(unknown_row(observed,resolved['logical_id'],resolution=resolved,members=list(pair),cut=register['cut']))
        else:
            unresolved += 1
            rows.append(unknown_row([row],identifier,resolution=resolved,members=list(pair),cut=register['cut']))
    result['rows'] = rows
    result['logical_ownership'] = {'states':states,'financial_acceptance':False,
        'unresolved_source_cards':unresolved,'raw_source_cards':len(originals),
        'logical_contracts':None if unresolved else len(rows)}
    if register.get('logical_ownership',{}).get('read_guard'):
        result['logical_ownership']['read_guard'] = register['logical_ownership']['read_guard']
    result['risk_summary'] = risk.summary(rows)
    result['counts'] = dict(register.get('counts') or {},raw_source_cards=len(originals),
                            logical_contracts=None if unresolved else len(rows))
    return result


def apply(register, context):
    if not context.present or not context.members:
        return register
    states = {}
    for pair in sorted({context.pairs[identifier] for identifier in context.members}):
        resolved = context.resolve(pair, register)
        if resolved:
            for identifier in pair:
                if identifier in context.members and context.pairs.get(identifier) == pair:
                    states[identifier] = resolved
    if not states:
        return register
    result = fold(register,states)
    result['logical_ownership']['read_guard'] = context.pin()
    for row in result['rows']:
        if row.get('source_correction'):
            row['source_correction']['read_guard'] = store_guard(context.pin())
            row['source_correction']['input_guard'] = context.pin()
    return result


def refresh(register, enriched_raw):
    if not has_raw_views(register):
        return enriched_raw
    context = _CONTEXT.get()
    if context is None:
        raise OwnershipProblem('Обогащение исходных карточек требует единого проверенного чтения.')
    context.adopt(register)
    result = dict(register)
    result.update({key:value for key,value in enriched_raw.items() if key != 'rows'})
    result.pop('raw_source_rows', None)
    result.pop('raw_source_order', None)
    result['raw_rows'] = enriched_raw.get('rows') or []
    refreshed = fold(result,register['logical_ownership']['states'])
    for row in refreshed['rows']:
        if row.get('source_correction'):
            row['source_correction']['read_guard'] = store_guard(context.pin())
            row['source_correction']['input_guard'] = context.pin()
    return refreshed


def store_guard(pin):
    import developaid_contract_identity_store as store
    return store.digest(pin)


def fold_corrections(register, states):
    """Each heavy raw source appears once in transport, never in each parent."""
    import developaid_contract_correction as correction
    import developaid_monitor_contract_risk as risk
    originals = raw_rows(register)
    result = dict(register)
    result.pop('raw_rows', None)
    result.pop('raw_source_rows', None)
    result.pop('raw_source_order', None)
    rows, pool, done = [], [], set()
    legacy_unresolved = 0
    for row in originals:
        state = states.get(row['id']) or {}
        if state and state.get('resolution_kind') != 'source_correction':
            # Preserve the existing strict-confirm fold verbatim beside new
            # source-role groups, including its own financial/binding gaps.
            group = tuple(state['member_ids'])
            if state.get('status') == 'confirmed':
                if group in done:
                    continue
                done.add(group)
                observed = [original for original in originals if original['id'] in group]
                rows.append(row if len(observed) == 1 else unknown_row(observed, state['logical_id'],
                    resolution=state, members=list(group), cut=register['cut']))
            else:
                legacy_unresolved += 1
                rows.append(unknown_row([row], row['id'], resolution=state, members=list(group), cut=register['cut']))
            continue
        applies = state.get('resolution_kind') == 'source_correction' and state.get('membership_confirmed')
        if not applies:
            rows.append(row)
            continue
        group = tuple(state['member_ids'])
        pool.append(row)
        if group not in done:
            done.add(group)
            rows.append(correction.project_row(register, state))
    result['rows'] = rows
    result['raw_source_rows'] = pool
    result['raw_source_order'] = [row['id'] for row in originals]
    result['logical_ownership'] = {'states': states, 'financial_acceptance_required': False,
        'raw_source_cards': len(originals), 'logical_contracts': None if legacy_unresolved else len(rows),
        'unresolved_source_cards': legacy_unresolved + len({state['decision_id'] for state in states.values() if state.get('resolution_kind') == 'source_correction' and state.get('status') == 'source_conflict'}),
        'historical_corrections': sorted({state['applies_from'] for state in states.values() if state.get('status') == 'historical_raw'})}
    if register.get('logical_ownership', {}).get('read_guard'):
        result['logical_ownership']['read_guard'] = register['logical_ownership']['read_guard']
    result['risk_summary'] = risk.summary(rows)
    result['counts'] = dict(register.get('counts') or {}, raw_source_cards=len(originals), logical_contracts=None if legacy_unresolved else len(rows),
        contracts_from_cumulative=sum(row.get('source_kind') == 'cumulative' for row in rows),
        contracts_from_closing_summary_only=sum(row.get('source_kind') == 'closing_summary' for row in rows))
    if 'contracts_from_documents' in result['counts']:
        result['counts']['contracts_from_documents'] = len(rows)
    if register.get('progress_summary'):
        result['progress_summary'] = dict(register['progress_summary'],
            known=sum((row.get('progress') or {}).get('ratio') is not None for row in rows),
            unknown=sum((row.get('progress') or {}).get('ratio') is None for row in rows),
            comparable=sum((row.get('progress') or {}).get('comparison_state') == 'comparable' for row in rows))
    return result
