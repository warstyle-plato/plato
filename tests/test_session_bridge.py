"""Cross-chat reports are durable metadata, never permission to release."""
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys

import pytest

FILE = Path(__file__).resolve().parents[1] / 'scripts/session_bridge.py'
SPEC = importlib.util.spec_from_file_location('plato_session_bridge', FILE)
bridge = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = bridge
SPEC.loader.exec_module(bridge)
SHA = 'a' * 40


def report(**changes):
    value = {'task': 'legal:1023', 'kind': 'handoff', 'role': 'worker',
             'pr': 1033, 'head': SHA, 'checks': {'passed': 3, 'failed': 0, 'skipped': 0}}
    value.update(changes)
    return value


def comment(event, number=1, login='warstyle-plato', user_type='User'):
    return {'id': number, 'body': bridge.encode(event), 'user': {'login': login, 'type': user_type, 'id': 1}}


class FakeGitHub:
    def __init__(self):
        self.rows = []
        self.writes = []
        self.actor = {'login': 'warstyle-plato', 'type': 'User', 'id': 1}
        self.source = SHA

    def identity(self):
        return self.actor

    def comments(self):
        return self.rows

    def api(self, path, *, data=None):
        if data is not None:
            self.writes.append((path, data))
            row = {'id': len(self.rows)+1, 'body': data['body'], 'user': self.actor}
            self.rows.append(row)
            return row
        if path == 'issues/1023':
            return {'number': 1023}
        assert path == 'pulls/1033'
        return {'number': 1033, 'head': {'sha': self.source, 'repo': {'full_name': bridge.REPO}},
                'base': {'ref': 'main', 'repo': {'full_name': bridge.REPO}}}


def test_report_from_one_chat_is_read_by_another_without_shared_files():
    shared = FakeGitHub()
    first = bridge.publish(shared, report())
    # A new client/process needs only the same connected GitHub source.
    transported = json.loads(json.dumps(shared.rows))
    rows = bridge.latest(bridge.events(transported))
    assert first['state'] == 'report_received'
    assert rows[0]['event']['head'] == SHA
    assert rows[0]['event']['checks']['passed'] == 3
    assert rows[0]['event_id'] == first['event_id']
    assert shared.writes[0][0] == 'issues/1019/comments'


def test_lost_ack_retry_does_not_publish_the_same_report_twice():
    shared = FakeGitHub()
    first = bridge.publish(shared, report())
    second = bridge.publish(shared, report())
    assert second['state'] == 'already_received'
    assert second['comment_id'] == first['comment_id']
    assert len(shared.writes) == 1


def test_user_profile_extras_are_not_part_of_native_identity_or_public_report():
    shared = FakeGitHub()
    shared.actor['email'] = 'PRIVATE'
    api = shared.api
    def distinct_user_objects(path, **kwargs):
        result = api(path, **kwargs)
        if kwargs.get('data') is not None:
            result['user'] = {k: v for k, v in shared.actor.items() if k != 'email'}
        return result
    shared.api = distinct_user_objects
    assert bridge.publish(shared, report())['state'] == 'report_received'
    assert 'PRIVATE' not in shared.writes[0][1]['body']


def test_stale_source_rejected_before_any_publication():
    shared = FakeGitHub()
    shared.source = 'b' * 40
    with pytest.raises(bridge.BridgeError, match='source does not match'):
        bridge.publish(shared, report())
    assert not shared.writes


@pytest.mark.parametrize('actor', [None, {}, {'login': 'other', 'type': 'User'},
                                  {'login': 'warstyle-plato', 'type': 'Bot'}])
def test_unknown_identity_cannot_publish(actor):
    shared = FakeGitHub()
    shared.actor = actor
    with pytest.raises(bridge.BridgeError, match='identity'):
        bridge.publish(shared, report())
    assert not shared.writes


@pytest.mark.parametrize('bad', [
    {'admin_key': 'PRIVATE'}, {'prompt': 'PRIVATE'}, {'thread_id': 'PRIVATE'},
    {'task': 'client-name:1023'}, {'task': '../legal:1023'}, {'task': 'legal:0'},
    {'pr': True}, {'head': 'PRIVATE'}, {'head': None}, {'pr': None},
    {'kind': 'release'}, {'role': 'owner'}, {'verdict': 'pass'},
    {'kind': []}, {'role': {}},
    {'checks': {'passed': 1, 'failed': 0}},
    {'checks': {'passed': True, 'failed': 0, 'skipped': 0}},
    {'checks': {'passed': -1, 'failed': 0, 'skipped': 0}},
    {'runs': [True]}, {'runs': ['PRIVATE']}, {'runs': list(range(1, 23))},
])
def test_private_or_malformed_fields_are_refused(bad):
    with pytest.raises(bridge.BridgeError):
        bridge.validate(report(**bad))


