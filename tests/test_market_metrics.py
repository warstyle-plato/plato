"""Блоки метрик и свод рынка Москвы.

Числа взяты с живого стенда по Кутузов Сити и его соседям: так тест заодно
показывает, что именно блок должен уметь сказать.
"""

from __future__ import annotations

from types import SimpleNamespace

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
        price_history=lambda ids, months=12: {},
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
         "latitude": 55.71584, "longitude": 37.43303,
         "address": "Москва, ЗАО, район Можайский, ул. Гродненская, вл. 18"},
        {"complex_id": 5549, "name": "Родина Парк", "developer": "—",
         "latitude": 55.72100, "longitude": 37.43900,
         "address": "Москва, ЗАО, район Можайский, ул. Верейская, вл. 12"},
        {"complex_id": 5737, "name": "Спрингс", "developer": "—",
         "latitude": 55.73200, "longitude": 37.45500,
         "address": "Москва, ЗАО, р-н Фили-Давыдково, ул. Малая Филёвская, вл. 46"},
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


def test_report_route_answers_and_refuses_with_a_reason(tmp_path, monkeypatch) -> None:
    """Конструктор должен быть достижим снаружи, иначе стенд его не показывает.

    До этого маршрута у модуля были только `/market/discovery` (сниппетный путь,
    который мы списываем) и `/market/price-hint`. Отчёт собирался лишь из кода,
    и приёмка поневоле мерила старый конвейер.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from market_search.api import install

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MARKET_CABINET_KEY", "stand-key-2026")
    app = FastAPI()
    service = install(app)

    segments = {5924: "Бизнес", 5549: "Премиум"}
    metrics = {
        5924: {"price_per_sqm": 708_109, "observed_at": "2026-08-18", "units_per_month": 4.6},
        5549: {"price_per_sqm": 780_032, "observed_at": "2026-08-18", "units_per_month": 20.1},
    }
    projects = [
        {"complex_id": 5924, "name": "Кутузов Сити", "developer": "—",
         "latitude": 55.71584, "longitude": 37.43303,
         "address": "Москва, ЗАО, район Можайский, ул. Гродненская, вл. 18"},
        {"complex_id": 5549, "name": "Родина Парк", "developer": "—",
         "latitude": 55.72100, "longitude": 37.43900,
         "address": "Москва, ЗАО, район Можайский, ул. Верейская, вл. 12"},
    ]
    service.pulse = _fake_pulse(segments, metrics, projects)
    client = TestClient(app, headers={"X-Market-Key": "stand-key-2026"})

    answer = client.post(
        "/market/report",
        json={"query": "55.71584, 37.43303", "codes": ["price"], "peers_limit": 5},
    )
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["subject"]["segment_source"] == "pulse"
    assert [peer["name"] for peer in body["peers"]] == ["Родина Парк"]
    assert [block["code"] for block in body["blocks"]] == ["price"]

    # Опечатка в списке разделов — отказ с причиной, а не пустой отчёт.
    typo = client.post("/market/report", json={"query": "55.71584, 37.43303", "codes": ["цена"]})
    assert typo.status_code == 422
    assert "цена" in typo.json()["detail"]

    # Кадастровый номер опознан, но справочника нет — это ответ человеку, а не
    # поломка сервиса, и потому 422, а не 500.
    service.cadastre_lookup = None
    refusal = client.post("/market/report", json={"query": "77:07:0013005:1042"})
    assert refusal.status_code == 422
    assert "ЕГРН" in refusal.json()["detail"]

    # Источник выключен — 502: чинить нечего, нужны доступы.
    service.pulse = SimpleNamespace(available=False, find_project=lambda q: None)
    off = client.post("/market/report", json={"query": "55.71584, 37.43303"})
    assert off.status_code == 502
    assert "PULSE_LOGIN" in off.json()["detail"]


def test_cabinet_is_closed_by_default_and_opens_only_by_key(tmp_path, monkeypatch) -> None:
    """Незаданный ключ выключает кабинет, а не открывает его.

    Так же устроен список получателей статистики: пусто — значит никому.
    Раздел, открывшийся всем из-за незаполненной переменной, — худший исход,
    потому что выглядит работающим.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from market_search.api import install

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("MARKET_CABINET_KEY", raising=False)
    app = FastAPI()
    install(app)
    client = TestClient(app)

    closed = client.get("/cabinet")
    assert closed.status_code == 503
    assert "MARKET_CABINET_KEY" in closed.text
    assert client.post("/market/report", json={"query": "Кутузов Сити"}).status_code == 503

    monkeypatch.setenv("MARKET_CABINET_KEY", "stand-key-2026")
    assert client.get("/cabinet").status_code == 401
    assert client.post("/market/report", json={"query": "Кутузов Сити"}).status_code == 401

    # Неверный ключ не пускает и не подсказывает, чем именно он неверен.
    denied = client.post("/cabinet/login", content="key=wrong",
                         headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert denied.status_code == 401
    assert "stand-key-2026" not in denied.text

    entered = client.post("/cabinet/login", content="key=stand-key-2026",
                          headers={"Content-Type": "application/x-www-form-urlencoded"},
                          follow_redirects=False)
    assert entered.status_code == 303
    assert client.get("/cabinet").status_code == 200
    assert "Конструктор отчёта" in client.get("/cabinet").text

    # Кириллический ключ заголовком не передаётся — это должно быть сказано,
    # а не проявляться загадочным отказом на одном из двух путей входа.
    monkeypatch.setenv("MARKET_CABINET_KEY", "ключ")
    broken = TestClient(app).get("/cabinet")
    assert broken.status_code == 503
    assert "не-ASCII" in broken.text


def test_price_hint_stays_open_when_the_cabinet_is_closed(tmp_path, monkeypatch) -> None:
    """Кнопка ориентира — не кабинет: одно число без источников, она открыта.

    Закрыть её вместе с конструктором значило бы сломать основной сервис ради
    границы, которую она и так соблюдает.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from market_search.api import install

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("MARKET_CABINET_KEY", raising=False)
    app = FastAPI()
    service = install(app)
    service.pulse = SimpleNamespace(available=False, find_project=lambda q: None)
    client = TestClient(app)

    answer = client.post("/market/price-hint", json={"latitude": 55.7158, "longitude": 37.4330})
    assert answer.status_code != 401
    assert answer.status_code != 503


def test_suggestions_rank_the_name_above_the_address(tmp_path) -> None:
    """Набравший «кутуз» ищет «Кутузов Сити», а не дома на Кутузовском проспекте.

    Подсказка берётся из своего справочника, не по сети: обращение к источнику
    на каждую букву замедлило бы ввод и ничего бы не добавило.
    """
    import json

    from market_search.pulse import PulseClient

    rows = [
        {"complex_id": 1, "name": "Кутузов Сити", "developer": "PLATO",
         "latitude": 55.7, "longitude": 37.4, "address": "ул. Гродненская, вл. 18"},
        {"complex_id": 2, "name": "Кутузовский XII", "developer": "Capital Group",
         "latitude": 55.7, "longitude": 37.5, "address": "Кутузовский проспект, вл. 12"},
        {"complex_id": 3, "name": "Левел Кутузовский", "developer": "Level",
         "latitude": 55.7, "longitude": 37.5, "address": "Гришина ул., вл. 16"},
        {"complex_id": 4, "name": "Событие", "developer": "Донстрой",
         "latitude": 55.6, "longitude": 37.4, "address": "Кутузовский проспект, вл. 99"},
    ]
    (tmp_path / "projects.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "segments.json").write_text(json.dumps({"1": "Бизнес"}), encoding="utf-8")

    client = PulseClient(tmp_path, login="x", password="y")
    names = [row["name"] for row in client.suggest("кутуз")]

    # Сначала совпавшие с начала имени — короткое имя выше длинного, потом
    # совпадение внутри имени, и только затем найденные по адресу.
    assert names == ["Кутузов Сити", "Кутузовский XII", "Левел Кутузовский", "Событие"]
    assert client.suggest("к") == []
    assert client.suggest("кутуз")[0]["segment"] == "Бизнес"


def test_suggestions_are_behind_the_cabinet_key(tmp_path, monkeypatch) -> None:
    """Список чужой базы — это тоже лицензионные данные, ключ обязателен."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from market_search.api import install

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MARKET_CABINET_KEY", "stand-key-2026")
    app = FastAPI()
    install(app)

    assert TestClient(app).get("/market/projects/suggest?q=кутуз").status_code == 401
    opened = TestClient(app, headers={"X-Market-Key": "stand-key-2026"})
    answer = opened.get("/market/projects/suggest?q=кутуз")
    assert answer.status_code == 200
    # Источника нет — пустой список и названная причина, а не молчание.
    assert answer.json()["items"] == []
    assert "PULSE_LOGIN" in answer.json()["reason"]


def test_city_base_is_not_borrowed_for_another_city() -> None:
    """Свод — «Москва старая». Для Мытищ его медианы не значат ничего.

    `snapshot()` смотрит только на класс и отдал бы московские квартили
    молча: отчёт по подмосковному проекту выглядел бы исправным и сравнивал
    бы его не с тем рынком. Новая Москва — тот же случай: слово «Москва» в
    адресе есть, а в отчёт она не входит.
    """
    city = MoscowMarket.bundled()

    assert city.covers("Москва, ЗАО, район Можайский, ул. Гродненская, вл. 18")
    assert not city.covers("МО, Мытищи, Летная ул.")
    assert not city.covers("Москва, ТАО, поселение Роговское, п. Рогово")
    assert not city.covers("")

    scope = city.scope("МО, Мытищи, Летная ул.")
    assert scope["covered"] is False
    assert "Москва старая" in scope["reason"]
    assert city.scope("Москва, Саввинская набережная, 25")["covered"] is True


def test_cabinet_script_is_valid_javascript() -> None:
    """Скрипт страницы проверяется настоящим node, а не на глаз.

    `CABINET_PAGE` — строка Python, и `\\n`, написанный для JavaScript, при
    обычных кавычках превращается в настоящий перенос ещё при импорте модуля:
    строка обрывается, и вся страница перестаёт работать целиком. Ошибка не
    видна ни в одном тесте на данные — она видна только в браузере.
    """
    import re
    import shutil
    import subprocess
    import tempfile

    import pytest

    from market_search.cabinet import cabinet_page

    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")

    scripts = re.findall(r"<script[^>]*>(.*?)</script>", cabinet_page(), re.S)
    assert scripts, "на странице кабинета нет скрипта"
    for index, source in enumerate(scripts):
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as handle:
            handle.write(source)
            path = handle.name
        done = subprocess.run([node, "--check", path], capture_output=True, text=True)
        assert done.returncode == 0, f"скрипт {index}: {done.stderr[:400]}"


def test_every_element_the_script_asks_for_exists_in_the_markup() -> None:
    """`$('#чего-нет')` возвращает null, и страница падает целиком.

    Одна забытая разметка — и не работает ничего: ни отчёт, ни подсказки, ни
    кнопки, потому что исключение обрывает установку всех обработчиков разом.
    В браузере это выглядит как «кабинет не реагирует», а в тестах на данные не
    видно вовсе.
    """
    import re

    from market_search.cabinet import cabinet_page

    page = cabinet_page()
    # Объявление ищется по всей странице, а не только в статической разметке:
    # часть узлов скрипт создаёт сам из шаблонов. Проверка ловит другое — имя,
    # которого нет нигде: опечатку и забытую вёрстку.
    present = set(re.findall(r'id="([a-zA-Z0-9_-]+)"', page))
    asked = set(re.findall(r"\$\('#([a-zA-Z0-9_-]+)'\)", page))
    assert asked, "скрипт не обращается ни к одному элементу — проверка бесполезна"
    assert not (asked - present), f"скрипт зовёт то, чего нет в разметке: {sorted(asked - present)}"


def test_market_tab_can_be_switched_off_without_losing_the_button(monkeypatch) -> None:
    """В production нужна кнопка и кабинет, но не вкладка «Рынок».

    Вкладка — сниппетный конвейер, который мы списываем: приёмка по нему
    красная. Кнопка ориентира от него не зависит — помощник поиска поля вложен
    в её скрипт, иначе вся её ценность (работает сама по себе) пропадала бы.
    """
    from market_search.ui_v6 import install_price_hint

    class FakeCore:
        PAGE = "<html><head></head><body><div id='root'></div></body></html>"

    only_button = FakeCore()
    install_price_hint(only_button)
    assert 'data-tab="marketDiscovery"' not in only_button.PAGE
    assert "market-v6-price-hint" in only_button.PAGE
    # Кнопка ищет поле цены сама, без панели.
    assert "function mdApartmentPriceInput()" in only_button.PAGE
    assert "function mdSetNativeValue(" in only_button.PAGE

    # Повторная установка ничего не дублирует: страница собирается один раз,
    # но модуль могут поставить дважды.
    install_price_hint(only_button)
    assert only_button.PAGE.count('id="market-v6-price-hint"') == 1


def test_price_hint_does_not_borrow_the_moscow_median_outside_moscow(tmp_path, monkeypatch) -> None:
    """Кнопка ориентира молча отвечала московской медианой на подмосковный адрес.

    Основания идут по убыванию силы: соседи, округ, город. Последнее — свод
    «Москва старая», и за его пределами оно означает не «шире», а «про другой
    город». На Мытищах кнопка выдавала 437 400 ₽/м² «по классу в Москве» и
    выглядела ответом.
    """
    from market_search.market_reference import MoscowMarket
    from market_search.price_hint import price_hint

    city = MoscowMarket.bundled()
    assert city.scope("Лётная улица, Мытищи, Московская область")["covered"] is False

    # С городской базой ориентир нашёлся бы — и был бы московским.
    borrowed = price_hint(peers=[], segment="Комфорт", okrug=None, city=city, fresh_since="2026-02-01")
    assert borrowed["available"] is True
    assert borrowed["basis"] == "city"

    # Без неё — честный отказ.
    refused = price_hint(peers=[], segment="Комфорт", okrug=None, city=MoscowMarket({}),
                         fresh_since="2026-02-01")
    assert refused["available"] is False


def test_suggestions_work_from_a_warm_cache_without_credentials(tmp_path, monkeypatch) -> None:
    """Справочник лежит файлом рядом — доступы нужны только на его обновление.

    Маршрут гасил подсказки признаком `available` ещё до того, как справочник
    спрашивали: на стенде с тёплым кэшем и без `PULSE_LOGIN` поле молчало.
    Молчало одинаково для «источник выключен» и «такого проекта нет», а
    отличить их человеку было нечем — оба выглядели как пустой список.
    """
    import json

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from market_search.api import install

    cache = tmp_path / "market" / "pulse"
    cache.mkdir(parents=True)
    (cache / "projects.json").write_text(
        json.dumps(
            [{"complex_id": 1, "name": "Кутузов Сити", "developer": "PLATO",
              "latitude": 55.7, "longitude": 37.4, "address": "ул. Гродненская, вл. 18"}],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MARKET_CABINET_KEY", "stand-key-2026")
    monkeypatch.delenv("PULSE_LOGIN", raising=False)
    monkeypatch.delenv("PULSE_PASSWORD", raising=False)
    app = FastAPI()
    install(app)
    opened = TestClient(app, headers={"X-Market-Key": "stand-key-2026"})

    found = opened.get("/market/projects/suggest?q=кутуз").json()
    assert [item["name"] for item in found["items"]] == ["Кутузов Сити"]

    # А пустой ответ по-прежнему объясняется, а не молчит.
    empty = opened.get("/market/projects/suggest?q=такогонет").json()
    assert empty["items"] == []
    assert "такогонет" in empty["reason"]
    assert "две буквы" in opened.get("/market/projects/suggest?q=к").json()["reason"]


def test_the_report_opens_with_the_verdict_and_closes_with_the_bottom_line() -> None:
    """Вывод — первым и последним, а не четвёртой карточкой посреди графиков.

    Он стоял под картой рынка и ценами соседей, то есть ниже сгиба: человек
    открывал отчёт и видел два больших графика вместо ответа. А заканчивался
    отчёт таблицей соседей — данными, без итога.
    """
    from market_search.cabinet import CABINET_PAGE

    body = CABINET_PAGE[CABINET_PAGE.index("function render(d)"):]
    verdict = body.index("Куда попадает проект")
    market_map = body.index("<h2>Карта рынка</h2>")
    assert verdict < market_map, "вывод обязан стоять до карты рынка"

    # Итоговая карточка приклеивается последней, уже после таблицы соседей.
    peers_table = body.index("<h2>Соседи в выборке</h2>")
    final = body.index("html+=finalCard(d);")
    assert peers_table < final < body.index("$('#out').innerHTML=html;")

    # Оговорки печатаются один раз — в итоге, а не в карточке премии, которой
    # может не быть вовсе.
    assert CABINET_PAGE.count("<h3>Чего эти числа не говорят</h3>") == 1


def test_the_hint_for_a_bare_site_stands_on_the_neighbours_of_its_own_report(tmp_path) -> None:
    """Ориентир будущего проекта — по конкурентам рядом, а не по городу.

    Кнопка ходила своим путём: радиус 2,5 км и двадцать ближайших. На участке
    в Новогирееве при пятнадцати сопоставимых соседях в отчёте она отвечала
    «по классу в Москве» — ориентир будущего проекта строился по городу, пока
    его конкуренты стояли на экране рядом.
    """
    from market_search.service_v6 import MarketDiscoveryService

    service = MarketDiscoveryService(tmp_path)
    segments = {i: "Бизнес" for i in (1, 2, 3)}
    metrics = {
        1: {"price_per_sqm": 500_000, "observed_at": "2026-08-18", "units_per_month": 5.0},
        2: {"price_per_sqm": 520_000, "observed_at": "2026-08-18", "units_per_month": 6.0},
        3: {"price_per_sqm": 560_000, "observed_at": "2026-08-18", "units_per_month": 4.0},
    }
    projects = [
        {"complex_id": 1, "name": "Первый", "developer": "—",
         "latitude": 55.7300, "longitude": 37.4400, "address": "Москва, ЗАО, район Можайский, дом 1"},
        {"complex_id": 2, "name": "Второй", "developer": "—",
         "latitude": 55.7310, "longitude": 37.4410, "address": "Москва, ЗАО, район Можайский, дом 2"},
        {"complex_id": 3, "name": "Третий", "developer": "—",
         "latitude": 55.7320, "longitude": 37.4420, "address": "Москва, ЗАО, район Можайский, дом 3"},
    ]
    service.pulse = _fake_pulse(segments, metrics, projects)

    report = service.build_report("55.73050, 37.44050", codes=[BLOCK_PRICE])
    hint = report["price_hint"]

    assert hint["available"] is True
    # Основание — соседи, и это те же соседи, что в выборке отчёта.
    assert hint["basis"] == "peers"
    assert hint["sample"] == len(report["peers"])
    assert hint["price_per_sqm"] == 520_000


def test_a_neighbour_name_opens_its_card_from_every_table() -> None:
    """Карточка соседа открывалась только из таблицы внизу.

    В таблицах разделов, где на соседа как раз и смотрят, то же имя было
    мёртвым текстом: чтобы посмотреть проект, приходилось искать его ещё раз
    в списке под всем отчётом.
    """
    from market_search.cabinet import CABINET_PAGE

    # Обработчик один — `td.link[data-peer]`; значит и таблица разделов обязана
    # ставить эту пару, иначе имя в ней остаётся текстом.
    assert "document.querySelectorAll('td.link[data-peer]')" in CABINET_PAGE
    assert 'attr:(r,i)=>r.__own?\'\':` class="link" data-peer="${i-1}"`' in CABINET_PAGE
    assert "c.attr?c.attr(r,i):''" in CABINET_PAGE


def test_the_bubble_knows_its_name_and_the_print_takes_every_view() -> None:
    """Кружок без подписи — точка без проекта, а в печати переключателя нет."""
    from market_search.cabinet import CABINET_PAGE

    # Имя показывается стилем по наведению: подсказка браузера ждёт секунду.
    assert "g.bub:hover text.hov{opacity:1}" in CABINET_PAGE
    assert '<text class="hov"' in CABINET_PAGE
    # На бумагу уходят все пары осей, а открытая на экране — прячется, иначе
    # она напечаталась бы дважды.
    assert ".printviews{display:block}" in CABINET_PAGE
    assert 'VIEWS.map(v=>`<h3>${esc(v.name)}</h3>`+bubbleChart(market,v))' in CABINET_PAGE


def test_the_search_shows_what_it_is_doing_while_it_waits() -> None:
    """Ожидание без признака работы читается как внезапность.

    Страница молчала полминуты и разом выкладывала отчёт. Сервер о своих шагах
    не сообщает, поэтому ход показывается тем, что есть: секундами и порядком
    шагов.
    """
    from market_search.cabinet import CABINET_PAGE

    assert "const timer=setInterval(tick,1000)" in CABINET_PAGE
    assert "clearInterval(timer)" in CABINET_PAGE
    assert "Спрашиваю прайсы и темпы у «Пульса»" in CABINET_PAGE
