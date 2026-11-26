"""Manual, source-bound intake from Yandex Disk; folder names are hints only.

Scan -> download/native preflight -> explicit apply. No cron, remote writes,
source removal, signature confirmation, or filename-based financial identity.
"""
from __future__ import annotations
import datetime as dt
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import zipfile
import developaid_contract_identity_store as ns

SCHEMA = 'contract-disk-intake-v5'
API = 'https://cloud-api.yandex.net/v1/disk/public/resources'
ROLES = {'Юрист', 'Сметчик'}
KINDS = {'Договор', 'Дополнительные соглашения', 'РДС', 'ГПР', 'КС-2', 'КС-6а', 'Акты передачи площадки'}
LEGAL_DOCUMENTS = 'Документы договора'
COMMON = 'Сводная по закрытию'
MAX_FILE, MAX_BATCH, MAX_JSON = 20*1024*1024, 50*1024*1024, 2*1024*1024
HASH = re.compile(r'[0-9a-f]{64}\Z')

class DiskSourceProblem(ValueError):
    pass

def need(ok, text):
    if not ok:
        raise DiskSourceProblem(text)

def source_url(value):
    need(isinstance(value, str) and len(value) <= 512, 'Укажите публичную ссылку на папку Яндекс.Диска.')
    url = urllib.parse.urlsplit(value.strip())
    need(url.scheme == 'https' and url.netloc == 'disk.yandex.ru' and re.fullmatch(r'/d/[A-Za-z0-9_-]{5,160}/?', url.path)
         and not url.query and not url.fragment, 'Нужна ссылка https://disk.yandex.ru/d/… без параметров и пароля.')
    return 'https://disk.yandex.ru'+url.path.rstrip('/')

def label(value):
    return ' '.join(unicodedata.normalize('NFC', str(value or '')).split())

def contract_folder(number):
    return label(number).replace('/', '_')

def location(path):
    parts = list(PurePosixPath(path).parts)
    if parts and parts[0] == '/':
        parts.pop(0)
    if len(parts) == 3 and parts[:2] == ['Общие по проекту', COMMON]:
        return {'role': parts[0], 'party': '', 'contract': '', 'kind': COMMON, 'layout': 'current'}
    if not parts or parts[0] not in ROLES:
        return None
    if (parts[0] == 'Юрист' and (len(parts) == 4 or len(parts) == 5 and parts[3] == 'Приложения')
            and parts[1].strip() and parts[2].strip()):
        return dict(role=parts[0], party=parts[1], contract=parts[2], kind=LEGAL_DOCUMENTS, layout='current')
    if len(parts) != 5:
        return None
    role, party, contract, kind, _ = parts
    layout = 'current' if role == 'Сметчик' and kind in {'КС-2', 'КС-6'} else 'legacy'
    if party in KINDS | {'КС-6'}:
        role, kind, party, contract, _ = parts
        layout = 'legacy'
    kind = 'КС-6а' if kind == 'КС-6' else kind
    if kind not in KINDS or not party.strip() or not contract.strip():
        return None
    return dict(role=role, party=party, contract=contract, kind=kind, layout=layout)


def location_purpose(loc):
    """Role directs the workflow; it never proves the document's content."""
    if loc.get('kind') == COMMON and loc.get('role') == 'Общие по проекту':
        return 'summary_book'
    if loc.get('role') == 'Юрист' and loc.get('kind') not in {'КС-2', 'КС-6а'}:
        return 'legal_pdf'
    if loc.get('role') == 'Сметчик':
        return {'КС-2': 'ks2_pdf', 'КС-6а': 'ks6_book'}.get(loc.get('kind'), '')
    return ''


def pdf_document_types(record):
    """Only actual native reader results supply semantic document types."""
    if record.get('act'):
        return ['КС-2']
    types = []
    if record.get('agreement'):
        types.append('Дополнительное соглашение')
    if record.get('estimates'):
        types.append('РДС')
    if record.get('schedule'):
        types.append('ГПР')
    return types or ['Документ договора']


def pdf_role_reason(entry, record):
    purposes = {location_purpose(loc) for loc in entry.get('locations') or []}
    wanted = 'ks2_pdf' if record.get('act') else 'legal_pdf'
    if purposes != {wanted}:
        return ('По содержимому это акт КС-2: он должен находиться в Сметчик / Контрагент / Договор / КС-2.'
                if wanted == 'ks2_pdf' else
                'По содержимому это документ договора или приложение, а не акт КС-2. Такие PDF должны находиться в Юрист / Контрагент / Договор.')
    return ''

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None

