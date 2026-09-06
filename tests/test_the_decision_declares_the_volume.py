"""Объём площадки называет решение, а не карточка каталога.

«Логику разложения данных не понимает» (владелец, 04.09.2026). Карточка
каталога по Варшавскому ш., вл. 37 сама с собой не сходится: 229 490 жилья и
52 510 нежилого при заявленных 443 700 всего. Проект решения сходится до
метра — 229 490 + 214 210 = 443 700, — и нежилого в нём вчетверо больше
карточного, из них не менее 167 787,5 м² коммунального, производственного и
иного назначения.

Три ловушки, каждую нашла только вторая площадка.

Слово совпадает, а вид утверждения — нет: «объект коммунального назначения
(общественный туалет) площадью 90 кв. м» на Левобережной читался как
минимальный объём коммунальной застройки. Оборот засчитывается только внутри
рамки «суммарная поэтажная площадь».

Тире перечня город пишет длинным (`–`), а не дефисом: набор `[;\\n]|-\\s` его
не знал, всё предложение оставалось одним оборотом, и на Малахитовой итог
зоны 187 550 читался как объём жилья. Та же ошибка, что уже ловилась в именах
ЖК на ASCII-дефисе.

А тире ЗНАЧЕНИЯ выглядит так же: «стен – 443 700 кв. м». Разделяет то, что
стоит следом: у перечня слово, у значения цифра. Без этого итог отрезался от
своего же числа.

Запуск: python3 -m pytest tests/test_the_decision_declares_the_volume.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from market_search.krt_requirements import programme_volumes  # noqa: E402

# Живой текст решения по Варшавскому ш., вл. 37 (mos.ru), с пробелами, как их
# оставил PDF: «объ ектов», «ми нимальная».
VARSHAVSKOE = [
    "Предельная (максимальная) суммарная поэтажная площадь объ ектов капитального "
    "строительства в габаритах наружных стен – 443 700 кв. м, включая: - объекты "
    "жилого назначения – 229 490 кв. м; - объекты нежилого назначения – 214 210 кв. м.",
    "Предельная (ми нимальная) суммарная поэтажная площадь объектов капитального "
    "строительства коммунального, производственного и иного назначения – 167 787,5 кв. м.",
]
# Малахитовая: длинное тире перечня и общественно-деловое назначение, которого
# в карточке каталога нет вовсе.
MALAKHITOVAYA = [
    "Зона 1 (11,24 га): Предельная (максимальная) суммарная поэтажная площадь "
    "объектов капитального строительства в габаритах наружных стен – 187 550 кв. м, "
    "в том числе: – объектов жилого назначения для реализации Программы реновации "
    "жилищного фонда в городе Москве и иных городских нужд – 179 150 кв. м; "
    "– объектов общественно-делового назначения – 8 400 кв. м.",
]


def test_the_decision_closes_where_the_card_does_not() -> None:
    volumes = programme_volumes(VARSHAVSKOE)
    assert volumes["total_sqm"] == 443_700.0
    assert volumes["housing_sqm"] == 229_490.0
    assert volumes["nonresidential_sqm"] == 214_210.0
    assert volumes["utility_sqm"] == 167_787.5
    assert volumes["closes"] is True, "слагаемые решения обязаны сойтись с его итогом"


def test_the_long_dash_list_is_split_into_its_items() -> None:
    volumes = programme_volumes(MALAKHITOVAYA)
    assert volumes["housing_sqm"] == 179_150.0, "итог зоны прочитан как объём жилья"
    assert volumes["business_sqm"] == 8_400.0, "общественно-деловое назначение потеряно"
    assert volumes["total_sqm"] == 187_550.0
    assert volumes["closes"] is True


def test_a_public_toilet_is_not_a_programme_volume() -> None:
    """Совпало слово, а не вид утверждения."""
    volumes = programme_volumes([
        "Осуществить строительство объекта коммунального назначения (общественный "
        "туалет) площадью ориентировочно 90 кв. м в границах территориальной зоны 1."])
    assert not volumes.get("utility_sqm")
    assert not volumes.get("total_sqm")


def test_nothing_read_is_not_zero() -> None:
    """Пустой разбор и площадка без объёмов на экране выглядят одинаково."""
    volumes = programme_volumes([])
    assert volumes["closes"] is None
    assert volumes["zones"] == 0


def test_the_zones_add_up() -> None:
    """Зоны — части, и они складываются, как у реновации."""
    volumes = programme_volumes(VARSHAVSKOE + MALAKHITOVAYA)
    assert volumes["total_sqm"] == 443_700.0 + 187_550.0
    assert volumes["housing_sqm"] == 229_490.0 + 179_150.0
    assert volumes["zones"] == 2


def test_our_own_subtraction_is_not_called_the_city_s_gap(core=None) -> None:
    """Вычтенное НАМИ не записывается в расхождение города.

    Коммунальный объём решение задаёт минимумом и внутри нежилого; скрининг
    вычитает его из нежилого, потому что продуктом девелопера он не является.
    А баланс считался по числам ПОСЛЕ этой правки — и на Варшавском ш., вл. 37
    объявлял «разница 167 788 м²» ровно на ту величину, которую мы сами и
    убрали, под именем города (владелец, 06.09.2026: «не объединено выше?»).
    Своя правка, названная чужой ошибкой, читается как находка в источнике.

    Проверяется арифметикой разложения, а не строкой на экране: сумма
    слагаемых обязана сойтись с итогом города, а вычтенный объём — стоять
    своей строкой.
    """
    import importlib.util

    from auction_search.krt_screening import build_krt_model_screening

    spec = importlib.util.spec_from_file_location("developaid_core", ROOT / "main_legacy.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["developaid_core"] = module
    spec.loader.exec_module(module)

    project = {
        "slug": "varshavskoe-shosse-vl-37", "name": "Варшавское шоссе, вл. 37",
        "district": "Нагатино-Садовники", "area_ha": 14.62,
        "total_gfa_sqm": 443_700.0, "housing_gfa_sqm": 229_490.0,
        "nonresidential_gfa_sqm": 52_510.0, "business_gfa_sqm": 0.0,
    }
    market = {"analysis": {"site": {"segment": "Бизнес", "price_per_sqm": 450_000,
                                    "sold_lot_avg": 58, "units_per_month": 25}},
              "price_hint": {}}
    result = build_krt_model_screening(
        project, market, module,
        requirements={"available": True, "volumes": programme_volumes(VARSHAVSKOE)})
    programme = result["programme"]

    assert programme["volumes"]["taken"] is True, "решение сошлось с итогом каталога — берём его"
    assert programme["city"]["utility_gfa_sqm"] == 167_787.5, (
        "вычтенный объём обязан стоять своей строкой разложения")
    assert programme["balance"]["matches"] is True, (
        "слагаемые с коммунальным объёмом сходятся с итогом города — "
        f"{programme['balance']['declared_sum_sqm']} против "
        f"{programme['city']['total_gfa_sqm']}")
    assert abs(programme["balance"]["difference_sqm"]) <= 1.0

    # И то, ради чего вычитание вообще есть: этот объём модель не строит и
    # говорит об этом отдельной строкой, а не молчанием.
    said = " ".join(result.get("exclusions") or [])
    assert "коммунального, производственного" in said
