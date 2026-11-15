"""Passive metadata for an already occurring catalogue walk, never a collector.

No body, URL, exception text, credentials or environment is retained here.
Successful lower transport phases are deliberately not inferred from HTTPS.
"""
from __future__ import annotations

import copy
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import errno
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import secrets
import socket
import ssl
import stat
import sys
import time
from types import ModuleType
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit


LIMIT = 96 * 1024
VIEW_LIMIT = 128 * 1024
I32 = 2**31 - 1
I64 = 2**63 - 1
NAME = 'catalogue_acquisition.json'
SCHEMA = 'krt-operational-acquisition-v1'
ENVELOPE = 'krt-operational-acquisition-envelope-v1'
VIEW = 'krt-operational-acquisition-view-v1'
SCOPE = 'current_generation_and_latest_attempt_not_an_archive'
_CURRENT = ContextVar('krt_catalogue_fetch_observation', default=None)
_SHA = re.compile(r'[0-9a-f]{64}\Z')
_COMMIT = re.compile(r'[0-9a-f]{40}\Z')
_VERSION = re.compile(r'[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,5}\Z')
_PHASES = {'dns': {'not_observed', 'failed'}, 'tcp': {'not_observed', 'failed'},
    'tls': {'not_observed', 'failed'}, 'HTTP': {'not_observed', 'response_observed', 'failed'},
    'body': {'not_observed', 'returned_complete', 'failed'},
    'parse': {'not_observed', 'complete', 'zero_rows', 'failed'}}
_BOUNDARIES = {'tls_context_setup', 'open_response', 'body', 'decode', 'parse', 'collector', 'diagnostic_IO'}
_KINDS = {'dns_resolution', 'tcp_refused', 'tcp_unreachable', 'tls_verification', 'tls_error',
    'HTTP_status', 'timeout', 'incomplete_body', 'decode_error', 'parse_error', 'other', 'unknown'}
_EVIDENCE = {'typed_exception', 'returned_response', 'direct_boundary', 'not_observed'}
_FAILURE_KEYS = {'fetch_ordinal', 'attempt_ordinal', 'boundary', 'kind', 'evidence',
    'endpoint_attribution', 'elapsed_ms'}
_RESULT_KEYS = {'acquisition', 'direct_rows_added', 'renderer_rows_added', 'collector_returned_rows',
    'completion_basis', 'catalogue_written', 'prior_catalogue_retained', 'source_updated_at',
    'historical_period_proven', 'production_acceptance'}
_RECEIPT_KEYS = {'schema', 'scope', 'state', 'started_at_utc', 'finished_at_utc',
    'acquisition_runtime', 'producer_sha256', 'fetches_seen', 'HTTP_attempts_seen',
    'metadata_chain_sha256', 'page_receipts', 'failure_samples', 'last_failure_phases',
    'detail_truncated', 'details_omitted', 'numeric_overflow', 'walk_result'}
_BINDING_KEYS = {'state', 'written_payload_sha256', 'written_bytes', 'inode', 'mtime_ns',
    'acquisition_receipt_sha256'}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def _now():
    return datetime.now(timezone.utc).isoformat()


def runtime(loaded=None):
    """Only existing module dictionaries; no app imports or configuration reads."""
    modules = loaded if loaded is not None else sys.modules
    for name in ('developaid_core', 'main_legacy', 'main'):
        module = modules.get(name)
        if not isinstance(module, ModuleType):
            continue
        values = vars(module)
        core = values.get('core')
        if isinstance(core, ModuleType):
            values = vars(core)
        commit, version = values.get('COMMIT'), values.get('VERSION')
        commit = commit if type(commit) is str and _COMMIT.fullmatch(commit) else None
        version = version if type(version) is str and _VERSION.fullmatch(version) else None
        if commit is not None or version is not None:
            return {'commit': commit, 'version': version}
    return {'commit': None, 'version': None}


