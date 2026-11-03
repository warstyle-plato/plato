"""Паспорт площадки — её собственные числа — опознаёт публикацию не хуже адреса.

«Прошлякова это просто развитие ЖК „Строгино 360"» (владелец, 06.09.2026).
Площадка КРТ на Маршала Прошлякова, вл. 9 стоит в каталоге свободной с баллом
84, а рынок знает её именем соседнего ЖК: в 51 прочитанной публикации номера
владения «9» не называет НИ ОДНА, поэтому строгий режим (улица «Маршала» общая
с соседней площадкой каталога) отсекал всё подряд.

Числа при этом называют: 69,73 га, 580 096 м² жилья, «более 950 тысяч
квадратных метров». Они и есть паспорт: номер владения у площадки и у
построенного рядом дома бывает ОДИН («Варшавское шоссе, 37» на витрине
продаж), а гектары — только у неё. Поэтому паспорт засчитывается по
ДОКУМЕНТУ, а номер владения по-прежнему по предложению.

Витрину продаж это не отпирает: «здесь уже продаётся ЖК» по-прежнему требует
нашего номера владения в документе — иначе вернулась бы ГК ФСК на Варшавском.

Запуск: python3 -m pytest tests/test_the_passport_is_an_anchor.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from market_search import krt_open_sources as sources  # noqa: E402


class Doc:
    def __init__(self, title: str, snippet: str, url: str) -> None:
        self.title, self.snippet, self.url = title, snippet, url


OURS = "Маршала Прошлякова ул., вл. 9"
# Соседняя площадка каталога по той же улице — из-за неё якорь «марша» общий,
# и включается строгий режим.
NEIGHBOUR = "Маршала Воробьева ул., вл. 12"
PASSPORT = {"area_ha": 69.73, "housing_gfa_sqm": 580_096.0,
            "total_gfa_sqm": 951_073.0}

ABOUT = [
    Doc("Участок на улице Маршала Прошлякова реорганизуют по программе КРТ",
        "Комплексное развитие территории площадью 69,7 га в Строгине. "
        "Здесь построят более 950 тысяч квадратных метров недвижимости. "
        "Проект реализует застройщик ГК «ПИК».",
        "https://www.mos.ru/news/item/152310073/"),
]
# Тот же документ без чисел: строгий режим обязан отсечь его по-прежнему.
WITHOUT = [
    Doc("Участок на улице Маршала Прошлякова реорганизуют по программе КРТ",
        "Комплексное развитие территории в Строгине. "
        "Проект реализует застройщик ГК «ПИК».",
        "https://www.mos.ru/news/item/152310073/"),
]


def test_the_passport_numbers_are_read_whole_and_with_their_unit() -> None:
    say = sources.says_our_passport
    assert say("территория площадью 69,7 га", PASSPORT)
    assert say("площадью 69,74 гектара", PASSPORT)
    assert say("580 тыс. кв. м жилья", PASSPORT)
    assert say("более 950 тысяч квадратных метров", PASSPORT)
    # Число берут целиком: «1 069,73 га» — не наши 69,73.
    assert not say("1 069,73 га", PASSPORT)
    # Единица — часть числа: километры гектарами не становятся.
    assert not say("в 69,73 км от центра", PASSPORT)
    # Соседняя площадка со своими гектарами нашей не является.
    assert not say("участок 12,97 га", PASSPORT)
    # Пустой паспорт — это «сверять не с чем», а не «совпало».
    assert not say("площадью 69,7 га", None)
    assert not say("площадью 69,7 га", {"area_ha": 0})


def test_the_publication_that_names_our_numbers_names_our_builder() -> None:
    """Строгий режим пропускает документ, назвавший паспорт площадки."""
    blind = sources.read_findings(ABOUT, OURS, [NEIGHBOUR])
    assert blind["strict_house"] is True, "проверяется не строгий режим"
    assert not blind["developer_named"], "без паспорта находка бралась и так"

    found = sources.read_findings(ABOUT, OURS, [NEIGHBOUR], PASSPORT)
    named = [item.get("name") for item in found["developer_named"]]
    assert any("ПИК" in str(one) for one in named), found["developer_named"]


def test_without_the_numbers_the_strict_mode_still_refuses() -> None:
    """Паспорт — доказательство, а не отмена строгости."""
    found = sources.read_findings(WITHOUT, OURS, [NEIGHBOUR], PASSPORT)
    assert not found["developer_named"], found["developer_named"]


def test_a_sales_page_is_not_unlocked_by_the_passport() -> None:
    """«Здесь уже продаётся ЖК» по-прежнему требует нашего номера владения."""
    sales = [Doc("ЖК «Строгино 360» от застройщика ПИК — купить квартиру",
                 "ЖК «Строгино 360» от застройщика ПИК на улице Маршала "
                 "Прошлякова. Рядом территория 69,7 га. Квартиры от 19 млн.",
                 "https://msk.restate.ru/complex/strogino-360-5936.html")]
    found = sources.read_findings(sales, OURS, [NEIGHBOUR], PASSPORT)
    assert not found["selling_now"], found["selling_now"]
