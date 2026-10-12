"""Полный PDF проверяет ограничения у каждого участка проекта (#655).

Тизер показывал все двадцать участков площадки, а полный PDF скринил первые
десять (`_pdf_screening_numbers`) и молчал об остальных: участок, не попавший в
десятку или не получивший ответа НСПД, в таблице не появлялся и читался как
чистый. Теперь у каждого номера проекта есть строка — находки, «ограничений
не обнаружено» или «не получено от источника» с причиной. Двадцать участков —
это минуты НСПД, поэтому /report/pdf собирается в фоне, как тизер (#578).

На прежнем коде: в скрининг уходило десять номеров — проверка на двадцать
строк падает; участок без ответа источника пропадал из таблицы; /report/pdf
держал запрос до конца сборки — проверка на 202 падает.

Запуск: python3 -m pytest tests/test_the_full_pdf_screens_every_parcel.py -q
"""

from __future__ import annotations

import io
import sys
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import main as _wrapper  # noqa: E402
import page_blocks  # noqa: E402

core = _wrapper.core

NUMBERS = [f"77:05:0004001:{n}" for n in range(101, 121)]  # двадцать участков


def _payload() -> dict:
    inputs = dict(core.DEFAULT_INPUTS)
    inputs["_land_lookup"] = {"query": ", ".join(NUMBERS)}
    tep = {key: dict(value) for key, value in core.TEP_DEFAULT.items()}
    bundle = core._run_authoritative_model(inputs, tep, [], {})
    return {"result": bundle["consolidated"], "inputs": inputs, "tep": tep,
            "rates": [], "phasing": {}, "scenario": "base", "project_name": "Площадка КРТ"}


@pytest.fixture(scope="module")
def payload():
    return _payload()


def _fake_screening(calls: list, silent: set[str] = frozenset()):
    """Скрининг как у ядра: отвечает по тем номерам, что спросили, и режет
    по `limit` так же, как настоящий. По номерам из `silent` НСПД не ответил."""
    def screening(cad: str = "", min_area_sqm=None, limit: int = 30):
        numbers = [n for n in cad.split(",") if n]
        calls.append({"numbers": numbers, "limit": limit})
        if limit and limit > 0:
            numbers = numbers[:limit]
        parcels = []
        for number in numbers:
            if number in silent:
                parcels.append({"cadastral_number": number, "found": False, "probe_failed": True,
                                "note": "Запрос в НСПД не прошёл: таймаут"})
                continue
            parcels.append({
                "cadastral_number": number, "found": True, "center": {"lat": 55.7, "lng": 37.6},
                "too_small": False, "probe_method": "contour",
                "findings": [{"flag_class": "economic", "name": f"Охранная зона у {number[-3:]}",
                              "impact": "режет посадку", "reg_number": "77:05-6.1"}],
            })
        return {"parcels": parcels, "requested_count": len(numbers), "checked_count": len(parcels),
                "min_area_sqm": 1000.0,
                "verdict": {"status": "WARNING", "headline": "Есть ограничения, влияющие на посадку",
                            "disclaimer": "Проверены ограничения, внесённые в ЕГРН."}}
    return screening


def _screening_section(pdf: bytes) -> str:
    pypdf = pytest.importorskip("pypdf")
    text = " ".join(page.extract_text() or "" for page in pypdf.PdfReader(io.BytesIO(pdf)).pages)
    text = " ".join(text.split())
    start = text.index("Реализуемость посадки")
    return text[start:text.index("Ключевая экономика", start)]


def test_twenty_parcels_give_twenty_restriction_rows(payload, monkeypatch):
    calls: list = []
    monkeypatch.setattr(core, "land_screening", _fake_screening(calls))
    section = _screening_section(core._build_developaid_pdf(payload))
    assert calls and calls[0]["numbers"] == NUMBERS, "в скрининг уходят все номера проекта"
    assert calls[0]["limit"] <= 0, "полный PDF не режет список пределом окна"
    missing = [n for n in NUMBERS if n not in section]
    assert not missing, f"участки без строки ограничений: {missing}"
    for number in NUMBERS:
        assert f"Охранная зона у {number[-3:]}" in section
    assert "Проверено участков: 20 из 20" in section


def test_rows_are_one_per_parcel_in_project_order():
    screening = _fake_screening([])(cad=",".join(NUMBERS), limit=0)
    rows = core._pdf_screening_rows(NUMBERS, screening)
    assert [r[0] for r in rows] == NUMBERS


