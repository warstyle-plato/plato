"""Bounded prospective metadata for the existing weekly runner; never calculates.

Only hashes, enum statuses and dates are recorded. Input headers survive resume;
missing or concurrently changing evidence is a gap, never a historical success.
"""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import time

import developaid_cached_source_audit as audit
from krt_status import model_exclusion, project_kind, with_last_known_status

SCHEMA = 1
MAX_SITES = 4000
MAX_TRACE_BYTES = 4 * 1024 * 1024
FOLDER = '.weekly-trace'
HASH = re.compile(r'[a-f0-9]{64}\Z')
ID = re.compile(r'[a-zA-Z0-9:_-]{1,180}\Z')
VERSION = re.compile(r'[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\Z')
RATING_VERSION = re.compile(r'issue-[0-9]{1,8}-krt-rating-4x100-v[0-9]{1,4}\Z')
KINDS = {'planned', 'running', 'draft', 'unparsed'}
POLICY = 'native_unique_first_conflicts_excluded'
REASONS = {'running', 'status_conflict', 'unknown_after_running'}
GAPS = {'source_missing', 'source_changed', 'source_stale', 'runtime_unknown',
        'source_incomplete', 'source_schema_unknown',
        'source_input_binding_missing',
        'source_identity_unknown', 'input_revision_changed', 'observation_missing',
        'financial_state_changed_or_concurrent_writer', 'effective_status_changed',
        'visit_repeated_with_different_evidence', 'excluded_visits_missing',
        'interrupted', 'trace_limit', 'trace_unavailable'}


class TraceProblem(ValueError):
    def __init__(self, code='trace_unavailable'):
        self.code = code
        super().__init__(code)


def _digest(value):
    return hashlib.sha256(_encode(value)).hexdigest()


def _encode(value):
    try:
        return json.dumps(value, ensure_ascii=True, allow_nan=False,
                          separators=(',', ':'), sort_keys=True).encode()
    except (ValueError, TypeError, RecursionError):
        raise TraceProblem() from None


def _stamp(value):
    # JSON integers can be arbitrarily large. Bound them without converting
    # to float: math.isfinite(10**1000) raises OverflowError before validation.
    if type(value) is int:
        return value if 0 <= value <= 4102444800 else None
    if type(value) is float:
        return value if math.isfinite(value) and 0 <= value <= 4102444800 else None
    return None


def _period(value):
    if _stamp(value) is None or value < 946684800 or int(value) != value:
        raise TraceProblem()
    value = int(value)
    if not 946684800 <= value <= 4102444800:
        raise TraceProblem()
    return value


def _site(project):
    slug = project.get('slug')
    if not isinstance(slug, str) or not ID.fullmatch(slug):
        raise TraceProblem('source_identity_unknown')
    status = project.get('status')
    excluded = model_exclusion(project) is not None
    reason = ('status_conflict' if project.get('model_status_conflict') else
              'running' if project_kind(project) == 'running' else 'unknown_after_running') if excluded else None
    return {'site_id_sha256': _digest(slug), 'status_sha256': _digest(status),
            'source_kind_sha256': _digest(project.get('source_kind')),
            'status_kind': project_kind(project),
            'last_known_status_kind': (project.get('last_known_status_kind')
                                       if project.get('last_known_status_kind') in KINDS else None),
            'model_status_conflict': bool(project.get('model_status_conflict')),
            'excluded': excluded, 'exclusion_reason': reason}


