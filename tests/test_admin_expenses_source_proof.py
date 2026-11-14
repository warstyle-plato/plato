"""A fixed admin source projection proves cells without exporting a workbook."""
from __future__ import annotations

import hashlib
import io
import json
import multiprocessing
from pathlib import Path
import time
from types import SimpleNamespace
import xml.etree.ElementTree as ET
import zipfile

import openpyxl
import pytest
from fastapi.testclient import TestClient

import developaid_admin_expenses_source as proof
import developaid_cached_source_audit as audit
import developaid_monitor as monitor
import developaid_schedule_versions as versions
import main as wrapper
from test_the_approved_budget_says_what_it_is_made_of import _finmodel

PROJECT = "Synthetic AHR source"
CUT = "2026-11-13"
KEY = "ahr-source-owner-key"
ROUTE = "/monitor/audit/admin-expenses"
RUNTIME = {"version": "0.29.test", "commit": "a"*40}


@pytest.fixture
def source(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path / "monitor")
    monkeypatch.setenv("DEVELOPAID_ADMIN_KEY", KEY)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    raw = _finmodel(unit=None)  # This fixture deliberately exercises absent unit evidence.
    monitor.replace_finance_baseline(PROJECT, raw, "2026-11-01", "private-source.xlsx")
    folder = monitor._project_dir(PROJECT) / "baseline"
    meta_path = folder / monitor.FINANCE_META
    meta = json.loads(meta_path.read_text())
    meta.update(token="PRIVATE-METADATA-CANARY", file_name="https://PRIVATE-FILENAME-CANARY")
    meta_path.write_text(json.dumps(meta))
    return folder, raw


def capture():
    return proof.capture(PROJECT, CUT, runtime=RUNTIME)


def changed(source, edit):
    with io.BytesIO(source[1]) as stream:
        book = openpyxl.load_workbook(stream)
        edit(book["cf_1_new"])
        out = io.BytesIO()
        book.save(out)
        book.close()
    monitor.replace_finance_baseline(PROJECT, out.getvalue(), "2026-11-01", "changed.xlsx")


def test_only_raw_leaf_cells_coordinates_and_bounded_provenance_leave_the_source(source, monkeypatch):
    folder, raw = source
    reads = []
    original = audit.Reader.read

    def read(reader, relative, **kwargs):
        reads.append(relative)
        return original(reader, relative, **kwargs)

    monkeypatch.setattr(audit.Reader, "read", read)
    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in folder.iterdir() if p.is_file()}
    got = capture()
    assert got["state"] == "ok" and got["purpose"] == proof.PURPOSE
    assert not got["financial_acceptance"] and got["values_are_raw_cached_cells"]
    assert got["source"]["sha256"] == hashlib.sha256(raw).hexdigest()
    assert got["source"]["version_date"] == "2026-11-01" and got["source"]["metadata_bound_to_bytes"]
    assert got["header_cells"] == {"total": "I6", "fact": "J6", "plan": "K6"}
    assert got["unit_evidence"]["state"]=="missing" and got["unit_evidence"]["recognized_unit"] is None
    assert got["unit_evidence"]["context"]["last_row"]==6
    row, = got["rows"]
    assert row["code"] == "2.4.1" and row["row"] == 14
    assert {key: cell["cached_value"] for key, cell in row["cells"].items()} == {
        "total": 40, "fact": 20, "plan": 20}  # Raw thousands: not a second AHR calculation.
    assert row["cells"]["fact"]["cell"] == "J14" and not row["cells"]["fact"]["formula"]
    assert set(reads) <= {"baseline/finance.xlsx", "baseline/finance_meta.json", ".aliases.json"}
    text = json.dumps(got, ensure_ascii=False)
    for forbidden in ("PRIVATE-METADATA-CANARY", "PRIVATE-FILENAME-CANARY", "content_base64", "tax", "bank_rss"):
        assert forbidden not in text
    assert all(code not in [x["code"] for x in got["rows"]] for code in ("2.4", "2.4.5", "2.4.5.1"))
    assert before == {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in folder.iterdir() if p.is_file()}


@pytest.mark.parametrize("text,unit",[("Все суммы в тыс. руб.","тыс. руб."),
    ("млн руб.","млн руб."),("Единица измерения: руб.","руб."),
    ("Все показатели в тыс. руб. с НДС","тыс. руб."),
    ("тыс. руб., в т.ч. НДС","тыс. руб."),("тыс. руб. в том числе НДС","тыс. руб.")])
