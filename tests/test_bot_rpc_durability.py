"""Native POSIX worker races with a fake provider; no app startup or network."""
from __future__ import annotations

import ast
import copy
import hashlib
import hmac
import json
import logging
import math
import multiprocessing
import os
from pathlib import Path
import re
import threading
import time
from typing import Any

from fastapi import HTTPException
import pytest

import agent_access

REPO = Path(__file__).resolve().parents[1]


def _load(path, names, namespace):
    nodes = [copy.deepcopy(n) for n in ast.parse((REPO/path).read_bytes()).body
             if isinstance(n, ast.FunctionDef) and (n.name in names or
                 path == 'engine/agent.py' and n.name.startswith('_plato_proxy_'))]
    for node in nodes:
        node.decorator_list = []
    exec(compile(ast.Module(nodes, []), str(REPO/path), 'exec'), namespace)
    return namespace


def _native(folder):
    ns = {'Path': Path, 'Any': Any, 'os': os, 'json': json, 'time': time,
          'threading': threading, 'HTTPException': HTTPException, 'math': math,
          're': re, 'hmac': hmac, 'hashlib': hashlib, '_agent_access': agent_access,
          '_PLATO_STAGE_DIR': Path(folder), '_PLATO_ANSWER_TTL': 600,
          '_PLATO_TRACE_TTL': 3600, '_PLATO_PROXY_JOBS': {},
          '_PLATO_PROXY_JOBS_LOCK': threading.Lock(), '_PLATO_PROXY_HANDOFF_SECONDS': 0,
          '_TRACE_ID_RE': re.compile(r'[0-9a-f]{8,32}\Z'),
          '_env_str': lambda key, default='': 'synthetic-service-key',
          '_PLATON_LOG': logging.getLogger('offline-rpc-test')}
    _load('engine/inputs.py', {'_safe_child'}, ns)
    return _load('engine/agent.py', {'_plato_stage_path', '_plato_answer_get',
        '_plato_answer_put', '_plato_job_path', '_plato_job_claim',
        '_openai_pull_request', '_plato_stage_cleanup'}, ns)


def _worker(folder, ticket, barrier, release, calls, outcomes):
    ns = _native(folder)
    threads = []
    def create(*a, **kw):
        thread = threading.Thread(*a, **kw); threads.append(thread); return thread
    ns['threading'] = type('ThreadAPI', (), {'Thread': staticmethod(create), 'Event': threading.Event})
    def provider(payload):
        with calls.get_lock(): calls.value += 1
        if not release.wait(8): raise AssertionError('test release not set')
        return {'synthetic_answer': True}
    ns['_openai_direct_request'] = provider
    try:
        barrier.wait(8)
        outcomes.put(ns['_plato_proxy_job'](ticket, {'synthetic_document': 'one'}))
        release.wait(8)
        for thread in threads:
            thread.join(8)
            if thread.is_alive(): raise AssertionError('orphan provider thread')
    except BaseException:
        outcomes.put({'test_worker_failure': True})
        raise


@pytest.mark.parametrize('same_ticket', [True, False])
def test_native_processes_claim_same_ticket_once_and_unrelated_tickets_concurrently(tmp_path, same_ticket):
    ctx = multiprocessing.get_context('fork')
    calls = ctx.Value('i', 0); barrier = ctx.Barrier(2); release = ctx.Event(); outcomes = ctx.Queue()
    tickets = ['a'*12, ('a' if same_ticket else 'b')*12]
    workers = [ctx.Process(target=_worker, args=(str(tmp_path), ticket, barrier, release, calls, outcomes))
               for ticket in tickets]
    for process in workers: process.start()
    try:
        assert all(outcomes.get(timeout=8).get('pending') is True for _ in workers)
        observed = calls.value
    finally:
        release.set()
        for process in workers:
            process.join(8)
            if process.is_alive(): process.kill(); process.join(3)
    assert all(process.exitcode == 0 for process in workers)
    assert observed == (1 if same_ticket else 2)


