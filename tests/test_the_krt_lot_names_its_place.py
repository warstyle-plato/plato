"""Место аукциона КРТ город называет в имени процедуры — читаем его оттуда.

«Как был 1 крт так и остался» (владелец, 03.09.2026). Постраничный обход
раздела к тому дню уже работал: живой прод отдавал 47 карточек и шесть
прочитанных КРТ. До экрана доходил один — пять убирал допуск основной подборки
с причиной «нет адреса или кадастрового номера», при заполненных площади, цене
и сроке подачи:

    2,9 га за 110,8 млн ₽ · 14,5 га за 87,4 млн ₽
    11,7 га за 3 825,5 млн ₽ · 6,6 га за 4,1 млн ₽

Допуск при этом верен — сопоставить лот с эталоном сделок без местоположения
нельзя, и ослаблять его нельзя тоже. Неверно было другое: адрес у карточки
ЕСТЬ, он стоит в самом имени процедуры, а мы его не читали. Ошибка того же
рода, что «раздел спрашивался одной страницей»: чинили не то место цепочки.

Названия здесь — настоящие, снятые с прода 03.09.2026.

Запуск: python3 -m pytest tests/test_the_krt_lot_names_its_place.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from auction_search.adapters.roseltorg import RoseltorgAdapter  # noqa: E402

WITH_ADDRESSES = (
    "21000005000000032802 Лот 1 Имущественные торги (178-ФЗ) Аукцион на право "
    "заключения договора о комплексном развитии территорий нежилой застройки "
    "города Москвы, площадью 2,90 га, расположенных по адресам: г. Москва, "
    "Куркинское ш., вл. 27-39, Куркинское ш., вл. 21, ул. Героев Панфиловцев, "
    "вл. 20, корп. 1")
WITH_ONE_ADDRESS = (
    "21000005000000031369 Лот 1 Аукцион на право заключения договора о "
    "комплексном развитии территории по адресу: г. Москва, Шипиловский "
    "пр-д, влд. 55")
WITH_A_ZONE = (
    "21000005000000031472 Лот 1 Имущественные торги (178-ФЗ) Аукцион на право "
    "заключения договора о комплексном развитии территории нежилой застройки "
    "города Москвы, площадью 11,74 га, расположенной в производственной зоне "
    "№ 54 «Прожектор» (территория 1)")
WITHOUT_A_PLACE = (
    "Аукцион на право заключения договора о комплексном развитии территории")


def test_the_addresses_are_read_from_the_name() -> None:
    place = RoseltorgAdapter._address_from_title(WITH_ADDRESSES)
    assert place.startswith("г. Москва, Куркинское ш., вл. 27-39")
    assert "Героев Панфиловцев" in place, "второй адрес не обрезаем — их несколько"
    assert RoseltorgAdapter._address_from_title(WITH_ONE_ADDRESS) == (
        "г. Москва, Шипиловский пр-д, влд. 55")


def test_a_zone_is_a_place_too() -> None:
    """Город называет место и без улицы. Это местоположение, а не пропуск."""
    assert RoseltorgAdapter._address_from_title(WITH_A_ZONE) == (
        "производственной зоне № 54 «Прожектор» (территория 1)")


def test_an_unnamed_place_stays_unnamed() -> None:
    """Не названо — пусто. Выдуманный адрес хуже отсутствующего: на нём стоит
    сопоставление с эталоном сделок и весь балл соответствия."""
    assert RoseltorgAdapter._address_from_title(WITHOUT_A_PLACE) == ""
    assert RoseltorgAdapter._address_from_title("") == ""


def test_the_gate_lets_the_lot_through_once_the_place_is_read() -> None:
    """Тот же допуск, что убирал лот, принимает его с прочитанным адресом."""
    from auction_search.catalogue_quality import catalogue_quality
    from auction_search.models import (AuctionLot, AuctionSource, LotKind,
                                       SourceKind)

    def lot(address: str | None) -> AuctionLot:
        return AuctionLot(
            source=AuctionSource(platform=SourceKind.ROSELTORG, lot_url="https://e/1",
                                 external_lot_id="1", source_name="Росэлторг",
                                 fetched_at="2026-09-03T05:51:42Z"),
            lot_kind=LotKind.KRT, title=WITH_ADDRESSES, address=address,
            land_area_sqm=29000.0, start_price_rub=110760951.18,
            current_price_rub=110760951.18, application_deadline="24.09.26 15:00",
            status="Прием заявок", raw={"lot_region_code": "77"})

    without = catalogue_quality(lot(None))
    assert without["accepted"] is False
    assert any("адрес" in reason for reason in without["reasons"])

    place = RoseltorgAdapter._address_from_title(WITH_ADDRESSES)
    with_place = catalogue_quality(lot(place))
    assert with_place["accepted"] is True, with_place["reasons"]
