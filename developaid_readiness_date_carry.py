"""Bounded approved, audited date corrections preserve current-plan choices.

The original readiness event and every source stay untouched. This is not a
general cross-source mapping: all work semantics and explicit weights survive.
"""
from __future__ import annotations

import copy
import datetime as dt
import io
import math
import re
import zipfile
import xml.etree.ElementTree as ET

import developaid_gpr_corpus as corpus
import developaid_monitor as monitor
import developaid_schedule_elements as elements
import developaid_schedule_versions as versions

MAX_CHAIN_EDGES = 8
MAX_AUDIT_ROWS = 160
MAX_AUDIT_XML = 1024 * 1024
_BANNER = 'Производная копия только листа ГПР из сохранённого разбора; не исходная книга.'
_HEADER = ['cell', 'original_raw', 'new_value', 'explicit_basis']
_REASONS = {
    'source_unreadable': 'Не удалось прочитать проверяемые утверждённые источники ГПР.',
    'source_digest': 'Отпечаток сохранённого источника ГПР не совпал с утверждённым.',
    'provenance_invalid': 'Протокол исправления дат отсутствует, повреждён или неоднозначен.',
    'lineage': 'Нет ограниченной подтверждённой цепочки между остаточными версиями ГПР.',
    'scope': 'Профиль не относится к оценке текущего остаточного состава.',
    'source_format': 'Формат источника не поддерживает проверяемый перенос долей.',
    'date_audit': 'Протокол не совпал с точным набором исправленных дат источника.',
    'semantics': 'В источнике изменились не только плановые даты или происхождение источника.',
    'definitions': 'Определения работ не совпали с сохранённым профилем.',
    'weights': 'Основания долей неизвестны или зависят от неподдерживаемого метода.',
    'parent_future': 'Прежний источник ещё не был утверждён на дату выбранного среза.',
}


