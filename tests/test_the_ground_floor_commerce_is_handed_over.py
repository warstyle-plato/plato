"""Жилой объём города — это МКД целиком: квартиры И встроенная коммерция.

Владелец о переданной из КРТ площадке «ул. Архитектора Власова, влд. 59»:
«А на самом деле вообще не передал как раз первый этаж коммерции». Замер живой
передачи 26.09.2026: строка «Квартиры» получила ГНС 26 260 м² — ВЕСЬ жилой
объём решения, — а «Коммерция 1 этажа» приехала нулём. Эти метры продавались по
цене квартир и не имели своей экономики.

Правило деления объявлено в движке (`MKD_SPP_SPLIT` 94/6) и применяется
страницей при правке жилья и восстановлением ГлавАПУ — а скрининг КРТ им не
пользовался. Классический случай «правило объявлено, читателей не проверили».

Делить лучше по числам самого города, когда он назвал оба. У этой площадки
решение называет и жильё 26 260 м², и площадь квартир 15 681 м²:

    квартиры ГНС      = 15 681 / 0,65 = 24 124,6
    встроенная        = 26 260 − 24 124,6 = 2 135,4

Это не подгонка под красивое число: тот же документ отдельной строкой называет
нежилую наземную площадь 3 410 м², и 3 410 / 0,9 − 1 655 (ОСЗ по решению)
= 2 133,9 — второй, независимый путь к той же величине, расхождение 1,5 м².

Запуск: python3 -m pytest tests/test_the_ground_floor_commerce_is_handed_over.py -q
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from auction_search.krt_screening import _split_mkd  # noqa: E402

# Числа проекта решения по ул. Архитектора Власова, влд. 59 (mos.ru 349135220).
HOUSING, FLATS = 26260.0, 15681.0
NONRES_SPP, STANDALONE = 1655.0, 1655.0
GROUND_NONRES = 3410.0
SALEABLE_OF_GNS = 0.65   # квартиры = 65% жилой СПП, методика ГлавАПУ
NONRES_OF_SPP = 0.90     # НП = 90% СПП, она же


def _core():
    spec = importlib.util.spec_from_file_location("core", ROOT / "main_legacy.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_city_own_numbers_split_the_housing_volume() -> None:
    """Названы оба числа — делим по ним, и продаваемая равна числу города."""
    core = _core()
    apartments, ground, basis = _split_mkd(core, HOUSING, FLATS, SALEABLE_OF_GNS)
    assert round(apartments, 1) == 24124.6
    assert round(ground, 1) == 2135.4
    assert apartments + ground == HOUSING, "деление не теряет и не добавляет метров"
    assert "названным городом" in basis
    # Выручка стоит на метре города, а не на нашем пересчёте.
    assert round(apartments * SALEABLE_OF_GNS, 0) == FLATS


def test_the_second_path_from_the_document_agrees() -> None:
    """Независимая сверка: нежилая наземная минус ОСЗ даёт ту же встроенную.

    Без неё деление было бы лишь правдоподобным. С ней — проверенным.
    """
    core = _core()
    _, ground, _ = _split_mkd(core, HOUSING, FLATS, SALEABLE_OF_GNS)
    by_nonres = GROUND_NONRES / NONRES_OF_SPP - STANDALONE
    assert abs(ground - by_nonres) < 2.0, (
        f"два пути к встроенной разошлись: {ground:.1f} и {by_nonres:.1f}")


def test_without_the_flats_the_engine_ratio_splits_it() -> None:
    """Квартиры не названы — делит объявленное в движке 94/6, а не ноль."""
    core = _core()
    apartments, ground, basis = _split_mkd(core, HOUSING, 0.0, SALEABLE_OF_GNS)
    assert apartments == HOUSING * core.MKD_SPP_SPLIT["apartments"]
    assert ground == pytest.approx(HOUSING * core.MKD_SPP_SPLIT["ground_commercial"])
    # Остаток считается вычитанием, а не второй долей: пара обязана сходиться
    # с жильём ТОЧНО, иначе метры теряются на округлении.
    assert apartments + ground == HOUSING
    assert ground > 0, "встроенная коммерция в МКД есть и без названной площади квартир"
    assert "94/6" in basis and "не названа" in basis


def test_a_contradiction_is_named_not_clipped() -> None:
    """ГНС квартир больше всего жилья — считаем умолчанием и ГОВОРИМ почему."""
    core = _core()
    apartments, ground, basis = _split_mkd(core, 20000.0, FLATS, SALEABLE_OF_GNS)
    assert apartments + ground == 20000.0
    assert apartments == 20000.0 * core.MKD_SPP_SPLIT["apartments"]
    assert "больше всего жилья" in basis and "делить нельзя" in basis


def test_nothing_is_invented_out_of_nothing() -> None:
    """Жилья нет — нет и деления: ноль не превращается в метры."""
    core = _core()
    assert _split_mkd(core, 0.0, FLATS, SALEABLE_OF_GNS) == (0.0, 0.0, "")


def test_the_screening_writes_the_row_and_says_what_split_it() -> None:
    """Строка заполняется и основание доезжает до предпосылок — в коде прогона."""
    source = (ROOT / "auction_search" / "krt_screening.py").read_text(encoding="utf-8")
    assert 'tep["ground_commercial"].update(' in source, "строка ТЭП заполняется"
    assert 'tep["apartments"].update({\n        "gns": apartments_gns,' in source, (
        "квартиры получают свою долю, а не весь жилой объём")
    assert "ground_basis" in source and "assumptions.append(" in source
    body = source[source.index("if ground_basis:"):]
    assert "встроенная коммерция" in body[:600]
