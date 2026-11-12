"""Документы договора хранятся в его карточке и не переходят к соседнему договору.

Документы нарисованы с выдуманными номерами (`estimate_pdf`, `schedule_pdf`):
репозиторий публичный, договоры владельца в него не попадают.
"""
from __future__ import annotations

import base64
import time

import pytest
from fastapi.testclient import TestClient

import developaid_contract_documents as documents
import developaid_contract_files as files
import developaid_monitor as monitor
import developaid_monitor_contracts as contracts
from tests.test_contract_documents_are_read_from_their_tables import TITLE, estimate_pdf, schedule_pdf

CONTRACT = "c" * 64
ROW = {"id": CONTRACT, "contract": "№ 12-ТСТ", "contract_date": "2025-09-01"}
BASE = ("Приложение № 1 к Договору подряда № 12-ТСТ от 01.09.2025", "Расчёт договорной стоимости")


@pytest.fixture
def store(monkeypatch, tmp_path):
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path / "monitor")
    return tmp_path / "monitor"


def test_documents_are_listed_as_editions_and_one_file_is_kept_once(store):
    pdf = estimate_pdf()  # рисование не повторяет байты: один файл — одни байты
    agreement = files.store("Учебный", ROW, "ДС4.pdf", pdf)
    assert agreement["title"] == "Дополнительное соглашение № 4 от 01.02.2026" and not agreement["already"]
    base = files.store("Учебный", ROW, "Договор.pdf", estimate_pdf(title=BASE))
    assert base["title"] == "Договор № 12-ТСТ от 01.09.2025"
    assert files.store("Учебный", ROW, "копия.pdf", pdf)["already"] is True
    listed = files.listing("Учебный", CONTRACT)["documents"]
    assert [d["filename"] for d in listed] == ["Договор.pdf", "ДС4.pdf"]
    assert [d["estimates"][0]["scope"] for d in listed] == ["full", "remaining"]
    assert all(d["warnings"] == [] for d in listed)
    assert files.listing("Учебный", "d" * 64)["documents"] == []


def test_a_document_of_another_contract_is_refused_and_not_kept(store):
    other = (TITLE[0], "к Договору подряда № 12-ТСТ от 02.09.2025") + TITLE[2:]
    with pytest.raises(files.ContractFilesProblem, match="договор № 12-ТСТ от 02.09.2025.*в карточке"):
        files.store("Учебный", ROW, "чужой.pdf", estimate_pdf(title=other))
    with pytest.raises(files.ContractFilesProblem, match="12-ТСЕ"):
        files.store("Учебный", {**ROW, "contract": "12-ТСЕ"}, "ДС4.pdf", estimate_pdf())
    assert files.listing("Учебный", CONTRACT)["documents"] == []


def test_a_document_without_the_contract_number_is_named_as_bound_by_choice(store):
    files.store("Учебный", ROW, "ГПР.pdf", schedule_pdf())
    (document,) = files.listing("Учебный", CONTRACT)["documents"]
    assert document["title"] == "Документ без номера договора и соглашения"
    assert document["warnings"][0].startswith("Номер договора в документе не прочитан")
    assert len(document["schedule"]["corrections"]) == 2


def test_two_files_of_one_edition_are_both_kept_and_named(store):
    files.store("Учебный", ROW, "ДС4.pdf", estimate_pdf())
    files.store("Учебный", ROW, "ДС4 без штампа.pdf", estimate_pdf(stamp=False))
    first, second = files.listing("Учебный", CONTRACT)["documents"]
    assert "ещё и файлом «ДС4 без штампа.pdf»" in first["warnings"][0]
    assert "ещё и файлом «ДС4.pdf»" in second["warnings"][0]


def test_a_newer_reader_reads_the_kept_pdf_again(store, monkeypatch):
    files.store("Учебный", ROW, "ДС4.pdf", estimate_pdf())
    calls = []
    read = documents.read
    monkeypatch.setattr(documents, "read", lambda data: calls.append(1) or read(data))
    files.listing("Учебный", CONTRACT)
    assert calls == []
    monkeypatch.setattr(documents, "READER_VERSION", documents.READER_VERSION + 1)
    (document,) = files.listing("Учебный", CONTRACT)["documents"]
    assert calls == [1] and document["reader"] == documents.READER_VERSION
    files.listing("Учебный", CONTRACT)
    assert calls == [1], "перечитанный разбор сохраняется"


def test_a_scan_is_refused_with_the_reason(store):
    import pymupdf
    document = pymupdf.open()
    document.new_page().draw_rect(pymupdf.Rect(40, 40, 400, 400), fill=(0.5, 0.5, 0.5))
    with pytest.raises(files.ContractFilesProblem, match="скан"):
        files.store("Учебный", ROW, "скан.pdf", document.tobytes())
    with pytest.raises(files.ContractFilesProblem, match="PDF"):
        files.store("Учебный", ROW, "таблица.xlsx", b"PK\x03\x04")


# --- маршруты -----------------------------------------------------------------

KEY = "synthetic-contract-files-key"


@pytest.fixture
def api(monkeypatch, store):
    import main as wrapper
    monkeypatch.setenv("DEVELOPAID_ADMIN_KEY", KEY)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(contracts, "build", lambda project, cut="", **_: {"rows": [ROW]})
    return TestClient(wrapper.core.app)


def _finished(client, response):
    deadline = time.monotonic() + 20
    while response.status_code == 202 and time.monotonic() < deadline:
        time.sleep(.02)
        response = client.post("/monitor/contracts/result", json={"key": KEY, "ticket": response.json()["ticket"]})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("path", ["documents", "document-upload"])
@pytest.mark.parametrize("key", ["", "wrong-key"])
def test_documents_need_the_current_admin_key(api, path, key, store):
    body = {"key": key, "session": "claimed-session", "project": "Учебный", "contract_id": CONTRACT,
            "content_base64": base64.b64encode(estimate_pdf()).decode()}
    response = api.post("/monitor/contracts/" + path, json=body)
    assert response.status_code == 403 and response.headers["cache-control"] == "private, no-store"
    assert not (store / "Учебный").exists() or not any((store).rglob("*.pdf"))


def test_upload_through_the_route_files_the_pdf_under_the_registered_contract(api):
    body = {"key": KEY, "project": "Учебный", "cut": "2026-11-06", "contract_id": CONTRACT, "filename": "ДС4.pdf",
            "content_base64": base64.b64encode(estimate_pdf()).decode()}
    done = _finished(api, api.post("/monitor/contracts/document-upload", json=body))
    assert done["ok"] and done["document"]["title"].startswith("Дополнительное соглашение № 4")
    assert [d["filename"] for d in done["documents"]] == ["ДС4.pdf"]
    stranger = _finished(api, api.post("/monitor/contracts/document-upload", json={**body, "contract_id": "e" * 64}))
    assert stranger == {**stranger, "ok": False, "detail": "Договор не найден в данных выбранного проекта на эту дату."}
    listed = _finished(api, api.post("/monitor/contracts/documents", json={
        "key": KEY, "project": "Учебный", "cut": "2026-11-06", "contract_id": CONTRACT}))
    assert [d["filename"] for d in listed["documents"]] == ["ДС4.pdf"]
    broken = api.post("/monitor/contracts/document-upload", json={**body, "content_base64": "не base64"})
    assert broken.status_code == 400
