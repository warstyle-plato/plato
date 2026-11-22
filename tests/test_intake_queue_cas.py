"""Native disk/process CAS: a loaded web/bot draft cannot replace a winner."""
from __future__ import annotations

import copy
import json
import multiprocessing
import os
from pathlib import Path
import stat

import pytest

import main

core = main.core
CHAT = 900000004


@pytest.fixture
def queue(monkeypatch, tmp_path):
    monkeypatch.setattr(core, '_PLATO_STAGE_DIR', tmp_path / 'stage')
    monkeypatch.setattr(core, '_require_web_access', lambda *a, **k: None)
    monkeypatch.setattr(core, 'usage_track', lambda *a, **k: None)
    monkeypatch.setenv('DEVELOPAID_ADMIN_KEY', 'synthetic-cas-owner')
    request = core._telegram_agent_request(CHAT)
    inputs, tep = dict(core.DEFAULT_INPUTS), copy.deepcopy(core.TEP_DEFAULT)
    card = core._intake_queue_start('synthetic.pdf', {'fields': [], 'questions': []},
        {'text': 'Synthetic source'}, inputs, tep, actor=request.scope['plato_actor'])
    return card, request, inputs, tep


def load(queue):
    return core._intake_queue_load(queue[0]['id'], request=queue[1])


def answer(state, queue, choice=0):
    return core.teaser_card.answer(state, queue[2], queue[3], index=0,
        action='answer', choice=choice, spp_split=core.MKD_SPP_SPLIT,
        presets=core.PROJECT_CLASS_PRESETS)


def web_answer(queue, card=None, **changes):
    card = card or queue[0]
    body = dict(intake_id=card['id'], index=card['questions']['index'],
        queue_revision=card['queue_revision'], question_token=card['question_token'],
        choice=0, inputs=queue[2], tep=queue[3])
    body.update(changes)
    return core.agent_document_answer(core.AgentDocumentAnswerRequest(**body), queue[1])


def test_second_loaded_same_owner_answer_cannot_replace_a_confirmed_answer(queue):
    first, stale = load(queue), load(queue)
    assert first['index'] == stale['index'] == 0
    answer(first, queue, 0); core._intake_queue_save(first)
    answer(stale, queue, 1)
    with pytest.raises(core.HTTPException) as conflict:
        core._intake_queue_save(stale)
    assert conflict.value.status_code == 409
    assert load(queue)['answers'][0]['choice'] == 0


def _stale_process(connection, queue):
    try:
        state = load(queue)
        connection.send(('loaded', os.getpid()))
        connection.recv()
        answer(state, queue, 1)
        try:
            core._intake_queue_save(state)
        except core.HTTPException as error:
            connection.send(('status', error.status_code))
        else:
            connection.send(('status', 200))
    except BaseException as error:
        connection.send(('error', type(error).__name__))
    finally:
        connection.close()


def test_os_process_second_loaded_answer_cannot_replace_committed_answer(queue):
    # Deliberately only old native seams: this exact desired oracle fails on91.
    context = multiprocessing.get_context('fork')
    reader, writer = context.Pipe()
    process = context.Process(target=_stale_process, args=(writer, queue))
    process.start(); writer.close()
    try:
        assert reader.poll(10)
        kind, pid = reader.recv()
        assert kind == 'loaded' and pid != os.getpid()
        first = load(queue); answer(first, queue, 0); core._intake_queue_save(first)
        reader.send('save stale snapshot')
        assert reader.poll(10)
        assert reader.recv() == ('status', 409)
        process.join(10)
        assert process.exitcode == 0
        assert load(queue)['answers'][0]['choice'] == 0
    finally:
        if process.is_alive():
            process.terminate(); process.join(5)
        reader.close()


def _simultaneous_writer(connection, queue, choice):
    try:
        state = load(queue)
        connection.send('loaded'); connection.recv()
        answer(state, queue, choice)
        try:
            core._intake_queue_save(state)
        except core.HTTPException as error:
            connection.send(error.status_code)
        else:
            connection.send(200)
    finally:
        connection.close()


