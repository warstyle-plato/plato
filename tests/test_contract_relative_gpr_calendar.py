"""Source dates, edition changes and exports share one guarded GPR projection."""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import io
import json
import multiprocessing
import time

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

import developaid_contract_documents as documents
import developaid_contract_files as files
import developaid_contract_gpr as gpr
import developaid_contract_gpr_export as export
import developaid_contract_plan as plan
import developaid_contract_comparison_export as old_export
import developaid_monitor as monitor
import developaid_monitor_contracts as contracts

PROJECT, CUT, KEY = 'Учебный относительный ГПР', '2026-02-12', 'synthetic-relative-gpr-admin'
ROW = {'id': 'b'*64, 'contract': '12-ТСТ', 'contract_date': '2026-02-01',
       'contractor': 'ООО Учебный', 'source_kind': 'contract_document'}


@pytest.mark.parametrize('unit,step', [('неделя', 7), ('день', 1)])
def test_pdf_relative_cells_keep_bar_gap_and_combined_resource_label(unit, step):
    import pymupdf
    pdf = pymupdf.open()
    page = pdf.new_page(width=600, height=260)
    page.insert_font(fontname='test', fontfile='/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')
    def text(x, y, value):
        page.insert_text((x, y), value, fontname='test', fontsize=7)
    text(30, 30, 'ГРАФИК ПРОИЗВОДСТВА РАБОТ')
    xs, ys = [30, 70, 300, 340, 390, 440, 490, 540], [70, 100, 125, 150, 175]
    for x in xs:
        page.draw_line((x, ys[0]), (x, ys[-1]))
    for y in ys:
        page.draw_line((xs[0], y), (xs[-1], y))
    for x, value in [(40, '№'), (80, 'Наименование работ'), (302, 'Длит.')]:
        text(x, 86, value)
    for i in range(4):
        text(350+i*50, 86, f'{i+1} {unit}')
    for y, code, name in [(115, '1.', 'Первая работа'), (140, '2.', 'Вторая работа')]:
        text(40, y, code)
        text(80, y, name)
        text(318, y, '2')
    for rectangle in [(340, 100, 390, 125), (440, 100, 490, 125), (390, 125, 490, 150)]:
        page.draw_rect(pymupdf.Rect(*rectangle), color=None, fill=(.3, .7, .4))
    text(80, 165, 'Количество рабочих и ИТР')
    for i in range(4):
        text(362+i*50, 165, '8')
    schedule = documents.read(pdf.tobytes())['schedule']
    assert schedule['calendar_basis'] == 'relative' and len(schedule['lines']) == 2
    assert [(part['start_day'], part['finish_day']) for part in schedule['lines'][0]['relative_segments']] == [
        (1, step), (2*step+1, 3*step)]
    assert schedule['resources'][0]['category'] == 'workers_and_itr'
    assert [value['value'] for value in schedule['resources'][0]['values']] == [8]*4


def record(folder, marker='base', agreement=None, pending=False, schedule=True):
    raw = b'%PDF-synthetic-gpr-source-'+marker.encode()
    sha = hashlib.sha256(raw).hexdigest()
    value = {'sha256': sha, 'reader': documents.READER_VERSION, 'filename': marker+'.pdf',
             'uploaded_at': '2026-02-01T12:00:00+00:00',
             'contract': {'number': ROW['contract'], 'date': ROW['contract_date']},
             'agreement': agreement, 'estimates': [], 'warnings': [], 'terms': {}, 'gpr_pending': pending,
             'schedule': {'pages': [1], 'calendar_basis': 'relative', 'relative_unit': 'week',
                'corrections': [], 'warnings': [], 'assumption': documents.RELATIVE_ASSUMPTION,
                'columns': [{'period': i+1, 'label': f'{i+1} неделя', 'start_day': i*7+1, 'finish_day': (i+1)*7}
                            for i in range(3)],
                'lines': [{'code': '1', 'name': 'Учебная работа', 'start': None, 'finish': None,
                           'parent': None, 'page': 1, 'bar': None,
                           'relative_segments': [{'start_day': 1, 'finish_day': 7, 'start_offset': 0, 'end_offset': 7},
                                                 {'start_day': 15, 'finish_day': 21, 'start_offset': 14, 'end_offset': 21}]}],
                'resources': [{'name': 'Рабочие и ИТР', 'category': 'workers_and_itr', 'source': {'page': 1},
                               'values': [{'period': i+1, 'value': 8} for i in range(3)]}]} if schedule else None}
    folder.mkdir(parents=True, exist_ok=True)
    files._write(folder/(sha+'.pdf'), raw)
    files._json(folder/(sha+'.json'), value)
    return sha, value


@pytest.fixture
def card(monkeypatch, tmp_path):
    monkeypatch.setattr(monitor, '_SNAPSHOT_DIR', tmp_path/'monitor')
    folder = files._directory(PROJECT, ROW['id'])
    sha, source = record(folder)
    return folder, sha, source


def change(listed, *, handover_date='2026-02-02', advance_date='', note='Учебный акт передачи площадки', **extra):
    return gpr.save(PROJECT, ROW, CUT, listed['gpr']['source']['sha256'], listed['gpr']['guard'],
                    'anchor', note, 'synthetic-owner', handover_date, advance_date, **extra)