class Client:
    """Public API; admin/session/auth headers never enter this transport."""
    def __init__(self):
        self.opener = urllib.request.build_opener(NoRedirect())
        self.deadline, self.calls = time.monotonic()+150, 0

    def read(self, url, limit, *, download=False):
        for redirects in range(4):
            self.calls += 1
            need(self.calls <= 400 and time.monotonic() < self.deadline, 'Папка слишком велика для одной проверки.')
            p = urllib.parse.urlsplit(url)
            # The public download API redirects to this exact storage host;
            # no wildcard storage/Yandex origins or API redirects are admitted.
            allowed = (p.netloc in {'downloader.disk.yandex.ru', 'mds.storage.yandex.net'} or re.fullmatch(r'[a-z0-9-]+\.(?:[a-z0-9-]+\.)?disk\.yandex\.net', p.netloc)) if download else p.netloc == 'cloud-api.yandex.net'
            need(p.scheme == 'https' and allowed and not p.username and not p.password, 'Диск вернул неподдерживаемый адрес файла.')
            request = urllib.request.Request(url, headers={'Accept': 'application/octet-stream' if download else 'application/json', 'User-Agent': 'DevelopAid-Manual-Source-Intake/1'})
            try:
                response = self.opener.open(request, timeout=min(20, max(1, self.deadline-time.monotonic())))
            except urllib.error.HTTPError as exc:
                if download and exc.code in {301,302,303,307,308} and redirects < 3:
                    url = urllib.parse.urljoin(url, exc.headers.get('Location', ''))
                    continue
                raise DiskSourceProblem('Диск не отдал папку или файл. Проверьте доступность ссылки.') from None
            except (OSError, ValueError):
                raise DiskSourceProblem('Не удалось прочитать Диск. Принятые источники Монитора сохранены.') from None
            with response:
                size = response.headers.get('Content-Length')
                need(not size or size.isdigit() and int(size) <= limit, 'Файл превышает допустимый размер.')
                raw = response.read(limit+1)
            need(len(raw) <= limit, 'Файл превышает допустимый размер.')
            return raw
        raise DiskSourceProblem('Слишком много перенаправлений при получении файла.')

    def metadata(self, url, path='/', offset=0):
        q = urllib.parse.urlencode(dict(public_key=source_url(url), path=path, limit=100, offset=offset))
        try:
            result = json.loads(self.read(API+'?'+q, MAX_JSON))
        except (ValueError, UnicodeError):
            raise DiskSourceProblem('Каталог Яндекс.Диска не прочитан.') from None
        need(isinstance(result, dict), 'Диск вернул неподдерживаемый каталог.')
        return result

    def download(self, url, path, sha, size):
        need(HASH.fullmatch(sha) and type(size) is int and 0 < size <= MAX_FILE, 'Размер или контрольная сумма файла не подтверждены.')
        q = urllib.parse.urlencode(dict(public_key=source_url(url), path=path))
        try:
            result = json.loads(self.read(API+'/download?'+q, 64*1024))
        except (ValueError, UnicodeError):
            raise DiskSourceProblem('Диск не вернул адрес исходного файла.') from None
        need(isinstance(result, dict) and isinstance(result.get('href'), str), 'Адрес исходника отсутствует.')
        raw = self.read(result['href'], MAX_FILE, download=True)
        need(len(raw) == size and hashlib.sha256(raw).hexdigest() == sha, 'Файл изменился после проверки каталога. Проверьте Диск заново.')
        return raw

def catalog(client, url, *, coverage=None):
    coverage = {} if coverage is None else coverage
    coverage.update(allowed_roots=sorted(ROLES | {'Общие по проекту'}), scanned_roots=[], not_scanned_roots=[])
    found, queue, seen = [], ['/'], set()
    while queue:
        path, offset = queue.pop(0), 0
        while True:
            value = client.metadata(url, path, offset)
            need(value.get('type') == 'dir', 'Ссылка должна вести на папку проекта.')
            embedded = value.get('_embedded') or {}
            items, total = embedded.get('items'), embedded.get('total')
            need(isinstance(items, list) and type(total) is int and 0 <= total <= 2000, 'Состав папки не подтверждён.')
            for item in items:
                need(isinstance(item, dict), 'Состав папки не подтверждён.')
                name = item.get('name')
                need(isinstance(name, str) and name not in {'.','..'} and not any(c in name for c in '/\\\x00') and len(name) <= 240, 'В каталоге недопустимое имя.')
                child = path.rstrip('/')+'/'+name
                need(child not in seen, 'Каталог изменился во время чтения. Повторите проверку.')
                seen.add(child)
                if path == '/':
                    if name not in ROLES | {'Общие по проекту'}:
                        coverage['not_scanned_roots'].append(name)
                        continue
                    if item.get('type')=='dir':
                        coverage['scanned_roots'].append(name)
                if item.get('type') == 'dir':
                    need(len(PurePosixPath(child).parts) <= 6, 'Вложенность слишком велика. Используйте Роль / Контрагент / Договор / Тип.')
                    queue.append(child)
                elif item.get('type') == 'file':
                    need(len(found) < 500, 'В папке слишком много файлов для одной проверки.')
                    found.append(dict(path=child, filename=name, sha256=item.get('sha256'), bytes=item.get('size'), modified=item.get('modified')))
                else:
                    raise DiskSourceProblem('Тип элемента каталога не подтверждён.')
            offset += len(items)
            if offset >= total:
                break
            need(bool(items), 'Диск вернул неполную страницу каталога.')
    coverage['scanned_roots'].sort()
    coverage['not_scanned_roots'].sort()
    coverage['scanned_files']=len(found)
    coverage['not_scanned_file_count']=None
    return found

