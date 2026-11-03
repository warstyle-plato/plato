"""«Структура выручки»: у продукта — доля в выручке, удельная — у итогов.

Каждая строка продукта делилась на продаваемую площадь ВСЕГО проекта: у
элитного проекта «Донской» (владелец, 15.10.2026, файл настроек в
tests/fixtures) коммерция 1 этажа при цене 1 790 тыс ₽/м² читалась как 85,
квартиры — 1 762 вместо 1 850. Цена продукта на свою базу уже есть —
«Средняя цена» в «Темпах и ценах продаж», и владелец решил её не повторять:
у строки продукта — доля в выручке, а на продаваемую проекта делятся только
итоги, которым эта база принадлежит.

Проверяется отрисованная таблица после настоящего пересчёта с файла
владельца, загруженного тем же путём, что «Загрузить настройки».

Запуск: python3 -m pytest tests/test_revenue_rows_show_their_share.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import browser  # noqa: E402
import main_legacy as core  # noqa: E402

PORT = 18975
SETTINGS = json.loads((ROOT / "tests" / "fixtures" / "project_settings_donskoy_0_25_78.json")
                      .read_text(encoding="utf-8"))

PROBE = r"""async (data) => {
  applyProjectSnapshot(data);
  let answer = null;
  const fetch0 = window.fetch;
  window.fetch = async (...args) => {
    const response = await fetch0(...args);
    if (String(args[0]).startsWith('/calculate')) {
      response.clone().json().then(body => { answer = body; });
    }
    return response;
  };
  await settledCalculate();
  for (let i = 0; i < 300 && !answer; i++) await new Promise(r => setTimeout(r, 100));
  window.fetch = fetch0;
  const text = el => (el.innerText || '').replace(/\s+/g, ' ').trim();
  return {
    rows: [...document.querySelectorAll('#revenueTable tr')].map(tr => ({
      key: tr.dataset.key || '', role: tr.dataset.role || '',
      cells: [...tr.children].map(text)})),
    products: answer ? answer.report.products : null,
  };
}"""


def _num(text: str) -> float:
    return float(text.replace(" ", "").replace(" ", "").replace(",", "."))


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
            got = page.evaluate(PROBE, SETTINGS)
            page.close()
    assert got["products"], "страница не получила ответ расчёта"
    return got


def _pct(text: str) -> float:
    return _num(text.rstrip("%")) / 100


def test_product_rows_show_their_share(table) -> None:
    products = {p["key"]: p for p in table["products"]}
    parts = [r for r in table["rows"] if r["role"] == "part"]
    assert {r["key"] for r in parts} >= {"apartments", "ground_commercial",
                                         "underground_parking", "storage"}, parts
    total = sum(p["revenue"] for p in products.values() if p.get("sellable"))
    for row in parts:
        assert _pct(row["cells"][2]) == pytest.approx(
            products[row["key"]]["revenue"] / total, abs=0.0001), row
        # Чужой базы у строки продукта нет: метр проекта — не его метр.
        assert row["cells"][3] == "—", row


def test_totals_are_on_the_project_saleable(table) -> None:
    totals = [r for r in table["rows"] if r["role"] == "total"]
    assert totals, table["rows"]
    whole = totals[-1]
    assert _pct(whole["cells"][2]) == pytest.approx(1.0)
    # 7,34 млрд на 3 562 м² продаваемой проекта (3 392 + 170).
    assert _num(whole["cells"][3]) == pytest.approx(2061.84, abs=0.01), whole
