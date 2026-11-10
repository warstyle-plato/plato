"""Карточка договора загружает PDF договора и показывает их разбор, исправления — красным.

Ответ маршрута собран настоящим разбором нарисованных документов
(`developaid_contract_files`), а не написан руками: страница проверяется на той
форме записи, которую отдаёт сервер.
"""
from __future__ import annotations

import base64
import json

import pytest

import developaid_contract_files as files
import developaid_monitor as monitor
from test_monitor_cumulative_controls import CONTRACT, KEY, MARKER, browser_page
from tests.test_contract_documents_are_read_from_their_tables import estimate_pdf, schedule_pdf

ROW = {"id": CONTRACT, "contract": "12-ТСТ", "contract_date": "2025-09-01"}
RED = "rgb(180, 35, 24)"


@pytest.fixture
def listing(monkeypatch, tmp_path):
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path / "monitor")
    files.store("Учебный", ROW, "ДС4.pdf", estimate_pdf())
    files.store("Учебный", ROW, MARKER + ".pdf", schedule_pdf())
    return files.listing("Учебный", CONTRACT)


def _serve(page, listing, calls):
    def handle(route):
        body = route.request.post_data_json or {}
        calls.append((route.request.url.rsplit("/", 1)[-1], body))
        assert body.get("key") == KEY and body.get("contract_id") == CONTRACT
        extra = {"document": {"already": False}} if body.get("content_base64") else {}
        route.fulfill(json={"pending": False, "ok": True, **extra, **json.loads(json.dumps(listing))})
    page.route("**/monitor/contracts/document*", handle)


def _open(page):
    page.locator("#contractsTab").click()
    page.locator(f'tr[data-contract-id="{CONTRACT}"] .contract-open').click()


@pytest.mark.parametrize("width", [390, 1440])
def test_the_card_lists_documents_and_shows_schedule_corrections_in_red(listing, width):
    from playwright.sync_api import expect
    calls = []
    with browser_page(width) as (page, _, errors):
        _serve(page, listing, calls)
        _open(page)
        documents = page.locator("#contractDocuments")
        expect(documents).to_contain_text("Дополнительное соглашение № 4 от 01.02.2026")
        expect(documents).to_contain_text("Расчёт договорной стоимости на завершение работ")
        expect(documents).to_contain_text("Итог документа: 127 150 ₽.")
        correction = documents.locator("ul.contract-correction li").first
        expect(correction).to_contain_text("у строки 2.3 «Стены»")
        expect(correction).to_contain_text("Взяты даты полосы: 29.01.2026 — 31.01.2026.")
        assert correction.evaluate("e => getComputedStyle(e).color") == RED
        warning = documents.locator("ul.contract-warning li", has_text="Номер договора в документе не прочитан")
        assert warning.evaluate("e => getComputedStyle(e).color") != RED
        documents.get_by_text("Строки графика (7)").click()
        fixed = documents.locator("tr.contract-correction", has_text="Стены")
        expect(fixed).to_contain_text("Даты исправлены: по полосе диаграммы.")
        expect(documents.locator("tr.contract-correction", has_text="Каркас")).to_contain_text(
            "по срокам входящих работ")
        assert fixed.evaluate("e => getComputedStyle(e).color") == RED
        assert [name for name, _ in calls] == ["documents"]
        assert page.evaluate("window.untrustedRan") is None and errors == []


def test_a_pdf_is_uploaded_into_the_open_card_and_other_files_are_refused(listing):
    from playwright.sync_api import expect
    calls = []
    with browser_page(1440) as (page, _, errors):
        _serve(page, listing, calls)
        _open(page)
        expect(page.locator("#contractDocuments")).to_contain_text("ДС4.pdf")
        page.locator("#contractDocumentFile").set_input_files(
            {"name": "Таблица.xlsx", "mimeType": "application/vnd.ms-excel", "buffer": b"PK"})
        page.locator("#contractDocumentUpload").click()
        expect(page.locator("#contractDocumentsMsg")).to_have_text(
            "Выберите PDF договора, дополнительного соглашения или акта КС-2.")
        pdf = b"%PDF-1.7 synthetic"
        page.locator("#contractDocumentFile").set_input_files(
            {"name": "ДС5.pdf", "mimeType": "application/pdf", "buffer": pdf})
        page.locator("#contractDocumentUpload").click()
        expect(page.locator("#contractDocumentsMsg")).to_have_text("Документ прочитан и сохранён.")
        name, body = calls[-1]
        assert name == "document-upload" and [n for n, _ in calls] == ["documents", "document-upload"]
        assert base64.b64decode(body["content_base64"]) == pdf and body["filename"] == "ДС5.pdf"
        assert body["project"] == "Учебный проект" and len(body["ticket"]) == 32
        assert errors == []


def test_the_card_shows_proposed_links_shares_and_reasons(listing):
    from playwright.sync_api import expect
    from test_contract_positions_are_linked_to_schedule_lines import ESTIMATE, SCHEDULE
    import developaid_contract_schedule_links as links
    agreement = next(d for d in listing["documents"] if d.get("agreement"))
    agreement["estimates"][0]["links"] = {**links.propose(ESTIMATE, SCHEDULE, agreement=True), "schedule": "Договор"}
    with browser_page(1440) as (page, _, errors):
        _serve(page, listing, [])
        _open(page)
        part = page.locator("#contractDocuments .contract-links").first
        expect(part).to_contain_text("по графику: Договор · предложено: 4 · на проверку: 4 · "
                                     "дополнительный объём без срока: 1")
        expect(part).to_contain_text("В накопленный план войдут только подтверждённые связи.")
        part.get_by_text("Предложенные связи (4)").click()
        walls = part.locator(".contract-links-proposed tr", has_text="3.1.1")
        expect(walls).to_contain_text("3.1.3 Возведение вертикальных конструкций 2-ого этажа · 16.03.2026 — 20.03.2026"
                                      " · доля 33,3 % ≈ 500 ₽")
        expect(walls).to_contain_text(links.SHARE_ASSUMPTION)
        part.get_by_text("На проверку (4)").click()
        expect(part.locator(".contract-links-review tr", has_text="Устройство стен")).to_contain_text(
            "строки пронумерованы под разделом 4, а самого раздела в графике нет.")
        part.get_by_text("Дополнительный объём без срока (1)").click()
        expect(part.locator(".contract-links-extra")).to_contain_text("Устройство пандуса")
        expect(part.locator(".contract-links-free summary")).to_have_text("Строки графика без позиций расчёта (6)")
        assert "₽ ₽" not in page.locator("#contractDocuments").inner_text()
        assert errors == []


def test_a_weekly_schedule_says_its_dates_are_precise_to_a_week(monkeypatch, tmp_path):
    from playwright.sync_api import expect
    import developaid_contract_documents as documents
    from tests.test_contract_documents_of_the_weekly_layout import weekly_pdf
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path / "monitor")
    files.store("Учебный", ROW, "ГПР.pdf", weekly_pdf())
    weekly = files.listing("Учебный", CONTRACT)
    with browser_page(1440) as (page, _, errors):
        _serve(page, weekly, [])
        _open(page)
        expect(page.locator("#contractDocuments .contract-schedule-assumption")).to_have_text(
            documents.WEEKS_ASSUMPTION)
        assert errors == []
