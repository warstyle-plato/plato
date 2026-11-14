import base64

import pytest

import developaid_gpr_corpus as corpus
from test_gpr_corpus_preview import book
from test_monitor_cumulative_api import api, post


@pytest.mark.parametrize('key,session', [('', ''), ('wrong', ''), ('', 'telegram'), ('market', 'demo')])
def test_source_gate_precedes_read_and_failed_response_is_not_cached(api, monkeypatch, key, session):
    client, _ = api
    monkeypatch.setattr(corpus, 'latest', lambda *_: pytest.fail('source read before admission'))
    response = post(client, 'gpr-corpus/view', key=key, session=session,
                    project='Учебный проект', cut='2026-11-06')
    assert response.status_code == 403
    assert response.headers['cache-control'] == 'private, no-store'


def test_source_preview_survives_reload_without_rss_or_baseline(api):
    client, _ = api
    uploaded = post(client, 'schedule-fact', project='Учебный проект', taken_at='2026-11-06',
                    content_base64=base64.b64encode(book()).decode())
    assert uploaded.status_code == 200
    assert uploaded.headers['cache-control'] == 'private, no-store'
    result = post(client, 'gpr-corpus/view', project='Учебный проект', cut='2026-11-06')
    assert result.status_code == 200
    assert result.headers['cache-control'] == 'private, no-store'
    assert result.json()['source']['sha256'] == uploaded.json()['corpus_gpr']['sha256']
    assert '31.06.2027' in result.json()['html']
    earlier = post(client, 'gpr-corpus/view', project='Учебный проект', cut='2026-11-05')
    assert earlier.json()['source'] is None
    assert earlier.json()['source_state']['selected_plan']['source_sha256'] == ''


def test_invalid_cut_is_rejected_instead_of_choosing_latest(api):
    client, _ = api
    result = post(client, 'gpr-corpus/view', project='Учебный проект', cut='2026-02-31')
    assert result.status_code == 400 and result.headers['cache-control'] == 'private, no-store'