def _producers():
    result = {}
    for key, name in (('http', 'http.py'), ('registry', 'krt_registry.py'),
                      ('observation', 'krt_catalogue_observation.py')):
        result[key] = None
        try:
            fd = os.open(Path(__file__).parent / name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, 'rb') as source:
                info = os.fstat(source.fileno())
                if stat.S_ISREG(info.st_mode) and info.st_size <= 1024 * 1024:
                    body = source.read(1024 * 1024)
                    if len(body) == info.st_size:
                        result[key] = hashlib.sha256(body).hexdigest()
        except (OSError, ValueError):
            pass
    return result


def _phases():
    return {key: 'not_observed' for key in _PHASES}


def _origin(value):
    if type(value) is not str or len(value) > 8192:
        return 'unknown'
    try:
        parts = urlsplit(value)
        if not parts.scheme or not parts.hostname:
            return 'unknown'
        if parts.scheme == 'https' and parts.port in (None, 443) and not parts.username and not parts.password:
            if parts.hostname in {'api.krt.mos.ru', 'krt.mos.ru'}:
                return 'official_https'
            if parts.hostname == 'r.jina.ai':
                return 'renderer_https'
        return 'other'
    except (ValueError, TypeError):
        return 'unknown'


def current_fetch():
    return _CURRENT.get()


def note(target, method, *args):
    """Diagnostic faults must neither mask nor create a business exception."""
    try:
        if target is not None:
            getattr(target, method)(*args)
    except Exception:
        pass


def _typed(exc):
    for _ in range(4):
        if isinstance(exc, HTTPError): return 'HTTP_status', exc
        if isinstance(exc, ssl.SSLCertVerificationError): return 'tls_verification', exc
        if isinstance(exc, ssl.SSLError): return 'tls_error', exc
        if isinstance(exc, socket.gaierror): return 'dns_resolution', exc
        if isinstance(exc, ConnectionRefusedError): return 'tcp_refused', exc
        if isinstance(exc, OSError) and exc.errno in {errno.ENETUNREACH, errno.EHOSTUNREACH}:
            return 'tcp_unreachable', exc
        if isinstance(exc, (TimeoutError, socket.timeout)): return 'timeout', exc
        if isinstance(exc, http.client.IncompleteRead): return 'incomplete_body', exc
        if isinstance(exc, UnicodeError): return 'decode_error', exc
        next_exc = exc.reason if isinstance(exc, URLError) else getattr(exc, '__cause__', None)
        if not isinstance(next_exc, BaseException) or next_exc is exc:
            break
        exc = next_exc
    return 'unknown', None


