"""ЕФРСБ: читатель торгов по банкротству, написанный по живым ответам.

Владелец не нашёл в «Торгах» лот из сообщения № 25074336 (ООО «Инжтехсвязь»,
публичное предложение на «Вердиктъ», 19.10.2026). Образцы в
`tests/fixtures/efrsb/` — ответы сервиса того же дня; поля разбора взяты из
них, а не из догадки.

Запуск: python3 -m pytest tests/test_efrsb_adapter.py -q
"""

from __future__ import annotations

import json
import sys
import urllib.error
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from auction_search.adapters import efrsb  # noqa: E402
from auction_search.models import (  # noqa: E402
    AuctionLot, AuctionSource, LotKind, LotOrigin, SourceKind)
from auction_search.service import AuctionSearchService  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "efrsb"
MSK = ZoneInfo("Europe/Moscow")
OWNER_LINK = "https://fedresurs.ru/bankruptmessages/5EA9BE17D759407D98021644C8B27F76"
NOW = datetime(2026, 10, 20, 12, 0, tzinfo=MSK)


def answer(name: str):
    return json.loads((FIX / name).read_text(encoding="utf-8"))["answer"]


class FakeClient:
    """Отдаёт сверенные ответы по путям; чужой путь — пустая страница."""

    def __init__(self, routes: dict[str, object], refuse_after: int | None = None):
        self.routes = routes
        self.requests = 0
        self.asked: list[tuple[str, dict]] = []
        self.refuse_after = refuse_after

    def get(self, path, params=None):
        self.requests += 1
        self.asked.append((path, dict(params or {})))
        if self.refuse_after is not None and self.requests > self.refuse_after:
            raise efrsb.SourceRefused("ЕФРСБ отказал в запросе (код 429): сервис ограничивает "
                                      "частоту обращений, сбор продолжится позже")
        if path == "biddings" and int((params or {}).get("offset") or 0) > 0:
            return {"pageData": [], "found": 0}
        return self.routes.get(path, {"pageData": []})


def moscow_routes() -> dict[str, object]:
    lots = answer("bidding_cbb43d13_lots.json")
    return {
        "biddings": answer("biddings_moscow_inn_7713210910.json"),
        "biddings/cbb43d13-5c05-4131-88a7-2a6a277679a1/lots": lots,
        "biddings/cbb43d13-5c05-4131-88a7-2a6a277679a1": answer("bidding_cbb43d13.json"),
        # Те же лоты у торгов с прошедшим сроком: статус у них «Открыт приём
        # заявок», и отсеять их обязан срок.
        "biddings/a9c37ecc-dcf4-445f-a454-e43037ef218b/lots": lots,
        "biddings/1535223c-07be-4c4a-bbaf-7853ea1045aa/lots": lots,
    }


def adapter_after_harvest(tmp_path, client) -> efrsb.EfrsbAdapter:
    path = str(tmp_path / "efrsb.json")
    efrsb._STARTED.clear()
    adapter = efrsb.EfrsbAdapter(
        store_path=path,
        starter=lambda job: efrsb.harvest("live", client=client, store_path=path))
    adapter.now = NOW
    return adapter


# --- главный вопрос владельца ------------------------------------------------

def test_the_owners_message_is_found_with_its_link_price_and_place(tmp_path) -> None:
    client = FakeClient(moscow_routes())
    adapter = adapter_after_harvest(tmp_path, client)
    adapter.discover_moscow()                      # запускает сбор
    lots = adapter.discover_moscow()               # читает собранное
    assert [lot.source.external_lot_id for lot in lots] == ["3031-ОТПП-1#1"]
    lot = lots[0]
    assert lot.source.lot_url == OWNER_LINK, "ссылка — на то самое сообщение"
    assert lot.source.platform is SourceKind.EFRSB
    assert lot.origin is LotOrigin.BANKRUPTCY
    assert lot.start_price_rub == 3_600_000_000
    assert "77:09:0005011:1057" in lot.cadastral_numbers
    assert lot.application_deadline.startswith("2027-03-15T12:00")
    assert lot.raw["efrsb_trade_place"] == "«Электронная площадка «Вердиктъ»"
    assert lot.procedure_type == "Банкротство, публичное предложение"
    assert lot.seller == 'ООО "ИНЖТЕХСВЯЗЬ"'


def test_stale_trades_with_an_open_status_are_not_live(tmp_path) -> None:
    """2684-ОТПП-1 и 2354-ОАОФ-1 — «Открыт приём заявок», а срок прошёл."""
    adapter = adapter_after_harvest(tmp_path, FakeClient(moscow_routes()))
    adapter.discover_moscow()
    numbers = {lot.raw["efrsb_trade_number"] for lot in adapter.discover_moscow()}
    assert numbers == {"3031-ОТПП-1"}
    assert adapter.last_report["skipped_not_live"] == 2


