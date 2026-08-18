"""Блоки метрик и свод рынка Москвы.

Числа взяты с живого стенда по Кутузов Сити и его соседям: так тест заодно
показывает, что именно блок должен уметь сказать.
"""

from __future__ import annotations

from market_search.market_reference import MoscowMarket
from market_search.metrics import (
    BLOCK_LOT,
    BLOCK_PACE,
    BLOCK_PRICE,
    BLOCK_STOCK,
    build_blocks,
    lot_size_block,
    pace_block,
    price_block,
    stock_block,
)


SUBJECT = {
    "name": "Кутузов Сити",
    "segment": "Бизнес",
    "price_per_sqm": 708_109,
    "price_per_sqm_min": 551_355,
    "price_per_sqm_max": 868_765,
    "observed_at": "2026-08-18",
    "lot_count": 56,
    "living_units": 220,
    "remaining_units": 165,
    "remaining_area": 10_534,
    "units_per_month": 4.6,
    "units_per_month_3m": 4.7,
    "sales_end_forecast": "2031-02-01",
    "sold_units": 27,
    "sold_area": 1448,
    "lot_area_avg": 61.0,
    "area_per_month": 207,
}

PEERS = [
    {"name": "Стеллар Сити", "price_per_sqm": 388_461, "units_per_month": 22.8, "lot_count": 311,
     "sold_lot_avg": 46.6, "area_per_month": 752},
    {"name": "Верейская 41", "price_per_sqm": 506_666, "units_per_month": 12.2, "lot_count": 115,
     "sold_lot_avg": 42.4, "area_per_month": 139},
    {"name": "Веер", "price_per_sqm": 515_823, "units_per_month": 34.4, "lot_count": 1092,
     "sold_lot_avg": 53.0, "area_per_month": 1485},
    {"name": "СЕТ", "price_per_sqm": 540_482, "units_per_month": 37.2, "lot_count": 746,
     "sold_lot_avg": 51.1, "area_per_month": 1249},
    {"name": "Нексус от Аквилон", "price_per_sqm": 563_767, "units_per_month": 7.8, "lot_count": 164,
     "sold_lot_avg": 52.6, "area_per_month": 458},
    {"name": "ИНДИВО", "price_per_sqm": 599_558, "units_per_month": 20.2, "lot_count": 57,
     "sold_lot_avg": 62.3, "area_per_month": 792},
]


def test_moscow_reference_ships_with_the_code() -> None:
    """Свод уезжает вместе с кодом: книга на 168 МБ в рантайме не нужна."""
    city = MoscowMarket.bundled()
    assert city.available
    assert city.observed_at == "2026-07"
    snapshot = city.snapshot("Бизнес")
    assert snapshot is not None
    assert snapshot.projects > 50
    assert 400_000 < snapshot.price_median < 900_000


def test_price_block_places_the_project_against_neighbours_and_the_city() -> None:
    """Один вопрос — три основания: сам проект, соседи, город."""
    block = price_block(SUBJECT, PEERS, MoscowMarket.bundled())
    assert block.subject["price_per_sqm"] == 708_109
    assert block.subject["basis"] == "прайс-лист, не сделка"

    assert block.peers["count"] == 6
    assert block.peers["median"] == 528_152.5
    assert block.peers["vs_median_pct"] == 34.1

    # Против города квартили честнее медианы: «выше верхнего квартиля» сразу
    # говорит, что проект вне основной массы, а «выше медианы» — нет.
    assert block.city["band"] == "above_p75"
    assert block.city["p75"] < 708_109


def test_pace_block_says_how_many_times_slower() -> None:
    block = pace_block(SUBJECT, PEERS, MoscowMarket.bundled())
    assert block.subject["units_per_month"] == 4.6
    assert block.peers["median"] == 21.5
    assert block.peers["peer_median_over_subject"] == 4.7
    assert block.city["sold_median"] is not None
    assert any("ДДУ" in note for note in block.notes)


def test_stock_block_counts_months_and_share_of_supply() -> None:
    block = stock_block(SUBJECT, PEERS, MoscowMarket.bundled())
    assert block.subject["exposure_share_pct"] == 25.5
    assert block.subject["months_to_sell"] == 35.9
    assert block.peers["exposure_total"] == 2485
    assert block.peers["subject_share_pct"] == 2.2


def test_lot_block_notices_that_small_lots_are_the_ones_selling() -> None:
    """Средний проданный лот 53,6 при среднем по проекту 61 — это факт о спросе."""
    block = lot_size_block(SUBJECT, PEERS, MoscowMarket.bundled())
    assert block.subject["sold_lot_avg"] == 53.6
    assert block.subject["project_lot_avg"] == 61.0
    assert block.subject["gap_pct"] == -12.1
    assert any("меньше средней" in note for note in block.notes)


