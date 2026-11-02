"""Продажа доли общества-«обёртки»: участок — из документов лота, а не из адреса общества.

Лот Росэлторга 178fz30102600019 (100% доли ООО «Фонвизина 8», 596 млн ₽): в
карточке участка нет, он назван только в выписке ЕГРН и лотовой
документации. Юридический адрес общества — другая улица, и участком он не
является. Для расчёта нужны участок по кадастру, цена доли как цена входа и
срок приёма заявок.

Всё здесь синтетическое: номера, имена и адреса выдуманы. Выписка собрана из
образца формата в `reference_data/krt/egrn` заменой номера, правообладателя и
адреса — формат настоящий, содержание нет.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from auction_search import api, equity_assets, equity_stake
from auction_search.models import AuctionDocument, AuctionLot, AuctionSource, LotKind, SourceKind
from auction_search.preset_mapper import build_project_preset

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = (ROOT / "reference_data/krt/egrn/77_05_0004001_2471.xml").read_text("utf-8")

PARCEL = "77:99:0000001:101"
NEIGHBOUR = "77:99:0000001:555"
BUILDING = "77:99:0000001:202"
ADDRESS_NUMBER = "77:99:0000009:9"
PARCEL_ADDRESS = "город Москва, улица Участковая, земельный участок 8"
COMPANY_ADDRESS = "г. Москва, ул. Зоологическая-Тестовая, д. 22"


def extract(number: str, holder: str, ogrn: str, address: str) -> bytes:
    body = (TEMPLATE.replace("77:05:0004001:2471", number)
            .replace('Акционерное общество "Автокомбинат № 19"', holder)
            .replace("1027700173808", ogrn))
    start = body.index("<readable_address>") + len("<readable_address>")
    end = body.index("</readable_address>", start)
    body = body[:start] + address + body[end:]
    assert number in body and holder in body and address in body
    return body.encode("utf-8")


def docx(*paragraphs: str) -> bytes:
    xml = ('<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
           "<w:body>" + "".join(f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>" for text in paragraphs)
           + "</w:body></w:document>")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", xml)
    return buffer.getvalue()


FILES = {
    "https://178fz.roseltorg.ru/file/get/1/egrn-zu.xml": extract(
        PARCEL, 'Общество с ограниченной ответственностью "Тестовая 1"', "1000000000001",
        PARCEL_ADDRESS),
    # Выписка соседа: правообладатель — не это общество, и её участок не наш.
    "https://178fz.roseltorg.ru/file/get/2/egrn-sosed.xml": extract(
        NEIGHBOUR, 'Акционерное общество "Соседнее"', "1000000000002",
        "город Москва, улица Соседняя, земельный участок 1"),
    "https://178fz.roseltorg.ru/file/get/3/lotovaya.docx": docx(
        f"Место нахождения общества: {COMPANY_ADDRESS}; помещение с кадастровым номером "
        f"{ADDRESS_NUMBER}.",
        f"Обществу на праве собственности принадлежит нежилое здание с кадастровым "
        f"номером {BUILDING}.",
    ),
}


def share_lot() -> AuctionLot:
    return AuctionLot(
        source=AuctionSource(platform=SourceKind.ROSELTORG,
                             lot_url="https://www.roseltorg.ru/procedure/178fzTEST00001/1",
                             external_lot_id="178fzTEST00001/1",
                             fetched_at="2026-11-02T00:00:00Z", source_name="Росэлторг"),
        lot_kind=LotKind.EQUITY_STAKE,
        title=("178fzTEST00001 Лот 1 Имущественные торги (178-ФЗ) Продажа доли, составляющей "
               "100% уставного капитала ООО «Тестовая 1», принадлежащей Тестовому фонду"),
        address=None,
        start_price_rub=595_986_000.0, current_price_rub=595_986_000.0,
        application_deadline="30.11.27 15:00", status="Прием заявок",
        documents=[
            AuctionDocument(title="Выписка ЕГРН ЗУ.xml", url=url, document_type="egrn")
            if "egrn" in url else
            AuctionDocument(title="Лотовая документация.docx", url=url, document_type="other")
            for url in FILES
        ],
        raw={"lot_region_code": "77"},
    )


def fake_bytes(document, **_kw):
    return FILES[document.url], "", "площадка"


def test_the_company_parcel_and_building_come_from_the_lot_documents(monkeypatch):
    monkeypatch.setattr(equity_assets, "_bytes_of", fake_bytes)
    lot = equity_assets.enrich_equity_from_documents(share_lot())
    assert lot.cadastral_numbers == [PARCEL, BUILDING]
    found = lot.raw["equity_assets"]
    assert found["company"]["name"] == "Тестовая 1"
    assert [row["cadastral_number"] for row in found["not_taken"]] == [NEIGHBOUR]
    assert found["refused"] == []


def test_the_company_address_is_never_taken_for_the_parcel(monkeypatch):
    monkeypatch.setattr(equity_assets, "_bytes_of", fake_bytes)
    lot = equity_assets.enrich_equity_from_documents(share_lot())
    assert ADDRESS_NUMBER not in lot.cadastral_numbers
    # Адрес лота — адрес участка из его выписки, а не место нахождения общества.
    assert lot.address == PARCEL_ADDRESS
    assert "Зоологическая" not in (lot.address or "")
    assert lot.land_area_sqm and lot.provenance["land_area_sqm"].raw_value.startswith(PARCEL)


def test_the_share_price_is_the_entry_price_and_the_assets_are_matched(monkeypatch):
    monkeypatch.setattr(equity_assets, "_bytes_of", fake_bytes)
    lot = equity_assets.enrich_equity_from_documents(share_lot())
    screened = equity_stake.screen(lot)
    assert screened["asset_match"] is True and screened["price_ok"] is True
    preset = build_project_preset(lot)
    assert abs(preset["auction_import"]["filled_inputs"]["purchase_price_mln"] - 595.986) < 1e-6


def test_an_unreadable_document_is_named_not_read_as_no_assets(monkeypatch):
    from auction_search.documents import DocumentTemporaryRefusal

    def refuse(document, **_kw):
        raise DocumentTemporaryRefusal("HTTP 503")

    monkeypatch.setattr(equity_assets, "_bytes_of", refuse)
    lot = equity_assets.enrich_equity_from_documents(share_lot())
    assert lot.cadastral_numbers == []
    assert len(lot.raw["equity_assets"]["refused"]) == 3


def test_the_ingest_route_reads_the_share_documents(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr(equity_assets, "_bytes_of", fake_bytes)

    class Adapter:
        def fetch_lot(self, url):
            return share_lot()

    monkeypatch.setattr(api, "_adapter_for", lambda url: Adapter())
    # Разбор лота — действие команды; здесь запрос идёт как от команды.
    monkeypatch.setattr(api.market_cabinet, "authorised", lambda request: True)
    app = FastAPI()
    api.install(app)
    body = TestClient(app).post(
        "/auctions/ingest",
        json={"url": "https://www.roseltorg.ru/procedure/178fzTEST00001/1"})
    assert body.status_code == 200, body.text
    body = body.json()
    assert body["lot"]["cadastral_numbers"] == [PARCEL, BUILDING]
    assert [row["cadastral_number"] for row in body["screening"]["equity_assets"]["objects"]] \
        == [PARCEL, BUILDING]
