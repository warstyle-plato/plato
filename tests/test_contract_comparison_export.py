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


def native_card(*, unknown=False, empty=False, finished=False):
    # Reuse the existing native control fixture's exact pure data helpers;
    # importing its full module would unnecessarily start the application.
    module = ast.parse((ROOT / "tests/test_contract_control_reports_lag_and_forecast.py").read_bytes())
    nodes = [n for n in module.body if isinstance(n, ast.FunctionDef) and n.name in {"_plan", "_fact"}
             or isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "LINE" for t in n.targets)]
    scope = {}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "<native-pure-control-fixture>", "exec"), scope)
    line = scope["LINE"]
    cut = "2026-03-15" if finished else CUT
    planned = scope["_plan"](cut, line, {**line, "code": "3.2", "name": "Работа с нулевым фактом", "volume": None})
    planned["editions"][0].update(title="Учебная редакция", date="2026-02-01",
                                  estimate="Расчёт.pdf", schedule="ГПР.pdf")
    performed = (("3.1", 1000.0, [{"unit": "м3", "quantity": 20.0}], "2026-03-14", True)
                 if finished else ("3.1", 300.0, [{"unit": "м3", "quantity": 6.0}]))
    actual = scope["_fact"](performed, ("3.2", 0.0, []))
    actual["source"] = "ks6a"
    if unknown:
        actual["note"] = "Дата выполнения не подтверждена."
    if empty:
        planned = {"editions": []}
    listed = {"plan": planned, "fact": actual, "documents": [],
              "control": control.build(planned, actual, None, "", cut)}
    cached = {"ok": True, "pending": False, "contract_id": CONTRACT, "documents": [],
              "comparison": comparison.build(listed, cut)}
    cached["comparison_export"] = export.bind_snapshot(PROJECT, cut, CONTRACT, cached,
                                                       {"contract": "Т-1", "contractor": "Учебный подрядчик"})
    return cached


def xlsx(cached, tokens=None, **kwargs):
    binding = cached["comparison_export"]
    selected = binding["row_tokens"] if tokens is None else tokens
    meta, table, rows = export.select_snapshot(cached, PROJECT, binding["cut"], CONTRACT, binding["revision"], selected)
    return export.workbook(meta, table, rows, **kwargs)


def table(raw):
    sheet = load_workbook(io.BytesIO(raw), data_only=False).active
    header = next(i for i, row in enumerate(sheet.values, 1) if row[0] == "Работа или поставка / единица")
    return sheet, header


def test_native_known_values_zero_units_and_dates_survive_roundtrip():
    cached = native_card()
    before = copy.deepcopy(cached)
    sheet, header = table(xlsx(cached))
    natural, money = cached["comparison"]["lines"]
    assert sheet.max_column == 7
    assert [sheet.cell(header + 1, i).value for i in (2, 3, 4, 5)] == [natural[k] for k in ("contract_total", "planned", "fact", "deviation")]
    assert "м3" in sheet.cell(header + 1, 1).value
    assert sheet.cell(header + 1, 6).value.date() == dt.date.fromisoformat(natural["due"])
    assert sheet.cell(header + 1, 7).value.date() == dt.date.fromisoformat(natural["forecast_finish"])
    assert sheet.cell(header + 3, 4).value == money["fact"] == 0
    assert sheet.cell(header + 3, 4).data_type == "n"
    assert "₽" in sheet.cell(header + 3, 4).number_format
    assert cached == before


def test_remaining_start_source_and_missing_data_remain_inspectable_in_excel():
    cached = native_card()
    cached['comparison']['edition'].update(start='2026-02-01', start_source={'title': 'Учебное ДС № 1'})
    cached['comparison']['data_gaps'] = ['В карточке нет акта КС-2 № 7.']
    cached['comparison_export'] = export.bind_snapshot(PROJECT, CUT, CONTRACT, cached, {'contract': 'Т-1'})
    sheet, _ = table(xlsx(cached))
    values = list(sheet.values)
    start = next(row for row in values if row[0] == 'Начало учёта оставшихся работ')
    assert start[1].date() == dt.date(2026, 2, 1)
    assert any(row[0] == 'Источник начала учёта: Учебное ДС № 1' for row in values)
    assert any(row[0] == 'В карточке нет акта КС-2 № 7.' for row in values)