def test_two_os_process_writers_have_exactly_one_winner(queue):
    context = multiprocessing.get_context('fork')
    peers, processes = [], []
    try:
        for choice in (0, 1):
            parent, child = context.Pipe()
            process = context.Process(target=_simultaneous_writer, args=(child, queue, choice))
            process.start(); child.close()
            peers.append(parent); processes.append(process)
        for peer in peers:
            assert peer.poll(10) and peer.recv() == 'loaded'
        for peer in peers: peer.send('go')
        statuses = []
        for peer in peers:
            assert peer.poll(10); statuses.append(peer.recv())
        assert sorted(statuses) == [200, 409]
        for process in processes:
            process.join(10); assert process.exitcode == 0
        assert len(load(queue)['answers']) == 1
    finally:
        for process in processes:
            if process.is_alive(): process.terminate(); process.join(5)
        for peer in peers: peer.close()


def test_revision_and_question_binding_are_returned_after_the_commit(queue):
    got = web_answer(queue)
    current = load(queue)
    assert got['card']['queue_revision'] == current['revision'] == 1
    assert got['card']['question_token'] == core._intake_question_token(current)
    path = core._intake_queue_path(current['id'])
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.with_suffix('.lock').stat().st_mode) == 0o600
    assert stat.S_IMODE((path.parent/'intake_access'/f"access_{current['id']}.json").stat().st_mode) == 0o600
    assert '_intake_snapshot' not in path.read_text()


@pytest.mark.parametrize('changes', [dict(queue_revision=None), dict(question_token=''),
    dict(queue_revision=6), dict(question_token='b'*64), dict(index=1)])
def test_unshown_or_stale_web_request_refreshes_with_typed409_without_applying(queue, changes):
    before = core._intake_queue_path(queue[0]['id']).read_bytes()
    with pytest.raises(core.HTTPException) as conflict:
        web_answer(queue, value='2,5', **changes)
    assert conflict.value.status_code == 409
    detail = conflict.value.detail
    assert detail['code'] == 'intake_queue_changed'
    assert detail['unapplied_answer']['value'] == '2,5' and not detail['applied']
    assert detail['card']['questions']['index'] == 0
    assert core._intake_queue_path(queue[0]['id']).read_bytes() == before


def test_old_web_request_cannot_answer_the_new_question(queue):
    winner = web_answer(queue)
    with pytest.raises(core.HTTPException) as conflict:
        web_answer(queue, action='stop', choice=1, value='stale proposal')
    assert conflict.value.status_code == 409
    assert conflict.value.detail['card']['queue_revision'] == winner['card']['queue_revision']
    assert len(load(queue)['answers']) == 1


def test_web_save_conflict_returns_fresh_winner_and_keeps_unapplied_answer(queue, monkeypatch):
    save = core._intake_queue_save
    calls = []
    def lost_race(state):
        calls.append(1)
        competing = load(queue); answer(competing, queue, 1); save(competing)
        save(state)
    monkeypatch.setattr(core, '_intake_queue_save', lost_race)
    with pytest.raises(core.HTTPException) as conflict:
        web_answer(queue, value='proposal with units 2,5 млн')
    assert conflict.value.status_code == 409 and calls == [1]
    assert conflict.value.detail['unapplied_answer']['value'] == 'proposal with units 2,5 млн'
    assert conflict.value.detail['card']['queue_revision'] == 1
    assert load(queue)['answers'][0]['choice'] == 1


def test_legacy_missing_revision_requires_refresh_then_explicit_zero(queue):
    path = core._intake_queue_path(queue[0]['id'])
    state = json.loads(path.read_bytes()); state.pop('revision', None)
    path.write_text(json.dumps(state, ensure_ascii=False))
    with pytest.raises(core.HTTPException) as conflict:
        web_answer(queue, queue_revision=None)
    assert conflict.value.status_code == 409
    card = conflict.value.detail['card']
    assert card['queue_revision'] == 0
    assert web_answer(queue, card)['card']['queue_revision'] == 1


