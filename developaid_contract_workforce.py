"""Dated per-contract personnel evidence, shared by the card and its workbook.

The projector never distributes a company crew, sums repeated plan resources,
or writes a scope decision. Existing source-bound decisions may be supplied
by server code; request bodies are not a source of such decisions.
"""
from __future__ import annotations

from collections import defaultdict
import datetime as dt
import hashlib
import json
import math
import re
import stat
from contextlib import nullcontext

SCHEMA = 'contract-workforce-v3'
REPORTS_NOT_LOADED = 'Сводки бота не загружены; наличие отчёта и фактическая численность не проверены.'
CATEGORIES = ('workers', 'itr')
HEADERS = ('Дата', 'Рабочие: план', 'Рабочие: факт', 'Отклонение, чел.',
           'ИТР: план', 'ИТР: факт', 'Отклонение, чел.', 'Источники и пояснение')
NOTE = ('Сравниваются одна дата и один состав персонала. Разница = факт − план. '
        'Общая бригада и общие ИТР не распределяются между договорами. '
        'Отсутствие записи не означает ноль; численность разных дней не суммируется.')
_HEX = re.compile(r'^[a-f0-9]{64}$')
COHORT_SCHEMA = 'contract-workforce-source-guard-v1'
REGISTER_GUARD = '_workforce_source_guard'
MAX_COHORT_FILES = 2048
MAX_COHORT_BYTES = 32 * 1024 * 1024


class SourceChanged(ValueError):
    status = 409


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _day(value):
    try:
        day = dt.date.fromisoformat(str(value))
        return day.isoformat() if str(value) == day.isoformat() else ''
    except (ValueError, TypeError):
        return ''


def _count(value):
    return (value if isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value >= 0 else None)


def _text(value):
    return ' '.join(str(value or '').lower().replace('ё', 'е').split())


def _cohort_inventory(root, cut):
    """Bounded native metadata only: no PDF/ZIP reads, parses or register build."""
    import developaid_contract_identity_store as store
    from developaid_contract_files import ContractFilesProblem
    entries, total = [], 0

    def children(folder):
        found = []
        for path in folder.iterdir():
            found.append(path)
            if len(found) > MAX_COHORT_FILES:
                raise ContractFilesProblem('Слишком много файлов для проверки источников численности.')
        return sorted(found)

    def add(path, *, content=True):
        nonlocal total
        try:
            info = path.lstat()
        except FileNotFoundError:
            return
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ContractFilesProblem('Происхождение источников численности не подтверждено. Обновите карточку.')
        if content:
            raw = store.read_bytes(path, 4 * 1024 * 1024)
            if raw is None:
                raise ContractFilesProblem('Источники численности изменились во время чтения. Обновите карточку.')
            total += len(raw)
            pin = hashlib.sha256(raw).hexdigest()
        else:
            # Native archive identities are immutable SHA-named sources.
            # Their roster/stamps detect uploads/removal/cache refresh without
            # rereading multi-megabyte manifests or financial archive bodies.
            pin = [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns]
        entries.append([path.relative_to(root).as_posix(), pin])
        if len(entries) > MAX_COHORT_FILES or total > MAX_COHORT_BYTES:
            raise ContractFilesProblem('Состав источников численности превышает предел проверки. Обновите карточку.')

    for name in ('contract_identity_decisions.jsonl', 'cumulative_terms.json',
                 'cumulative_header_dates.json', 'contract_links.json', 'contract_pdf_sources.json'):
        add(root / name)
    for folder in (root / 'cumulative', root / 'contract_documents', root / 'estimate'):
        if folder.is_symlink():
            raise ContractFilesProblem('Каталог источников численности не подтверждён.')
    cumulative = root / 'cumulative'
    if cumulative.exists():
        add(cumulative / '.snapshot-activity.json')
        for path in children(cumulative):
            if re.fullmatch(r'\d{4}-\d{2}-\d{2}-[a-f0-9]{64}\.(?:json|zip)', path.name) and path.name[:10] <= cut:
                add(path, content=False)
    estimate = root / 'estimate'
    if estimate.exists():
        for path in children(estimate):
            if path.suffix == '.xlsx' and path.stem <= cut:
                add(path, content=False)
    documents = root / 'contract_documents'
    families = []
    if documents.exists():
        folders = [path for path in children(documents) if _HEX.fullmatch(path.name)]
        if len(folders) > 256:
            raise ContractFilesProblem('Слишком много карточек для проверки источников численности.')
        for folder in folders:
            if folder.is_symlink() or not folder.is_dir():
                raise ContractFilesProblem('Каталог договора не подтверждён.')
            families.append(folder.name)
            entries.append([folder.relative_to(root).as_posix(), 'native_card'])
            for path in children(folder):
                # GPR calendar events do not feed register identity/scope.
                # Its selected graph/anchor has the separate target GPR guard;
                # keeping events here would reject every own anchor save.
                if path.name == 'links.json' or re.fullmatch(r'[a-f0-9]{64}\.json', path.name):
                    add(path)
                elif re.fullmatch(r'[a-f0-9]{64}\.pdf', path.name):
                    add(path, content=False)
    return {'families': families, 'sha256': digest(entries)}


