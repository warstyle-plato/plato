"""Ту же компанию называют другими словами — и все они значат одно.

Владелец прислал две публикации о КРТ на Светлом проезде, вл. 4 (01.09.2026),
и фильтр не считал площадку занятой ни по одной из них. Причина не в якоре и не
в поиске: в обоих текстах слова «застройщик» нет вовсе.

    «Компания «КС-Про», на 30% принадлежащая головной организации девелопера
    STONE — АО «Стоунхедж», проводит инженерно-геодезические работы на участке
    по адресу: Светлый проезд, вл. 4.»   (t.me/livesokol)

    «ЖК от STONE на Светлый проезд, 4»   (dzen.ru, 15.12.2025)

Первое — «девелопер», которого не было в наших словах. Второе — другая форма
целиком: имя стоит ПЕРЕД адресом, и хвостовой разбор («что написано после
слова «оператор») его не достаёт вовсе.

Имя при этом берётся только доказанное: «ЖК от застройщика» — это роль, а не
компания, и именем не становится. Регистр здесь значащий, поэтому у имени он не
игнорируется — под общим `(?i)` «застройщика» проходило как имя.

Запуск: python3 -m pytest tests/test_a_developer_is_named_by_other_words_too.py -q
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from market_search import krt_open_sources  # noqa: E402

SITE = "Светлый проезд, вл. 4"

LIVESOKOL = ("Компания «КС-Про», на 30% принадлежащая головной организации девелопера "
             "STONE — АО «Стоунхедж», проводит инженерно-геодезические работы "
             "на участке по адресу: Светлый проезд, вл. 4.")
DZEN = "ЖК от STONE на Светлый проезд, 4 — старт продаж ЖК бизнес-класса в САО Москвы"


@dataclass
class Doc:
    title: str
    snippet: str
    url: str = "https://t.me/livesokol/14677"
    domain: str = "t.me"
    rank: int = 1


def test_a_developer_counts_as_an_operator():
    got = krt_open_sources.read_findings(
        [Doc(title="Стройка на Светлом проезде", snippet=LIVESOKOL)], SITE)
    assert got["operator_named"], "«девелопер» не опознан как тот, кто площадку берёт"
    name = got["operator_named"][0]["name"]
    assert "Стоунхедж" in name or "STONE" in name, f"имя разобрано как «{name}»"
    assert got["taken"] is True


def test_the_name_keeps_its_closing_quote():
    """«АО «Стоунхедж» с непарной кавычкой дальше не совпадёт ни с чем."""
    name = krt_open_sources._operator_name(LIVESOKOL)
    assert name.count("«") == name.count("»"), f"непарная кавычка в «{name}»"


def test_a_brand_before_the_address_is_read_too():
    """«ЖК от STONE» — имя стоит перед адресом, хвостовой разбор его не видит."""
    got = krt_open_sources.read_findings(
        [Doc(title=DZEN, snippet="", url="https://dzen.ru/a/x", domain="dzen.ru")], SITE)
    assert got["operator_named"], "имя из заголовка не прочитано"
    assert got["operator_named"][0]["name"] == "STONE"
    assert got["taken"] is True


def test_a_role_after_ot_is_not_a_name():
    for phrase in ("ЖК от застройщика на Светлый проезд",
                   "Проект от Города на Светлый проезд",
                   "Квартал от девелопера на Светлый проезд"):
        assert krt_open_sources._operator_name(phrase) == "", phrase


def test_a_quoted_brand_is_read():
    assert krt_open_sources._operator_name(
        "ЖК от «Донстрой» на Светлый проезд") == "Донстрой"


def test_the_old_wording_still_works():
    """Правка добавляет слова, а не заменяет прежние."""
    name = krt_open_sources._operator_name(
        "Оператором выступает компания «КРТ «Магистральные улицы» - группа ЕСН.")
    assert "ЕСН" in name or "Магистральные" in name


def test_a_stranger_site_still_does_not_borrow_the_name():
    """Якорь не смягчается: имя без адреса площадки — чужое."""
    got = krt_open_sources.read_findings(
        [Doc(title="ЖК от STONE на Бутовской улице", snippet="")], SITE)
    assert not got["operator_named"] and got["taken"] is False
