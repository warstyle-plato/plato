"""Балл лота — соответствие девелоперскому профилю, и эталон измерен.

«Баллы это соответствие девелоперскому профилю»; «сделки — это бенчмарк 100
соответствия» (владелец, 26.08.2026). Эталон — не наше представление о хорошем
лоте, а 121 сделка владельца за 2025 год.

Граница односторонняя: снизу. «Крупнее лучше! просто тогда таких сделок не
было» — за верхний край не снижаем вовсе.
"""
from __future__ import annotations

from pathlib import Path

from auction_search import profile_fit as fitmod
from auction_search.profile_fit import profile_fit

SOURCE = Path(__file__).resolve().parent.parent / "auction_search" / "profile_fit.py"
UI = Path(__file__).resolve().parent.parent / "auction_search" / "ui.py"

DEAL = {"land_area_sqm": 2956, "building_area_sqm": 1351, "current_price_rub": 204_834_000}


def test_a_typical_deal_is_a_full_match() -> None:
    assert profile_fit(DEAL)["fit"] == 1.0


def test_bigger_than_any_past_deal_is_still_a_full_match() -> None:
    """Выход за девять десятых прошлых сделок — про предложение, не про профиль."""
    huge = profile_fit({"land_area_sqm": 1_000_000, "building_area_sqm": 300_000,
                        "current_price_rub": 20_000_000_000})
    assert huge["fit"] == 1.0
    assert huge["misses"] == []


def test_a_garage_misses_on_every_measured_side() -> None:
    got = profile_fit({"building_area_sqm": 26, "current_price_rub": 200_000})
    assert got["fit"] == 0.0
    assert len(got["misses"]) == 2
    # Насколько мимо — числом: «в 241 раз» объясняет больше, чем «мало».
    assert any("241 раз" in miss for miss in got["misses"])


def test_a_small_sum_is_not_rounded_to_zero() -> None:
    """«Цена 0 млн ₽» читается как отсутствие цены, а не как двести тысяч."""
    got = profile_fit({"building_area_sqm": 26, "current_price_rub": 200_000})
    assert any("0,2 млн ₽" in miss for miss in got["misses"])


def test_an_unmeasured_side_is_not_a_miss() -> None:
    """Лот без цены не хуже лота с плохой ценой — он неизвестен."""
    got = profile_fit({"land_area_sqm": 5000})
    assert got["misses"] == []
    assert "цена" in got["unknown"]
    assert got["fit"] == 1.0


def test_nothing_to_compare_says_so() -> None:
    got = profile_fit({})
    assert got["fit"] is None and got["note"]


def test_cheap_per_metre_is_not_punished() -> None:
    """Низкая цена метра выгодна: штраф за неё понижал бы балл за то, ради чего ходят."""
    body = SOURCE.read_text()
    block = body[body.index("def profile_fit("):]
    assert "checks = [(LAND, land), (BUILDING, building), (PRICE, price)]" in block
    assert "PER_SQM" not in block.split("checks = ")[1].split("\n")[0]
    # Но показать её надо: вход сравнивают с тем, по чему покупали раньше.
    got = profile_fit(DEAL)
    assert got["per_sqm"] and got["per_sqm_median"]


def test_the_benchmark_names_where_it_came_from() -> None:
    """Порог, взятый на глаз, на экране выглядит так же уверенно, как измеренный."""
    assert "121 сделка" in fitmod.BENCHMARK_SOURCE
    for band in (fitmod.LAND, fitmod.BUILDING, fitmod.PRICE, fitmod.PER_SQM):
        assert band.measured > 0, f"у полосы «{band.name}» не назван объём выборки"
        assert band.p10 < band.p25 < band.median < band.p75 < band.p90


def test_the_invented_threshold_is_gone() -> None:
    """«Меньше 500 м² — не площадка» отсекало четверть его же сделок."""
    page = UI.read_text()
    assert "LOT_SMALL_SQM" not in page
    block = page[page.index("function lotScore("):page.index("function lotScoreNote(")]
    assert "l.fit" in block, "балл берёт соответствие у сервера, а не считает сам"
    assert "Крупнее лучше" in block, "почему сверху не снижаем — сказано"


def test_the_screen_does_not_compute_the_fit() -> None:
    page = UI.read_text()
    block = page[page.index("function lotScore("):page.index("function lotScoreNote(")]
    for forbidden in ("p10", "p90", "median", "434", "2956", "48296550"):
        assert forbidden not in block, f"эталон просочился на экран: {forbidden}"