def folder(project):
    ns.assert_namespace(project)
    root = ns.project_root(project)
    need(root.is_dir(), 'Выберите существующий проект Монитора.')
    path = root/'.contract_disk_sources'
    need(not path.is_symlink(), 'Хранилище исходников Диска требует проверки.')
    path.mkdir(mode=0o700, exist_ok=True)
    for name in ('catalogs','stages','bytes'):
        child = path/name
        need(not child.is_symlink(), 'Хранилище исходников Диска требует проверки.')
        child.mkdir(mode=0o700, exist_ok=True)
    return path

def load(path):
    raw = ns.read_bytes(path, MAX_JSON)
    need(raw is not None, 'Сохранённая проверка не найдена. Проверьте каталог заново.')
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError):
        raise DiskSourceProblem('Сохранённая проверка не прочитана.') from None
    need(isinstance(value, dict), 'Сохранённая проверка не подтверждена.')
    return value

def save(path, value, *, raw=False):
    need(not path.is_symlink(), 'Ссылка вместо сохранённого источника; операция остановлена.')
    data = value if raw else ns.canonical(value)
    if raw:
        need(len(data) <= MAX_FILE, 'Подготовленный исходник превышает допустимый размер.')
        existing = list(path.parent.glob('*.bin'))
        need(len(existing) <= 512 and sum(item.lstat().st_size for item in existing) + (0 if path.exists() else len(data)) <= 256*1024*1024,
             'Хранилище подготовленных исходников заполнено. Принятые источники сохранены; обратитесь к администратору.')
    else:
        need(len(data) <= MAX_JSON, 'Проверка содержит слишком много данных.')
        if path.parent.name in {'catalogs','stages'} and not path.exists():
            need(len(list(path.parent.glob('*.json'))) < 128,
                 'Достигнут предел сохранённых проверок. Принятые источники сохранены; обратитесь к администратору.')
    fd, temporary = tempfile.mkstemp(prefix='.disk-', dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'wb') as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)

def rows(project, cut):
    import developaid_monitor_contracts as contracts
    register = contracts.build(project, cut, include_history=False)
    selected = {}
    # Until the adapter uses the native operational admission, an active role
    # selection cannot be bypassed by addressing one of its original raw rows.
    for event in ns.load(project)['active']:
        if event.get('action') != 'correct_sources':
            continue
        payload = event.get('payload') or {}
        frame = {'event_id': event['event_id'], 'roles': payload.get('roles'),
                 'members': payload.get('members')}
        for member in payload.get('members') or []:
            selected[member['raw_id']] = frame
    return [{**row, '_disk_source_correction': selected[row['id']]} if row['id'] in selected else row
            for row in contracts.raw_rows(register)]

def row_guard(row):
    return ns.digest({key: row.get(key) for key in ('id','contractor','customer','contract','contract_date','document_source_ids','source_correction','logical_contract_id','_disk_source_correction','_disk_operational','_disk_native_owner','_disk_execution_owner','_disk_review_reason')})

def party_folder(value):
    import developaid_monitor_contracts as contracts
    words = contracts._party_norm(value).split()
    forms = {short for _, short in contracts._LEGAL_FORMS}
    return ' '.join(words[1:] if words and words[0] in forms else words)

def match_rows(loc, candidates):
    import developaid_monitor_contracts as contracts
    # Folder aliases are hints only. Multiple legal identities remain ambiguous;
    # preflight later checks the exact legal form and requisites inside the file.
    return [row for row in candidates if party_folder(row.get('contractor')) == party_folder(loc['party'])
            and contract_folder(contracts._contract_number(row.get('contract'))).upper() == label(loc['contract']).upper()]


