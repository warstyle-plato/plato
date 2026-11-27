"""A derived card export uses its saved DTO, never source books or client amounts."""
import ast
import asyncio
import copy
import datetime as dt
import io
import json
import logging
from pathlib import Path
import re
from types import SimpleNamespace
import time
import threading
import zipfile

from fastapi import HTTPException
from openpyxl import load_workbook
from pydantic import BaseModel, Field, ValidationError, field_validator
import pytest
from starlette.responses import Response

import developaid_contract_comparison as comparison
import developaid_contract_control as control
import developaid_contract_comparison_export as export
import developaid_management_report_jobs as jobs

ROOT = Path(__file__).resolve().parents[1]
PROJECT, CUT, CONTRACT, TICKET = "Учебный проект", "2026-03-05", "c" * 64, "a" * 32
KEY, SESSION = "synthetic-export-admin", "synthetic-owner"


from tests.contract_rds_fixtures import native_card


def xlsx(cached, tokens=None, **kwargs):
    binding = cached["comparison_export"]
    selected = binding["row_tokens"] if tokens is None else tokens
    meta, table, rows = export.select_snapshot(cached, PROJECT, binding["cut"], CONTRACT, binding["revision"], selected)
    return export.workbook(meta, table, rows, **kwargs)


def table(raw, *, data_only=False):
    sheet = load_workbook(io.BytesIO(raw), data_only=data_only).active
    header = next(i for i, row in enumerate(sheet.values, 1) if row[0] == "№")
    return sheet, header


def test_native_known_values_zero_units_and_dates_survive_roundtrip():
    cached = native_card()
    before = copy.deepcopy(cached)
    sheet, header = table(xlsx(cached), data_only=True)
    assert len(sheet.parent.worksheets) == 1 and sheet.max_column == 16
    first, zero = cached['rds_comparison']['rows']
    assert [sheet.cell(header+1, i).value for i in (6,7,8,9,10,11,12,13,14)] == [10,.5,6,.3,-4,500,300,-200,2]
    assert sheet.cell(header+1,3).value == 'м3'
    assert sheet.cell(header+1,4).value.date() == dt.date(2026,3,1)
    assert sheet.cell(header+1,5).value.date() == dt.date(2026,3,10)
    assert sheet.cell(header+2,8).value == 0 and sheet.cell(header+2,8).data_type == 'n'
    assert sheet.cell(6,14).value == 'Отставание на дату среза, дни'
    assert sheet.cell(header+1,14).number_format.startswith('[Red]+0')
    assert 'плюс — отставание' in sheet['N6'].comment.text
    assert sheet.freeze_panes is None and sheet.auto_filter.ref.startswith('A6:P')
    assert sheet.page_setup.orientation == 'landscape' and str(sheet.page_setup.paperSize) == sheet.PAPERSIZE_A3
    assert all(cell.data_type!='e' for row in sheet for cell in row)
    assert cached == before


def test_remaining_start_source_and_missing_data_are_comments_not_extra_rows_or_sheets():
    cached = native_card()
    cached['rds_comparison'].update(remaining_start='2026-02-01',remaining_source='Учебное ДС № 1',
                                  data_gaps=['В карточке нет акта КС-2 № 7.'])
    cached['comparison_export'] = export.bind_snapshot(PROJECT,CUT,CONTRACT,cached,{})
    sheet, header = table(xlsx(cached))
    assert '01.02.2026' in sheet['F6'].comment.text and 'Учебное ДС № 1' in sheet['F6'].comment.text
    assert 'нет акта' in sheet['A3'].comment.text
    assert sheet.max_row == header+2 and len(sheet.parent.worksheets) == 1


def test_unknown_and_no_rds_are_not_zero_or_pseudo_estimate_rows():
    sheet, header = table(xlsx(native_card(unknown=True)), data_only=True)
    assert sheet.cell(header+1,6).value == 10
    assert all(sheet.cell(header+1,i).value is None for i in (8,9,12,14,15,16))
    assert sheet.cell(header+1,10).value is None
    assert sheet.cell(header+1,13).value is None
    assert 'не подтверждена' in sheet.cell(header+1,8).comment.text
    empty = native_card(empty=True)
    assert empty['comparison_export']['available'] is False
    with pytest.raises(export.ExportProblem):
        export.select_snapshot(empty, PROJECT, CUT, CONTRACT, '0'*64, [])