def test_a_parcel_the_source_did_not_answer_is_named(payload, monkeypatch):
    silent = {NUMBERS[3], NUMBERS[15]}
    monkeypatch.setattr(core, "land_screening", _fake_screening([], silent))
    section = _screening_section(core._build_developaid_pdf(payload))
    rows = core._pdf_screening_rows(NUMBERS, _fake_screening([], silent)(cad=",".join(NUMBERS), limit=0))
    named = {r[0]: r for r in rows}
    for number in silent:
        assert named[number][1] == "не получено от источника"
        assert "таймаут" in named[number][2], "причина — словами источника"
    assert section.count("не получено от источника") >= 2
    assert "Проверено участков: 18 из 20" in section


def test_a_failed_screening_is_named_per_parcel_not_skipped(payload, monkeypatch):
    def down(**kw):
        raise RuntimeError("ядро недоступно: connection refused")

    monkeypatch.setattr(core, "land_screening", down)
    section = _screening_section(core._build_developaid_pdf(payload))
    assert "Скрининг не выполнен" in section
    assert "connection refused" in section, "отказ называет реальную причину"
    assert "Проверено участков: 0 из 20" in section
    assert all(n in section for n in NUMBERS)


def test_the_core_screening_checks_every_parcel_when_asked(monkeypatch):
    monkeypatch.setattr(core, "_core_api_url", lambda path: "")
    monkeypatch.setattr(core, "_nspd_search_features", lambda q: [])
    monkeypatch.setattr(core, "_LAND_RETRY_PAUSE_SECONDS", 0)
    core._LAND_SCREENING_CACHE.clear()
    numbers = ", ".join(f"50:12:0101031:{n}" for n in range(1, 41))
    assert core.land_screening(cad=numbers, limit=0)["checked_count"] == 40
    assert core.land_screening(cad=numbers)["checked_count"] == 30, "окну — прежний предел"


# --- фоновая сборка ----------------------------------------------------------

@pytest.fixture
def cold(monkeypatch, tmp_path):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setattr(core, "_REPORT_JOB_DIR", tmp_path / "report", raising=False)
    monkeypatch.setattr(core, "_TEASER_HANDOFF_SECONDS", 0.3)
    release = threading.Event()

    def cold_screening(**kw):
        release.wait(3.0)
        return {"parcels": [], "verdict": {}}

    monkeypatch.setattr(core, "land_screening", cold_screening)
    yield release
    release.set()


def test_a_cold_report_does_not_hold_the_request(payload, cold):
    client = TestClient(core.app)
    body = {**payload, "sensitivity": {"rows": []}}
    started = time.monotonic()
    response = client.post("/report/pdf", json=body)
    assert time.monotonic() - started < 2.5, "запрос не ждёт скрининга целиком"
    assert response.status_code == 202, response.text
    state = response.json()
    assert state["poll"] == f"/report/pdf/{state['ticket']}"
    assert "PDF-отчёт готовится" in state["detail"]
    cold.set()
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        response = client.get(state["poll"])
        if response.status_code != 202:
            break
        time.sleep(0.2)
    assert response.status_code == 200
    assert response.content[:4] == b"%PDF"
    assert "DevelopAid_" in response.headers["content-disposition"]


def test_an_unknown_report_ticket_is_not_pending(monkeypatch, tmp_path):
    monkeypatch.setattr(core, "_REPORT_JOB_DIR", tmp_path / "report")
    response = TestClient(core.app).get("/report/pdf/" + "0" * 32)
    assert response.status_code == 404
    assert "PDF-отчёта не найден" in response.json()["detail"]


def test_the_page_polls_the_report_ticket_until_the_pdf():
    prelude = """
const log=[];let button={textContent:'Экспорт PDF',disabled:false};
const document={querySelector:()=>button};
async function calculate(){}
function activeSession(){return ''}
const projectsAdminKey='';
function currentPdfReportPayload(){return {result:{},inputs:{},tep:{x:1}}}
function alert(t){log.push('alert:'+t)}
function setTimeout(f){f()}
function downloadBlobResponse(blob,d,f){log.push('download:'+blob+':'+button.textContent)}
let n=0;
async function fetch(url,opts){
 log.push((opts&&opts.method||'GET')+' '+url);
 n++;
 if(n<3)return {status:202,ok:true,json:async()=>({pending:true,ticket:'abc',detail:'PDF-отчёт готовится: скрининг.'})};
 return {status:200,ok:true,blob:async()=>'PDF',headers:{get:()=>''}};
}
"""
    tail = """
(async()=>{await exportReportPdf(); console.log(JSON.stringify({log,label:button.textContent,disabled:button.disabled}));})();
"""
    out = page_blocks.run_json(prelude, tail)
    assert out["log"][0] == "POST /report/pdf"
    assert out["log"][1:3] == ["GET /report/pdf/abc", "GET /report/pdf/abc"]
    assert out["log"][3] == "download:PDF:PDF-отчёт готовится: скрининг."
    assert out["label"] == "Экспорт PDF" and out["disabled"] is False
