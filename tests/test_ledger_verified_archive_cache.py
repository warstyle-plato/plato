"""Synthetic immutable ZIPs exercise the shared, disposable source cache."""
import copy
import gzip
import hashlib
import json
import subprocess
import sys
import zlib

import pytest

import developaid_monitor as monitor
import developaid_monitor_archive_cache as disk
import developaid_monitor_contracts as contracts
import developaid_monitor_ledgers as ledgers
from test_monitor_cumulative_ledgers import archive, book


@pytest.fixture
def source(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, '_SNAPSHOT_DIR', tmp_path)
    monkeypatch.setattr(ledgers, '_PARSE_CACHE', type(ledgers._PARSE_CACHE)())
    imported = ledgers.store_archive('Example', archive([('Works.xlsx', book())]),
                                     '2026-11-01', 'Works.zip')
    root = ledgers._root('Example')
    manifest = root / (imported['snapshot_id'] + '.json')
    saved = json.loads(manifest.read_text())
    saved.pop('identity_schema')
    manifest.write_text(json.dumps(saved))
    return root, saved


def count_parser(monkeypatch):
    calls = []
    parser = ledgers.parse_archive
    def counted(*args, **kwargs):
        calls.append(1)
        return parser(*args, **kwargs)
    monkeypatch.setattr(ledgers, 'parse_archive', counted)
    return calls


def read(saved):
    return ledgers.verified_archive('Example', saved['snapshot_id'], saved['filename'])


def entries(root):
    return list((root / disk.DIRECTORY).glob('*.json.gz'))


def test_prepared_identity_reader_uses_shared_raw_parse_and_fresh_worker(source, monkeypatch):
    root, saved = source
    assert ledgers.basis_metadata_current(saved)
    before = {p.name: p.read_bytes() for p in root.iterdir() if p.is_file()}
    calls = count_parser(monkeypatch)
    first = contracts._archive('Example', saved['taken_at'])
    expected = copy.deepcopy(first)
    first['ledgers'][0]['items'][0]['plan_quantity'] = -999
    assert contracts._archive('Example', saved['taken_at']) == expected
    assert len(calls) == 1
    code = """import json,sys
from pathlib import Path
import developaid_monitor as m
import developaid_monitor_ledgers as l
import developaid_monitor_contracts as c
m._SNAPSHOT_DIR=Path(sys.argv[1])
def fail(*args,**kwargs):raise AssertionError('fresh worker reparsed ZIP')
l.parse_archive=fail
print(json.dumps(c._archive('Example','2026-11-01'),ensure_ascii=False))
"""
    child = subprocess.check_output([sys.executable, '-c', code, str(monitor._SNAPSHOT_DIR)], text=True)
    assert json.loads(child) == expected
    assert {p.name: p.read_bytes() for p in root.iterdir() if p.is_file()} == before
    assert len(entries(root)) == 1
    assert (root / disk.DIRECTORY).stat().st_mode & 0o777 == 0o700
    assert entries(root)[0].stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize('clear_memory', [False, True])
def test_tampered_original_is_rejected_before_any_memory_or_disk_hit(source, monkeypatch, clear_memory):
    root, saved = source
    read(saved)
    if clear_memory:
        ledgers._PARSE_CACHE.clear()
    calls = count_parser(monkeypatch)
    raw = root / (saved['snapshot_id'] + '.zip')
    raw.write_bytes(raw.read_bytes() + b'changed')
    with pytest.raises(contracts.ContractProblem, match='отпечатком'):
        contracts._archive('Example', saved['taken_at'])
    assert calls == []


def test_schema_code_filename_and_different_source_never_reuse_parse(source, monkeypatch):
    root, saved = source
    calls = count_parser(monkeypatch)
    read(saved)
    ledgers.verified_archive('Example', saved['snapshot_id'], 'Renamed.zip')
    monkeypatch.setattr(ledgers, '_PARSER_FINGERPRINT', 'changed parser/dependencies')
    read(saved)
    monkeypatch.setattr(ledgers, 'PARSER_SCHEMA', ledgers.PARSER_SCHEMA + 1)
    read(saved)
    payload = archive([('Works.xlsx', book(actual=7))])
    identifier = '2026-11-02-' + hashlib.sha256(payload).hexdigest()
    (root / (identifier + '.zip')).write_bytes(payload)
    changed = ledgers.verified_archive('Example', identifier, saved['filename'])
    assert changed['ledgers'][0]['items'][0]['completed_quantity'] == 7
    assert len(calls) == 5


