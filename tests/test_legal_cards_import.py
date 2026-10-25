"""Готовые карточки споров — файлом с кнопки владельца на странице сводки.

«Почему ты не загрузил карточки споров» (владелец, 21.10.2026). Файл с
карточками положить на сервер некому: выкатка идёт образом из main. Владелец
загружает тот же файл (формат legal_seed.json) кнопкой; повторная загрузка
дублей не плодит, а посторонний кнопки не видит и маршрут ему отказывает.

Запуск: python3 -m pytest tests/test_legal_cards_import.py -q
"""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from test_legal_cases import CARD, PROJECT  # noqa: E402

import developaid_legal_cases as legal  # noqa: E402
import developaid_management_report as report  # noqa: E402
import developaid_monitor as monitor  # noqa: E402

PORT = 18809
OTHER = dict(CARD, counterparty="ООО «Лютик»", contract="Договор № 2 от 01.05.2026",
             claims=[], events=[])


def _file(*cards, project=PROJECT) -> bytes:
    return json.dumps({"projects": [{"project": project, "at": "2026-10-01T00:00:00+00:00",
                                     "cases": [{"card": c} for c in cards]}]},
                      ensure_ascii=False).encode("utf-8")


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path / "monitor")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))


def test_cards_are_added_once_and_marked_unchecked():
    got = legal.import_cards(PROJECT, _file(CARD, OTHER), legal.SEED_AUTHOR)
    assert got == {"added": [CARD["counterparty"], OTHER["counterparty"]], "updated": [],
                   "skipped": [], "questions": []}
    again = legal.import_cards(PROJECT, _file(CARD, OTHER), legal.SEED_AUTHOR)
    assert again == {"added": [], "updated": [],
                     "skipped": [CARD["counterparty"], OTHER["counterparty"]], "questions": []}
    rows = legal.cases(PROJECT)
    assert len(rows) == 2 and all(row["unchecked"] for row in rows)
    text = report.render_text(report.build(PROJECT, "week", "2026-10-25"))
    assert report.LEGAL_UNCHECKED in text and "Открытых споров: 2" in text


def test_a_wrong_file_is_named():
    with pytest.raises(ValueError, match="JSON"):
        legal.import_cards(PROJECT, b"not json", "x")
    with pytest.raises(ValueError, match="Другой"):
        legal.import_cards(PROJECT, _file(CARD, project="Другой"), "x")
    with pytest.raises(ValueError, match="Карточка 1"):
        legal.import_cards(PROJECT, _file(dict(CARD, counterparty="")), "x")
    assert legal.cases(PROJECT) == []


def test_the_route_is_for_the_owner_only(monkeypatch):
    from fastapi import HTTPException
    from test_management_report_model import _gpr_book

    import main_legacy as core

    monitor.store_schedule(PROJECT, _gpr_book({}), None, "2026-07-01")
    monkeypatch.setattr(core, "_require_web_access", lambda *_a, **_k: None)
    request = core.MonitorLegalImportRequest(
        project=PROJECT, content_base64=base64.b64encode(_file(CARD)).decode())
    monkeypatch.setattr(core, "_is_admin_request", lambda *_a, **_k: False)
    with pytest.raises(HTTPException) as refused:
        core.monitor_legal_import(request)
    assert refused.value.status_code == 403
    assert core.monitor_legal(core.MonitorLegalRequest(project=PROJECT))["can_import"] is False
    monkeypatch.setattr(core, "_is_admin_request", lambda *_a, **_k: True)
    done = core.monitor_legal_import(request)
    assert done["imported"]["added"] == [CARD["counterparty"]] and done["can_import"] is True


def test_the_owner_uploads_the_file_on_the_page(monkeypatch, tmp_path):
    from browser import chromium_or_skip, serve

    chrome = chromium_or_skip()
    from playwright.sync_api import sync_playwright
    from test_management_report_model import _gpr_book

    import main_legacy as core

    monitor.store_schedule(PROJECT, _gpr_book({}), None, "2026-07-01")
    monkeypatch.setattr(core, "_require_web_access", lambda *_a, **_k: None)
    monkeypatch.setattr(core, "_is_admin_request", lambda *_a, **_k: True)
    sample = tmp_path / "legal_seed.json"
    sample.write_bytes(_file(CARD, OTHER))
    with serve(core.app, PORT) as base, sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chrome))
        try:
            tab = browser.new_page()
            errors: list[str] = []
            tab.on("pageerror", lambda e: errors.append(str(e)))
            tab.add_init_script("localStorage.setItem('developaid_web_session','проба')")
            tab.goto(f"{base}/report", wait_until="domcontentloaded")
            tab.wait_for_selector("#legalImport:not(.hidden)")
            tab.set_input_files("#legalImportFile", str(sample))
            tab.click("#legalImportBtn")
            tab.wait_for_function(
                "document.getElementById('legalMsg').textContent.includes('Внесено споров: 2')")
            listed = tab.inner_text("#legalList")
        finally:
            browser.close()
    assert not errors, errors
    assert "Ромашка-Строй" in listed and "Лютик" in listed
    assert "внесено по вашим документам" in listed
