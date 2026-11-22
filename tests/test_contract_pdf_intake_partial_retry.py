"""An unpublished pair may finish a clean partial write, never replace corruption."""
import json

import pytest

import developaid_contract_files as files
import developaid_contract_pdf_intake as intake
import developaid_monitor_contracts as contracts
from test_contract_pdf_intake import PROJECT, CUT, ACTOR, pdf, project, admit


def interrupted(project, monkeypatch, missing):
    raw, claims = pdf()
    checked = intake.preview(PROJECT, raw, **claims)
    original = files._write
    def crash(path, content):
        if path.name == (claims['source_sha256']+'.json' if missing == 'json' else intake.REGISTRY):
            raise OSError('Synthetic interruption before publication')
        return original(path, content)
    with monkeypatch.context() as patch:
        patch.setattr(files, '_write', crash)
        with pytest.raises(OSError):
            intake.commit(PROJECT, raw, filename='source.pdf', expected_revision=0,
                          preview_token=checked['preview_token'], actor=ACTOR, **claims)
    folder = project/'contract_documents'/checked['contract_id']
    absent = folder/(claims['source_sha256']+'.'+missing)
    if missing == 'pdf':
        absent.unlink()
    assert not absent.exists() and not (project/intake.REGISTRY).exists()
    assert contracts.build(PROJECT, CUT, include_history=False)['rows'] == []
    (folder/files.CHOICES).write_bytes(b'{"version":1,"choices":{} }\n')
    return raw, claims, checked, folder, absent


@pytest.mark.parametrize('missing', ['json', 'pdf'])
def test_clean_unpublished_pair_restores_only_the_missing_component(project, monkeypatch, missing):
    raw, claims, checked, folder, absent = interrupted(project, monkeypatch, missing)
    retained = folder/(claims['source_sha256']+('.pdf' if missing == 'json' else '.json'))
    before, when = retained.read_bytes(), retained.stat().st_mtime_ns
    choices = (folder/files.CHOICES).read_bytes()
    saved = intake.commit(PROJECT, raw, filename='retry.pdf', expected_revision=0,
                          preview_token=checked['preview_token'], actor=ACTOR, **claims)
    assert saved['revision'] == 1 and saved['already'] is False
    assert absent.is_file() and retained.read_bytes() == before and retained.stat().st_mtime_ns == when
    assert (folder/files.CHOICES).read_bytes() == choices
    row, = contracts.build(PROJECT, CUT, include_history=False)['rows']
    assert row['id'] == checked['contract_id'] and row['completed'] is None
    repeated = intake.commit(PROJECT, raw, filename='retry.pdf', expected_revision=0,
                             preview_token=checked['preview_token'], actor=ACTOR, **claims)
    assert repeated['already'] and repeated['revision'] == 1
    assert retained.read_bytes() == before and retained.stat().st_mtime_ns == when
    assert (folder/files.CHOICES).read_bytes() == choices


@pytest.mark.parametrize('missing', ['json', 'pdf'])
def test_corrupt_retained_component_is_not_replaced_or_published(project, monkeypatch, missing):
    raw, claims, checked, folder, absent = interrupted(project, monkeypatch, missing)
    retained = folder/(claims['source_sha256']+('.pdf' if missing == 'json' else '.json'))
    if missing == 'json':
        retained.write_bytes(b'%PDF synthetic corruption')
    else:
        record = json.loads(retained.read_bytes())
        record['contract'] = {'number': 'OTHER-SYNTHETIC', 'date': '2020-01-01'}
        retained.write_text(json.dumps(record))
    corrupted, choices = retained.read_bytes(), (folder/files.CHOICES).read_bytes()
    with pytest.raises((intake.IntakeProblem, files.ContractFilesProblem)):
        intake.commit(PROJECT, raw, filename='retry.pdf', expected_revision=0,
                      preview_token=checked['preview_token'], actor=ACTOR, **claims)
    assert retained.read_bytes() == corrupted and not absent.exists()
    assert (folder/files.CHOICES).read_bytes() == choices and not (project/intake.REGISTRY).exists()


@pytest.mark.parametrize('missing', ['json', 'pdf'])
def test_published_source_does_not_enter_partial_write_recovery(project, missing):
    raw, claims = pdf()
    checked, saved = admit(raw, claims)
    absent = project/'contract_documents'/saved['contract_id']/(claims['source_sha256']+'.'+missing)
    absent.unlink()
    registry = (project/intake.REGISTRY).read_bytes()
    with pytest.raises(intake.IntakeProblem):
        intake.commit(PROJECT, raw, filename='retry.pdf', expected_revision=0,
                      preview_token=checked['preview_token'], actor=ACTOR, **claims)
    assert not absent.exists() and (project/intake.REGISTRY).read_bytes() == registry