def test_result_and_error_remain_stable_without_repeating_provider(tmp_path):
    ns = _native(tmp_path); calls = []; threads = []
    def provider(payload):
        calls.append(True)
        raise HTTPException(502, 'Synthetic provider refusal')
    def create(*a, **kw):
        thread = threading.Thread(*a, **kw); threads.append(thread); return thread
    ns['threading'] = type('ThreadAPI', (), {'Thread': staticmethod(create), 'Event': threading.Event})
    ns['_openai_direct_request'] = provider
    try:
        ns['_plato_proxy_job']('c'*12, {'synthetic': True})
    except HTTPException as exc:
        assert exc.status_code == 502
    for thread in threads: thread.join(3); assert not thread.is_alive()
    other = _native(tmp_path)
    other['_openai_direct_request'] = lambda *_: pytest.fail('provider repeated')
    with pytest.raises(HTTPException) as caught:
        other['_plato_proxy_job']('c'*12, {'synthetic': True})
    assert caught.value.status_code == 502 and caught.value.detail == 'Synthetic provider refusal'
    assert len(calls) == 1
    for path in tmp_path.glob('proxy_claim_*.lock'):
        assert b'synthetic-service-key' not in path.read_bytes() and b'synthetic_document' not in path.read_bytes()


def test_stranded_claim_is_terminal_and_rotation_or_changed_payload_cannot_adopt_it(tmp_path):
    ns = _native(tmp_path); fd, cached = ns['_plato_proxy_claim']('d'*12, {'synthetic': True})
    assert fd is not None and cached is None
    os.close(fd)  # Native process interruption before a result was saved.
    with pytest.raises(HTTPException) as stopped:
        _native(tmp_path)['_plato_proxy_job']('d'*12, {'synthetic': True})
    assert stopped.value.status_code == 502
    with pytest.raises(HTTPException) as changed:
        ns['_plato_proxy_claim']('d'*12, {'other': True})
    assert changed.value.status_code == 409
    ns['_env_str'] = lambda *_: 'rotated-synthetic-key'
    with pytest.raises(HTTPException) as rotated:
        ns['_plato_proxy_result']('d'*12)
    assert rotated.value.status_code == 403


@pytest.mark.parametrize('kind', ['symlink', 'hardlink'])
def test_private_claim_links_cannot_invoke_a_provider(tmp_path, kind):
    folder = tmp_path/'stage'; folder.mkdir()
    outside = tmp_path/'outside'; outside.write_bytes(b'{}'); outside.chmod(0o600)
    claim = folder/('proxy_claim_'+'1'*12+'.lock')
    if kind == 'symlink': claim.symlink_to(outside)
    else: os.link(outside, claim)
    ns = _native(folder); ns['_openai_direct_request'] = lambda *_: pytest.fail('provider invoked')
    with pytest.raises(HTTPException): ns['_plato_proxy_job']('1'*12, {'synthetic': True})
    assert outside.read_bytes() == b'{}'


def test_missing_result_after_provider_does_not_start_it_again(tmp_path):
    ns = _native(tmp_path); threads = []; calls = []
    def create(*a, **kw):
        thread=threading.Thread(*a, **kw); threads.append(thread); return thread
    ns['threading'] = type('ThreadAPI', (), {'Thread': staticmethod(create), 'Event': threading.Event})
    ns['_openai_direct_request'] = lambda payload: calls.append(True) or {'synthetic': True}
    ns['_plato_answer_put'] = lambda *_: None  # Disk failure after provider completed.
    try: ns['_plato_proxy_job']('2'*12, {'synthetic': True})
    except HTTPException as exc: assert exc.status_code == 502
    for thread in threads: thread.join(3); assert not thread.is_alive()
    other = _native(tmp_path); other['_openai_direct_request'] = lambda *_: pytest.fail('provider repeated')
    with pytest.raises(HTTPException) as stopped:
        other['_plato_proxy_job']('2'*12, {'synthetic': True})
    assert stopped.value.status_code == 502 and len(calls) == 1
    assert other['_plato_proxy_result']('2'*12)['status'] == 502