def cohort_sources(project_name, cut):
    """Pin native peer inputs in existing global lock order, never expand a held family.

    Operational mutations may already hold only their selected native family.
    They reuse those locks and use an atomic two-pass seal for all other peers;
    taking an earlier peer lock while holding a later one would deadlock.
    A normal download takes the existing complete family in native order.
    """
    import developaid_contract_identity as identity
    import developaid_contract_identity_store as store
    import developaid_contract_files as files
    cut = _day(cut)
    if not cut:
        raise files.ContractFilesProblem('Дата численности не подтверждена.')
    with store.namespace(project_name):
        root = store.project_root(project_name)
        if not root.is_dir():
            raise files.ContractFilesProblem('Проект для проверки численности не найден.')
        held = store._HELD_NATIVE_LOCKS.get()
        card_held = bool(getattr(files._held, 'folders', set()))
        first = _cohort_inventory(root, cut)
        paths = [identity._safe_path(project_name, *parts) for parts in (
            ('cumulative', '.lock'), ('cumulative_header_dates.lock',),
            ('cumulative_terms.lock',), ('.contract_links.lock',))]
        paths += [identity._safe_path(project_name, 'contract_documents', value, '.lock')
                  for value in first['families']]
        outer = nullcontext() if held or card_held else store.locked(project_name)
        locks = nullcontext() if held or card_held else identity._binding_path_locks(paths)
        with outer, locks:
            before = _cohort_inventory(root, cut)
            after = _cohort_inventory(root, cut)
            if first != before or before != after:
                raise files.ContractFilesProblem('Состав договоров или их источники изменились. Откройте карточку заново.')
            info = root.stat()
            return {'schema': COHORT_SCHEMA, 'project_scope': store.project_scope(project_name), 'cut': cut,
                    'namespace': [info.st_dev, info.st_ino], 'sources_sha256': after['sha256']}


def reports_revision(reports, cut):
    """Pin all saved dated reports, including a changed or absent count label."""
    pinned = [{'date': r.get('date'), 'text': r.get('text'),
               'parsed': r.get('parsed'), 'contractors': r.get('contractors'),
               'source': r.get('source'), 'stored_at': r.get('stored_at')}
              for r in reports if cut and _day(r.get('date')) and _day(r['date']) <= cut]
    return digest(sorted({digest(r) for r in pinned}))


def _raw_counts(line, daily):
    """A range, expression or repeated category is not one exact headcount."""
    # Native legacy \w* also consumes compact count digits (рабочие12 → 2).
    patterns = {'workers': re.compile(r'рабоч[^\W\d_]*\D{0,12}?(\d+)', re.I), 'itr': daily._ITR}
    matches = {category: list(pattern.finditer(line)) for category, pattern in patterns.items()}
    labels = list(re.finditer(r'\b(?:итр|рабоч\w*)\b', line, re.I))
    values, reasons = {}, {}
    for category, found in matches.items():
        exact = len(found) == 1
        if exact:
            match = found[0]
            finish = min((label.start() for label in labels if label.start() > match.start()), default=len(line))
            segment = line[match.start():finish]
            exact = not re.search(r'\d\s*(?:[-–—/+]|[.,](?=\d)|\bи\b)\s*\d', segment, re.I)
        values[category] = int(found[0][1]) if found and exact else None
        if found and not exact:
            reasons[category] = 'В исходной строке диапазон, выражение или несколько значений категории; точная численность не подтверждена.'
    return matches, values, reasons


