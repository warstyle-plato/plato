"""Комнатность: картинка и вывод, а не две таблицы.

«Блок с комнатностью интересный, но там ни графика с полосами или чем-то
наглядным, ни выводов. Получается, соседи-то продают крупные лоты больше и
поэтому возможно цена у них ниже» (владелец, 05.09.2026).

Обе половины проверяются здесь. Картинка — парные полосы «доля в проданном
против доли в остатке»: вымывание это и есть расхождение двух полос одной
строки. Вывод — разложение разрыва в цене метра на набор квартир и уровень цен:
догадка владельца верна ВНУТРИ проекта (метр тем дороже, чем мельче квартира) и
неверна по рынку (у 174 проектов августа корреляция «средний проданный лот ↔
медианная цена метра» +0,64 — крупные форматы строят в дорогих классах), поэтому
отвечать на неё надо счётом на своём проекте, а не правилом.

Запуск: python3 -m pytest tests/test_the_rooms_block_draws_and_concludes.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from market_search import cabinet, metrics, verdict  # noqa: E402
from market_search.market_reference import MoscowMarket  # noqa: E402


CITY = MoscowMarket({"last_month": "2026-08", "current": {"Бизнес": {"projects": 90}}})

# Мелкий метр дороже крупного — так устроен прайс внутри проекта. У нас набор
# мелкий, у соседей крупный, а цены по комнатности ОДИНАКОВЫЕ: значит весь
# разрыв средней цены объясняется набором, и блок обязан это назвать.
LADDER = {
    "studio": 760_000,
    "r1": 700_000,
    "r2": 640_000,
    "r3": 600_000,
}
SUBJECT = {
    "segment": "Бизнес",
    "room_mix": {
        "studio": {"sold": 12, "rem": 60, "price": LADDER["studio"]},
        "r1": {"sold": 8, "rem": 30, "price": LADDER["r1"]},
        "r2": {"sold": 2, "rem": 8, "price": LADDER["r2"]},
        "r3": {"sold": 0, "rem": 2, "price": LADDER["r3"]},
    },
    "bands": {"28-40": 15, "40-55": 5, "55-85": 2},
}
PEERS = [
    {
        "name": "Сосед А",
        "room_mix": {
            "studio": {"sold": 1, "rem": 5, "price": LADDER["studio"]},
            "r1": {"sold": 3, "rem": 15, "price": LADDER["r1"]},
            "r2": {"sold": 6, "rem": 40, "price": LADDER["r2"]},
            "r3": {"sold": 5, "rem": 40, "price": LADDER["r3"]},
        },
        "bands": {"40-55": 4, "55-85": 8, "85-120": 4},
    },
    {
        "name": "Сосед Б",
        "room_mix": {
            "r2": {"sold": 4, "rem": 30, "price": LADDER["r2"]},
            "r3": {"sold": 4, "rem": 30, "price": LADDER["r3"]},
        },
        "bands": {"55-85": 6, "85-120": 2},
    },
]


def _block() -> dict:
    return metrics.rooms_block(SUBJECT, PEERS, CITY).to_dict()


def test_the_gap_is_split_into_the_mix_and_the_price_level() -> None:
    """Одни и те же цены по комнатам, разный набор — разрыв целиком от набора."""
    mix = _block()["subject"]["mix"]
    assert mix["own_at_own_mix"] > mix["peers_at_peers_mix"], "мелкий набор обязан стоить дороже"
    # Цены по комнатам совпадают, значит уровень цен ни при чём — и это должен
    # сказать сам расчёт, а не читатель.
    assert abs(mix["level_pct"]) < 0.5, mix
    assert mix["mix_pct"] < -5, mix
    # Покрытие называется рядом: цена «при наборе соседей» на трети набора —
    # это оценка, а не измерение.
    assert mix["own_coverage_pct"] == 100.0
    assert mix["cross_coverage_pct"] == 100.0


def test_the_level_shows_when_prices_differ_and_the_mix_does_not() -> None:
    """Обратный случай: набор один и тот же, цены разные — набор не при чём."""
    dearer = [
        {
            "name": "Сосед В",
            "room_mix": {
                name: {"sold": item["sold"], "rem": item["rem"], "price": item["price"] * 1.25}
                for name, item in SUBJECT["room_mix"].items()
            },
        }
    ]
    mix = metrics.rooms_block(SUBJECT, dearer, CITY).to_dict()["subject"]["mix"]
    assert abs(mix["mix_pct"]) < 0.5, mix
    assert mix["level_pct"] < -15, mix


def test_a_room_without_a_price_leaves_the_weight_instead_of_averaging_it() -> None:
    """Комнатность без цены выбрасывается из веса, а не считается по средней.

    Иначе неизвестная цена молча считалась бы средней — а средняя тут и есть
    предмет спора.
    """
    price, covered = metrics._weighted_price(
        {"r1": 700_000, "r2": 640_000}, {"r1": 50, "r2": 50, "r3": 100}
    )
    assert price == 670_000
    assert covered == 50.0
    assert metrics._weighted_price({}, {"r1": 10}) == (None, 0.0)


def test_the_note_answers_the_question_about_the_mix() -> None:
    note = verdict.rooms_note(_block())
    text = note["text"]
    assert "набором квартир объясняется" in text, text
    # Вымывание названо своим числом, а не словом «вымывается».
    assert "% продаж при" in text, text
    assert note["tone"] in {verdict.TONE_WATCH, verdict.TONE_FLAT}

    empty = verdict.rooms_note({"subject": {}, "peers": {}})
    assert "не раскрыта" in empty["text"]


def test_the_notes_exist_for_every_new_section() -> None:
    """Раздел без вывода читается как «сказать нечего»."""
    for code in ("rooms", "payment", "channel"):
        assert code in verdict.NOTE_BUILDERS, code


def test_the_block_is_drawn_with_bars_in_a_real_browser(tmp_path) -> None:
    """Спор «наглядно или нет» решает экран, а не рассуждение о коде."""
    import json

    import pytest

    play = pytest.importorskip("playwright.sync_api")

    import browser_launch

    block = _block()
    page = cabinet.cabinet_page("market").replace("__DEVELOPAID_VERSION__", "test")
    file = tmp_path / "market.html"
    file.write_text(page, encoding="utf-8")
    with play.sync_playwright() as pw:
        try:
            browser = browser_launch.launch(pw)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"Chromium недоступен: {exc}")
        try:
            tab = browser.new_page()
            errors: list[str] = []
            tab.on("pageerror", lambda exc: errors.append(str(exc)))
            tab.route("**/*", lambda route: route.abort()
                      if route.request.url.startswith("http") else route.continue_())
            tab.goto(file.as_uri())
            drawn = tab.evaluate(
                "([block, say]) => blockCard(block, {analysis:{blocks:{rooms:say}}})",
                [block, verdict.rooms_note(block)],
            )
            tab.close()
        finally:
            browser.close()
    assert not errors, errors
    # Две картинки: комнатность и полосы площади. Полос столько же, сколько
    # известных долей, — пустой <svg> выглядит на экране так же, как полный.
    assert drawn.count("<svg") == 2, drawn.count("<svg")
    assert drawn.count("<rect") >= 12, drawn.count("<rect")
    assert "доля в проданном" in drawn and "доля в остатке" in drawn
    assert "наши сделки" in drawn and "у соседей" in drawn
    # Картинка стоит НАД своей таблицей: в колоде чертится та таблица, над
    # которой стоит график.
    assert drawn.index("<svg") < drawn.index("<table"), "график встал под таблицу"
    # И числа разложения — на плитках, а не только в тексте вывода.
    assert "из разрыва — набор квартир" in drawn
    assert "из разрыва — уровень цен" in drawn
    assert "набором квартир объясняется" in drawn