def test_units_are_quoted_from_the_fixed_header_instead_of_assumed(source,text,unit):
    changed(source,lambda sheet:setattr(sheet["B2"],"value",text))
    got=capture()["unit_evidence"]
    assert got["state"]=="observed" and got["recognized_unit"]==unit
    token,=got["tokens"]
    assert token["cell"]=="B2" and token["recognized_unit"]==unit
    assert token["raw_token"] in text
    assert text not in json.dumps(got) or text==token["raw_token"]


def test_conflicting_units_and_per_area_labels_do_not_invent_thousands(source):
    def edit(sheet):
        sheet["B2"]="тыс. руб.";sheet["B3"]="млн руб.";sheet["B4"]="руб./м²"
    changed(source,edit)
    got=capture()["unit_evidence"]
    assert got["state"]=="ambiguous" and got["recognized_unit"] is None
    assert {x["cell"] for x in got["tokens"]}=={"B2","B3"}


@pytest.mark.parametrize("suffix",["за м²","на м2","за 1 кв.м","на 1 кв. м", "на 100 м²",
    "на квадратный метр", "на единицу площади", "на место", "за 1 место", "на рабочее место",
    "за машино-место", "на площадь", "за гектар", "на1м2"])
def test_per_area_or_per_place_words_do_not_confirm_global_currency_units(source,suffix):
    changed(source,lambda sheet:setattr(sheet["B2"],"value","Стоимость: тыс. руб. "+suffix))
    got=capture()["unit_evidence"]
    assert got["state"]=="missing" and got["recognized_unit"] is None


@pytest.mark.parametrize("quantity",["1 000","1\u00a0000","1\u202f000","1 000 000", "1,5", "1.5", "1/2", "½", "1,5 тыс."])
@pytest.mark.parametrize("unit",["м²","м³","место"])
def test_quantity_and_denominator_grammar_never_turns_a_rate_into_a_global_scale(source,quantity,unit):
    changed(source,lambda sheet:setattr(sheet["B2"],"value","Стоимость: тыс. руб. на "+quantity+" "+unit))
    got=capture()["unit_evidence"]
    assert got["state"]=="missing" and got["recognized_unit"] is None


@pytest.mark.parametrize("caption",["тыс. руб. за м3", "тыс. руб. за 100 м^3", "тыс. руб. за куб. м",
    "тыс. руб. за 1 000 кг", "тыс. руб. на 100 шт.", "тыс. руб. в месяц", "тыс. руб. на 01.11.2026",
    "тыс. руб. на неизвестный показатель", "тыс. руб. из расчёта на услугу", "м²/тыс. руб.",
    "Стоимость 1 м³ в тыс. руб.", "Стоимость за тонну, тыс. руб.", "Цена 1 000 кг, тыс. руб.",
    "Стоимость на жителя, тыс. руб.", "Стоимость на неизвестный показатель, тыс. руб.",
    "Цена килограмма, тыс. руб.", "Стоимость человеко-часа, тыс. руб.", "Цена штуки, тыс. руб."])
def test_specific_or_ambiguous_context_cannot_fall_back_to_a_global_currency_label(source,caption):
    changed(source,lambda sheet:setattr(sheet["B2"],"value",caption))
    got=capture()["unit_evidence"]
    assert got["state"]=="missing" and got["recognized_unit"] is None


def test_unit_token_collector_is_bounded_while_scanning_and_late_units_remain_ambiguous():
    cell=SimpleNamespace(value="руб. "*6000+"тыс. руб.",coordinate="B2",data_type="s")
    collector=proof._HeaderEvidence(2)
    collector.add(2,[cell])
    assert len(collector.tokens)==proof.MAX_UNIT_TOKENS
    assert collector.found==6001 and collector.kinds=={"руб.","тыс. руб."}
    got=collector.result()
    assert got["state"]=="ambiguous" and got["recognized_unit"] is None
    assert got["tokens_found"]==6001 and got["omitted_tokens"]==6001-proof.MAX_UNIT_TOKENS


@pytest.mark.parametrize("limit",["cell","total","cells"])
def test_header_scan_limits_fail_before_retaining_or_normalising_oversized_text(source,monkeypatch,limit):
    changed(source,lambda sheet:setattr(sheet["B2"],"value","руб. "*30))
    monkeypatch.setattr(proof,{"cell":"MAX_HEADER_CELL_CHARS","total":"MAX_HEADER_CHARS",
                              "cells":"MAX_HEADER_CELLS"}[limit],100 if limit!="cells" else 10)
    with pytest.raises(proof.SourceProblem,match="header_size_limit"):capture()


@pytest.mark.parametrize("value,kind", [(None,"missing"),(0,"number"),(False,"boolean"),
    ("неизвестно","text"),("#REF!","error"),("=1+2","missing")])