def test_missing_data_is_named_not_zeroed() -> None:
    """Пустая база — не ноль в отчёте, а сказанное вслух «нечем сравнить»."""
    blank = {"name": "Без данных", "segment": "Бизнес"}
    block = price_block(blank, [], MoscowMarket.bundled())
    assert block.usable is False
    assert block.subject == {}
    assert block.notes and "нет действующего прайса" in block.notes[0]

    priced = price_block(SUBJECT, [], MoscowMarket.bundled())
    assert priced.peers == {}
    assert any("Ни у одного сопоставимого соседа" in note for note in priced.notes)


def test_unknown_section_is_refused_loudly() -> None:
    """Опечатка в списке разделов не должна выглядеть как пустой раздел."""
    import pytest

    with pytest.raises(ValueError, match="цена-метра"):
        build_blocks(SUBJECT, PEERS, MoscowMarket.bundled(), codes=[BLOCK_PRICE, "цена-метра"])


def test_constructor_returns_only_requested_sections() -> None:
    codes = [BLOCK_PACE, BLOCK_STOCK, BLOCK_LOT]
    blocks = build_blocks(SUBJECT, PEERS, MoscowMarket.bundled(), codes=codes)
    assert [b["code"] for b in blocks] == codes
    assert all(b["title"] for b in blocks)


def test_empty_reference_is_not_a_failure() -> None:
    """Нет свода — блок считает то, что может, и говорит, чего не хватило."""
    city = MoscowMarket({})
    assert city.available is False
    block = price_block(SUBJECT, PEERS, city)
    assert block.peers["count"] == 6
    assert block.city == {}


def test_price_hint_prefers_neighbours_then_okrug_then_city() -> None:
    """Порядок оснований важен: чем шире база, тем меньше она знает о месте."""
    from market_search.price_hint import BASIS_CITY, BASIS_OKRUG, BASIS_PEERS, price_hint

    near = [
        {"price_per_sqm": 506_666, "observed_at": "2026-08-17", "segment": "Бизнес"},
        {"price_per_sqm": 540_482, "observed_at": "2026-08-17", "segment": "Бизнес"},
        {"price_per_sqm": 515_823, "observed_at": "2026-08-18", "segment": "Бизнес"},
    ]
    hint = price_hint(peers=near, segment="Бизнес", okrug="Западный", fresh_since="2026-06-01")
    assert hint["basis"] == BASIS_PEERS
    assert hint["price_per_sqm"] == 515_823
    assert hint["sample"] == 3

    # Двух соседей мало — это не медиана, а пара случайных чисел.
    hint = price_hint(peers=near[:2], segment="Бизнес", okrug="Западный", fresh_since="2026-06-01")
    assert hint["basis"] in (BASIS_OKRUG, BASIS_CITY)

    # Устаревший прайс в выборку не идёт: у сданных домов он бывает 2020 года.
    stale = [{**row, "observed_at": "2022-05-18"} for row in near]
    hint = price_hint(peers=stale, segment="Бизнес", fresh_since="2026-06-01")
    assert hint["basis"] == BASIS_CITY

    # Класса нет и соседей нет — молча подставлять городскую медиану нельзя.
    hint = price_hint(peers=[], segment=None, fresh_since="2026-06-01")
    assert hint["available"] is False
    assert "не рассчитан" in hint["reason"]


def test_subject_is_recognised_from_the_same_input_as_the_main_service() -> None:
    """Ввод тот же, что в поле «Участок»: номер, координаты, название, адрес."""
    import pytest

    from market_search.subject import (
        SOURCE_CADASTRE,
        SOURCE_COORDS,
        SOURCE_PROJECT,
        Subject,
        SubjectNotFound,
        resolve_subject,
    )

    parcels = {
        "77:07:0013005:1042": {
            "center": {"lat": 55.71584, "lng": 37.43303},
            "address": "г Москва, ул Гродненская, вл 18",
        }
    }
    projects = {
        "кутузов сити": {
            "complex_id": 5924, "name": "Кутузов Сити", "segment": "Бизнес",
            "latitude": 55.71584, "longitude": 37.43303, "address": "ул. Гродненская, вл. 18",
        }
    }

    found = resolve_subject("77:07:0013005:1042", cadastre=parcels.get)
    assert found.source == SOURCE_CADASTRE
    assert found.cadastre == "77:07:0013005:1042"
    assert found.address.endswith("вл 18")

    found = resolve_subject("55.71584, 37.43303")
    assert found.source == SOURCE_COORDS
    assert (found.latitude, found.longitude) == (55.71584, 37.43303)

    found = resolve_subject("Кутузов Сити", find_project=lambda q: projects.get(q.lower()))
    assert found.source == SOURCE_PROJECT
    assert found.project_id == 5924 and found.segment == "Бизнес"

    # Номер опознан, но участка нет — это ответ, а не повод искать строку
    # номера геокодером: тот поставит точку куда угодно, и отчёт выйдет
    # достоверным на вид и не о том месте.
    with pytest.raises(SubjectNotFound, match="не найден в ЕГРН"):
        resolve_subject("77:07:0000000:1", cadastre=lambda n: None,
                        geocode=lambda t: Subject(0, 0, "x", t))

    with pytest.raises(SubjectNotFound, match="справочник ЕГРН недоступен"):
        resolve_subject("77:07:0013005:1042")

    with pytest.raises(SubjectNotFound, match="Пусто"):
        resolve_subject("   ")


