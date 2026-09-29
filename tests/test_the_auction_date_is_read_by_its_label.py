"""Дата торгов читается по подписи поля у источника — по живым образцам, без сети.

Образцы сняты с ядра через `/auctions/source-page` 29.09.2026 и лежат в
`tests/fixtures/*_2026-09-29.*`:

* Росэлторг — таблица «Этапы» карточки: «Проведение торгов 19.10.26 10:00».
  Соседние строки той же таблицы — окончание заявок и вскрытие конвертов —
  тоже даты, поэтому дата берётся после своей подписи, а не по месту.
* ГПБ — явный ключ API `lots_first_date_begin_auction`.
* lot-online — на карточке лота даты торгов нет; «Дата и время аукциона»
  стоит только у СОСЕДНИХ лотов в блоке под карточкой. Дата чужого лота —
  не дата этого, и лот честно говорит «не получена от источника».
"""

from __future__ import annotations

import json
from pathlib import Path

from auction_search import krt_tenders
from auction_search.adapters import lot_online
from auction_search.adapters.etp_gpb import ETPGPBAdapter
from auction_search.adapters.roseltorg import RoseltorgAdapter

FIXTURES = Path(__file__).resolve().parent / "fixtures"
ROSELTORG = FIXTURES / "roseltorg_procedure_2026-09-29.html"
LOT_ONLINE = FIXTURES / "lot_online_product_2026-09-29.html"
GPB = FIXTURES / "etp_gpb_procedures_2026-09-29.json"


def test_roseltorg_takes_the_date_after_its_label(monkeypatch) -> None:
    html = ROSELTORG.read_text(encoding="utf-8")
    monkeypatch.setattr(RoseltorgAdapter, "_read",
                        staticmethod(lambda *_a, **_k: html))
    lot = RoseltorgAdapter().fetch_lot(
        "https://www.roseltorg.ru/procedure/21000005000000033452/1")
    assert lot.auction_date == "19.10.26 10:00"
    # Соседние даты «Этапов» остались на своих местах.
    assert lot.application_deadline == "09.10.26 15:00"
    origin = lot.provenance["auction_date"]
    assert origin.source_section == "карточка, «Этапы»: Проведение торгов"
    assert origin.source_url.endswith("/procedure/21000005000000033452/1")


def test_roseltorg_without_the_label_has_no_date() -> None:
    text = ("Этапы Публикация извещения 07.09.26 20:00 (МСК) Дата и время "
            "окончания приёма заявок до 09.10.26 15:00 (МСК) Вскрытие конвертов "
            "14.10.26 23:59 (МСК)")
    assert RoseltorgAdapter._auction_date(text) == (None, None)


def _gpb_item_with_key() -> dict:
    snapshot = json.loads(GPB.read_text(encoding="utf-8"))
    item = next(x for x in snapshot["data"]
                if x["attributes"].get(ETPGPBAdapter.AUCTION_DATE_KEY))
    # Живой ответ поиска 29.09.2026 — сплошь закупки (223-ФЗ/44-ФЗ) других
    # регионов с прошедшим сроком; адаптер отсекает их все. Фильтры здесь не
    # проверяются: проверяется ключ даты торгов в том виде, как он пришёл.
    attrs = dict(item["attributes"])
    attrs.pop("kind", None)
    attrs.update({"procedure_type_name": "Продажа имущества","lot_regions": [{"id": 77, "name": "г. Москва"}],
                  "stage": "accepting", "end_registration": "2099-01-01T12:00:00+03:00",
                  "title": "Продажа земельного участка, г. Москва, площадь 5 000 кв. м"})
    return {**item, "attributes": attrs}


def test_gpb_takes_the_explicit_key() -> None:
    item = _gpb_item_with_key()
    raw = item["attributes"][ETPGPBAdapter.AUCTION_DATE_KEY]
    lot = ETPGPBAdapter._to_lot(item, "2026-09-29T00:00:00+00:00")
    assert lot is not None
    assert lot.auction_date == ETPGPBAdapter._moment(raw)
    origin = lot.provenance["auction_date"]
    assert origin.raw_value == raw
    assert origin.source_section.startswith(
        "API площадки, ключ lots_first_date_begin_auction")


def test_gpb_without_the_key_has_no_date() -> None:
    item = _gpb_item_with_key()
    item["attributes"].pop(ETPGPBAdapter.AUCTION_DATE_KEY)
    lot = ETPGPBAdapter._to_lot(item, "2026-09-29T00:00:00+00:00")
    assert lot is not None and lot.auction_date is None
    assert "auction_date" not in lot.provenance


class _Response:
    def __init__(self, body: bytes) -> None:
        self._body = body
        self.headers = self

    def get_content_charset(self):
        return "utf-8"

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def test_lot_online_does_not_borrow_a_neighbours_date(monkeypatch) -> None:
    body = LOT_ONLINE.read_bytes()
    # Под карточкой стоят соседние лоты со своей «Датой и временем аукциона».
    assert "Дата и время аукциона".encode() in body
    monkeypatch.setattr(lot_online, "urlopen",
                        lambda *_a, **_k: _Response(body))
    lot = lot_online.LotOnlineAdapter().fetch_lot(
        "https://catalog.lot-online.ru/index.php?dispatch=products.view&product_id=1773641")
    assert lot.auction_date is None
    summary = krt_tenders.auction_date_fields(
        {"auction_date": lot.auction_date, "source": "Lot-online"})
    assert summary["auction_date_note"] == "дата торгов не получена от источника (Lot-online)"


def test_the_link_carries_where_the_date_came_from() -> None:
    sites = [{"slug": "s", "name": "", "okrug": "",
              "cadastral_numbers": ["77:01:0001001:1"]}]
    lot = {"title": "Аукцион на право заключения договора о КРТ",
           "cadastral_numbers": ["77:01:0001001:1"], "lot_kind": "krt",
           "application_deadline": "09.10.26 15:00", "auction_date": "19.10.26 10:00",
           "provenance": {"auction_date": {
               "source_section": "карточка, «Этапы»: Проведение торгов"}},
           "source": {"catalogue": "Росэлторг", "lot_url": "https://www.roseltorg.ru/procedure/1"}}
    linked = krt_tenders.match([lot], sites)
    [summary] = linked["by_site"].get("s") or linked["unmatched"]
    assert summary["auction_date_origin"] == "карточка, «Этапы»: Проведение торгов"
    assert summary["auction_date_label"] == "19.10.2026, 10:00 МСК"