def _validate(value):
    """Trace output cannot become an arbitrary text/field export from disk."""
    def digest(one, *, nullable=False):
        return one is None and nullable or isinstance(one, str) and HASH.fullmatch(one)

    def stamp(one, *, nullable=False):
        return one is None and nullable or _stamp(one) is not None and one <= 4102444800

    def version(one, grammar):
        return one is None or isinstance(one, str) and grammar.fullmatch(one)

    if (not isinstance(value, dict) or set(value) !=
            {'schema', 'header', 'header_sha256', 'visits', 'gaps', 'completed', 'finished_at'}
            or type(value.get('schema')) is not int or value['schema'] != SCHEMA
            or not isinstance(value.get('header'), dict)
            or _digest(value['header']) != value.get('header_sha256')
            or not isinstance(value.get('visits'), dict) or len(value['visits']) > MAX_SITES):
        raise TraceProblem()
    header = value['header']
    if (set(header) != {'period', 'created_at', 'runtime_commit', 'runtime_version',
                       'source_revisions', 'cohort', 'selection'} or not isinstance(header['cohort'], list)
            or len(header['cohort']) > MAX_SITES
            or type(value['completed']) is not bool or not isinstance(value['gaps'], list)
            or len(value['gaps']) > len(GAPS)
            or any(not isinstance(gap, str) or gap not in GAPS for gap in value['gaps'])
            or not stamp(header['created_at']) or not stamp(value['finished_at'], nullable=True)
            or not version(header['runtime_version'], VERSION)
            or header['runtime_commit'] is not None and not
                (isinstance(header['runtime_commit'], str) and re.fullmatch('[a-f0-9]{40}', header['runtime_commit']))):
        raise TraceProblem()
    _period(header['period'])
    selection = header['selection']
    if (not isinstance(selection, dict) or set(selection) !=
            {'raw_count', 'unique_count', 'raw_statuses_sha256', 'policy'}
            or type(selection['raw_count']) is not int or type(selection['unique_count']) is not int
            or not 0 <= selection['unique_count'] <= selection['raw_count'] <= MAX_SITES
            or selection['unique_count'] != len(header['cohort'])
            or not digest(selection['raw_statuses_sha256']) or selection['policy'] != POLICY):
        raise TraceProblem()
    site_keys = {'site_id_sha256', 'status_sha256', 'source_kind_sha256', 'status_kind',
                 'last_known_status_kind', 'model_status_conflict', 'excluded', 'exclusion_reason'}
    def valid_site(site):
        if (not isinstance(site, dict) or set(site) != site_keys
                or not digest(site['site_id_sha256']) or not digest(site['status_sha256'])
                or not digest(site['source_kind_sha256'])
                or not isinstance(site['status_kind'], str) or site['status_kind'] not in KINDS
                or site['last_known_status_kind'] is not None and
                   (not isinstance(site['last_known_status_kind'], str) or site['last_known_status_kind'] not in KINDS)
                or type(site['model_status_conflict']) is not bool or type(site['excluded']) is not bool
                or (site['exclusion_reason'] is not None and
                    (not isinstance(site['exclusion_reason'], str) or site['exclusion_reason'] not in REASONS))
                or site['excluded'] != (site['exclusion_reason'] is not None)):
            raise TraceProblem()
    for site in header['cohort']:
        valid_site(site)
    if len({site['site_id_sha256'] for site in header['cohort']}) != len(header['cohort']):
        raise TraceProblem('source_identity_unknown')
    if (not isinstance(header['source_revisions'], dict)
            or set(header['source_revisions']) != {'catalogue', 'decisions', 'early_code_sha256'}):
        raise TraceProblem()
    revisions = header['source_revisions']
    if not digest(revisions['early_code_sha256']):
        raise TraceProblem()
    for role in ('catalogue', 'decisions'):
        source = revisions[role]
        if source is not None and (not isinstance(source, dict)
                or set(source) != {'sha256', 'bytes', 'retrieved_at', 'complete'}
                or not digest(source['sha256']) or type(source['bytes']) is not int
                or not 0 <= source['bytes'] <= audit.MAX_FILE_BYTES
                or not stamp(source['retrieved_at'], nullable=True)
                or source['complete'] is not None and type(source['complete']) is not bool):
            raise TraceProblem()
    observation_keys = {'state', 'row_present', 'report_present', 'report_sha256',
                        'financial_row_sha256', 'rating_sha256', 'model_at', 'rating_at',
                        'model_version', 'rating_version', 'rating_inner_at'}
    for site_id, visit in value['visits'].items():
        if (not isinstance(visit, dict) or set(visit) != site_keys | {'before', 'after', 'unchanged', 'visited_at'}
                or visit['site_id_sha256'] != site_id
                or visit['unchanged'] is not None and type(visit['unchanged']) is not bool
                or not stamp(visit['visited_at'])):
            raise TraceProblem()
        valid_site({key: visit[key] for key in site_keys})
        for side in ('before', 'after'):
            observation = visit[side]
            if (not isinstance(observation, dict) or not
                    (set(observation) == {'state'} and observation['state'] == 'unavailable'
                     or set(observation) == observation_keys and observation['state'] == 'read')):
                raise TraceProblem()
            if observation['state'] == 'read' and (
                    any(type(observation[key]) is not bool for key in ('row_present', 'report_present'))
                    or any(not digest(observation[key], nullable=True) for key in
                           ('report_sha256', 'financial_row_sha256', 'rating_sha256'))
                    or any(not stamp(observation[key], nullable=True) for key in
                           ('model_at', 'rating_at', 'rating_inner_at'))
                    or not version(observation['model_version'], VERSION)
                    or not version(observation['rating_version'], RATING_VERSION)):
                raise TraceProblem()
    if len(_encode(value)) > MAX_TRACE_BYTES:
        raise TraceProblem('trace_limit')
    return value