def personnel(reports, cut):
    """Retain raw presence. Legacy parsed zero is unknown without its label."""
    import developaid_monitor_daily as daily
    out = []
    for report in reports:
        date = _day(report.get('date'))
        if not date or date > cut:
            continue
        raw = str(report.get('text') or '')
        source = {**(report.get('source') or {}), 'kind': 'daily_report', 'date': date,
                  'text_sha256': hashlib.sha256(raw.encode()).hexdigest() if raw else '',
                  'parsed_sha256': digest(report.get('parsed') or report.get('contractors') or {})}
        found = []
        if raw:
            for index, line in enumerate(raw.splitlines()):
                if daily._section_of(line):
                    break  # Counts inside work/supply prose are not the headcount header.
                matches, values, reasons = _raw_counts(line, daily)
                if not any(matches.values()):
                    continue
                end = min(m[0].start() for m in matches.values() if m)
                name = daily._LEAD_NUM.sub('', line[:end]).strip(' \t:—–-.,;')
                if not name:
                    # A wrapped category belongs to the preceding explicit party.
                    if not found:
                        continue
                    target = found[-1]
                    for category, match in matches.items():
                        if match:
                            repeated = target[category + '_present'] or category in target['ambiguities']
                            target[category] = values[category] if not repeated else None
                            target[category + '_present'] = target[category] is not None
                            if repeated or category in reasons:
                                target['ambiguities'][category] = reasons.get(category) or 'Категория повторяется в исходнике; состав не подтверждён.'
                            target['raw'] += '\n' + line
                    continue
                found.append({'party': name, 'raw': line, 'line': index,
                    **values, 'ambiguities': reasons,
                    **{category + '_present': values[category] is not None for category in CATEGORIES}})
        else:
            parsed = report.get('parsed') or report
            for index, item in enumerate(parsed.get('contractors') or []):
                row = {'party': str(item.get('name') or ''), 'raw': '', 'line': index, 'ambiguities': {}}
                for category in CATEGORIES:
                    value = _count(item.get(category))
                    present = item.get(category + '_present') is True or value is not None and value > 0
                    row.update({category: value if present else None, category + '_present': present})
                found.append(row)
        for row in found:
            row.update(date=date, source=source)
            row['personnel_key'] = digest({'date': date, 'source': source,
                'line': row['line'], 'party': row['party'], 'raw': row['raw']})
            out.append(row)
    # The same saved report observed twice is one source. Two different lines
    # with the same counts remain distinct and must not be silently summed.
    return list({row['personnel_key']: row for row in out}.values())


def _resource_values(schedule, date):
    found = defaultdict(list)
    for index, resource in enumerate((schedule or {}).get('resources') or []):
        for cell in resource.get('values') or []:
            start, finish = _day(cell.get('start')), _day(cell.get('finish'))
            if not start or not finish or not start <= date <= finish:
                continue
            basis = resource.get('period_basis')
            allowed = (basis == 'literal_date' and start == finish
                or basis == 'explicit_interval'
                or basis == 'relative_explicit_period' and schedule.get('calendar_state') == 'anchored'
                and bool(_day((schedule.get('anchor') or {}).get('handover_date'))))
            if not allowed:
                continue
            found[resource.get('category')].append({'value': _count(cell.get('value')),
                'raw': cell.get('raw'), 'range': cell['value'] if isinstance(cell.get('value'), dict) else None,
                'source': resource.get('source'), 'label': resource.get('name'),
                'scope': resource.get('scope'), 'scope_state': resource.get('scope_state'),
                'period_basis': resource.get('period_basis'), 'start': start, 'finish': finish,
                'resource_key': digest({'index': index, 'resource': resource})})
    return dict(found)


def _plan_bound(row, source):
    contract = source.get('contract') or {}
    return (bool(_HEX.fullmatch(str(row.get('id') or '')))
            and bool(_HEX.fullmatch(str(source.get('sha256') or '')))
            and contract.get('number') == row.get('contract')
            and _day(contract.get('date')) and contract.get('date') == row.get('contract_date')
            and row.get('excluded') is not True)