def test_raw_sha_detects_byte_change_without_revision_change(queue):
    stale = load(queue); path = core._intake_queue_path(stale['id'])
    changed = path.read_bytes() + b'\n'
    path.write_bytes(changed)
    answer(stale, queue)
    with pytest.raises(core.HTTPException) as conflict: core._intake_queue_save(stale)
    assert conflict.value.status_code == 409 and path.read_bytes() == changed


@pytest.mark.parametrize('change', ['id', 'revision', 'root', 'plain_dict'])
def test_a_loaded_snapshot_cannot_be_rebound_or_forged(queue, monkeypatch, change):
    state = load(queue)
    if change == 'id': state['id'] = 'a'*32
    elif change == 'revision': state['revision'] = 99
    elif change == 'root': monkeypatch.setattr(core, '_PLATO_STAGE_DIR', core._PLATO_STAGE_DIR / 'different')
    else: state = dict(state, _intake_snapshot={'sha256': 'client controlled'})
    with pytest.raises(core.HTTPException) as conflict: core._intake_queue_save(state)
    assert conflict.value.status_code == 409


def test_deleted_snapshot_is_not_resurrected(queue):
    state = load(queue); path = core._intake_queue_path(state['id']); path.unlink()
    with pytest.raises(core.HTTPException) as missing: core._intake_queue_save(state)
    assert missing.value.status_code == 404 and not path.exists()


def test_owner_change_after_load_is_rechecked_before_save(queue):
    state = load(queue)
    path = core._PLATO_STAGE_DIR/'intake_access'/f"access_{state['id']}.json"
    other = core._telegram_agent_request(CHAT+1).scope['plato_actor']
    path.write_text(json.dumps(other.metadata()))
    with pytest.raises(core.HTTPException) as denied: core._intake_queue_save(state)
    assert denied.value.status_code == 403
    assert json.loads(core._intake_queue_path(state['id']).read_bytes())['answers'] == []


def test_foreign_owner_is_rejected_before_reading_private_queue(queue, monkeypatch):
    monkeypatch.setattr(core, '_intake_queue_path', lambda *a: pytest.fail('private file read'))
    with pytest.raises(core.HTTPException) as denied:
        core._intake_queue_load(queue[0]['id'], request=core._telegram_agent_request(CHAT+1))
    assert denied.value.status_code == 403


@pytest.mark.parametrize('intake_id', ['../outside', 'a'*31, 'a'*32+'\n', 'A'*32, 'a'*33, ''])
def test_invalid_ids_never_name_a_file(queue, intake_id):
    with pytest.raises(core.HTTPException) as invalid:
        core._intake_queue_load(intake_id, request=queue[1])
    assert invalid.value.status_code == 400


@pytest.mark.parametrize('record', ['queue', 'metadata', 'lock'])
@pytest.mark.parametrize('link', ['symlink', 'hardlink'])
def test_linked_records_fail_closed_and_never_change_the_target(queue, tmp_path, record, link):
    state = load(queue); path = core._intake_queue_path(state['id'])
    if record == 'metadata': path = path.parent/'intake_access'/f"access_{state['id']}.json"
    elif record == 'lock': path = path.with_suffix('.lock')
    target = tmp_path/'target'; target.write_bytes(path.read_bytes()); before = target.read_bytes()
    path.unlink()
    if link == 'symlink': path.symlink_to(target)
    else: os.link(target, path)
    with pytest.raises(core.HTTPException) as denied: load(queue)
    assert denied.value.status_code == 404
    if record != 'lock':
        with pytest.raises(core.HTTPException) as denied: core._intake_queue_save(state)
        assert denied.value.status_code == 404
    else:
        with pytest.raises(OSError): core._intake_queue_save(state)
    assert target.read_bytes() == before


@pytest.mark.parametrize('directory', ['stage', 'access'])
def test_symlink_directory_is_not_traversed(queue, directory, tmp_path):
    stage = core._PLATO_STAGE_DIR
    path = stage if directory == 'stage' else stage/'intake_access'
    renamed = tmp_path/'renamed'; path.rename(renamed); path.symlink_to(renamed, target_is_directory=True)
    with pytest.raises(core.HTTPException) as missing: load(queue)
    assert missing.value.status_code == 404