def test_cached_unknown_zero_boolean_error_and_uncalculated_formula_remain_distinct(source,value,kind):
    changed(source, lambda sheet: setattr(sheet["J14"], "value", value))
    cell = capture()["rows"][0]["cells"]["fact"]
    assert cell["value_type"] == kind and cell["formula"] == (value == "=1+2")
    assert cell["cached_value"] == (value if kind=="number" else None)
    if value is not None and kind in {"boolean","text","error"}:
        assert cell["value_sha256"]==hashlib.sha256(str(value).encode()).hexdigest()


@pytest.mark.parametrize("value",["1 234,50","1\u00a0234.50","1\u202f234,50","0","-12,5","+.5","1.25e3"," 0 "])
def test_numeric_cached_text_preserves_its_representation_without_becoming_arbitrary_text(source,value):
    changed(source,lambda sheet:setattr(sheet["J14"],"value",value))
    cell=capture()["rows"][0]["cells"]["fact"]
    assert cell["cached_value"]==value and cell["value_type"]=="numeric_text"


@pytest.mark.parametrize("value",["https://synthetic.invalid/private?token=CANARY", "token=PRIVATE-CREDENTIAL",
    "PRIVATE-EXPENSE-NAME", "123abc", "NaN", "Infinity", "1e309"])
def test_nonnumeric_cached_text_is_only_a_typed_missing_value_and_hash(source,value):
    changed(source,lambda sheet:setattr(sheet["J14"],"value",value))
    got=capture();cell=got["rows"][0]["cells"]["fact"]
    assert cell["cached_value"] is None and cell["value_type"]=="text"
    assert cell["value_sha256"]==hashlib.sha256(value.encode()).hexdigest()
    assert value not in json.dumps(got)


def test_formula_text_and_external_urls_are_not_projected(source):
    changed(source, lambda sheet: setattr(sheet["J14"], "value",
                                         '=HYPERLINK("https://PRIVATE-FORMULA-CANARY", "secret")'))
    got = capture()
    assert got["rows"][0]["cells"]["fact"]["formula"]
    assert "PRIVATE-FORMULA-CANARY" not in json.dumps(got)


