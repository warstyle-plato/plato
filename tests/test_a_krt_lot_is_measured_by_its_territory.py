"""Лот КРТ меряется территорией, а не ценой права.

«В торгах по КРТ на самом деле активных 12, а не 6» (владелец, 03.09.2026).
Часть терялась в допуске: продаётся ПРАВО на заключение договора, а стартовая
цена этого права ничего не говорит о масштабе площадки. Эталон снят со 121
сделки ПОКУПКИ недвижимости (48…931 млн ₽), и им мерили цену билета — то же
самое, что сверять «продукты» отчёта с построенными местами.

На живой выдаче 03.09.2026 так выпадали Шипиловский пр-д, влд. 55 (6,61 га,
право 4,1 млн ₽) и ул. Нижние Поля (8,97 га, 9,3 млн) — оба с адресом,
площадью и открытым приёмом заявок, оба «ниже профиля сделок».

Мера у вида своя и названа: местоположение, площадь территории, актуальность
процедуры. Цена в воротах не участвует — но и не замалчивается.

Запуск: python3 -m pytest tests/test_a_krt_lot_is_measured_by_its_territory.py -q
"""

from __future__ import annotations

from auction_search.catalogue_quality import catalogue_quality
from auction_search.models import AuctionLot, AuctionSource, LotKind, SourceKind


def _krt(**changes) -> AuctionLot:
    values = {
        "source": AuctionSource(
            SourceKind.TORGI_GOV,
            "https://torgi.gov.ru/new/public/lots/lot/21000005000000031369_1",
            "21000005000000031369_1",
            "now",
        ),
        "lot_kind": LotKind.KRT,
        "title": ("Аукцион на право заключения договора о комплексном развитии "
                  "территории нежилой застройки города Москвы, площадью 6,61 га"),
        "address": "г. Москва, Шипиловский пр-д, влд. 55",
        "land_area_sqm": 66_100.0,
        "current_price_rub": 4_113_340.42,
        "application_deadline": "2026-10-02T15:00:00+03:00",
    }
    values.update(changes)
    return AuctionLot(**values)


def test_a_cheap_right_is_not_a_small_site() -> None:
    """4,1 млн ₽ за право на 6,61 га — это не «ниже профиля сделок»."""
    quality = catalogue_quality(_krt())
    assert quality["accepted"] is True, quality["reasons"]
    assert quality["state"] == "ready"
    assert quality["measured_by"] == "площадь территории и объём строительства"


def test_the_price_is_not_a_gate_but_it_is_still_shown() -> None:
    """Порогом цену не меряем, а посчитанное соответствие остаётся видимым."""
    quality = catalogue_quality(_krt(current_price_rub=None, start_price_rub=None))
    assert quality["accepted"] is True, quality["reasons"]
    assert quality["fit"] is not None, "соответствие профилю всё равно считается"
    assert quality["minimum_profile_fit"] is None, "порога по цене у этого вида нет"


def test_a_site_without_a_place_is_still_refused() -> None:
    """Без местоположения лот не сопоставить ни с чем — это «не знаем»."""
    quality = catalogue_quality(_krt(address="", cadastral_numbers=[]))
    assert quality["accepted"] is False
    assert quality["state"] == "incomplete"
    assert any("адрес" in reason for reason in quality["reasons"]), quality["reasons"]


def test_a_site_without_metres_is_refused_too() -> None:
    """Площадь территории — единственная мера масштаба, какая у КРТ есть."""
    quality = catalogue_quality(_krt(land_area_sqm=None))
    assert quality["accepted"] is False
    assert any("площадь" in reason for reason in quality["reasons"]), quality["reasons"]


def test_an_expired_procedure_is_refused() -> None:
    quality = catalogue_quality(_krt(application_deadline="", status=""))
    assert quality["accepted"] is False
    assert any("срок" in reason for reason in quality["reasons"]), quality["reasons"]


def test_other_kinds_keep_the_deal_benchmark() -> None:
    """Правило заведено виду КРТ, а не всем: у покупки актива порог остаётся."""
    lot = _krt(lot_kind=LotKind.PROPERTY_COMPLEX, land_area_sqm=None,
               building_area_sqm=1_351, current_price_rub=4_113_340.42)
    quality = catalogue_quality(lot)
    assert quality["accepted"] is False
    assert quality["state"] == "outside_profile", quality