def test_relative_rows_survive_missing_set_change_clear_and_reload(card):
    folder, sha, source = card
    initial = files.listing(PROJECT, ROW['id'], CUT)
    before = (folder/(sha+'.json')).read_bytes()
    assert initial['gpr']['schedule']['lines'][0]['start'] is None
    assert initial['gpr']['schedule']['lines'][0]['relative_segments'] == source['schedule']['lines'][0]['relative_segments']
    first = change(initial)
    line = first['gpr']['schedule']['lines'][0]
    assert (line['start'], line['finish']) == ('2026-02-02', '2026-02-22')
    assert [(part['start'], part['finish']) for part in line['segments']] == [
        ('2026-02-02', '2026-02-08'), ('2026-02-16', '2026-02-22')]
    # The week without a bar produces no daily plan or duration share.
    assert plan.done(line, dt.date(2026, 2, 15)) == .5
    assert plan.done(line, dt.date(2026, 2, 16)) == 8/14
    second = change(files.listing(PROJECT, ROW['id'], CUT), handover_date='2026-02-03')
    assert second['gpr']['schedule']['lines'][0]['finish'] == '2026-02-23'
    cleared = change(second, handover_date='')
    assert cleared['gpr']['schedule']['lines'][0]['start'] is None
    assert len(gpr.events(folder)) == 3
    assert all(event['actor'] == 'synthetic-owner' and event['source']['sha256'] == sha for event in gpr.events(folder))
    assert (folder/(sha+'.json')).read_bytes() == before, 'A manual calendar must not rewrite the source parse.'


def test_old_card_cas_and_both_exports_refuse_changed_anchor(card):
    old = files.listing(PROJECT, ROW['id'], CUT)
    binding = old['gpr']
    changed = change(old)
    with pytest.raises(files.ContractFilesProblem, match='изменил'):
        change(old, handover_date='2026-02-04')
    with pytest.raises(files.ContractFilesProblem, match='изменил'):
        gpr.require_current(binding)
    with pytest.raises(old_export.ExportProblem, match='изменил'):
        old_export.require_current_sources({'gpr_binding': binding})
    assert changed['gpr']['guard'] != old['gpr']['guard']


def test_new_ds_without_gpr_preserves_graph_and_new_graph_needs_signed_evidence(card):
    folder, sha, _ = card
    record(folder, 'ds-without-gpr', {'number': '1', 'date': '2026-02-05'}, schedule=False)
    assert files.listing(PROJECT, ROW['id'], CUT)['gpr']['source']['sha256'] == sha
    new_sha, _ = record(folder, 'new-graph', {'number': '2', 'date': '2026-02-10'}, pending=True)
    pending = files.listing(PROJECT, ROW['id'], CUT)
    assert pending['gpr']['source']['sha256'] == sha and pending['gpr']['pending'][0]['source']['sha256'] == new_sha
    with pytest.raises(files.ContractFilesProblem, match='подпись'):
        gpr.save(PROJECT, ROW, CUT, new_sha, pending['gpr']['guard'], 'activate',
                 'Подпись контрагента на странице 1', 'synthetic-owner')
    accepted = gpr.save(PROJECT, ROW, CUT, new_sha, pending['gpr']['guard'], 'activate',
                        'Подпись контрагента на странице 1', 'synthetic-owner', counterparty_signed=True)
    assert accepted['gpr']['source']['sha256'] == new_sha
    assert accepted['gpr']['schedule']['anchor'] is None, 'An anchor belongs to one source and edition.'
    assert gpr.events(folder)[0]['cryptographically_validated'] is False


@pytest.mark.parametrize('old_schedule', [None, {'lines': []}])
def test_passive_discovery_of_newer_unsigned_ds_cannot_replace_legacy_graph(card, monkeypatch, old_schedule):
    folder, original_sha, _ = card
    new_sha, recognised = record(folder, 'discovered-ds', {'number': '1', 'date': '2026-02-05'})
    cached = copy.deepcopy(recognised)
    cached.update(reader=14, schedule=old_schedule)
    cached.pop('gpr_pending', None)
    files._json(folder/(new_sha+'.json'), cached)
    monkeypatch.setattr(documents, 'read', lambda raw: copy.deepcopy({key: value for key, value in recognised.items()
        if key not in {'sha256', 'reader', 'filename', 'uploaded_at'}}))
    current = files.listing(PROJECT, ROW['id'], CUT)
    assert current['gpr']['source']['sha256'] == original_sha
    assert current['gpr']['pending'][0]['source']['sha256'] == new_sha
    fresh = files._stored(folder/(new_sha+'.json'))
    assert fresh['gpr_pending'] is True and fresh['reader'] == documents.READER_VERSION
    assert fresh['gpr_discovery']['reason'] == 'new_graph_discovered_by_reader'
    assert fresh['gpr_discovery']['from_reader'] == 14
    assert fresh['gpr_discovery']['source_pdf_sha256'] == new_sha
    assert gpr.events(folder) == [], 'Reader discovery cannot invent an activation event.'
    assert files.listing(PROJECT, ROW['id'], CUT)['gpr']['source']['sha256'] == original_sha
    accepted = gpr.save(PROJECT, ROW, CUT, new_sha, current['gpr']['guard'], 'activate',
                        'Учебная проверка подписи контрагента, страница 1', 'synthetic-owner', counterparty_signed=True)
    assert accepted['gpr']['source']['sha256'] == new_sha
    assert accepted['gpr']['history'][-1]['cryptographically_validated'] is False