def test_fingerprint_tracks_reader_code_and_installed_dependency_versions(tmp_path, monkeypatch):
    reader = tmp_path / 'reader.py'
    reader.write_text('parser version one')
    first = disk.fingerprint(reader)
    reader.write_text('parser version two')
    second = disk.fingerprint(reader)
    assert first != second
    monkeypatch.setattr(disk.importlib.metadata, 'version', lambda package: 'changed dependency')
    assert disk.fingerprint(reader) != second


@pytest.mark.parametrize('damage', ['header', 'deflate', 'identity', 'decoded_size', 'compressed_size'])
def test_corrupt_or_oversized_cache_reparses_verified_original(source, monkeypatch, damage):
    root, saved = source
    expected = read(saved)
    path, = entries(root)
    blob = path.read_bytes()
    if damage == 'header':
        broken = b'broken'
    elif damage == 'deflate':
        broken = bytearray(blob)
        broken[10] = (broken[10] & ~6) | 6
        broken = bytes(broken)
        with pytest.raises(zlib.error):
            gzip.decompress(broken)
    elif damage == 'identity':
        envelope = json.loads(gzip.decompress(blob))
        envelope['identity'][1] = '0' * 64
        broken = gzip.compress(json.dumps(envelope).encode())
    elif damage == 'decoded_size':
        broken = gzip.compress(b' ' * (ledgers.MAX_PARSED_BYTES + 1))
    else:
        broken = b'x' * (ledgers._PARSE_CACHE_BYTES + 1)
    path.write_bytes(broken)
    ledgers._PARSE_CACHE.clear()
    calls = count_parser(monkeypatch)
    assert read(saved) == expected
    assert len(calls) == 1
    assert len(entries(root)) == 1


def test_both_raw_readers_share_parse_but_cut_and_owner_decisions_are_reapplied(source, monkeypatch):
    root, saved = source
    saved.pop('parser_schema')
    (root / (saved['snapshot_id'] + '.json')).write_text(json.dumps(saved))
    import developaid_monitor_header_confirmations as confirmations
    decisions = ['first']
    def apply(project, snapshot, cut):
        snapshot['ledgers'][0]['contractor'] = decisions[0]
        return {**snapshot, 'selected_cut': cut}
    monkeypatch.setattr(confirmations, 'apply', apply)
    calls = count_parser(monkeypatch)
    first = ledgers.effective_snapshot('Example', '2026-11-01')
    decisions[0] = 'second'
    second = ledgers.effective_snapshot('Example', '2026-11-02')
    raw = contracts._archive('Example', '2026-11-02')
    assert first['selected_cut'] == '2026-11-01' and first['ledgers'][0]['contractor'] == 'first'
    assert second['selected_cut'] == '2026-11-02' and second['ledgers'][0]['contractor'] == 'second'
    assert raw['ledgers'][0]['contractor'] not in decisions + ['first']
    assert 'selected_cut' not in raw and len(calls) == 1


def test_disk_lru_and_byte_entry_limits_include_previous_versions(tmp_path, monkeypatch):
    monkeypatch.setattr(ledgers, '_PARSE_CACHE', type(ledgers._PARSE_CACHE)())
    monkeypatch.setattr(ledgers, '_PARSE_CACHE_ENTRIES', 2)
    monkeypatch.setattr(ledgers, 'parse_archive', lambda data, name: {'data': data.decode()})
    replace = disk.os.replace
    peaks = []
    def measure(*args, **kwargs):
        peaks.append(sum(p.stat().st_size for p in (tmp_path / disk.DIRECTORY).iterdir()))
        return replace(*args, **kwargs)
    monkeypatch.setattr(disk.os, 'replace', measure)
    def current(i):
        ledgers._PARSE_CACHE.clear()
        return ledgers._current_archive(str(i).encode(), str(i) * 64, 'source.zip', cache_root=tmp_path)
    current(0)
    first, = entries(tmp_path)
    size = first.stat().st_size
    monkeypatch.setattr(ledgers, '_PARSE_CACHE_TOTAL_BYTES', 2 * size + 32)
    current(1)
    current(0)  # Disk hit refreshes its LRU date.
    current(2)
    values = [json.loads(gzip.decompress(p.read_bytes()))['parsed']['data'] for p in entries(tmp_path)]
    assert sorted(values) == ['0', '2']
    assert sum(p.stat().st_size for p in entries(tmp_path)) <= ledgers._PARSE_CACHE_TOTAL_BYTES
    assert all(p.stat().st_size <= ledgers._PARSE_CACHE_BYTES for p in entries(tmp_path))
    assert sum(map(len, ledgers._PARSE_CACHE.values())) <= ledgers._PARSE_CACHE_TOTAL_BYTES
    # A format/code revision occupies the same bounded directory, not a new variant directory.
    monkeypatch.setattr(ledgers, '_PARSER_FINGERPRINT', 'new revision')
    current(3)
    assert len(entries(tmp_path)) <= 2
    assert max(peaks) <= ledgers._PARSE_CACHE_TOTAL_BYTES