def test_initial_publication_does_not_clobber_an_existing_unowned_record(queue):
    prepared, _ = core._intake_queue_prepare('new.pdf', {'fields': []}, {'text': ''}, queue[2], queue[3],
        actor=queue[1].scope['plato_actor'])
    path = core._intake_queue_path(prepared['id']); path.write_bytes(b'existing private record')
    with pytest.raises(core.HTTPException) as conflict: core._intake_queue_publish(prepared, queue[1].scope['plato_actor'])
    assert conflict.value.status_code == 409 and path.read_bytes() == b'existing private record'


def test_cleanup_uses_the_same_lock_and_expired_snapshot_cannot_resurrect(queue):
    state = load(queue); path = core._intake_queue_path(state['id'])
    old = core.time.time() - core._INTAKE_QUEUE_TTL - 5
    os.utime(path, (old, old))
    with core._intake_queue_directory() as directory, core._intake_queue_lock(directory, state['id']):
        core._intake_queue_cleanup()
        assert path.exists()
    core._intake_queue_cleanup()
    assert not path.exists() and path.with_suffix('.lock').exists()
    with pytest.raises(core.HTTPException) as missing: core._intake_queue_save(state)
    assert missing.value.status_code == 404


def _publish_process(connection, prepared, actor):
    connection.send('ready'); connection.recv()
    try:
        core._intake_queue_publish(prepared, actor)
    except core.HTTPException as error:
        connection.send(error.status_code)
    else:
        connection.send(200)
    finally:
        connection.close()


def test_initial_private_publication_is_atomic_and_has_only_one_process_winner(queue):
    prepared, _ = core._intake_queue_prepare('new.pdf', {'fields': []}, {'text': ''}, queue[2], queue[3])
    context = multiprocessing.get_context('fork')
    peers, processes = [], []
    try:
        for _ in range(2):
            parent, child = context.Pipe()
            process = context.Process(target=_publish_process,
                args=(child, prepared, queue[1].scope['plato_actor']))
            process.start(); child.close(); peers.append(parent); processes.append(process)
        for peer in peers: assert peer.poll(10) and peer.recv() == 'ready'
        for peer in peers: peer.send('publish')
        statuses = []
        for peer in peers: assert peer.poll(10); statuses.append(peer.recv())
        assert sorted(statuses) == [200, 409]
        path = core._intake_queue_path(prepared['id'])
        assert json.loads(path.read_bytes())['id'] == prepared['id']
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert core._intake_queue_load(prepared['id'], request=queue[1])['revision'] == 0
    finally:
        for process in processes:
            process.join(10)
            if process.is_alive(): process.terminate(); process.join(5)
        for peer in peers: peer.close()


def test_a_question_token_binds_the_full_current_question_and_queue(queue):
    original = load(queue); token = core._intake_question_token(original)
    for changed in (dict(original, id='b'*32), dict(original, revision=1), dict(original, index=1)):
        assert core._intake_question_token(changed) != token
    changed = copy.deepcopy(original)
    changed['cards'][0]['options'][0]['label'] += ' changed'
    assert core._intake_question_token(changed) != token



def test_replaced_stage_directory_cannot_receive_an_old_loaded_snapshot(queue, tmp_path):
    import shutil
    state = load(queue)
    stage = core._PLATO_STAGE_DIR
    old = tmp_path / 'old-stage'
    stage.rename(old)
    shutil.copytree(old, stage)
    with pytest.raises(core.HTTPException) as conflict:
        core._intake_queue_save(state)
    assert conflict.value.status_code == 409
    assert load(queue)['answers'] == []



def test_publication_of_an_already_published_queue_is_not_an_update(queue):
    prepared, _ = core._intake_queue_prepare('new.pdf', {'fields': []}, {'text': ''}, queue[2], queue[3])
    actor = queue[1].scope['plato_actor']
    core._intake_queue_publish(prepared, actor)
    path = core._intake_queue_path(prepared['id']); before = path.read_bytes()
    with pytest.raises(core.HTTPException) as conflict:
        core._intake_queue_publish(prepared, actor)
    assert conflict.value.status_code == 409 and path.read_bytes() == before
