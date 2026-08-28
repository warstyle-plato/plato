from __future__ import annotations

import json

from auction_search.adapters.nistp import NistpAdapter
from auction_search.adapters.etp_gpb import ETPGPBAdapter
from auction_search.adapters.etp_rf import ETPRFAdapter
from auction_search.adapters.fedresurs_api import FedresursApiAdapter
from auction_search.adapters.sberbank_ast import SberbankASTAdapter
from auction_search.api import _analysis_support, _discovery_adapters
from auction_search.models import LotKind, LotOrigin, SourceKind


class _Headers:
    @staticmethod
    def get_content_charset():
        return "utf-8"


class _Response:
    def __init__(self, body: str):
        self.body = body.encode("utf-8")
        self.headers = _Headers()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self):
        return self.body


def test_etp_gpb_reads_the_official_json_catalogue(monkeypatch) -> None:
    payload = {
        "data": [{
            "id": "2037204",
            "type": "procedure",
            "attributes": {
                "registry_number": "1005522",
                "stage": "accepting",
                "title": (
                    "Продажа земельного участка площадью 12 500 кв. м, "
                    "Москва, ул. Примерная, кадастровый номер 77:01:0001001:77"
                ),
                "platform_url": "https://etp.gpb.ru/procedure/2037204",
                "procedure_type_name": "Продажа имущества должника (банкротство)",
                "rebranding_truncated_path": "/procedures/auction/2037204",
                "amount": "650000000.0",
                "date_published": "2026-08-28T16:30:00.000+03:00",
                "lot_regions": ["Москва"],
                "end_registration": "2099-09-03T03:00:00.000+03:00",
            },
        }],
        "included": [],
        "meta": {"total": 1},
    }
    calls = []

    def fake_open(request, timeout):
        calls.append((request.full_url, timeout))
        return _Response(json.dumps(payload, ensure_ascii=False))

    monkeypatch.setattr("auction_search.adapters.etp_gpb.urlopen", fake_open)
    adapter = ETPGPBAdapter()
    adapter.SEARCH_TERMS = ("продажа земельного участка",)
    lots = adapter.discover_moscow()

    assert len(lots) == 1
    lot = lots[0]
    assert lot.source.platform is SourceKind.ETP_GPB
    assert lot.source.external_lot_id == "1005522"
    assert lot.lot_kind is LotKind.LAND_SALE
    assert lot.origin is LotOrigin.BANKRUPTCY
    assert lot.land_area_sqm == 12_500
    assert lot.current_price_rub == 650_000_000
    assert lot.cadastral_numbers == ["77:01:0001001:77"]
    assert lot.application_deadline.startswith("2099-09-03T03:00:00")
    assert "procedure%5Bstage%5D%5B0%5D=accepting" in calls[0][0]
    assert adapter.last_report["kept"] == 1


def test_etp_gpb_rejects_moscow_region_and_procurement() -> None:
    common = {
        "stage": "accepting",
        "end_registration": "2099-09-03T03:00:00+03:00",
        "amount": "100000000",
        "rebranding_truncated_path": "/procedures/1",
    }
    region = {"id": "1", "attributes": {
        **common, "title": "Продажа земельного участка, Московская область",
        "lot_regions": ["Московская область"],
    }}
    procurement = {"id": "2", "attributes": {
        **common, "title": "Поставка материалов для земельного участка в Москве",
        "lot_regions": ["Москва"],
    }}
    assert ETPGPBAdapter._to_lot(region, "now") is None
    assert ETPGPBAdapter._to_lot(procurement, "now") is None


def test_etp_gpb_reads_region_objects_from_the_current_api() -> None:
    attrs = {
        "title": "Продажа земельного участка площадью 10 000 кв. м",
        "lot_regions": [{"id": 77, "name": "г. Москва"}],
    }
    assert ETPGPBAdapter._is_moscow(attrs) is True
    assert ETPGPBAdapter._is_moscow({
        **attrs, "lot_regions": [{"name": "Московская область"}],
    }) is False