def test_sole_discovered_graph_has_readonly_preview_until_explicit_activation(card, monkeypatch):
    folder, sha, recognised = card
    cached = copy.deepcopy(recognised)
    cached.update(reader=13, schedule=None)
    cached.pop('gpr_pending', None)
    files._json(folder/(sha+'.json'), cached)
    monkeypatch.setattr(documents, 'read', lambda raw: copy.deepcopy({key: value for key, value in recognised.items()
        if key not in {'sha256', 'reader', 'filename', 'uploaded_at'}}))
    listed = files.listing(PROJECT, ROW['id'], CUT)
    state = listed['gpr']
    assert state['source'] is None and state['schedule'] is None
    assert state['preview']['source']['sha256'] == sha
    assert state['preview']['presentation']['rows'][0]['bars']
    assert all(bar['state'] in {'unknown','plan'} for bar in state['preview']['presentation']['rows'][0]['bars'])
    assert state['pending'][0]['source']['sha256'] == sha
    with pytest.raises(files.ContractFilesProblem, match='прежняя редакция'):
        gpr.save(PROJECT, ROW, CUT, sha, state['guard'], 'anchor',
                 'Учебный акт передачи площадки', 'synthetic-owner', handover_date='2026-02-02')
    accepted = gpr.save(PROJECT, ROW, CUT, sha, state['guard'], 'activate',
                        'Учебная подпись контрагента, страница 1', 'synthetic-owner', counterparty_signed=True)
    assert accepted['gpr']['source']['sha256'] == sha and accepted['gpr']['preview'] is None


def test_pending_graph_does_not_accept_incomplete_or_other_source_activation(card):
    _, _, source = card
    source['gpr_pending'] = True
    valid = {'schema': gpr.SCHEMA, 'action': 'activate', 'source': gpr.source_key(source),
             'origin': 'manual_document_reference', 'counterparty_signed': True,
             'actor': 'synthetic-owner', 'note': 'Учебная подпись контрагента, страница 1'}
    assert gpr.accepted(source, [valid])
    for change in [{'counterparty_signed': False}, {'schema': 'unsupported'}, {'actor': ''},
                   {'origin': 'parser'}, {'source': {**valid['source'], 'sha256': 'f'*64}}]:
        assert not gpr.accepted(source, [{**valid, **change}])


def test_previously_recognised_legacy_graph_and_exact_activation_survive_reread(card, monkeypatch):
    folder, sha, recognised = card
    recognised['reader'] = 14
    files._json(folder/(sha+'.json'), recognised)
    monkeypatch.setattr(documents, 'read', lambda raw: copy.deepcopy({key: value for key, value in recognised.items()
        if key not in {'sha256', 'reader', 'filename', 'uploaded_at'}}))
    assert files.listing(PROJECT, ROW['id'], CUT)['gpr']['source']['sha256'] == sha
    assert not files._stored(folder/(sha+'.json')).get('gpr_pending')
    # A genuine exact-source activation remains authoritative if an old cache
    # later lacks a graph; neither the price nor scan decision grants it.
    fresh = files._stored(folder/(sha+'.json'))
    fresh['gpr_pending'] = True
    files._json(folder/(sha+'.json'), fresh)
    listed = files.listing(PROJECT, ROW['id'], CUT)
    gpr.save(PROJECT, ROW, CUT, sha, listed['gpr']['guard'], 'activate',
             'Учебная подпись контрагента, страница 1', 'synthetic-owner', counterparty_signed=True)
    history = copy.deepcopy(gpr.events(folder))
    fresh.update(reader=14, schedule=None)
    fresh.pop('gpr_pending')
    files._json(folder/(sha+'.json'), fresh)
    assert files.listing(PROJECT, ROW['id'], CUT)['gpr']['source']['sha256'] == sha
    assert gpr.events(folder) == history


def test_advance_and_handover_are_separate_conditions(card):
    folder, sha, source = card
    from developaid_contract_terms import read
    source['terms'] = read(['Срок начала Работ-с даты оплаты аванса и подписания Сторонами Акта передачи '
                            'Строительной площадки. Срок окончания Работ -не позднее 45 (сорока пяти) дней с даты Начала Работ.'])
    files._json(folder/(sha+'.json'), source)
    handover = change(files.listing(PROJECT, ROW['id'], CUT))
    condition = handover['gpr']['conditions'][0]
    assert condition['duration_days'] == 45 and condition['missing_triggers'] == ['paid_advance']
    assert condition['reference_finish'] is None
    forecast = handover['control']['forecast'] or {}
    assert forecast.get('deadline') is None or not forecast.get('from_register')
    both = change(handover, advance_date='2026-02-06')
    assert both['gpr']['conditions'][0]['start'] == '2026-02-06'
    assert both['gpr']['conditions'][0]['reference_only'] is True


def test_no_money_ratio_or_split_mapping_is_painted_as_physical():
    listed = {'plan': {'editions': [{'in_force': True, 'position_links': [
        {'estimate': 0, 'index': 0, 'lines': [{'code': '1', 'share': .5}, {'code': '2', 'share': .5}]}]}]}}
    rds = {'source': 'ks6a', 'rows': [{'estimate': 0, 'index': 0, 'fact_quantity_ratio': .75,
                                    'day_deviation': None, 'readiness': .9}]}
    assert gpr.physical_overlays(listed, rds) == {}
    schedule = {'lines': [{'code': '1', 'name': 'Работа', 'start': '2026-02-01', 'finish': '2026-02-10'}]}
    display = export.presentation(schedule, {}, CUT)
    assert {bar['state'] for bar in display['rows'][0]['bars']} == {'unknown'}


