"""Нежилое решения входит в модель, а его цена идёт за ценой жилья.

«Пускать — это же влияет на фин рез? а мы его игнорируем пока?» и следом «нам
бы выйти на плюс минус 0» (владелец, 21.09.2026).

Игнорировали, и в опасную сторону. Нежилой объём город называет ДВУМЯ полями:
карточка каталога — суммарной поэтажной площадью, проект решения — наземной.
Читалось одно, и у 86 площадок-решений из 240 нежилое не входило в модель
вовсе — 3,59 млн м², которые обязаны построить. На Рубцовской наб., влд. 3 это
16 200 м² при 4 290 м² квартир: экономика стояла на жилой пятой части, и
площадка выглядела прибыльной (+257,5 млн ₽, LLCR 1,09) именно поэтому.

Долю восстановления мы не выбирали — её назвал сам город: на всех трёх
решениях, где названы обе величины, наземная составляет РОВНО 0,900 суммарной
поэтажной (Алтуфьевское ш. пз № 50, Котляково пз № 32, ТПУ «Кленовый
Бульвар»). Это та же «НП = 90% СПП» методики ГлавАПУ.

А цена нежилого стояла одним числом 500 тыс ₽/м² ВНЕ профиля класса — смена
класса её не двигала вовсе, та же болезнь, что была у цены кладовой. Замер на
Рубцовской: полная себестоимость ОСЗ/ТЦ 344 тыс ₽ на метр ГНС при выходе
продаваемой 56,4% (у встроенной коммерции 90% — потому при одной цене она
зарабатывает, а ТЦ нет), порог окупаемости 590 тыс ₽/м² на входе. При 0,9 цены
жилья метры дают −5,6% на себе, при 1,0 — +2,3%: «плюс-минус ноль», о котором
и просил владелец. Пол 450 тыс ₽/м² — московский.

Запуск: python3 -m pytest tests/test_the_nonresidential_metres_pay_for_themselves.py -q
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main_legacy as core  # noqa: E402
from auction_search import krt_screening  # noqa: E402


def test_the_price_follows_the_class_not_a_fixed_number() -> None:
    """Цена нежилого — классовая, а не одно число на все классы."""
    prices = {key: preset["retail_price_th_per_sqm"]
              for key, preset in core.PROJECT_CLASS_PRESETS.items()}
    assert len(set(prices.values())) == len(prices), \
        f"цена нежилого снова одна на все классы: {prices}"
    for key, preset in core.PROJECT_CLASS_PRESETS.items():
        # Офисы и ТЦ — один нежилой метр: два числа разошлись бы молча.
        assert preset["offices_price_th_per_sqm"] == preset["retail_price_th_per_sqm"]
        expected = core.nonresidential_price_th(preset["apartment_price_th"])
        assert preset["retail_price_th_per_sqm"] == expected, \
            f"{key}: цена нежилого выписана числом, а не посчитана правилом"


def test_the_moscow_floor_lifts_the_cheap_class_and_only_moscow() -> None:
    """Пол 450 — московский: в области его нет, и он назван, а не безусловен."""
    assert core.nonresidential_price_th(350) == core.MOSCOW_NONRES_PRICE_FLOOR_TH
    assert core.nonresidential_price_th(350, region="mo") == 350.0
    # Дорогой класс пол не трогает.
    assert core.nonresidential_price_th(1500) == 1500.0
    # Пустая цена жилья — не повод выдумать пол вне Москвы.
    assert core.nonresidential_price_th(0, region="mo") == 0.0


def test_the_screening_prices_by_this_sites_housing() -> None:
    """Цена нежилого идёт за ценой жилья ЭТОЙ площадки, а не пресета."""
    source = Path(krt_screening.__file__).read_text("utf-8")
    at = source.index('"apartment_price_th": start_price / 1000.0,')
    block = source[at:at + 700]
    assert "retail_price_th_per_sqm" in block and "offices_price_th_per_sqm" in block, \
        "цена нежилого снова остаётся числом пресета при рыночной цене жилья"
    assert "core.nonresidential_price_th" in block, \
        "скрининг считает цену нежилого своей копией правила"


def _programme(project: dict) -> dict:
    inputs = copy.deepcopy(core.DEFAULT_INPUTS)
    tep = copy.deepcopy(core.TEP_DEFAULT)
    return krt_screening._programme(
        core, project, {"volumes": {}, "social_objects": []}, inputs, tep,
        core.tep_ratios_applied("")[0], 10_000.0)


def test_the_ground_area_becomes_the_volume_the_model_builds() -> None:
    """Названа наземная без СПП — объём входит в модель, а не молчит."""
    site = {"slug": "decision:1", "no_card": True, "area_ha": 0.73,
            "flats_sqm": 4290.0, "nonresidential_ground_sqm": 16200.0}
    got = _programme(site)
    assert got["nonresidential_from_ground"] is True
    assert got["city"]["nonresidential_ground_sqm"] == 16200.0
    assert abs(got["city"]["nonresidential_gfa_sqm"] - 16200.0 / 0.9) < 0.5, \
        "нежилое восстановлено не отношением города"
    assert got["commercial_gba_sqm"] > 0, "восстановленный объём до продукта не доехал"

    # Названа СПП — она и берётся: наш пересчёт числа города не подменяет.
    named = _programme({"slug": "krt:1", "nonresidential_gfa_sqm": 20000.0,
                        "nonresidential_ground_sqm": 18000.0})
    assert named["nonresidential_from_ground"] is False
    assert named["city"]["nonresidential_gfa_sqm"] == 20000.0

    # Не названа ни одна — это «не знаем», а не ноль метров из воздуха.
    silent = _programme({"slug": "decision:2", "no_card": True})
    assert silent["nonresidential_from_ground"] is False
    assert silent["city"]["nonresidential_gfa_sqm"] == 0.0


def test_the_city_ratio_is_declared_once() -> None:
    """Отношение наземной к СПП объявлено в движке, а не выписано числом."""
    assert core.CITY_GROUND_OF_SPP == 0.9
    source = Path(krt_screening.__file__).read_text("utf-8")
    at = source.index("nonresidential_from_ground = ")
    block = source[at:at + 400]
    assert "core.CITY_GROUND_OF_SPP" in block, \
        "скрининг делит на своё число вместо объявленного отношения города"
    assert "/ 0.9" not in block, "отношение города снова выписано литералом"