def test_unknown_and_empty_native_comparisons_are_qualified_not_zero():
    cached = native_card(unknown=True)
    sheet, header = table(xlsx(cached))
    assert sheet.cell(header + 1, 3).value is not None  # Known plan survives.
    assert sheet.cell(header + 1, 4).value is None
    assert sheet.cell(header + 1, 5).value is None
    text = "\n".join(str(c.value) for row in sheet for c in row if c.value is not None)
    assert "Дата выполнения не подтверждена" in text and "Факт неизвестен" in text
    empty = native_card(empty=True)
    sheet, header = table(xlsx(empty))
    assert "нет действующей редакции плана" in sheet.cell(header + 1, 1).value
    assert all(sheet.cell(header + 1, n).value is None for n in range(2, 8))


def test_completed_period_date_and_forecast_qualification_stay_visible():
    cached = native_card(finished=True)
    sheet, header = table(xlsx(cached))
    assert sheet.cell(header + 1, 7).value.date() == dt.date(2026, 3, 14)
    assert "По периоду КС, завершено" in sheet.cell(header + 2, 7).value
    assert "Позже срока на 4 дн." in sheet.cell(header + 2, 7).value
    date_row = next(row for row in sheet if row[0].value == "Дата редакции")
    assert date_row[1].value.date() == dt.date(2026, 2, 1)
    assert any(c.value == "ГПР: ГПР.pdf" for row in sheet for c in row)


def test_tokens_bind_revision_ordinal_and_digest_even_with_duplicate_codes():
    cached = native_card()
    cached["comparison"]["lines"] *= 2
    cached["comparison_export"] = export.bind_snapshot(PROJECT, CUT, CONTRACT, cached, {})
    meta = cached["comparison_export"]
    assert len(set(meta["row_tokens"])) == 4
    _, _, rows = export.select_snapshot(cached, PROJECT, CUT, CONTRACT, meta["revision"], [meta["row_tokens"][2]])
    assert rows == [cached["comparison"]["lines"][2]]
    changed = copy.deepcopy(cached)
    changed["comparison"]["lines"][0]["fact"] = 999
    with pytest.raises(export.ExportProblem, match="Версия"):
        xlsx(changed)
    with pytest.raises(export.ExportProblem, match="строки"):
        xlsx(cached, [meta["row_tokens"][0]] * 2)
    with pytest.raises(export.ExportProblem, match="строки"):
        xlsx(cached, ["0" * 64])


@pytest.mark.parametrize("field,value", [("project", "Другой"), ("cut", "2026-03-04"), ("contract_id", "b" * 64)])
def test_snapshot_context_cannot_be_relabelled(field, value):
    cached = native_card()
    params = dict(project=PROJECT, cut=CUT, contract_id=CONTRACT,
                  revision=cached["comparison_export"]["revision"], selected_tokens=[])
    params[field] = value
    with pytest.raises(export.ExportProblem, match="другому"):
        export.select_snapshot(cached, **params)


def test_selection_only_uses_server_values_and_keeps_empty_filter_explicit():
    cached = native_card()
    sheet, header = table(xlsx(cached, [cached["comparison_export"]["row_tokens"][1]], query="нулевым", filter="behind"))
    assert "нулевым" in sheet.cell(header + 1, 1).value and sheet.cell(header + 1, 4).value == 0
    sheet, header = table(xlsx(cached, [], query="нет такой работы"))
    assert sheet.cell(header + 1, 1).value == "По выбранному фильтру строк нет."
    meta, comparison, rows = export.select_snapshot(cached, PROJECT, CUT, CONTRACT,
        cached["comparison_export"]["revision"], list(reversed(cached["comparison_export"]["row_tokens"])))
    assert rows == comparison["lines"]  # Client order cannot reorder authoritative rows.


