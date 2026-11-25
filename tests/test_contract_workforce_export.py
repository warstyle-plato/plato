"""The normal cached-card download carries dated staffing and rejects stale reports."""
import copy
import base64
import io

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

import developaid_contract_files as files
import developaid_contract_gpr_export as export
import developaid_monitor_contracts as contracts
import developaid_monitor_daily as daily
from tests.test_contract_relative_gpr_calendar import card, record, ROW, PROJECT, CUT, KEY, finished


@pytest.mark.parametrize('has_plan', [True, False])
def test_native_workbook_conditionally_includes_staff_and_checks_even_unavailable_sources(card, monkeypatch, has_plan):
    import main
    folder, sha, source = card
    source['schedule']['calendar_basis'] = 'calendar'
    source['schedule']['columns'] = [{'period': 1, 'start': CUT, 'finish': CUT, 'label': CUT}]
    source['schedule']['lines'][0].update(start='2026-02-01', finish=CUT)
    source['schedule']['lines'][0].pop('relative_segments')
    source['schedule']['resources'] = ([
        {'name': name, 'category': category, 'period_basis': 'literal_date', 'source': {'page': 1, 'row': index},
         'values': [{'period': 1, 'start': CUT, 'finish': CUT, 'value': count, 'raw': str(count)}]}
        for index, (name, category, count) in enumerate([
            ('Количество рабочих на объекте', 'workers', 10), ('Количество ИТР на объекте', 'itr', 2)], 1)] if has_plan else [])
    files._json(folder/(sha+'.json'), source)
    reports = ([{'date': CUT, 'text': 'ООО Учебный, договор 12-ТСТ ИТР 1, рабочие 8'}]
               if has_plan else [])
    monkeypatch.setattr(daily, '_load_reports', lambda _: copy.deepcopy(reports))
    monkeypatch.setenv('DEVELOPAID_ADMIN_KEY', KEY)
    monkeypatch.setattr(contracts, 'build', lambda *a, **k: {'rows': [copy.deepcopy(ROW)], 'cut': CUT})
    client = TestClient(main.app)
    base = {'key': KEY, 'session': 'synthetic-owner', 'project': PROJECT, 'cut': CUT, 'contract_id': ROW['id']}
    opened = finished(client, client.post('/monitor/contracts/documents', json=base))
    projection = opened['gpr']['workforce']
    assert projection['available'] is has_plan
    body = {**base, 'ticket': opened['ticket'], 'revision': opened['gpr_export']['revision']}
    response = client.post('/monitor/contracts/gpr.xlsx', json=body)
    assert response.status_code == 200, response.text
    book = load_workbook(io.BytesIO(response.content))
    assert book.sheetnames == ['ГПР', 'Выполнение']+(['Численность'] if has_plan else [])
    assert all(sheet.freeze_panes is None for sheet in book)
    if has_plan:
        assert projection['coverage']['workers_pairs'] == projection['coverage']['itr_pairs'] == 1
        assert list(next(book['Численность'].iter_rows(min_row=6, max_row=6, min_col=2, max_col=7, values_only=True))) == [10, 8, -2, 2, 1, -1]
    else:
        assert projection['reason'] in '\n'.join(str(cell.value) for row in book['ГПР'] for cell in row)
    # Even an unavailable staffing projection pins its current source set. The
    # same cached ticket must not silently omit a subsequently saved report.
    reports.append({'date': CUT, 'text': 'Новый исходник отчёта без распределения по договорам'})
    stale = client.post('/monitor/contracts/gpr.xlsx', json=body)
    assert stale.status_code == 409 and 'численности' in stale.json()['detail']
    refreshed = finished(client, client.post('/monitor/contracts/documents', json=base))
    assert refreshed['gpr_export']['revision'] != opened['gpr_export']['revision']
    assert client.post('/monitor/contracts/gpr.xlsx', json={**base, 'ticket': refreshed['ticket'],
        'revision': refreshed['gpr_export']['revision']}).status_code == 200
    original_workbook = export.workbook
    generated = []
    def report_changed_during_generation(*args):
        raw = original_workbook(*args)
        generated.append(True)
        reports.append({'date': CUT, 'text': 'Изменение отчёта во время сборки Excel'})
        return raw
    monkeypatch.setattr(export, 'workbook', report_changed_during_generation)
    raced = client.post('/monitor/contracts/gpr.xlsx', json={**base, 'ticket': refreshed['ticket'],
        'revision': refreshed['gpr_export']['revision']})
    assert generated == [True] and raced.status_code == 409 and 'численности' in raced.json()['detail']
    monkeypatch.setattr(export, 'workbook', original_workbook)
    refreshed = finished(client, client.post('/monitor/contracts/documents', json=base))
    # A new peer contract changes the company/cohort domain even if the target
    # card's own GPR and the reports are unchanged. No full-register calculation
    # is permitted as a side effect of this synchronous download.
    peer_folder = files._directory(PROJECT, 'd'*64)
    peer_sha, peer = record(peer_folder, 'new-peer-cohort')
    peer['contract']['number'] = 'PEER-99'
    files._json(peer_folder/(peer_sha+'.json'), peer)
    monkeypatch.setattr(contracts, 'build', lambda *a, **k: pytest.fail('Download must not rebuild the register.'))
    peer_stale = client.post('/monitor/contracts/gpr.xlsx', json={**base, 'ticket': refreshed['ticket'],
        'revision': refreshed['gpr_export']['revision']})
    assert peer_stale.status_code == 409 and 'численности' in peer_stale.json()['detail']


