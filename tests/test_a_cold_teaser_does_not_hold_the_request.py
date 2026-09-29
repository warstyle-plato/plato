"""Холодный тизер не держит запрос дольше nginx: 202 с билетом, PDF — опросом.

Первый тизер после выкатки на площадке КРТ из двадцати участков — это скрининг
НСПД по каждому участку (шесть десятков слоёв на участок) и поиск контуров для
карты: на пустых кэшах минуты. nginx перед ядром столько не держит — прод
отвечал 504, а повтор через пару минут шёл быстро, по прогретому кэшу.

Холодный источник здесь — скрининг, который отвечает дольше порога передачи.
На прежнем коде запрос ждал его целиком и отвечал PDF через всё это время —
проверка на времени ответа и на 202 падает.

Запуск: python3 -m pytest tests/test_a_cold_teaser_does_not_hold_the_request.py -q
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import main as _wrapper  # noqa: E402
import page_blocks  # noqa: E402

core = _wrapper.core

COLD_SECONDS = 3.0
HANDOFF_SECONDS = 0.3
BUDGET_SECONDS = 2.0  # меньше холодного скрининга, с запасом над порогом


def _inputs():
    from test_the_dashboard_and_the_teaser_show_one_calculation import _starved
    inputs, tep, _ = _starved()
    return inputs, tep


@pytest.fixture
def cold(monkeypatch, tmp_path):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    # raising=False: на прежнем коде этих имён нет, и проверка обязана упасть
    # на времени ответа, а не на подстановке.
    monkeypatch.setattr(core, "_TEASER_JOB_DIR", tmp_path / "teaser", raising=False)
    monkeypatch.setattr(core, "_TEASER_HANDOFF_SECONDS", HANDOFF_SECONDS, raising=False)
    release = threading.Event()
    calls = []

    def cold_screening(**kw):
        # Кэш пуст: НСПД опрашивается по каждому участку.
        calls.append(kw)
        release.wait(COLD_SECONDS)
        return {"parcels": [], "verdict": {}}

    monkeypatch.setattr(core, "land_screening", cold_screening)
    monkeypatch.setattr(core, "_teaser_map_png", lambda site: None)
    yield release, calls
    release.set()


def _post(client, inputs, tep, **extra):
    return client.post("/report/teaser", json={
        "inputs": inputs, "tep": tep, "rates": [], "phasing": {},
        "project_name": "Холодный", "cadastral_numbers": ["77:05:0004001:40"], **extra})


def _poll(client, ticket, limit=60.0):
    deadline = time.monotonic() + limit
    while time.monotonic() < deadline:
        response = client.get(f"/report/teaser/{ticket}")
        if response.status_code != 202:
            return response
        time.sleep(0.1)
    raise AssertionError("тизер не собрался за отведённое время")


def test_a_cold_teaser_answers_within_the_budget_and_names_the_stage(cold):
    from fastapi.testclient import TestClient
    release, calls = cold
    inputs, tep = _inputs()
    client = TestClient(core.app)
    started = time.monotonic()
    response = _post(client, inputs, tep)
    took = time.monotonic() - started
    assert took < BUDGET_SECONDS, f"запрос держался {took:.1f} с — столько же, сколько холодный источник"
    assert response.status_code == 202, response.text[:300]
    state = response.json()
    assert state["pending"] is True and state["ticket"]
    assert state["stage"] == "screening", state
    assert "скрининг" in state["detail"]
    assert calls, "скрининг не начался: 202 вышел не из-за холодного источника"

    # Пока сборка идёт — опрос честно говорит «готовится».
    assert client.get(f"/report/teaser/{state['ticket']}").status_code == 202

    release.set()
    done = _poll(client, state["ticket"])
    assert done.status_code == 200, done.text[:300]
    assert done.headers["content-type"].startswith("application/pdf")
    assert done.content.startswith(b"%PDF")
    assert "Холодный" in done.headers["content-disposition"] or "%D0%A5" in done.headers["content-disposition"]


def test_the_result_lives_on_disk_for_the_other_worker(cold):
    """Воркеров два: опрос, пришедший не туда, где шла сборка, видит итог."""
    from fastapi.testclient import TestClient
    release, _ = cold
    inputs, tep = _inputs()
    client = TestClient(core.app)
    ticket = _post(client, inputs, tep).json()["ticket"]
    release.set()
    _poll(client, ticket)
    with core._TEASER_JOBS_LOCK:
        assert ticket not in core._TEASER_JOBS  # в памяти пусто — отвечает диск
    again = client.get(f"/report/teaser/{ticket}")
    assert again.status_code == 200 and again.content.startswith(b"%PDF")


def test_a_repeated_request_with_the_same_ticket_does_not_build_twice(cold):
    """Оборванный запрос повторяют с тем же билетом — сборка одна."""
    from fastapi.testclient import TestClient
    release, calls = cold
    inputs, tep = _inputs()
    client = TestClient(core.app)
    ticket = "ab" * 16
    first = _post(client, inputs, tep, ticket=ticket)
    second = _post(client, inputs, tep, ticket=ticket)
    assert first.status_code == 202 and second.status_code == 202
    assert second.json()["ticket"] == ticket
    assert len(calls) == 1
    release.set()
    assert _poll(client, ticket).status_code == 200


def test_a_warm_teaser_still_answers_with_the_pdf_itself(monkeypatch, tmp_path):
    """Тёплый путь не меняется: успела сборка до порога — PDF тем же ответом."""
    from fastapi.testclient import TestClient
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setattr(core, "_TEASER_JOB_DIR", tmp_path / "teaser")
    monkeypatch.setattr(core, "_TEASER_HANDOFF_SECONDS", 60.0)
    monkeypatch.setattr(core, "land_screening", lambda **kw: {"parcels": [], "verdict": {}})
    monkeypatch.setattr(core, "_teaser_map_png", lambda site: None)
    inputs, tep = _inputs()
    response = _post(TestClient(core.app), inputs, tep)
    assert response.status_code == 200, response.text[:300]
    assert response.content.startswith(b"%PDF")


def test_a_failed_build_is_named_and_an_unknown_ticket_is_not_pending(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setattr(core, "_TEASER_JOB_DIR", tmp_path / "teaser")
    monkeypatch.setattr(core, "_TEASER_HANDOFF_SECONDS", 30.0)

    def broken(**kw):
        raise RuntimeError("шрифт не найден")

    monkeypatch.setattr(core, "land_screening", lambda **kw: {"parcels": [], "verdict": {}})
    monkeypatch.setattr(core, "_teaser_map_png", lambda site: None)
    monkeypatch.setattr(core, "build_teaser_pdf", lambda *a, **kw: broken())
    inputs, tep = _inputs()
    client = TestClient(core.app)
    response = _post(client, inputs, tep)
    assert response.status_code == 500
    assert "вёрстка PDF" in response.json()["detail"] and "шрифт не найден" in response.json()["detail"]
    missing = client.get("/report/teaser/" + "cd" * 16)
    assert missing.status_code == 404 and "Запросите тизер" in missing.json()["detail"]
    assert client.get("/report/teaser/not-a-ticket").status_code == 400


def test_a_stalled_build_is_reported_not_pending_forever(monkeypatch, tmp_path):
    """Сборка, оборванная перезапуском, не висит «готовится» вечно."""
    monkeypatch.setattr(core, "_TEASER_JOB_DIR", tmp_path / "teaser")
    ticket = "ef" * 16
    core._teaser_stage(ticket, "screening", time.time() - 7200)
    path = core._teaser_job_path(ticket, "pending")
    stale = time.time() - core._TEASER_JOB_STALL_SECONDS - 60
    path.write_text(f'{{"stage": "screening", "started": {stale}, "updated": {stale}}}',
                    encoding="utf-8")
    state = core._teaser_job_state(ticket)
    assert state["state"] == "error" and "скрининг" in state["detail"]


def test_the_page_polls_the_ticket_until_the_pdf():
    """Страница: 202 → опрос билета с надписью стадии на кнопке → скачивание."""
    prelude = """
