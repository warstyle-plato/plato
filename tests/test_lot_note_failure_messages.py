"""Cached provider failures remain honest failures in the sheet and workbook."""
import io
import json
import time
from pathlib import Path

import openpyxl
import pytest
from fastapi.testclient import TestClient

from auction_search import api, lot_notes
from scripts import prod_smoke
from test_a_lot_gets_platons_comment_in_the_book import _app, _lot

RAW = "HTTPException: OpenAI API: You have no credits remaining. Add credits to continue."


@pytest.mark.parametrize("reason,fragment", [
    (RAW, "лимит"),
    ("RateLimitError: insufficient_quota", "лимит"),
    ("RuntimeError: лимит AI-запросов исчерпан", "лимит"),
    ("HTTPException: Too many requests", "число запросов"),
    ("ReadTimeout: https://provider.example.invalid/internal", "не ответил вовремя"),
    ("HTTPException: Вопрос слишком длинный: 4551 знаков при пределе 4000", "Объём данных"),
    ("RuntimeError: Платон вернул пустой ответ", "пустой ответ"),
    ("AuthenticationError: invalid API key PRIVATE-DIAGNOSTIC", "Доступ"),
    ("ValueError: PRIVATE-DIAGNOSTIC https://provider.example.invalid/internal", "ошибки сервиса"),
    (None, "ошибки сервиса"),
])
def test_public_failure_explains_the_reason_without_echoing_provider_details(reason, fragment):
    text = lot_notes.comment_for_book({"failed": True, "reason": reason})
    assert text.startswith("Разбор не удался:") and fragment in text
    assert all(value not in text for value in ("HTTPException", "RateLimitError", "Traceback",
                                               "PRIVATE-DIAGNOSTIC", "https://", "OpenAI API"))


def test_existing_failed_cache_is_readable_in_api_and_xlsx_without_a_new_model_call(tmp_path, monkeypatch):
    def forbidden(_):
        raise AssertionError("Reading an existing failure must not request the model")

    app, asked = _app(tmp_path, monkeypatch, forbidden)
    store = lot_notes.LotNotes(tmp_path / "market")
    url = "https://etp/lot/1"
    store.remember_lots([_lot(url)])
    store.save_note(url, {"failed": True, "reason": RAW, "asked_at": int(time.time())})
    store.record_run("notes", "разбор не удался " + url + ": " + RAW)
    original_note = store.note(url)
    original_runs = store.runs()
    rows = [{"section": "Торги", "name": "Лот 1", "url": url,
             "cadastre": "77:01:0001001:1", "application_deadline_iso": "2099-01-10T12:00:00+03:00"}]
    with TestClient(app) as client:
        response = client.post("/auctions/table", json={"rows": rows, "kind": "auctions"})
        assert response.status_code == 200
        cell = response.json()["rows"][0]["cells"]["plato_comment"]
        assert cell["ready"] is False
        status = client.get("/auctions/lot-notes/status").json()
    assert status["failed"] == 1 and status["commented"] == 0
    assert "лимит" in status["last_failure"]
    assert "лимит" in status["runs"]["notes"]["result"]
    assert "HTTPException" not in json.dumps(status) and "no credits" not in json.dumps(status)
    data = api._xlsx(rows, "auctions")
    workbook = openpyxl.load_workbook(io.BytesIO(data))
    sheet = workbook.active
    header = [c.value for c in sheet[1]]
    col = next(i + 1 for i, label in enumerate(header) if str(label).startswith("Комментарий"))
    assert sheet.cell(2, col).value == cell["text"]
    assert "лимит" in cell["text"] and "HTTPException" not in cell["text"]
    assert asked == []
    assert store.note(url) == original_note and store.runs() == original_runs

    # Keep the production checker strict: sanitized honest failures pass,
    # while replacing that cell with the old raw exception still fails.
    ref = json.loads((Path(__file__).parents[1] / "scripts/prod_smoke_reference.json").read_text())
    assert prod_smoke.judge_auction_export(data, ref).status == prod_smoke.OK
    sheet.cell(2, col).value = "Разбор не удался: " + RAW
    mutated = io.BytesIO(); workbook.save(mutated)
    assert prod_smoke.judge_auction_export(mutated.getvalue(), ref).status == prod_smoke.FAIL


def test_successful_comments_and_sources_are_not_rewritten():
    text = lot_notes.comment_for_book({"failed": False, "text": "Что пишут: спор о залоге [1].",
        "asked_at": 1, "sources": [{"url": "https://news.example.invalid/1", "modtime": "2026-11-01"}]})
    assert text.startswith("Что пишут: спор о залоге [1].")
    assert "https://news.example.invalid/1" in text and "2026-11-01" in text


@pytest.mark.parametrize("width", [390, 1440])
def test_actual_lot_card_explains_cached_ai_failure(width, tmp_path, monkeypatch):
    from playwright.sync_api import expect, sync_playwright
    from tests import browser
    from test_the_auction_page_shows_the_book_columns import _app as fixture_app, _open, LIVE_URL, NOW

    app = fixture_app(tmp_path, monkeypatch)
    store = lot_notes.LotNotes(tmp_path / "market")
    store.save_note(LIVE_URL, {"failed": True, "reason": RAW, "asked_at": int(time.time())})
    with browser.serve(app, 18912) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(browser.chromium_or_skip())) as chromium:
            page = chromium.new_page(viewport={"width": width, "height": 900})
            page.clock.set_fixed_time(NOW)
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            _open(page, base)
            page.locator('#sheetRows tr.sheetrow').first.click()
            note = page.locator('#lotModalNote')
            expect(note).to_be_visible()
            expect(note).to_contain_text('Разбор не удался')
            expect(note).to_contain_text('лимит')
            assert 'HTTPException' not in note.inner_text() and 'no credits' not in note.inner_text()
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+2')
            assert store.note(LIVE_URL)['failed'] is True
            assert not errors, errors