def native_hashes(project):
    """Retained file metadata only; never warms old PDF readers or restores removals."""
    import developaid_monitor_ledgers as ledgers
    result = {'project': project, 'documents': {}, 'ks6': {}, 'origins': {}}
    docs = ns.project_root(project)/'contract_documents'
    budget, count = 0, 0
    if docs.exists():
        need(not docs.is_symlink(), 'Хранилище документов требует проверки.')
        for card in docs.iterdir():
            if not HASH.fullmatch(card.name):
                continue
            need(card.is_dir() and not card.is_symlink(), 'Хранилище документов требует проверки.')
            count += 1
            need(count <= 500, 'Слишком много карточек для одной проверки источников.')
            hashes = set()
            for path in card.glob('*.pdf'):
                need(HASH.fullmatch(path.stem) and not path.is_symlink(), 'Исходник документа требует проверки.')
                need(len(hashes) < 500, 'Слишком много исходников в одной карточке.')
                if (card/(path.stem+'.json')).is_file():
                    hashes.add(path.stem)
            result['documents'][card.name] = hashes
    snapshots = ledgers.list_snapshots(project, include_removed=True)
    need(len(snapshots) <= 128, 'Слишком много снимков для одной проверки источников.')
    for snapshot in snapshots:
        path = ledgers._root(project)/(snapshot['snapshot_id']+'.json')
        raw = ns.read_bytes(path, ledgers.MAX_PARSED_BYTES)
        need(raw is not None, 'Сохранённый архив не прочитан.')
        budget += len(raw)
        need(budget <= 64*1024*1024, 'История исходников слишком велика для одной проверки.')
        parsed = json.loads(raw)
        scopes = {}
        for ledger in parsed.get('ledgers') or []:
            scopes.setdefault(ledger.get('file_sha256'), set()).add(legal_identity(ledger))
        for summary in parsed.get('summary_contracts') or []:
            scopes.setdefault(summary.get('file_sha256'), set()).add('project')
        for source in parsed.get('files') or []:
            sha = source.get('sha256')
            if isinstance(sha, str) and HASH.fullmatch(sha):
                result['ks6'].setdefault(sha, set()).update(scopes.get(sha, set()))
                result['origins'].setdefault(sha, []).append((snapshot['snapshot_id'], source['filename']))
    return result

def native_owner(row, *, execution=False):
    return (row.get('_disk_execution_owner' if execution else '_disk_native_owner') or row) if row else row


def native_family(project, row):
    import developaid_contract_files as files
    return files.source_family(project, native_owner(row))


def capture_source_guard(project, row, *, pdf):
    import developaid_monitor_ledgers as ledgers
    with ns.locked(project):
        if pdf:
            import developaid_contract_files as files
            import developaid_contract_identity as identity
            row = native_owner(row)
            family = files.source_family(project, row)
            with identity._binding_locks(project, family, correction=True):
                return files.source_preservation_guard(project, row)
        root = ledgers._root(project, create=True)
        with ledgers._lock(root):
            return {'archive_revision': ledgers.snapshot_inventory(project)['revision']}


def legal_identity(row):
    import developaid_monitor_contracts as contracts
    return ns.digest(dict(customer=contracts._party_norm(row.get('customer')),
                          party=contracts._party_norm(row.get('contractor')),
                          contract=contracts._contract_number(row.get('contract')),
                          contract_date=row.get('contract_date')))

def known(entry, hashes):
    sha, project = entry['sha256'], hashes['project']
    if entry['family'] == 'pdf':
        family = entry.get('source_family') or [entry.get('contract_id')]
        owner = next((member for member in family if sha in hashes['documents'].get(member, set())), None)
        if owner is None:
            return False
        card = ns.project_root(project)/'contract_documents'/owner
        raw = ns.read_bytes(card/(sha+'.pdf'), MAX_FILE)
        record = ns.read_bytes(card/(sha+'.json'), 16*1024*1024)
        need(raw and hashlib.sha256(raw).hexdigest() == sha and record and json.loads(record).get('sha256') == sha,
             'Сохранённый PDF не совпал с его отпечатком. Проверьте исходник карточки.')
        if pdf_role_reason(entry, json.loads(record)):
            return False
        return True
    if entry['identity'] not in hashes['ks6'].get(sha, set()):
        return False
    import developaid_monitor_ledgers as ledgers
    for snapshot_id, filename in hashes['origins'].get(sha, []):
        original = ns.read_bytes(ledgers._root(project)/(snapshot_id+'.zip'), MAX_FILE)
        need(original and hashlib.sha256(original).hexdigest() == snapshot_id[11:],
             'Сохранённый архив не совпал с отпечатком. Проверьте исходник снимка.')
        for member, raw in ledgers._zip_members(original):
            if member == filename and hashlib.sha256(raw).hexdigest() == sha:
                return True
    raise DiskSourceProblem('Сохранённая ведомость не найдена в исходном архиве.')


def scope_notice(scope):
    scanned = ', '.join(scope.get('scanned_roots') or []) or 'не найдены'
    text = 'Проверены только найденные разделы: '+scanned+'.'
    omitted = scope.get('not_scanned_roots') or []
    if omitted:
        text += ' Не просмотрены: '+', '.join(omitted)+'. Содержимое этих разделов, включая прежние папки ГПР, не проверялось; число файлов в них неизвестно.'
    return text