@pytest.mark.parametrize('bound', ['entry', 'decoded'])
def test_uncacheable_result_stays_intact_without_a_disk_entry(tmp_path, monkeypatch, bound):
    monkeypatch.setattr(ledgers, '_PARSE_CACHE', type(ledgers._PARSE_CACHE)())
    monkeypatch.setattr(ledgers, '_PARSE_CACHE_BYTES' if bound == 'entry' else 'MAX_PARSED_BYTES', 10)
    payload = {'data': [None, 0, 'preserved']}
    calls = []
    def parse(*args):
        calls.append(1)
        return copy.deepcopy(payload)
    monkeypatch.setattr(ledgers, 'parse_archive', parse)
    for _ in range(2):
        assert ledgers._current_archive(b'raw', 'a' * 64, 'source.zip', cache_root=tmp_path) == payload
    assert len(calls) == 2 and not entries(tmp_path) and not ledgers._PARSE_CACHE


@pytest.mark.parametrize('link', ['directory', 'lock', 'entry', 'source'])
def test_symlinks_never_read_or_change_an_outside_file(source, monkeypatch, tmp_path, link):
    root, saved = source
    outside = tmp_path / 'outside'
    outside.mkdir()
    target = outside / 'private'
    target.write_bytes(b'do not touch')
    cache = root / disk.DIRECTORY
    if link == 'directory':
        cache.symlink_to(outside, target_is_directory=True)
    elif link == 'source':
        read(saved)
        raw = root / (saved['snapshot_id'] + '.zip')
        raw.unlink()
        raw.symlink_to(target)
    else:
        read(saved)
        if link == 'lock':
            path = cache / '.lock'
        else:
            path, = entries(root)
        path.unlink()
        path.symlink_to(target)
    ledgers._PARSE_CACHE.clear()
    if link == 'source':
        with pytest.raises(ledgers.LedgerProblem):
            read(saved)
    else:
        assert read(saved)['ledgers']
    assert target.read_bytes() == b'do not touch'
    assert list(outside.iterdir()) == [target]


def test_two_cold_workers_parse_once_under_the_project_lock(source):
    root, saved = source
    counter = root.parent / 'parse-count'
    code = """import sys,time
from pathlib import Path
import developaid_monitor as m
import developaid_monitor_ledgers as l
m._SNAPSHOT_DIR=Path(sys.argv[1])
parse=l.parse_archive
def counted(*args,**kwargs):
    with Path(sys.argv[3]).open('a') as out:out.write('parse\\n')
    time.sleep(.2)
    return parse(*args,**kwargs)
l.parse_archive=counted
print('ready',flush=True)
sys.stdin.readline()
assert l.verified_archive('Example',sys.argv[2],'Works.zip')['ledgers']
"""
    processes = [subprocess.Popen([sys.executable, '-c', code, str(monitor._SNAPSHOT_DIR),
                    saved['snapshot_id'], str(counter)], stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
    try:
        for process in processes:
            assert process.stdout.readline().strip() == 'ready'
        for process in processes:
            process.stdin.write('\n'); process.stdin.flush()
        for process in processes:
            _, error = process.communicate(timeout=20)
            assert process.returncode == 0, error
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill(); process.wait()
    assert counter.read_text().splitlines() == ['parse']
    assert len(entries(root)) == 1
