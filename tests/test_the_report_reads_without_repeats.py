"""Отчёт читается без повторов и в порядке смысла (ревизия интерфейса, пакет «Отчёт»).

Находки docs/ui_audit_2026-09-27.md, которые закрывает этот набор:

* **S7** — десять строк ставок стояли в обеих карточках раздела
  «Финансирование», а пики, лимит, проценты и LLCR — ещё раз в «Ставках».
  Теперь «Финансирование» — лимиты, пики и итог долга, «Ставки
  финансирования» — только ставки.
* **S33** — НДС стоял после налога на прибыль и читался платой из чистой
  прибыли. Теперь «НДС к уплате» идёт перед налогом — в порядке, в каком его
  вычитает база налога. Числа те же.
* **S10** — «Структура выручки» шла в порядке ключей ответа (паркинг первым,
  квартиры четвёртыми) и с нулевыми строками.
* **S17** — плитка «Цена приобретения» писала «0 млрд ₽» там, где цена не
  задана.
* **S5** — средняя цена квартиры выходила «0,03 млрд ₽».

Строки продаваемого, но в этом расчёте непроданного продукта в «Темпах и ценах
продаж» остаются намеренно: «ничего не продал» — не «не продаётся»
(tests/test_the_sales_table_does_not_sell_a_kindergarten.py).

Проверяется отрисованная страница после настоящего пересчёта.

Запуск: python3 -m pytest tests/test_the_report_reads_without_repeats.py -q
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

PORT = 18977

PROBE = r"""async () => {
  inputs.purchase_price_mln = 0;
  calculate();
  for (let i = 0; i < 200; i++) {
    if (document.querySelectorAll('#revenueTable tr').length > 1
        && document.querySelectorAll('#ratesDebtTable tr').length > 1) break;
    await new Promise(r => setTimeout(r, 100));
  }
  const rows = id => [...document.querySelectorAll('#' + id + ' tr')]
    .map(tr => [...tr.children].map(td => td.innerText.trim().replace(/\s+/g, ' ')));
  const kpi = [...document.querySelectorAll('#reportKpi .kpi')]
    .map(k => [k.querySelector('span').innerText.trim(), k.querySelector('b').innerText.trim()]);
  return {
    finance: rows('reportFinanceTable').map(r => r[0]),
    rates: rows('ratesDebtTable').map(r => r[0]),
    economics: rows('economicsTable').map(r => r[0]),
    revenue: rows('revenueTable'),
    pace: rows('apartmentPaceTable'),
    sales: rows('salesReportTable'),
    kpi: kpi,
    order: Object.keys(PRODUCT_LABELS).map(k => PRODUCT_LABELS[k]),
  };
}"""


@pytest.fixture(scope="module")
def seen() -> dict:
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    path = browser.chromium_or_skip()
    errors: list[str] = []
    with browser.serve(core.app, PORT) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            page = engine.new_page(viewport={"width": 1440, "height": 900})
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_timeout(1500)
            got = page.evaluate(PROBE)
            page.close()
    got["errors"] = errors
    return got


def test_the_page_calculates(seen) -> None:
    assert seen["errors"] == [], seen["errors"]
    assert len(seen["revenue"]) > 1 and len(seen["rates"]) > 1


def test_the_two_finance_cards_do_not_repeat_each_other(seen) -> None:
    shared = set(seen["finance"]) & set(seen["rates"])
    assert not shared, f"строки в обеих карточках: {sorted(shared)}"
    assert not [r for r in seen["finance"] if "ставк" in r.lower() or r.startswith("Спред")], seen["finance"]
    assert not [r for r in seen["rates"] if r.startswith(("Пиков", "Лимит", "Проценты", "LLCR"))], seen["rates"]


def test_vat_comes_before_the_profit_tax(seen) -> None:
    rows = seen["economics"]
    assert rows.index("НДС к уплате") < rows.index("Налог на прибыль") < rows.index("Чистая прибыль")
    assert rows.index("Прибыль до налога") < rows.index("НДС к уплате")


def test_revenue_follows_the_product_order_without_zeros(seen) -> None:
    body = [r for r in seen["revenue"] if not r[0].startswith("Итого")]
    rank = {name: i for i, name in enumerate(seen["order"])}
    names = [r[0] for r in body]
    assert all(n in rank for n in names), names
    assert [rank[n] for n in names] == sorted(rank[n] for n in names), names
    zeros = [r[0] for r in body if r[1].startswith("0 ")]
    assert not zeros, f"нулевые продукты в выручке: {zeros}"


def test_an_unset_price_says_so(seen) -> None:
    tiles = dict(seen["kpi"])
    assert tiles["Цена приобретения"] == "не задана", tiles


def test_the_apartment_price_is_in_millions(seen) -> None:
    price = next((r[1] for r in seen["pace"] if r[0] == "Средняя цена квартиры"), None)
    if price is None:
        pytest.skip("в проекте по умолчанию квартир нет")
    assert price.endswith("млн ₽") and not price.startswith("0,"), price