class Fetch:
    def __init__(self, walk, source, ordinal):
        self.walk, self.source, self.ordinal = walk, source, ordinal
        self.attempts = 0
        self.events = False
        self.status = None
        self.origin = 'unknown'
        self.length = self.digest = None
        self.complete = False
        self.decode = self.parse = 'not_observed'
        self.rows = self.added = None
        self.phases = _phases()
        self.last_failure = None
        self.failure_chain = hashlib.sha256()
        self.failure_events = 0
        self.boundary = 'collector'
        self.attempt = None
        self.started = time.monotonic()

    def context_start(self):
        self.events = True
        self.walk.http_observed = True
        self.started = time.monotonic()

    def attempt_start(self, ordinal):
        self.events = True
        self.walk.http_observed = True
        self.attempts += 1
        self.attempt = self.walk.number(self.attempts)
        self.walk.attempts += 1
        self.status, self.origin = None, 'unknown'
        self.length = self.digest = None
        self.complete = False
        self.phases = _phases()
        self.started = time.monotonic()

    def response(self, response):
        # The existing returned object's metadata only, never an extra read.
        self.phases['HTTP'] = 'response_observed'
        try:
            code = response.status
            self.status = code if type(code) is int and 100 <= code <= 599 else None
        except Exception:
            self.status = None
        try:
            self.origin = _origin(response.geturl())
        except Exception:
            self.origin = 'unknown'
        if self.status is not None and not 200 <= self.status < 400:
            self._failure('HTTP_status', 'open_response', 'returned_response')

    def body(self, body):
        if type(body) is bytes and len(body) <= I64:
            self.length, self.digest = len(body), hashlib.sha256(body).hexdigest()
            self.complete = True
            self.phases['body'] = 'returned_complete'

    def stage(self, boundary):
        self.boundary = boundary

    def decoded(self):
        self.decode = 'complete'

    def parsed(self, rows):
        self.rows = self.walk.number(rows)
        self.parse = 'zero_rows' if rows == 0 else 'complete'
        self.phases['parse'] = self.parse
        if rows == 0:
            self.added = 0
        self.boundary = 'collector'

    def contributed(self, rows):
        self.added = self.walk.number(rows)
        self.walk.added[self.source] += rows

    def _failure(self, kind, boundary, evidence):
        sample = {'fetch_ordinal': self.walk.number(self.walk.fetches), 'attempt_ordinal': self.attempt,
            'boundary': boundary, 'kind': kind, 'evidence': evidence,
            'endpoint_attribution': 'origin_or_proxy_unknown',
            'elapsed_ms': self.walk.number(max(0, int((time.monotonic() - self.started) * 1000)))}
        if sample['fetch_ordinal'] is not None:
            self.last_failure = sample
            self.failure_events += 1
            self.failure_chain.update(canonical({'failure': sample, 'phases': dict(self.phases)}) + b'\n')
            self.walk.failure(sample, self.phases)

    def failure(self, exc, boundary):
        kind, typed = _typed(exc)
        if boundary == 'body' and not self.complete:
            self.phases['body'] = 'failed'
            self.length = self.digest = None
            self.complete = False
        if kind in {'dns_resolution', 'tcp_refused', 'tcp_unreachable'} and self.phases['HTTP'] == 'not_observed':
            self.phases['dns' if kind == 'dns_resolution' else 'tcp'] = 'failed'
        elif kind in {'dns_resolution', 'tcp_refused', 'tcp_unreachable'}:
            kind, typed = 'unknown', None
        if kind in {'tls_verification', 'tls_error'}:
            self.phases['tls'] = 'failed'
        if kind == 'HTTP_status' and typed is not None:
            code = typed.code
            self.status = code if type(code) is int and 100 <= code <= 599 else None
            self.phases['HTTP'] = 'response_observed'
            try: self.origin = _origin(typed.geturl())
            except Exception: self.origin = 'unknown'
        self._failure(kind, boundary, 'typed_exception' if typed is not None else 'not_observed')

    def escaped(self, exc):
        self.walk.escaped_exception = exc
        if self.boundary == 'decode':
            self.decode = 'failed'
            self._failure('decode_error', 'decode', 'direct_boundary')
        elif self.boundary == 'parse':
            self.parse = 'failed'
            self.phases['parse'] = 'failed'
            self._failure('parse_error', 'parse', 'direct_boundary')
        elif self.last_failure is None:
            # A custom fetch gives no observations of its private transport.
            self._failure('unknown', 'collector', 'not_observed')

    def finish(self):
        attempts = self.walk.number(self.attempts) if self.events else None
        page = [self.source, self.walk.number(self.ordinal), attempts, self.status, self.origin,
            self.length, self.digest, self.complete, self.decode, self.parse, self.rows, self.added]
        if page[1] is None:
            self.walk.omit()
            # Explicit overflow gap, not a fabricated ordinal or empty body.
            chained_page = None
        else:
            chained_page = page
            if len(self.walk.pages) < 200:
                self.walk.pages.append(page)
            else:
                self.walk.omit()
        self.walk.chain.update(canonical({'page': chained_page,
            'failure_chain_sha256': self.failure_chain.hexdigest(),
            'failure_events': self.walk.number(self.failure_events)}) + b'\n')


@contextmanager
def fetch_scope(walk, source, ordinal):
    fetch = None
    token = None
    try:
        token = _CURRENT.set(None)
        if walk is not None:
            walk.fetches += 1
            fetch = Fetch(walk, source, ordinal)
            _CURRENT.set(fetch)
    except Exception:
        fetch = None
    try:
        yield fetch
    except BaseException as exc:
        note(fetch, 'escaped', exc)
        raise
    finally:
        if token is not None:
            _CURRENT.reset(token)
        note(fetch, 'finish')


def _binding(state='unbound'):
    return {'state': state, 'written_payload_sha256': None, 'written_bytes': None,
        'inode': None, 'mtime_ns': None, 'acquisition_receipt_sha256': None}


