"""Export identity follows the captured project; document titles stay unchanged."""
from __future__ import annotations

import json
import re
import sys
import threading
from datetime import date
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import main_legacy as core  # noqa: E402
from browser import chromium_or_skip, wait_for_result  # noqa: E402


def _header_name(response):
    return unquote(response.headers["content-disposition"].split("filename*=UTF-8''", 1)[1])


@pytest.mark.parametrize(("metadata", "label"), [
    ({}, "модель"),
    ({"nonres_book": True, "office_book": True}, "нежилой_офис"),
    ({"nonres_book": True, "office_book": False}, "нежилой"),
    ({"hotel_book": True}, "гостиница"),
])
def test_workbook_headers_use_export_identity_without_renaming_document(monkeypatch, metadata, label):
    calls = []
    monkeypatch.setattr(core, "require_calc_access", lambda *_a, **_k: None)

    def book(*args, **kwargs):
        calls.append(kwargs)
        return b"PK\x03\x04probe", "legacy.xlsx", metadata

    monkeypatch.setattr(core, "build_project_workbook", book)
    body = {"inputs": {}, "tep": {}, "project_name": "Заголовок документа",
            "export_name": 'Берёзовый / 東京: "корпус"\x00\n' + "Ж" * 100}
    response = TestClient(core.app).post("/report/workbook", json=body)
    assert response.status_code == 200
    name = _header_name(response)
    assert name.startswith(f"DevelopAid_{label}_Берёзовый _ 東京_ _корпус_")
    assert name.endswith(f"_{date.today().isoformat()}.xlsx")
    assert len(name.encode("utf-8")) < 255
    assert not re.search(r'[\\/:*?"<>|\x00-\x1f\x7f]', name)
    assert calls == [{"project_name": "Заголовок документа", "scenario": "base"}]
    assert response.content == b"PK\x03\x04probe"
    # Older API clients retain their builder's filename and need no project save.
    response = TestClient(core.app).post("/report/workbook", json={"inputs": {}, "tep": {}})
    assert _header_name(response) == "legacy.xlsx"


@pytest.mark.parametrize("kind", ["report", "teaser"])
def test_background_pdf_receipts_keep_each_requests_name(monkeypatch, tmp_path, kind):
    release = threading.Event()
    captured = []
    monkeypatch.setattr(core, "_REPORT_JOB_DIR", tmp_path / "reports")
    monkeypatch.setattr(core, "_TEASER_JOB_DIR", tmp_path / "teasers")
    monkeypatch.setattr(core, "_TEASER_HANDOFF_SECONDS", 0)
    monkeypatch.setattr(core, "require_payload_access", lambda *_a, **_k: None)
    monkeypatch.setattr(core, "usage_track", lambda *_a, **_k: None)
    monkeypatch.setattr(core, "_run_authoritative_model", lambda *_a, **_k: {"consolidated": {}})
    monkeypatch.setattr(core, "_parity_mismatch", lambda *_a, **_k: [])
    for function in ["entry_price_block", "entry_price_for_report", "strategy_compare_for_report",
                     "_teaser_site_facts"]:
        monkeypatch.setattr(core, function, lambda *_a, **_k: {})
    monkeypatch.setattr(core, "_teaser_map_png", lambda *_a, **_k: None)

    def pdf(payload):
        captured.append(payload["project_name"])
        assert release.wait(5)
        return b"%PDF-probe"

    def teaser(_bundle, inputs, *_a, **_k):
        return pdf(inputs)

    monkeypatch.setattr(core, "_build_developaid_pdf", pdf)
    monkeypatch.setattr(core, "build_teaser_pdf", teaser)
    client = TestClient(core.app)
    route = "/report/pdf" if kind == "report" else "/report/teaser"
    label = "Отчет" if kind == "report" else "Тизер"
    states = []
    try:
        for name in ["Берёзовый 東京", "Другой проект"]:
            body = {"inputs": {}, "tep": {"apartments": {}}, "result": {},
                    "project_name": "Заголовок документа", "export_name": name,
                    "sensitivity": {"rows": []}}
            response = client.post(route, json=body)
            assert response.status_code == 202, response.text
            state = response.json()
            states.append((name, state, core._job_events(kind)[state["ticket"]]))
    finally:
        release.set()
    for name, state, done in states:
        assert done.wait(5)
        response = client.get(state["poll"])
        assert response.status_code == 200, response.text
        assert response.content == b"%PDF-probe"
        assert _header_name(response) == f"DevelopAid_{label}_{name}_{date.today().isoformat()}.pdf"
        # Polling the same ticket returns its original filename, even after another export.
        assert _header_name(client.get(state["poll"])) == _header_name(response)
    assert captured == ["Заголовок документа"] * 2
    assert core._teaser_filename({}) == "DevelopAid_Тизер_DevelopAid.pdf"
    assert core._report_filename({}) == f"DevelopAid_Отчет_DevelopAid_{date.today().isoformat()}.pdf"
    assert core._teaser_filename({"project_name": "Проект / 1"}) == "DevelopAid_Тизер_Проект_1.pdf"
    assert core._report_filename({"project_name": "Проект / 1"}) == f"DevelopAid_Отчет_Проект_1_{date.today().isoformat()}.pdf"