def scan(project, source, cut, *, client=None, row_provider=None):
    source = source_url(source)
    coverage = {}
    candidates, files = (row_provider or rows)(project, cut), catalog(client or Client(), source,coverage=coverage)
    hashes = native_hashes(project)
    with ns.locked(project):
        root = folder(project)
        previous = load(root/'latest.json') if (root/'latest.json').exists() else {}
        old = {x['path']: x['sha256'] for x in previous.get('locations') or [] if previous.get('source') == source}
        grouped, issues = {}, []
        for item in files:
            loc = location(item['path'])
            reason = ('Нужен путь Юрист / Контрагент / Договор / Файл либо Сметчик / Контрагент / Договор / КС-2 или КС-6 / Файл.' if not loc else
                      'Контрольная сумма или допустимый размер файла не подтверждены.' if not isinstance(item['sha256'], str) or not HASH.fullmatch(item['sha256']) or type(item['bytes']) is not int or not 0 < item['bytes'] <= MAX_FILE else '')
            if reason:
                issues.append({**item, 'status': 'review', 'reason': reason})
                continue
            purpose = location_purpose(loc)
            if not purpose:
                issues.append({**item, 'status':'review', 'reason':
                    'Договор, допники, РДС, ГПР и приложения хранятся у Юриста; КС-2 и КС-6 — только у Сметчика. Файл не принят из папки другого назначения.'})
                continue
            common = loc['kind'] == COMMON
            matches = [] if common else match_rows(loc, candidates)
            suffix = PurePosixPath(item['filename']).suffix.lower()
            family = ('ks6' if purpose in {'ks6_book','summary_book'} and suffix in {'.xls','.xlsx','.xlsm'} else
                      'pdf' if purpose in {'legal_pdf','ks2_pdf'} and suffix == '.pdf' else '')
            row = matches[0] if len(matches) == 1 else None
            scope = 'project' if common else row['id'] if row else ns.digest(dict(party=loc['party'], contract=loc['contract']))
            identifier = ns.digest(dict(scope=scope, sha256=item['sha256']))
            entry = grouped.setdefault(identifier, dict(id=identifier, sha256=item['sha256'], bytes=item['bytes'], filename=item['filename'], family=family,
                locations=[], kinds=[], status='new', contract_id=row and row['id'], row_guard=row and row_guard(row), scope=scope, source_family=native_family(project,row) if row else [], identity='project' if common else legal_identity(native_owner(row,execution=True)) if row else None, native_context=row.get('_disk_operational') if row else None))
            entry['locations'].append({**loc, 'path':item['path']})
            if loc['kind'] not in entry['kinds']:
                entry['kinds'].append(loc['kind'])
            if not family:
                entry.update(status='review', reason='Excel-приложение сохранено на Диске, но его приём как РДС или ГПР пока не поддерживается. Это не КС-6; нужен отдельный поддерживаемый разбор.' if purpose=='legal_pdf' and suffix in {'.xls','.xlsx','.xlsm'} else
                    'Для договора, допников, приложений и КС-2 нужен PDF; для КС-6 и общей сводной — XLS, XLSX либо XLSM.')
            elif not common and row is None:
                entry.update(status='review', reason='Договор не найден однозначно. Сверьте реквизиты или сначала создайте карточку через приём исходного PDF.')
            elif family == 'ks6' and entry['sha256'] in hashes['ks6'] and not known(entry, hashes):
                entry.update(status='review', reason='Этот исходник уже сохранён с другой или неподтверждённой принадлежностью. Сверьте реквизиты.')
            elif row and row.get('_disk_review_reason'):
                entry.update(status='review', reason=row['_disk_review_reason'])
            elif row and row.get('_disk_source_correction'):
                entry.update(status='review', reason='Для договора подтверждён выбор источников. Обновление требует штатного операционного допуска из карточки договора; автоматическая привязка к исходной карточке запрещена.')
            elif known(entry, hashes):
                entry['status'] = 'already'
            elif old.get(item['path']) and old[item['path']] != item['sha256']:
                entry['status'] = 'changed'
        entries, by_sha = list(grouped.values()), {}
        for entry in entries:
            by_sha.setdefault(entry['sha256'], set()).add(entry['scope'])
        for entry in entries:
            if len(by_sha[entry['sha256']]) > 1:
                entry.update(status='review', reason='Одинаковый файл лежит у разных договоров. Принадлежность нужно сверить.')
        body = dict(schema=SCHEMA, project_scope=ns.project_scope(project), source=source, cut=cut, scope=coverage, entries=entries, issues=issues)
        revision = ns.digest(body)
        save(root/'catalogs'/(revision+'.json'), body)
        save(root/'latest.json', dict(source=source, revision=revision, locations=files))
        return dict(revision=revision, scope=coverage, scope_notice=scope_notice(coverage), checked_at=dt.datetime.now(dt.timezone.utc).isoformat(), entries=entries, issues=issues,
                    missing_previous_files=[p for p in old if p not in {x['path'] for x in files}],
                    notice='Проверка каталога не меняет Монитор. Исчезнувшие файлы не удаляются из принятых источников.')