class DateCarryProblem(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(_REASONS[code])


def _source_call(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except (OSError, ValueError, zipfile.BadZipFile, ET.ParseError) as exc:
        raise DateCarryProblem('source_unreadable') from exc


def _audit(data):
    """Bound the entire provenance worksheet, including hidden/extra cells."""
    from openpyxl import load_workbook
    from developaid_monitor_ledgers import _xlsx_bounds
    _source_call(_xlsx_bounds, data)
    try:
        book = _source_call(load_workbook, io.BytesIO(data), read_only=True, data_only=False, keep_links=False)
    except KeyError as exc:
        # openpyxl uses KeyError for missing mandatory ZIP members.
        raise DateCarryProblem('provenance_invalid') from exc
    try:
        if book.sheetnames != ['ГПР', 'Происхождение']:
            raise DateCarryProblem('provenance_invalid')
        sheet = book['Происхождение']
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                with archive.open(sheet._worksheet_path.lstrip('/')) as handle:
                    xml = handle.read(MAX_AUDIT_XML+1)
        except (KeyError, OSError, zipfile.BadZipFile) as exc:
            raise DateCarryProblem('provenance_invalid') from exc
        if len(xml) > MAX_AUDIT_XML or b'<!DOCTYPE' in xml or b'<!ENTITY' in xml:
            raise DateCarryProblem('provenance_invalid')
        root = _source_call(ET.fromstring, xml)
        ns = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
        if root.tag != ns+'worksheet' or len(root.findall(ns+'sheetData')) != 1:
            raise DateCarryProblem('provenance_invalid')
        cells, row_numbers = set(), set()
        previous_row = 0
        sheet_data = root.find(ns+'sheetData')
        for row in sheet_data:
            number = row.get('r', '')
            if (row.tag != ns+'row' or not re.fullmatch(r'[1-9][0-9]*', number)
                    or int(number) > MAX_AUDIT_ROWS or int(number) <= previous_row or number in row_numbers):
                raise DateCarryProblem('provenance_invalid')
            row_numbers.add(number)
            previous_row = int(number)
            previous_column = ''
            for node in row:
                ref = node.get('r', '')
                match = re.fullmatch(r'[A-D]([1-9][0-9]*)', ref)
                if (node.tag != ns+'c' or not match or match[1] != number or ref in cells
                        or ref[0] <= previous_column):
                    raise DateCarryProblem('provenance_invalid')
                cells.add(ref)
                previous_column = ref[0]
        if (len(root.findall('.//'+ns+'c')) != len(cells)
                or len(root.findall('.//'+ns+'row')) != len(row_numbers)):
            raise DateCarryProblem('provenance_invalid')
        rows = []
        for row in sheet.iter_rows(max_row=MAX_AUDIT_ROWS, max_col=4):
            if any(cell.data_type == 'f' for cell in row):
                raise DateCarryProblem('provenance_invalid')
            rows.append([cell.value for cell in row])
        while rows and rows[-1] == [None]*4:
            rows.pop()
    finally:
        book.close()
    if len(rows) < 6 or rows[0] != [_BANNER, None, None, None]:
        raise DateCarryProblem('provenance_invalid')
    expected = ('original_upload_sha256', 'expected_active_sha256', 'expected_revision')
    metadata = {}
    for row, name in zip(rows[1:4], expected):
        if row[0] != name or row[2:] != [None, None]:
            raise DateCarryProblem('provenance_invalid')
        metadata[name] = row[1]
    cursor = 4
    seen = set()
    while cursor < len(rows) and rows[cursor][0] == 'saved_parse':
        row = rows[cursor]
        if (row[3] is not None or row[1] in seen or not isinstance(row[1], str)
                or not monitor._day(row[1]) or not isinstance(row[2], str)
                or not versions._SHA.fullmatch(row[2])):
            raise DateCarryProblem('provenance_invalid')
        seen.add(row[1]); cursor += 1
    if cursor >= len(rows) or rows[cursor] != _HEADER:
        raise DateCarryProblem('provenance_invalid')
    audit = rows[cursor+1:]
    if not audit or len(audit) > 100:
        raise DateCarryProblem('provenance_invalid')
    corrections = {}
    for cell, before, after, note in audit:
        if (not isinstance(cell, str) or cell in corrections or not isinstance(note, str)
                or not note.strip() or len(note) > 1000):
            raise DateCarryProblem('provenance_invalid')
        corrections[cell] = before, after
    return metadata, corrections


def _date_cells(source):
    result = {}
    for package in source['packages']:
        for scope in package['scopes']:
            for key in ('start', 'finish'):
                cell = scope['source_cells'][key]
                if cell in result:
                    raise DateCarryProblem('semantics')
                result[cell] = (scope['raw'][key], scope.get(key))
    return result


def _journal(project, target_sha):
    """Read a bounded native journal; callers still verify every used edge."""
    current = _source_call(monitor._working_baseline_state, project)
    if (not isinstance(current, dict) or not isinstance(current.get('versions'), list)
            or len(current['versions']) > versions.MAX_VERSIONS
            or type(current.get('revision')) is not int or current['revision'] < 2
            or current.get('baseline_scope') != 'remaining_work'
            or not isinstance(current.get('source_sha256'), str)
            or not versions._SHA.fullmatch(current['source_sha256'])):
        raise DateCarryProblem('lineage')
    events = current['versions']
    revisions = []
    for event in events:
        if (not isinstance(event, dict) or type(event.get('revision')) is not int
                or event['revision'] < 1):
            raise DateCarryProblem('lineage')
        revisions.append(event['revision'])
    if revisions != list(range(1, len(events)+1)):
        raise DateCarryProblem('lineage')
    child = next((e for e in events if e['revision'] == current['revision']), None)
    if not child or child.get('source_sha256') != target_sha or current['source_sha256'] != target_sha:
        raise DateCarryProblem('lineage')
    return events, current['revision']


def _verified_edge(project, parent, child, *, expected_parent_sha=None):
    """The same complete byte/audit/semantic proof for one native journal edge."""
    target_sha = child.get('source_sha256') if isinstance(child, dict) else None
    for event in (parent, child):
        if (event is None or event.get('baseline_scope') != 'remaining_work'
                or any(not isinstance(event.get(field), str) or not versions._SHA.fullmatch(event[field])
                       for field in ('source_sha256', 'previous_source_sha256'))
                or any(not isinstance(event.get(field), str)
                       for field in ('effective_from', 'approved_at'))):
            raise DateCarryProblem('lineage')
        try:
            versions._day(event['effective_from'])
            approved = dt.datetime.fromisoformat(event['approved_at'])
        except ValueError:
            raise DateCarryProblem('lineage') from None
        if approved.utcoffset() != dt.timedelta(0):
            raise DateCarryProblem('lineage')
    parent_sha = parent['source_sha256'] if parent else ''
    if (not child or not parent or child['revision'] != parent['revision']+1
            or child['previous_source_sha256'] != parent_sha
            or expected_parent_sha is not None and parent_sha != expected_parent_sha
            or target_sha == parent_sha
            or any(e.get('baseline_scope') != 'remaining_work' for e in (parent, child))):
        raise DateCarryProblem('lineage')
    folder = monitor._project_dir(project)/'baseline'/'schedule_sources'
    old_bytes, new_bytes = (_source_call(versions._read, folder/(sha+'.xlsx')) for sha in (parent_sha, target_sha))
    if versions.digest(old_bytes) != parent_sha or versions.digest(new_bytes) != target_sha:
        raise DateCarryProblem('source_digest')
    metadata, audit = _audit(new_bytes)
    if (metadata['original_upload_sha256'] != parent_sha
            or metadata['expected_active_sha256'] != parent_sha
            or type(metadata['expected_revision']) is not int
            or metadata['expected_revision'] != parent['revision']):
        raise DateCarryProblem('lineage')
    old, new = _source_call(corpus.read, old_bytes), _source_call(corpus.read, new_bytes)
    if not old or not new or old['format'] != 'corpus-gpr-v1' or new['format'] != old['format']:
        raise DateCarryProblem('source_format')
    def non_date_packages(source):
        packages = copy.deepcopy(source['packages'])
        for package in packages:
            for scope in package['scopes']:
                for field in ('start', 'finish'):
                    scope.pop(field, None)
                    scope['raw'].pop(field, None)
        return packages
    if non_date_packages(old) != non_date_packages(new):
        raise DateCarryProblem('semantics')
    before, after = _date_cells(old), _date_cells(new)
    if before.keys() != after.keys():
        raise DateCarryProblem('semantics')
    changed = {cell for cell in before if before[cell] != after[cell]}
    if not changed or changed != set(audit):
        raise DateCarryProblem('date_audit')
    for cell in changed:
        if (audit[cell] != (before[cell][0], after[cell][0]) or before[cell][1] is None
                or after[cell][1] is None or before[cell][1] == after[cell][1]):
            raise DateCarryProblem('date_audit')
    def catalog(source):
        rows = corpus.as_schedule(source)['works']
        result = {str(row.get('id') or ''): row for row in rows}
        if not rows or len(rows) > 3000 or len(result) != len(rows) or '' in result:
            raise DateCarryProblem('definitions')
        return result
    full, child_rows = catalog(old), catalog(new)
    if full.keys() != child_rows.keys():
        raise DateCarryProblem('definitions')
    for key, row in full.items():
        other = child_rows[key]
        for value, sha in ((row, parent_sha), (other, target_sha)):
            start, finish = value.get('start'), value.get('finish')
            duration = (finish-start).days+1 if start and finish else None
            if value.get('duration') != duration or value.get('source_sha256') != sha:
                raise DateCarryProblem('semantics')
        excluded = {'start', 'finish', 'duration', 'source_sha256'}
        if {k:v for k,v in row.items() if k not in excluded} != {k:v for k,v in other.items() if k not in excluded}:
            raise DateCarryProblem('semantics')
    provenance = {'kind':'approved_date_only_projection', 'from_source_sha256':parent_sha,
                  'to_source_sha256':target_sha, 'source_revision':child['revision'],
                  'source_effective_from':child['effective_from'], 'source_approved_at':child['approved_at'],
                  'parent_effective_from':parent['effective_from'], 'parent_approved_at':parent['approved_at'],
                  'changed_date_cells':sorted(changed), 'persisted':False}
    return full, child_rows, provenance


def verified_transition(project, target_sha, *, expected_parent_sha=None):
    """Strictly the current single edge; never infer a more distant parent."""
    events, revision = _journal(project, target_sha)
    return _verified_edge(project, events[revision-2] if revision >= 2 else None,
                          events[revision-1], expected_parent_sha=expected_parent_sha)


def _combined(edges):
    """Keep the single-edge wire unchanged; describe every multi-edge hop."""
    if len(edges) == 1:
        return edges[0]
    for _, _, edge in edges:
        if (versions._day(edge['parent_effective_from']) > versions._day(edge['source_effective_from'])
                or dt.datetime.fromisoformat(edge['parent_approved_at'])
                   > dt.datetime.fromisoformat(edge['source_approved_at'])):
            raise DateCarryProblem('lineage')
    first, last = edges[0][2], edges[-1][2]
    proof = dict(last, from_source_sha256=first['from_source_sha256'],
                 changed_date_cells=sorted({cell for edge in edges for cell in edge[2]['changed_date_cells']}),
                 reference_source_sha256=first['from_source_sha256'],
                 reference_effective_from=first['parent_effective_from'],
                 reference_approved_at=first['parent_approved_at'],
                 immediate_parent_source_sha256=last['from_source_sha256'],
                 lineage_steps=[copy.deepcopy(edge[2]) for edge in edges])
    return edges[0][0], edges[-1][1], proof


def _available(proof, day):
    return (versions._day(proof['parent_effective_from']) <= day
            and dt.datetime.fromisoformat(proof['parent_approved_at']).date() <= day)


def _chain(project, target_sha, *, reference_sha=None, day=None):
    # The public single-edge function stays authoritative, including typed
    # failures. Only an already-proven edge can start a longer chain.
    edge = verified_transition(project, target_sha)
    edges = [edge]
    seen = {target_sha, edge[2]['from_source_sha256']}
    events, revision = None, edge[2]['source_revision']
    if reference_sha is not None:
        events, current_revision = _journal(project, target_sha)
        if (current_revision != revision or sum(e.get('source_sha256') == reference_sha
                                               for e in events[:revision]) != 1):
            raise DateCarryProblem('lineage')
    while ((reference_sha is not None and edges[0][2]['from_source_sha256'] != reference_sha)
           or (day is not None and not _available(edges[0][2], day))):
        if len(edges) >= MAX_CHAIN_EDGES or revision <= 2:
            raise DateCarryProblem('parent_future' if day is not None else 'lineage')
        if events is None:
            events, current_revision = _journal(project, target_sha)
            if current_revision != edge[2]['source_revision']:
                raise DateCarryProblem('lineage')
        child, parent = events[revision-2], events[revision-3]
        if child.get('source_sha256') != edges[0][2]['from_source_sha256']:
            raise DateCarryProblem('lineage')
        prior = _verified_edge(project, parent, child)
        if prior[2]['from_source_sha256'] in seen:
            raise DateCarryProblem('lineage')
        seen.add(prior[2]['from_source_sha256'])
        edges.insert(0, prior)
        revision -= 1
    return _combined(edges)


def parent_facts(project, target_sha, cut):
    """Use only an eligible ancestor, with unchanged facts across every hop."""
    day = versions._day(cut)
    parent, child, provenance = _chain(project, target_sha, day=day)
    return parent, dict(provenance, kind='unchanged_parent_gpr_facts')


def project(project, profile, target_sha):
    """Project only existing choices onto the verified child catalog."""
    from developaid_schedule_readiness import CURRENT_ESTIMATE, CONFIG_FIELDS, _fingerprint
    if (profile.get('scope_kind') != CURRENT_ESTIMATE or profile.get('basis') != 'estimated_elements'
            or profile.get('full_scope_confirmed') is not False or profile.get('outside_completed_ids')
            or profile.get('full_source_sha256') != profile.get('remaining_source_sha256')):
        raise DateCarryProblem('scope')
    if set(profile)-CONFIG_FIELDS-{'remaining_source_sha256', 'full_fingerprint', 'remaining_fingerprint', 'recorded_at'}:
        raise DateCarryProblem('weights')
    full, child_rows, provenance = _chain(project, target_sha,
        reference_sha=profile['full_source_sha256'])
    if (profile.get('full_fingerprint') != _fingerprint(full)
            or profile.get('remaining_fingerprint') != _fingerprint(full)):
        raise DateCarryProblem('definitions')
    try:
        elements.validate(profile.get('element_profile'), full)
    except ValueError as exc:
        raise DateCarryProblem('weights') from exc
    # Known internal methods are cost/quantity or explicit expert shares.
    # Neither duration-derived nor unknown methods are admitted by validate.
    for weight in profile.get('weights') or []:
        if (not isinstance(weight, dict) or set(weight) != {'full_id', 'value'} or weight['full_id'] not in full
                or isinstance(weight['value'], bool) or not isinstance(weight['value'], (int, float))
                or not math.isfinite(weight['value']) or weight['value'] < 0):
            raise DateCarryProblem('weights')
    projected = copy.deepcopy(profile)
    projected.update(full_source_sha256=target_sha, remaining_source_sha256=target_sha)
    provenance['profile_decisions_unchanged'] = True
    return projected, child_rows, provenance