@pytest.mark.parametrize('action', ['remove', 'links', 'confirm', 'upload'])
def test_persisted_document_change_rebuilds_fresh_scope_and_keeps_gpr_download_usable(card, monkeypatch, action):
    import main
    import developaid_contract_workforce as workforce
    folder, _, _ = card
    auxiliary, auxiliary_record = record(folder, 'auxiliary-without-gpr', schedule=False)
    from tests.test_contract_documents_are_read_from_their_tables import estimate_pdf
    new_pdf = estimate_pdf(title=('Приложение № 1 к Договору подряда № 12-ТСТ от 01.02.2026',
                                 'Расчёт договорной стоимости'))
    if action == 'links':
        auxiliary = files.store(PROJECT, ROW, 'Смета для связи.pdf', new_pdf)['sha256']
    elif action == 'confirm':
        auxiliary_record['scan'] = {'read': {}, 'confirmed_at': None}
        files._json(folder/(auxiliary+'.json'), auxiliary_record)
    calls = []
    monkeypatch.setenv('DEVELOPAID_ADMIN_KEY', KEY)
    monkeypatch.setattr(daily, '_load_reports', lambda _: [])
    def build(*args, **kwargs):
        calls.append(workforce.cohort_sources(PROJECT, CUT))
        return {'rows': [copy.deepcopy(ROW)], 'cut': CUT}
    monkeypatch.setattr(contracts, 'build', build)
    client = TestClient(main.app)
    base = {'key': KEY, 'session': 'synthetic-owner', 'project': PROJECT, 'cut': CUT, 'contract_id': ROW['id']}
    opened = finished(client, client.post('/monitor/contracts/documents', json=base))
    old_sources = opened['gpr']['workforce']['cohort_source_guard']
    path, change = {'remove': ('document-remove', {'sha256': auxiliary}),
        'links': ('document-links', {'sha256': auxiliary, 'estimate': 0, 'choices': [{'index': 0}], 'clear': True}),
        'confirm': ('document-confirm', {'sha256': auxiliary, 'kind': 'agreement', 'values': {
            'contract_number': ROW['contract'], 'contract_date': ROW['contract_date'],
            'agreement_number': '1', 'agreement_date': '2026-02-05'}}),
        'upload': ('document-upload', {'filename': 'Новый расчёт.pdf', 'content_base64': base64.b64encode(new_pdf).decode()})}[action]
    changed = finished(client, client.post('/monitor/contracts/'+path, json={**base, **change}))
    assert changed['ok'] and changed['gpr']['source'] == opened['gpr']['source']
    if action == 'remove':
        assert auxiliary in {doc['sha256'] for doc in changed['removed']}
    elif action == 'upload':
        assert changed['document']['sha256'] != auxiliary and not changed['document']['already']
    elif action == 'confirm':
        assert files._stored(folder/(auxiliary+'.json'))['scan']['confirmed_at']
    else:
        assert (folder/files.CHOICES).is_file()
    assert len(calls) == 3, 'One read, one mutation admission and one async post-write register rebuild.'
    assert calls[0] == calls[1] == old_sources and calls[2] != old_sources
    assert changed['gpr']['workforce']['cohort_source_guard'] == calls[2]
    assert workforce.require_current(changed['gpr']['workforce'], PROJECT)
    response = client.post('/monitor/contracts/gpr.xlsx', json={**base, 'ticket': changed['ticket'],
        'revision': changed['gpr_export']['revision']})
    assert response.status_code == 200 and load_workbook(io.BytesIO(response.content)).sheetnames == ['ГПР', 'Выполнение']
