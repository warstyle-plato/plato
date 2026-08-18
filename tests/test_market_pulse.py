"""Провайдер «Пульс Продаж Новостроек».

Сети в тестах нет: сайт подменяется, потому что проверяется разбор и поведение
при отказе, а не доступность чужого сервиса.
"""

from __future__ import annotations

import json
from pathlib import Path

from market_search.pulse import PulseClient, PulseProject, _balanced_json


def _map_page(features: list[dict]) -> str:
    """Страница карты: GeoJSON лежит в ней присваиванием посреди скрипта."""
    collection = json.dumps(
        {"type": "FeatureCollection", "features": features}, ensure_ascii=False
    ).replace('{"type": "FeatureCollection"', '{"type":"FeatureCollection"')
    return (
        "<html><script>var polygons = {\"14\":{\"name\":\"го Дмитровский\"}};\n"
        f"var search = {collection};\n"
        "var tail = {\"unrelated\": true};</script></html>"
    )


def _feature(fid: int, name: str, lat: float, lon: float, **props) -> dict:
    return {
        "type": "Feature",
        "id": fid,
        "geometry": {"type": "Point", "coordinates": [lat, lon]},
        "properties": {"name": name, **props},
    }


def test_credentials_absent_is_not_a_failure(tmp_path: Path) -> None:
    """Источник без доступов просто выключен — поведение прежнее."""
    client = PulseClient(tmp_path, login="", password="")
    assert client.available is False
    assert client.projects() == []
    assert client.near(55.73, 37.56, 3.0) == []
    assert client.sign_in() is False


def test_project_index_is_read_from_the_map_page(tmp_path: Path) -> None:
    """Данные всех проектов лежат в самой странице карты, а не в API."""
    page = _map_page(
        [
            _feature(
                3372,
                "Саввинская 17",
                55.73445,
                37.56574,
                developer="Level Group",
                zastroychik='ООО "СЗ "Инвест Менеджмент Групп"',
                construction_address="Москва, ЦАО, Хамовники, Саввинская набережная, д. 17",
            ),
            _feature(5924, "Кутузов Сити", 55.72564, 37.42891, developer="МДС-ГРУПП"),
            # Битую запись без координат пропускаем молча: это не проект.
            {"type": "Feature", "id": 1, "geometry": {}, "properties": {"name": "мусор"}},
        ]
    )

    client = PulseClient(tmp_path, login="l", password="p")
    client._open = lambda path, **kwargs: page.encode("utf-8")  # type: ignore[assignment]
    client._cookie = lambda name: "cookie"  # type: ignore[assignment]

    projects = client.projects()
    assert [item.complex_id for item in projects] == [3372, 5924]
    first = projects[0]
    assert first.developer == "Level Group"
    assert first.address.endswith("д. 17")
    assert first.to_dict()["url"] == "https://pulsprodaj.ru/complex/3372/"

    # Второй вызов идёт с диска: справочник на три с половиной тысячи проектов
    # незачем тянуть на каждый запрос, а воркеров два.
    assert (tmp_path / "projects.json").exists()


def test_radius_is_measured_not_guessed(tmp_path: Path) -> None:
    """Расстояние считаем сами, от координат проекта."""
    client = PulseClient(tmp_path, login="l", password="p")
    client._projects = [
        PulseProject(3372, "Саввинская 17", 55.73445, 37.56574),
        PulseProject(5924, "Кутузов Сити", 55.72564, 37.42891),
    ]
    near = client.near(55.7295, 37.5665, 3.0)
    assert [item.name for _, item in near] == ["Саввинская 17"]
    distance = near[0][0]
    assert 0.4 <= distance <= 0.7, distance


def test_price_carries_its_date_and_sample(tmp_path: Path) -> None:
    """Цена без даты и числа лотов — это не цена, а число.

    У «Манифеста» прайс от 2022 года, у ИНДИВО — сегодняшний. Прежде такое
    различить было нечем, и устаревшая цена шла в ориентир наравне со свежей.
    """
    client = PulseClient(tmp_path, login="l", password="p")
    client._post_json = lambda path, payload: {  # type: ignore[assignment]
        "current_price": {
            "price_date": "2026-08-12T12:00:00",
            "flat_sqm_price": 2_948_528,
            "flat_sqm_price_min": 2_558_316,
            "flat_sqm_price_max": 3_402_527,
            "flat_lot_count": 4.0,
            "flat_lot_area": 109,
        }
    }
    price = client.price(3372)
    assert price == {
        "price_per_sqm": 2_948_528,
        "price_per_sqm_min": 2_558_316,
        "price_per_sqm_max": 3_402_527,
        "lot_count": 4,
        "lot_area_avg": 109,
        "observed_at": "2026-08-12",
        "source": "Пульс Продаж Новостроек",
        "basis": "pulse_price_list_average",
    }


def test_empty_price_is_none_not_zero(tmp_path: Path) -> None:
    """У сданного и распроданного дома прайса нет — это не нулевая цена."""
    client = PulseClient(tmp_path, login="l", password="p")
    client._post_json = lambda path, payload: {  # type: ignore[assignment]
        "current_price": {"price_date": "2026-08-18T12:00:00", "flat_sqm_price": 0}
    }
    assert client.price(3043) is None


def test_network_failure_is_silent(tmp_path: Path) -> None:
    """Отказ сети — это «данных нет», а не исключение в расчёте."""
    def boom(*args, **kwargs):
        raise OSError("сеть недоступна")

    client = PulseClient(tmp_path, login="l", password="p")
    client._open = boom  # type: ignore[assignment]
    assert client.projects() == []
    assert client.diagnostics()["errors"], "отказ должен быть виден в диагностике"


def test_balanced_json_survives_nested_braces() -> None:
    text = 'x = {"a": {"b": "}"}, "c": [1,2]}; tail'
    blob = _balanced_json(text, text.index("{"))
    assert json.loads(blob) == {"a": {"b": "}"}, "c": [1, 2]}
