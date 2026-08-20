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


def test_lzstring_payload_is_unpacked_without_a_dependency() -> None:
    """Карта отвечает сжатым LZ-string; библиотеку ради этого не тянем.

    Образец снят с живого ответа `/api/search/`: первые байты того самого
    FeatureCollection, который страница разжимает у себя в браузере.
    """
    from market_search.pulse import lz_decompress_base64

    sample = "N4IgLgngDgpiBcIBiMCGYCuAnGBhA9gDaEwDGYAlvgHYgA0IAZmpjgM4IDaAugxQCYd4PAL5AAA="
    assert lz_decompress_base64(sample) == '{"type":"FeatureCollection","features":[],"ids":[]}'
    assert lz_decompress_base64("") == ""
    assert lz_decompress_base64("не base64 вовсе") is None


def test_segments_are_read_from_the_class_filter(tmp_path: Path) -> None:
    """Класса нет ни в точке карты, ни в карточке — он существует фильтром.

    Принадлежность выводится из того, что попало в выборку по каждому классу.
    """
    import json as jsonlib

    from market_search.pulse import _CLASS_FILTERS

    answers = {
        "Бизнес": [5924],
        "Премиум": [3372, 1695],
        "Элит/De Luxe": [5504],
        "Комфорт": [],
        "Стандарт/Эконом": [],
    }
    asked: list[int] = []

    def fake_open(path, data=None, headers=None):
        payload = dict(pair.split("=", 1) for pair in data.decode().split("&"))
        import urllib.parse

        body = jsonlib.loads(urllib.parse.unquote_plus(payload["data"]))
        code = body["classes_ppn_list"][0]
        asked.append(code)
        ids = answers[_CLASS_FILTERS[code]]
        # Ответ отдаётся сжатым, но разжатие проверяется отдельным тестом:
        # здесь подменяется уже разжатая ветка.
        return jsonlib.dumps({"features": [{"id": i} for i in ids]}).encode("utf-8")

    client = PulseClient(tmp_path, login="l", password="p")
    client._open = fake_open  # type: ignore[assignment]
    client._cookie = lambda name: "cookie"  # type: ignore[assignment]
    import market_search.pulse as pulse_module

    original = pulse_module.lz_decompress_base64
    pulse_module.lz_decompress_base64 = lambda text: text
    try:
        segments = client.segments()
    finally:
        pulse_module.lz_decompress_base64 = original

    assert sorted(asked) == [1, 2, 3, 4, 5], "спрашиваем каждый класс по разу"
    assert segments == {5924: "Бизнес", 3372: "Премиум", 1695: "Премиум", 5504: "Элит/De Luxe"}
    assert (tmp_path / "segments.json").exists(), "класс складывается на сутки"


def test_balanced_json_survives_nested_braces() -> None:
    text = 'x = {"a": {"b": "}"}, "c": [1,2]}; tail'
    blob = _balanced_json(text, text.index("{"))
    assert json.loads(blob) == {"a": {"b": "}"}, "c": [1, 2]}


def test_the_probe_names_what_the_answer_carries_and_what_we_drop(tmp_path: Path) -> None:
    """«Почему свод по файлу, а не по сайту» — вопрос про цену в общем ответе.

    Разбор карты читает четыре свойства, разбор классов — один `id`. Что ещё
    лежит в тех же ответах, никто не смотрел, и довод «цена только поштучно»
    держался на догадке. Проба называет ключи фактом.
    """
    page = _map_page(
        [
            _feature(3372, "Дом", 55.7, 37.5, developer="Level Group",
                     construction_address="ул. Мишина, д. 17",
                     price_avg=512000, class_ppn="Бизнес"),
            _feature(5924, "Второй", 55.71, 37.43, price_avg=708109),
        ]
    )

    client = PulseClient(tmp_path, login="l", password="p")
    client._open = lambda path, **kwargs: page.encode("utf-8")  # type: ignore[assignment]
    client._cookie = lambda name: "cookie"  # type: ignore[assignment]

    probe = client.probe_fields()
    assert probe["available"] is True
    keys = {row["key"]: row["share_pct"] for row in probe["map"]["keys"]}
    assert keys["name"] == 100
    # Поле, которое есть не у всех, — это исключение, и доля показывает это.
    assert keys["developer"] == 50
    # Главное: то, что приходит и выбрасывается, названо поимённо.
    assert "price_avg" in probe["map"]["unused"]
    assert "class_ppn" in probe["map"]["unused"]
    assert "name" not in probe["map"]["unused"]
    assert probe["map"]["sample"]["price_avg"] == 512000

    # Без доступов проба не выдумывает пустой ответ, а говорит, что выключена.
    off = PulseClient(tmp_path / "off", login="", password="")
    assert off.probe_fields()["available"] is False