def test_the_message_link_alone_gives_the_same_lot() -> None:
    lots = efrsb.lots_from_message(answer("message_25074336.json"),
                                   "5ea9be17-d759-407d-9802-1644c8b27f76", "now")
    assert len(lots) == 1
    assert lots[0].source.lot_url == OWNER_LINK
    assert lots[0].start_price_rub == 3_600_000_000


def test_areas_are_summed_over_the_objects_of_the_lot(tmp_path) -> None:
    """Первая площадь текста — 151 м², одно здание из двадцати."""
    adapter = adapter_after_harvest(tmp_path, FakeClient(moscow_routes()))
    adapter.discover_moscow()
    lot = adapter.discover_moscow()[0]
    assert lot.land_area_sqm == 12_097 + 5_097, "два права аренды участков"
    assert lot.building_area_sqm > 15_611.5
    assert "сумма" in lot.provenance["building_area_sqm"].raw_value


# --- регион: должника и имущества ----------------------------------------------

def test_search_asks_moscow_debtors_with_the_verified_names(tmp_path) -> None:
    client = FakeClient(moscow_routes())
    adapter = adapter_after_harvest(tmp_path, client)
    adapter.discover_moscow()
    path, params = client.asked[0]
    assert path == "biddings"
    assert params["regionCode"] == "77"
    assert params["onlyAvailableToParticipate"] == "true"
    assert params["limit"] == 15


def test_a_moscow_debtor_selling_land_in_tula_is_not_moscow() -> None:
    entry = {"row": answer("biddings_moscow_inn_7713210910.json")["pageData"][0],
             "card": answer("bidding_cbb43d13.json"),
             "lots": [{"number": "1", "startPrice": 50_000_000.0,
                       "status": {"code": "ApplicationSessionStarted"},
                       "tradeObject": "Земельный участок 528 000 кв.м, кадастровый номер "
                                      "71:14:030301:12, обл. Тульская"}]}
    lots, skipped = efrsb.to_lots(entry, "now", now=NOW)
    assert lots == [] and skipped["not_moscow"] == 1


def test_region_50_answer_has_no_moscow_debtor_trades() -> None:
    """Сверка смысла regionCode: московский должник с 50 не находится."""
    assert answer("biddings_region_50_inn_7713210910.json")["pageData"] == []
    assert answer("biddings_moscow_inn_7713210910.json")["found"] == 3


# --- отказ и фон -----------------------------------------------------------------

def test_first_harvest_in_progress_says_so(tmp_path) -> None:
    adapter = efrsb.EfrsbAdapter(store_path=str(tmp_path / "efrsb.json"),
                                 starter=lambda job: None)
    efrsb._STARTED.clear()
    assert adapter.discover_moscow() == []
    assert "первый сбор" in adapter.last_report["reason"]


def test_a_refusal_is_named_and_what_was_collected_stays(tmp_path) -> None:
    client = FakeClient(moscow_routes(), refuse_after=3)
    adapter = adapter_after_harvest(tmp_path, client)
    adapter.discover_moscow()
    adapter.discover_moscow()
    assert "429" in adapter.last_report["reason"]
    assert "Сбор прерван" in adapter.last_report["reason"]


def test_a_429_from_the_service_becomes_a_refusal() -> None:
    def opener(request, timeout, context):
        raise urllib.error.HTTPError(request.full_url, 429, "Too Many", {}, None)

    with pytest.raises(efrsb.SourceRefused, match="429"):
        efrsb.Client(gap_seconds=0, opener=opener).get("biddings", {"limit": 15})


# --- завершённые ---------------------------------------------------------------

def test_finished_lot_carries_the_result_price() -> None:
    finished = answer("bidding_b56811b9_lots_finished.json")["pageData"][0]
    row = dict(answer("biddings_moscow_inn_7713210910.json")["pageData"][0])
    row["status"] = {"code": "Finished", "name": "Завершенные"}
    lot_raw = dict(finished, tradeObject="Нежилое здание и земельный участок, общая пл. "
                                         "900 кв.м, кад. № 77:09:0005011:1078, г. Москва")
    lots, _ = efrsb.to_lots({"row": row, "lots": [lot_raw]}, "now", finished=True)
    assert lots and lots[0].result_price_rub == finished["currentPrice"]
    assert lots[0].status_code == "Finished"


def test_finished_window_reads_trade_start_dates(tmp_path) -> None:
    path = str(tmp_path / "efrsb.json")
    client = FakeClient({"biddings": answer("biddings_moscow_finished_window.json")})
    efrsb.harvest("finished", client=client, store_path=path,
                  since=date(2026, 7, 19), until=date(2026, 10, 19), max_pages=1)
    params = client.asked[0][1]
    assert params["tradeStartDate"] == "2026-07-19T00:00:00"
    assert params["tradeEndDate"] == "2026-10-19T23:59:59"
    assert "onlyAvailableToParticipate" not in params
    # Лоты дочитываются только у завершённых торгов, а не у всех в окне.
    lot_paths = [p for p, _ in client.asked if p.endswith("/lots")]
    codes = [r["status"]["code"] for r in answer("biddings_moscow_finished_window.json")["pageData"]]
    assert len(lot_paths) == sum(code in efrsb.FINISHED_STATUSES for code in codes)