def test_claim_cleanup_keeps_a_held_inode_and_retires_only_idle_expired_claim(tmp_path):
    ns = _native(tmp_path); fd, _ = ns['_plato_proxy_claim']('e'*12, {'synthetic': True})
    path = tmp_path/('proxy_claim_'+'e'*12+'.lock')
    old = time.time() - ns['_PLATO_TRACE_TTL'] - 1
    os.utime(path, (old, old)); identity = path.stat().st_ino
    ns['_plato_proxy_cleanup']()
    assert path.stat().st_ino == identity
    os.close(fd); ns['_plato_proxy_cleanup']()
    assert not path.exists()


def test_expired_claim_and_fresh_answer_are_retired_together_before_secret_rotation(tmp_path):
    import types
    ns = _native(tmp_path); clock = types.SimpleNamespace(value=time.time())
    ns['time'] = types.SimpleNamespace(time=lambda: clock.value)
    ticket = 'f'*12
    fd, _ = ns['_plato_proxy_claim'](ticket, {'synthetic': True}); os.close(fd)
    clock.value += ns['_PLATO_TRACE_TTL'] + 1
    ns['_plato_answer_put']('proxy'+ticket, {'answer': {'synthetic': True}})
    assert ns['_plato_answer_get']('proxy'+ticket) is not None
    ns['_plato_proxy_cleanup']()
    ns['_env_str'] = lambda *_: 'rotated-synthetic-key'
    assert ns['_plato_proxy_result'](ticket) is None
    assert not (tmp_path/('answer_proxy'+ticket+'.json')).exists()


def test_complete_queue_is_the_only_claimable_publication(tmp_path, monkeypatch):
    import types
    ns = _native(tmp_path); attempted = []; claimed = []
    clock = types.SimpleNamespace(value=0.)
    clock.monotonic = lambda: clock.value; clock.time = lambda: 1000.
    def step(seconds):
        clock.value += seconds
        job = ns['_plato_job_claim']()
        if job:
            claimed.append(job)
            ns['_plato_answer_put']('pull'+job['job_id'], {'answer': {'synthetic': True}})
    clock.sleep = step
    ns.update(time=clock, _PLATO_AI_TIMEOUT_SECONDS=1, _PLATO_QUEUE_POLL_SECONDS=.4,
              _plato_trace_stage=lambda *a: None, _plato_puller_diagnosis=lambda: 'synthetic marker')
    original = os.replace
    def before_publish(source, target, *a, **kw):
        if Path(target).name.startswith('job_'):
            attempted.append(ns['_plato_job_claim']())
        return original(source, target, *a, **kw)
    old_write = Path.write_text
    def partial_old_writer(path, text, *a, **kw):
        if path.parent == tmp_path and path.name.startswith('job_') and path.suffix == '.json':
            with path.open('w', encoding='utf-8') as out:
                half=len(text)//2; out.write(text[:half]); out.flush()
                attempted.append(ns['_plato_job_claim']())
                out.write(text[half:])
            return len(text)
        return old_write(path, text, *a, **kw)
    # Native atomic writer uses Path.replace, which delegates to os.replace.
    monkeypatch.setattr(os, 'replace', before_publish)
    monkeypatch.setattr(Path, 'write_text', partial_old_writer)
    value = ns['_openai_pull_request']({'synthetic': True}, budget_seconds=1)
    assert value == {'synthetic': True}
    assert attempted == [{}]
    assert len(claimed) == 1 and claimed[0]['payload'] == {'synthetic': True}
    assert all(p.stat().st_mode & 0o077 == 0 for p in tmp_path.glob('job_*.taken'))


def _state_worker(folder, barrier, outcomes, value):
    ns = {'Path': Path, 'Any': Any, 'os': os, '_STATE_DIR': Path(folder), '_STATE_TTL_SECONDS': 100000}
    _load('main.py', {'_state_file', '_state_write'}, ns)
    import tempfile
    original = tempfile.mkstemp
    def concurrent(*a, **kw):
        result = original(*a, **kw)
        barrier.wait(8)  # Both private temporaries exist before FS serialization.
        return result
    tempfile.mkstemp = concurrent
    try: outcomes.put(ns['_state_write']('chat:123', {'worker': value}))
    finally: tempfile.mkstemp = original


