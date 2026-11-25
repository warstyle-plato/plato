"""Initial contract cards from owner-confirmed PDF evidence, without financial facts.

The preview is stateless. Commit rechecks the original and publishes its source
record last, under a project lock. Existing native IDs and card files are never
renamed when a later cumulative archive supplies the same legal identity.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import fcntl
import hashlib
import os
from pathlib import Path
import re
import stat

import developaid_contract_documents as documents
import developaid_contract_identity_store as namespace
import developaid_monitor_contracts as contracts

SCHEMA = 'contract-pdf-intake-v1'
REGISTRY = 'contract_pdf_sources.json'
MAX_SOURCES = 128
MAX_REGISTRY_BYTES = 2 * 1024 * 1024
MAX_SOURCE_BYTES = 64 * 1024 * 1024
NO_FACT = 'К договору загружен исходный PDF. Накопительная КС-6а не предоставлена; выполнение по ней не рассчитано.'
HASH = re.compile(r'[0-9a-f]{64}\Z')
ROLES = {'customer': {'заказчик', 'генеральный подрядчик', 'генподрядчик',
                      'генеральный подрядчик/генподрядчик'}, 'contractor': {'подрядчик'}}


class IntakeProblem(contracts.ContractProblem):
    def __init__(self, message, status=409):
        self.status = status
        super().__init__(message)


def _need(condition, message, status=409):
    if not condition:
        raise IntakeProblem(message, status)


def _root(project, *, existing=False):
    root = namespace.project_root(project)
    if existing:
        _need(root.is_dir() and any(p.is_dir() and not p.is_symlink() and
              any(not x.name.startswith('.') for x in p.iterdir())
              for p in root.iterdir() if not p.name.startswith('.')),
              'Выберите существующий проект Монитора с сохранёнными исходниками.', 404)
    return root


def _path(root, *parts):
    path = root
    for part in parts:
        path = path / part
        _need(not path.is_symlink(), 'Ссылка вместо исходника договора; проверка остановлена.', 503)
    return path


def _read_state(project):
    root = _root(project)
    raw = namespace.read_bytes(_path(root, REGISTRY), MAX_REGISTRY_BYTES)
    if raw is None:
        return {'schema': SCHEMA, 'project_scope': namespace.project_scope(project), 'revision': 0, 'sources': []}
    state = namespace.strict_json(raw)
    _need(isinstance(state, dict) and set(state) == {'schema', 'project_scope', 'revision', 'sources'}
          and state['schema'] == SCHEMA and state['project_scope'] == namespace.project_scope(project)
          and type(state['revision']) is int and isinstance(state['sources'], list)
          and state['revision'] == len(state['sources']) <= MAX_SOURCES,
          'Реестр PDF-источников не подтверждён.', 503)
    seen, total = set(), 0
    for source in state['sources']:
        _need(isinstance(source, dict) and set(source) == {'contract_id', 'evidence', 'actor', 'recorded_at',
              'preview_token', 'expected_revision', 'source_sha256', 'filename', 'bytes'},
              'Запись PDF-источника не подтверждена.', 503)
        evidence = source['evidence']
        _need(isinstance(evidence, dict) and evidence.get('schema') == SCHEMA
              and evidence.get('project_scope') == state['project_scope']
              and evidence.get('edition') == 'contract' and isinstance(evidence.get('identity'), dict)
              and HASH.fullmatch(str(source['source_sha256'])) and HASH.fullmatch(str(source['actor']))
              and type(source['bytes']) is int and 0 < source['bytes'] <= documents_limit()
              and source['source_sha256'] == evidence.get('source_sha256')
              and source['contract_id'] == _id(project, evidence['identity'])
              and source['preview_token'] == _token(evidence, source['expected_revision'])
              and source['source_sha256'] not in seen,
              'Происхождение PDF-источника не подтверждено.', 503)
        seen.add(source['source_sha256'])
        total += source['bytes']
    _need(total <= MAX_SOURCE_BYTES, 'Превышен общий размер PDF-источников.', 413)
    return state


def documents_limit():
    return 20 * 1024 * 1024


def _id(project, identity):
    _need(set(identity) == {'customer', 'contractor', 'contract', 'contract_date'}
          and all(isinstance(v, str) and v.strip() for v in identity.values())
          and namespace.day(identity['contract_date']), 'Реквизиты договора не подтверждены.', 400)
    return contracts._groups([identity], project)[0][0]


def _token(evidence, revision):
    return namespace.digest({'evidence': evidence, 'expected_revision': revision})


def _quote(proof, texts):
    _need(isinstance(proof, dict) and set(proof) == {'name', 'designation', 'page', 'quote'}
          and type(proof['page']) is int and 1 <= proof['page'] <= len(texts)
          and all(isinstance(proof[k], str) and 0 < len(proof[k]) <= (2000 if k == 'quote' else 300)
                  for k in ('name', 'designation', 'quote')), 'Укажите сторону, её роль, страницу и цитату из PDF.', 400)
    quote = documents._space(proof['quote'])
    # Legal-name and role quotation boundaries are evidence, not decoration.
    # Normalize whitespace and case only, then retain the actual source slice.
    source = documents._space(texts[proof['page']-1])
    found = re.search(re.escape(quote), source, re.I)
    _need(found is not None, 'Цитата стороны не найдена на указанной странице исходного PDF.', 400)
    _need(not re.search(r'\b(?:не|ни)\s*$', source[:found.start()], re.I),
          'Цитата не должна отсекать отрицание роли стороны в исходном PDF.', 400)
    return found[0]


def _quoted_parties(quote):
    """Complete expressly quoted legal names, including nested Russian quotes."""
    forms = {full for full, _ in contracts._LEGAL_FORMS} | {short for _, short in contracts._LEGAL_FORMS}
    pattern = r'(?<![а-я])(' + '|'.join(re.escape(form) for form in sorted(forms, key=len, reverse=True)) + r')\s*([«“"])'
    found = set()
    for match in re.finditer(pattern, quote, re.I):
        opening = match[2]
        closing = {'«': '»', '“': '”', '"': '"'}[opening]
        depth, end = 1, match.end()
        while end < len(quote):
            if quote[end] == closing:
                depth -= 1
                if not depth:
                    found.add(contracts._party_norm(match[1]+' '+quote[match.end():end]))
                    break
            elif opening != closing and quote[end] == opening:
                depth += 1
            end += 1
    return found


def _role_assertion(quote, designation, named):
    role = re.escape(designation)
    quoted_role = r'(?:«'+role+r'»|“'+role+r'”|"'+role+r'")'
    clause = re.search(r'\bименуем(?:ое|ый|ая|ые|ым|ой|ыми)\s+(?:в\s+дальнейшем\s+)?'
                       + quoted_role + r'(?![\w/\-‐‑‒–—―])', quote, re.I)
    if clause:
        prefix = quote[:clause.start()]
        # A negative or alternative assertion cannot establish a party's role.
        if re.search(r'\b(?:не|ни)\b', re.split(r'[.;!?]', prefix)[-1], re.I):
            return False
        return named in contracts._party_norm(prefix)
    labelled = re.match(r'(?:'+quoted_role+'|'+role+r')\s*:\s*', quote, re.I)
    return bool(labelled and named in contracts._party_norm(quote[labelled.end():]))


def _evidence(project, content, source_sha256, contract_number, contract_date, customer, contractor):
    _need(isinstance(content, bytes) and 0 < len(content) <= documents_limit() and content.startswith(b'%PDF'),
          'Выберите непустой PDF размером не больше 20 МБ.', 413)
    sha = hashlib.sha256(content).hexdigest()
    _need(sha == source_sha256, 'SHA исходного PDF не совпал с подтверждаемым источником.', 409)
    _need(namespace.day(contract_date) is not None, 'Дата договора не подтверждена.', 400)
    import pymupdf
    try:
        pdf = pymupdf.open(stream=content, filetype='pdf')
    except (RuntimeError, ValueError):
        raise IntakeProblem('Исходный файл не прочитан как PDF.', 400) from None
    with pdf:
        _need(0 < pdf.page_count <= documents.MAX_PAGES, 'Превышен предел страниц PDF.', 413)
        texts = [page.get_text() for page in pdf]
    try:
        found = documents.identity(texts[0])
    except documents.ContractHeaderAmbiguity as exc:
        raise IntakeProblem(str(exc), 400) from None
    _need(found.get('contract') and not found.get('agreement')
          and not all(pattern.search(texts[0]) for pattern in documents._ACT_FORM),
          'Начальная карточка создаётся только по основному договору, не по соглашению или акту.', 400)
    header = found['contract']
    _need(contracts._contract_number(header['number'], reference=True) ==
          contracts._contract_number(contract_number, reference=True) and header['date'] == contract_date,
          'Номер или дата не совпали с основным договором в тексте PDF.', 409)
    proofs = {'customer': customer, 'contractor': contractor}
    checked = {}
    for role, proof in proofs.items():
        quote = _quote(proof, texts)
        designation = contracts._norm(proof['designation'])
        _need(designation in ROLES[role], 'Указанная роль стороны не поддерживается для этого поля.', 400)
        # A self-contained clause must name this party and explicitly call it
        # by the chosen role. A whole page containing both parties is not proof.
        named = contracts._party_norm(proof['name'])
        normalized = contracts._party_norm(quote)
        quoted = _quoted_parties(quote)
        _need(named in quoted,
              'Цитата должна содержать полное наименование выбранной стороны с правовой формой.', 400)
        _need(quoted == {named}, 'Для каждой стороны нужна отдельная цитата с её собственной ролью.', 400)
        _need(named and _role_assertion(quote, designation, named),
              'Цитата не подтверждает выбранную сторону в указанной роли.', 400)
        other = proofs['contractor' if role == 'customer' else 'customer']
        _need(contracts._party_norm(other.get('name')) not in normalized,
              'Для каждой стороны нужна отдельная цитата с её собственной ролью.', 400)
        checked[role] = {**proof, 'quote': quote}
    _need(contracts._party_norm(customer['name']) != contracts._party_norm(contractor['name']),
          'Стороны договора должны различаться.', 400)
    identity = {'customer': customer['name'].strip(), 'contractor': contractor['name'].strip(),
                'contract': header['number'], 'contract_date': header['date']}
    return {'schema': SCHEMA, 'project_scope': namespace.project_scope(project), 'source_sha256': sha,
            'edition': 'contract', 'identity': identity, 'parties': checked,
            'header': {'page': 1, **header}}


@contextlib.contextmanager
def _locked(project):
    with namespace.namespace(project):
        root = _root(project, existing=True)
        descriptor = os.open(root/'.contract_pdf_intake.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, 'a+b') as handle:
            info = os.fstat(handle.fileno())
            _need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, 'Блокировка приёма PDF недоступна.', 503)
            fcntl.flock(handle, fcntl.LOCK_EX)
            yield


def preview(project, content, *, source_sha256, contract_number, contract_date, customer, contractor):
    with namespace.namespace(project):
        _root(project, existing=True)
        evidence = _evidence(project, content, source_sha256, contract_number, contract_date, customer, contractor)
        state = _read_state(project)
        return {'contract_id': _id(project, evidence['identity']), 'revision': state['revision'],
                'preview_token': _token(evidence, state['revision']), 'evidence': evidence,
                'financial_acceptance': False}


def _verify_native_source(project, source, content, *, allow_missing=False):
    """Caller holds the native card lock; cached metadata cannot prove its own origin."""
    import developaid_contract_files as files
    folder = _path(_root(project), 'contract_documents', source['contract_id'])
    sha = source['source_sha256']
    persisted = namespace.read_bytes(_path(folder, sha+'.pdf'), documents_limit())
    _need((persisted is None and allow_missing) or
          (persisted == content and hashlib.sha256(persisted).hexdigest() == sha),
          'Сохранённый оригинал PDF не совпал с проверенным источником; карточка не опубликована.', 503)
    metadata = namespace.read_bytes(_path(folder, sha+'.json'), 16 * 1024 * 1024)
    _need(metadata is not None or allow_missing,
          'Сохранённый разбор PDF недоступен; карточка не опубликована.', 503)
    if metadata is not None:
        record = namespace.strict_json(metadata)
        _need(isinstance(record, dict), 'Сохранённый разбор PDF не подтверждён.', 503)
        if persisted is not None:
            record = files._current(folder, sha)
        expected = files._record(sha, record.get('filename', ''), content, record.get('uploaded_at', ''))
        operational = {'filename', 'uploaded_at', 'removed_at'}
        _need(namespace.canonical({key: value for key, value in record.items() if key not in operational}) ==
              namespace.canonical({key: value for key, value in expected.items() if key not in operational}),
              'Сохранённый разбор PDF не совпал с разбором проверенного источника; карточка не опубликована.', 503)
    return persisted is None, metadata is None


def commit(project, content, *, filename, expected_revision, preview_token, actor, **claims):
    import developaid_contract_files as files
    with _locked(project):
        evidence = _evidence(project, content, **claims)
        _need(type(expected_revision) is int and expected_revision >= 0 and
              preview_token == _token(evidence, expected_revision),
              'Проверка относится к другому PDF, проекту, редакции или составу сторон.', 409)
        _need(isinstance(actor, str) and HASH.fullmatch(actor), 'Автор подтверждения не установлен.', 403)
        state = _read_state(project)
        for source in state['sources']:
            if source['source_sha256'] == evidence['source_sha256']:
                _need(source['evidence'] == evidence, 'Этот PDF уже принят с другими реквизитами.', 409)
                sources(project, evidence['identity']['contract_date'])
                folder = _path(_root(project), 'contract_documents', source['contract_id'])
                with files._locked(folder):
                    _verify_native_source(project, source, content)
                return {'contract_id': source['contract_id'], 'revision': state['revision'],
                        'already': True, 'source_sha256': source['source_sha256'], 'financial_acceptance': False}
        _need(expected_revision == state['revision'], 'Реестр PDF уже изменился. Повторите предварительную проверку.', 409)
        _need(len(state['sources']) < MAX_SOURCES and sum(s['bytes'] for s in state['sources']) + len(content)
              <= MAX_SOURCE_BYTES, 'Достигнут предел приёма PDF-источников.', 413)
        identifier = _id(project, evidence['identity'])
        # A second original edition is a normal card upload, never a second
        # initial identity assertion under a different spelling or PDF hash.
        _need(not any(contracts._identity(s['evidence']['identity']) == contracts._identity(evidence['identity'])
                      for s in state['sources']), 'Договор уже создан. Загрузите файл в существующую карточку.', 409)
        register = contracts.build(project, dt.date.today().isoformat(), include_history=False)
        _need(not any(contracts._identity(row) == contracts._identity(evidence['identity'])
                      for row in contracts.raw_rows(register)),
              'Договор уже есть в реестре. Загрузите PDF в существующую карточку.', 409)
        # No visibility before both the native PDF and its parsed record exist.
        folder = _path(_root(project), 'contract_documents', identifier)
        _path(folder, '.lock')
        _path(folder, evidence['source_sha256']+'.pdf')
        _path(folder, evidence['source_sha256']+'.json')
        namespace.assert_namespace(project)
        source = {'contract_id': identifier, 'evidence': evidence, 'source_sha256': evidence['source_sha256'],
                  'filename': Path(str(filename)).name[:240] or 'договор.pdf', 'bytes': len(content),
                  'recorded_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'actor': actor,
                  'preview_token': preview_token, 'expected_revision': expected_revision}
        updated = {**state, 'revision': state['revision']+1, 'sources': [*state['sources'], source]}
        packed = namespace.canonical(updated)
        _need(len(packed) <= MAX_REGISTRY_BYTES, 'Достигнут предел реестра происхождения PDF.', 413)
        with files._locked(folder):
            if (folder/(evidence['source_sha256']+'.pdf')).exists() or (folder/(evidence['source_sha256']+'.json')).exists():
                missing_pdf, missing_json = _verify_native_source(project, source, content, allow_missing=True)
                # Only this unpublished branch may finish an interrupted pair.
                # Existing components and position choices are never replaced.
                if missing_pdf:
                    files._write(folder/(source['source_sha256']+'.pdf'), content)
                if missing_json:
                    files._json(folder/(source['source_sha256']+'.json'),
                                files._record(source['source_sha256'], source['filename'], content, files._now()))
            else:
                files.store(project, {'id': identifier, **evidence['identity']}, filename, content)
            _verify_native_source(project, source, content)
            namespace.assert_namespace(project)
            files._write(_path(_root(project), REGISTRY), packed)
        return {'contract_id': identifier, 'revision': updated['revision'], 'already': False,
                'source_sha256': evidence['source_sha256'], 'financial_acceptance': False}


def sources(project, cut):
    """Bounded, verified native originals; never enumerate caller paths."""
    if not _path(_root(project), REGISTRY).exists():
        return []
    with namespace.namespace(project):
        state = _read_state(project)
        out = []
        for source in state['sources']:
            if source['evidence']['identity']['contract_date'] > cut:
                continue
            path = _path(_root(project), 'contract_documents', source['contract_id'], source['source_sha256']+'.pdf')
            parsed = _path(_root(project), 'contract_documents', source['contract_id'], source['source_sha256']+'.json')
            raw = namespace.read_bytes(path, documents_limit())
            _need(raw is not None and len(raw) == source['bytes'] and hashlib.sha256(raw).hexdigest()
                  == source['source_sha256'] and parsed.is_file(),
                  'Оригинал PDF-источника или его сохранённый разбор недоступен либо изменился.', 503)
            out.append(source)
        return out


def attach(project, cut, register):
    """Document provenance supplements an exact legal identity; no money is inferred."""
    retained = sources(project, cut)
    if not retained:
        return register
    rows = register['rows']
    added = 0
    for source in retained:
        identity = source['evidence']['identity']
        matches = [row for row in rows if contracts._identity(row) == contracts._identity(identity)]
        _need(len(matches) <= 1, 'PDF подходит нескольким исходным карточкам; принадлежность требует уточнения.', 409)
        if matches:
            row = matches[0]
        else:
            row = {'id': source['contract_id'], **identity, 'source_kind': 'contract_document',
                   'source_date': identity['contract_date'], 'source_snapshot_id': None,
                   'contract_identity_kind': 'confirmed_pdf', 'subject': '', 'physical_items': [],
                   'financial_sources': [], 'sources': [], 'scope': [], 'warnings': [NO_FACT],
                   'amount': None, 'completed': None, 'completion_ratio': None, 'remaining': None,
                   'completed_works': None, 'completed_materials': None, 'monetary_comparable': False,
                   'works_materials_split': False, 'deadline': None, 'deadline_source': {},
                   'amount_source_label': 'Цена не включена: карточка создана только для хранения документов.',
                   'amount_basis': '', 'completed_basis': '', 'requires_reconciliation': False,
                   'performance_basis': NO_FACT, 'risk': {'status': 'unknown', 'note': NO_FACT},
                   'advance': {'paid': None, 'unworked': None, 'note': NO_FACT},
                   'source': {'filename': source['filename'], 'page': 1, 'label': 'Основной договор PDF'},
                   'statement_progress': {'state': 'unknown', 'ratio': None, 'why': NO_FACT}}
            rows.append(row)
            added += 1
        row.setdefault('document_source_ids', []).append(source['contract_id'])
        row.setdefault('document_provenance', []).append(source)
    if added:
        register['empty_reason'] = ''
        register['scope_note'] += ' Договоры без КС показаны по подтверждённым исходным PDF; выполнение неизвестно.'
    register['counts']['contracts_from_pdf'] = added
    if added:
        import developaid_monitor_contract_risk as risk
        register['risk_summary'] = risk.summary(rows)
    return register