def _candidates(person, rows):
    import developaid_monitor_contract_links as links
    # Use the native whole-party identity rules, never the broader substring
    # crew matcher. An explicit contract reference can disambiguate a party.
    references = links._explicit_contract_numbers(person['party'])
    party = re.split(r'\b(?:договор\w*|дог\.)\s*', person['party'], maxsplit=1, flags=re.I)[0].strip(' ,;:—-')
    found, basis = links._party_rows(party, rows)
    if basis == 'work_context':
        annotation = re.fullmatch(r'(.+?)\s*\(([^()]*)\)\s*', party)
        words = links._work_words(annotation[2]) if annotation else set()
        found = [r for r in found if words and words <= links._work_words(' '.join([
            str(r.get('subject') or ''), *(str(x) for x in r.get('scope') or []),
            *(str(x.get('name') or '') for x in r.get('physical_items') or [])]))]
    found = [r for r in found if r.get('id') and r.get('excluded') is not True
             and (not r.get('contract_date') or r['contract_date'] <= person['date'])]
    if references:
        found = [r for r in found if links._text(r.get('contract')).replace('–','-').replace('—','-') in references]
    return found, basis, references


def company_observations(people, row, peers):
    """Whole-company identity only; a work qualifier never allocates a crew.

    The strict contract matcher may correctly reject '(roofing)' when the
    register has no work context. That does not erase the company's source
    report. Distinct explicit legal names/forms remain distinct here too.
    """
    import developaid_monitor_contract_links as links
    result = []
    for person in people:
        party = re.split(r'\b(?:договор\w*|дог\.)\s*', person['party'], maxsplit=1, flags=re.I)[0].strip(' ,;:—-')
        qualifier = re.fullmatch(r'(.+?)\s*\(([^()]*)\)\s*', party)
        base = qualifier[1].strip() if qualifier else party
        candidates, basis = links._party_rows(base, peers)
        identities = {tuple(links._party_parts(r.get('contractor'))[0]) + (links._party_parts(r.get('contractor'))[1],)
                      for r in candidates}
        if (basis in {'not_found','unresolved_context','ambiguous_alias'} or len(identities) != 1
                or not any(r.get('id') == row.get('id') and r.get('excluded') is not True for r in candidates)):
            continue
        result.append({'date':person['date'], 'scope':'contractor_unallocated', 'contract_fact':False,
            'candidate':{k:person.get(k) for k in ('personnel_key','party','workers','itr','workers_present',
                'itr_present','source','raw','ambiguities')}})
    return result


def _whole_resource(resource, schedule, person, row):
    scope = resource.get('scope')
    if isinstance(scope, dict):
        scope = scope.get('text') if scope.get('complete') is True else ''
    if scope and resource.get('scope_state') == 'confirmed':
        return True
    # A resource caption is evidence; a preceding work heading is only a hint.
    # Repeated crew/category rows can never become a single object total.
    unique = sum(r.get('category') == resource.get('category')
                 for r in schedule.get('resources') or []) == 1
    caption = re.fullmatch(
        r'(?:(?:необходимое\s+)?(?:количество|численность)\s+|всего\s+)'
        r'(рабочих|рабочие|итр)\s+(?:на\s+объекте|по\s+(?:всему\s+)?договору|по\s+объекту)'
        r'(?:\s*\(([^()]*)\))?[.:]?', _text(resource.get('label')))
    if not unique or not caption:
        return False
    qualifier = caption[2]
    if not qualifier:
        return True
    if resource.get('category') == 'itr':
        return qualifier == 'назначенные по приказу'
    # A profession list can qualify the complete crew; a work heading,
    # corpus restriction or unrelated profession cannot. Generic assistants
    # alone do not establish that all workers were included.
    import developaid_monitor_contract_links as links
    context = links._work_words(' '.join([person['party'], str(row.get('subject') or ''),
                                        *(str(x) for x in row.get('scope') or [])]))
    disciplines = []
    for profession in map(str.strip, qualifier.split(',')):
        if profession in {'подсобники', 'разнорабочие'}:
            continue
        if not re.fullmatch(r'[а-я]{3,}(?:ники|щики|чики|исты|ры)', profession):
            return False
        disciplines.append(profession)
        if not any(len(word) >= 5 and word[:5] == profession[:5] for word in context):
            return False
    return bool(disciplines)