def test_proven_physical_quantity_is_separate_from_source_calendar_and_its_gap():
    listed = {'plan': {'editions': [{'in_force': True, 'position_links': [
        {'estimate': 0, 'index': 0, 'lines': [{'code': '1', 'share': 1}]}]}]}}
    rds = {'source': 'ks6a', 'rows': [{'estimate': 0, 'index': 0, 'fact_quantity_ratio': .4,
        'plan_quantity_ratio': .8, 'day_deviation': 4, 'fact_quantity': 4, 'contract_quantity': 10, 'unit': 'м3'}]}
    overlays = gpr.physical_overlays(listed, rds)
    schedule = {'lines': [{'code': '1', 'name': 'Работа', 'start': '2026-02-01', 'finish': '2026-02-21',
        'segments': [{'start': '2026-02-01', 'finish': '2026-02-07'},
                     {'start': '2026-02-15', 'finish': '2026-02-21'}]}]}
    shown = export.presentation(schedule, overlays, '2026-02-25')
    bars = shown['rows'][0]['bars']
    assert {bar['state'] for bar in bars} == {'unknown'}
    assert all(bar['end'] <= 7 or bar['start'] >= 14 for bar in bars), 'The source gap cannot become physical work.'
    assert not any(bar.get('overdue') for bar in bars)
    assert shown['rows'][0]['progress']['fraction'] == .4
    assert shown['rows'][0]['progress']['delta_pp'] == -40
    assert 'не подтверждает даты' in shown['legend']


def test_resource_ranges_and_sparse_literal_dates_are_not_interpolated():
    schedule = {'lines': []}
    layout = {'first': 4, 'dates': {4: (dt.date(2026, 11, 19),)*2, 5: (dt.date(2026, 11, 30),)*2}}
    assert documents._resource_row(schedule, ['4.1', 'ИТР', 'чел.', '', '1–2', ''], 'ИТР', 1, 10, layout)
    assert schedule['resources'][0]['period_basis'] == 'literal_date'
    exact = gpr.staffing(schedule, date='2026-11-19')['rows'][0]
    assert exact['plan'] == {'min': 1.0, 'max': 2.0, 'raw': '1–2'} and exact['fact'] is None
    assert gpr.staffing(schedule, date='2026-11-20')['rows'] == []
    assert gpr.staffing(schedule, date='2026-11-30')['rows'][0]['plan'] is None


def test_two_sheet_export_preserves_current_source_and_disjoint_bars(card):
    import developaid_contract_workforce as workforce
    listed = change(files.listing(PROJECT, ROW['id'], CUT))
    listed['rds_comparison'] = {'available': False, 'detail': 'РДС не загружена.'}
    listed['gpr']['overlays'] = {}
    register = {'rows': [ROW], '_workforce_source_guard': workforce.cohort_sources(PROJECT, CUT)}
    listed['gpr']['workforce'] = workforce.from_cached(PROJECT, ROW, register, CUT, listed['gpr'])
    result = {'ok': True, **listed}
    meta = export.bind_snapshot(PROJECT, CUT, ROW['id'], result, ROW)
    result['gpr_export'] = meta
    selected = export.select_snapshot(result, PROJECT, CUT, ROW['id'], meta['revision'])
    book = load_workbook(io.BytesIO(export.workbook(selected, result)))
    assert book.sheetnames == ['ГПР', 'Выполнение', 'Численность подрядчика']
    text = '\n'.join(str(cell.value) for row in book['ГПР'] for cell in row if cell.value is not None)
    provenance = book['ГПР']['A1'].comment.text
    assert listed['gpr']['source']['sha256'] in provenance and listed['gpr']['schedule']['anchor']['event_id'] in provenance
    assert listed['gpr']['source']['sha256'] not in text
    assert 'Редакция ГПР:' in book['ГПР']['A2'].value and 'Срез:' in book['ГПР']['A3'].value
    assert all(sheet.freeze_panes is None for sheet in book), 'The source/name columns must not lock the phone viewport.'
    row = next(row for row in book['ГПР'] if row[1].value == 'Учебная работа')
    colored = [cell.fill.fgColor.rgb for cell in row[6:27]]
    assert colored[:7] == ['00E4DFEC']*7 and colored[7:14] == ['00000000']*7 and colored[14:] == ['00D9D9D9']*7
    assert book['Выполнение'].max_column == 16


def operation_projection_case():
    schedule = {'lines': [{'code': 'G1', 'name': 'Составная конструкция', 'start': '2026-02-01',
        'finish': '2026-02-21', 'segments': [{'start': '2026-02-01', 'finish': '2026-02-07'},
                                          {'start': '2026-02-15', 'finish': '2026-02-21'}]}]}
    listed = {'plan': {'editions': [{'in_force': True, 'position_links': [
        {'estimate': 0, 'index': i, 'status': 'confirmed', 'lines': [{'code': 'G1', 'share': 1}]}
        for i in range(2)]}]}}
    rds = {'available': True, 'source': 'ks6a', 'headings': [{'before_position': 0, 'number': '', 'name': 'Корпус 1'}],
        'rows': [{'estimate': 0, 'index': i, 'number': f'1.{i+1}', 'name': name,
            'start': '2026-02-01', 'finish': '2026-02-21', 'unit': 'м2',
            'contract_quantity': 100, 'fact_quantity': qty, 'fact_quantity_ratio': qty/100,
            'plan_quantity_ratio': .8, 'day_deviation': 4, 'comments': {}}
            for i, (name, qty) in enumerate([('Монтаж каркаса', 40), ('Остекление', 0)])]}
    return listed, rds, schedule


