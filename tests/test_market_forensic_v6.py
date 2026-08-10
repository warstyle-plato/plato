"""Регрессия на классы ошибок, найденные forensic-ревизией живого preview.

Каждый тест назван по классу ошибки и воспроизводит её на тех же строках, что
пришли со стенда. Проверяется поведение конвейера, а не пересказ намерения:
где нужен поиск или геокодер, подставляется двойник, а не пропускается шаг.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from market_search import documents
from market_search.candidates_v6 import extract_candidates
from market_search.entities import merge_geographic_duplicates, resolve_entities
from market_search.geo_resolution import (
    RESOLVED,
    UNRESOLVED,
    ProjectGeoResolver,
    address_signature,
    extract_address,
    precision_is_usable,
)
from market_search.geocoder import GeoPoint, GeocodingError
from market_search.normalize import canonical_key, looks_like_project_name, name_similarity
from market_search.price_evidence import VerifiedPriceEnricher
from market_search.recommendation import market_recommendation
from market_search.service import MarketDiscoveryService as LegacyService
from market_search.service_v6 import MarketDiscoveryService as ServiceV6
from market_search.yandex_search import SearchDoc


SUBJECT = "Москва, Саввинская набережная, 25"


def doc(title: str, url: str, snippet: str = "", rank: int = 1, domain: str | None = None) -> SearchDoc:
    from urllib.parse import urlsplit

    return SearchDoc(
        title=title,
        url=url,
        domain=(domain if domain is not None else (urlsplit(url).hostname or "")),
        snippet=snippet,
        rank=rank,
    )


class FakeSearch:
    """Поисковый клиент, отвечающий заранее заданной выдачей."""

    def __init__(self, responses: dict[str, list[SearchDoc]] | None = None, default: list[SearchDoc] | None = None):
        self.responses = responses or {}
        self.default = default or []
        self.queries: list[str] = []

    def search(self, query: str, *, groups_on_page: int = 10) -> list[SearchDoc]:
        self.queries.append(query)
        for needle, docs in self.responses.items():
            if needle in query:
                return docs
        return self.default


class FakeGeocoder:
    def __init__(self, table: dict[str, GeoPoint]):
        self.table = table
        self.queries: list[str] = []

    def geocode(self, query: str) -> GeoPoint:
        self.queries.append(query)
        for needle, point in self.table.items():
            if needle.lower() in query.lower():
                return point
        raise GeocodingError(f"нет данных: {query}")


def point(lat: float, lon: float, name: str, precision: str = "exact") -> GeoPoint:
    return GeoPoint(latitude=lat, longitude=lon, display_name=name, provider="yandex", precision=precision)


# --- класс 1: проза из сниппета становилась жилым комплексом -----------------


def test_editorial_prose_never_becomes_a_project() -> None:
    """«Москвы. Рейтинг застройщиков Дубая. Адрес офиса» — реальный кандидат v5."""
    docs = [
        doc(
            "Клубные дома Москвы — рейтинг застройщиков",
            "https://example.ru/stati/klubnye-doma",
            "Мы строим клубный дом в центре Москвы. Рейтинг застройщиков Дубая. Адрес офиса, приходите.",
        ),
    ]
    assert extract_candidates(docs) == []


def test_prose_fragment_is_rejected_by_name_grammar() -> None:
    assert not looks_like_project_name("в центре Москвы. Рейтинг застройщиков Дубая. Адрес офиса")
    assert not looks_like_project_name("Рейтинг застройщиков Дубая")
    assert not looks_like_project_name("Саввинская набережная, 27")
    assert looks_like_project_name("Хамовники 12")
    assert looks_like_project_name("Клубный квартал Фрунзенский")


def test_article_and_listing_documents_produce_no_entity() -> None:
    docs = [
        doc(
            "ЖК Тургенев — обзор проекта",
            "https://www.cian.ru/stati/zhk-turgenev-obzor/",
            "Жилой комплекс Тургенев в Москве от застройщика",
        ),
        doc(
            "Купить квартиру 58 м² в ЖК Мод",
            "https://realty.yandex.ru/offer/1234567/",
            "Продаётся квартира в жилом комплексе Мод",
        ),
    ]
    assert extract_candidates(docs) == []


# --- класс 2: маркетинговый хвост в названии ---------------------------------


def test_marketing_tail_does_not_split_one_project_in_two() -> None:
    """v5 давал «Cult (Культ» и «Cult (Культ) - купить квартиру» одним документом."""
    docs = [
        doc(
            "ЖК Cult (Культ) - купить квартиру, цены от застройщика",
            "https://www.cian.ru/zhiloy-kompleks-cult-1234567/",
            "Квартиры в продаже от застройщика",
        )
    ]
    candidates = extract_candidates(docs)
    assert [item.canonical_name for item in candidates] == ["Cult (Культ)"]


def test_ascii_hyphen_terminates_the_title_name() -> None:
    docs = [
        doc(
            "ЖК Тургенев - купить квартиру, официальный сайт",
            "https://www.cian.ru/zhiloy-kompleks-turgenev-9991111/",
            "Квартиры от застройщика в Москве",
        )
    ]
    assert [item.canonical_name for item in extract_candidates(docs)] == ["Тургенев"]


# --- класс 3: дубли одного ЖК ------------------------------------------------


def test_latin_and_cyrillic_spellings_are_one_entity() -> None:
    docs = [
        doc(
            "Savvin River Residence — квартиры от застройщика",
            "https://www.cian.ru/zhiloy-kompleks-savvin-river-residence-4001001/",
            "Клубный дом на Саввинской набережной",
            rank=1,
        ),
        doc(
            "Саввин Ривер Резиденс - купить квартиру",
            "https://realty.yandex.ru/moskva/kupit/novostrojka/savvin-river-2002002/",
            "Квартиры в продаже",
            rank=2,
        ),
    ]
    entities = resolve_entities(extract_candidates(docs))
    assert len(entities) == 1
    assert name_similarity("Savvin River Residence", "Саввин Ривер Резиденс") >= 0.88


def test_external_id_merges_differing_titles() -> None:
    docs = [
        doc(
            "ДОМ XXII — квартиры от застройщика",
            "https://www.cian.ru/zhiloy-kompleks-dom-xxii-4463213/",
            "Строится на Погодинской улице",
            rank=1,
        ),
        doc(
            "Дом 22 в Хамовниках",
            "https://www.cian.ru/zhiloy-kompleks-dom-22-4463213/",
            "Элитный жилой комплекс",
            rank=2,
        ),
    ]
    entities = resolve_entities(extract_candidates(docs))
    assert len(entities) == 1
    assert canonical_key("ДОМ XXII") == canonical_key("Дом 22")


def test_geographic_duplicates_collapse_after_geocoding() -> None:
    rows = [
        {"name": "Savvin River Residence", "coordinates": {"latitude": 55.7305, "longitude": 37.5620}},
        {"name": "Саввин Ривер Резиденс", "coordinates": {"latitude": 55.7306, "longitude": 37.5621}},
        {"name": "Хамовники 12", "coordinates": {"latitude": 55.7350, "longitude": 37.5700}},
    ]
    merged = merge_geographic_duplicates(rows)
    assert len(merged) == 2
    assert "Саввин Ривер Резиденс" in merged[0]["merged_from"]


# --- класс 4: наследование subject-адреса и мнимые 0 км ----------------------


def test_subject_address_echo_is_not_inherited_by_a_candidate() -> None:
    """Главный дефект v5: сниппет повторяет адрес запроса, кандидат встаёт в 0 км."""
    subject_snippet = (
        "Новостройки рядом с адресом Москва, Саввинская набережная, 25 — подборка ЖК Мод"
    )
    # Регрессия на прежнее поведение: старый разбор действительно возвращал subject.
    assert LegacyService._address_hint(subject_snippet) == "Москва, Саввинская набережная, 25"

    entities = resolve_entities(
        extract_candidates(
            [
                doc(
                    "ЖК Мод — купить квартиру",
                    "https://www.cian.ru/zhiloy-kompleks-mod-7007007/",
                    subject_snippet,
                )
            ]
        )
    )
    assert len(entities) == 1

    resolver = ProjectGeoResolver(
        FakeGeocoder({"Саввинская набережная, 25": point(55.7333, 37.5638, "Москва, Саввинская набережная, 25")}),
        FakeSearch(),
        locality="Москва",
        subject_signature=address_signature(SUBJECT),
        locality_matches=LegacyService._locality_matches,
    )
    resolution = resolver.resolve(entities[0])
    assert resolution.status == UNRESOLVED
    assert resolution.point is None
    assert "эхо" in (resolution.reason or "")


def test_address_signature_ignores_street_type_and_city() -> None:
    assert address_signature("Москва, Саввинская наб., 25") == address_signature(
        "Саввинская набережная, д. 25"
    )
    assert address_signature("Москва, Саввинская набережная, 25") != address_signature(
        "Москва, Саввинская набережная, 27"
    )


def test_catalog_snippet_address_is_not_attributed_to_its_children() -> None:
    """Каталог перечисляет проекты; адрес из его сниппета ничей."""
    catalog = doc(
        "Новостройки (ЖК) в Хамовниках",
        "https://www.cian.ru/novostroyki-hamovniki/",
        'ЖК «Хамовники 12», ЖК «Мод», ЖК «Тургенев». Офис продаж: Москва, Саввинская набережная, 25',
    )
    candidates = extract_candidates([catalog])
    assert {item.canonical_name for item in candidates} == {"Хамовники 12", "Мод", "Тургенев"}
    assert all(item.address_attributable is False for item in candidates)

    resolver = ProjectGeoResolver(
        FakeGeocoder({"Саввинская набережная": point(55.7333, 37.5638, "Москва, Саввинская набережная, 25")}),
        FakeSearch(),
        locality="Москва",
        subject_signature=address_signature(SUBJECT),
        locality_matches=LegacyService._locality_matches,
    )
    for entity in resolve_entities(candidates):
        assert resolver.resolve(entity).status == UNRESOLVED


def test_city_centroid_precision_is_rejected() -> None:
    """Геокодер, не знающий бренд, возвращает центр Москвы — это не адрес проекта."""
    assert not precision_is_usable(point(55.7558, 37.6173, "Москва", precision="other"))
    assert not precision_is_usable(
        GeoPoint(55.7558, 37.6173, "Москва", provider="nominatim", precision="city")
    )
    assert precision_is_usable(point(55.7333, 37.5638, "Москва, Саввинская набережная, 27", "exact"))

    entity = resolve_entities(
        extract_candidates(
            [doc("ЖК Мод — квартиры", "https://www.cian.ru/zhiloy-kompleks-mod-7007007/", "Квартиры в продаже")]
        )
    )[0]
    resolver = ProjectGeoResolver(
        FakeGeocoder({"Москва": point(55.7558, 37.6173, "Москва", precision="other")}),
        FakeSearch(),
        locality="Москва",
        subject_signature=address_signature(SUBJECT),
        locality_matches=LegacyService._locality_matches,
    )
    assert resolver.resolve(entity).status == UNRESOLVED


def test_own_project_address_resolves_and_gives_a_real_distance() -> None:
    entity = resolve_entities(
        extract_candidates(
            [
                doc(
                    "Саввинская 27 — квартиры от застройщика",
                    "https://www.novostroy.ru/buildings/savvinskaya-27/",
                    "Делюкс-проект Level Group, Москва, Саввинская набережная, 27",
                )
            ]
        )
    )[0]
    resolver = ProjectGeoResolver(
        FakeGeocoder({"Саввинская набережная, 27": point(55.7352, 37.5651, "Москва, Саввинская набережная, 27")}),
        FakeSearch(),
        locality="Москва",
        subject_signature=address_signature(SUBJECT),
        locality_matches=LegacyService._locality_matches,
    )
    resolution = resolver.resolve(entity)
    assert resolution.status == RESOLVED
    assert resolution.address == "Москва, Саввинская набережная, 27"
    assert resolution.address_source == "project_page_snippet"


def test_extract_address_adds_locality_when_snippet_omits_it() -> None:
    assert extract_address("Проект расположен: Погодинская улица, вл. 22/3", "Москва") == (
        "Москва, Погодинская улица, вл. 22/3"
    )


def test_ordinal_prefix_stays_in_the_street_name() -> None:
    """«1-й переулок Тружеников» без порядкового номера — другой переулок."""
    assert extract_address("Клубный дом, Москва, 1-й переулок Тружеников, 12А", "Москва") == (
        "Москва, 1-й переулок Тружеников, 12А"
    )


def test_targeted_address_search_is_bounded() -> None:
    """Два вызова Search API на сущность без потолка растягивают запрос на сотни."""
    search = FakeSearch(default=[])
    resolver = ProjectGeoResolver(
        FakeGeocoder({}),
        search,
        locality="Москва",
        subject_signature=address_signature(SUBJECT),
        locality_matches=LegacyService._locality_matches,
        search_budget=2,
    )
    entities = resolve_entities(
        extract_candidates(
            [
                doc(
                    "Новостройки (ЖК) в Хамовниках",
                    "https://www.cian.ru/novostroyki-hamovniki/",
                    'ЖК «Мод», ЖК «Тургенев», ЖК «Cult», ЖК «Лаврушинский», ЖК «Титул»',
                )
            ]
        )
    )
    assert len(entities) >= 5
    for entity in entities:
        assert resolver.resolve(entity).status == UNRESOLVED
    # Потолок выражен в бюджете, а не в числе: форм запроса на сущность три.
    assert len(search.queries) <= 2 * 3, search.queries


# --- класс 5: цена, не принадлежащая проекту ---------------------------------


def test_price_from_a_district_catalog_is_rejected() -> None:
    entity = resolve_entities(
        extract_candidates(
            [
                doc(
                    "Хамовники 12 — квартиры от застройщика",
                    "https://www.cian.ru/zhiloy-kompleks-hamovniki-12-3186893/",
                    "Клубный дом COLDY",
                )
            ]
        )
    )[0]
    catalog = doc(
        "Новостройки Хамовников — цены",
        "https://www.cian.ru/novostroyki-hamovniki/",
        "Хамовники 12 от 3 306 021 ₽/м², Мод от 900 000 ₽/м², Тургенев от 800 000 ₽/м²",
    )
    enricher = VerifiedPriceEnricher(FakeSearch(default=[catalog]), today=date(2026, 8, 7))
    result = enricher.collect(entity, "Москва")
    assert result["price"]["available"] is False
    assert result["price"]["verified"] is False
    assert result["rejected_observations"][0]["reason"] == "entity_match_not_proven"


def test_price_from_the_matching_project_page_is_accepted_with_provenance() -> None:
    entity = resolve_entities(
        extract_candidates(
            [
                doc(
                    "Хамовники 12 — квартиры от застройщика",
                    "https://www.cian.ru/zhiloy-kompleks-hamovniki-12-3186893/",
                    "Клубный дом COLDY",
                )
            ]
        )
    )[0]
    project_page = doc(
        "Хамовники 12 — купить квартиру",
        "https://realty.yandex.ru/moskva/kupit/novostrojka/hamovniki-12-3186893/",
        "Цена 3 306 021 ₽/м². В продаже 3 квартиры. Обновлено 28 февраля 2026",
    )
    enricher = VerifiedPriceEnricher(FakeSearch(default=[project_page]), today=date(2026, 8, 7))
    result = enricher.collect(entity, "Москва")
    price = result["price"]
    assert price["verified"] is True
    assert price["price_per_sqm"] == 3_306_021
    assert price["sample_count"] >= 1
    assert price["quality"] in {"high", "medium"}
    assert price["observed_at"] == "2026-02-28"
    assert price["retrieved_at"] == "2026-08-07"
    assert result["inventory"]["units"] == 3
    assert result["inventory"]["source"] == "Яндекс Недвижимость"


def test_inventory_is_unknown_rather_than_invented() -> None:
    entity = resolve_entities(
        extract_candidates(
            [doc("Мод — квартиры", "https://www.cian.ru/zhiloy-kompleks-mod-7007007/", "Квартиры в продаже")]
        )
    )[0]
    enricher = VerifiedPriceEnricher(FakeSearch(default=[]), today=date(2026, 8, 7))
    inventory = enricher.collect(entity, "Москва")["inventory"]
    assert inventory == {
        "units": None,
        "source": None,
        "observed_at": None,
        "quality": "unknown",
        "note": "Экспозиция не извлекается достоверно из поискового индекса",
    }


def test_secondary_market_page_never_prices_a_primary_project() -> None:
    entity = resolve_entities(
        extract_candidates(
            [doc("Мод — квартиры", "https://www.cian.ru/zhiloy-kompleks-mod-7007007/", "Квартиры в продаже")]
        )
    )[0]
    resale = doc(
        "Мод — купить квартиру",
        "https://www.cian.ru/zhiloy-kompleks-mod-7007007/",
        "Вторичный рынок, 700 000 ₽/м²",
    )
    enricher = VerifiedPriceEnricher(FakeSearch(default=[resale]), today=date(2026, 8, 7))
    result = enricher.collect(entity, "Москва")
    assert result["price"]["available"] is False
    assert any(item["reason"] == "secondary_market" for item in result["rejected_observations"])


def test_million_plus_price_is_not_silently_divided_by_ten() -> None:
    """Прежний шаблон читал «3 306 021 ₽/м²» как 306 021 — и это проходило проверку диапазона."""
    values = VerifiedPriceEnricher._prices("Цена 3 306 021 ₽/м², от 2 256 990 ₽/м²")
    assert values == [3_306_021, 2_256_990]
    assert VerifiedPriceEnricher._prices("598 500 ₽/м²") == [598_500]
    assert VerifiedPriceEnricher._prices("598,5 тыс. ₽/м²") == [598_500]


# --- класс 6: рекомендация по недоказанным наблюдениям ------------------------


def test_recommendation_ignores_unverified_and_geo_unresolved_rows() -> None:
    projects = [
        {
            "name": "верный",
            "within_radius": True,
            "geo_status": "resolved",
            "price_verified": True,
            "distance_km": 0.5,
            "confirmed": False,
            "market_source_count": 2,
            "market_price": {"available": True, "price_per_sqm": 1_000_000},
        },
        {
            "name": "цена без доказательства",
            "within_radius": True,
            "geo_status": "resolved",
            "price_verified": False,
            "distance_km": 0.4,
            "confirmed": False,
            "market_source_count": 1,
            "market_price": {"available": True, "price_per_sqm": 4_000_000},
        },
        {
            "name": "география не подтверждена",
            "within_radius": True,
            "geo_status": "geo_unresolved",
            "price_verified": True,
            "distance_km": 0.0,
            "confirmed": False,
            "market_source_count": 1,
            "market_price": {"available": True, "price_per_sqm": 4_500_000},
        },
    ]
    result = market_recommendation(projects)
    assert result is not None
    assert result["projects"] == ["верный"]
    assert result["price_per_sqm"] == 1_000_000


# --- класс 7: чужая география ------------------------------------------------


def test_khabarovsk_project_is_not_confirmed_for_moscow() -> None:
    card = {"title": "СВОЙ", "snippet": "СВОЙ, Хабаровск, Хабаровский край"}
    assert not LegacyService._official_card_matches("СВОЙ", None, card, locality="Москва")


def test_other_city_name_is_rejected_by_name_grammar() -> None:
    assert not looks_like_project_name("Новостройки Хабаровска")
    assert not looks_like_project_name("СВОЙ Хабаровск")


def test_grodnenskaya_control_keeps_khabarovsk_out_of_the_moscow_set() -> None:
    """Контроль 3: «СВОЙ» из Хабаровска не должен становиться московским аналогом."""
    docs = [
        doc(
            "ЖК СВОЙ — купить квартиру",
            "https://www.cian.ru/zhiloy-kompleks-svoy-8008008/",
            "Жилой комплекс СВОЙ, Хабаровск, Хабаровский край. Квартиры от застройщика",
        )
    ]
    entities = resolve_entities(extract_candidates(docs))
    resolver = ProjectGeoResolver(
        FakeGeocoder({"Хабаровск": GeoPoint(48.4802, 135.0719, "Хабаровск, Хабаровский край", "yandex", "exact")}),
        FakeSearch(),
        locality="Москва",
        subject_signature=address_signature("Москва, Гродненская улица, 18"),
        locality_matches=LegacyService._locality_matches,
    )
    for entity in entities:
        assert resolver.resolve(entity).status == UNRESOLVED


# --- контроль 2: Мишина, 46 ---------------------------------------------------


def test_mishina_control_keeps_phases_apart_and_drops_the_office_building() -> None:
    """«Петровский парк II» — не то же самое, что «Петровский парк», а БЦ — не аналог."""
    docs = [
        doc(
            "Петровский парк II — квартиры от застройщика",
            "https://www.cian.ru/zhiloy-kompleks-petrovskiy-park-ii-5005005/",
            "Строящийся жилой комплекс, Москва, улица Мишина, 42",
            rank=1,
        ),
        doc(
            "Петровский парк — купить квартиру",
            "https://www.cian.ru/zhiloy-kompleks-petrovskiy-park-4004004/",
            "Москва, Петровско-Разумовская аллея, 2. Квартиры от застройщика",
            rank=2,
        ),
        doc(
            "Бизнес-центр Савёловский Сити — офисы",
            "https://example.ru/proekty/savelovsky-city",
            "Офисный комплекс рядом с улицей Мишина",
            rank=3,
        ),
    ]
    entities = resolve_entities(extract_candidates(docs))
    names = {entity.canonical_name for entity in entities}
    assert names == {"Петровский парк II", "Петровский парк"}
    assert phase_apart("Петровский парк", "Петровский парк II")


def phase_apart(left: str, right: str) -> bool:
    from market_search.normalize import phase_number

    return phase_number(left) != phase_number(right)


# --- сквозной прогон конвейера ------------------------------------------------


@pytest.fixture()
def service(tmp_path: Path) -> ServiceV6:
    return ServiceV6(tmp_path)


def test_pipeline_keeps_valid_analogues_and_quarantines_the_rest(service: ServiceV6, monkeypatch) -> None:
    discovery = [
        doc(
            "Хамовники 12 — квартиры в клубном доме",
            "https://www.cian.ru/zhiloy-kompleks-hamovniki-12-3186893/",
            "Клубный дом COLDY, Москва, 1-й переулок Тружеников, 12А. Цена 3 306 021 ₽/м²",
            rank=1,
        ),
        doc(
            "Саввинская 27 — квартиры от застройщика",
            "https://www.novostroy.ru/buildings/savvinskaya-27/",
            "Level Group, Москва, Саввинская набережная, 27. Цена 3 200 000 ₽/м²",
            rank=2,
        ),
        doc(
            "Клубные дома Москвы — рейтинг застройщиков",
            "https://example.ru/stati/klubnye-doma",
            "Клубный дом в центре Москвы. Рейтинг застройщиков Дубая. Адрес офиса.",
            rank=3,
        ),
        doc(
            "ЖК Мод — купить квартиру",
            "https://www.cian.ru/zhiloy-kompleks-mod-7007007/",
            "Новостройки рядом с адресом Москва, Саввинская набережная, 25",
            rank=4,
        ),
    ]
    search = FakeSearch(default=discovery)
    monkeypatch.setattr(service, "search", search)
    monkeypatch.setattr(service.verified_prices, "search", search)
    monkeypatch.setattr(
        service,
        "geocoder",
        FakeGeocoder(
            {
                "Тружеников, 12А": point(55.7360, 37.5730, "Москва, 1-й переулок Тружеников, 12А"),
                "Саввинская набережная, 27": point(55.7352, 37.5651, "Москва, Саввинская набережная, 27"),
                "Саввинская набережная, 25": point(55.7333, 37.5638, "Москва, Саввинская набережная, 25"),
            }
        ),
    )

    result = service.discover(
        address=SUBJECT, latitude=55.7333, longitude=37.5638, radius_km=3.0, limit=10
    )

    names = [row["name"] for row in result["projects"]]
    assert "Хамовники 12" in names
    assert "Саввинская 27" in names
    assert not any("Рейтинг" in name for name in names)
    assert "Мод" not in names, "проект без собственного адреса не должен вставать в 0 км"
    assert all(row["distance_km"] > 0 for row in result["projects"])
    assert result["source"]["mode"] == "forensic_entity_pipeline_v6"
    assert result["quarantine_count"] >= 1
    assert any(item["status"] == "geo_unresolved" for item in result["quarantine"])
    assert result["diagnostics"]["documents_by_kind"].get("article") == 1


def test_pipeline_never_reads_the_golden_fixture(service: ServiceV6, monkeypatch) -> None:
    search = FakeSearch(default=[])
    monkeypatch.setattr(service, "search", search)
    monkeypatch.setattr(service.verified_prices, "search", search)
    monkeypatch.setattr(service, "geocoder", FakeGeocoder({}))
    result = service.discover(
        address=SUBJECT, latitude=55.7333, longitude=37.5638, radius_km=3.0, limit=10
    )
    assert result["projects"] == []
    assert result["price_summary"] is None
    assert "Хамовники" not in repr(result)


def test_ui_renders_the_v6_price_shape_instead_of_silently_showing_nothing() -> None:
    """Панель читала price.asking / price.official — в v6 их нет."""
    from market_search.ui_v6 import install as install_ui

    class FakeCore:
        PAGE = (
            "<html><head></head><body>"
            '<input id="apartment_price_th" type="number" value="500">'
            "<button class=\"tab\" data-tab=\"report\" onclick=\"openTab('report',this)\">Отчёт</button>"
            '<div id="report" class="panel"></div>'
            "</body></html>"
        )

    core = FakeCore()
    install_ui(core)
    page = core.PAGE
    assert "price.asking" not in page
    assert "officialPrice" not in page
    assert "Адрес проекта не разрешён" in page
    assert "Экспозиция: неизвестна" in page
    assert "в карантине: " in page
    assert "Не подтверждён — в расчёт цены не идёт" not in page


def _acceptance_module():
    import importlib.util

    path = Path(__file__).resolve().parent.parent / "market-preview-acceptance.py"
    spec = importlib.util.spec_from_file_location("market_preview_acceptance", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_acceptance_contract_matches_what_the_service_actually_returns(
    service: ServiceV6, monkeypatch
) -> None:
    """Приёмка и движок не должны разъезжаться по имени контракта.

    Прежде строка режима жила в двух местах, и обновление одного из них
    превращало исправный стенд в «старый market API»."""
    acceptance = _acceptance_module()
    search = FakeSearch(default=[])
    monkeypatch.setattr(service, "search", search)
    monkeypatch.setattr(service.verified_prices, "search", search)
    monkeypatch.setattr(service, "geocoder", FakeGeocoder({}))
    result = service.discover(
        address=SUBJECT, latitude=55.7333, longitude=37.5638, radius_km=3.0, limit=10
    )
    assert result["source"]["mode"] == acceptance.EXPECTED_MODE
    ok, error = acceptance.validate_contract(result)
    assert ok, error
    assert acceptance.validate_data_quality(result["projects"]) == []
    assert "Гродненская 18" in acceptance.GOLDEN


def test_acceptance_data_quality_catches_the_live_preview_garbage() -> None:
    acceptance = _acceptance_module()
    problems = acceptance.validate_data_quality(
        [
            {
                "name": "Сидней Сити (Sidney City)",
                "distance_km": 0.0,
                "geo_status": "resolved",
                "address": None,
                "market_price": {"available": True, "verified": False, "price_per_sqm": 900_000},
                "inventory": {"units": 12, "source": None},
            },
            {"name": "Savvin River Residence", "distance_km": 0.4, "address": "Москва, Саввинская наб., 15"},
            {"name": "саввин ривер резиденс", "distance_km": 0.4, "address": "Москва, Саввинская наб., 15"},
        ]
    )
    joined = " | ".join(problems)
    assert "0 км" in joined
    assert "нет собственного адреса" in joined
    assert "без доказанной привязки" in joined
    assert "экспозиция без источника" in joined
    assert "дубль" in joined


def test_document_classification_covers_the_live_aggregators() -> None:
    cases = {
        "https://www.cian.ru/zhiloy-kompleks-dom-xxii-4463213/": (documents.PROJECT_PAGE, "cian:4463213"),
        "https://zhk-frunzenskaya-naberezhnaya-i.cian.ru/": (
            documents.PROJECT_PAGE,
            "cian:zhk:frunzenskaya-naberezhnaya",
        ),
        "https://www.cian.ru/novostroyki-hamovniki/": (documents.CATALOG, None),
        "https://www.cian.ru/stati/rejting-zastrojshchikov/": (documents.ARTICLE, None),
        "https://realty.yandex.ru/moskva/kupit/novostrojka/hamovniki-12-3186893/": (
            documents.PROJECT_PAGE,
            "yandex:3186893",
        ),
        "https://realty.yandex.ru/offer/1234567/": (documents.LISTING, None),
        "https://www.novostroy.ru/buildings/savvinskaya-27/": (
            documents.PROJECT_PAGE,
            "novostroy:savvinskaya-27",
        ),
        "https://xn--80az8a.xn--d1aqf.xn--p1ai/lk/na-dom/2079406": (documents.OFFICIAL_CARD, "domrf:2079406"),
    }
    for url, (kind, external) in cases.items():
        ref = documents.classify_document(url)
        assert ref.kind == kind, url
        assert ref.external_id == external, url


# --- класс 8: находки живого стенда 08.08 (2 проекта, 0 цен) ------------------


def test_duplicated_parenthetical_no_longer_breaks_self_match() -> None:
    """«Клубный дом «Саввинская 17» (Саввинская 17)» не узнавал собственную карточку."""
    from market_search.normalize import drop_duplicate_parenthetical, labels_match, search_name

    raw = "Клубный дом «Саввинская 17» (Саввинская 17)"
    assert drop_duplicate_parenthetical(raw) == "Клубный дом «Саввинская 17»"
    assert canonical_key(raw) == canonical_key("Саввинская 17")
    assert labels_match("Клубный дом «Саввинская 17»", [raw])
    # Двуязычная вывеска — не задвоение, её трогать нельзя.
    assert drop_duplicate_parenthetical("Сидней Сити (Sidney City)") == "Сидней Сити (Sidney City)"
    # В запрос уходит имя без кавычек: точная фраза с «» не находит ничего.
    assert search_name(raw) == "Клубный дом Саввинская 17"


def test_project_page_price_survives_a_duplicated_entity_label() -> None:
    entity = resolve_entities(
        extract_candidates(
            [
                doc(
                    "Клубный дом «Саввинская 17» (Саввинская 17) — купить квартиру",
                    "https://realty.yandex.ru/moskva/kupit/novostrojka/savvinskaya-17-1234567/",
                    "Квартиры от застройщика",
                )
            ]
        )
    )[0]
    page = doc(
        "Саввинская 17 — цены и планировки",
        "https://www.cian.ru/zhiloy-kompleks-savvinskaya-17-7654321/",
        "от 2 256 990 ₽ за м². В продаже 22 квартиры",
    )
    result = VerifiedPriceEnricher(FakeSearch(default=[page]), today=date(2026, 8, 8)).collect(
        entity, "Москва"
    )
    assert result["price"]["verified"] is True
    assert result["price"]["price_per_sqm"] == 2_256_990
    assert result["inventory"]["units"] == 22


def test_price_is_read_in_every_common_russian_form() -> None:
    """Раньше из пяти ходовых форм читалась одна — «₽/м²»."""
    cases = {
        "3 306 021 ₽/м²": 3_306_021,
        "от 2 256 990 ₽ за м²": 2_256_990,
        "1 200 000 руб. за кв. м": 1_200_000,
        "от 598,5 тыс. ₽ за м²": 598_500,
        "цена за м²: 900 000 ₽": 900_000,
    }
    for text, expected in cases.items():
        assert VerifiedPriceEnricher._prices(text) == [expected], text
    # Цена лота и площадь рядом — не цена метра.
    assert VerifiedPriceEnricher._prices("120 м² за 50 000 000 ₽") == []
    assert VerifiedPriceEnricher._prices("5 000 000 ₽ за квартиру") == []


def test_catalog_list_yields_each_project_separately() -> None:
    """Каталог перечисляет проекты списком; кавычек в сниппете обычно нет."""
    catalog = doc(
        "Новостройки (ЖК) в Хамовниках — купить квартиру",
        "https://www.cian.ru/novostroyki-hamovniki/",
        "ЖК Хамовники 12 · ДОМ XXII · Клубный квартал Фрунзенский · Саввинская 27",
    )
    names = {item.canonical_name for item in extract_candidates([catalog])}
    assert {"Хамовники 12", "ДОМ XXII", "Саввинская 27"} <= names
    assert any("Фрунзенский" in name for name in names)
    # Ни одно имя не склеило соседей списка.
    assert not any("·" in name for name in names)
    assert all(
        item.address_attributable is False for item in extract_candidates([catalog])
    ), "каталожный кандидат адреса не наследует"


def test_catalog_advertising_line_yields_nothing() -> None:
    noise = doc(
        "Новостройки Москвы",
        "https://www.cian.ru/novostroyki-moskva/",
        "Рейтинг застройщиков · Ипотека от 5% · Скидки до 20% · Консультация бесплатно",
    )
    assert extract_candidates([noise]) == []


def test_ui_shows_why_candidates_were_dropped() -> None:
    from market_search.ui_v6 import install as install_ui

    class FakeCore:
        PAGE = (
            "<html><head></head><body>"
            '<input id="apartment_price_th" type="number" value="500">'
            "<button class=\"tab\" data-tab=\"report\" onclick=\"openTab('report',this)\">Отчёт</button>"
            '<div id="report" class="panel"></div>'
            "</body></html>"
        )

    core = FakeCore()
    install_ui(core)
    assert "mdQuarantine(payload)" in core.PAGE
    assert "адрес проекта не подтверждён" in core.PAGE
    assert "найдены, но в расчёт не взяты" in core.PAGE


# --- класс 9: адрес не находился ни у кого (стенд 08.08, 21 в карантине) ------


def test_developer_site_is_accepted_as_address_evidence() -> None:
    """Официальный сайт застройщика — лучший источник адреса, а его отвергали."""
    entities = resolve_entities(
        extract_candidates(
            [
                doc(
                    "Новостройки (ЖК) в Хамовниках",
                    "https://www.cian.ru/novostroyki-hamovniki/",
                    "Дом Дау · West Garden · Хедлайнер",
                )
            ]
        )
    )
    entity = next(item for item in entities if item.canonical_name == "Дом Дау")
    developer_page = doc(
        "Дом Дау — официальный сайт застройщика",
        "https://domdau.example/projects/dom-dau/",
        "Небоскрёб в Москва-Сити. Адрес: Москва, Пресненская набережная, 14",
    )
    resolver = ProjectGeoResolver(
        FakeGeocoder({"Пресненская набережная, 14": point(55.7473, 37.5378, "Москва, Пресненская набережная, 14")}),
        FakeSearch(default=[developer_page]),
        locality="Москва",
        subject_signature=address_signature(SUBJECT),
        locality_matches=LegacyService._locality_matches,
    )
    resolution = resolver.resolve(entity)
    assert resolution.status == RESOLVED
    assert resolution.address == "Москва, Пресненская набережная, 14"
    assert resolution.address_source == "targeted_address_search"


def test_catalog_and_article_still_never_give_an_address() -> None:
    entity = resolve_entities(
        extract_candidates(
            [doc("Новостройки Хамовников", "https://www.cian.ru/novostroyki-hamovniki/", "Дом Дау · Мод")]
        )
    )[0]
    wrong = [
        doc(
            "Дом Дау — обзор проекта",
            "https://example.ru/stati/dom-dau/",
            "Адрес: Москва, Тверская улица, 1",
        ),
        doc(
            "Новостройки Пресни",
            "https://www.cian.ru/novostroyki-presnya/",
            "Дом Дау, Москва, Пресненская набережная, 14",
        ),
    ]
    resolver = ProjectGeoResolver(
        FakeGeocoder({"Тверская": point(55.7601, 37.6100, "Москва, Тверская улица, 1")}),
        FakeSearch(default=wrong),
        locality="Москва",
        subject_signature=address_signature(SUBJECT),
        locality_matches=LegacyService._locality_matches,
    )
    assert resolver.resolve(entity).status == UNRESOLVED


def test_geocoder_resolves_a_known_brand_only_at_house_precision() -> None:
    """Бренд, который геокодер знает домом, — законная последняя попытка."""
    entity = resolve_entities(
        extract_candidates(
            [doc("Новостройки Хамовников", "https://www.cian.ru/novostroyki-hamovniki/", "West Garden · Мод")]
        )
    )[0]

    exact = ProjectGeoResolver(
        FakeGeocoder({"West Garden": point(55.7015, 37.5158, "Москва, улица Лобачевского, 122", "exact")}),
        FakeSearch(default=[]),
        locality="Москва",
        subject_signature=address_signature(SUBJECT),
        locality_matches=LegacyService._locality_matches,
    ).resolve(entity)
    assert exact.status == RESOLVED
    assert exact.address_source == "geocoder_brand_exact"

    coarse = ProjectGeoResolver(
        FakeGeocoder({"West Garden": point(55.7558, 37.6173, "Москва", "street")}),
        FakeSearch(default=[]),
        locality="Москва",
        subject_signature=address_signature(SUBJECT),
        locality_matches=LegacyService._locality_matches,
    ).resolve(entity)
    assert coarse.status == UNRESOLVED, "уровень улицы — не адрес проекта"


def test_catalog_list_junk_is_dropped_before_it_eats_the_budget() -> None:
    """«2 корпуса», «Донстрой», «Мичуринский проспект» — из живого карантина."""
    catalog = doc(
        "Новостройки Москвы",
        "https://www.cian.ru/novostroyki-moskva/",
        "Дом Дау · 2 корпуса · Донстрой · Мичуринский проспект · Ход строительства · West Garden",
    )
    names = {item.canonical_name for item in extract_candidates([catalog])}
    assert "Дом Дау" in names
    assert "West Garden" in names
    for junk in ("2 корпуса", "Донстрой", "Мичуринский проспект", "Ход строительства"):
        assert junk not in names, junk


def test_project_pages_get_the_parsing_budget_before_catalog_leads() -> None:
    """Наводка из списка не должна съедать целевые поиски у настоящей карточки."""
    docs = [
        doc(
            "Новостройки Хамовников",
            "https://www.cian.ru/novostroyki-hamovniki/",
            "Альфа · Бета · Гамма · Дельта",
            rank=1,
        ),
        doc(
            "Хамовники 12 — квартиры",
            "https://realty.yandex.ru/moskva/kupit/novostrojka/hamovniki-12-3186893/",
            "Клубный дом",
            rank=9,
        ),
    ]
    entities = resolve_entities(extract_candidates(docs))
    ordered = sorted(
        entities,
        key=lambda item: (not item.project_pages, -item.extraction_confidence, item.search_rank),
    )
    assert ordered[0].canonical_name == "Хамовники 12"


def test_developer_own_page_is_a_price_source_when_the_entity_matches() -> None:
    """Собственная цена застройщика — самая авторитетная, её нельзя игнорировать."""
    entity = resolve_entities(
        extract_candidates(
            [doc("Новостройки Москвы", "https://www.cian.ru/novostroyki-moskva/", "Дом Дау · Мод")]
        )
    )[0]
    own = doc(
        "Дом Дау — официальный сайт застройщика",
        "https://domdau.example/projects/dom-dau/",
        "Квартиры от 1 250 000 ₽ за м². Москва, Пресненская набережная, 14",
    )
    result = VerifiedPriceEnricher(FakeSearch(default=[own]), today=date(2026, 8, 8)).collect(
        entity, "Москва"
    )
    assert result["price"]["verified"] is True
    assert result["price"]["price_per_sqm"] == 1_250_000

    # Чужой проект на том же сайте цену не отдаёт.
    other = resolve_entities(
        extract_candidates(
            [doc("Новостройки Москвы", "https://www.cian.ru/novostroyki-moskva/", "Мод · Тургенев")]
        )
    )[0]
    rejected = VerifiedPriceEnricher(FakeSearch(default=[own]), today=date(2026, 8, 8)).collect(
        other, "Москва"
    )
    assert rejected["price"]["available"] is False


# --- класс 10: стенд 08.08 после починки адресов ------------------------------


def test_official_eiszhs_card_supplies_the_address() -> None:
    """Карточка ЕИСЖС несёт строительный адрес — надёжнее любого агрегатора."""
    entity = next(
        item
        for item in resolve_entities(
            extract_candidates(
                [doc("Новостройки Хамовников", "https://www.cian.ru/novostroyki-hamovniki/", "Хамовники 12 · Мод")]
            )
        )
        if item.canonical_name == "Хамовники 12"
    )
    card = doc(
        "Жилой комплекс Хамовники 12 — ЕИСЖС",
        "https://xn--80az8a.xn--d1aqf.xn--p1ai/lk/na-dom/2079406",
        "Москва, 1-й переулок Тружеников, 12А. Застройщик COLDY",
    )
    resolver = ProjectGeoResolver(
        FakeGeocoder({"Тружеников, 12А": point(55.7360, 37.5730, "Москва, 1-й переулок Тружеников, 12А")}),
        FakeSearch(responses={"наш.дом.рф": [card]}, default=[]),
        locality="Москва",
        subject_signature=address_signature(SUBJECT),
        locality_matches=LegacyService._locality_matches,
    )
    resolution = resolver.resolve(entity)
    assert resolution.status == RESOLVED
    assert resolution.address_source == "official_eiszhs_card"
    assert resolution.address == "Москва, 1-й переулок Тружеников, 12А"


def test_official_card_of_another_project_is_not_borrowed() -> None:
    entity = next(
        item
        for item in resolve_entities(
            extract_candidates(
                [doc("Новостройки Хамовников", "https://www.cian.ru/novostroyki-hamovniki/", "Хамовники 12 · Мод")]
            )
        )
        if item.canonical_name == "Хамовники 12"
    )
    foreign = doc(
        "Жилой комплекс Прайм Парк — ЕИСЖС",
        "https://xn--80az8a.xn--d1aqf.xn--p1ai/lk/na-dom/1111111",
        "Москва, Ленинградский проспект, 37",
    )
    resolver = ProjectGeoResolver(
        FakeGeocoder({"Ленинградский": point(55.7900, 37.5300, "Москва, Ленинградский проспект, 37")}),
        FakeSearch(responses={"наш.дом.рф": [foreign]}, default=[]),
        locality="Москва",
        subject_signature=address_signature(SUBJECT),
        locality_matches=LegacyService._locality_matches,
    )
    assert resolver.resolve(entity).status == UNRESOLVED


def test_street_and_company_names_never_reach_the_geocoder() -> None:
    """«Мичуринский проспект», «Донстрой», «УК АСК ГРУПП» получали координаты."""
    catalog = doc(
        "Новостройки Москвы",
        "https://www.cian.ru/novostroyki-moskva/",
        "ЖК Мичуринский проспект · ЖК Донстрой · УК АСК ГРУПП · 2 корпуса · ЖК Дом Дау",
    )
    names = {item.canonical_name for item in extract_candidates([catalog])}
    assert "Дом Дау" in names
    for junk in ("Мичуринский проспект", "Донстрой", "УК АСК ГРУПП", "2 корпуса"):
        assert junk not in names, junk


def test_price_queries_are_not_quoted() -> None:
    """Точная фраза внутри site: почти всегда даёт пустую выдачу."""
    entity = resolve_entities(
        extract_candidates(
            [
                doc(
                    "Клубный дом «Саввинская 17» — купить квартиру",
                    "https://realty.yandex.ru/moskva/kupit/novostrojka/savvinskaya-17-1234567/",
                    "Квартиры от застройщика",
                )
            ]
        )
    )[0]
    search = FakeSearch(default=[])
    VerifiedPriceEnricher(search, today=date(2026, 8, 8)).collect(entity, "Москва")
    assert search.queries, "запросы должны быть"
    assert not any('"' in query for query in search.queries), search.queries
    assert any("цена за м²" in query for query in search.queries), search.queries


# --- класс 11: сопоставимость, а не только география --------------------------


def test_class_alone_would_not_have_excluded_the_skyscraper() -> None:
    """Дом Дау тоже элитный — класс его не отсекает, отсекает пара с районом."""
    from market_search.segments import detect_district, detect_segment, districts_match

    assert detect_segment("Дом Дау — элитный небоскрёб в Москва-Сити") == "элитный"
    assert detect_segment("Хамовники 12 — элитный клубный дом") == "элитный"
    assert not districts_match(
        detect_district("Москва, район Хамовники, Саввинская набережная, 25"),
        detect_district("Москва, Пресненский район, 1-й Красногвардейский проезд, 14"),
    )


def test_deluxe_and_elite_are_one_tier() -> None:
    """Саввинская 27 — делюкс, Хамовники 12 — элитный; это прямые конкуренты."""
    from market_search.segments import detect_segment

    assert detect_segment("Делюкс-проект Level Group") == detect_segment("Элитный клубный дом")


def test_marketing_adjective_alone_is_not_a_class() -> None:
    from market_search.segments import detect_segment

    assert detect_segment("Премиальный жилой комплекс у реки") is None


def test_pipeline_drops_a_neighbouring_district_project(tmp_path: Path, monkeypatch) -> None:
    service = ServiceV6(tmp_path)
    discovery = [
        doc(
            "Хамовники 12 — квартиры",
            "https://realty.yandex.ru/moskva/kupit/novostrojka/hamovniki-12-3186893/",
            "Элитный клубный дом. Москва, 1-й переулок Тружеников, 12А. 3 306 021 ₽ за м²",
            rank=1,
        ),
        doc(
            "Дом Дау — квартиры",
            "https://realty.yandex.ru/moskva/kupit/novostrojka/dom-dau-7777777/",
            "Элитный небоскрёб. Москва, 1-й Красногвардейский проезд, 14. 1 500 000 ₽ за м²",
            rank=2,
        ),
    ]
    search = FakeSearch(default=discovery)
    monkeypatch.setattr(service, "search", search)
    monkeypatch.setattr(service.verified_prices, "search", search)
    monkeypatch.setattr(
        service,
        "geocoder",
        FakeGeocoder(
            {
                "Саввинская набережная, 25": point(
                    55.7333, 37.5638, "Саввинская набережная, 25, район Хамовники, Москва"
                ),
                "Тружеников, 12А": point(
                    55.7360, 37.5730, "1-й переулок Тружеников, 12А, район Хамовники, Москва"
                ),
                "Красногвардейский проезд, 14": point(
                    55.7480, 37.5390, "1-й Красногвардейский проезд, 14, Пресненский район, Москва"
                ),
            }
        ),
    )
    result = service.discover(address=SUBJECT, latitude=None, longitude=None, radius_km=3.0, limit=10)

    names = [row["name"] for row in result["projects"]]
    assert "Хамовники 12" in names
    assert "Дом Дау" not in names, "Пресненский район — не аналог Хамовников"
    dropped = {item["name"]: item for item in result["quarantine"]}
    assert dropped["Дом Дау"]["status"] == "district_mismatch"
    assert "Пресненский" in dropped["Дом Дау"]["reason"]
    assert result["query"]["subject_district"] == "Хамовники"


def test_official_average_is_shown_but_never_sets_the_benchmark() -> None:
    """Средняя ЕИСЖС отражает сделки и отстаёт: показывать можно, считать нельзя."""
    rows = [
        {
            "name": "рынок",
            "within_radius": True,
            "geo_status": "resolved",
            "price_verified": True,
            "distance_km": 0.5,
            "confirmed": True,
            "market_source_count": 1,
            "market_price": {
                "available": True,
                "basis": "verified_project_page_asking",
                "price_per_sqm": 3_000_000,
            },
        },
        {
            "name": "официальная средняя",
            "within_radius": True,
            "geo_status": "resolved",
            "price_verified": True,
            "distance_km": 0.4,
            "confirmed": True,
            "market_source_count": 1,
            "market_price": {
                "available": True,
                "basis": "official_domrf_fallback",
                "price_per_sqm": 919_717,
            },
        },
    ]
    result = market_recommendation(rows)
    assert result is not None
    assert result["projects"] == ["рынок"]
    assert result["price_per_sqm"] == 3_000_000


def test_class_filter_stays_off_when_almost_nothing_has_a_class(tmp_path: Path) -> None:
    """Отбор по одному наблюдению выкосил бы выдачу целиком."""
    service = ServiceV6(tmp_path)
    rows = [
        {"name": "с классом", "segment": "элитный", "distance_km": 0.5, "coordinates": {}},
        {"name": "без класса", "segment": None, "distance_km": 0.6, "coordinates": {}},
    ]
    quarantine: list[dict] = []
    kept, info = service._apply_comparability(
        rows, quarantine, subject_district="Хамовники", requested=None
    )
    assert info["class_filter_active"] is False
    assert len(kept) == 2
    assert quarantine == []


def test_class_is_looked_up_for_projects_the_catalog_did_not_label() -> None:
    """«Японский дом» в 630 метрах вылетал со статусом «класс не определён»."""
    from market_search.segments import SegmentResolver

    entity = next(
        item
        for item in resolve_entities(
            extract_candidates(
                [doc("Новостройки Хамовников", "https://www.cian.ru/novostroyki-hamovniki/", "Японский дом · Мод")]
            )
        )
        if item.canonical_name == "Японский дом"
    )
    assert entity.segment is None, "каталог класс не назвал"

    found = doc(
        "Японский дом — квартиры от застройщика",
        "https://www.cian.ru/zhiloy-kompleks-yaponskiy-dom-5150001/",
        "Элитный клубный дом в Хамовниках",
    )
    assert SegmentResolver(FakeSearch(default=[found]), locality="Москва").resolve(entity) == "элитный"

    # Класс соседа своим не становится.
    foreign = doc(
        "Прайм Парк — премиум-класс",
        "https://www.cian.ru/zhiloy-kompleks-prime-park-9990001/",
        "Премиум-класс на Ленинградском проспекте",
    )
    assert SegmentResolver(FakeSearch(default=[foreign]), locality="Москва").resolve(entity) is None


def test_completion_dates_and_prose_are_not_projects() -> None:
    """«2 квартал 2026 года», «Прямо напротив», «…по соседству» — из живого карантина."""
    catalog = doc(
        "Новостройки Хамовников",
        "https://www.cian.ru/novostroyki-hamovniki/",
        "Японский дом · 2 квартал 2026 года · Прямо напротив · Новодевичий монастырь, по соседству · Феникс-Парк",
    )
    names = {item.canonical_name for item in extract_candidates([catalog])}
    assert {"Японский дом", "Феникс-Парк"} <= names
    for junk in ("2 квартал 2026 года", "Прямо напротив", "Новодевичий монастырь, по соседству"):
        assert junk not in names, junk
