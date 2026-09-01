"""У площадки бывает несколько адресов, и спрашивать надо по каждому.

Владелец показал Алису на «ул. Удальцова, влд. 75А, ул. Веерная, влд. КРТ кто
строит» (01.09.2026). Наш запрос склеивал оба адреса в одну строку —
«ул. Удальцова 75А ул. Веерная 1», — а такой строки нет ни в одной публикации:
поиск отвечает про что угодно.

Запуск: python3 -m pytest tests/test_a_site_with_two_addresses_is_asked_twice.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from market_search import krt_open_sources as sources  # noqa: E402


def test_two_addresses_become_two_addresses() -> None:
    got = sources.search_addresses("ул. Удальцова, влд. 75А, ул. Веерная, влд. 1")
    assert got == ["ул. Удальцова 75А", "ул. Веерная 1"]


def test_one_address_is_not_torn_apart_by_its_own_commas() -> None:
    """«Молдавская ул., вл. 3-5» — один адрес: тип улицы стоит ПОСЛЕ имени."""
    assert sources.search_addresses("Молдавская ул., вл. 3-5") == ["Молдавская ул. 3-5"]
    assert sources.search_addresses("Светлый проезд, вл. 3") == ["Светлый проезд 3"]
    assert sources.search_addresses("Маршала Прошлякова ул., вл. 9") == [
        "Маршала Прошлякова ул. 9"]


def test_every_address_gets_its_own_question() -> None:
    asked = sources.queries("ул. Удальцова, влд. 75А, ул. Веерная, влд. 1",
                            "ЗАО", "Проспект Вернадского")
    assert any("ул. Удальцова 75А Москва" in q for q in asked)
    assert any("ул. Веерная 1 Москва" in q for q in asked)
    # Склеенного адреса быть не должно ни в одном запросе.
    assert not any("Удальцова 75А ул. Веерная" in q for q in asked)


def test_the_price_of_a_long_name_is_capped() -> None:
    """Поиск платный: площадка с пятью адресами не стоит впятеро дороже."""
    long_name = ", ".join(f"ул. Тестовая{i}, вл. {i}" for i in range(1, 6))
    assert len(sources.search_addresses(long_name)) == 5
    assert len(sources.queries(long_name, "ЮАО", "Нагатино")) <= 5
    assert len(sources.telegram_queries(long_name)) <= 2


def test_a_channel_is_asked_by_each_address_too() -> None:
    asked = sources.telegram_queries("ул. Удальцова, влд. 75А, ул. Веерная, влд. 1")
    assert len(asked) == 2
    assert all(q.startswith("site:t.me") for q in asked)
    # Доказанное имя проекта сильнее адреса: его знают, а адрес — нет.
    assert sources.telegram_queries("ул. Удальцова, влд. 75А", ["Строгино 360"]) == [
        'site:t.me "Строгино 360" КРТ застройщик оператор']
