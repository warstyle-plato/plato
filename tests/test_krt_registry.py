import json
from pathlib import Path
import sys
from types import SimpleNamespace

from market_search.geocoder import GeocodingError
from market_search.krt_registry import KrtRegistry, parse_catalogue, parse_catalogue_markdown
from market_search.subject import SOURCE_KRT, resolve_subject


PAGE = """
<a href="/projects/no7-oktabr-skoe-pole"><img></a>
<a href="/projects/no7-oktabr-skoe-pole">№7 Октябрьское поле <span>Подробнее</span></a>
<p>Площадь: 5.92</p><p>Округ: СЗАО</p><p>Район: Щукино</p><p>Статус: В реализации</p>
<p>Общий объем застройки: 184930</p><p>Жилое назначение: 161680</p>
<p>Общественно-деловое назначение: 12700</p><p>Прирост рабочих мест: 1490</p>
<button class="button show_more" data-url="/projects/?PAGEN_1=2">Загрузить еще</button>
"""


def test_catalogue_parser_keeps_source_tep_and_pagination() -> None:
    rows, next_url = parse_catalogue(PAGE)
    assert next_url == "https://api.krt.mos.ru/projects/?PAGEN_1=2"
    assert len(rows) == 1
    row = rows[0]
    assert row.slug == "no7-oktabr-skoe-pole"
    assert row.area_ha == 5.92
    assert row.housing_gfa_sqm == 161680
    assert row.business_gfa_sqm == 12700
    assert row.query == "krt:no7-oktabr-skoe-pole"


def test_rendered_official_catalogue_keeps_the_same_fields() -> None:
    markdown = """
[№7 Октябрьское поле Подробнее](https://api.krt.mos.ru/projects/no7-oktabr-skoe-pole)

Площадь: 5.92

Округ: СЗАО

Район: Щукино

Статус: В реализации

Общий объем застройки: 184930

Жилое назначение: 161680

Прирост рабочих мест: 1490
"""
    rows = parse_catalogue_markdown(markdown)
    assert len(rows) == 1
    assert rows[0].slug == "no7-oktabr-skoe-pole"
    assert rows[0].housing_gfa_sqm == 161680
    assert rows[0].district == "Щукино"


def test_rendered_catalogue_does_not_assign_the_next_card_to_previous_krt() -> None:
    markdown = """
[Ул. Сеславинская, вл. 6А, Минская ул., вл. 2Г Подробнее](https://api.krt.mos.ru/projects/seslavinskaya)

Площадь: 1.79
Округ: ЗАО
Район: Филёвский парк
Статус: Планируемый

[Полимерная ул., вл. 8 (Мартеновская ул.)Подробнее](https://api.krt.mos.ru/projects/polimernaya)

Площадь: 12.97
Округ: ВАО
Район: Новогиреево
Статус: Планируемый
Общий объем застройки: 305440
Жилое назначение: 300440

[Зеленый проспект, влд. 2Подробнее](https://api.krt.mos.ru/projects/zelenyy)

Площадь: 2.28
Округ: ВАО
Район: Перово
Статус: Планируемый
Общий объем застройки: 79010
Жилое назначение: 79010
"""

    rows = parse_catalogue_markdown(markdown)

    assert [row.slug for row in rows] == ["seslavinskaya", "polimernaya", "zelenyy"]
    assert rows[0].area_ha == 1.79
    assert rows[0].okrug == "ЗАО"
    assert rows[0].district == "Филёвский парк"
    assert rows[0].housing_gfa_sqm is None
    assert rows[1].housing_gfa_sqm == 300440
    assert rows[2].housing_gfa_sqm == 79010


def test_cold_catalogue_never_waits_for_the_city_portal(tmp_path: Path) -> None:
    registry = KrtRegistry(tmp_path, fetch=lambda url: (_ for _ in ()).throw(
        AssertionError("network must stay off the request thread")
    ))
    started = []
    registry.refresh_in_background = lambda: started.append(True) or True
    assert registry.catalogue() == []
    assert started == [True]


