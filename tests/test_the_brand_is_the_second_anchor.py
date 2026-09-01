"""Площадку знают по имени проекта, а не по адресу.

«По улице Маршала Воробьева 12 не показывает, что оно обещано кому-то, а там же
Строгино 360 и это ПИК» (владелец, 01.09.2026). Проверка по источникам
показала, что «Строгино 360» — действительно ПИК, но стоит он на улице Маршала
ПРОШЛЯКОВА: в реестре это отдельная площадка «Маршала Прошлякова ул., вл. 9»
(69,73 га, 580 096 м² жилья — числа сходятся с публикацией один в один).

Но в самом разборе нашлись две настоящие поломки, и обе теряли находку молча.

Первая: разбиение на предложения рвалось на сокращении. «Маршала Прошлякова
ул., вл. 9» разваливалось надвое, адрес уезжал в одно предложение, признак — в
другое, и правило «в одном предложении» не срабатывало НИ РАЗУ на адресе с
«вл.» — то есть почти на любом адресе КРТ.

Вторая: якорем служил только адрес. Статья, где сказано «Строгино 360» и «ПИК»
и нет адреса, к площадке не привязывалась вовсе. Имя проекта берётся из той
публикации, где оно стоит рядом с адресом, — и дальше работает вторым якорем.

Запуск: python3 -m pytest tests/test_the_brand_is_the_second_anchor.py -q
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from market_search.krt_open_sources import (  # noqa: E402
    _sentences, brand_names, read_findings)


@dataclass
class Doc:
    title: str
    snippet: str
    url: str = "https://www.mos.ru/news/item/1/"
    domain: str = "mos.ru"
    rank: int = 1


SITE = "Маршала Прошлякова ул., вл. 9"
WITH_ADDRESS = Doc(
    title="КРТ в Строгино",
    snippet=("На улице Маршала Прошлякова, вл. 9 группа ПИК построит жилой "
             "комплекс «Строгино 360»."))
BRAND_ONLY = Doc(
    title="«Строгино 360» выходит на рынок",
    snippet="Оператором «Строгино 360» выступает группа ПИК.")
STRANGER = Doc(
    title="«Чужой квартал»",
    snippet="Оператором «Чужого квартала» выступает ООО «Не наше».",
    domain="example.com")


def test_a_dot_after_an_abbreviation_does_not_end_the_sentence():
    parts = _sentences("Строгино. На улице Маршала Прошлякова, вл. 9 построит ПИК.")
    assert len(parts) == 2, f"фраза разорвана: {parts}"
    assert "вл. 9" in parts[1] and "Прошлякова" in parts[1]
    # Число после точки — тоже не начало фразы: «тыс. кв. м», «д. 5 стр. 2».
    assert len(_sentences("Площадь 951 тыс. кв. м. Жильё 580 тыс.")) == 2


def test_the_brand_is_taken_only_next_to_the_address():
    assert brand_names([WITH_ADDRESS], SITE) == ["Строгино 360"]
    # Имя из предложения без адреса — это чужой проект, а не наш бренд.
    assert brand_names([BRAND_ONLY], SITE) == []
    assert brand_names([STRANGER], SITE) == []


def test_the_brand_attaches_the_article_that_never_names_the_address():
    got = read_findings([WITH_ADDRESS, BRAND_ONLY], SITE)
    assert got["brands"] == ["Строгино 360"]
    assert got["operator_named"], "оператор из статьи про бренд не подхвачен"
    assert "ПИК" in got["operator_named"][0]["name"]
    assert got["taken"] is True


def test_a_stranger_brand_does_not_bring_its_operator():
    got = read_findings([WITH_ADDRESS, STRANGER], SITE)
    assert all("Не наше" not in one["name"] for one in got["operator_named"]), \
        "чужой проект приписал нашей площадке своего оператора"


def test_the_route_asks_the_brand_in_a_second_round():
    source = (ROOT / "auction_search" / "api.py").read_text(encoding="utf-8")
    block = source[source.index('"/auctions/krt/{slug}/open-sources"'):]
    block = block[:block.index('@app.get("/auctions/krt/{slug}/card-facts")')]
    assert 'found.get("brands")' in block, "второй круг по имени проекта не идёт"
    assert "[:1]" in block, "поиск платный — кругов должно быть не больше одного"
