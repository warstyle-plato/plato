"""«Структура выручки» (вкладка «Доходы») читается группами, без нулей.

Снимок владельца с прода (телефон, 28.09.2026): строки шли в порядке словаря
движка — «Паркинг — ТЦ» с нулём первым, офисы посреди кладовых, семь строк
«0 млрд ₽» между настоящими. Порядок теперь решает движок
(`revenue_structure` → `product_groups`, тот же, что у сравнения очередей):
МКД → Итого МКД → объекты в порядке реестра, каждый со своим паркингом →
Итого ОСЗ → Итого.

Проверяется отрисованное: Chromium на живой странице при 390 px исполняет
настоящую `renderResult` на результате очередей.

Запуск: python3 -m pytest tests/test_the_revenue_structure_reads_in_groups.py -q
"""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import main_legacy as core  # noqa: E402
from browser import chromium_or_skip  # noqa: E402
from test_object_parking_reaches_the_queue import _phased  # noqa: E402

PORT = 18937


@pytest.fixture(scope="module")
def consolidated() -> dict:
    sys.setrecursionlimit(400000)
    return json.loads(json.dumps(_phased(), default=str))["consolidated"]


def _expected(revenue: dict) -> list[str]:
    """Порядок, выведенный из реестров напрямую, а не из проверяемой функции."""
    labels = core.product_labels()
    sold = {k for k, v in revenue.items() if k != "total" and abs(float(v or 0)) > 0.5}
    mkd = [k for k in core.MKD_PRODUCTS if k in sold]
    osz = []
    for o in core.STANDALONE_OBJECTS:
        for k in (o.key, core.OBJECT_PARKING_PRODUCT_KEYS.get(o.key, "")):
            if k in sold:
                osz.append(k)
    osz += sorted(sold - set(mkd) - set(osz))
    out = [labels.get(k, k) for k in mkd] + (["Итого МКД"] if len(mkd) > 1 else [])
    out += [labels.get(k, k) for k in osz] + (["Итого ОСЗ"] if len(osz) > 1 else [])
    return out + ["Итого"]


def test_the_engine_orders_groups_and_drops_zeros(consolidated) -> None:
    revenue = consolidated["revenue"]
    rows = consolidated["revenue_structure"]["rows"]
    assert [r["label"] for r in rows] == _expected(revenue)
    assert any(abs(float(v or 0)) <= 0.5 for k, v in revenue.items() if k != "total"), (
        "на вводных нет нулевого продукта — проверка нулей ничего не доказывает")
    for group in ("mkd", "osz"):
        parts = [r["value"] for r in rows if r["group"] == group and r["role"] == "part"]
        totals = [r["value"] for r in rows if r["group"] == group and r["role"] == "total"]
        if totals:
            assert totals[0] == pytest.approx(sum(parts), abs=1.0)
    assert rows[-1]["value"] == pytest.approx(consolidated["summary"]["revenue"], abs=1.0)


def _server():
    import uvicorn

    server = uvicorn.Server(uvicorn.Config(core.app, host="127.0.0.1", port=PORT,
                                           log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started
    return server


@pytest.fixture(scope="module")
def server():
    chromium_or_skip()
    srv = _server()
    yield srv
    srv.should_exit = True


@pytest.mark.timeout(300)
def test_the_rendered_table_reads_in_groups_on_a_phone(consolidated, server) -> None:
    from playwright.sync_api import sync_playwright

    chrome = chromium_or_skip()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chrome))
        page = browser.new_page(viewport={"width": 390, "height": 900})
        page.goto(f"http://127.0.0.1:{PORT}/", wait_until="domcontentloaded")
        page.wait_for_function("typeof renderResult==='function'")
        got = page.evaluate(
            "r=>{lastResult=r;try{renderResult()}catch(e){}"
            "return [...document.querySelectorAll('#revenueTable tr')].map(t=>({"
            "label:t.cells[0].innerText.trim(),value:t.cells[1].innerText.trim(),"
            "weight:+getComputedStyle(t.cells[1]).fontWeight}))}", consolidated)
        browser.close()
    assert [r["label"] for r in got] == _expected(consolidated["revenue"]), got
    assert not [r for r in got if r["value"].startswith("0 ")], got
    for r in got:
        if r["label"].startswith("Итого"):
            assert r["weight"] >= 700, r
