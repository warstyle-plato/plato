"""Статьи «Структуры затрат по статьям» стоят в порядке смысла, а не хеша.

Статьи расходов по очередям складывал `_sum_dicts`, и ключи он перебирал
через `set`. Порядок множества строк зависит от сида хеша процесса: на экране
«ИРД» стояла рядом с «Процентами по рассрочке ВРИ», «Офисы» — между «Резервом»
и «Управлением проектом», и от перезапуска к перезапуску по-разному. Между
статьями стояли нули («Офисы 2 — 0 млрд ₽»). Замечание владельца 28.09.2026,
находка S9 ревизии docs/ui_audit_2026-09-27.md.

Порядок статей один — список движка `_MODEL_CAPEX_LABELS` (земля → ИРД и
проект → снос → СМР → объекты → соцнагрузка → надбавки → резерв); страница
получает его подстановкой вместе с именами. Проверяется отрисованная таблица
после настоящего пересчёта, а не литерал.

Запуск: python3 -m pytest tests/test_cost_articles_keep_their_order.py -q
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

PORT = 18973

ORDER = [key for key, _ in core._MODEL_CAPEX_LABELS]
NAMES = {key: core.CAPEX_SHORT_NAMES.get(key, name) for key, name in core._MODEL_CAPEX_LABELS}


def test_summing_keeps_the_order_keys_came_in() -> None:
    """Двадцать ключей: совпасть с порядком множества случайно им не дано."""
    keys = [f"article_{i:02d}" for i in range(20)]
    first = {key: 1.0 for key in keys[:12]}
    second = {key: 2.0 for key in keys[8:]}
    summed = core._sum_dicts([first, second])
    assert list(summed) == keys + ["total"]
    assert summed["article_09"] == pytest.approx(3.0)


PROBE = r"""async () => {
  calculate();
  for (let i = 0; i < 200; i++) {
    if (document.querySelectorAll('#capexTable tr').length > 1) break;
    await new Promise(r => setTimeout(r, 100));
  }
  return [...document.querySelectorAll('#capexTable tr')].map(tr => {
    const cells = [...tr.children].map(td => td.innerText.trim());
    return {name: cells[0], sum: cells[1]};
  });
}"""


@pytest.fixture(scope="module")
def rows() -> list[dict]:
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    path = browser.chromium_or_skip()
    with browser.serve(core.app, PORT) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            page = engine.new_page(viewport={"width": 1440, "height": 900})
            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_timeout(1500)
            got = page.evaluate(PROBE)
            page.close()
    assert len(got) > 3, got
    return got


def test_articles_follow_the_engine_order(rows) -> None:
    body = [row["name"] for row in rows if not row["name"].startswith("Итого")]
    rank = {NAMES[key]: i for i, key in enumerate(ORDER)}
    unknown = [name for name in body if name not in rank]
    assert not unknown, f"статьи без места в порядке движка: {unknown}"
    ranks = [rank[name] for name in body]
    assert ranks == sorted(ranks), f"статьи не по порядку: {body}"


def test_zero_articles_take_no_row(rows) -> None:
    zeros = [row["name"] for row in rows
             if not row["name"].startswith("Итого") and row["sum"].startswith("0 ")]
    assert not zeros, f"нулевые статьи в таблице: {zeros}"


def test_the_total_stays_last(rows) -> None:
    assert rows[-1]["name"] == "Итого CAPEX"
