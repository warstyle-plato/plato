"""Аукцион КРТ города доезжает до подборки: падеж, гектары, раздел площадки.

Владелец прислал живой лот Росэлторга (01.09.2026): «Аукцион на право
заключения договора о комплексном развитии территорий нежилой застройки
города Москвы, площадью 14,62 га», 2 403 657 113,51 ₽, заявки до 21.09.26.
Его слова: «твои торги не работают вообще».

Три вещи мешали ему доехать, и все три видны в нашем коде, без ответа
источника:

1. «города Москвы» не считалось Москвой. Проверка требовала именительного
   падежа, а копий её было три — две искали подстроку «москва» и не узнавали
   ни «Москвы», ни «Москве».
2. «14,62 га» не читалось как площадь: разбор знал только квадратные метры.
   Метров при этом нет вовсе, а допуск подборки требует площадь.
3. Раздел имущества «Развитие территории», откуда город публикует КРТ,
   разведка не спрашивала вовсе — она ходила только в поиск по тегам.

Запуск: python3 -m pytest tests/test_the_city_krt_lot_reaches_us.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from auction_search.adapters.roseltorg import RoseltorgAdapter  # noqa: E402
from auction_search.classifier import classify_lot  # noqa: E402
from auction_search.models import AuctionLot, AuctionSource, SourceKind  # noqa: E402
from auction_search.parsing import mentions_moscow, parse_hectares_sqm  # noqa: E402

OWNER_TITLE = ("Аукцион на право заключения договора о комплексном развитии "
               "территорий нежилой застройки города Москвы, площадью 14,62 га")


def _lot(title: str) -> AuctionLot:
    return AuctionLot(
        source=AuctionSource(
            platform=SourceKind.ROSELTORG,
            lot_url="https://www.roseltorg.ru/procedure/000000/1",
            external_lot_id="000000/1",
            fetched_at="",
            source_name="Росэлторг",
        ),
        lot_kind=classify_lot(title, "Аукцион", []),
        title=title,
        raw={},
    )


def test_the_owner_lot_passes_every_gate() -> None:
    lot = _lot(OWNER_TITLE)
    assert lot.lot_kind in RoseltorgAdapter.RELEVANT_KINDS
    assert RoseltorgAdapter._is_asset_disposal(lot)
    assert RoseltorgAdapter._confirmed_moscow(lot), (
        "«города Москвы» — это Москва: заголовок аукциона города падеж не меняет")
    assert RoseltorgAdapter._area_from_text(OWNER_TITLE) == 146_200


def test_moscow_is_read_in_every_case_and_the_oblast_is_not_moscow() -> None:
    for text in ("города Москвы", "в городе Москве", "г. Москва", "МОСКВЫ"):
        assert mentions_moscow(text), text
    for text in ("Московская область", "Московской области", "Новомосковск",
                 "пос. Московский"):
        assert not mentions_moscow(text), text
    # Область рядом с городом города не отменяет.
    assert mentions_moscow("Москва и Московская область")


def test_hectares_are_square_metres_and_metres_are_not_hectares() -> None:
    assert parse_hectares_sqm("площадью 14,62 га") == 146_200
    assert parse_hectares_sqm("2,5 гектара") == 25_000
    assert parse_hectares_sqm("площадь 1200 кв.м") is None


def test_a_deadline_without_an_hour_is_the_end_of_that_day() -> None:
    """«заявки до 21.09.26» — так пишет извещение города, и это срок, а не мусор.

    Прежде срок без часа не читался вовсе, и лот выбрасывался как
    просроченный: «часа не назвали» превращалось в «время вышло».
    """
    assert RoseltorgAdapter._deadline("Прием заявок до 21.09.26") == "21.09.26"
    assert RoseltorgAdapter._has_current_deadline("21.09.26")
    assert not RoseltorgAdapter._has_current_deadline("01.01.2020")
    # Час, если он назван, не теряется: образцы с часом стоят первыми.
    assert RoseltorgAdapter._deadline(
        "Дата и время окончания приема заявок | 21.09.2026 10:00") == "21.09.2026 10:00"


def test_the_rule_is_declared_once() -> None:
    """Три копии проверки Москвы расходились молча — теперь она одна."""
    for name in ("roseltorg", "lot_online", "investmoscow"):
        body = (ROOT / "auction_search" / "adapters" / f"{name}.py").read_text()
        assert "mentions_moscow" in body, name
        assert '"москва" in' not in body.lower(), (
            f"{name}: своя проверка Москвы — это вторая копия правила")


def test_the_property_section_is_asked_and_only_for_links() -> None:
    """Раздел спрашивается, но своего разбора карточек у него нет.

    Со страницы берутся только ссылки на `/procedure/`; каждая читается тем же
    `fetch_lot`. Разбор чужой разметки по догадке однажды уже приехал на прод
    тридцатью гаражами.
    """
    urls = [url for _name, url in RoseltorgAdapter.SECTION_URLS]
    assert any("razvitie-territorii" in url for url in urls)
    assert any("okato" in url for url in urls), "раздел спрашивается по Москве"
    body = (ROOT / "auction_search" / "adapters" / "roseltorg.py").read_text()
    section_reader = body[body.index("for label, section_url in self.SECTION_URLS"):
                          body.index("for tag in self.DISCOVERY_TAGS")]
    assert "_procedure_urls" in section_reader
    for invented in ("Начальная цена", "class=", "itemprop", "data-lot"):
        assert invented not in section_reader, (
            "разбора карточек раздела быть не должно, пока не увиден ответ")


def test_a_silent_section_is_a_coverage_line_not_an_empty_market() -> None:
    body = (ROOT / "auction_search" / "adapters" / "roseltorg.py").read_text()
    assert '"sections"' in body and '"market"' in body
