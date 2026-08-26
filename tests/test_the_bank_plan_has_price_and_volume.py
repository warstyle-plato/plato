"""У плана банка есть цена и объём — я заявил обратное, не посмотрев лист.

«Почему из фин модели банка не взяли цену для сравнения? там же и цена и объём
заданы» (владелец, 26.08.2026). Над строками рассрочки лист держит по каждому
продукту цену и объём, а ниже — пул проекта в метрах и штуках. Заявленное
отсутствие проверяется так же, как заявленное наличие.

И вторая половина той же ошибки: сумму наших договоров я сравнивал со строкой
«Продажи с учётом рассрочки». Это разные величины. Рассрочка — про деньги,
доходящие до эскроу; сумме договоров соответствует валовое «цена × объём».
"""
from __future__ import annotations

from pathlib import Path

import pytest

from market_search import contracting

SOURCE = Path(__file__).resolve().parent.parent / "market_search" / "contracting.py"


def test_the_price_row_pairs_with_the_volume_row_below_it() -> None:
    body = SOURCE.read_text()
    block = body[body.index("    # Пары «цена / объём» берутся ПОЗИЦИОННО"):]
    block = block[:block.index("    # Пул проекта стоит")]
    assert "_BANK_VOLUME_PREFIX" in block, "объём опознаётся своей подписью"
    # Первая пара, а не последняя: ниже стоит блок «Факт» с теми же подписями и
    # нулями, и «последняя выигрывает» подменяла план фактом.
    assert "if name in products:" in block and "continue" in block


def test_the_pool_table_does_not_overwrite_the_price() -> None:
    """«Квартиры, м2» лежит в колонках первых кварталов и начинается тем же словом."""
    body = SOURCE.read_text()
    block = body[body.index("    # Пул проекта стоит"):body.index("    # Валовые продажи плана")]
    assert '"м2" in titles and "шт" in titles' in block, "пул ищется по своей шапке"


def test_gross_is_price_times_volume_not_the_installment_row() -> None:
    """Две разные величины под одним словом «план» — на этом мы уже обжигались."""
    body = SOURCE.read_text()
    block = body[body.index("    # Валовые продажи плана"):body.index("    return {\"sheet\": BANK_SHEET")]
    assert "metres * rate" in block
    assert "учётом рассрочки" in block, "почему это разные строки — сказано"
    compare = body[body.index("def plan_comparison("):body.index("# ------", body.index("def plan_comparison("))]
    assert '"bank_amount": bank_gross.get(name)' in compare, "с суммой договоров сравнивается валовое"
    assert '"bank_cash": bank_cash.get(name)' in compare, "касса банка остаётся рядом, а не пропадает"


def test_the_price_compared_is_the_price_of_the_same_goods() -> None:
    """Общая цена метра мешает паркинг с жильём и даёт третье число."""
    body = SOURCE.read_text()
    assert 'price_plan = dict((products.get("Квартира") or {}).get("price") or {})' in body
    assert '"by_quarter_flats"' in body, "наш факт по квартирам считает сервер"
    assert 'item["price_flats"]' in body, "и помесячно тоже"


def test_the_thousands_of_the_bank_sheet_are_converted_once() -> None:
    body = SOURCE.read_text()
    block = body[body.index("    # Пары «цена / объём» берутся ПОЗИЦИОННО"):]
    block = block[:block.index("    # Пул проекта стоит")]
    assert "value * 1000.0" in block, "цена листа в тысячах, свод в рублях"


def test_a_missing_bank_block_is_not_a_zero() -> None:
    """Пустой план банка даёт отсутствие линии, а не линию по нулю."""
    summary = {"by_quarter": [{"quarter": "2026 Q1", "amount": 100.0, "area": 1.0,
                               "price_per_sqm": 100.0}],
               "by_quarter_flats": {}, "dynamics": [{"month": "2026-01"}],
               "fm_plan": {}, "bank_plan": {}}
    rows = contracting.plan_comparison(summary)["quarters"]
    assert rows and rows[0]["bank_amount"] is None
    assert rows[0]["bank_price"] is None