def archive_bytes(files):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_STORED) as archive:
        for index, (name, raw) in enumerate(files):
            info = zipfile.ZipInfo(str(index+1)+'/'+PurePosixPath(name).name, (1980,1,1,0,0,0))
            archive.writestr(info, raw)
    need(stream.tell() <= MAX_FILE, 'Совокупный ZIP превышает20МБ. Выберите меньше ведомостей.')
    return stream.getvalue()

def check_ks6(entry, raw, row):
    import developaid_monitor_ledgers as ledgers
    import developaid_monitor_contracts as contracts
    parsed = ledgers.parse_archive(archive_bytes([(entry['filename'],raw)]), 'Проверка.zip')
    common = COMMON in entry['kinds']
    if common:
        need(bool(parsed.get('summary_contracts')) and not parsed.get('ledgers'), 'В общей папке нужна сводная по закрытию, без ведомостей отдельных договоров.')
    else:
        need(row and ns.day(row.get('contract_date')), 'Дата договора не подтверждена в карточке. Уточните реквизиты перед приёмом с Диска.')
        need(bool(parsed.get('ledgers')) and not parsed.get('summary_contracts'), 'Книга должна содержать КС-6а одного договора. Сводную положите в общую папку проекта.')
        for ledger in parsed['ledgers']:
            need(contracts._party_norm(ledger.get('contractor')) == contracts._party_norm(row.get('contractor')) and
                 contracts._contract_number(ledger.get('contract')) == contracts._contract_number(row.get('contract')) and
                 bool(ledger.get('customer')) and contracts._party_norm(ledger.get('customer')) == contracts._party_norm(row.get('customer')) and
                 ledger.get('contract_date') == row.get('contract_date'),
                 'Реквизиты внутри КС-6а не совпадают с договором. Имя папки не подтверждает принадлежность файла.')
    return dict(kind='ks6', files=parsed['files'], ledgers=len(parsed['ledgers']), summary_contracts=len(parsed['summary_contracts']))

def pdf_party_proofs(raw, row):
    """Reuse native explicit party/role clauses; folder hints are not evidence."""
    import pymupdf
    import developaid_contract_pdf_intake as intake
    import developaid_monitor_contracts as contracts
    forms = {full for full, _ in contracts._LEGAL_FORMS} | {short for _, short in contracts._LEGAL_FORMS}
    starts = re.compile(r'(?<![а-я])(?:'+'|'.join(re.escape(x) for x in sorted(forms,key=len,reverse=True))+r')\s*[«“"]',re.I)
    proofs = {}
    with pymupdf.open(stream=raw,filetype='pdf') as document:
        texts = [page.get_text() for page in document]
    for role in ('customer','contractor'):
        named = contracts._party_norm(row.get(role))
        need(bool(named), 'В карточке не подтверждён состав сторон. Уточните реквизиты перед приёмом с Диска.')
        for page,text in enumerate(texts,1):
            text = ' '.join(text.split())
            matches = list(starts.finditer(text))
            for index, match in enumerate(matches):
                end = matches[index+1].start() if index+1 < len(matches) else len(text)
                # A single expressly quoted legal identity, never a whole-page
                # co-occurrence of two names used as evidence of their roles.
                chunk = text[match.start():end].strip()[:2000]
                if intake._quoted_parties(chunk) != {named}:
                    continue
                for designation in sorted(intake.ROLES[role]):
                    if intake._role_assertion(chunk,designation,named):
                        proof = dict(name=row[role],designation=designation,page=page,quote=chunk)
                        try:
                            intake._quote(proof,texts)
                        except intake.IntakeProblem:
                            continue
                        proofs[role] = proof
                        break
                if role in proofs:
                    break
            if role in proofs:
                break
        need(role in proofs, 'Роль и полное наименование стороны не подтверждены цитатой PDF. Откройте штатный приём документа договора.')
    return proofs

def check_pdf(entry, raw, row):
    import developaid_contract_files as files
    need(row and ns.day(row.get('contract_date')), 'Дата договора не подтверждена в карточке. Уточните реквизиты перед приёмом с Диска.')
    record = files._record(entry['sha256'], entry['filename'], raw, dt.datetime.now(dt.timezone.utc).isoformat())
    need(not record.get('scan'), 'PDF требует подтверждения реквизитов. Откройте штатный приём документа договора.')
    reason = pdf_role_reason(entry, record)
    need(not reason, reason)
    source_contract = record.get('contract')
    # Manual card upload permits ancillary documents without their own header.
    # Automated folder intake cannot use that exception to assign a source:
    # both requisites must have been parsed from these exact PDF bytes.
    need(isinstance(source_contract, dict)
         and isinstance(source_contract.get('number'), str)
         and bool(source_contract['number'].strip())
         and len(source_contract['number']) <= 80
         and ns.day(source_contract.get('date')) is not None,
         'В PDF не подтверждены номер и дата договора. Имя папки и совпадение сторон не заменяют реквизиты исходника.')
    reason = files._same_contract(source_contract, row)
    need(not reason, reason or 'Принадлежность PDF не подтверждена.')
    parties = pdf_party_proofs(raw,row)
    return dict(kind='pdf', document_types=pdf_document_types(record), semantic_basis='native_pdf_content',
                title=record.get('title'), contract=record.get('contract'), parties=parties,
                notice='Тип документа прочитан из PDF. Сохранение не подтверждает подпись, ГПР или финансовый факт.')

