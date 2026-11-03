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


MARKET = {"analysis": {"site": {"segment": "комфорт", "price_per_sqm": 400_000,
                               "sold_lot_avg": 45.0, "units_per_month": 12.0}},
          "price_hint": {"entry_per_sqm": 400_000, "price_per_sqm": 400_000}}
# Ул. Архитектора Власова, влд. 59 — решение называет и жильё, и площадь квартир.
VLASOV = {"slug": "decision:349135220", "name": "ул. Архитектора Власова, влд. 59",
          "no_card": True, "area_ha": 2.1, "housing_gfa_sqm": HOUSING,
          "flats_sqm": FLATS, "nonresidential_ground_sqm": GROUND_NONRES}
# Рубцовская наб., влд. 3 — жилой объём документ НЕ называет, квартиры называет.
FLATS_ONLY = {"slug": "decision:333331220", "name": "Рубцовская наб., влд. 3",
              "no_card": True, "area_ha": 0.73, "flats_sqm": 4_290.0,
              "nonresidential_ground_sqm": 16_200.0}


def _screened(site: dict) -> dict:
    """Прогон настоящим движком. Движок берётся ИМПОРТОМ, а не своей загрузкой:
    загруженный копией, он теряет разрешённые модели pydantic и падает не по
    делу."""
    import main_legacy  # noqa: PLC0415 — тяжёлый движок нужен только здесь

    from auction_search.krt_screening import build_krt_model_screening  # noqa: PLC0415

    got = build_krt_model_screening(dict(site), MARKET, main_legacy)
    assert got["available"] is True, got.get("reason")
    return got


def test_the_screening_writes_the_row_and_says_what_split_it() -> None:
    """Прогон заполняет строку и называет основание — проверяется на РЕЗУЛЬТАТЕ.

    Прежняя версия читала исходник подстроками и поэтому не заметила, что
    восстановленный из квартир объём делится 94/6 (см. проверку ниже): текст в
    файле стоял, а поведение было другим.
    """
    got = _screened(VLASOV)
    tep = got["model_inputs"]["tep"]
    apartments, ground = tep["apartments"], tep["ground_commercial"]

    assert apartments["gns"] + ground["gns"] == pytest.approx(HOUSING)
    assert apartments["gns"] == pytest.approx(FLATS / SALEABLE_OF_GNS, abs=0.5)
    assert ground["gns"] > 0, "строка встроенной коммерции снова приехала нулём"
    assert ground["saleable"] == pytest.approx(
        ground["gns"] * 0.9, rel=0.001), ground
    # Продаваемая квартир — ровно названное городом число, а не наш пересчёт.
    assert got["phasing"]["saleable_sqm"] == round(FLATS)
    said = " ".join(got["assumptions"])
    assert "встроенная коммерция" in said and "названным городом" in said, said
    # Эти метры идут по цене площадки, а не по цене класса из пресета.
    inputs = got["model_inputs"]["inputs"]
    assert inputs["commercial_price_th"] == inputs["apartment_price_th"]


def test_a_volume_restored_from_the_flats_is_not_split_again() -> None:
    """Восстановленный из квартир объём — уже ГНС квартир, делить его нечем.

    Рубцовская наб., влд. 3: решение называет только площадь квартир 4 290 м².
    Деление такого объёма методикой 94/6 отняло бы 6% в пользу метров, которых
    никто не называл, и продаваемая вышла бы 4 033 вместо 4 290 — наш пересчёт
    вместо числа города.
    """
    got = _screened(FLATS_ONLY)
    tep = got["model_inputs"]["tep"]
    assert got["phasing"]["saleable_sqm"] == round(FLATS_ONLY["flats_sqm"])
    assert tep["apartments"]["gns"] == pytest.approx(
        FLATS_ONLY["flats_sqm"] / SALEABLE_OF_GNS, abs=0.5)
    assert tep["ground_commercial"]["gns"] == 0, (
        "приписана встроенная коммерция, которой документ не называл")
    said = " ".join(got["assumptions"])
    assert "восстановлен из площади квартир" in said, said
    # Предохранитель: там, где город назвал ОБА числа, строка не нулевая —
    # иначе проверка проходила бы и на полностью отключённом делении.
    assert _screened(VLASOV)["model_inputs"]["tep"]["ground_commercial"]["gns"] > 0
