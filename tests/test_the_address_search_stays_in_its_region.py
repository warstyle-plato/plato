"""Поиск по адресу не уходит в чужой город, а спуск на запасной геокодер слышен.

«Москва Мишина 46 ничего не находил или находил везде, не только в Москве»
(владелец, 30.08.2026). В запросе к Nominatim стоял только `countrycodes=ru`:
города не было вовсе, поэтому улица искалась по всей стране, найденная точка
шла в НСПД и возвращала чужой участок — на экране обычной находкой.

Рядом второе: провайдер без ключа возвращает пустоту, а не ошибку, и падение
на запасной геокодер было неотличимо от плохого адреса.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402


def test_the_region_named_in_the_query_is_recognised() -> None:
    assert core._query_region("Москва Мишина 46")[1] == ("77",)
    assert core._query_region("г. Москва, Саввинская наб 25")[1] == ("77",)
    # Область проверяется раньше города: в «Московской области» есть «Москва»,
    # и обратный порядок отдал бы области московский код.
    assert core._query_region("Московская область, Химки, Ленина 5")[1] == ("50",)
    assert core._query_region("Подмосковье, Мытищи")[1] == ("50",)
    # Не назван — ничего не отсекаем: лучше не проверять, чем отсечь верное.
    assert core._query_region("Мишина 46") is None


def test_a_parcel_from_another_region_is_not_it() -> None:
    """Регион участка написан первыми цифрами номера — сверка тут дармовая."""
    assert core._same_region("77:09:0004014:13", ("77",))
    assert not core._same_region("76:12:0001:5", ("77",))
    assert core._same_region("50:21:0120316:1221", ("50",))
    # Пустой номер и пустой список кодов ничего не отсекают.
    assert core._same_region("", ("77",))
    assert core._same_region("76:12:0001:5", ())


def test_the_city_reaches_the_geocoder_and_filters_its_answer(monkeypatch) -> None:
    """Город из запроса едет условием, а ответ проверяется по себе же."""
    seen: dict[str, str] = {}

    def fake_fetch(url, **kwargs):
        seen["url"] = url
        return [
            {"lat": "55.79", "lon": "37.57", "display_name": "улица Мишина, Москва",
             "address": {"state": "Москва", "road": "улица Мишина"}},
            {"lat": "57.62", "lon": "39.87", "display_name": "улица Мишина, Ярославль",
             "address": {"state": "Ярославская область", "road": "улица Мишина"}},
        ]

    monkeypatch.setattr(core, "_land_fetch_json", fake_fetch)
    monkeypatch.setattr(core, "_nominatim_last_call", 0.0, raising=False)
    got = core._geocode_nominatim("Москва Мишина 46", 5)
    assert "state=" in seen["url"], "город не доехал до геокодера"
    assert "addressdetails=1" in seen["url"], "без подробностей ответ не проверить"
    assert [item["label"] for item in got] == ["улица Мишина, Москва"], \
        "чужой город остался в выдаче"


def test_dropping_to_the_spare_geocoder_is_said_out_loud(monkeypatch) -> None:
    """Провайдер без ключа возвращает пустоту, а не ошибку: молчаливый спуск
    неотличим от плохого адреса."""
    monkeypatch.setattr(core, "_env_str", lambda *a, **k: "")
    monkeypatch.setattr(core, "_GEOCODERS", (
        ("yandex", lambda address, limit: []),
        ("dadata", lambda address, limit: []),
        ("nominatim", lambda address, limit: [{"lat": 55.0, "lng": 37.0,
                                               "label": "точка",
                                               "provider": "OpenStreetMap"}]),
    ))
    found, warnings = core._geocode_address("Москва Мишина 46", 3)
    assert found, "точка не нашлась"
    said = " ".join(warnings)
    assert "OpenStreetMap" in said and "Яндекс" in said and "DaData" in said
    assert "грубее" in said, "не сказано, чем этот ответ хуже"


def test_nothing_is_said_when_the_first_geocoder_answers(monkeypatch) -> None:
    """Оговорка про запасной появляется только когда до него дошло."""
    monkeypatch.setattr(core, "_env_str", lambda *a, **k: "")
    monkeypatch.setattr(core, "_GEOCODERS", (
        ("yandex", lambda address, limit: [{"lat": 55.0, "lng": 37.0,
                                            "label": "точка", "provider": "Яндекс"}]),
    ))
    found, warnings = core._geocode_address("Москва Мишина 46", 3)
    assert found and not warnings