def test_etp_rf_reads_the_public_registry_table(monkeypatch) -> None:
    html = """
    <table><thead><tr>
      <th>Номер</th><th>Номер извещения</th><th>Предмет извещения</th>
      <th>Начальная цена</th><th>Организатор</th><th>Дата публикации</th>
      <th>Дата начала приема заявок</th><th>Дата завершения приема заявок</th>
      <th>Дата начала торгов</th><th>Статус извещения</th>
      <th>Статус торгов</th><th>Тип извещения</th>
    </tr></thead><tbody><tr>
      <td><a href="/Notification/id/20019">20019</a></td><td>BNKOA00014936</td>
      <td>Продажа земельного участка, г. Москва, площадь 57 367 кв. м,
          кадастровый номер 77:02:0002002:19</td>
      <td>277 000 000 руб.</td><td>Конкурсный управляющий</td><td>28.08.2026 10:00</td>
      <td>28.08.2026 12:00</td><td>01.09.2099 12:00</td><td>05.09.2099 12:00</td>
      <td>Опубликовано</td><td>Ожидает подачи заявок</td>
      <td>Продажа имущества должника (банкротство)</td>
    </tr></tbody></table>
    """
    monkeypatch.setattr(
        "auction_search.adapters.etp_rf.urlopen",
        lambda request, timeout, context: _Response(html),
    )

    adapter = ETPRFAdapter()
    lots = adapter.discover_moscow()

    assert len(lots) == 1
    lot = lots[0]
    assert lot.source.platform is SourceKind.ETP_RF
    assert lot.source.lot_url == "https://sale.etprf.ru/Notification/id/20019"
    assert lot.origin is LotOrigin.BANKRUPTCY
    assert lot.land_area_sqm == 57_367
    assert lot.current_price_rub == 277_000_000
    assert lot.cadastral_numbers == ["77:02:0002002:19"]
    assert adapter.last_report["cards"] == adapter.last_report["kept"] == 1


def test_sberbank_ast_reads_all_public_list_views(monkeypatch) -> None:
    html = """
    <table><tr>
      <th>Номер</th><th>Предмет</th><th>Цена</th><th>Регион</th>
      <th>Срок подачи</th><th>Статус</th>
    </tr><tr>
      <td>SBR00012345</td>
      <td><a href="/Bankruptcy/NBT/PurchaseView/4/0/0/12345">
        Продажа земельного участка, г. Москва, площадь 57 367 кв. м,
        кадастровый номер 77:02:0002002:19
      </a></td>
      <td>277 000 000 руб.</td><td>Москва</td>
      <td>01.09.2099 12:00</td><td>Приём заявок</td>
    </tr></table>
    """
    calls = []

    def fake_open(request, timeout):
        calls.append((request.full_url, request.data, request.headers.get("Referer")))
        return _Response(html)

    monkeypatch.setattr("auction_search.adapters.sberbank_ast.urlopen", fake_open)
    adapter = SberbankASTAdapter()
    lots = adapter.discover_moscow()

    assert len(lots) == 1
    lot = lots[0]
    assert lot.source.platform is SourceKind.SBERBANK_AST
    assert lot.source.external_lot_id == "SBR00012345"
    assert lot.source.lot_url == (
        "https://utp.sberbank-ast.ru/Bankruptcy/NBT/PurchaseView/4/0/0/12345"
    )
    assert lot.lot_kind is LotKind.LAND_SALE
    assert lot.origin is LotOrigin.BANKRUPTCY
    assert lot.land_area_sqm == 57_367
    assert lot.current_price_rub == 277_000_000
    assert lot.cadastral_numbers == ["77:02:0002002:19"]
    assert len(calls) == len(SberbankASTAdapter.LIST_URLS) * SberbankASTAdapter.MAX_PAGES
    assert all(item[1] and b"xmlFilter" in item[1] for item in calls)
    assert {item[2] for item in calls} == set(SberbankASTAdapter.LIST_URLS)


def test_sberbank_ast_form_contains_page_and_public_filter() -> None:
    body = SberbankASTAdapter._form_body(2).decode("cp1251")
    assert "hdnPageNum=2" in body
    assert "xmlFilter=" in body


def test_nistp_reads_the_public_bankruptcy_table(monkeypatch) -> None:
    html = """
    <table><tr>
      <th>Код торгов</th><th>Организатор</th><th>Должник, предмет торгов</th>
      <th>Начальная цена, руб.</th><th>Начало приема заявок</th>
      <th>Конец приема заявок</th><th>Состояние</th>
    </tr><tr>
      <td>69553-ОАОФ</td><td>Конкурсный управляющий</td>
      <td><a href="https://nistp.ru/bankrot/trade_view.php?trade_nid=490360#lot1">
        Земельный участок, г. Москва, площадь 12 500 кв. м,
        кадастровый номер 77:01:0001001:77
      </a></td>
      <td>650 000 000.00</td><td>03.09.2099 10:00</td>
      <td>05.09.2099 10:00</td><td>Прием заявок</td>
    </tr></table>
    """
    monkeypatch.setattr("auction_search.adapters.nistp.urlopen", lambda request, timeout: _Response(html))

    adapter = NistpAdapter()
    lots = adapter.discover_moscow()

    assert len(lots) == 1
    lot = lots[0]
    assert lot.source.platform is SourceKind.NISTP
    assert lot.source.external_lot_id == "490360-1"
    assert lot.source.lot_url == "https://nistp.ru/bankrot/trade_view.php?trade_nid=490360#lot1"
    assert lot.lot_kind is LotKind.LAND_SALE
    assert lot.origin is LotOrigin.BANKRUPTCY
    assert lot.land_area_sqm == 12_500
    assert lot.current_price_rub == 650_000_000
    assert lot.cadastral_numbers == ["77:01:0001001:77"]
    assert lot.application_deadline.startswith("2099-09-05T10:00")
    assert adapter.last_report["cards"] == adapter.last_report["kept"] == 1