# --- дубли с площадками, которые мы читаем ---------------------------------------

def _platform_lot(kind: SourceKind, external: str, cad: list[str]) -> AuctionLot:
    return AuctionLot(source=AuctionSource(kind, f"https://example/{external}", external, "now"),
                      lot_kind=LotKind.PROPERTY_COMPLEX, title="Здание", cadastral_numbers=cad)


def _registry_lot(host: str, number: str, cad: list[str]) -> AuctionLot:
    lot = _platform_lot(SourceKind.EFRSB, f"{number}#1", cad)
    lot.source = AuctionSource(SourceKind.EFRSB, OWNER_LINK, f"{number}#1", "now")
    lot.raw = {"efrsb_trade_place_host": host, "efrsb_trade_number": number}
    return lot


def test_the_same_trade_on_nis_is_kept_once_with_the_registry_link() -> None:
    nis = _platform_lot(SourceKind.NISTP, "37014-1", [])
    copy = _registry_lot("nistp.ru", "37014-ОТПП", [])
    kept = AuctionSearchService._deduplicate([copy, nis])
    assert kept == [nis]
    assert nis.raw["efrsb_message_url"] == OWNER_LINK


def test_a_shared_cadastral_number_on_sberbank_is_the_same_trade() -> None:
    sber = _platform_lot(SourceKind.SBERBANK_AST, "SBR012-1", ["77:01:1:1", "77:01:1:2"])
    copy = _registry_lot("sberbank-ast.ru", "SBR012-999", ["77:01:1:2"])
    assert AuctionSearchService._deduplicate([sber, copy]) == [sber]


def test_a_trade_on_a_platform_we_do_not_read_stays() -> None:
    """«Вердиктъ» мы не читаем — лот ЕФРСБ там единственный."""
    nis = _platform_lot(SourceKind.NISTP, "3031-1", [])
    copy = _registry_lot("vertrades.ru", "3031-ОТПП-1", [])
    assert len(AuctionSearchService._deduplicate([nis, copy])) == 2


def test_same_number_on_another_platform_is_not_a_duplicate() -> None:
    gpb = _platform_lot(SourceKind.ETP_GPB, "37014", [])
    copy = _registry_lot("nistp.ru", "37014-ОТПП", [])
    assert len(AuctionSearchService._deduplicate([gpb, copy])) == 2


# --- выдача ----------------------------------------------------------------------

def test_the_source_is_in_all_and_selectable() -> None:
    from auction_search.api import _analysis_support, _discovery_adapters
    from auction_search.ui import auctions_page

    assert any(isinstance(item, efrsb.EfrsbAdapter) for item in _discovery_adapters("all"))
    assert isinstance(_discovery_adapters("efrsb")[0], efrsb.EfrsbAdapter)
    assert '<option value="efrsb">ЕФРСБ</option>' in auctions_page()
    support = _analysis_support(OWNER_LINK)
    assert support["available"] is False and "ЕФРСБ" in support["reason"]


def test_reasons_are_plain_sentences() -> None:
    """Строка охвата читается посетителем: полные фразы, без кодов статусов."""
    body = (ROOT / "auction_search" / "adapters" / "efrsb.py").read_text(encoding="utf-8")
    assert "Лоты появятся в выдаче, когда он закончится." in body
    assert "Показано то, что успели собрать." in body


def test_the_switch_stops_the_background_harvest(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv(efrsb.HARVEST_FLAG, "0")
    efrsb._STARTED.clear()
    adapter = efrsb.EfrsbAdapter(store_path=str(tmp_path / "efrsb.json"))
    assert adapter.discover_moscow() == []
    assert efrsb.HARVEST_FLAG in adapter.last_report["reason"]
    assert not (tmp_path / "efrsb.json.lock").exists()


def test_objects_listed_with_dashes_are_split_too() -> None:
    """Живой лот 241161-МЭТС-1 (19.10.2026): квартира 293,1 м² и участок 300 м²."""
    text = ("- жилое помещение (квартира в сблокированном жилом доме), общей площадью "
            "293,1 кв.м., кадастровый номер 77:18:0170103:446, по адресу г. Москва; "
            "- земельный участок, общей площадью 300 кв.м., кадастровый номер "
            "50:21:0120114:437, виды разрешенного использования: для размещения "
            "коттеджной застройки; культурно-делового центра")
    land, building, objects = efrsb._areas(text)
    assert (land, building, objects) == (300, 293.1, 2)