def test_composite_gpr_keeps_known_operation_facts_and_source_gaps():
    listed, rds, schedule = operation_projection_case()
    assert gpr.physical_overlays(listed, rds) == {}, 'Operations are not summed into the parent construction percent.'
    positions = gpr.position_projections(listed, rds, schedule)
    shown = export.presentation(schedule, {}, '2026-02-25', positions)
    assert all(bar['state'] == 'unknown' for bar in shown['rows'][0]['bars'])
    assert [row['quantity']['fact_quantity'] for row in shown['positions']] == [40, 0]
    assert [row['gpr_code'] for row in shown['positions']] == ['G1', 'G1']
    assert all(row['section'] == 'Корпус 1' for row in shown['positions'])
    assert [row['progress']['fraction'] for row in shown['positions']] == [.4, 0]
    assert not any(bar['state'] in {'fact', 'lag'} for row in shown['positions'] for bar in row['bars'])
    assert all(bar['end'] <= 7 or bar['start'] >= 14 for row in shown['positions'] for bar in row['bars'])


@pytest.mark.parametrize('defect', ['no_quantity', 'money_readiness', 'split', 'unproved_days', 'duplicate_code', 'duplicate_binding', 'ratio_mismatch'])
def test_operation_chart_refuses_unattributable_or_money_only_facts(defect):
    listed, rds, schedule = operation_projection_case()
    if defect in {'no_quantity', 'money_readiness'}:
        rds['rows'][0]['fact_quantity'] = rds['rows'][0]['fact_quantity_ratio'] = None
        rds['rows'][0]['readiness'] = .95
    elif defect == 'split':
        listed['plan']['editions'][0]['position_links'][0]['lines'][0]['share'] = .5
    elif defect == 'unproved_days':
        rds['rows'][0]['day_deviation'] = None
    elif defect == 'duplicate_code':
        schedule['lines'].append(copy.deepcopy(schedule['lines'][0]))
    elif defect == 'duplicate_binding':
        listed['plan']['editions'][0]['position_links'].append(
            copy.deepcopy(listed['plan']['editions'][0]['position_links'][0]))
    else:
        rds['rows'][0]['fact_quantity_ratio'] = .9
    positions = gpr.position_projections(listed, rds, schedule)
    assert positions[0]['physical'] is None
    shown = export.presentation(schedule, {}, '2026-02-25', positions)
    refused = next(row for row in shown['positions'] if row['position_key'] == [0, 0])
    assert not any(bar['state'] in {'fact', 'lag'} for bar in refused['bars'])
    assert all(bar['state']=='overdue_unclosed' for bar in refused['reporting']['bars'])
    assert refused['reporting']['checkpoints']==[] and refused['reporting']['forecast'] is None
    if defect == 'unproved_days':
        assert refused['quantity']['fact_quantity'] == 40, 'An unavailable time projection does not remove a known quantity.'


def test_duplicate_operation_binding_also_cannot_paint_a_parent_percent():
    listed, rds, _ = operation_projection_case()
    rds['rows'] = rds['rows'][:1]
    binding = copy.deepcopy(listed['plan']['editions'][0]['position_links'][0])
    listed['plan']['editions'][0]['position_links'] = [binding, copy.deepcopy(binding)]
    assert gpr.physical_overlays(listed, rds) == {}


@pytest.mark.parametrize('partial', [False, True])
def test_source_cash_header_keeps_partial_and_after_cut_amounts_separate(partial):
    source = {'total': None if partial else 100e6, 'work': None if partial else 20e6,
              'material': 80e6, 'known_total': 100e6, 'known_work': 20e6, 'known_material': 80e6}
    comparison = {'source': 'ks6a', 'cut': '2026-11-01', 'statement_summary': {
        'source_dates': ['2026-11-18'], 'historical': {'total': None}, 'cash': {'source': source,
        'current': {'total': 40e6}, 'after_cut': {'total': 60e6}, 'undated': {'total': 0}}}}
    shown = export.statement_projection(comparison)
    text = '\n'.join(export.statement_text(shown))
    assert shown['total'] is source['total'] or shown['total'] == source['total']
    assert 'Всего в исходной КС-6а:' in text and '100,0 млн ₽' in text
    assert 'В учёте на срез: 40,0 млн ₽' in text and 'позже среза: 60,0 млн ₽' in text
    if partial:
        assert 'известная часть 100,0 млн ₽; полный итог не подтверждён' in text
        assert 'Работы: известная часть 20,0 млн ₽; полный итог не подтверждён' in text
        assert shown['total'] is None and shown['work'] is None
    else:
        assert 'известная часть' not in text
    assert export.statement_projection({**comparison, 'source': 'ks2'}) is None