def test_registry_uses_last_snapshot_when_portal_is_down(tmp_path: Path) -> None:
    good = KrtRegistry(tmp_path, fetch=lambda url: PAGE.encode())
    rows = good.projects(refresh=True, max_pages=1)
    assert rows and good.path.exists()
    bad = KrtRegistry(tmp_path, fetch=lambda url: (_ for _ in ()).throw(OSError("down")))
    assert bad.projects(refresh=True)[0].name == "№7 Октябрьское поле"


def test_legacy_misaligned_snapshot_is_refreshed_even_when_fresh(tmp_path: Path) -> None:
    registry = KrtRegistry(tmp_path, fetch=lambda url: PAGE.encode())
    registry.path.parent.mkdir(parents=True)
    registry.path.write_text(json.dumps({
        "complete": True,
        "projects": [{
            "slug": "old", "name": "Старая карточка", "url": "https://example.test",
        }],
    }), encoding="utf-8")
    started = []
    registry.refresh_in_background = lambda: started.append(True) or True

    assert registry.catalogue()[0]["slug"] == "old"
    assert registry.status()["complete"] is False
    assert started == [True]


def test_krt_is_a_subject_with_an_explicit_approximation(tmp_path: Path) -> None:
    registry = KrtRegistry(tmp_path, fetch=lambda url: PAGE.encode())
    registry.projects(refresh=True, max_pages=1)
    point = SimpleNamespace(latitude=55.79, longitude=37.49, display_name="Москва, Щукино")
    subject = resolve_subject(
        "krt:no7-oktabr-skoe-pole", geocode=lambda query: point, find_krt=registry.find
    )
    assert subject.source == SOURCE_KRT
    assert subject.subject_type == "krt"
    assert subject.source_data["total_gfa_sqm"] == 184930
    assert "геометр" in subject.notes[0].lower()


def test_krt_multiple_holdings_are_geocoded_as_separate_addresses() -> None:
    territory = {
        "slug": "two-holdings",
        "query": "krt:two-holdings",
        "name": "ул. Сеславинская, вл. 6А, Минская ул., вл. 2Г",
        "district": "Перово",
        "geocode_query": (
            "Москва, Перово, ул. Сеславинская, вл. 6А, Минская ул., вл. 2Г"
        ),
    }
    calls = []

    def geocode(query: str):
        calls.append(query)
        if query == "Москва, ул. Сеславинская, вл. 6А":
            return SimpleNamespace(
                latitude=55.744, longitude=37.499, display_name=query
            )
        raise GeocodingError(f"Адрес «{query}» не найден")

    subject = resolve_subject(
        "krt:two-holdings", geocode=geocode, find_krt=lambda query: territory
    )

    assert calls == ["Москва, ул. Сеславинская, вл. 6А"]
    assert subject.address == "Москва, ул. Сеславинская, вл. 6А"
    assert "отдельному адресу" in subject.notes[1]


def test_krt_falls_back_to_district_when_each_address_is_not_found() -> None:
    territory = {
        "slug": "district-fallback",
        "query": "krt:district-fallback",
        "name": "ул. Первая, вл. 1, Вторая ул., вл. 2",
        "district": "Перово",
        "geocode_query": "Москва, Перово, ул. Первая, вл. 1, Вторая ул., вл. 2",
    }
    calls = []

    def geocode(query: str):
        calls.append(query)
        if query == "Москва, район Перово":
            return SimpleNamespace(
                latitude=55.751, longitude=37.786, display_name=query
            )
        raise GeocodingError(f"Адрес «{query}» не найден")

    subject = resolve_subject(
        "krt:district-fallback", geocode=geocode, find_krt=lambda query: territory
    )

    assert calls == [
        "Москва, ул. Первая, вл. 1",
        "Москва, Вторая ул., вл. 2",
        "Москва, район Перово",
    ]
    assert subject.address == "Москва, район Перово"
    assert "предварительного анализа" in subject.notes[1]