def test_suggestions_never_go_to_the_network(tmp_path: Path) -> None:
    """«Подсказки не пришли: 502» на живом стенде.

    Подсказка ходит на каждую вторую букву, а справочник за ней — на страницу
    карты, которая весит мегабайты. Пока кэш свежий, этого не видно; стоит ему
    протухнуть, и первое же нажатие тянет её целиком, ответ не успевает, и
    nginx отдаёт 502 — притом что нужный список лежал на диске часом раньше.
    """
    import json

    client = PulseClient(tmp_path, login="l", password="p")
    (tmp_path / "projects.json").write_text(
        json.dumps([{"complex_id": 7, "name": "Крылатская 33", "developer": "—",
                     "latitude": 55.75, "longitude": 37.41, "address": "Крылатская ул."}],
                   ensure_ascii=False),
        encoding="utf-8",
    )
    (tmp_path / "segments.json").write_text(json.dumps({"7": "Бизнес"}), encoding="utf-8")
    # Кэш нарочно объявлен протухшим: именно в этот момент всё и ломалось.
    client.ttl_seconds = 0

    def forbidden(*args, **kwargs):
        raise AssertionError("подсказка полезла в сеть")

    client._open = forbidden  # type: ignore[assignment]
    client._fetch_projects = forbidden  # type: ignore[assignment]

    found = client.suggest("крыла")
    assert [row["name"] for row in found] == ["Крылатская 33"]
    # Протухший класс тоже берётся с диска: без него сосед в списке безымянный.
    assert found[0]["segment"] == "Бизнес"

    # А путь отчёта за сетью ходить по-прежнему обязан — иначе справочник
    # никогда не обновится.
    fresh_client = PulseClient(tmp_path / "other", login="l", password="p")
    fresh_client._fetch_projects = lambda: []  # type: ignore[assignment]
    assert fresh_client.projects() == []
    assert fresh_client.projects(fetch=False) == []


def test_the_probe_asks_the_source_about_commercial_and_parking(monkeypatch, tmp_path) -> None:
    """«Есть ли в Пульсе коммерция и машино-места» — вопрос владельца 20.08.2026.

    Ответить по коду нельзя: всё, что мы берём, прибито к жилью. Цена
    запрашивается с `object_type: "living"`, в таблице читаются
    `living_count`, `living_area`. Приставка у каждого поля и сам параметр
    говорят, что типы источник различает, — но это признак, а не
    доказательство. Проба спрашивает и печатает ответ.
    """
    from market_search.pulse import PulseClient

    client = PulseClient(tmp_path)
    # `available` — свойство по наличию доступов, поэтому задаём сами доступы.
    monkeypatch.setattr(client, "login", "probe")
    monkeypatch.setattr(client, "password", "probe")

    asked: list[tuple[str, dict]] = []

    def fake_post(path: str, payload: dict):
        asked.append((path, payload))
        if path.endswith("/table/"):
            return {"living_count": 220, "living_area": 13400,
                    "commercial_count": 12, "parking_count": 180,
                    "buildings": [{"id": 1}]}
        kind = payload["opts"]["object_type"]
        if kind == "living":
            return [{"id": 1, "values": [{"month": "2026-07", "value": 708109}]}]
        if kind == "parking":
            return [{"id": 1, "values": [{"month": "2026-07", "value": 2_500_000}]}]
        # Остальные типы источник не знает — и это тоже ответ.
        return []

    monkeypatch.setattr(client, "_post_json", fake_post)
    out = client.probe_object_types(1)

    assert out["available"] is True
    # Спросили каждый тип, а не только жильё.
    kinds = [payload["opts"]["object_type"] for path, payload in asked
             if "price-dynamic-chart" in path]
    assert "living" in kinds and "commercial" in kinds and "parking" in kinds
    # Ответ по типам: где числа есть, где нет.
    assert out["by_object_type"]["living"]["points"] == 1
    assert out["by_object_type"]["parking"]["sample"]["value"] == 2_500_000
    assert out["by_object_type"]["commercial"]["points"] == 0
    # Сырые ключи таблицы отвечают на вопрос без интерпретации.
    assert "commercial_count" in out["table_keys"]
    assert "parking_count" in out["table_keys"]
    # Списки и словари в образец не идут: проба должна читаться, а не листаться.
    assert "buildings" not in out["table_sample"]

    # Источник выключен — так и сказано, а не пустой ответ, читаемый как «нет».
    monkeypatch.setattr(client, "login", "")
    monkeypatch.setattr(client, "password", "")
    monkeypatch.setattr(client, "_cookie", lambda name: None)
    assert client.probe_object_types(1)["available"] is False