def test_completed_row_has_signed_canonical_days_and_no_forecast_columns():
    cached=native_card(finished=True)
    sheet,header=table(xlsx(cached), data_only=True)
    canonical=cached['control']['lines'][0]
    assert sheet.cell(header+1,14).value == canonical['lag_days']-canonical['ahead_days']
    assert sheet.cell(header+1,15).value.date() == dt.date(2026,3,14)
    assert sheet.cell(header+1,16).value == 4
    assert sheet.cell(header+1,14).value != 4  # Finished four days after GPR is a different metric.
    assert not any('Прогноз' in str(cell.value) for cell in sheet[header])


def test_tokens_bind_revision_ordinal_and_digest_even_with_duplicate_codes():
    cached=native_card()
    cached['rds_comparison']['rows'] *= 2
    cached['comparison_export']=export.bind_snapshot(PROJECT,CUT,CONTRACT,cached,{})
    meta=cached['comparison_export']
    assert len(set(meta['row_tokens'])) == 4
    _,_,rows=export.select_snapshot(cached,PROJECT,CUT,CONTRACT,meta['revision'],meta['row_tokens'])
    assert rows == cached['rds_comparison']['rows']
    changed=copy.deepcopy(cached);changed['rds_comparison']['rows'][0]['fact']=999
    with pytest.raises(export.ExportProblem,match='Версия'): xlsx(changed)
    changed=copy.deepcopy(cached);changed['fact']['rds_positions'][0]['amount']=999
    with pytest.raises(export.ExportProblem,match='Версия'): xlsx(changed)
    with pytest.raises(export.ExportProblem): xlsx(cached,[meta['row_tokens'][0]]*2)
    with pytest.raises(export.ExportProblem): xlsx(cached,['0'*64])


@pytest.mark.parametrize('field,value',[('project','Другой'),('cut','2026-03-04'),('contract_id','b'*64)])
def test_snapshot_context_cannot_be_relabelled(field,value):
    cached=native_card()
    params=dict(project=PROJECT,cut=CUT,contract_id=CONTRACT,revision=cached['comparison_export']['revision'],selected_tokens=[])
    params[field]=value
    with pytest.raises(export.ExportProblem,match='другому'):export.select_snapshot(cached,**params)


def test_full_rds_scope_refuses_hidden_gpr_filter_or_partial_selection():
    cached=native_card();tokens=cached['comparison_export']['row_tokens']
    for selected in ([],tokens[:1],list(reversed(tokens))):
        with pytest.raises(export.ExportProblem):xlsx(cached,selected)
    with pytest.raises(export.ExportProblem):xlsx(cached,filter='behind')
    with pytest.raises(export.ExportProblem):xlsx(cached,query='кладка')


def test_binding_cannot_relabel_a_different_native_cut_or_contract():
    cached=native_card()
    assert export.bind_snapshot(PROJECT,'2026-03-04',CONTRACT,cached,{})['available'] is False
    assert export.bind_snapshot(PROJECT,CUT,'b'*64,cached,{})['available'] is False


@pytest.mark.parametrize('prefix',['=HYPERLINK("https://invalid.example","x")','+cmd','-cmd','@SUM(1,2)'])
def test_source_strings_remain_literal_without_formulas_macros_or_links(prefix):
    cached=native_card();cached['rds_comparison']['rows'][0]['name']=prefix
    cached['comparison_export']=export.bind_snapshot(PROJECT,CUT,CONTRACT,cached,{'contract':prefix})
    raw=xlsx(cached);sheet,header=table(raw)
    assert sheet.cell(header+1,2).value==prefix
    assert all(cell.column in (10,13,16) for row in sheet for cell in row if cell.data_type=='f')
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        assert not any('externalLink' in name or 'vbaProject' in name for name in archive.namelist())
        assert not any(b'TargetMode="External"' in archive.read(name) for name in archive.namelist() if name.endswith('.rels'))
        assert all(cell.column in (10,13,16) for row in sheet for cell in row if cell.data_type=='f')


