"""Поиск по адресу не уходит из названного региона — и не ломается об это.

«Москва Мишина 46 ничего не находил или находил везде, не только в Москве»
(владелец, 30.08.2026, повторно 31.08.2026 — «он так и не работает»).

Первая правка добавила Nominatim параметр `state`. Живой ответ портала
(31.08.2026): `q` вместе со структурным `state` — это **400 Bad Request**.
Свободный и структурный запросы у Nominatim не совмещаются, и запасной
геокодер начал падать ровно на тех запросах, ради которых сужение и делалось:
на всех, где названа Москва или область. «Находил везде» сменилось на «не
находил ничего», и это была та же правка.

Отсюда три правила, и каждое проверяется здесь.

- **Регион проверяется по ОТВЕТУ, а не сужается запросом.** Каждый провайдер
  свой регион объявляет сам: DaData — «г Москва», Nominatim — `address.state`.
- **Правило одно на всю лесенку.** Отсев стоял внутри Nominatim, а DaData
  отвечает раньше: до последней ступени дело обычно не доходит вовсе.
- **Сверять регион подстрокой нельзя:** «москва» входит в «московская», и
  Подмосковье проходило московский отсев целиком.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import main_legacy  # noqa: E402


def _candidate(label: str, region: str) -> dict[str, Any]:
    return {"lat": 55.0, "lng": 37.0, "label": label, "region": region,
            "provider": "DaData"}


def _ladder(monkeypatch, *providers) -> None:
    monkeypatch.setattr(main_legacy, "_GEOCODERS",
                        tuple((f"stub{i}", p) for i, p in enumerate(providers)))


def test_the_free_form_query_never_carries_a_structured_region(monkeypatch) -> None:
    """`q` и `state` вместе — 400 от Nominatim, то есть геокодера нет вовсе.

    Проверяется собранный адрес запроса: именно он и был поломкой.
    """
    asked: list[str] = []

    def fetch(url: str, **kwargs: Any) -> Any:
        asked.append(url)
        return []

    monkeypatch.setattr(main_legacy, "_land_fetch_json", fetch)
    monkeypatch.setattr(main_legacy, "_nominatim_last_call", 0.0)
    main_legacy._geocode_nominatim("Москва Мишина 46", 3)
    assert asked, "запрос к геокодеру не собрался"
    url = asked[0]
    assert "q=" in url
    for structured in ("state=", "city=", "street=", "county="):
        assert structured not in url, (
            f"структурный параметр {structured} рядом с q — Nominatim ответит 400")


def test_the_region_is_read_from_the_answer_not_forced_on_the_query(monkeypatch) -> None:
    """Регион находки объявляет сама находка, и чужая отбрасывается."""
    def dadata(address: str, limit: int) -> list[dict[str, Any]]:
        return [_candidate("г Москва, ул Мишина, д 46", "г Москва"),
                _candidate("г Нижний Новгород, ул Мишина, д 46", "Нижегородская обл")]

    _ladder(monkeypatch, dadata)
    found, _ = main_legacy._geocode_address("Москва Мишина 46", 3)
    assert [item["label"] for item in found] == ["г Москва, ул Мишина, д 46"]


def test_the_rule_holds_on_the_first_rung_not_only_the_last(monkeypatch) -> None:
    """DaData отвечает раньше Nominatim — отсев обязан работать и там.

    Проверка жила внутри Nominatim, и до неё в норме не доходило: «находил
    везде» оставалось верным при исправном DaData.
    """
    def dadata(address: str, limit: int) -> list[dict[str, Any]]:
        return [_candidate("г Тула, ул Мишина", "Тульская обл")]

    reached: list[str] = []

    def nominatim(address: str, limit: int) -> list[dict[str, Any]]:
        # Чужое у первой ступени — не ответ: спуск к следующей верен, она
        # может найти нужное. Проверяется не то, что спуска нет, а то, что
        # чужая находка первой ступени за ответ не выдана.
        reached.append(address)
        return []

    _ladder(monkeypatch, dadata, nominatim)
    found, warnings = main_legacy._geocode_address("Москва Мишина 46", 3)
    assert found == []
    assert reached, "лесенка остановилась на чужой находке"
    assert any("вне «Москва»" in text for text in warnings), warnings
    # Отсечённое называется: молча выброшенная находка читается как её
    # отсутствие, и человек не знает, что менять в запросе.
    assert any("Тула" in text for text in warnings), warnings


def test_the_region_moscow_does_not_swallow_the_oblast(monkeypatch) -> None:
    """«москва» — подстрока «московская», и подстрочный отсев их не различал."""
    def both(address: str, limit: int) -> list[dict[str, Any]]:
        return [_candidate("Московская обл, г Химки, ул Ленина, д 1", "Московская обл"),
                _candidate("г Москва, ул Ленина", "г Москва")]

    _ladder(monkeypatch, both)
    city, _ = main_legacy._geocode_address("Москва, Ленина 1", 3)
    assert [item["label"] for item in city] == ["г Москва, ул Ленина"]
    oblast, _ = main_legacy._geocode_address("МО, Химки, Ленина 1", 3)
    assert [item["label"] for item in oblast] == [
        "Московская обл, г Химки, ул Ленина, д 1"]


def test_no_region_named_filters_nothing(monkeypatch) -> None:
    """Регион не назван — сужать не по чему, и выдумывать его нельзя."""
    def dadata(address: str, limit: int) -> list[dict[str, Any]]:
        return [_candidate("г Москва, ул Мишина, д 46", "г Москва"),
                _candidate("г Нижний Новгород, ул Мишина, д 46", "Нижегородская обл")]

    _ladder(monkeypatch, dadata)
    found, _ = main_legacy._geocode_address("Мишина 46", 3)
    assert len(found) == 2


def test_an_undeclared_region_is_judged_by_the_label() -> None:
    """Провайдер региона не назвал — судим по подписи, но по границе слова."""
    marks = main_legacy._query_region("Москва")[1]
    assert main_legacy._in_region({"label": "46, Мишина улица, Москва, Россия"}, marks)
    assert not main_legacy._in_region(
        {"label": "1, Ленина, Химки, Московская область"}, marks)


def test_the_region_is_recognised_in_the_wordings_people_type() -> None:
    """Метка ищется по границе слова: «Химки, МО» опознаётся, Ярославль — нет."""
    def name(query: str) -> str | None:
        got = main_legacy._query_region(query)
        return got[0] if got else None

    assert name("Москва Мишина 46") == "Москва"
    assert name("г. Москва, ул. Мишина, 46") == "Москва"
    assert name("Московская область, Красногорск") == "Московская область"
    assert name("Химки, МО") == "Московская область"
    assert name("Подмосковье, Одинцово") == "Московская область"
    # Ни улица, ни чужой город регионом не становятся.
    assert name("Московский проспект, Ярославль") is None
    assert name("Санкт-Петербург, Невский 1") is None
    assert name("Мишина 46") is None