def test_the_saved_excel_cache_is_projected_without_recalculating_the_formula(source):
    changed(source, lambda sheet: setattr(sheet["J14"],"value","=1+2"))
    path=source[0]/"finance.xlsx";out=io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(path.read_bytes())) as archive, zipfile.ZipFile(out,"w") as target:
        for info in archive.infolist():
            data=archive.read(info.filename)
            if info.filename=="xl/worksheets/sheet2.xml":
                tree=ET.fromstring(data);ns={"m":"http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
                tree.find('.//m:c[@r="J14"]/m:v',ns).text="900"
                data=ET.tostring(tree)
            target.writestr(info,data)
    monitor.replace_finance_baseline(PROJECT,out.getvalue(),"2026-11-01","cached.xlsx")
    cell=capture()["rows"][0]["cells"]["fact"]
    assert cell["formula"] and cell["cached_value"]==900  # The source cache, not evaluated 1+2.


@pytest.mark.parametrize("version,state", [(None,"source_date_unknown"),("2026-11-14","source_after_cut")])
def test_missing_or_future_source_dates_never_produce_historical_money_rows(source,version,state):
    path = source[0] / monitor.FINANCE_META
    meta = json.loads(path.read_text());meta["taken_at"] = version
    path.write_text(json.dumps(meta))
    got = capture()
    assert got["state"] == state and got["rows"] == []


def test_legacy_metadata_is_explicit_and_a_mismatched_new_pair_is_refused(source):
    path = source[0] / monitor.FINANCE_META
    meta = json.loads(path.read_text());meta.pop("source_sha256")
    path.write_text(json.dumps(meta))
    assert not capture()["source"]["metadata_bound_to_bytes"]
    meta["source_sha256"] = "0"*64;path.write_text(json.dumps(meta))
    with pytest.raises(proof.SourceProblem,match="source_pair_mismatch"):
        capture()


def test_a_nonexistent_project_does_not_create_a_directory(source):
    before = set(monitor._SNAPSHOT_DIR.iterdir())
    with pytest.raises(proof.SourceProblem):
        proof.capture("Project that does not exist",CUT,runtime=RUNTIME)
    assert set(monitor._SNAPSHOT_DIR.iterdir()) == before


def test_an_existing_single_alias_selects_only_its_canonical_project(source):
    folder, raw=source
    canonical=folder.parent.parent/"canonical"
    folder.parent.rename(canonical)
    (monitor._SNAPSHOT_DIR/".aliases.json").write_text(json.dumps({"aliases":{
        monitor._slug(PROJECT):"canonical"}}))
    got=capture()
    assert got["source"]["sha256"]==hashlib.sha256(raw).hexdigest()
    assert got["source"]["aliases_sha256"] and not folder.parent.exists()


@pytest.mark.parametrize("target", ["../outside","/etc","nested/child","..",""])
def test_unsafe_alias_cannot_choose_another_filesystem_source(source,target):
    (monitor._SNAPSHOT_DIR / ".aliases.json").write_text(json.dumps({"aliases":{monitor._slug(PROJECT):target}}))
    with pytest.raises(proof.SourceProblem):
        capture()


@pytest.mark.parametrize("name", ["finance.xlsx",monitor.FINANCE_META,".schedule_versions.lock"])
def test_source_and_lock_symlinks_are_not_followed(source,tmp_path,name):
    outside = tmp_path / "private-outside";outside.write_text("PRIVATE-OUTSIDE-CANARY")
    target = source[0] / name;target.unlink();target.symlink_to(outside)
    with pytest.raises(proof.SourceProblem):
        capture()
    assert outside.read_text() == "PRIVATE-OUTSIDE-CANARY"


def test_a_baseline_directory_symlink_cannot_redirect_the_lock(source,tmp_path):
    folder,_=source
    moved=folder.with_name("original-baseline");folder.rename(moved)
    outside=tmp_path/"outside-baseline";outside.mkdir()
    folder.symlink_to(outside,target_is_directory=True)
    with pytest.raises(proof.SourceProblem):capture()
    assert list(outside.iterdir())==[]


def test_an_interrupted_update_refuses_the_mismatched_pair(source,monkeypatch):
    meta_path=source[0]/monitor.FINANCE_META
    meta=json.loads(meta_path.read_text());meta.pop("source_sha256")
    meta_path.write_text(json.dumps(meta))  # The first update of a legacy source.
    original=versions._atomic
    def atomic(path,data):
        if path.name=="finance.xlsx":raise OSError("Synthetic interrupted writer")
        original(path,data)
    monkeypatch.setattr(versions,"_atomic",atomic)
    with pytest.raises(OSError):changed(source,lambda sheet:setattr(sheet["I14"],"value",80))
    with pytest.raises(proof.SourceProblem,match="source_pair_mismatch"):capture()


def test_source_and_expanded_workbook_size_are_bounded(source,monkeypatch):
    monkeypatch.setattr(proof,"MAX_EXPANDED",1)
    with pytest.raises(proof.SourceProblem,match="workbook_size_limit"):capture()
    with (source[0]/"finance.xlsx").open("wb") as stream:stream.truncate(proof.MAX_SOURCE+1)
    with pytest.raises(proof.SourceProblem):capture()


def test_output_is_bounded_without_returning_a_silent_partial_projection(source,monkeypatch):
    monkeypatch.setattr(proof,"MAX_OUTPUT",1)
    with pytest.raises(proof.SourceProblem,match="projection_size_limit"):capture()


def test_a_long_valid_code_is_not_silently_dropped(source):
    changed(source,lambda sheet:setattr(sheet["C14"],"value","2.4.1234567"))
    assert [r["code"] for r in capture()["rows"]]==["2.4.1234567"]


def test_an_oversized_valid_code_refuses_the_projection_instead_of_omitting_it(source):
    changed(source,lambda sheet:setattr(sheet["C14"],"value","2.4."+"1"*97))
    with pytest.raises(proof.SourceProblem,match="code_size_limit"):capture()


@pytest.mark.parametrize("edit,code", [
    (lambda s: s.cell(6,12,"ФАКТ"),"columns_ambiguous"),
    (lambda s: s.cell(s.max_row+1,3,"2.4.1"),"codes_ambiguous"),
    (lambda s: s.cell(proof.MAX_ROWS+1,1,1),"worksheet_size_limit"),
])
def test_ambiguous_or_unbounded_source_shapes_are_refused(source,edit,code):
    changed(source,edit)
    with pytest.raises(proof.SourceProblem,match=code):
        capture()


def test_source_change_during_parsing_is_not_a_coherent_proof(source,monkeypatch):
    original = proof._cells
    def cells(data):
        result = original(data)
        changed(source,lambda sheet: setattr(sheet["I14"],"value",80))
        return result
    monkeypatch.setattr(proof,"_cells",cells)
    with pytest.raises(proof.SourceProblem,match="source_changed"):
        capture()


def _paused_writer(root,ready,release):
    monitor._SNAPSHOT_DIR=Path(root)
    original=versions._atomic
    def atomic(path,data):
        original(path,data)
        if path.name==monitor.FINANCE_META:
            ready.set()
            assert release.wait(15)
    versions._atomic=atomic
    monitor.replace_finance_baseline(PROJECT,_finmodel(),"2026-11-14","future.xlsx")


def _read_worker(root,ready,done,result):
    monitor._SNAPSHOT_DIR=Path(root);ready.set()
    try:result.put(capture())
    finally:done.set()


def test_native_writer_and_source_proof_share_the_lock_across_processes(source):
    context=multiprocessing.get_context("fork")
    ready,release,read_ready,done=(context.Event() for _ in range(4));result=context.Queue()
    writer=context.Process(target=_paused_writer,args=(monitor._SNAPSHOT_DIR,ready,release))
    reader=context.Process(target=_read_worker,args=(monitor._SNAPSHOT_DIR,read_ready,done,result))
    writer.start()
    try:
        assert ready.wait(10)
        reader.start();assert read_ready.wait(10)
        assert not done.wait(.2)
        release.set();got=result.get(timeout=10)
        assert got["state"]=="source_after_cut" and got["rows"]==[]
        assert got["source"]["version_date"]=="2026-11-14"
    finally:
        release.set()
        for process in (writer,reader):
            if process.pid:
                process.join(10)
                if process.is_alive():process.terminate();process.join(5)
        result.close();result.join_thread()
    assert writer.exitcode==reader.exitcode==0


def call(client,suffix="",**body):
    return client.post(ROUTE+suffix,json={"key":KEY,"session":"owner",**body})


def poll(client,ticket,**body):
    end=time.monotonic()+5
    while time.monotonic()<end:
        response=call(client,"/result",ticket=ticket,**body)
        if response.status_code!=202:return response
        time.sleep(.01)
    pytest.fail("Synthetic source projection did not finish")


def test_native_job_is_explicit_private_and_owner_bound_with_no_widget_or_model_call(source,monkeypatch):
    client=TestClient(wrapper.core.app)
    monkeypatch.setattr(monitor,"build",lambda *a,**k:pytest.fail("Financial widget must not run"))
    denied=call(client,project=PROJECT,cut=CUT,key="wrong")
    assert denied.status_code==403 and not (monitor._SNAPSHOT_DIR/".admin_ahr_source_jobs").exists()
    admitted=call(client,project=PROJECT,cut=CUT,ticket="a"*32)
    assert admitted.status_code==202 and admitted.headers["cache-control"]=="private, no-store"
    assert call(client,"/result",ticket="a"*32,session="other").status_code==404
    result=poll(client,"a"*32)
    assert result.status_code==200 and result.headers["cache-control"]=="private, no-store"
    assert result.json()["ok"] and result.json()["source_projection"]["state"]=="ok"
    assert call(client,project="other",cut=CUT,ticket="a"*32).status_code==409
    job_root=monitor._SNAPSHOT_DIR/".admin_ahr_source_jobs"
    meta=(job_root/("a"*32+".json")).read_text()
    assert KEY not in meta and PROJECT not in meta and "private-source" not in meta
    monkeypatch.setenv("DEVELOPAID_ADMIN_KEY","rotated-source-key")
    assert poll(client,"a"*32).status_code==403
    assert poll(client,"a"*32,key="rotated-source-key").status_code==404


@pytest.mark.parametrize("extra", [{"sheet":"Other"},{"path":"/etc/passwd"},{"range":"A1:ZZ99"},
    {"url":"https://example.com"},{"cells":["J14"]},{"content_base64":"private"},{"session":[]},
    {"ticket":"invalid"},{"cut":"2026-02-31"}])
def test_native_body_is_closed_to_selectors_and_invalid_fields(source,extra):
    response=call(TestClient(wrapper.core.app),**{"project":PROJECT,"cut":CUT,**extra})
    assert response.status_code==400 and response.headers["cache-control"]=="private, no-store"
    assert not (monitor._SNAPSHOT_DIR/".admin_ahr_source_jobs").exists()


def test_oversized_and_duplicate_json_are_refused_before_source_reads(source,monkeypatch):
    monkeypatch.setattr(proof,"capture",lambda *a,**k:pytest.fail("Source must not be read"))
    client=TestClient(wrapper.core.app)
    too_big=client.post(ROUTE,content=b" "*12289,headers={"content-type":"application/json"})
    assert too_big.status_code==413 and too_big.headers["cache-control"]=="private, no-store"
    duplicate='{"key":"'+KEY+'","project":"one","project":"two","cut":"'+CUT+'"}'
    assert client.post(ROUTE,content=duplicate,headers={"content-type":"application/json"}).status_code==400