@pytest.mark.parametrize('name',['x'*32768,'bad\x01text'])
def test_unrepresentable_text_is_refused_instead_of_silently_truncated(name):
    cached=native_card();cached['rds_comparison']['rows'][0]['name']=name
    cached['comparison_export']=export.bind_snapshot(PROJECT,CUT,CONTRACT,cached,{})
    with pytest.raises(export.ExportProblem):xlsx(cached)


def test_row_and_output_caps_fail_with_a_status_instead_of_an_empty_file(monkeypatch):
    cached=native_card();cached['rds_comparison']['rows']*=export.MAX_ROWS
    assert export.bind_snapshot(PROJECT,CUT,CONTRACT,cached,{})['available'] is False
    monkeypatch.setattr(export,'MAX_XLSX_BYTES',1)
    with pytest.raises(export.ExportProblem,match='Файл слишком большой'):xlsx(native_card())


def test_writer_does_not_rescan_the_entire_sheet_for_each_work(monkeypatch):
    from openpyxl.worksheet.worksheet import Worksheet
    cached=native_card();cached['rds_comparison']['rows']*=100
    cached['comparison_export']=export.bind_snapshot(PROJECT,CUT,CONTRACT,cached,{})
    original=Worksheet.max_row.fget;scans=[]
    def count_scans(sheet):
        scans.append(1);return original(sheet)
    monkeypatch.setattr(Worksheet,'max_row',property(count_scans))
    assert xlsx(cached).startswith(b'PK') and len(scans)<20


@pytest.fixture
def route(tmp_path, monkeypatch):
    source = ast.parse((ROOT / "engine/monitor_cumulative.py").read_bytes())
    names = {"MonitorCumulativeAuth", "MonitorCumulativeProject", "MonitorContractsBuild", "MonitorContractDocuments",
             "MonitorContractComparisonExport", "_monitor_cumulative_day", "_monitor_contract_gpr_current",
             "monitor_contract_comparison_xlsx"}
    nodes = [n for n in source.body if isinstance(n, (ast.ClassDef, ast.FunctionDef)) and n.name in names]
    key = [KEY]
    def require_key(given, _section, _session):
        if given != key[0]:
            raise HTTPException(403, "Нет доступа")
    scope = dict(BaseModel=BaseModel, _CumulativeField=Field, _CumulativeValidator=field_validator, re=re,
                 Response=Response, HTTPException=HTTPException, logging=logging,
                 app=SimpleNamespace(post=lambda *a, **k: lambda fn: fn), _require_admin_key=require_key,
                 _env_str=lambda *a: key[0], developaid_monitor=SimpleNamespace(_SNAPSHOT_DIR=tmp_path))
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "<exact-native-export-route>", "exec"), scope)
    cached = native_card()
    cached['contract_calculation_revision'] = control.CALCULATION_REVISION
    monkeypatch.setattr(jobs.Store, "start", lambda *a, **k: pytest.fail("new job during export"))
    root = tmp_path / ".cumulative_jobs"
    root.mkdir()
    profile = "monitor-cumulative-v1:contracts"
    import developaid_monitor as monitor
    import developaid_monitor_ledgers as ledgers
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path)
    metadata = dict(ticket=TICKET, owner=jobs.owner_binding(KEY, SESSION, profile), profile=profile,
                    request="synthetic", created=time.time(), state="done",
                    context=ledgers.snapshot_job_context(PROJECT))
    (root / (TICKET + ".json")).write_text(json.dumps(metadata))
    (root / (TICKET + ".result")).write_text(json.dumps(cached))
    values = dict(key=KEY, session=SESSION, project=PROJECT, cut=CUT, contract_id=CONTRACT,
                  ticket=TICKET, revision=cached["comparison_export"]["revision"],
                  selected_tokens=cached["comparison_export"]["row_tokens"])
    return scope, key, root, cached, values


