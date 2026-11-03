"""Чьё это КРТ и не занято ли оно — словами источника, а не нашей оценкой.

«Надо добавлять то, что видно по открытым источникам, фильтр по нуждам города и
возможно уже назначение оператора» (владелец, 31.08.2026).

Три вещи, и каждая с цитатой. Вид КРТ по ст. 65 ГрК заголовок проекта решения
называет прямо. Городские нужды — узкий набор оборотов: «расселение» и
«аварийное» сюда не входят, обязательство расселить мы считаем отдельно и оно
есть у половины площадок, а признак, срабатывающий почти всегда, ничего не
отделяет. Оператор — строка «Застройщик» карточки, которая у нас была и
отбрасывалась вместе с ТЭП как служебная.

Главное правило проверяется отдельно: не нашлось — это «не найдено», а не
«нет». Молчащий источник, выданный за отрицательный ответ, — та же ошибка, что
пустой ответ НСПД, прочитанный как отсутствие ограничений.

Запуск: python3 -m pytest tests/test_krt_says_whose_project_it_is.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from market_search.krt_requirements import (  # noqa: E402
    _meta_fields, decision_intent, krt_kind, merge_decision_requirements,
    parse_decision_requirements, parse_project_requirements,
)

CARD = """
# Описание объекта
Площадь, га: 10.24
Округ: СЗАО
Район: Строгино
Застройщик: АО «Мосинжпроект»
Общий объем застройки: 323 796
Территория включает производственные корпуса.
"""

DECISION_TITLE = (
    "Проект решения о комплексном развитии территории нежилой застройки "
    "по адресу: г. Москва, Маршала Воробьева ул., вл. 12")

DECISION_TEXT = (
    "Настоящим утверждается проект решения о комплексном развитии территории. "
    "Предельный срок реализации решения — 2031 год. "
    "Изъятие земельных участков осуществляется для государственных нужд города Москвы. "
    "Оператор комплексного развития территории определяется по результатам торгов.")


def test_the_kind_is_read_from_the_title() -> None:
    kind, quote = krt_kind(DECISION_TITLE)
    assert kind == "нежилой застройки"
    assert "нежилой застройки" in quote


def test_the_kinds_are_told_apart() -> None:
    for title, expected in (
        ("Проект решения о комплексном развитии территории жилой застройки", "жилой застройки"),
        ("… территории нежилой застройки", "нежилой застройки"),
        ("… незастроенной территории", "незастроенной территории"),
        ("… по инициативе правообладателей", "по инициативе правообладателей"),
    ):
        assert krt_kind(title)[0] == expected, title


def test_the_developer_line_of_the_card_is_no_longer_thrown_away() -> None:
    fields = _meta_fields(CARD)
    assert fields.get("застройщик") == "АО «Мосинжпроект»"
    # И она по-прежнему не попадает в перечень обязательств.
    card = parse_project_requirements(CARD, {"slug": "x", "name": DECISION_TITLE})
    assert all("Мосинжпроект" not in line for line in card["description"])
    assert card["intent"]["operator_name"] == "АО «Мосинжпроект»"
    assert card["intent"]["taken"] is True


def test_city_needs_come_with_the_sentence_that_says_so() -> None:
    intent = decision_intent(DECISION_TEXT, title=DECISION_TITLE)
    assert intent["city_needs"], "оборот о государственных нуждах не найден"
    assert "государственных нужд" in intent["city_needs"][0]
    assert intent["operator"], "оборот об операторе не найден"


def test_a_resettlement_duty_is_not_a_city_need() -> None:
    """Иначе признак срабатывает почти всегда и ничего не отделяет."""
    text = ("Подлежат расселению жилые дома, признанные аварийными. "
            "Расселение осуществляется застройщиком за свой счёт.")
    assert decision_intent(text)["city_needs"] == []


def test_nothing_found_is_not_nothing_there() -> None:
    """Пустой ответ — «не найдено», и это видно по `probed`."""
    quiet = decision_intent("Территория развивается поэтапно.", title="")
    assert quiet["city_needs"] == [] and quiet["operator"] == []
    assert quiet["taken"] is False
    assert quiet["kind"] == "", "вид не назван — угадывать его нечем"
    assert quiet["probed"] is True, "документ был — искали и не нашли"

    unread = decision_intent("", title="", card_fields={}, probed=False)
    assert unread["probed"] is False, "документа не было — это другой ответ"


def test_the_decision_does_not_lose_the_name_from_the_card() -> None:
    card = parse_project_requirements(CARD, {"slug": "x", "name": DECISION_TITLE})
    facts = parse_decision_requirements(DECISION_TEXT, DECISION_TITLE)
    merged = merge_decision_requirements(card, facts, {"id": "1", "title": DECISION_TITLE})
    assert merged["intent"]["operator_name"] == "АО «Мосинжпроект»"
    assert merged["intent"]["kind"] == "нежилой застройки"
    assert merged["intent"]["city_needs"]


def test_renovation_is_a_city_need_and_so_is_krt_of_housing() -> None:
    """«Реновация — это тоже городские нужды» (владелец, 31.08.2026).

    Двух ответов на один вопрос быть не должно: КРТ жилой застройки — та же
    история, город расселяет жильцов по своей программе. Вид КРТ поэтому сам по
    себе основание — со своей цитатой из заголовка, а не выданный за фразу
    документа.
    """
    housing_title = ("Проект решения о комплексном развитии территории жилой застройки "
                     "города Москвы, расположенной по адресу: г. Москва, ул. Тестовая, вл. 1")
    intent = decision_intent("Территория развивается поэтапно.", title=housing_title)
    assert intent["kind"] == "жилой застройки"
    assert intent["city_needs"], "жилая застройка — городская история, и это должно быть видно"
    assert "жилой застройки" in intent["city_needs"][0]

    # А нежилая сама по себе городских нужд не означает.
    other = decision_intent("Территория развивается поэтапно.",
                            title="… территории нежилой застройки …")
    assert other["kind"] == "нежилой застройки"
    assert other["city_needs"] == []


def test_the_renovation_word_alone_is_enough() -> None:
    text = ("Площадка включена в программу реновации жилищного фонда города Москвы. "
            "Строительство ведётся поэтапно.")
    got = decision_intent(text, title="… территории нежилой застройки …")
    assert got["city_needs"] and "реновац" in got["city_needs"][0].lower()