def test_native_process_state_publications_have_unique_private_temporaries(tmp_path):
    ctx = multiprocessing.get_context('fork'); barrier = ctx.Barrier(2); outcomes = ctx.Queue()
    workers = [ctx.Process(target=_state_worker, args=(str(tmp_path), barrier, outcomes, v)) for v in ('A', 'B')]
    for process in workers: process.start()
    try: assert [outcomes.get(timeout=10) for _ in workers] == ['', '']
    finally:
        for process in workers:
            process.join(8)
            if process.is_alive(): process.kill(); process.join(3)
    assert all(process.exitcode == 0 for process in workers)
    records = list(tmp_path.glob('*.json'))
    assert len(records) == 1 and json.loads(records[0].read_bytes())['worker'] in ('A', 'B')
    assert records[0].stat().st_mode & 0o077 == 0
    assert not list(tmp_path.glob('*.tmp'))


def _state_locked_writer(folder, synced, done, outcome, inherited_lock):
    os.close(inherited_lock)  # A separate server worker does not own parent's claim.
    ns = {'Path': Path, 'Any': Any, 'os': os, '_STATE_DIR': Path(folder), '_STATE_TTL_SECONDS': 100000}
    _load('main.py', {'_state_file', '_state_write'}, ns)
    original = os.fsync
    def signal_sync(fd):
        result = original(fd); synced.set(); return result
    os.fsync = signal_sync
    try: outcome.put(ns['_state_write']('chat:fresh', {'fresh': True}))
    finally: os.fsync = original; done.set()


def test_state_publication_waits_for_gc_filesystem_claim_before_replace(tmp_path):
    import fcntl
    ctx = multiprocessing.get_context('fork'); synced = ctx.Event(); done = ctx.Event(); outcome = ctx.Queue()
    lock = os.open(tmp_path/'.state-fs.lock', os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(lock, fcntl.LOCK_EX)
    process = ctx.Process(target=_state_locked_writer, args=(str(tmp_path), synced, done, outcome, lock))
    process.start()
    try:
        assert synced.wait(8)  # Private temp content is complete, before publication.
        assert not done.wait(.1), 'fresh replace raced past retention decision'
    finally:
        os.close(lock)
    try:
        assert outcome.get(timeout=8) == ''
    finally:
        process.join(8)
        if process.is_alive(): process.kill(); process.join(3)
    assert process.exitcode == 0
    records = list(tmp_path.glob('*.json'))
    assert len(records) == 1 and json.loads(records[0].read_bytes()) == {'fresh': True}


def test_trace_cleanup_uses_dialog_owner_ttl_and_preserves_intake_lifecycle(tmp_path):
    ns = _native(tmp_path); now = time.time(); calls = []
    bot = ast.parse((REPO/'engine/bot_telegram.py').read_bytes())
    ttl_node = next(n for n in bot.body if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == '_TELEGRAM_DIALOG_TTL_SECONDS' for t in n.targets))
    ttl = eval(compile(ast.Expression(ttl_node.value), '<native dialog TTL>', 'eval'), {'__builtins__': {}})
    younger = ns['_PLATO_TRACE_TTL'] + 1
    assert younger < ttl
    for chat, age in [(1, younger), (2, ttl+1)]:
        path = tmp_path/f'dialog_{chat}.json'; path.write_text(json.dumps({'updated_at': now-age}))
        os.utime(path, (now-age, now-age))
    intake = tmp_path/'intake_abcdef123456.json'; intake.write_text('{}'); os.utime(intake, (now-2*ttl, now-2*ttl))
    def owner(chat):
        calls.append(chat); path = tmp_path/f'dialog_{chat}.json'
        if now-json.loads(path.read_bytes())['updated_at'] > ttl: path.unlink()
    ns['_telegram_dialog_get'] = owner
    ns['_plato_stage_cleanup']()
    assert sorted(calls) == [1, 2]
    assert (tmp_path/'dialog_1.json').exists() and not (tmp_path/'dialog_2.json').exists()
    assert intake.exists()