def _binding(person, category, row, source, plans, peers, bindings, schedule):
    candidates, basis, references = _candidates(person, peers)
    ids = {r['id'] for r in candidates}
    # A bound decision must pin the actual report, GPR edition, category and
    # complete cohort. It is not inferred from a confirmed individual work.
    assigned = [b for b in bindings if b.get('personnel_key') == person['personnel_key']
        and b.get('scope_complete') is True and b.get('confirmed') is True
        and category in (b.get('categories') or [])
        and _HEX.fullmatch(str((b.get('source') or {}).get('sha256') or ''))
        and str(b.get('scope') or '').strip()]
    if assigned and {b.get('contract_id') for b in assigned} != {row['id']}:
        return False, 'Одна бригада или ИТР относятся к нескольким договорам; распределение не подтверждено.', None
    valid = [b for b in assigned if b.get('plan_sha256') == source.get('sha256')]
    if valid:
        owners = {b.get('contract_id') for b in valid}
        if owners == {row['id']}:
            return True, 'Сохранённая связь полного состава с договором и редакцией ГПР.', valid[0]['source']
        return False, 'Одна бригада или ИТР относятся к нескольким договорам; распределение не подтверждено.', None
    if person['source'].get('contract_scope_confirmed') is False:
        return False, 'Источник содержит численность подрядчика по направлению; полный состав по договору не подтверждён.', None
    if ids != {row['id']}:
        return False, 'Численность сообщения не распределена однозначно между договорами подрядчика.', None
    resources = plans.get(category) or [dict(r, label=r.get('name'))
        for r in schedule.get('resources') or [] if r.get('category') == category]
    if len(resources) != 1:
        return False, 'В ГПР нет единственного отдельного показателя этой категории; общие бригады не сложены.', None
    resource = resources[0]
    if not _whole_resource({**resource, 'category': category}, schedule, person, row):
        return False, 'Полный состав планового ресурса ГПР не подтверждён; заголовок работ не является составом бригады.', None
    import developaid_monitor_contract_links as links
    actual_objects, actual_unclear = links._scope_info(person['party'])
    plan_objects, plan_unclear = links._scope_info(resource.get('scope'))
    if not plan_objects:
        plan_objects, plan_unclear = links._contract_scope_info(row)
    if actual_unclear or plan_unclear or actual_objects and actual_objects != plan_objects:
        return False, 'Состав объектов сообщения не совпадает с полным составом планового ресурса.', None
    scope = resource.get('scope')
    if isinstance(scope, dict):
        scope = scope.get('text') if scope.get('complete') is True else ''
    scope = str(scope or '').strip()
    # The resource's whole-cohort scope must already be explicit. A preceding
    # work heading is only a hint and is deliberately not used as such proof.
    if (references and len(references) == 1 or basis == 'work_context'
            or scope and resource.get('scope_state') == 'confirmed'
            and re.search(r'\(([^()]*)\)', person['party'])
            and _text(re.search(r'\(([^()]*)\)', person['party'])[1]) == _text(scope)):
        return True, 'Однозначный договор и полный состав указаны в исходнике сообщения/ГПР.', person['source']
    return False, 'Договор найден; совпадение полного состава бригады и ресурса ГПР не подтверждено.', None