class Walk:
    def __init__(self, catalogue, prior_exists):
        self.catalogue = Path(catalogue)
        self.started = _now()
        self.identity, self.producers = runtime(), _producers()
        self.fetches = self.attempts = self.omitted = 0
        self.http_observed = self.overflow = self.truncated = False
        self.pages, self.failures = [], []
        self.chain = hashlib.sha256()
        self.added = {'official': 0, 'renderer': 0}
        self.returned_rows = None
        self.basis = 'not_observed'
        self.written = False
        self.prior_exists = prior_exists
        self.saved = None
        self.escaped_exception = None
        self.last_failure = {'phases': _phases(), 'failure': None}
        previous = read_view(self.catalogue.parent)
        diagnostic = previous['diagnostic']
        if diagnostic and previous['current_catalogue_binding_check'] == 'stat_identity_matches':
            self.current = diagnostic['current_catalogue_acquisition']
            self.binding = dict(diagnostic['current_catalogue_binding'])
            self.binding['state'] = 'retained_prior_known'
        else:
            self.current = None
            self.binding = _binding('prior_unknown' if prior_exists else 'unbound')

    def number(self, value):
        if type(value) is int and 0 <= value <= I32:
            return value
        self.overflow = self.truncated = True
        return None

    def omit(self):
        self.omitted += 1
        self.truncated = True

    def failure(self, sample, phases):
        self.last_failure = {'phases': dict(phases), 'failure': sample}
        if len(self.failures) < 8:
            self.failures.append(sample)
        else:
            self.omit()

    def wrote(self, saved):
        self.written = True
        self.saved = dict(saved)

    def returned(self, count, basis):
        self.returned_rows = self.number(count)
        self.basis = basis

    def receipt(self, finished):
        direct, renderer = (self.number(self.added[key]) for key in ('official', 'renderer'))
        fetches, attempts, omitted = self.number(self.fetches), self.number(self.attempts), self.number(self.omitted)
        acquisition = ('unknown' if self.overflow else 'mixed' if direct and renderer else
            'official_only' if direct else 'renderer_only' if renderer else 'none')
        if self.overflow:
            fetches = attempts = omitted = direct = renderer = None
        return {'schema': SCHEMA, 'scope': 'one_walk_not_global_process_state',
            'state': 'finished' if finished else 'started', 'started_at_utc': self.started,
            'finished_at_utc': _now() if finished else None,
            'acquisition_runtime': self.identity, 'producer_sha256': self.producers,
            'fetches_seen': fetches, 'HTTP_attempts_seen': attempts if self.http_observed else None,
            'metadata_chain_sha256': self.chain.hexdigest(), 'page_receipts': copy.deepcopy(self.pages),
            'failure_samples': copy.deepcopy(self.failures), 'last_failure_phases': copy.deepcopy(self.last_failure),
            'detail_truncated': self.truncated, 'details_omitted': omitted, 'numeric_overflow': self.overflow,
            'walk_result': {'acquisition': acquisition, 'direct_rows_added': direct, 'renderer_rows_added': renderer,
                'collector_returned_rows': None if self.overflow else self.returned_rows,
                'completion_basis': self.basis, 'catalogue_written': self.written,
                'prior_catalogue_retained': bool(finished and self.prior_exists and not self.written),
                'source_updated_at': None, 'historical_period_proven': False, 'production_acceptance': False}}

    def persist(self, finished=False):
        receipt = self.receipt(finished)
        current, binding = self.current, dict(self.binding)
        if finished and self.written:
            current = copy.deepcopy(receipt)
            saved = self.saved or {}
            binding = _binding('written_by_this_walk')
            for key in ('written_payload_sha256', 'written_bytes', 'inode', 'mtime_ns'):
                binding[key] = saved.get(key)
        envelope = {'schema': ENVELOPE, 'scope': SCOPE, 'current_catalogue_acquisition': current,
            'latest_attempt': receipt, 'current_catalogue_binding': binding}
        if not write_envelope(self.catalogue.parent, envelope):
            self.failure({'fetch_ordinal': min(self.fetches, I32), 'attempt_ordinal': None,
                'boundary': 'diagnostic_IO', 'kind': 'unknown', 'evidence': 'not_observed',
                'endpoint_attribution': 'origin_or_proxy_unknown', 'elapsed_ms': None}, _phases())

    def finish(self, exc=None):
        unseen = exc is not None and exc is not self.escaped_exception
        self.escaped_exception = None
        if unseen:
            self.failure({'fetch_ordinal': min(self.fetches, I32), 'attempt_ordinal': None,
                'boundary': 'collector', 'kind': 'unknown', 'evidence': 'not_observed',
                'endpoint_attribution': 'origin_or_proxy_unknown', 'elapsed_ms': None}, _phases())
        if exc is not None:
            self.basis = 'loop_limit_or_partial'
        elif self.basis == 'not_observed':
            self.basis = 'prior_cache_retained' if self.prior_exists and not self.written else 'loop_limit_or_partial'
        self.persist(True)