def test_auctions_exposes_krt_as_a_separate_tab_and_endpoint(monkeypatch) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import main_legacy as core
    from auction_search.api import install

    project = {
        "slug": "test", "name": "КРТ Тест", "status": "Планируемый",
        "housing_gfa_sqm": 161_680, "total_gfa_sqm": 184_930,
    }
    calls = []
    monkeypatch.setenv("MARKET_CABINET_KEY", "test-key")
    monkeypatch.setitem(sys.modules, "developaid_core", core)
    app = FastAPI()
    app.state.market_discovery_service = SimpleNamespace(
        krt=SimpleNamespace(
            catalogue=lambda: [project], status=lambda: {"complete": True, "refreshing": False}
        ),
        build_report=lambda query, **kwargs: calls.append((query, kwargs)) or {
            "subject": {"project_name": "КРТ Тест"},
            "peers": [{"name": "ЖК рядом"}],
            "analysis": {"site": {
                "segment": "бизнес", "price_per_sqm": 708_000, "sold_lot_avg": 50.0,
            }},
            "price_hint": {"entry_per_sqm": 650_000, "price_per_sqm": 708_000},
        },
    )
    install(app)
    client = TestClient(app)
    page = client.get("/auctions")
    assert page.status_code == 200
    assert "Проекты КРТ Москвы" in page.text
    assert "/auctions/krt" in page.text
    assert 'id="krtOkrug"' in page.text
    assert 'id="krtOkrugOptions"' in page.text
    assert "input.type='checkbox'" in page.text
    assert "krtOkrugs:new Set()" in page.text
    assert "state.krtOkrugs.has(x.okrug)" in page.text
    assert "const values=KRT_OKRUGS" in page.text
    assert "const KRT_OKRUGS=['ЦАО','САО'" in page.text
    assert "'НАО','ТАО','ЗелАО'" in page.text
    assert "Оценка Платона" in page.text
    # Подпись фильтра каталога: «Платон:» из неё убрана намеренно — балл здесь
    # арифметический, по каталожным ТЭП, и Платон в нём не участвует. Он
    # появляется отдельной кнопкой, и обещать его выбором в списке нельзя.
    assert "Ищем: жильё, готовое к старту" in page.text
    assert "Платон: жильё" not in page.text
    assert "Короткий вывод Платона" in page.text
    assert "analysis.site||analysis.overall" in page.text
    # Карточка открывает посчитанное, а не запускает счёт заново: кнопка
    # называется пересчётом, потому что отчёт уже лежит.
    assert "Пересчитать сейчас" in page.text
    assert "Передать в DevelopAid" in page.text
    assert "Предварительный прогон модели" in page.text
    answer = client.get("/auctions/krt")
    assert answer.status_code == 200
    # Каталог дописывает к площадке, когда её впервые увидели: «новое» — это
    # разница с прошлым составом, и считать её должен сервер, а не человек
    # глазами по списку.
    returned = answer.json()["projects"]
    assert [{key: value for key, value in row.items()
             if key not in {"first_seen_at", "is_new"}} for row in returned] == [project]
    assert returned[0]["is_new"] is False, "первый снимок новым никого не делает"
    assert "new_count" in answer.json()
    assert answer.json()["complete"] is True
    assert client.get("/auctions/krt/test/market").status_code == 401
    market = client.get("/auctions/krt/test/market", headers={"X-Market-Key": "test-key"})
    assert market.status_code == 200
    assert market.json()["peers"][0]["name"] == "ЖК рядом"
    assert market.json()["model_screening"]["available"] is True
    assert market.json()["model_screening"]["phasing"]["count"] == 2
    assert calls[0][0] == "krt:test"
    assert calls[0][1]["include_project_totals"] is True