def project(schedule, reports, row, register, cut, *, source=None, existing_bindings=()):
    """Pure snapshot projection. No project-wide total or daily interpolation."""
    cut = _day(cut)
    reports_loaded = reports is not None
    reports = reports or ()
    source = source or (schedule or {}).get('source_identity') or {}
    result = {'schema': SCHEMA, 'cut': cut, 'contract_id': row.get('id'),
        'contract': row.get('contract'), 'contractor': row.get('contractor'),
        'plan_source': source, 'rows': [], 'note': NOTE, 'available': False,
        'report_input_status': 'loaded' if reports_loaded else 'not_loaded',
        'report_status_note': '' if reports_loaded else REPORTS_NOT_LOADED,
        'report_sources_revision': reports_revision(reports, cut) if reports_loaded else None,
        'company_observations': [], 'report_dates': sorted({_day(r.get('date')) for r in reports if cut and _day(r.get('date')) and _day(r['date']) <= cut}),
        'bindings_revision': digest(existing_bindings),
        'coverage': {'dates': 0, 'workers_pairs': 0, 'itr_pairs': 0, 'project_total': False}}
    if not cut or not _plan_bound(row, source):
        result['reason'] = 'Нет подтверждённой привязки ГПР к этому договору и дате; численность не рассчитана.'
        result['revision'] = digest(result)
        return result
    people = personnel(reports, cut)
    peers = register.get('rows') or []
    result['company_observations'] = company_observations(people, row, peers)
    # Literal operation/period captions are context, never whole-crew totals.
    result['plan_annotations'] = [dict(a) for a in (schedule or {}).get('personnel_annotations') or []
        if (a.get('source') or {}).get('sha256') == source.get('sha256')]
    by_date = defaultdict(list)
    for person in people:
        candidates, _, _ = _candidates(person, peers)
        if any(r['id'] == row['id'] for r in candidates):
            by_date[person['date']].append(person)
    dates = set(by_date)
    for resource in (schedule or {}).get('resources') or []:
        for value in resource.get('values') or []:
            start = _day(value.get('start'))
            if start and start <= cut:
                dates.add(start)
    if not dates:
        dates.add(cut)
    for date in sorted(dates):
        plans = _resource_values(schedule, date)
        item = {'date': date, 'source_date': date, 'reasons': [], 'sources': [], 'candidates': []}
        for category in CATEGORIES:
            values = plans.get(category) or []
            plan = values[0]['value'] if len(values) == 1 else None
            item[category + '_plan'] = plan
            item[category + '_plan_sources'] = values
            item['sources'].extend(v.get('source') for v in values if v.get('source'))
            if len(values) > 1:
                item['reasons'].append('В ГПР несколько строк «'+('Рабочие' if category == 'workers' else 'ИТР')+'»; общий состав не подтверждён, строки не суммируются.')
            accepted = []
            for person in by_date.get(date, []):
                matched, reason, proof = _binding(person, category, row, source, plans, peers, existing_bindings, schedule)
                item['candidates'].append({k: person.get(k) for k in ('personnel_key','party','workers','itr','workers_present','itr_present','source','raw','ambiguities')})
                if person['ambiguities'].get(category):
                    item['reasons'].append(person['ambiguities'][category])
                if matched and person[category + '_present']:
                    accepted.append((person, proof, reason))
                elif not matched:
                    item['reasons'].append(reason)
            fact = accepted[0][0][category] if len(accepted) == 1 else None
            if len(accepted) > 1:
                item['reasons'].append('На одну дату есть несколько записей бригад/ИТР; численность не суммируется без отдельного подтверждения состава.')
            item[category + '_fact'] = fact
            item[category + '_delta'] = fact-plan if fact is not None and plan is not None else None
            if fact is not None:
                item[category + '_personnel_key'] = accepted[0][0]['personnel_key']
                item[category + '_basis'] = accepted[0][2]
                item['sources'].extend([accepted[0][0]['source'], accepted[0][1]])
            if item[category + '_delta'] is not None:
                result['coverage'][category + '_pairs'] += 1
        if plans.get('workers_and_itr'):
            item['combined_plan'] = plans['workers_and_itr']
            item['reasons'].append('В ГПР рабочие и ИТР объединены; раздельный план не выдуман.')
        if not by_date.get(date):
            item['reasons'].append('На эту дату нет подходящей строки численности в сохранённых отчётах.'
                                   if reports_loaded else REPORTS_NOT_LOADED)
        if not plans:
            item['reasons'].append('На эту дату в ГПР нет подтверждённого календарного показателя численности; даты не интерполированы.')
        edition_date = (source.get('edition') or {}).get('date')
        if edition_date and date < edition_date:
            item['reasons'].append('Сравнение с более поздней текущей редакцией ГПР; исторически действовавшая редакция не подтверждена.')
        item['reasons'] = list(dict.fromkeys(item['reasons']))
        item['candidates'] = list({v['personnel_key']: v for v in item['candidates']}.values())
        result['rows'].append(item)
    result['available'] = any(any(r.get(category + '_plan_sources') or r.get(category + '_fact') is not None
                                 for category in CATEGORIES) or r.get('combined_plan') for r in result['rows'])
    if not result['available']:
        result['reason'] = (REPORTS_NOT_LOADED if not reports_loaded else
            'В ГПР нет календарных строк численности; записи подрядчика в отчётах есть, '
            'но состав по этому договору не распределён.' if by_date else
            'В ГПР нет календарных строк численности и в сохранённых отчётах нет применимого состава этого договора.')
        if result['company_observations']:
            result['reason'] = ('Датированные записи подрядчика в отчётах есть; численность показана отдельно. '
                'Общий состав по этому договору не подтверждён; план и отклонения не рассчитаны.')
    result['coverage']['dates'] = len(result['rows'])
    result['company_rows'] = company_rows(result)
    result['revision'] = digest(result)
    return result