def start(catalogue, prior_exists):
    try:
        walk = Walk(catalogue, prior_exists)
        note(walk, 'persist')
        return walk
    except Exception:
        return None


def _object(value, keys):
    return type(value) is dict and set(value) == set(keys)


def _number(value, maximum=I32, minimum=0, nullable=True):
    return (value is None and nullable) or (type(value) is int and minimum <= value <= maximum)


def _sha(value, nullable=True):
    return (value is None and nullable) or (type(value) is str and bool(_SHA.fullmatch(value)))


def _timestamp(value, nullable=False):
    if value is None: return nullable
    if type(value) is not str or len(value) > 40: return False
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.utcoffset() == timezone.utc.utcoffset(None) and value.endswith('+00:00')
    except ValueError:
        return False


def _runtime(value):
    return (_object(value, {'commit', 'version'})
        and (value['commit'] is None or type(value['commit']) is str and bool(_COMMIT.fullmatch(value['commit'])))
        and (value['version'] is None or type(value['version']) is str and bool(_VERSION.fullmatch(value['version']))))


def _failure(value):
    return (_object(value, _FAILURE_KEYS) and _number(value['fetch_ordinal'], nullable=False)
        and _number(value['attempt_ordinal'], minimum=1) and _number(value['elapsed_ms'])
        and value['boundary'] in _BOUNDARIES and value['kind'] in _KINDS and value['evidence'] in _EVIDENCE
        and value['endpoint_attribution'] == 'origin_or_proxy_unknown')


def _page(value):
    if type(value) is not list or len(value) != 12: return False
    source, ordinal, attempts, code, origin, length, digest, complete, decode, parse, rows, added = value
    return (source in {'official', 'renderer'} and _number(ordinal, minimum=1, nullable=False)
        and _number(attempts) and _number(code, maximum=599, minimum=100)
        and origin in {'official_https', 'renderer_https', 'other', 'unknown'}
        and _number(length, I64) and _sha(digest) and type(complete) is bool
        and ((complete and length is not None and digest is not None and attempts is not None and attempts > 0)
             or (not complete and length is None and digest is None))
        and decode in {'complete', 'failed', 'not_observed'}
        and parse in {'complete', 'zero_rows', 'failed', 'not_observed'}
        and _number(rows) and _number(added)
        and (parse != 'zero_rows' or rows == 0)
        and (added is None or rows is not None and added <= rows))


