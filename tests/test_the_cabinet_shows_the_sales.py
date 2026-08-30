"""Свод продаж виден в кабинете, а не только за маршрутом.

`/cabinet/contracting` считал всё — динамику, структуру оплаты, каналы,
вознаграждение, расторжения, — и отдавал JSON, который на экране никто не
рисовал: до свода нельзя было дойти руками. Кнопка загрузки в кабинете была
только у «Плана продаж».

Экран НИЧЕГО не считает, кроме долей внутри одной картинки: второй счёт той же
выручки однажды разошёлся бы с первым, и обе строки выглядели бы верными.

И отдельно — премия отдела продаж. Она лежит другим полем, чем брокерская
комиссия, и без неё канал «напрямую» показывал ровно ноль, то есть «бесплатно».
Это не бесплатно, это другая строка расходов.

Запуск: python3 -m pytest tests/test_the_cabinet_shows_the_sales.py -q
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from market_search.cabinet import cabinet_page  # noqa: E402
from market_search.contracting import _totals  # noqa: E402


def page() -> str:
    # Свод продаж живёт своей страницей: на титуле кабинета его нет вовсе.
    return cabinet_page("sales")


def script() -> str:
    blocks = re.findall(r"<script>(.*?)</script>", page(), re.S)
    return max(blocks, key=len)


def row(**kwargs) -> dict:
    base = {"units": 1.0, "area": 50.0, "amount": 30_000_000.0, "escrow_paid": 20_000_000.0,
            "broker_fee": 0.0, "sales_bonus_paid": 0.0}
    base.update(kwargs)
    return base


def test_the_cabinet_has_a_place_to_drop_the_file() -> None:
    html = page()
    assert 'id="cf"' in html, "кнопки загрузки ЦФ не было вовсе"
    assert "Загрузить файл проекта" in html
    assert 'id="sales"' in html
    assert "/cabinet/contracting" in html


def test_every_block_the_summary_carries_is_drawn() -> None:
    body = script()
    for key in ("dynamics", "by_product", "by_payment", "by_channel", "by_size", "terminated"):
        assert f"d.{key}" in body, f"раздел {key} посчитан, но не нарисован"
    # Чего в выгрузке не нашлось — вслух: пустой раздел и отсутствующий
    # выглядят одинаково, а значат разное.
    assert "Не прочитано" in body


def test_the_screen_does_no_arithmetic_of_its_own() -> None:
    """Доли внутри картинки — можно; выручка, площади и ставки — нет."""
    body = script()
    # Область — весь блок продаж, а не одна функция: рисование разъехалось по
    # разделам, и проверка, глядящая в одну функцию, проверяла бы половину.
    start = body.index("const SALES_METRICS=")
    block = body[start:body.index("\nfunction tile(", start)]
    # Доли и удельные приходят с сервера, а не считаются здесь. Перевод в
    # миллионы — оформление, а не экономика, и он разрешён.
    for forbidden in ("/x.amount", "/x.area", "/m.area", "/m.amount", "*1.2", "0.9*"):
        assert forbidden not in block, f"экран считает сам: {forbidden}"
    for ready in ("x.fee_of_escrow", "x.cost_of_sales", "x.filled", "m.price_per_sqm"):
        assert ready in block, f"готовое значение {ready} не используется"


def test_the_own_desk_is_not_free() -> None:
    """Премия ОП — отдельная строка расходов, а не ноль вознаграждения."""
    own = _totals([row(sales_bonus_paid=500_000.0)])
    assert own["broker_fee"] == 0.0
    assert own["sales_bonus"] == 500_000.0
    assert own["cost_of_sales"] > 0, "свой отдел не бесплатный"
    assert "Премия ОП" in script()


def test_the_cost_of_a_channel_counts_both_lines() -> None:
    """У брокера это почти всегда комиссия, у своего отдела — премия."""
    got = _totals([row(broker_fee=1_000_000.0, sales_bonus_paid=200_000.0)])
    assert got["cost_of_sales"] == (1_000_000.0 + 200_000.0) / 30_000_000.0


def test_an_empty_fee_is_not_a_free_broker() -> None:
    """Ноль при непустой ставке — «не заполнено», а не «даром»."""
    assert "fee_unknown" in script()
    assert "не заполнено" in script()


def test_one_path_to_platon_for_the_whole_cabinet() -> None:
    """Копия опроса по номеру была бы вторым местом, где чинят обрыв ответа."""
    body = script()
    assert body.count("/agent/result/") == 1, "опрос по номеру запуска объявлен один раз"
    assert "async function platoAnswer(" in body
    assert "await platoAnswer(" in body


def test_platon_reads_the_numbers_and_does_not_recount_them() -> None:
    """Числа считает движок; темы разбора живут в подсказках диалога."""
    body = script()
    ask = body[body.index("async function askPlatoSales("):]
    ask = ask[:ask.index("\n}")]
    assert "НЕ пересчитывай" in ask

    asks = body[body.index("const SALES_ASKS=["):]
    asks = asks[:asks.index("\n];")]
    assert "рассрочка" in asks and "брокер" in asks.lower()
    assert "собственного отдела" in asks or "отдела продаж" in asks
