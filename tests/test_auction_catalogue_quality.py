"""Основная выдача содержит измеримые девелоперские лоты, а не сырые карточки."""

from auction_search.adapters.torgi_gov import TorgiGovAdapter
from auction_search.api import _discovery_adapters
from auction_search.catalogue_quality import catalogue_quality
from auction_search.models import (
    AuctionLot, AuctionSource, LotKind, SourceKind,
)
from auction_search.service import AuctionSearchService


def _lot(**changes) -> AuctionLot:
    values = {
        "source": AuctionSource(
            SourceKind.LOT_ONLINE,
            "https://catalog.lot-online.ru/example",
            "example",
            "now",
        ),
        "lot_kind": LotKind.PROPERTY_COMPLEX,
        "title": "Имущественный комплекс под редевелопмент",
        "address": "Москва, ул. Примерная, д. 1",
        "cadastral_numbers": ["77:01:0001001:1"],
        "building_area_sqm": 1_351,
        "current_price_rub": 204_834_000,
        "application_deadline": "2099-12-01T12:00:00+03:00",
    }
    values.update(changes)
    return AuctionLot(**values)


def test_a_complete_lot_enters_the_main_catalogue() -> None:
    lot = _lot()
    quality = catalogue_quality(lot)
    assert quality["accepted"] is True
    assert quality["state"] == "ready"
    assert AuctionSearchService([]).last_quality_report["seen"] == 0


def test_an_unmeasured_card_is_not_presented_as_an_interesting_lot() -> None:
    lot = _lot(
        address=None,
        cadastral_numbers=[],
        building_area_sqm=None,
        current_price_rub=None,
        application_deadline=None,
    )

    class _One:
        def discover_moscow(self):
            return [lot]

    service = AuctionSearchService([_One()])
    assert service.discover_moscow() == []
    assert service.last_quality_report == {
        "seen": 1,
        "accepted": 0,
        "incomplete": 1,
        "outside_profile": 0,
        "noise": 0,
    }
    assert service.discover_moscow(include_noise=True) == [lot]
    assert "нет площади" in " ".join(catalogue_quality(lot)["reasons"])


def test_a_garage_is_available_only_in_show_everything_mode() -> None:
    garage = _lot(
        title="Гаражный бокс",
        building_area_sqm=26,
        current_price_rub=200_000,
    )
    quality = catalogue_quality(garage)
    assert quality["accepted"] is False
    assert quality["state"] == "outside_profile"


def test_a_small_real_deal_is_not_cut_by_an_invented_area_threshold() -> None:
    # В файле сделок есть строения меньше 500 м². Высокая цена входа может
    # оставить такой объект у нижней границы профиля — размер сам по себе не
    # является запретом.
    compact = _lot(building_area_sqm=196.7, current_price_rub=204_834_000)
    quality = catalogue_quality(compact)
    assert quality["fit"]["fit"] == 0.7
    assert quality["accepted"] is True


def test_default_sources_do_not_mislabel_torgi_gov_as_bankruptcy() -> None:
    assert not any(isinstance(adapter, TorgiGovAdapter)
                   for adapter in _discovery_adapters("all"))
    assert isinstance(_discovery_adapters("torgi_gov")[0], TorgiGovAdapter)


def test_the_screen_names_the_main_and_raw_catalogues_honestly() -> None:
    from auction_search.ui import auctions_page

    page = auctions_page()
    assert "Основные проверенные источники" in page
    assert "ГИС Торги — отдельно, сырые данные" in page
    assert "Интересные · данные заполнены" in page
    assert "Показать неполные и шум" in page
