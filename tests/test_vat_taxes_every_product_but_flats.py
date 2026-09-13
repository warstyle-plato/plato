"""База НДС — вся выручка, кроме квартир, и она не перечисляется списком.

Движок брал облагаемые продукты перечислением двух пулов — `core_products` и
объекты КРТ. Паркинг отдельно стоящих объектов завели позже обоих (06.09.2026)
и ни в один не вписали: 166,0 млн его выручки выпадали из базы, а с ними
4,7 млн налога. Книга при этом считала верно и без списка — вся выручка минус
строка квартир, — и расхождение выходило в строке чистой прибыли ПРОВЕРОК при
совпадающих до сотой доли CAPEX, выручке и EBITDA. Ошибка того же рода, что
«корзина, заведённая позже, в счётчик не попадает».

Закреплено:
- облагается всё, кроме квартир (пп. 22-23 п. 3 ст. 149 НК);
- база берётся из самих графиков выручки, а не из перечня продуктов, — иначе
  следующий продукт выпадет так же молча;
- у сценария есть предохранитель: паркинг объектов обязан продаваться, иначе
  проверка зелена на сломанном коде.

Запуск: python3 -m pytest tests/test_vat_taxes_every_product_but_flats.py -q
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402


def _inputs() -> dict:
    x = copy.deepcopy(core.DEFAULT_INPUTS)
    x.update(offices_enabled=True, retail_enabled=True,
             offices_parking_under_spaces=80, offices_parking_over_spaces=20,
             retail_parking_under_spaces=60,
             parking_k1=1.0, parking_k2=0.5)
    return x


@pytest.fixture(scope="module")
def report() -> dict:
    return core.calculate(core.CalcRequest(
        inputs=_inputs(), tep=copy.deepcopy(core.TEP_DEFAULT), rates=[]))


def _revenue(report: dict) -> dict[str, float]:
    return {row.get("key"): float(row.get("revenue") or 0.0)
            for row in report["report"].get("products", [])}


def test_the_scenario_actually_sells_the_object_parking(report: dict) -> None:
    """Предохранитель: без выручки паркинга объектов проверка ниже пуста."""
    assert _revenue(report).get("object_parking", 0.0) > 100e6, (
        "паркинг отдельно стоящих объектов не продаётся — сценарий ничего не ловит")


def test_the_vat_base_is_every_product_but_the_flats(report: dict) -> None:
    """Начисленный НДС считается со всей выручки, кроме квартир."""
    finance = report["finance"]
    rate = float(core.DEFAULT_INPUTS["vat_pct"]) / 100
    charged = float(finance["vat_charged"])
    taxable = charged / (rate / (1 + rate))
    revenue = _revenue(report)
    expected = sum(value for key, value in revenue.items() if key != "apartments")
    assert taxable == pytest.approx(expected, rel=1e-6), (
        f"в базе НДС {taxable / 1e6:.1f} млн, а нежилой выручки "
        f"{expected / 1e6:.1f} млн — продукт выпал из базы")
    assert revenue["apartments"] > 0, "квартиры обязаны продаваться: они и освобождены"


def test_the_base_is_taken_from_the_revenue_itself_not_from_a_list() -> None:
    """Перечня продуктов в базе НДС нет: следующий выпал бы так же молча."""
    source = Path(core.__file__).read_text(encoding="utf-8")
    at = source.find("vat_taxable_products = tuple(")
    assert at > 0, "база НДС объявлена не там, где её искали"
    block = source[at:at + 200]
    assert "revenue_schedules" in block, (
        "база НДС снова собирается перечислением пулов, а не ключами выручки")
    assert "core_products" not in block and "krt_products" not in block