def test_mixed_class_sample_shows_its_own_class_separately() -> None:
    """Соседний класс в выборке — решение владельца, но не повод прятать разброс.

    У Кутузов Сити соседи по лестнице — комфорт и премиум, и общая медиана
    получается серединой между тремя разными товарами. Она остаётся, но рядом
    обязана стоять медиана своего класса, иначе отчёт выдаёт мушу за уровень
    рынка.
    """
    mixed = [
        {"name": "Петра Алексеева 10", "segment": "Комфорт", "price_per_sqm": 268_800},
        {"name": "Верейская 41", "segment": "Бизнес", "price_per_sqm": 506_666},
        {"name": "СЕТ", "segment": "Бизнес", "price_per_sqm": 540_715},
        {"name": "Родина Парк", "segment": "Премиум", "price_per_sqm": 780_032},
        {"name": "Спрингс", "segment": "Премиум", "price_per_sqm": 1_254_077},
    ]
    block = price_block(SUBJECT, mixed, MoscowMarket.bundled())
    assert block.peers["count"] == 5
    assert block.peers["median"] == 540_715
    assert block.peers["same_class"]["count"] == 2
    assert block.peers["same_class"]["median"] == 523_690.5
    assert any("своего класса" in note for note in block.notes)

    # Выборка одного класса лишней строки не заводит: сравнивать не с чем.
    plain = [row for row in mixed if row["segment"] == "Бизнес"]
    assert "same_class" not in price_block(SUBJECT, plain, MoscowMarket.bundled()).peers


def _fake_pulse(segments, metrics, projects):
    """Источник без сети: те же вызовы, что у PulseClient, но на словаре."""
    import math
    from types import SimpleNamespace

    def near(lat, lon, radius_km):
        out = []
        for row in projects:
            dy = (row["latitude"] - lat) * 111.0
            dx = (row["longitude"] - lon) * 111.0 * math.cos(math.radians(lat))
            distance = math.hypot(dx, dy)
            if distance <= radius_km:
                out.append((round(distance, 3), SimpleNamespace(**row)))
        return sorted(out, key=lambda item: item[0])

    return SimpleNamespace(
        available=True,
        segments=lambda: segments,
        near=near,
        metrics=lambda cid: metrics.get(cid, {}),
        project_totals=lambda cid: {},
        find_project=lambda query: None,
        remaining=lambda cid: {},
    )


def test_constructor_names_where_the_class_came_from(tmp_path) -> None:
    """Класс ставит «Пульс» (решение владельца 18.08.2026), но у пустыря его нет.

    Метка источника и догадка по окружению в ответе выглядят одинаково, и
    отличить их можно только полем: без него отчёт по голому участку не
    отличается от отчёта по проекту.
    """
    from market_search.service_v6 import MarketDiscoveryService

    service = MarketDiscoveryService(tmp_path)
    segments = {5924: "Бизнес", 5549: "Премиум", 5737: "Премиум"}
    metrics = {
        5924: {"price_per_sqm": 708_109, "observed_at": "2026-08-18", "units_per_month": 4.6},
        5549: {"price_per_sqm": 780_032, "observed_at": "2026-08-18", "units_per_month": 20.1},
        5737: {"price_per_sqm": 1_254_077, "observed_at": "2026-08-18", "units_per_month": 3.5},
    }
    projects = [
        {"complex_id": 5924, "name": "Кутузов Сити", "developer": "—",
         "latitude": 55.71584, "longitude": 37.43303},
        {"complex_id": 5549, "name": "Родина Парк", "developer": "—",
         "latitude": 55.72100, "longitude": 37.43900},
        {"complex_id": 5737, "name": "Спрингс", "developer": "—",
         "latitude": 55.73200, "longitude": 37.45500},
    ]
    service.pulse = _fake_pulse(segments, metrics, projects)

    # Точка совпала с проектом — класс у источника, и он же в отчёте.
    report = service.build_report("55.71584, 37.43303", codes=[BLOCK_PRICE])
    assert report["subject"]["segment"] == "Бизнес"
    assert report["subject"]["segment_source"] == "pulse"

    # Премиальный сосед входит в выборку соседним классом, оставаясь премиумом:
    # несогласие с меткой выражается правилом уровня, а не подменой класса.
    assert {peer["name"] for peer in report["peers"]} == {"Родина Парк", "Спрингс"}
    assert {peer["segment"] for peer in report["peers"]} == {"Премиум"}

    # Голый участок в стороне от проектов — класса в источнике нет, и это
    # сказано вслух, а не выдано за метку «Пульса».
    blank = service.build_report("55.72600, 37.44700", codes=[BLOCK_PRICE])
    assert blank["subject"]["segment_source"] == "neighbours"
    assert blank["comparison"]["segment_source"] == "neighbours"