def company_rows(projection):
    """One source observation per row, shared by the PAGE and workbook.

    A contract resource plan does not suppress unallocated company reports.
    Different source records remain separate even when their counts agree.
    """
    found, by_date = [], {}
    for item in projection.get('rows') or []:
        if (not _day(item.get('date')) or
                projection.get('cut') and item['date'] > projection['cut']):
            continue
        by_date.setdefault(item['date'],[]).extend(c for c in item.get('candidates') or [] if c.get('personnel_key'))
    for item in projection.get('company_observations') or []:
        if (_day(item.get('date')) and (not projection.get('cut') or item['date'] <= projection['cut'])
                and item.get('scope') == 'contractor_unallocated' and item.get('contract_fact') is False):
            candidate = item.get('candidate') or {}
            if candidate.get('personnel_key'):
                by_date.setdefault(item['date'],[]).append(candidate)
    for date, values in sorted(by_date.items()):
        candidates = list({digest(candidate):candidate for candidate in values}.values())
        for candidate in candidates:
            row = {'date':date,'workers':None,'itr':None,'candidates':[candidate]}
            reasons = []
            for key,label in (('workers','Рабочие'),('itr','ИТР')):
                value = candidate.get(key)
                if (candidate.get(key+'_present') is True and type(value) in (int,float)
                        and math.isfinite(value) and value >= 0 and not (candidate.get('ambiguities') or {}).get(key)):
                    row[key] = value
                else:
                    reasons.append(label+': категория не подтверждена.')
            row['reason'] = (str(candidate.get('party') or 'Подрядчик')+
                '. Отдельная запись источника; с другими строками не суммируется. '
                'По договорам повторно не суммировать. План не сопоставлен.'+
                (' '+' '.join(reasons) if reasons else ''))
            found.append(row)
    return found


def from_cached(project_name, row, register, cut, gpr_state, *, existing_bindings=()):
    """Read existing reports only; never write an allocation or reload a chat."""
    import developaid_monitor_daily as daily
    expected = register.get(REGISTER_GUARD)
    if not isinstance(expected, dict) or expected != cohort_sources(project_name, cut):
        raise SourceChanged('Состав договоров изменился. Откройте карточку заново перед сравнением численности.')
    result = project(gpr_state.get('schedule') or {}, daily._load_reports(project_name), row,
                     register, cut, source=gpr_state.get('source') or {}, existing_bindings=existing_bindings)
    if expected != cohort_sources(project_name, cut):
        raise SourceChanged('Источники численности изменились во время чтения. Откройте карточку заново.')
    result['cohort_source_guard'] = expected
    result['revision'] = digest({key:value for key,value in result.items() if key != 'revision'})
    return result


def require_current(projection, project_name, *, existing_bindings=()):
    """Download guard; changes require the normal card refresh, no new writes."""
    import developaid_monitor_daily as daily
    import developaid_contract_identity_store as store
    from developaid_contract_files import ContractFilesProblem
    try:
        return (projection.get('schema') == SCHEMA
                and projection.get('cohort_source_guard') == cohort_sources(project_name, projection.get('cut'))
                and projection.get('report_sources_revision') == reports_revision(daily._load_reports(project_name), projection.get('cut') or '')
                and projection.get('bindings_revision') == digest(existing_bindings))
    except (ContractFilesProblem, store.IdentityProblem, OSError):
        return False