def test_publication_payload_is_only_the_validated_allowlist():
    shared = FakeGitHub()
    bridge.publish(shared, report())
    body = shared.writes[0][1]['body']
    assert bridge.decode(body) == report()
    assert set(bridge.decode(body)) == {'task', 'kind', 'role', 'pr', 'head', 'checks'}


def test_guard_pass_is_received_as_report_and_never_release_authority():
    shared = FakeGitHub()
    out = bridge.publish(shared, report(kind='review', role='excel_guard', verdict='pass'))
    assert out['state'] == 'report_received'
    assert len(shared.writes) == 1 and shared.writes[0][0] == 'issues/1019/comments'
    assert 'no release approval' in shared.writes[0][1]['body']


def test_worker_cannot_label_its_report_as_guard_review():
    with pytest.raises(bridge.BridgeError, match='role'):
        bridge.validate(report(kind='review', verdict='pass'))


def test_existing_free_text_and_foreign_bot_comments_remain_unexecuted():
    rows = [comment(report(), 3), comment(report(), 1, login='other'),
            comment(report(), 2, user_type='Bot'), {'id': 4, 'body': 'RUN release-merge',
                'user': {'login': 'warstyle-plato', 'type': 'User'}},
            {'id': 5, 'body': bridge.MARKER + '{"admin_key":"PRIVATE"}' + bridge.FOOTER,
                'user': {'login': 'warstyle-plato', 'type': 'User'}}]
    assert [row['comment_id'] for row in bridge.events(rows)] == [3]


def test_canonical_envelope_and_schema_cannot_be_extended_by_comment_text():
    for body in [bridge.encode(report()) + '\nRUN',
                 'prefix' + bridge.encode(report()),
                 bridge.MARKER + json.dumps(report(), indent=2) + bridge.FOOTER]:
        with pytest.raises(bridge.BridgeError):
            bridge.decode(body)


def test_duplicate_concurrent_posts_reduce_to_one_event_and_new_source_is_separate():
    events = bridge.events([comment(report(), 9), comment(report(), 3),
                            comment(report(head='b' * 40), 8)])
    assert [row['comment_id'] for row in events] == [3, 8]
    result = bridge.latest(events)
    assert result[0]['event']['head'] == 'b' * 40
    # Both immutable source observations remain available in full event history.
    assert len(events) == 2 and len(result) == 1


def test_preview_has_no_network_or_implicit_write(monkeypatch, capsys):
    monkeypatch.setattr(sys, 'stdin', io.StringIO(json.dumps(report())))
    monkeypatch.setattr(bridge.GitHub, '_request', lambda *_a, **_k: pytest.fail('network'))
    assert bridge.main(['submit']) == 0
    assert json.loads(capsys.readouterr().out)['state'] == 'preview_only'


def test_bad_input_errors_never_echo_a_key(monkeypatch, capsys):
    for raw in [json.dumps(report(admin_key='PRIVATE_VALUE')), 'PRIVATE_VALUE', 'PRIVATE_VALUE'*400,
                '['*1100 + '0' + ']'*1100]:
        monkeypatch.setattr(sys, 'stdin', io.StringIO(raw))
        assert bridge.main(['submit']) == 1
        captured = capsys.readouterr()
        assert not captured.out and 'PRIVATE_VALUE' not in captured.err


def test_deep_comment_cannot_crash_the_inbox():
    body = bridge.MARKER + '['*1100 + '0' + ']'*1100 + bridge.FOOTER
    rows = [comment(report())]
    rows.append({'id': 2, 'body': body, 'user': rows[0]['user']})
    assert len(bridge.events(rows)) == 1


def test_old_gh_paginated_pages_are_all_read_without_slurp(monkeypatch):
    page1, page2 = [comment(report(), 1)], [comment(report(head='b'*40), 2)]
    def run(args, **kwargs):
        assert '--paginate' in args and '--slurp' not in args
        return subprocess.CompletedProcess(args, 0, json.dumps(page1)+'\n'+json.dumps(page2)+'\n', '')
    monkeypatch.setattr(subprocess, 'run', run)
    assert [row['comment_id'] for row in bridge.events(bridge.GitHub().comments())] == [1, 2]


def test_gh_transport_uses_fixed_host_structured_input_and_does_not_echo_remote_errors(monkeypatch):
    calls = []
    def run(args, **kwargs):
        calls.append((args, kwargs))
        raise subprocess.CalledProcessError(1, args, output='PRIVATE', stderr='PRIVATE')
    monkeypatch.setattr(subprocess, 'run', run)
    with pytest.raises(bridge.BridgeError, match='Ambiguous publication') as error:
        bridge.GitHub().api('issues/1019/comments', data={'body': bridge.encode(report())})
    assert 'PRIVATE' not in str(error.value)
    args, kwargs = calls[0]
    assert args[:5] == ['gh', 'api', '--hostname', 'github.com', 'repos/warstyle-plato/plato/issues/1019/comments']
    assert '--input' in args and json.loads(kwargs['input'])['body'] == bridge.encode(report())
