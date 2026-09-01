"""Каналы спрашиваются тем же поиском, а их находки называются каналами.

Владелец (01.09.2026): «а поиск информации можно через телеграм-каналы ещё
вести?». Можно, и своего пути наружу для этого заводить не надо: платный индекс
понимает ограничение по домену, и круг по `site:t.me` — это тот же поиск, что
и по прессе. Правила находки не смягчаются: цитата, ссылка и якорь площадки в
том же предложении.

Разница в одном, и она обязана быть видна: канал — не издание. Пост пишет кто
угодно, опровергать его никто не обязан, а на экране он встал бы рядом с
mos.ru и выглядел бы так же. Поэтому у находки стоит происхождение, а «каналы
спрошены и там пусто» отличается от «каналы не спрошены» — это то же правило,
по которому пустой ответ НСПД не выдаётся за отсутствие ограничений.

Запуск: python3 -m pytest tests/test_a_channel_is_not_a_publication.py -q
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from auction_search import ui  # noqa: E402
from market_search import krt_open_sources  # noqa: E402

NAME = "Маршала Воробьева ул., вл. 12"


@dataclass
class Doc:
    title: str
    url: str
    domain: str
    snippet: str
    rank: int = 1


def test_the_channel_round_is_asked_by_the_project_name_when_it_is_proven():
    asked = krt_open_sources.telegram_queries(NAME, ["Строгино 360"])
    assert asked == ['site:t.me "Строгино 360" КРТ застройщик'], asked


def test_without_a_proven_name_the_channel_round_falls_back_to_the_address():
    """Адрес — в человеческом виде: «вл.» пишет каталог, а не канал."""
    asked = krt_open_sources.telegram_queries(NAME, [])
    assert len(asked) == 1 and "site:t.me" in asked[0]
    assert "Маршала Воробьева" in asked[0]
    assert "вл." not in asked[0], "канцелярское сокращение уехало в запрос к каналам"
    assert krt_open_sources.telegram_queries("", []) == []


def test_a_finding_from_a_channel_says_so():
    docs = [
        Doc(title="Строгино 360",
            url="https://t.me/some_channel/1201",
            domain="t.me",
            snippet="Застройщиком проекта на Маршала Воробьева, вл. 12 выступает ПАО «ПИК»."),
        Doc(title="Городские новости",
            url="https://www.mos.ru/news/item/1",
            domain="www.mos.ru",
            snippet="Территория по адресу Маршала Воробьева, вл. 12 включена в программу реновации."),
    ]
    found = krt_open_sources.read_findings(docs, NAME)
    items = (found["operator_named"] + found["operator_appointed"]
             + found["operator_pending"] + found["city_needs"] + found["stage"])
    assert items, "находок нет вовсе — проверять нечего"
    from_channel = [i for i in items if i["domain"] == "t.me"]
    assert from_channel, "находка из канала не дошла"
    assert all(i["telegram"] for i in from_channel), \
        "находка из канала не помечена как канал — на экране она встанет вровень с mos.ru"
    assert all(not i["telegram"] for i in items if i["domain"] != "t.me"), \
        "меткой канала помечено издание"
    assert found["telegram_found"] == len(from_channel)


def test_a_publication_is_never_marked_as_a_channel():
    docs = [Doc(title="Ведомости", url="https://www.vedomosti.ru/1", domain="vedomosti.ru",
                snippet="Застройщиком проекта на Маршала Воробьева, вл. 12 выступает ПАО «ПИК».")]
    found = krt_open_sources.read_findings(docs, NAME)
    assert found["telegram_found"] == 0


def test_the_screen_tells_an_empty_answer_from_an_unasked_one():
    page = ui.auctions_page(None)
    assert "telegram_asked" in page, "экран не различает «каналы не спрошены» и «в них пусто»"
    assert "телеграм-канал, не издание" in page, \
        "происхождение находки из канала на экране не названо"
