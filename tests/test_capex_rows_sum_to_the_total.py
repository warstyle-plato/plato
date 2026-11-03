"""Строки «Структуры затрат по статьям» складываются в «Итого CAPEX».

Итог CAPEX движок складывает из помесячного потока, и в нём есть покупка
(цена + выкуп ЗУ/ОКС). Строки же брались из смет статей, где покупки нет:
у элитного проекта с ценой входа 1 млрд строки давали около 3 млрд при итоге
4,62 (владелец, 15.10.2026). Покупка — статья `purchase` того же словаря
`capex`, что и итог; строка стоит первой, а итог равен сумме строк.

Проверяется отрисованная таблица после настоящего пересчёта: сумма строк
равна итогу с точностью округления, а число каждой строки — число движка по
её ключу (`data-key`), а не по позиции. Суммы меньше 0,1 млрд — в млн ₽.

Запуск: python3 -m pytest tests/test_capex_rows_sum_to_the_total.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import browser  # noqa: E402
import main_legacy as core  # noqa: E402

PORT = 18974
PRICE_MLN = 1000.0
BUYOUT_MLN = 200.0


def test_engine_articles_sum_to_the_total() -> None:
    """Итог движка — сумма его статей, покупка среди них."""
    result = core.calculate(core.CalcRequest(
        inputs={**core.DEFAULT_INPUTS, "purchase_price_mln": PRICE_MLN,
                "land_buyout_mln": BUYOUT_MLN},
        tep=core.TEP_DEFAULT, rates=[]))
    capex = result["capex"]
    rows = sum(value for key, value in capex.items() if key != "total")
    assert rows == pytest.approx(capex["total"], abs=1.0)
    assert capex["total"] == pytest.approx(result["summary"]["capex"], abs=1.0)
    assert capex["purchase"] == pytest.approx((PRICE_MLN + BUYOUT_MLN) * 1e6, abs=1.0)
    assert "purchase" in dict(core._MODEL_CAPEX_LABELS)


PROBE = r"""async ([price, buyout]) => {
  document.getElementById('f_purchase_price_mln').value = price;
  document.getElementById('f_land_buyout_mln').value = buyout;
  let answer = null;
  const fetch0 = window.fetch;
  window.fetch = async (...args) => {
    const response = await fetch0(...args);
    if (String(args[0]).startsWith('/calculate')) {
      response.clone().json().then(body => { answer = body; });
    }
    return response;
  };
  calculate();
  for (let i = 0; i < 300; i++) {
    if (answer && document.querySelector('#capexTable tr[data-key="purchase"]')) break;
    await new Promise(r => setTimeout(r, 100));
  }
  window.fetch = fetch0;
  const rows = [...document.querySelectorAll('#capexTable tr')].map(tr => ({
    key: tr.dataset.key || '', name: tr.children[0].innerText.trim(),
    sum: tr.children[1].innerText.trim()}));
  return {rows, capex: answer ? answer.capex : null};
}"""


def _rub(text: str) -> tuple[float, float]:
    """Подпись суммы в рублях и шаг её округления."""
    number, unit = text.replace(" ", " ").replace(" ₽", "").rsplit(" ", 1)
    value = float(number.replace(" ", "").replace(",", "."))
    decimals = len(number.split(",")[1]) if "," in number else 0
    scale = {"млрд": 1e9, "млн": 1e6}[unit]
    return value * scale, 0.5 * 10 ** -decimals * scale


@pytest.fixture(scope="module")
def table() -> dict:
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    path = browser.chromium_or_skip()
    with browser.serve(core.app, PORT) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            page = engine.new_page(viewport={"width": 1440, "height": 900})
            page.goto(base, wait_until="domcontentloaded")
            browser.wait_for_result(page)
            got = page.evaluate(PROBE, [PRICE_MLN, BUYOUT_MLN])
            page.close()
    assert got["capex"], "страница не получила ответ расчёта"
    assert len(got["rows"]) > 3, got
    return got


def test_purchase_has_its_row(table) -> None:
    names = dict(core._MODEL_CAPEX_LABELS)
    row = next((r for r in table["rows"] if r["key"] == "purchase"), None)
    assert row, [r["name"] for r in table["rows"]]
    assert row["name"] == core.CAPEX_SHORT_NAMES.get("purchase", names["purchase"])
    assert table["rows"][0]["key"] == "purchase"


def test_rows_sum_to_the_total(table) -> None:
    # По подписи, а не по ключу: сумма проверяется и там, где ключей нет.
    body = [r for r in table["rows"] if r["name"] != "Итого CAPEX"]
    total_row = table["rows"][-1]
    assert total_row["name"] == "Итого CAPEX"
    total, total_step = _rub(total_row["sum"])
    parts = [_rub(r["sum"]) for r in body]
    shown = sum(value for value, _ in parts)
    slack = total_step + sum(step for _, step in parts)
    assert abs(shown - total) <= slack, (
        f"строки {shown / 1e9:.3f} млрд ≠ итог {total / 1e9:.3f} млрд: "
        f"{[(r['name'], r['sum']) for r in body]}")


def test_each_row_shows_its_own_article(table) -> None:
    capex = table["capex"]
    names = {key: core.CAPEX_SHORT_NAMES.get(key, name) for key, name in core._MODEL_CAPEX_LABELS}
    for row in table["rows"]:
        if row["key"] == "total":
            continue
        assert row["name"] == names[row["key"]], row
        value, step = _rub(row["sum"])
        assert abs(value - float(capex[row["key"]])) <= step, (row, capex[row["key"]])


def test_small_sums_are_in_millions(table) -> None:
    for row in table["rows"]:
        value, _ = _rub(row["sum"])
        if abs(value) < 1e8:
            assert "млн" in row["sum"], row
