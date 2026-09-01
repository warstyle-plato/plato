"""Лоты о продаже долей в юрлицах: пороги владельца и активы общества.

Задача владельца (01.09.2026): «надо посмотреть ещё лоты по продаже долей в
юр лицах. С критериями возможными: стартовая цена 100 млн рублей за долю и от
500 за 100% долей. Доп критерий — если в лоте упоминается активы юр лица и там
есть недвижка или ЗУ».

Три вещи проверяются здесь, и каждая — про то, чтобы молчание источника не
превратилось в его отрицательный ответ.

Неназванная доля не считается стопроцентной: порог у неё нижний, и это сказано
вслух. Выбрать за продавца больший порог значит выбросить лот, о доле которого
он просто не написал.

Неопубликованная цена — не «дёшево»: критерий цены к ней не применяется вовсе,
ответ третий.

Активы — доп. критерий, а не ворота: лот без описания активов остаётся в
выдаче с названной пометкой. Требовать же от доли площадь участка нельзя —
её у такого лота не бывает, и прежний допуск выбросил бы весь вид целиком,
ответив «таких лотов нет» на «мы их не умеем мерить».

Запуск: python3 -m pytest tests/test_a_share_in_a_company_is_read_by_its_own_measure.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from auction_search import equity_stake, ui  # noqa: E402
from auction_search.catalogue_quality import catalogue_quality  # noqa: E402
from auction_search.classifier import classify_lot  # noqa: E402
from auction_search.models import (  # noqa: E402
    AuctionLot, AuctionSource, LotKind, SourceKind,
)

FULL = ("Продажа доли в размере 100 (сто) % уставного капитала ООО «РИВЬЕРА ПАРК». "
        "Активы общества: земельный участок 77:01:0004023:15 и здание площадью 4 200 кв.м.")
PART = ("Продажа доли в размере 51 % уставного капитала ООО «Ромашка». "
        "Активы общества: нежилое здание в Москве.")
BARE = "Продажа доли в размере 25 % уставного капитала ООО «Ромашка»."


def _lot(title: str, price: float | None) -> AuctionLot:
    return AuctionLot(
        source=AuctionSource(platform=SourceKind.LOT_ONLINE, lot_url="https://lot-online.ru/1",
                             external_lot_id="1", fetched_at="2026-09-01T00:00:00"),
        lot_kind=classify_lot(title), title=title,
        start_price_rub=price, status="Приём заявок",
    )


def test_the_kind_is_recognised():
    assert classify_lot(FULL) is LotKind.EQUITY_STAKE
    assert classify_lot(PART) is LotKind.EQUITY_STAKE


def test_a_share_in_common_property_is_not_a_share_in_a_company():
    """«Доля в праве общей долевой собственности» — это недвижимость."""
    assert not equity_stake.is_equity_lot(
        "Продажа 1/2 доли в праве общей долевой собственности на жилой дом")


def test_the_full_stake_uses_the_higher_floor():
    assert equity_stake.screen(_lot(FULL, 750_000_000))["price_ok"] is True
    below = equity_stake.screen(_lot(FULL, 480_000_000))
    assert below["price_ok"] is False
    assert "500 млн" in below["why"][0], below["why"]


def test_a_partial_stake_uses_the_lower_floor():
    assert equity_stake.screen(_lot(PART, 120_000_000))["price_ok"] is True
    assert equity_stake.screen(_lot(PART, 80_000_000))["price_ok"] is False


def test_an_unnamed_share_is_not_read_as_a_hundred_percent():
    text = "Продажа доли в уставном капитале ООО «Ромашка». Активы общества: здание."
    screened = equity_stake.screen(_lot(text, 150_000_000))
    assert screened["share_pct"] is None and screened["share_named"] is False
    assert screened["price_ok"] is True, "неназванная доля получила верхний порог"
    assert "не названа" in screened["share_label"]


def test_an_unpublished_price_is_a_third_answer():
    screened = equity_stake.screen(_lot(FULL, None))
    assert screened["price_ok"] is None
    assert "не опубликована" in screened["why"][0]
    assert catalogue_quality(_lot(FULL, None))["state"] == "incomplete"


def test_assets_are_read_with_a_quote():
    found = equity_stake.screen(_lot(FULL, 750_000_000))["assets"]
    assert found["real_estate"] and found["land"] and found["mentioned"]
    assert found["quotes"] and all(q["quote"] for q in found["quotes"]), \
        "признак активов поставлен без цитаты"


def test_undescribed_assets_are_not_absent_assets():
    screened = equity_stake.screen(_lot(BARE, 150_000_000))
    assert screened["asset_match"] is False
    assert any("не знаем" in line for line in screened["why"]), \
        "«активы не описаны» подано как «активов нет»"
    # Доп. критерий не ворота: лот остаётся в основной подборке.
    assert catalogue_quality(_lot(BARE, 150_000_000))["accepted"] is True


def test_the_missing_area_does_not_throw_the_whole_kind_away():
    """У доли нет ни участка, ни строений — и требовать их нельзя."""
    lot = _lot(FULL, 750_000_000)
    assert lot.land_area_sqm is None and lot.building_area_sqm is None
    quality = catalogue_quality(lot)
    assert quality["accepted"] is True, quality["reasons"]
    assert quality["measured_by"] == "цена доли и активы общества"


def test_a_price_below_the_floor_is_named_not_hidden():
    quality = catalogue_quality(_lot(FULL, 120_000_000))
    assert quality["accepted"] is False
    assert any("порог" in reason for reason in quality["reasons"]), quality["reasons"]


def test_the_page_shows_the_kind_and_counts_it_once():
    page = ui.auctions_page(None)
    assert "equity_stake:'Доля в юрлице'" in page, "вид лота на экране не назван"
    assert '<option value="equity_stake">' in page, "по виду нельзя отобрать"
    assert "function equityNote(" in page, "что стоит за долей, на экране не сказано"
    body = page[page.index("function equityNote("):]
    body = body[:body.index("\nfunction ")]
    for forbidden in ("100000000", "500000000", "1e8", "5e8"):
        assert forbidden not in body, "порог владельца зашит в страницу второй копией"


def test_the_thresholds_are_declared_once():
    assert equity_stake.PART_STAKE_MIN_RUB == 100_000_000
    assert equity_stake.FULL_STAKE_MIN_RUB == 500_000_000
    page = ui.auctions_page(None)
    assert "PART_STAKE_MIN" not in page and "FULL_STAKE_MIN" not in page
