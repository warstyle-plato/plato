"""«Документов 26» отвечало не на тот вопрос: четыре из них площадка не отдала.

Счёт вложений лежал в `lot.raw`, а `include_raw` у карточки выключен: на экране
стояло число вложений и ни слова о том, сколько из них прочитано. Посчитанное
за маршрутом и никем не показанное неотличимо от непосчитанного — у лота 33444
(13.09.2026) из 26 вложений прочитано 21, четыре ответили HTTP 503, а
фотоархив без текста не разобрался.

Состояний у вложения три, и слить их нельзя: прочитано, площадка не отдала (с
причиной), не спрашивали намеренно (ГПЗУ — программы и обязательств в нём
нет). Молча пропущенное вложение на экране неотличимо от неотданного.

Считает их СЕРВЕР рядом с самими вложениями, страница печатает: второй счёт
тех же вложений однажды разошёлся бы с первым, и оба выглядели бы верными.
Поэтому строка экрана проверяется настоящей функцией страницы, накормленной
тем, что отдаёт маршрут.

Запуск: python3 -m pytest tests/test_the_lot_attachments_are_counted.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import page_blocks  # noqa: E402
from auction_search import krt_pipeline, ui  # noqa: E402
from auction_search.documents import (  # noqa: E402
    DocumentAuthorizationRequired,
    DocumentExtractionError,
    DocumentTemporaryRefusal,
)
from auction_search.models import (  # noqa: E402
    AuctionDocument,
    AuctionLot,
    AuctionSource,
    LotKind,
    SourceKind,
)

GIVEN = "https://www.roseltorg.ru/file/get/1/name/Извещение.pdf"
BUSY = "https://www.roseltorg.ru/file/get/2/name/Схема границ.pdf"
CLOSED = "https://www.roseltorg.ru/file/get/3/name/Договор.pdf"
GPZU = "https://www.roseltorg.ru/file/get/4/name/ГПЗУ.pdf"


def lot() -> AuctionLot:
    return AuctionLot(
        source=AuctionSource(
            platform=SourceKind.ROSELTORG,
            lot_url="https://www.roseltorg.ru/procedure/33444",
            external_lot_id="21000005000000033444",
            fetched_at="2026-09-13T10:00:00Z",
        ),
        lot_kind=LotKind.KRT,
        title="КРТ: право на заключение договора",
        documents=[
            AuctionDocument(title="Извещение.pdf", url=GIVEN, document_type="notice"),
            AuctionDocument(title="Схема границ.pdf", url=BUSY, document_type="annex"),
            AuctionDocument(title="Договор.pdf", url=CLOSED, document_type="agreement"),
            AuctionDocument(title="ГПЗУ.pdf", url=GPZU, document_type="gpzu"),
        ],
    )


def answers(url, **kwargs):
    if url == BUSY:
        raise DocumentTemporaryRefusal("площадка ответила HTTP 503; попыток: 3 из 3")
    if url == CLOSED:
        raise DocumentAuthorizationRequired("official ETP requires authentication")
    return b"%PDF-1.4", "application/pdf", False


@pytest.fixture
def counted(monkeypatch):
    monkeypatch.setattr(krt_pipeline, "download_document", answers)
    monkeypatch.setattr(
        krt_pipeline, "extract_document_paragraphs",
        lambda document, data=None, content_type="": ["Предельная площадь жилой застройки составляет 180 000 кв. м."])
    enriched = krt_pipeline.enrich_krt_from_official_documents(lot())
    return krt_pipeline.documents_summary(enriched)


def test_three_answers_about_an_attachment_are_counted_apart(counted):
    assert counted["total"] == 4
    # Спрашивали трёх: ГПЗУ не спрашивали намеренно.
    assert (counted["asked"], counted["read"]) == (3, 1)
    assert counted["refused_by_kind"] == {"temporary": 1, "auth_required": 1}
    assert [row["why"] for row in counted["skipped"]] == [
        "ГПЗУ: программы и обязательств в нём нет"]


def test_only_the_temporary_refusal_is_asked_again(counted):
    """Вход и негодный формат вторым заходом не лечатся: тот же ответ."""
    assert [row["url"] for row in counted["ask_again"]] == [BUSY]


def test_a_refusal_that_is_not_read_is_not_a_refusal_of_the_platform(monkeypatch):
    """Скачали, а текста нет — это «не разобралось», а не «не отдали».

    Фотоархив лота 33444 приезжает целиком и текста не содержит вовсе. Свалить
    его в один список с неотданными значит обвинить площадку там, где она
    ответила.
    """
    monkeypatch.setattr(krt_pipeline, "download_document",
                        lambda url, **kwargs: (b"%PDF", "application/pdf", False))

    def no_text(document, data=None, content_type=""):
        raise DocumentExtractionError("сканированный PDF без текстового слоя")

    monkeypatch.setattr(krt_pipeline, "extract_document_paragraphs", no_text)
    enriched = krt_pipeline.enrich_krt_from_official_documents(lot())
    view = krt_pipeline.documents_summary(enriched)
    assert view["refused_by_kind"] == {"extraction_error": 3}
    assert view["ask_again"] == []


def test_the_ledger_does_not_exist_where_it_was_not_counted():
    """«Не считали» и «нуль» — разные ответы: у не-КРТ лота счёта нет вовсе."""
    plain = lot()
    plain.lot_kind = LotKind.LAND_SALE
    assert krt_pipeline.documents_summary(
        krt_pipeline.enrich_krt_from_official_documents(plain)) is None


def run_page(view: dict | None, total: int) -> dict:
    """Настоящие функции страницы на том, что отдаёт маршрут.

    Куски берёт общий разрешитель, а не перечисление руками: правило «стенд
    разрешает зависимости сам» записано трижды, и этот стенд его не исполнял —
    у `docsRead` появился помощник `docsRefusalSides`, и падение вышло про
    стенд, а не про то, что он проверяет.
    """
    prelude = f"const view={json.dumps(view, ensure_ascii=False)};\n"
    tail = f"""