const log=[];let button={textContent:'Скачать тизер',disabled:false};
const document={querySelector:()=>button};
async function calculate(){}
function activeSession(){return ''}
const projectsAdminKey='';
function currentPdfReportPayload(){return {inputs:{},tep:{x:1}}}
function alert(t){log.push('alert:'+t)}
function setTimeout(f){f()}
function downloadBlobResponse(blob,d,f){log.push('download:'+blob+':'+button.textContent)}
let n=0;
async function fetch(url,opts){
 log.push((opts&&opts.method||'GET')+' '+url);
 n++;
 if(n<3)return {status:202,ok:true,json:async()=>({pending:true,ticket:'abc',detail:'Тизер готовится: скрининг участков в НСПД.'})};
 return {status:200,ok:true,blob:async()=>'PDF',headers:{get:()=>''}};
}
"""
    tail = """
(async()=>{const seen=[];const p=exportTeaserPdf();
 await p; console.log(JSON.stringify({log,label:button.textContent,disabled:button.disabled}));})();
"""
    out = page_blocks.run_json(prelude, tail)
    assert out["log"][0].startswith("POST /report/teaser")
    assert out["log"][1:3] == ["GET /report/teaser/abc", "GET /report/teaser/abc"]
    assert out["log"][3] == "download:PDF:Тизер готовится: скрининг участков в НСПД."
    assert out["label"] == "Скачать тизер" and out["disabled"] is False
