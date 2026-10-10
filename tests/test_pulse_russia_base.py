"""Всероссийский кабинет «Пульса»: свой поддомен, номер с кодом региона.

Подписка на всю Россию открывает карту на `russia.pulsprodaj.ru`, а номер
проекта там выглядит как «50-004184». Прежний код приводил id к `int` и
держал один кэш на все базы: такой номер ронял справочник целиком, а
московский кэш выдавался бы за всероссийский.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from market_search import pulse as pulse_module
from market_search.pulse import (
    PulseClient,
    PulseNetwork,
    address_region,
    make_pulse_client,
    parse_bases,
    pulse_id,
    pulse_region,
)

RUSSIA = "https://russia.pulsprodaj.ru"
MOSCOW = "https://pulsprodaj.ru"


def _map_page(features: list[dict]) -> str:
    collection = json.dumps(
        {"type": "FeatureCollection", "features": features}, ensure_ascii=False, separators=(",", ":")
    )
    return f"<html><script>var data = {collection};</script></html>"


def _feature(fid, name, lat, lon, address):
    return {
        "type": "Feature",
        "id": fid,
        "geometry": {"type": "Point", "coordinates": [lat, lon]},
        "properties": {"name": name, "construction_address": address},
    }


def _client(tmp_path: Path, base: str, page: str) -> PulseClient:
    client = PulseClient(tmp_path, login="l", password="p", base=base)
    client._open = lambda path, **kwargs: page.encode("utf-8")  # type: ignore[assignment]
    client._cookie = lambda name: "cookie"  # type: ignore[assignment]
    return client


def test_the_id_is_a_string_and_the_region_is_read_only_from_the_full_format() -> None:
    assert pulse_id("50-004184") == "50-004184"
    assert pulse_region("50-004184") == "50"
    # Старые числовые id дают ту же строку — сохранённые проекты находятся.
    assert pulse_id(4184) == pulse_id("4184") == pulse_id(4184.0) == "4184"
    assert pulse_region(4184) is None
    # Код региона не выводится из чего попало.
    assert pulse_region("50-ab") is None
    assert pulse_region("x50-004184") is None
    assert pulse_id(None) is None and pulse_id("") is None and pulse_id(True) is None
    assert pulse_module._api_id("4184") == 4184
    assert pulse_module._api_id("50-004184") == "50-004184"


def test_a_regional_number_no_longer_drops_the_catalog(tmp_path: Path) -> None:
    page = _map_page([
        _feature("50-004184", "Одинцовские Кварталы", 55.66, 37.21,
                 "Московская область, Одинцовский г.о., д. Солманово"),
        _feature("50-001200", "Мытищи Парк", 55.91, 37.73, "Московская обл, г. Мытищи"),
    ])
    client = _client(tmp_path, RUSSIA, page)
    projects = client.projects()
    assert [item.complex_id for item in projects] == ["50-004184", "50-001200"]
    assert projects[0].region == "50"
    assert projects[0].to_dict()["url"] == f"{RUSSIA}/complex/50-004184/"
    assert client.project("50-004184").name == "Одинцовские Кварталы"
    assert [row["name"] for row in client.suggest("мытищ")] == ["Мытищи Парк"]


def test_the_catalog_cache_is_kept_per_base(tmp_path: Path) -> None:
    moscow = _client(tmp_path, MOSCOW, _map_page([_feature(7, "Крылатская 33", 55.75, 37.41, "г Москва")]))
    assert [item.complex_id for item in moscow.projects()] == ["7"]

    # Всероссийский клиент рядом с тёплым московским кэшем не видит его как свой.
    russia = PulseClient(tmp_path, login="l", password="p", base=RUSSIA)
    assert russia.dir != moscow.dir
    assert russia.projects(fetch=False) == []
    assert (tmp_path / "pulsprodaj.ru" / "projects.json").exists()
    assert not (tmp_path / "russia.pulsprodaj.ru" / "projects.json").exists()


def test_two_bases_merge_into_one_catalog_and_details_go_to_the_owner(tmp_path: Path) -> None:
    russia = _client(tmp_path, RUSSIA, _map_page([
        _feature("50-004184", "Одинцовские Кварталы", 55.66, 37.21, "Московская область"),
        _feature(7, "Крылатская 33", 55.75, 37.41, "г Москва"),
        _feature(9, "Чужой с тем же номером", 59.93, 30.31, "г Санкт-Петербург"),
    ]))
    moscow = _client(tmp_path, MOSCOW, _map_page([
        _feature(7, "Крылатская 33", 55.7501, 37.4101, "г Москва"),
        _feature(9, "Московский девятый", 55.80, 37.60, "г Москва"),
        _feature(11, "Только в Москве", 55.70, 37.50, "г Москва"),
    ]))
    network = PulseNetwork([russia, moscow])
    ids = [(item.complex_id, item.base) for item in network.projects()]
    assert ids == [("50-004184", RUSSIA), ("7", RUSSIA), ("9", RUSSIA), ("11", MOSCOW)]
    assert network.duplicates == 1, "тот же проект в двух базах — один"
    assert len(network.conflicts) == 1, "один номер у разных проектов не прячется"
    assert network.conflicts[0]["dropped"]["name"] == "Московский девятый"

    asked: list[tuple[str, str]] = []
    russia.price = lambda cid: (asked.append((RUSSIA, cid)), {"price_per_sqm": 1})[1]  # type: ignore[assignment]
    moscow.price = lambda cid: (asked.append((MOSCOW, cid)), {"price_per_sqm": 2})[1]  # type: ignore[assignment]
    assert network.price("11") == {"price_per_sqm": 2}
    assert network.price("50-004184") == {"price_per_sqm": 1}
    # Старый числовой id из сохранённого проекта находит своего владельца.
    assert network.price(11) == {"price_per_sqm": 2}
    assert asked == [(MOSCOW, "11"), (RUSSIA, "50-004184"), (MOSCOW, 11)]

    report = network.catalog_report()
    assert report["projects"] == 4
    assert [row["base"] for row in report["bases"]] == [RUSSIA, MOSCOW]
    assert report["bases"][0]["by_id_region"] == {"без кода в номере": 2, "50": 1}
    assert report["bases"][0]["id_format"] == {"регион-номер": 1, "число": 2, "иное": 0}


def test_price_history_sends_each_id_in_its_own_form(tmp_path: Path) -> None:
    client = PulseClient(tmp_path, login="l", password="p", base=RUSSIA)
    sent: list[list] = []

    def fake_post(path, payload):
        sent.append(payload["ids"])
        return [{"id": "50-004184", "values": [{"month": "2026-09-01", "value": 300000}]},
                {"id": 4184, "values": [{"month": "2026-09-01", "value": 200000}]}]

    client._post_json = fake_post  # type: ignore[assignment]
    series = client.price_history(["50-004184", 4184])
    assert sent == [["50-004184", 4184]]
    assert set(series) == {"50-004184", "4184"}


def test_make_pulse_client_reads_the_list_of_bases(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PULSE_BASE_URL", f"{RUSSIA}/, {MOSCOW}")
    assert parse_bases(f"{RUSSIA}/, {MOSCOW}") == [RUSSIA, MOSCOW]
    network = make_pulse_client(tmp_path)
    assert isinstance(network, PulseNetwork)
    assert [site.base for site in network.sites] == [RUSSIA, MOSCOW]

    monkeypatch.setenv("PULSE_BASE_URL", RUSSIA)
    single = make_pulse_client(tmp_path)
    assert isinstance(single, PulseClient) and single.base == RUSSIA

    monkeypatch.delenv("PULSE_BASE_URL")
    assert make_pulse_client(tmp_path).base == MOSCOW


@pytest.mark.parametrize(
    ("address", "region"),
    [
        ("Московская область, г.о. Мытищи, ул. Колпакова", "Московская область"),
        ("Московская обл, Одинцовский г.о., д. Солманово", "Московская область"),
        ("г Москва, Варшавское шоссе, д 37", "Москва"),
        ("г. Санкт-Петербург, Невский пр.", "Санкт-Петербург"),
        ("ул. Ленина, д. 1", None),
        ("Москва, Варшавское шоссе, д 37", "Москва"),
        ("Краснодарский край, г. Сочи", "Краснодарский край"),
        ("Республика Татарстан, г. Казань", "Республика Татарстан"),
        (None, None),
    ],
)
def test_the_address_region_is_only_a_diagnostic_label(address, region) -> None:
    assert address_region(address) == region


def test_the_catalog_route_finds_mytishchi_and_asks_its_price(monkeypatch, tmp_path: Path) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from market_search.api import install

    cache = tmp_path / "market" / "pulse" / "russia.pulsprodaj.ru"
    cache.mkdir(parents=True)
    (cache / "projects.json").write_text(json.dumps([
        {"complex_id": "50-001200", "name": "Мытищи Парк", "latitude": 55.91, "longitude": 37.73,
         "address": "Московская область, г.о. Мытищи"},
        {"complex_id": "77-000007", "name": "Крылатская 33", "latitude": 55.75, "longitude": 37.41,
         "address": "Москва, Крылатская ул."},
    ], ensure_ascii=False), encoding="utf-8")

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MARKET_CABINET_KEY", "stand-key-2026")
    monkeypatch.setenv("PULSE_BASE_URL", RUSSIA)
    monkeypatch.setenv("PULSE_LOGIN", "l")
    monkeypatch.setenv("PULSE_PASSWORD", "p")
    monkeypatch.setattr(PulseClient, "price", lambda self, cid: {"price_per_sqm": 251000, "observed_at": "2026-10-01"})
    monkeypatch.setattr(PulseClient, "remaining", lambda self, cid: {"remaining_units": 120})
    app = FastAPI()
    install(app)
    opened = TestClient(app, headers={"X-Market-Key": "stand-key-2026"})

    report = opened.get("/market/pulse/catalog", params={"q": "Мытищи", "check": 1}).json()
    base = report["bases"][0]
    assert base["base"] == RUSSIA and base["projects"] == 2
    assert base["by_id_region"] == {"50": 1, "77": 1}
    assert base["by_address_region"] == {"Москва": 1, "Московская область": 1}
    assert base["catalog"]["updated_at"]
    assert report["configured"] == "PULSE_BASE_URL"
    assert report["query"]["items"][0]["complex_id"] == "50-001200"
    check = report["query"]["check"]
    assert check["ok"] is True and check["price_per_sqm"] == 251000 and check["remaining_units"] == 120

    # Строковый id проходит и в маршрут одного проекта: прежде он был `int`.
    monkeypatch.setattr(PulseClient, "metrics", lambda self, cid: {})
    monkeypatch.setattr(PulseClient, "project_totals", lambda self, cid: {})
    monkeypatch.setattr(PulseClient, "price_history", lambda self, ids, months=12: {})
    monkeypatch.setattr(PulseClient, "segments", lambda self, **kw: {})
    row = opened.get("/market/project/50-001200")
    assert row.status_code == 200, row.text
    assert row.json()["name"] == "Мытищи Парк"


def test_the_map_probe_reads_the_spa_bundle_for_its_endpoints(tmp_path: Path) -> None:
    """Всероссийская карта — SPA: страница пустая, адреса данных — в скрипте."""
    shell = '<html><head><title>Пульс</title><script type="module" src="/assets/index-P_cxj_7a.js"></script></head></html>'
    bundle = ('const c=axios.create({baseURL:"/api/v2"});c.get("map/complexes/");'
              'fetch(`/api/complex/${id}/price_stats/`);x="/assets/logo.svg"')
    client = PulseClient(tmp_path, login="l", password="p", base=RUSSIA)
    client._cookie = lambda name: "cookie"  # type: ignore[assignment]
    client._open = lambda path, **kwargs: (bundle if path.endswith(".js") else shell).encode("utf-8")  # type: ignore[assignment]
    page, index = client._read_map()
    assert index < 0
    found = client.map_probe[0]["bundles"][0]
    assert found["script"] == "/assets/index-P_cxj_7a.js"
    assert "/api/complex/${id}/price_stats/" in found["paths"]
    assert found["base_urls"] == ["/api/v2"] and "map/complexes/" in found["relative"]
    assert "/assets/logo.svg" not in found["paths"]