def test_workbook_keeps_operation_facts_mobile_header_and_source_identity(card):
    binding, rds, schedule = operation_projection_case()
    listed = change(files.listing(PROJECT, ROW['id'], CUT))
    listed['plan']['editions'] = binding['plan']['editions']
    rds.update(layout=export.LAYOUT, cut='2026-02-25')
    from developaid_contract_rds import FIELDS
    rds['rows'] = [{**{field: None for field in FIELDS}, **row,
        'plan_quantity': 80, 'quantity_deviation': row['fact_quantity']-80} for row in rds['rows']]
    listed['rds_comparison'] = rds
    listed['gpr']['schedule'] = schedule
    listed['gpr']['overlays'] = {}
    result = {'ok': True, **listed}
    meta = export.bind_snapshot(PROJECT, rds['cut'], ROW['id'], result, ROW)
    book = load_workbook(io.BytesIO(export.workbook(meta, result)))
    assert all(sheet.freeze_panes is None for sheet in book)
    header = '\n'.join(str(book['ГПР'].cell(i, 1).value or '') for i in range(1, 6))
    assert 'Редакция ГПР:' in header and 'Срез: 25.02.2026' in header
    assert not any(word in header for word in ('SHA256', 'event_id', 'cryptograph', "'kind'"))
    assert result['gpr']['source']['sha256'] in book['ГПР']['A1'].comment.text
    source = next(row for row in book['ГПР'] if row[1].value == 'Составная конструкция')
    assert not any(c.fill.fgColor.rgb == '0070AD47' for c in source)
    operation = next(row for row in book['ГПР'] if str(row[1].value or '').startswith('Монтаж каркаса'))
    assert operation[4].value == .4 and operation[4].number_format == '0.0%'
    assert '40 / 100 м2' in operation[1].value
    assert any(rule.type == 'dataBar' for rules in book['ГПР'].conditional_formatting._cf_rules.values() for rule in rules)
    assert not any(c.fill.fgColor.rgb=='0070AD47' for c in operation[6:])
    assert all(json.loads(c.comment.text.splitlines()[-1])['track']=='overdue_without_ks_closure' for c in operation[6:] if c.fill.fgColor.rgb=='00E06666')
    assert all(c.fill.fgColor.rgb == '00000000' for c in operation[13:20]), 'The original gap stays unpainted.'
    zero = next(row for row in book['ГПР'] if str(row[1].value or '').startswith('Остекление'))
    assert zero[4].value == 0 and zero[4].number_format == '0.0%'
    execution = [row for row in book['Выполнение'] if row[1].value in {'Монтаж каркаса', 'Остекление'}]
    assert [row[7].value for row in execution] == [40, 0]
    assert [row[8].value for row in execution] == [.4, 0]


def _parallel_anchor(root, guard, sha, date, start, output):
    monitor._SNAPSHOT_DIR = root
    start.wait(10)
    try:
        gpr.save(PROJECT, ROW, CUT, sha, guard, 'anchor', 'Учебный акт передачи', 'separate-worker', date)
        output.put('saved')
    except files.ContractFilesProblem:
        output.put('stale')


def test_two_workers_cannot_overwrite_the_same_anchor_revision(card):
    folder, sha, _ = card
    initial = files.listing(PROJECT, ROW['id'], CUT)
    context = multiprocessing.get_context('fork')
    start, output = context.Event(), context.Queue()
    workers = [context.Process(target=_parallel_anchor, args=(monitor._SNAPSHOT_DIR,
        initial['gpr']['guard'], sha, date, start, output)) for date in ('2026-02-02', '2026-02-03')]
    for worker in workers:
        worker.start()
    start.set()
    results = [output.get(timeout=15) for _ in workers]
    for worker in workers:
        worker.join(15)
        assert worker.exitcode == 0
    assert sorted(results) == ['saved', 'stale'] and len(gpr.events(folder)) == 1


def finished(client, response):
    assert response.status_code in (200, 202), response.text
    value = response.json()
    until = time.monotonic()+15
    while value.get('pending') and time.monotonic() < until:
        time.sleep(.02)
        response = client.post('/monitor/contracts/result', json={'key': KEY, 'session': 'synthetic-owner', 'ticket': value['ticket']})
        assert response.status_code in (200, 202), response.text
        value = response.json()
    assert not value.get('pending')
    return value


def test_native_admin_route_current_export_and_stale_ticket(card, monkeypatch):
    import main
    monkeypatch.setenv('DEVELOPAID_ADMIN_KEY', KEY)
    monkeypatch.setattr(contracts, 'build', lambda *args, **kwargs: {'rows': [copy.deepcopy(ROW)], 'cut': CUT})
    client = TestClient(main.app)
    base = {'key': KEY, 'session': 'synthetic-owner', 'project': PROJECT, 'cut': CUT, 'contract_id': ROW['id']}
    opened = finished(client, client.post('/monitor/contracts/documents', json=base))
    assert opened['ok'] and opened['gpr_export']['available']
    body = {**base, 'source_sha256': opened['gpr']['source']['sha256'], 'expected_guard': opened['gpr']['guard'],
            'action': 'anchor', 'handover_date': '2026-02-02', 'note': 'Учебный акт передачи площадки'}
    assert client.post('/monitor/contracts/gpr-change', json={**body, 'key': 'wrong'}).status_code == 403
    updated = finished(client, client.post('/monitor/contracts/gpr-change', json=body))
    assert updated['ok'] and updated['gpr']['schedule']['lines'][0]['start'] == '2026-02-02'
    stale = client.post('/monitor/contracts/result', json={'key': KEY, 'session': 'synthetic-owner', 'ticket': opened['ticket']})
    assert stale.status_code == 409
    old = client.post('/monitor/contracts/gpr.xlsx', json={**base, 'ticket': opened['ticket'], 'revision': opened['gpr_export']['revision']})
    assert old.status_code == 409
    fresh = client.post('/monitor/contracts/gpr.xlsx', json={**base, 'ticket': updated['ticket'], 'revision': updated['gpr_export']['revision']})
    assert fresh.status_code == 200 and load_workbook(io.BytesIO(fresh.content)).sheetnames == ['ГПР', 'Выполнение', 'Численность подрядчика']
    assert "filename*=UTF-8''" in fresh.headers['content-disposition']
    assert ROW['contract'] in updated['gpr_export']['filename'] and PROJECT in updated['gpr_export']['filename']


