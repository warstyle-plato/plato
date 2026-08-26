"""«Продано 3 594 м²» без второй половины — не показатель, а число.

Пятая часть проекта и половина проекта выглядят на экране одинаково, пока
рядом не стоит база (владелец, 26.08.2026). База берётся из уже прочитанных
источников — плана финмодели и книги, — а не заводится третьей.

Здесь же вымывание: доля полосы в пуле против её доли в продажах. Оно
отвечает на «почему не покупают» с той стороны, с которой у нас есть числа:
что показывают покупателю сегодня и чем это отличается от того, что было.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from market_search import contracting


def _rows(areas: list[float]) -> list[dict]:
    return [{"product": "Квартира", "area": area, "amount": area * 600_000.0,
             "month": "2026-01", "units": 1.0} for area in areas]


def _pool(bands: list[tuple[str, float, float, float]]) -> dict:
    return {"sheet": "график продажи_1", "missing": [], "volumes": [],
            "book_pool_units": sum(b[3] for b in bands), "book_sold_units": 0.0,
            "bands": [{"band": name, "low": low, "high": high, "pool_units": units,
                       "book_sold_units": 0.0, "book_sold_area": 0.0,
                       "book_sold_amount": 0.0, "book_price_per_sqm": 0.0}
                      for name, low, high, units in bands]}


def test_the_share_is_counted_where_the_money_is_counted() -> None:
    """Доля, посчитанная в браузере, — второй счёт той же величины."""
    page = (Path(__file__).resolve().parent.parent / "market_search" / "cabinet.py").read_text()
    start = page.index("const SALES_METRICS=")
    block = page[start:page.index("\nfunction tile(", start)]
    for forbidden in ("/p.pool_amount", "/p.pool_area", "/p.pool_units",
                      "sold_amount/", "sold_units/", "sold_area/"):
        assert forbidden not in block, f"экран делит сам: {forbidden}"
    for ready in ("units_share", "area_share", "amount_share", "pool_share",
                  "sold_share", "left_share"):
        assert ready in block, f"готовая доля {ready} не используется"


def test_the_pool_comes_from_the_plan_horizon() -> None:
    """Горизонт плана — весь проект, значит сумма плана и есть пул."""
    fm = {"sheet": "лист", "plan": {
        "Квартира": {"2026-01": {"amount": 100.0, "area": 10.0},
                     "2026-02": {"amount": 300.0, "area": 30.0}},
        "Итого": {"2026-01": {"amount": 999.0}}}}
    got = contracting.plan_pool(fm)
    assert got["Квартира"]["amount"] == 400.0
    assert got["Квартира"]["area"] == 40.0
    assert "Итого" not in got, "итог — не продукт, иначе пул удваивается"


def test_one_product_has_one_name_in_three_sources() -> None:
    """CRM пишет «Машиноместа», план — «Машиноместо», книга — «М/М».

    Пока имена не сведены к одному, пул машино-мест не находится вовсе, и
    доля показывается пустой при полном наборе данных — то есть «не знаем»
    вместо посчитанного.
    """
    for label in ("Машиноместа", "Машиноместо", "М/М", "м/м"):
        assert contracting.product_name(label) == "Машиноместо"
    assert contracting.product_name("КЛД") == "Кладовая"
    assert contracting.product_name("ПСН") == "Коммерческие площади"
    # Незнакомое имя остаётся собой, а не уезжает в ближайшее похожее.
    assert contracting.product_name("Апартамент") == "Апартамент"


def test_the_top_band_is_closed_on_the_right() -> None:
    """Самая большая квартира ровно на верхней границе — она в проекте есть."""
    pool = _pool([("28,3 - 40", 28.3, 40.0, 10.0), ("40 - 168,6", 40.0, 168.6, 10.0)])
    summary = {"by_product": [], "total": {}}
    got = contracting.pool_progress(summary, _rows([30.0, 168.6]), None, pool)
    placed = sum(b["sold_units"] for b in got["bands"])
    assert placed == 2, "квартира на верхней границе потеряна вместе с договором"


def test_a_contract_outside_the_bands_is_named_not_dropped() -> None:
    """Молча выброшенный договор читается как его отсутствие."""
    pool = _pool([("28,3 - 40", 28.3, 40.0, 10.0)])
    got = contracting.pool_progress({"by_product": [], "total": {}}, _rows([30.0, 200.0]), None, pool)
    assert any("вне полос" in line for line in got["missing"])


def test_the_skew_is_the_answer_not_the_count() -> None:
    """Вымывание — это доля полосы в продажах против её доли в пуле."""
    pool = _pool([("маленькие", 20.0, 40.0, 20.0), ("большие", 40.0, 100.0, 80.0)])
    got = contracting.pool_progress({"by_product": [], "total": {}},
                                    _rows([30.0, 31.0, 32.0, 50.0]), None, pool)
    small = next(b for b in got["bands"] if b["band"] == "маленькие")
    big = next(b for b in got["bands"] if b["band"] == "большие")
    assert small["pool_share"] == pytest.approx(0.2)
    assert small["sold_share"] == pytest.approx(0.75)
    assert small["skew"] > 0 and big["skew"] < 0
    # Остаток витрины — не пул и не продажи, а то, что осталось показывать.
    assert small["left_units"] == 17.0 and big["left_units"] == 79.0
    assert big["left_share"] > big["pool_share"], "витрина тяжелеет, и это видно"


def test_two_pools_disagreeing_is_said_aloud() -> None:
    """Доля от 75 мест и доля от 73 выглядят одинаково."""
    fm = {"sheet": "лист", "plan": {"Машиноместо": {"2026-01": {"amount": 1.0, "units": 75.0}}}}
    pool = {"sheet": "книга", "bands": [], "missing": [], "book_pool_units": 0.0,
            "volumes": [{"product": "Машиноместо", "sold": 0.0, "paid": 0.0, "pool": 73.0}]}
    got = contracting.pool_progress({"by_product": [], "total": {}}, [], fm, pool)
    assert any("план финмодели 75" in line and "книга 73" in line for line in got["missing"])


def test_the_unlabelled_pool_column_is_proved_by_the_book() -> None:
    """Колонка «всего» в книге без заголовка — её нельзя угадывать."""
    source = (Path(__file__).resolve().parent.parent / "market_search" / "contracting.py").read_text()
    body = source[source.index("def read_pool("):source.index("def plan_pool(")]
    assert "_POOL_PCT" in body, "доля из книги — доказательство колонки"
    assert "опознана неверно" in body, "не сошлось — это missing, а не похожая колонка"


def test_the_money_block_is_not_read_as_metres() -> None:
    """Подписи КВ/ПСН/М/М/КЛД встречаются в листе трижды.

    Ниже физических объёмов идёт «Мониторинг денежных средств» с теми же
    именами над рублями. Рубли, принятые за метры, выглядят как метры.
    """
    source = (Path(__file__).resolve().parent.parent / "market_search" / "contracting.py").read_text()
    body = source[source.index("def read_pool("):source.index("def plan_pool(")]
    assert "Мониторинге" in body, "почему читается один блок — сказано"
    assert "head_at" in body, "объёмы читаются колонками своего блока, а не поиском подписи"