def test_binding_cannot_relabel_a_different_native_cut_or_contract():
    cached = native_card()
    assert export.bind_snapshot(PROJECT, "2026-03-04", CONTRACT, cached, {})["available"] is False
    assert export.bind_snapshot(PROJECT, CUT, "b" * 64, cached, {})["available"] is False


@pytest.mark.parametrize("prefix", ["=HYPERLINK(\"https://invalid.example\",\"x\")", "+cmd", "-cmd", "@SUM(1,2)"])
def test_source_strings_remain_literal_without_formulas_macros_or_links(prefix):
    cached = native_card()
    cached["comparison"]["lines"][0]["name"] = prefix
    cached["comparison_export"] = export.bind_snapshot(PROJECT, CUT, CONTRACT, cached, {"contract": prefix})
    raw = xlsx(cached, query=prefix)
    sheet, header = table(raw)
    assert sheet.cell(header + 1, 1).value.startswith(prefix)
    assert all(c.data_type != "f" for row in sheet for c in row)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        assert not any("externalLink" in n or "vbaProject" in n for n in archive.namelist())
        assert b"<f>" not in archive.read("xl/worksheets/sheet1.xml")
        assert not any(b'TargetMode="External"' in archive.read(n) for n in archive.namelist() if n.endswith(".rels"))


@pytest.mark.parametrize("name", ["x" * 32768, "bad\x01text"])
def test_unrepresentable_text_is_refused_instead_of_silently_truncated(name):
    cached = native_card()
    cached["comparison"]["lines"][0]["name"] = name
    cached["comparison_export"] = export.bind_snapshot(PROJECT, CUT, CONTRACT, cached, {})
    with pytest.raises(export.ExportProblem):
        xlsx(cached)


def test_row_and_output_caps_fail_with_a_status_instead_of_an_empty_file(monkeypatch):
    cached = native_card()
    cached["comparison"]["lines"] *= export.MAX_ROWS
    meta = export.bind_snapshot(PROJECT, CUT, CONTRACT, cached, {})
    assert meta["available"] is False and meta["detail"]
    monkeypatch.setattr(export, "MAX_XLSX_BYTES", 1)
    with pytest.raises(export.ExportProblem, match="Файл слишком большой"):
        xlsx(native_card())


def test_writer_does_not_rescan_the_entire_sheet_for_each_work(monkeypatch):
    from openpyxl.worksheet.worksheet import Worksheet
    cached = native_card()
    cached["comparison"]["lines"] *= 100
    cached["comparison_export"] = export.bind_snapshot(PROJECT, CUT, CONTRACT, cached, {})
    original = Worksheet.max_row.fget
    scans = []
    def count_scans(sheet):
        scans.append(1)
        return original(sheet)
    monkeypatch.setattr(Worksheet, "max_row", property(count_scans))
    assert xlsx(cached).startswith(b"PK")
    assert len(scans) < 20, "whole-sheet scans per work make large exports quadratic"


@pytest.fixture
def route(tmp_path, monkeypatch):
    source = ast.parse((ROOT / "engine/monitor_cumulative.py").read_bytes())
    names = {"MonitorCumulativeAuth", "MonitorCumulativeProject", "MonitorContractsBuild", "MonitorContractDocuments",
             "MonitorContractComparisonExport", "_monitor_cumulative_day", "monitor_contract_comparison_xlsx"}
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
    monkeypatch.setattr(jobs.Store, "start", lambda *a, **k: pytest.fail("new job during export"))
    root = tmp_path / ".cumulative_jobs"
    root.mkdir()
    profile = "monitor-cumulative-v1:contracts"
    metadata = dict(ticket=TICKET, owner=jobs.owner_binding(KEY, SESSION, profile), profile=profile,
                    request="synthetic", created=time.time(), state="done")
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