def stage(project, revision, item_ids, *, client=None, row_provider=None):
    need(isinstance(revision, str) and HASH.fullmatch(revision), 'Номер проверки каталога неверен.')
    need(isinstance(item_ids,list) and 1 <= len(item_ids) <= 20 and len(set(item_ids)) == len(item_ids), 'Выберите от1 до20 разных файлов.')
    root = folder(project)
    view = load(root/'catalogs'/(revision+'.json'))
    need(view.get('schema') == SCHEMA, 'Проверка выполнена прежней версией. Проверьте каталог заново.')
    need(view.get('project_scope') == ns.project_scope(project) and ns.digest(view) == revision, 'Проверка каталога не подтверждена для этого проекта.')
    entries = {x['id']:x for x in view['entries']}
    need(all(x in entries and entries[x]['status'] in {'new','changed'} for x in item_ids), 'Выбраны отсутствующие или требующие сверки источники.')
    need(sum(entries[x]['bytes'] for x in item_ids) <= MAX_BATCH, 'Одна проверка принимает не больше50МБ исходников.')
    native = {row['id']:row for row in (row_provider or rows)(project,view['cut'])}
    checked, client = [], client or Client()
    for item_id in item_ids:
        entry = dict(entries[item_id])
        row = native.get(entry.get('contract_id'))
        if COMMON not in entry['kinds']:
            need(row and row_guard(row) == entry['row_guard'], 'Реквизиты договора изменились. Проверьте каталог заново.')
        path = root/'bytes'/(entry['sha256']+'.bin')
        raw = ns.read_bytes(path,MAX_FILE) if path.exists() else None
        if raw is None:
            raw = client.download(view['source'],entry['locations'][0]['path'],entry['sha256'],entry['bytes'])
        need(len(raw) == entry['bytes'] and hashlib.sha256(raw).hexdigest() == entry['sha256'], 'Исходник не совпал с проверенным файлом.')
        try:
            if entry['family'] == 'pdf':
                need(entry.get('source_family') == native_family(project,row), 'Состав исходных карточек изменился. Проверьте каталог заново.')
            before = capture_source_guard(project,row,pdf=entry['family']=='pdf')
            proof = check_pdf(entry,raw,native_owner(row)) if entry['family'] == 'pdf' else check_ks6(entry,raw,native_owner(row,execution=True))
            after = capture_source_guard(project,row,pdf=entry['family']=='pdf')
            need(before == after, 'Источники изменились во время разбора. Повторите проверку.')
            entry.update(status='ready',proof=proof,source_policy=after)
        except ValueError as exc:
            entry.update(status='review',reason=str(exc))
        with ns.locked(project):
            if not path.exists():
                save(path,raw,raw=True)
        checked.append(entry)
    body = dict(schema=SCHEMA,project_scope=view['project_scope'],cut=view['cut'],scope=view['scope'],catalog_revision=revision,entries=checked)
    token = ns.digest(body)
    with ns.locked(project):
        save(root/'stages'/(token+'.json'),body)
    return dict(stage_token=token,scope=view['scope'],scope_notice=scope_notice(view['scope']),entries=checked,notice='Исходники проверены и сохранены отдельно. Для обновления Монитора выберите применение.')