@pytest.mark.parametrize('width', [390, 1440])
def test_native_popup_gantt_anchor_reload_and_two_sheet_download(card, width, tmp_path):
    from playwright.sync_api import expect
    from tests.test_monitor_cumulative_controls import browser_page
    import developaid_contract_rds as rds
    response_state = {}
    captured = []
    def snapshot():
        listed = files.listing(PROJECT, ROW['id'], CUT)
        listed['rds_comparison'] = rds.build(listed)
        listed['gpr']['overlays'] = gpr.physical_overlays(listed, listed['rds_comparison'])
        listed['gpr']['presentation'] = export.presentation(listed['gpr']['schedule'], listed['gpr']['overlays'], CUT)
        listed['gpr_export'] = export.bind_snapshot(PROJECT, CUT, ROW['id'], listed, ROW)
        listed['comparison_export'] = old_export.bind_snapshot(PROJECT, CUT, ROW['id'], listed, ROW)
        response_state.clear()
        response_state.update(ok=True, pending=False, ticket='c'*32, **listed)
        return copy.deepcopy(response_state)
    def change_route(route):
        body = route.request.post_data_json
        captured.append(body)
        gpr.save(PROJECT, ROW, CUT, body['source_sha256'], body['expected_guard'], body['action'], body['note'],
                 'browser-owner', body.get('handover_date', ''), body.get('advance_date', ''))
        route.fulfill(json=snapshot())
    with browser_page(width) as (page, responses, errors):
        responses.data['rows'] = [copy.deepcopy(ROW)]
        page.route('**/monitor/contracts/documents', lambda route: route.fulfill(json=snapshot()))
        page.route('**/monitor/contracts/gpr-change', change_route)
        def download_route(route):
            body = route.request.post_data_json
            assert body['revision'] == response_state['gpr_export']['revision']
            assert body['contract_id'] == ROW['id'] and 'selected_tokens' not in body
            raw = export.workbook(response_state['gpr_export'], response_state)
            route.fulfill(body=raw, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                          headers={'Content-Disposition': 'attachment; filename="test-gpr-performance.xlsx"'})
        page.route('**/monitor/contracts/gpr.xlsx', download_route)
        page.locator('#contractsTab').click()
        page.locator(f'tr[data-contract-id="{ROW["id"]}"] .contract-open').click()
        page.locator('#contractGpr > summary').click()
        expect(page.locator('#contractGprHandover')).to_be_visible()
        expect(page.locator('#contractGprBody')).to_contain_text('дата начала не указана')
        # SVG defs contain a hatch sample; only direct plan rectangles are intervals.
        intervals = page.locator('.contract-gpr-track svg > rect')
        assert intervals.count() == 2, 'The two source intervals must remain separate.'
        geometry = intervals.evaluate_all('(nodes)=>nodes.map(n=>({x:+n.getAttribute("x"),width:+n.getAttribute("width")}))')
        assert geometry[0]['width'] > 0 and geometry[1]['width'] > 0
        assert geometry[0]['x'] + geometry[0]['width'] < geometry[1]['x'], 'The source gap must remain a gap.'
        assert page.locator('.contract-gpr-track rect[fill="#70AD47"]').count() == 0
        page.locator('#contractGprHandover').fill('2026-02-02')
        page.locator('#contractGprReference').fill('Учебный акт передачи, страница 1')
        page.locator('#contractGprSave').click()
        expect(page.locator('.contract-gpr-name').filter(has_text='Учебная работа')).to_contain_text('02.02.2026 — 22.02.2026')
        assert captured[0]['source_sha256'] == card[1] and captured[0]['expected_guard']
        expect(page.locator('#contractGprDownload')).to_be_enabled()
        with page.expect_download() as transfer:
            page.locator('#contractGprDownload').click()
        target = tmp_path/f'gpr-performance-{width}.xlsx'
        assert ROW['contract'] in transfer.value.suggested_filename and PROJECT in transfer.value.suggested_filename
        transfer.value.save_as(target)
        assert load_workbook(target).sheetnames == ['ГПР', 'Выполнение', 'Численность подрядчика']
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert page.locator('#contractGpr').evaluate('(element)=>element.getBoundingClientRect().right<=innerWidth')
        page.screenshot(path=str(tmp_path/f'gpr-popup-{width}.png'), full_page=True)
        # Exercise the exact PAGE renderer with an attributed physical DTO.
        # Native physical attribution and refusal are covered separately above.
        physical = copy.deepcopy(response_state['gpr'])
        physical['overlays'] = {'1': {'fact_fraction': .25, 'planned_fraction': .5,
            'fact_quantity': 2.5, 'contract_quantity': 10, 'unit': 'м3', 'basis': 'physical_cut_projection'}}
        physical['presentation'] = export.presentation(physical['schedule'], physical['overlays'], CUT)
        page.evaluate('(state)=>renderContractGpr(state)', physical)
        assert page.locator('.contract-gpr-track rect[fill="#70AD47"]').count() == 0
        assert page.locator('.contract-gpr-track rect[fill="#E06666"]').count() == 0
        assert page.locator('.contract-gpr-progress-fill').count() == 1
        assert page.locator('.contract-gpr-progress-gap').count() == 1
        # Owner refinement: one report-state plan track replaces the old
        # earned-duration model. Missing period quantities cannot paint history.
        assert page.locator('.contract-gpr-equivalent-track').count() == 0
        assert page.locator('[data-report-state]').count() == 0
        expect(page.locator('.contract-gpr-report-note').first).to_contain_text('не восстановлены')
        assert page.locator('.contract-gpr-track rect[fill="#D9D9D9"]').count()+page.locator('.contract-gpr-track rect[fill="#E4DFEC"]').count() == 2
        expect(page.locator('#contractGprBody')).to_contain_text('не подтверждает даты производства')
        page.screenshot(path=str(tmp_path/f'gpr-physical-projection-{width}.png'), full_page=True)
        child_listed, child_rds, child_schedule = operation_projection_case()
        physical['schedule'] = child_schedule
        physical['overlays'] = {}
        physical['presentation'] = export.presentation(child_schedule, {}, '2026-02-25',
            gpr.position_projections(child_listed, child_rds, child_schedule))
        page.evaluate('(state)=>renderContractGpr(state)', physical)
        expect(page.locator('.contract-gpr-position')).to_have_count(2)
        expect(page.locator('.contract-gpr-position[data-rds-position="0:0"]')).to_contain_text('Монтаж каркаса')
        expect(page.locator('.contract-gpr-position[data-rds-position="0:0"]')).to_contain_text('40')
        assert page.locator('.contract-gpr-position[data-rds-position="0:0"] .contract-gpr-progress[data-physical-nonzero="true"]').count() == 1
        assert page.locator('.contract-gpr-position[data-rds-position="0:1"] .contract-gpr-meter').get_attribute('aria-valuenow') == '0'
        assert page.locator('.contract-gpr-position[data-rds-position="0:1"] .contract-gpr-progress-gap').count() == 1
        assert page.locator('.contract-gpr-position .contract-gpr-track rect[fill="#70AD47"]').count() == 0
        assert page.locator('.contract-gpr-position .contract-gpr-track [data-report-state="overdue"]').count() == 0
        assert page.locator('.contract-gpr-position .contract-gpr-track [data-report-state="overdue_unclosed"]').count() == 2
        assert page.locator('.contract-gpr-source-chart rect[fill="#70AD47"]').count() == 0
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path=str(tmp_path/f'gpr-operation-facts-{width}.png'), full_page=True)
        physical['presentation']['statement'] = {'total': None, 'known_total': 100e6, 'work': None,
            'known_work': 20e6, 'material': 80e6, 'known_material': 80e6, 'source_dates': ['2026-11-18'],
            'current': {'total': 40e6}, 'after_cut': {'total': 60e6}, 'undated': {'total': 0}}
        page.evaluate('(state)=>renderContractGpr(state)', physical)
        cash_text = page.locator('.contract-gpr-statement').inner_text().replace('\u00a0', '')
        assert 'известная часть 100000000 ₽; полный итог не подтверждён' in cash_text
        assert 'Всего в исходной КС-6а' in cash_text and 'позже среза: 60000000 ₽' in cash_text
        assert 'В учёте на срез: 40000000 ₽' in cash_text
        pending_records = gpr.project_records([{**card[2], 'gpr_pending': True}], [])
        pending = gpr.view(PROJECT, ROW['id'], pending_records, [card[0]], CUT)
        page.evaluate('(state)=>renderContractGpr(state)', pending)
        expect(page.locator('#contractGprBody')).to_contain_text('Предварительный просмотр обнаруженного ГПР')
        expect(page.locator('#contractGprDownload')).to_be_disabled()
        assert page.locator('#contractGprHandover').count() == 0
        choices = page.locator('.contract-gpr-source-selection')
        expect(choices).not_to_have_attribute('open', '')
        choices.locator(':scope > summary').click()
        expect(choices.locator('[data-gpr-activate]')).to_be_visible()
        assert page.locator('.contract-gpr-track rect[fill="#70AD47"]').count() == 0
        assert page.locator('.contract-gpr-track rect[fill="#E06666"]').count() == 0
        assert page.locator('.contract-gpr-track rect[fill="#D9D9D9"]').count()+page.locator('.contract-gpr-track rect[fill="#E4DFEC"]').count() == 2
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path=str(tmp_path/f'gpr-pending-preview-{width}.png'), full_page=True)
        page.locator('#contractDialogClose').click()
        page.locator(f'tr[data-contract-id="{ROW["id"]}"] .contract-open').click()
        page.locator('#contractGpr > summary').click()
        expect(page.locator('#contractGprHandover')).to_have_value('2026-02-02')
        page.locator('#contractGprReference').fill('Ошибочная дата снята по учебному акту')
        page.locator('#contractGprClear').click()
        expect(page.locator('#contractGprHandover')).to_have_value('')
        expect(page.locator('#contractGprBody')).to_contain_text('дата начала не указана')
        assert not errors