def test_real_page_downloads_saved_name_address_switches_and_settings_roundtrip():
    from playwright.sync_api import sync_playwright

    result = core._run_authoritative_model(dict(core.DEFAULT_INPUTS), core.TEP_DEFAULT, [], {})["consolidated"]
    posted = []
    mode = {"switch": False, "header": False}
    saved_name = 'Берёзовый / 東京: "дом"'
    expected_subject = "Берёзовый _ 東京_ _дом"
    day = date.today().isoformat()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chromium_or_skip()))
        page = browser.new_page(accept_downloads=True)
        page.add_init_script("localStorage.setItem('plato_projects_key','export-test-only')")
        page.on("dialog", lambda dialog: dialog.accept())

        def route(request_route):
            request = request_route.request
            path = urlsplit(request.url).path
            if path == "/":
                return request_route.fulfill(status=200, content_type="text/html", body=core.PAGE)
            if path in ["/calculate", "/calculate-phased"]:
                return request_route.fulfill(json=result if path == "/calculate" else {"consolidated": result})
            if path in ["/report/workbook", "/report/pdf", "/report/teaser"]:
                body = request.post_data_json
                posted.append((path, body))
                if mode["switch"]:
                    page.evaluate("""() => {
                      applyProjectSnapshot({inputs:{_cadastral_query:'Тула, улица Новая, 9'}});
                      rememberOpenedProject({id:'next',name:'Следующий проект'});
                    }""")
                headers = {}
                if mode["header"]:
                    label = {"/report/workbook": "модель", "/report/pdf": "Отчет", "/report/teaser": "Тизер"}[path]
                    ext = "xlsx" if path == "/report/workbook" else "pdf"
                    from urllib.parse import quote
                    filename = core._project_export_filename(label, body["export_name"], ext)
                    headers["Content-Disposition"] = "attachment; filename*=UTF-8''" + quote(filename)
                return request_route.fulfill(body=b"export-probe", headers=headers)
            return request_route.fulfill(json={})

        page.route("**/*", route)
        try:
            page.goto("http://export.test/", wait_until="domcontentloaded")
            wait_for_result(page)
            # Both HTTP headers and headerless downloads use the captured identity.
            for header in [False, True]:
                mode.update(switch=True, header=header)
                for function, label, extension in [
                    ("exportModelArchive", "модель", "xlsx"),
                    ("exportReportPdf", "Отчет", "pdf"),
                    ("exportTeaserPdf", "Тизер", "pdf"),
                ]:
                    page.evaluate("""name => {
                      applyProjectSnapshot({inputs:{_cadastral_query:'Москва, улица Лесная, 1',
                        _manual_tep_import:{project_name:'Заголовок документа'}}});
                      rememberOpenedProject({id:'saved',name});
                    }""", saved_name)
                    with page.expect_download() as download:
                        page.evaluate(f"{function}()")
                    assert download.value.suggested_filename == f"DevelopAid_{label}_{expected_subject}_{day}.{extension}"
                    download.value.delete()
                    assert posted[-1][1]["export_name"] == saved_name
                    assert posted[-1][1]["project_name"] == "Заголовок документа"

            mode.update(switch=False, header=False)
            # Import/snapshot replacement forgets the previously opened saved name.
            page.evaluate("applyProjectSnapshot({inputs:{_cadastral_query:'Москва, улица Лесная, 1'}})")
            page.evaluate("settledCalculate()")
            assert page.evaluate("currentPdfReportPayload().export_name") == "Москва, улица Лесная, 1"
            with page.expect_download() as download:
                page.evaluate("downloadCurrentSettings()")
            assert download.value.suggested_filename == f"DevelopAid_настройки_Москва_ улица Лесная_ 1_{day}.json"
            settings = Path(download.value.path()).read_bytes()
            download.value.delete()
            assert json.loads(settings)["name"] == "Москва, улица Лесная, 1"
            snapshot = page.evaluate("JSON.stringify([inputs,tep,phasing,scenarioSelect.value])")
            page.evaluate("rememberOpenedProject({id:'foreign',name:'Чужой проект'})")
            page.locator("#settingsFileInput").set_input_files({"name": "settings.json", "mimeType": "application/json", "buffer": settings})
            wait_for_result(page)
            assert page.evaluate("openedProject") is None
            assert page.evaluate("currentPdfReportPayload().export_name") == "Москва, улица Лесная, 1"
            restored = page.evaluate("JSON.stringify([inputs,tep,phasing,scenarioSelect.value])")
            assert json.loads(restored) == json.loads(snapshot)
            # A cadastral number or coordinates are not invented addresses.
            for query in ["77:01:0001001:1", "55.75, 37.61"]:
                page.evaluate("query => applyProjectSnapshot({inputs:{_cadastral_query:query}})", query)
                assert page.evaluate("currentPdfReportPayload().export_name") == ""
            page.evaluate("""() => {
              cadastralAnalysis={recognized:['77:01:0001001:1'],parcels:[{cadastral_number:'77:01:0001001:1',address:'Старый адрес'}]};
              moResult={query:'77:01:0001001:1',territory:{address:'Другой старый адрес'}};
              inputs._cadastral_query='77:01:0001001:2';
            }""")
            assert page.evaluate("currentPdfReportPayload().export_name") == ""
            page.evaluate("inputs._cadastral_query='Москва, улица Новая, 3'")
            assert page.evaluate("currentPdfReportPayload().export_name") == "Москва, улица Новая, 3"
            page.evaluate("inputs._cadastral_query='77:01:0001001:1'")
            assert page.evaluate("currentPdfReportPayload().export_name") == "Старый адрес"
            page.evaluate("applyProjectSnapshot({inputs:{_cadastral_query:'77:01:0001001:2',_mo_calc:{query:'77:01:0001001:1',territory:{address:'Старый адрес'}}}})")
            assert page.evaluate("currentPdfReportPayload().export_name") == ""
            page.evaluate("applyProjectSnapshot({inputs:{_mo_calc:{territory:{address:'Химки, улица Мира, 2'}}}})")
            assert page.evaluate("currentPdfReportPayload().export_name") == "Химки, улица Мира, 2"
            page.evaluate("rememberOpenedProject({id:'final',name:'Последний проект'});resetAll()")
            assert page.evaluate("currentPdfReportPayload().export_name") == ""
        finally:
            browser.close()