def test_nistp_does_not_confuse_moscow_region_with_moscow() -> None:
    row = {
        "url": "https://nistp.ru/bankrot/trade_view.php?trade_nid=1#lot1",
        "lot_text": "Земельный участок, Московская область",
        "cells": ["1", "Организатор", "Земельный участок, Московская область",
                  "10 000 000.00", "01.09.2099 10:00", "03.09.2099 10:00", "Прием заявок"],
    }
    assert NistpAdapter._to_lot(row, "now") is None


def test_fedresurs_official_api_authenticates_and_reads_trade_xml(monkeypatch) -> None:
    xml = """<Envelope><Body><SetBiddingInvitation><BiddingInvitation>
      <TradeOrganizer><TradeOrganizerCompany FullName="Организатор" /></TradeOrganizer>
      <TradeInfo AuctionType="PublicOffer"><Application TimeEnd="2099-09-05T10:00:00+03:00" />
        <LotList><Lot LotNumber="2"><StartPrice>650000000</StartPrice>
          <TradeObjectHtml>Земельный участок, г. Москва, площадь 12 500 кв. м,
          кадастровый номер 77:01:0001001:77</TradeObjectHtml>
        </Lot></LotList>
      </TradeInfo></BiddingInvitation></SetBiddingInvitation></Body></Envelope>"""
    responses = [
        _Response(json.dumps({"jwt": "token"})),
        _Response(json.dumps({"total": 1, "pageData": [{
            "guid": "118311e8-bcdb-4fd6-b156-104b90709dc3", "number": "1670420",
            "type": "BiddingInvitation", "content": xml,
            "trade": {"number": "ПП-1", "guid": "trade-guid"},
        }]})),
    ]
    calls = []

    def fake_open(request, timeout):
        calls.append(request)
        return responses.pop(0)

    monkeypatch.setenv("FEDRESURS_API_LOGIN", "contract-login")
    monkeypatch.setenv("FEDRESURS_API_PASSWORD", "contract-password")
    monkeypatch.setattr("auction_search.adapters.fedresurs_api.urlopen", fake_open)
    adapter = FedresursApiAdapter()
    lots = adapter.discover_moscow()

    assert len(lots) == 1
    lot = lots[0]
    assert lot.source.platform is SourceKind.FEDRESURS
    assert lot.source.external_lot_id.endswith(":2")
    assert lot.land_area_sqm == 12_500
    assert lot.current_price_rub == 650_000_000
    assert lot.cadastral_numbers == ["77:01:0001001:77"]
    assert calls[0].full_url.endswith("/v1/auth")
    assert "/v1/trade-messages?" in calls[1].full_url
    assert calls[1].headers["Authorization"] == "Bearer token"
    assert b"contract-password" in calls[0].data


def test_fedresurs_without_contract_credentials_reports_configuration(monkeypatch) -> None:
    monkeypatch.delenv("FEDRESURS_API_LOGIN", raising=False)
    monkeypatch.delenv("FEDRESURS_API_PASSWORD", raising=False)
    adapter = FedresursApiAdapter()
    assert adapter.discover_moscow() == []
    assert "FEDRESURS_API_LOGIN" in adapter.last_report["reason"]


def test_new_sources_are_part_of_all_and_can_be_selected() -> None:
    all_adapters = _discovery_adapters("all")
    assert any(isinstance(item, ETPGPBAdapter) for item in all_adapters)
    assert any(isinstance(item, ETPRFAdapter) for item in all_adapters)
    assert any(isinstance(item, SberbankASTAdapter) for item in all_adapters)
    assert any(isinstance(item, NistpAdapter) for item in all_adapters)
    assert any(isinstance(item, FedresursApiAdapter) for item in all_adapters)
    assert isinstance(_discovery_adapters("etp_gpb")[0], ETPGPBAdapter)
    assert isinstance(_discovery_adapters("etp_rf")[0], ETPRFAdapter)
    assert isinstance(_discovery_adapters("sberbank_ast")[0], SberbankASTAdapter)
    assert isinstance(_discovery_adapters("nistp")[0], NistpAdapter)
    assert isinstance(_discovery_adapters("fedresurs")[0], FedresursApiAdapter)
    assert _analysis_support("https://etpgpb.ru/procedures/auction/2037204")["available"] is True
    support = _analysis_support("https://sale.etprf.ru/Notification/id/20019")
    assert support["available"] is False
    assert "поиску" in support["reason"]


def test_the_screen_names_both_new_sources() -> None:
    from auction_search.ui import auctions_page

    page = auctions_page()
    assert '<option value="etp_gpb">ЭТП ГПБ</option>' in page
    assert '<option value="etp_rf">ЭТП РФ</option>' in page
    assert '<option value="sberbank_ast">Сбербанк-АСТ</option>' in page
    assert '<option value="nistp">НИС</option>' in page
    assert '<option value="fedresurs">Федресурс / ЕФРСБ</option>' in page