def test_native_route_reads_only_completed_owner_bound_job_and_returns_private_xlsx(route, monkeypatch):
    scope, _, _, _, values = route
    monkeypatch.setattr(control, "build", lambda *a: pytest.fail("new calculation during export"))
    result = scope["monitor_contract_comparison_xlsx"](scope["MonitorContractComparisonExport"](**values))
    assert result.status_code == 200 and result.headers["cache-control"] == "private, no-store"
    assert result.headers["content-disposition"] == f'attachment; filename="contract-plan-fact-{CUT}.xlsx"'
    assert result.body.startswith(b"PK") and KEY.encode() not in result.body and SESSION.encode() not in result.body
    with zipfile.ZipFile(io.BytesIO(result.body)) as archive:
        for name in archive.namelist():
            content = archive.read(name)
            assert KEY.encode() not in content and SESSION.encode() not in content


def test_denied_current_key_precedes_cache_io(route, monkeypatch):
    scope, _, _, _, values = route
    monkeypatch.setattr(jobs, "Store", lambda *a: pytest.fail("cache before authentication"))
    with pytest.raises(HTTPException) as denied:
        scope["monitor_contract_comparison_xlsx"](scope["MonitorContractComparisonExport"](**{**values, "key": "wrong"}))
    assert denied.value.status_code == 403


@pytest.mark.parametrize("change", ["owner", "rotation", "expired", "revision", "project", "pending"])
def test_unavailable_or_stale_jobs_do_not_rebuild_or_export(route, change, monkeypatch):
    scope, key, root, _, values = route
    if change == "owner":
        values["session"] = "another-owner"
    elif change == "rotation":
        key[0] = values["key"] = "rotated-synthetic-admin"
    elif change == "expired":
        path = root / (TICKET + ".json")
        meta = json.loads(path.read_text()); meta["created"] -= jobs.TTL_SECONDS + 1
        path.write_text(json.dumps(meta))
    elif change == "revision":
        values["revision"] = "0" * 64
    elif change == "project":
        values["project"] = "Другой"
    else:
        monkeypatch.setattr(jobs.Store, "poll", lambda *a: {"pending": True})
    with pytest.raises(HTTPException) as unavailable:
        scope["monitor_contract_comparison_xlsx"](scope["MonitorContractComparisonExport"](**values))
    assert unavailable.value.status_code == 409


def test_request_rejects_client_financial_rows_and_duplicate_or_invalid_tokens(route):
    scope, _, _, _, values = route
    for extra in [{"rows": [{"fact": 999}]}, {"selected_tokens": ["bad"]},
                  {"selected_tokens": values["selected_tokens"] * 2}, {"selected_tokens": [0]}]:
        with pytest.raises(ValidationError):
            scope["MonitorContractComparisonExport"](**{**values, **extra})