def _receipt(value):
    if not _object(value, _RECEIPT_KEYS): return False
    result, failure, producers = value['walk_result'], value['last_failure_phases'], value['producer_sha256']
    return (value['schema'] == SCHEMA and value['scope'] == 'one_walk_not_global_process_state'
        and value['state'] in {'started', 'finished'} and _timestamp(value['started_at_utc'])
        and _timestamp(value['finished_at_utc'], nullable=True)
        and (value['finished_at_utc'] is None) == (value['state'] == 'started')
        and _runtime(value['acquisition_runtime'])
        and _object(producers, {'http', 'registry', 'observation'}) and all(_sha(v) for v in producers.values())
        and all(_number(value[key]) for key in ('fetches_seen', 'HTTP_attempts_seen', 'details_omitted'))
        and _sha(value['metadata_chain_sha256'], nullable=False)
        and type(value['page_receipts']) is list and len(value['page_receipts']) <= 200
        and all(_page(page) for page in value['page_receipts'])
        and type(value['failure_samples']) is list and len(value['failure_samples']) <= 8
        and all(_failure(sample) for sample in value['failure_samples'])
        and _object(failure, {'phases', 'failure'}) and _object(failure['phases'], _PHASES)
        and all(failure['phases'][key] in choices for key, choices in _PHASES.items())
        and (failure['failure'] is None or _failure(failure['failure']))
        and type(value['detail_truncated']) is bool and type(value['numeric_overflow']) is bool
        and (not value['numeric_overflow'] or value['detail_truncated'] and value['details_omitted'] is None)
        and _object(result, _RESULT_KEYS) and result['acquisition'] in {'official_only', 'renderer_only', 'mixed', 'none', 'unknown'}
        and all(_number(result[key]) for key in ('direct_rows_added', 'renderer_rows_added', 'collector_returned_rows'))
        and result['completion_basis'] in {'existing_direct_termination', 'existing_renderer_repeated_page',
            'existing_renderer_empty_page', 'loop_limit_or_partial', 'prior_cache_retained', 'not_observed'}
        and type(result['catalogue_written']) is bool and type(result['prior_catalogue_retained']) is bool
        and result['source_updated_at'] is None and result['historical_period_proven'] is False
        and result['production_acceptance'] is False)


def validate(value):
    """Closed shape and exact scalar types; unknown objects are not projected."""
    try:
        if not _object(value, {'schema', 'scope', 'current_catalogue_acquisition', 'latest_attempt', 'current_catalogue_binding'}): return False
        current, latest, binding = value['current_catalogue_acquisition'], value['latest_attempt'], value['current_catalogue_binding']
        if value['schema'] != ENVELOPE or value['scope'] != SCOPE: return False
        if current is not None and (not _receipt(current) or current['state'] != 'finished' or not current['walk_result']['catalogue_written']): return False
        if latest is not None and not _receipt(latest): return False
        if not _object(binding, _BINDING_KEYS): return False
        if binding['state'] not in {'written_by_this_walk', 'retained_prior_known', 'prior_unknown', 'unbound'}: return False
        if not all(_sha(binding[key]) for key in ('written_payload_sha256', 'acquisition_receipt_sha256')): return False
        if not all(_number(binding[key], I64) for key in ('written_bytes', 'inode', 'mtime_ns')): return False
        if binding['state'] in {'written_by_this_walk', 'retained_prior_known'}:
            if current is None: return False
        elif current is not None or any(binding[key] is not None for key in _BINDING_KEYS - {'state'}):
            return False
        if binding['acquisition_receipt_sha256'] != (hashlib.sha256(canonical(current)).hexdigest() if current is not None else None): return False
        return True
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError):
        return False


def _fit(value):
    value = copy.deepcopy(value)
    while True:
        current = value['current_catalogue_acquisition']
        value['current_catalogue_binding']['acquisition_receipt_sha256'] = hashlib.sha256(canonical(current)).hexdigest() if current is not None else None
        raw = canonical(value)
        if len(raw) <= LIMIT:
            return raw if validate(value) else None
        receipts = [receipt for receipt in (current, value['latest_attempt']) if receipt is not None]
        candidates = [(receipt, key) for receipt in receipts for key in ('page_receipts', 'failure_samples') if receipt[key]]
        if not candidates: return None
        receipt, key = max(candidates, key=lambda pair: len(canonical(pair[0][pair[1]])))
        receipt[key].pop()
        receipt['detail_truncated'] = True
        if not receipt['numeric_overflow']:
            receipt['details_omitted'] += 1


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size, info.st_mtime_ns)


def _regular(info):
    return stat.S_ISREG(info.st_mode) and info.st_nlink == 1


def _directory(root):
    return os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)


