from pathlib import Path
from types import SimpleNamespace

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


def test_auctions_exposes_krt_as_a_separate_tab_and_endpoint(monkeypatch) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from auction_search.api import install

    project = {"slug": "test", "name": "КРТ Тест", "status": "Планируемый"}
    calls = []
    monkeypatch.setenv("MARKET_CABINET_KEY", "test-key")
    app = FastAPI()
    app.state.market_discovery_service = SimpleNamespace(
        krt=SimpleNamespace(
            catalogue=lambda: [project], status=lambda: {"complete": True, "refreshing": False}
        ),
        build_report=lambda query, **kwargs: calls.append((query, kwargs)) or {
            "subject": {"project_name": "КРТ Тест"}, "peers": [{"name": "ЖК рядом"}]
        },
    )
    install(app)
    client = TestClient(app)
    page = client.get("/auctions")
    assert page.status_code == 200
    assert "Проекты КРТ Москвы" in page.text
    assert "/auctions/krt" in page.text
    answer = client.get("/auctions/krt")
    assert answer.status_code == 200
    assert answer.json()["projects"] == [project]
    assert answer.json()["complete"] is True
    assert client.get("/auctions/krt/test/market").status_code == 401
    market = client.get("/auctions/krt/test/market", headers={"X-Market-Key": "test-key"})
    assert market.status_code == 200
    assert market.json()["peers"][0]["name"] == "ЖК рядом"
    assert calls[0][0] == "krt:test"
    assert calls[0][1]["include_project_totals"] is True