def test_legacy_ticket_refuses_export_and_normal_new_admission_builds_new_snapshot(tmp_path, monkeypatch):
    cached = native_card()
    legacy = copy.deepcopy(cached)
    legacy.pop("comparison_export")
    old, new = "1" * 32, "2" * 32
    root = tmp_path / "jobs"
    root.mkdir()
    store = jobs.Store(root)
    profile = "monitor-cumulative-v1:contracts"
    owner = jobs.owner_binding(KEY, SESSION, profile)
    old_params = dict(operation="documents", click=old, project=PROJECT, cut=CUT, contract_id=CONTRACT)
    fingerprint = jobs.hashlib.sha256(json.dumps(old_params, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    (root / (old + ".json")).write_text(json.dumps(dict(ticket=old, owner=owner, profile=profile,
        request=fingerprint, created=time.time(), state="done")))
    (root / (old + ".result")).write_text(json.dumps(legacy))
    same = store.start(owner, profile, old_params, lambda: pytest.fail("old completed job rebuilt"), old)
    with pytest.raises(export.ExportProblem) as unbound:
        export.select_snapshot(same, PROJECT, CUT, CONTRACT, "0" * 64, [])
    assert unbound.value.status == 409
    workers = []
    class HeldThread:
        def __init__(self, *, target, args, **kwargs):
            workers.append((target, args))
        def start(self):
            pass
    monkeypatch.setattr(jobs.threading, "Thread", HeldThread)
    pending = store.start(owner, profile, {**old_params, "click": new}, lambda: cached, new)
    assert pending["pending"] and pending["ticket"] == new and len(workers) == 1
    target, args = workers[0]
    target(*args)  # Exercise the exact worker after releasing the admission lock.
    ready = store.poll(new, owner, profile)
    meta, _, rows = export.select_snapshot(ready, PROJECT, CUT, CONTRACT,
        ready["comparison_export"]["revision"], ready["comparison_export"]["row_tokens"])
    assert meta["available"] and len(rows) == 2


def test_sync_export_writer_is_offloaded_and_does_not_block_the_event_loop(route, monkeypatch):
    from fastapi import FastAPI
    scope, _, _, _, values = route
    app = FastAPI()
    app.post("/comparison.xlsx")(scope["monitor_contract_comparison_xlsx"])
    @app.get("/ping")
    async def ping():
        return {"ok": True}
    started, release = threading.Event(), threading.Event()
    native = export.workbook
    worker_ids = []
    def held_writer(*args, **kwargs):
        worker_ids.append(threading.get_ident())
        started.set()
        assert release.wait(2), "event loop could not release the writer"
        return native(*args, **kwargs)
    monkeypatch.setattr(export, "workbook", held_writer)
    async def request(path, body=None):
        messages, sent = [], False
        async def receive():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": json.dumps(body).encode() if body else b"", "more_body": False}
            return {"type": "http.disconnect"}
        async def send(message):
            messages.append(message)
        await app({"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                   "method": "POST" if body else "GET", "scheme": "http", "path": path,
                   "raw_path": path.encode(), "query_string": b"", "root_path": "",
                   "headers": [(b"content-type", b"application/json")],
                   "server": ("synthetic.local", 80), "client": ("synthetic", 1)}, receive, send)
        status = next(m["status"] for m in messages if m["type"] == "http.response.start")
        return status, b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
    async def exercise():
        loop_thread = threading.get_ident()
        running = asyncio.create_task(request("/comparison.xlsx", values))
        try:
            deadline = time.monotonic() + 1
            while not started.is_set() and time.monotonic() < deadline:
                await asyncio.sleep(.005)
            assert started.is_set() and worker_ids != [loop_thread]
            status, body = await request("/ping")
            assert status == 200 and json.loads(body) == {"ok": True}
            assert not release.is_set()
        finally:
            release.set()
        status, body = await running
        assert status == 200 and body.startswith(b"PK")
    asyncio.run(exercise())


def test_previous_export_v4_schema_cannot_be_reused_as_current_snapshot():
    cached=native_card();binding=cached['comparison_export']
    assert binding['schema']==export.SCHEMA and export.SCHEMA!='contract-rds-plan-fact-export-v4'
    cached['comparison_export']={**binding,'schema':'contract-rds-plan-fact-export-v4'}
    with pytest.raises(export.ExportProblem,match='Версия таблицы изменилась'):
        export.select_snapshot(cached,PROJECT,binding['cut'],CONTRACT,binding['revision'],binding['row_tokens'])


@pytest.mark.parametrize('previous_schema',['contract-rds-plan-fact-export-v5','contract-rds-plan-fact-export-v6','contract-rds-plan-fact-export-v7'])
def test_previous_runtime_export_is_rejected_even_with_unchanged_sources(monkeypatch,previous_schema):
    cached=native_card()
    schema=export.SCHEMA
    monkeypatch.setattr(export,'SCHEMA',previous_schema)
    cached['comparison_export']=export.bind_snapshot(PROJECT,CUT,CONTRACT,cached,{})
    monkeypatch.setattr(export,'SCHEMA',schema)
    with pytest.raises(export.ExportProblem,match='Версия'):
        xlsx(cached)
