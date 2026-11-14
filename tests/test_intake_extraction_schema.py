"""Malformed synthetic provider JSON must take the native explicit failure path."""
import base64
import json

import pytest

import document_intake as di


@pytest.mark.parametrize('payload,path', [
    ({'fields': 23}, 'fields'), ({'fields': {}}, 'fields'),
    ({'fields': None}, 'fields'), ({'fields': [23]}, 'fields[]'),
    ({'fields': [{'key': 'purchase_price_mln', 'value': {}}]}, 'fields[].value'),
    ({'questions': 23}, 'questions'), ({'questions': 'question'}, 'questions'),
    ({'questions': [None]}, 'questions[]'),
    ({'questions': [{'question': 'Как поступить?', 'options': {}}]}, 'questions[].options'),
    ({'questions': [{'question': 'Как поступить?', 'options': [23]}]}, 'questions[].options[]'),
    ({'questions': [{'question': 'Как поступить?', 'options': [{'label': 'Вариант', 'value': {}}]}]}, 'questions[].options[].value'),
    ({'questions': [{'question': 'Как поступить?', 'options': [{'label': 'Вариант', 'value': float('nan')}]}]}, 'questions[].options[].value'),
    ({'fields': [{'key': 'purchase_price_mln', 'value': float('inf')}]}, 'fields[].value'),
    ({'fields': [{'key': 'purchase_price_mln', 'value': 10**400}]}, 'fields[].value'),
    ({'questions': [{'question': 'Как поступить?', 'options': [{'label': 'Вариант', 'value': 10**400}]}]}, 'questions[].options[].value'),
    ({'notes': 23}, 'notes'), ({'notes': 'note'}, 'notes'),
    ({'notes': [{}]}, 'notes[]'),
])
def test_wrong_container_or_member_type_is_an_explicit_failure(payload, path):
    got = di.parse_intake(json.dumps(payload))
    assert got['reason']
    assert got['parse_error'] == {'code': 'invalid_extraction_shape', 'path': path}
    assert got['fields'] == got['questions'] == []


def test_missing_optional_collections_and_known_zero_are_not_failures():
    got = di.parse_intake(json.dumps({'fields': [{'key': 'purchase_price_mln',
        'value': 0, 'unit': 'руб.', 'quote': 'Стоимость 0 руб.'}]}))
    assert not got['reason'] and got['fields'][0]['value'] == 0
    assert got['questions'] == got['notes'] == []


@pytest.fixture
def fake_provider(monkeypatch, tmp_path):
    import main as wrapper
    from starlette.requests import Request
    core = wrapper.core
    request = Request({'type': 'http', 'method': 'POST', 'path': '/agent/document',
                       'headers': [], 'query_string': b''})
    monkeypatch.setattr(core, '_PLATO_STAGE_DIR', tmp_path)
    monkeypatch.setattr(core, '_require_web_access', lambda *_a: None)
    monkeypatch.setattr(core, '_agent_bind_actor', lambda *_a, **_k: None)
    monkeypatch.setattr(core, 'usage_track', lambda *_a, **_k: None)
    calls = []
    def provider(*_args):
        calls.append('fake-provider')
        return {'answer': json.dumps({'fields': 23})}
    monkeypatch.setattr(core, 'plato_answer', provider)
    return core, request, calls


def test_native_reader_preserves_typed_shape_failure(fake_provider):
    core, request, calls = fake_provider
    got = core.document_intake_read({'text': 'Описание', 'pages': 1}, request)
    assert got['parse_error']['path'] == 'fields' and got['reason']
    assert got['fields'] == [] and calls == ['fake-provider']


@pytest.mark.parametrize('body,has_fallback', [('Стоимость 2400000 руб.', True), ('Только описание', False)])
def test_native_document_caller_recovers_from_source_labels_or_keeps_failure(fake_provider, monkeypatch, body, has_fallback):
    core, request, calls = fake_provider
    monkeypatch.setattr(di, 'extract_text', lambda _raw, filename: {
        'text': body, 'pages': 1, 'filename': filename, 'recognized': False, 'reason': ''})
    inputs = {'purchase_price_mln': 9}
    req = core.AgentDocumentRequest(filename='synthetic.txt',
        content_b64=base64.b64encode(b'synthetic').decode(), inputs=inputs, tep={})
    got = core.agent_document(req, request)
    assert calls == ['fake-provider'] and req.inputs == inputs
    if has_fallback:
        assert got['fallback'] == 'local-labelled-fields' and not got['reason']
        assert got['card']['inputs']['purchase_price_mln'] == 2.4
        assert not got['card']['ready']
        assert any('резервный' in note for note in got['notes'])
    else:
        assert got['reason'] and got['parse_error']['path'] == 'fields'
        assert got['card'] is None and got['fields'] == []