@contextlib.contextmanager
def _store(root, *, write):
    reader = audit.Reader(Path(root).absolute())
    folder = lock = None
    try:
        if write:
            try:
                os.mkdir(FOLDER, 0o700, dir_fd=reader.rootfd)
            except FileExistsError:
                pass
        try:
            folder = os.open(FOLDER, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                             dir_fd=reader.rootfd)
        except FileNotFoundError:
            yield None
            return
        flags = os.O_RDWR | os.O_CREAT if write else os.O_RDONLY
        lock = os.open('.lock', flags | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=folder)
        info = os.fstat(lock)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise TraceProblem()
        # The audit must never wait on a stuck reader/writer in the model loop.
        fcntl.flock(lock, (fcntl.LOCK_EX if write else fcntl.LOCK_SH) | fcntl.LOCK_NB)
        pinned = os.fstat(folder)
        current = os.stat(FOLDER, dir_fd=reader.rootfd, follow_symlinks=False)
        if (pinned.st_dev, pinned.st_ino) != (current.st_dev, current.st_ino):
            raise TraceProblem('source_changed')
        reader.check_identity()
        yield folder
        current = os.stat(FOLDER, dir_fd=reader.rootfd, follow_symlinks=False)
        if (pinned.st_dev, pinned.st_ino) != (current.st_dev, current.st_ino):
            raise TraceProblem('source_changed')
        reader.check_identity()
    except (OSError, audit.AuditError):
        raise TraceProblem() from None
    finally:
        if lock is not None:
            os.close(lock)
        if folder is not None:
            os.close(folder)
        reader.close()


def _read(folder, period):
    if folder is None:
        return None
    try:
        fd = os.open(str(_period(period))+'.json', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=folder)
    except FileNotFoundError:
        return None
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > MAX_TRACE_BYTES:
            raise TraceProblem('trace_limit')
        raw = bytearray()
        while len(raw) <= MAX_TRACE_BYTES:
            part = os.read(fd, min(65536, MAX_TRACE_BYTES+1-len(raw)))
            if not part:
                break
            raw.extend(part)
        after = os.fstat(fd)
        if ((before.st_ino, before.st_size, before.st_mtime_ns) !=
                (after.st_ino, after.st_size, after.st_mtime_ns)):
            raise TraceProblem('source_changed')
        if len(raw) > MAX_TRACE_BYTES:
            raise TraceProblem('trace_limit')
        try:
            value = _validate(audit._json(bytes(raw)))
        except audit.AuditError:
            raise TraceProblem() from None
        if value['header'].get('period') != _period(period):
            raise TraceProblem()
        return value
    finally:
        os.close(fd)


def _write(folder, period, value):
    raw = _encode(_validate(value))
    temporary = '.tmp-'+os.urandom(16).hex()
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=folder)
        try:
            with os.fdopen(fd, 'wb') as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, str(_period(period))+'.json', src_dir_fd=folder, dst_dir_fd=folder)
            os.fsync(folder)
        finally:
            try:
                os.unlink(temporary, dir_fd=folder)
            except FileNotFoundError:
                pass
    except OSError:
        raise TraceProblem() from None


def read(root, period):
    with _store(root, write=False) as folder:
        return _read(folder, period)