console.log(JSON.stringify({{
  line: docsRead(view, {total}),
  note: docsRefusalNote(view),
}}));
"""
    out, _ = page_blocks.run(prelude, tail, page=ui.auctions_page())
    return json.loads(out)


def test_the_card_says_how_many_were_read_not_how_many_exist(counted):
    got = run_page(counted, counted["total"])
    assert "прочитано 1 из 4" in got["line"]
    assert "площадка не отдала 2" in got["line"]
    assert "не спрашивали 1" in got["line"]


def test_the_card_names_the_reason_and_the_second_pass(counted):
    got = run_page(counted, counted["total"])
    assert "Схема границ.pdf" in got["note"]
    assert "площадка отказала временно" in got["note"]
    assert "нужен вход на ЭТП" in got["note"]
    # Неотданное спрашивается снова, и об этом сказано: иначе отказ читается
    # как окончательный ответ площадки.
    assert "Спросим снова при следующем разборе: 1" in got["note"]
    assert "склад" in got["note"]


def test_an_old_answer_without_the_count_still_shows_the_number(counted):
    """Ответ маршрута прежнего выпуска счёта не несёт: число вложений на месте,
    а обещания «прочитано» страница не выдумывает."""
    got = run_page(None, 26)
    assert got["line"] == "26"
    assert got["note"] == ""


def test_the_route_hands_the_count_to_the_card(monkeypatch, tmp_path):
    """Счёт доезжает до карточки — проверяем ту дверь, в которую ходят.

    `include_raw` у карточки выключен, поэтому «посчитано» и «показано» здесь
    разные утверждения: свой блок карточка читает из `screening`.
    """
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AUCTION_KRT_WEEKLY", "0")
    monkeypatch.setenv("AUCTION_KRT_WATCH", "0")
    monkeypatch.setattr(krt_pipeline, "download_document", answers)
    monkeypatch.setattr(
        krt_pipeline, "extract_document_paragraphs",
        lambda document, data=None, content_type="": [
            "Предельная площадь жилой застройки составляет 180 000 кв. м."])

    from auction_search import api as auction_api

    class Adapter:
        def fetch_lot(self, url):
            return lot()

    monkeypatch.setattr(auction_api, "_adapter_for", lambda url: Adapter())
    app = FastAPI()
    auction_api.install(app)
    client = TestClient(app)
    answer = client.post("/auctions/ingest", json={
        "url": "https://www.roseltorg.ru/procedure/33444",
        "enrich_krt_documents": True,
        "include_raw": False,
    })
    assert answer.status_code == 200, answer.text
    view = answer.json()["screening"]["documents"]
    assert (view["total"], view["asked"], view["read"]) == (4, 3, 1)
    assert view["refused_by_kind"] == {"temporary": 1, "auth_required": 1}
    # Склад назван вместе со счётом: молчащий склад неотличим от отсутствующего.
    assert view["store"]["floor_mb"]
