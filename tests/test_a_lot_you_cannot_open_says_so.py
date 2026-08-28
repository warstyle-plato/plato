"""Лот, который нечем разобрать, говорит это в списке, а не после клика.

ГИС Торги приехали в выдачу, а `/auctions/ingest` их не знал: на «Разобрать
лот» приходило «поддерживаются только официальные URL Росэлторг и
РАД/Lot-online». Узнать, что карточку не открыть, можно было только нажав —
владелец так и спросил: «зачем они тогда в списке» (25.08.2026).

Ответ на «можно ли разобрать» считает тот же `_adapter_for`, который потом и
разбирает: второе правило о том же самом однажды разошлось бы с первым, и
кнопка обещала бы разбор там, где его нет.

А сам разбор ГИС Торгов теперь есть — и он ничего не пропускает молча: адрес
одиночной карточки живым ответом не сверен, поэтому не тот вид ответа и не та
форма оболочки называют, что спросили и что пришло.

Запуск: python3 -m pytest tests/test_a_lot_you_cannot_open_says_so.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from auction_search import api as auction_api  # noqa: E402
from auction_search.adapters.torgi_gov import (  # noqa: E402
    TorgiGovAdapter, lot_card, lot_documents, lot_id_from_url,
)
from auction_search.ui import auctions_page  # noqa: E402


TORGI_URL = "https://torgi.gov.ru/new/public/lots/lot/22000123450000000123_1"


def test_a_torgi_lot_is_routed_to_its_own_adapter() -> None:
    adapter = auction_api._adapter_for(TORGI_URL)
    assert isinstance(adapter, TorgiGovAdapter)


def test_the_list_says_a_torgi_lot_can_be_opened() -> None:
    assert auction_api._analysis_support(TORGI_URL) == {"available": True, "reason": ""}


def test_an_unknown_platform_names_itself_in_the_refusal() -> None:
    got = auction_api._analysis_support("https://unknown-etp.example/lot/1")
    assert got["available"] is False
    assert "unknown-etp.example" in got["reason"], "отказ обязан назвать, что именно не опознано"


def test_the_answer_comes_from_the_same_router_that_parses() -> None:
    """Одно правило: если маршрут отказал, отказ виден и в списке."""
    source = Path(ROOT / "auction_search" / "api.py").read_text()
    body = source[source.index("def _analysis_support("):]
    body = body[:body.index("\n@") if "\n@" in body else len(body)]
    assert "_adapter_for(" in body, "второй копии списка площадок быть не должно"


def test_the_id_is_the_last_segment_and_nothing_else() -> None:
    assert lot_id_from_url(TORGI_URL) == "22000123450000000123_1"
    assert lot_id_from_url("https://torgi.gov.ru/new/public/lots/lot/abc123?tab=notice") == "abc123"
    # Перебор сегментов вверх дал бы «public» — чужой адрес с уверенным видом.
    assert lot_id_from_url("https://torgi.gov.ru/new/public/lots/") == ""
    assert lot_id_from_url("https://torgi.gov.ru/") == ""


CARD = {
    "id": "22000123450000000123_1",
    "lotName": "Имущественный комплекс, г. Москва, ул. Ленинская Слобода",
    "subjectRFCode": "77",
    "priceMin": 480_000_000,
    "biddEndTime": "2099-09-11T09:00:00Z",
    "characteristics": [
        {"code": "cadastralNumberRealty", "characteristicValue": "77:05:0004001:1042"},
        {"code": "totalAreaRealty", "characteristicValue": "26000"},
    ],
    "documents": [
        {"url": "https://torgi.gov.ru/f/1", "name": "Извещение"},
        {"name": "приложение без ссылки"},
    ],
}


def test_the_card_is_found_however_it_is_wrapped() -> None:
    assert lot_card(CARD)["id"] == CARD["id"]
    assert lot_card({"lot": CARD})["id"] == CARD["id"]
    assert lot_card({"content": [CARD]})["id"] == CARD["id"]


def test_an_unknown_shape_is_not_an_empty_lot() -> None:
    assert lot_card({"status": "ok", "payload": 1}) is None
    assert lot_card([1, 2, 3]) is None


def test_a_document_without_a_link_is_not_a_document() -> None:
    got = lot_documents(CARD)
    assert [d.title for d in got] == ["Извещение"]


def _adapter_answering(payload: str, *, status: int = 200, ctype: str = "application/json"):
    adapter = TorgiGovAdapter()
    asked: list[str] = []

    def fake(url: str):
        asked.append(url)
        return status, ctype, payload

    adapter._fetch_raw = fake  # type: ignore[method-assign]
    return adapter, asked


def test_one_card_is_parsed_by_the_same_rule_as_the_list() -> None:
    adapter, asked = _adapter_answering(json.dumps(CARD))
    lot = adapter.fetch_lot(TORGI_URL)
    assert asked == ["https://torgi.gov.ru/new/api/public/lotcards/22000123450000000123_1"]
    assert lot.cadastral_numbers == ["77:05:0004001:1042"]
    assert lot.building_area_sqm == 26_000
    assert lot.current_price_rub == 480_000_000
    assert [d.title for d in lot.documents] == ["Извещение"]


def test_a_page_instead_of_json_names_what_came_back() -> None:
    adapter, _ = _adapter_answering("<html>Портал</html>", ctype="text/html")
    with pytest.raises(ValueError) as exc:
        adapter.fetch_lot(TORGI_URL)
    assert "не JSON" in str(exc.value) and "text/html" in str(exc.value)


def test_an_unknown_envelope_names_its_keys() -> None:
    adapter, _ = _adapter_answering(json.dumps({"status": "ok", "payload": {}}))
    with pytest.raises(ValueError) as exc:
        adapter.fetch_lot(TORGI_URL)
    assert "карточки лота нет" in str(exc.value)
    assert "payload" in str(exc.value) and "status" in str(exc.value)


def test_a_bad_address_never_becomes_a_request() -> None:
    adapter, asked = _adapter_answering(json.dumps(CARD))
    with pytest.raises(ValueError):
        adapter.fetch_lot("https://torgi.gov.ru/new/public/lots/")
    assert asked == [], "неразобранный адрес не должен уходить в сеть"


def test_the_screen_says_it_before_the_click() -> None:
    page = auctions_page()
    assert "function lotAnalysis(" in page
    assert "Разобрать этот лот нечем" in page
    assert "Разбор недоступен" in page
    assert "этот лот нечем разобрать" in page, "балл обязан назвать это снижением"
    # Своей копии списка площадок на странице нет: правило приходит с сервера.
    assert "roseltorg" not in page.lower().split("function lotanalysis(")[1][:600]


def test_a_lot_without_the_field_is_not_forbidden() -> None:
    """«Источник не сказал» — не «нельзя»: старый ответ не должен гасить кнопку."""
    page = auctions_page()
    body = page[page.index("function lotAnalysis("):]
    body = body[:body.index("\nfunction lotCaveats(")]
    assert "available:true" in body.replace(" ", "")