def write_sheet(workbook, projection):
    if not projection.get('available'):
        return None
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.comments import Comment
    sheet = workbook.create_sheet('Численность')
    sheet.sheet_view.showGridLines = False
    sheet.freeze_panes = None
    for number, text in enumerate((
            'Численность · '+str(projection.get('contract') or 'Договор'), NOTE,
            'Сравнение с текущей редакцией ГПР; отсутствие исторической редакции не означает нарушение договора.'), 1):
        sheet.cell(number, 1, text);sheet.merge_cells(start_row=number,start_column=1,end_row=number,end_column=8)
        sheet.row_dimensions[number].height=35
    for column,label in enumerate(HEADERS,1):
        cell=sheet.cell(5,column,label);cell.fill=PatternFill('solid',fgColor='1F4E78')
        cell.font=Font(name='Calibri',size=10,bold=True,color='FFFFFF')
    for item in projection.get('rows') or [{'date':'','reasons':[projection.get('reason') or 'Нет сопоставимых данных.']}]:
        notes=list(item.get('reasons') or [])
        matched={item.get(category+'_personnel_key') for category in CATEGORIES
                 if item.get(category+'_fact') is not None}
        for candidate in item.get('candidates') or []:
            counts=', '.join(('рабочие' if category=='workers' else 'ИТР')+': '+str(candidate[category])
                             for category in CATEGORIES if candidate.get(category+'_present'))
            if candidate['personnel_key'] in matched:
                notes.append('Источник факта: отчёт '+str(item.get('date') or '')+'; '+candidate['party']+'.')
            else:
                notes.append('В сообщении: '+candidate['party']+'; '+counts+'. Это не распределение по договорам.')
        for category in CATEGORIES:
            for plan in item.get(category+'_plan_sources') or []:
                if plan.get('range'):
                    notes.append('План '+('рабочих' if category=='workers' else 'ИТР')+': '+str(plan['range'].get('raw') or plan['range'])+'; диапазон не заменён одним числом.')
        for combined in item.get('combined_plan') or []:
            value = combined.get('value')
            label = str(value) if value is not None else str((combined.get('range') or {}).get('raw') or 'не подтверждён')
            notes.append('План рабочих и ИТР вместе: '+label+'.')
        sheet.append([dt.date.fromisoformat(item['date']) if _day(item.get('date')) else None,
            *[item.get(category+'_'+field) for category in CATEGORIES for field in ('plan','fact','delta')],
            '\n'.join(dict.fromkeys(notes))])
        row=sheet.max_row;sheet.cell(row,1).number_format='dd.mm.yyyy'
        for target,planned,actual in (('D','B','C'),('G','E','F')):
            sheet[target+str(row)]='=IF(COUNT('+planned+str(row)+':'+actual+str(row)+')=2,'+actual+str(row)+'-'+planned+str(row)+',"")'
        sources={'plan':projection.get('plan_source'),'date':item.get('date'),'sources':item.get('sources'),
                 'candidates':item.get('candidates')}
        sheet.cell(row,8).comment=Comment(json.dumps(sources,ensure_ascii=False,sort_keys=True),'DevelopAid')
        sheet.row_dimensions[row].height=min(180,max(44,14*(1+len(sheet.cell(row,8).value)//65+sheet.cell(row,8).value.count('\n'))))
    for cells in sheet:
        for cell in cells:
            if isinstance(cell.value, str) and not (cell.row > 5 and cell.column in (4,7) and cell.data_type == 'f'):
                cell.data_type = 's'
            cell.alignment=Alignment(wrap_text=True,vertical='top')
            if cell.row != 5:cell.font=Font(name='Calibri',size=10)
    for column,width in zip('ABCDEFGH',(14,15,15,17,13,13,17,72)):
        sheet.column_dimensions[column].width=width
    sheet.auto_filter.ref='A5:H'+str(sheet.max_row)
    sheet.sheet_properties.pageSetUpPr.fitToPage=True
    sheet.page_setup.orientation='landscape';sheet.page_setup.fitToWidth=1;sheet.page_setup.fitToHeight=0
    return sheet