def write_envelope(root, value):
    """Only a bounded diagnostic sidecar; failure is not a source-write failure."""
    directory = descriptor = None
    temporary = None
    try:
        raw = _fit(value)
        if raw is None: return False
        root = Path(root)
        root.mkdir(parents=True, exist_ok=True)
        directory = _directory(root)
        try:
            if not _regular(os.stat(NAME, dir_fd=directory, follow_symlinks=False)): return False
        except FileNotFoundError:
            pass
        temporary = '.catalogue_acquisition.' + secrets.token_hex(12) + '.tmp'
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        view = memoryview(raw)
        while view:
            written = os.write(descriptor, view)
            if written <= 0: return False
            view = view[written:]
        os.close(descriptor); descriptor = None
        if (os.stat(root, follow_symlinks=False).st_dev, os.stat(root, follow_symlinks=False).st_ino) != (os.fstat(directory).st_dev, os.fstat(directory).st_ino): return False
        os.replace(temporary, NAME, src_dir_fd=directory, dst_dir_fd=directory)
        return True
    except Exception:
        return False
    finally:
        if descriptor is not None:
            try: os.close(descriptor)
            except OSError: pass
        if directory is not None:
            if temporary is not None:
                try: os.unlink(temporary, dir_fd=directory)
                except OSError: pass
            try: os.close(directory)
            except OSError: pass


class ChangedDuringRead(ValueError):
    pass


def _read_pass(directory):
    descriptor = os.open(NAME, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    try:
        before = os.fstat(descriptor)
        if not _regular(before) or not 0 <= before.st_size <= LIMIT: raise ValueError('unsafe_diagnostic')
        pieces, remaining = [], before.st_size
        while remaining:
            piece = os.read(descriptor, remaining)
            if not piece: break
            pieces.append(piece); remaining -= len(piece)
        after = os.fstat(descriptor)
        if remaining or _identity(before) != _identity(after): raise ChangedDuringRead()
        return b''.join(pieces), _identity(before)
    finally:
        os.close(descriptor)


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result: raise ValueError('duplicate_key')
        result[key] = value
    return result


def _binding_check(directory, binding):
    try:
        info = os.stat('catalogue.json', dir_fd=directory, follow_symlinks=False)
    except FileNotFoundError:
        return 'missing'
    except OSError:
        return 'unknown'
    if not _regular(info) or binding['state'] in {'prior_unknown', 'unbound'}:
        return 'unknown'
    expected = (binding['inode'], binding['written_bytes'], binding['mtime_ns'])
    if any(value is None for value in expected) or binding['written_payload_sha256'] is None: return 'unknown'
    return 'stat_identity_matches' if expected == (info.st_ino, info.st_size, info.st_mtime_ns) else 'mismatch'


def read_view(root, reader_runtime=None):
    result = {'schema': VIEW, 'state': 'absent', 'reader_runtime': reader_runtime if _runtime(reader_runtime) else runtime(),
        'collector_started': False, 'source_files_written': False, 'production_acceptance': False,
        'binding_check_basis': 'stat_identity_only_not_current_payload_rehash',
        'current_catalogue_binding_check': 'unknown', 'diagnostic': None}
    directory = None
    first_read = False
    try:
        directory = _directory(root)
        directory_identity = os.fstat(directory)
        first, first_identity = _read_pass(directory)
        first_read = True
        second, second_identity = _read_pass(directory)
        current_directory = os.stat(root, follow_symlinks=False)
        if first != second or first_identity != second_identity or (current_directory.st_dev, current_directory.st_ino) != (directory_identity.st_dev, directory_identity.st_ino): raise ChangedDuringRead()
        value = json.loads(first, object_pairs_hook=_pairs,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError('non_finite')))
        if not validate(value): raise ValueError('invalid_diagnostic')
        result.update(state='present', diagnostic=value,
            current_catalogue_binding_check=_binding_check(directory, value['current_catalogue_binding']))
    except FileNotFoundError:
        if first_read: result['state'] = 'changed_during_read'
    except ChangedDuringRead:
        result['state'] = 'changed_during_read'
    except (OSError, ValueError, TypeError, RecursionError, OverflowError):
        result['state'] = 'corrupt'
    finally:
        if directory is not None:
            try: os.close(directory)
            except OSError:
                result.update(state='corrupt', diagnostic=None, current_catalogue_binding_check='unknown')
    return result