def _source_state(root):
    reader = audit.Reader(Path(root).absolute())
    try:
        result, first, gaps = {}, {}, []
        for role in ('catalogue', 'decisions'):
            found = reader.read(role+'.json')
            first[role] = found
            if found is None:
                result[role] = None
                gaps.append('source_missing')
            else:
                data = audit._json(found[0])
                result[role] = {'sha256': found[1]['sha256'], 'bytes': found[1]['bytes'],
                                'retrieved_at': _stamp(data.get('retrieved_at')),
                                'complete': data.get('complete') if type(data.get('complete')) is bool else None}
                if result[role]['complete'] is not True or data.get('stale') is True:
                    gaps.append('source_incomplete')
                at = result[role]['retrieved_at']
                if at is None or time.time()-at > 86400 or at > time.time():
                    gaps.append('source_stale')
        for role in first:
            if first[role] != reader.read(role+'.json'):
                raise TraceProblem('source_changed')
        reader.check_identity()
        early = Path(__file__).parent / 'auction_search' / 'krt_early_projects.py'
        fd = os.open(early, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size > 256*1024:
                raise TraceProblem('trace_limit')
            raw = os.read(fd, 256*1024+1)
            after = os.fstat(fd)
            if (info.st_ino, info.st_size, info.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
                raise TraceProblem('source_changed')
            result['early_code_sha256'] = hashlib.sha256(raw).hexdigest()
        finally:
            os.close(fd)
        return result, gaps
    except (OSError, audit.AuditError, TypeError, AttributeError):
        raise TraceProblem() from None
    finally:
        reader.close()


def source_revision(root):
    """A bounded witness before the existing native cohort is assembled."""
    return _source_state(root)


def begin(root, period, projects, runtime, raw_projects=None, source_before=None):
    raw_projects = projects if raw_projects is None else raw_projects
    if len(projects) > MAX_SITES or len(raw_projects) > MAX_SITES:
        raise TraceProblem('trace_limit')
    revisions, gaps = _source_state(root)
    if source_before is None:
        gaps.append('source_input_binding_missing')
    elif source_before[0] != revisions:
        gaps.append('input_revision_changed')
    else:
        gaps.extend(source_before[1])
    cohort = [_site(p) for p in projects]
    selection = {'raw_count': len(raw_projects), 'unique_count': len(projects),
                 'raw_statuses_sha256': _digest([_site(p) for p in raw_projects]), 'policy': POLICY}
    commit, version = runtime.get('commit'), runtime.get('version')
    commit = commit if isinstance(commit, str) and re.fullmatch('[a-f0-9]{40}', commit) else None
    version = version if isinstance(version, str) and re.fullmatch(r'[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}', version) else None
    if commit is None or version is None:
        gaps.append('runtime_unknown')
    with _store(root, write=True) as folder:
        previous = _read(folder, period)
        if previous is not None:
            changed = False
            if (previous['header']['cohort'] != cohort or previous['header']['selection'] != selection
                    or previous['header']['source_revisions'] != revisions
                    or previous['header']['runtime_commit'] != commit or previous['header']['runtime_version'] != version):
                previous['gaps'] = sorted(set(previous['gaps']) | {'input_revision_changed'})
                changed = True
            merged_gaps = sorted(set(previous['gaps']) | set(gaps))
            if previous['gaps'] != merged_gaps or previous['completed'] or previous['finished_at'] is not None:
                previous.update(gaps=merged_gaps, completed=False, finished_at=None)
                changed = True
            if changed:
                _write(folder, period, previous)
            return
        header = {'period': _period(period), 'created_at': int(time.time()),
                  'runtime_commit': commit, 'runtime_version': version,
                  'source_revisions': revisions, 'cohort': cohort, 'selection': selection}
        _write(folder, period, {'schema': SCHEMA, 'header': header, 'header_sha256': _digest(header),
                                'visits': {}, 'gaps': sorted(set(gaps)), 'completed': False, 'finished_at': None})


def observe(root, slug, mutable_fields=()):
    if not isinstance(slug, str) or not ID.fullmatch(slug):
        raise TraceProblem('source_identity_unknown')
    reader = audit.Reader(Path(root).absolute())
    name = re.sub(r'[^a-z0-9_-]+', '-', slug.strip().lower())[:120]+'.json'
    try:
        first = {role: reader.read(role) for role in ('ranking.json', 'reports/'+name)}
        ranking = audit._json(first['ranking.json'][0]) if first['ranking.json'] else None
        if ranking is not None and (not isinstance(ranking, dict) or ranking.get('schema_version') != 1):
            raise TraceProblem('source_schema_unknown')
        rows = ranking.get('rows') if ranking else None
        if ranking is not None and (not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows)):
            raise TraceProblem('source_schema_unknown')
        matches = [r for r in rows if r.get('slug') == slug] if rows is not None else []
        if len(matches) > 1:
            raise TraceProblem('source_identity_unknown')
        row = matches[0] if matches else None
        report = first['reports/'+name]
        if report is not None:
            data = audit._json(report[0])
            if not isinstance(data, dict) or data.get('schema_version') != 1:
                raise TraceProblem('source_schema_unknown')
            if data.get('slug') != slug:
                raise TraceProblem('source_identity_unknown')
        financial = ({k:v for k,v in row.items() if k not in {*mutable_fields, 'slug'}}
                     if row is not None else {})
        rating = row.get('investment_rating') if row is not None else None
        model_version = row.get('engine_version') if row is not None else None
        rating_version = rating.get('version') if isinstance(rating, dict) else None
        result = {'state': 'read', 'row_present': row is not None, 'report_present': report is not None,
                  'report_sha256': report[1]['sha256'] if report else None,
                  'financial_row_sha256': _digest(financial) if financial else None,
                  'rating_sha256': _digest(row['investment_rating']) if row is not None and 'investment_rating' in row else None,
                  'model_at': _stamp(row.get('computed_at')) if row is not None else None,
                  'rating_at': _stamp(row.get('investment_rating_computed_at')) if row is not None else None,
                  'rating_inner_at': _stamp(rating.get('computed_at')) if isinstance(rating, dict) else None,
                  'model_version': model_version if isinstance(model_version, str) and VERSION.fullmatch(model_version) else None,
                  'rating_version': rating_version if isinstance(rating_version, str) and RATING_VERSION.fullmatch(rating_version) else None}
        for role, before in first.items():
            if before != reader.read(role):
                raise TraceProblem('source_changed')
        reader.check_identity()
        return result
    except (OSError, audit.AuditError, TypeError, AttributeError):
        raise TraceProblem() from None
    finally:
        reader.close()


def visit(root, period, project, before, after):
    site = _site(project)
    if not site['excluded']:
        return
    with _store(root, write=True) as folder:
        value = _read(folder, period)
        if value is None:
            raise TraceProblem()
        expected = next((r for r in value['header']['cohort'] if r['site_id_sha256'] == site['site_id_sha256']), None)
        gaps = set(value['gaps'])
        if expected != site:
            gaps.add('effective_status_changed')
        known = isinstance(before, dict) and isinstance(after, dict) and before.get('state') == after.get('state') == 'read'
        before = before if isinstance(before, dict) else {'state': 'unavailable'}
        after = after if isinstance(after, dict) else {'state': 'unavailable'}
        fields = ('report_sha256', 'financial_row_sha256', 'rating_sha256', 'model_at', 'rating_at',
                  'rating_inner_at', 'model_version', 'rating_version', 'report_present')
        unchanged = all(before.get(k) == after.get(k) for k in fields) if known else None
        if not known:
            gaps.add('observation_missing')
        elif not unchanged:
            gaps.add('financial_state_changed_or_concurrent_writer')
        record = {**site, 'before': before, 'after': after, 'unchanged': unchanged,
                  'visited_at': int(time.time())}
        previous = value['visits'].get(site['site_id_sha256'])
        if previous is not None:
            if {k:v for k,v in previous.items() if k != 'visited_at'} != {k:v for k,v in record.items() if k != 'visited_at'}:
                gaps.add('visit_repeated_with_different_evidence')
        else:
            value['visits'][site['site_id_sha256']] = record
        value['gaps'] = sorted(gaps)
        _write(folder, period, value)


def end(root, period, completed):
    revisions, source_gaps = _source_state(root)
    with _store(root, write=True) as folder:
        value = _read(folder, period)
        if value is None:
            raise TraceProblem()
        expected = {r['site_id_sha256'] for r in value['header']['cohort'] if r['excluded']}
        gaps = set(value['gaps'])
        gaps.update(source_gaps)
        if revisions != value['header']['source_revisions']:
            gaps.add('input_revision_changed')
        if expected - set(value['visits']):
            gaps.add('excluded_visits_missing')
        if not completed:
            gaps.add('interrupted')
        value.update(completed=bool(completed), finished_at=int(time.time()), gaps=sorted(gaps))
        _write(folder, period, value)