def apply(project,stage_token,*,taken_at='',row_provider=None,document_commit=None,book_commit=None):
    need(isinstance(stage_token,str) and HASH.fullmatch(stage_token), 'Номер проверки файлов неверен.')
    import developaid_contract_files as files
    import developaid_monitor_ledgers as ledgers
    with ns.locked(project):
        root = folder(project)
        staged = load(root/'stages'/(stage_token+'.json'))
        need(staged.get('schema') == SCHEMA, 'Проверка выполнена прежней версией. Проверьте исходники заново.')
        need(staged.get('project_scope') == ns.project_scope(project) and ns.digest(staged) == stage_token, 'Проверка исходников не подтверждена для этого проекта.')
        ready = [x for x in staged['entries'] if x['status'] == 'ready']
        need(bool(ready), 'Нет проверенных файлов для применения.')
        current = {row['id']:row for row in (row_provider or rows)(project,staged['cut'])}
        hashes, pending, outcomes = native_hashes(project), [], []
        for entry in ready:
            row = current.get(entry.get('contract_id'))
            need(COMMON in entry['kinds'] or row and row_guard(row) == entry['row_guard'], 'Реквизиты договора изменились. Повторите проверку перед применением.')
            raw = ns.read_bytes(root/'bytes'/(entry['sha256']+'.bin'),MAX_FILE)
            need(raw and len(raw) == entry['bytes'] and hashlib.sha256(raw).hexdigest() == entry['sha256'], 'Проверенный оригинал отсутствует или изменился.')
            if entry['family']=='pdf':
                need(entry.get('source_family') == native_family(project,row), 'Состав исходных карточек изменился. Проверьте каталог заново.')
            if known(entry,hashes):
                outcomes.append(dict(id=entry['id'],status='already',sha256=entry['sha256']))
                continue
            # Validate the entire batch before the first native business write.
            if entry['family'] == 'pdf':
                check_pdf(entry,raw,native_owner(row))
            else:
                check_ks6(entry,raw,native_owner(row,execution=True))
            pending.append((entry,raw,row))
        documents = [(entry,raw,row) for entry,raw,row in pending if entry['family']=='pdf']
        books = [(entry,raw) for entry,raw,_ in pending if entry['family']=='ks6']
        baselines, carried = {}, {}
        for entry,_,_ in documents:
            policy = entry.get('source_policy')
            need(isinstance(policy,dict) and policy.get('family') == entry.get('source_family'),
                 'Проверка состава исходных карточек отсутствует. Проверьте файлы заново.')
            key = tuple(policy['family'])
            need(key not in baselines or baselines[key] == policy,
                 'Источники менялись между проверками файлов. Повторите проверку этой группы.')
            baselines[key] = policy
        archive_policies = [entry.get('source_policy') for entry,_ in books]
        if books:
            need(ns.day(taken_at), 'Укажите дату снимка КС-6а. Дата изменения файла не является датой выполнения.')
            need(all(isinstance(value,dict) and set(value)=={'archive_revision'} for value in archive_policies)
                 and all(value==archive_policies[0] for value in archive_policies),
                 'Состав снимков менялся между проверками. Проверьте ведомости заново.')
            archive = archive_bytes([(entry['filename'],raw) for entry,raw in books])
    # PDF guards share the original archive revision. Commit them before
    # our own optional KS import changes that revision; never rebase a pin
    # onto unrelated current state. Only a native own-write seal may carry
    # the exact same family's metadata to its next source in this batch.
    for entry,raw,row in documents:
        try:
            ns.assert_namespace(project)
            key = tuple(entry['source_policy']['family'])
            policy = carried.get(key, entry['source_policy'])
            if document_commit:
                result = document_commit(project,staged['cut'],row,entry,raw,policy)
            else:
                need(not entry.get('native_context'), 'Операционное обновление требует штатного обработчика карточки.')
                with ns.locked(project):
                    result = files.store(project,native_owner(row),entry['filename'],raw,source_policy=policy)
            if not result.get('already'):
                carried[key] = result['source_policy_guard']
            outcomes.append(dict(id=entry['id'],filename=entry['filename'],status='already' if result.get('already') else 'imported',
                                 sha256=entry['sha256'],contract_id=row['id'],preserved_removed=bool(result.get('preserved_removed'))))
        except (files.ContractFilesProblem,DiskSourceProblem) as exc:
            outcomes.append(dict(id=entry['id'],filename=entry['filename'],status='review',reason=str(exc),sha256=entry['sha256']))
    if books:
        try:
            ns.assert_namespace(project)
            if book_commit:
                snapshot = book_commit(project,staged['cut'],books,taken_at,archive,archive_policies[0])
            else:
                need(not any(entry.get('native_context') for entry,_ in books), 'Операционное обновление требует штатного обработчика карточки.')
                with ns.locked(project):
                    snapshot = ledgers.store_archive(project,archive,taken_at,'Обновление с Диска.zip',source_policy=archive_policies[0])
            outcomes.extend(dict(id=entry['id'],filename=entry['filename'],status='imported',sha256=entry['sha256'],snapshot_id=snapshot['snapshot_id']) for entry,_ in books)
        except (ledgers.LedgerProblem,DiskSourceProblem) as exc:
            outcomes.extend(dict(id=entry['id'],filename=entry['filename'],status='review',reason=str(exc),sha256=entry['sha256']) for entry,_ in books)
    return dict(scope=staged['scope'],scope_notice=scope_notice(staged['scope']),entries=outcomes,review=[x for x in staged['entries'] if x['status'] != 'ready'],
                notice='Обработаны только проверенные источники. Строки со статусом «Требует сверки» не применены. Подпись и редакция ГПР подтверждаются в карточке договора. Прежние версии сохранены.')
