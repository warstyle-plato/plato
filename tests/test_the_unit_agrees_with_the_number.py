"""Единица при числе склоняется: «6 лотов», а не «6 лоты».

«2026-05: Коммерческие площади, 6 лоты» (экран владельца, 13.09.2026).
Подсказка столбика склеивала число с ИМЕНЕМ МЕРЫ, а имя меры — это подпись
вкладки и легенды («Ищем: лоты»), не единица при числе. У «млн ₽» и «м²» обе
формы совпадают, и потому ошибку было не видно, пока мер было две.

Запуск: python3 -m pytest tests/test_the_unit_agrees_with_the_number.py -q
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from market_search import contracting  # noqa: E402
from market_search.cabinet import cabinet_page  # noqa: E402


def _piece(name: str) -> str:
    """Кусок страницы от объявления функции до её закрывающей скобки.

    Границей служат скобки, а не соседняя строка: сосед переписывается, и
    тогда проверка падает, ничего не сказав о том, что сломалось.
    """
    page = cabinet_page("sales")
    start = page.index(f"function {name}(")
    depth = 0
    seen = False
    for i in range(start, len(page)):
        if page[i] == "{":
            depth += 1
            seen = True
        elif page[i] == "}":
            depth -= 1
            if seen and depth == 0:
                return page[start:i + 1]
    raise AssertionError(f"не нашёл тела функции {name}")


def _run(js: str) -> str:
    src = _piece("ruPlural") + "\n" + js
    got = subprocess.run([  # noqa: S603,S607
        "node", "-e", src], capture_output=True, text=True, timeout=60)
    assert got.returncode == 0, got.stderr
    return got.stdout.strip()


def test_the_lot_word_follows_the_number() -> None:
    """Русское правило целиком, вместе с одиннадцатью и двадцать одним."""
    script = """
      const out=[];
      for (const n of [0,1,2,4,5,6,11,12,14,21,22,25,101,111,112])
        out.push(n + ' ' + ruPlural(n,'лот','лота','лотов'));
      console.log(out.join('\\n'));
    """
    said = dict(line.split(" ", 1) for line in _run(script).splitlines())
    assert said["1"] == "лот", said
    assert said["21"] == "лот", said
    assert said["101"] == "лот", said
    assert said["2"] == "лота" and said["4"] == "лота", said
    assert said["22"] == "лота", said
    assert said["5"] == "лотов" and said["6"] == "лотов", said
    # Одиннадцать–четырнадцать — исключение, и на нём ломается наивное правило.
    assert said["11"] == "лотов", said
    assert said["12"] == "лотов", said
    assert said["14"] == "лотов", said
    assert said["111"] == "лотов" and said["112"] == "лотов", said
    assert said["0"] == "лотов", said


def test_only_the_declining_measure_declares_a_unit() -> None:
    """У «млн ₽» и «м²» единица совпадает с именем — своей формы им не нужно.

    Лишняя форма там, где склонения нет, — это второй ответ на тот же вопрос.
    Набор мер берётся со страницы, а не переписывается сюда: копия разошлась
    бы с оригиналом молча.
    """
    page = cabinet_page("sales")
    start = page.index("const SALES_METRICS=[")
    literal = page[start:page.index("];", start) + 2]
    said = _run(literal + """
      console.log(SALES_METRICS.map(m=>m.key+':'+(m.unit?m.unit(6):'нет')).join(' '));
    """)
    assert "units:лотов" in said, said
    assert "amount:нет" in said, said
    assert "area:нет" in said, said


def _deal(product: str, area: float, amount: float, month: str) -> dict:
    return {"month": month, "signed": f"{month}-05", "product": product,
            "unit": "", "kind": "", "rooms": "", "area": area, "contract": "1",
            "contract_type": "ДДУ", "state": "Действующий", "amount": amount,
            "units": 1.0, "payment_variant": "", "broker": "", "broker_fee": 0.0,
            "broker_rate": None, "sales_bonus_paid": 0.0, "escrow_paid": 0.0,
            "company_buyer": False, "escrow_schedule": []}


def test_the_drawn_tooltip_agrees_too() -> None:
    """Проверяем то, что видно: подсказку настоящего графика в Chromium.

    В исходнике сломанная и починенная страница выглядят одинаково — склейка
    числа со словом стоит в одной строке и там, и там.
    """
    import pytest

    play = pytest.importorskip("playwright.sync_api")

    import browser_launch

    rows = [_deal("Коммерческие площади", 50.0, 38_000_000.0, "2026-05")
            for _ in range(6)]
    rows += [_deal("Квартира", 40.0, 24_000_000.0, "2026-01"),
             _deal("Квартира", 45.0, 27_000_000.0, "2026-01")]
    got = contracting.summarise({"rows": rows, "project": "П", "missing": []})
    payload = {"project": "П", "total": got["total"], "dynamics": got["dynamics"],
               "by_product": got["by_product"], "product_order": got["product_order"],
               "by_payment": [], "by_channel": [], "by_size": [], "by_rooms": [],
               "terminated": [], "sources": [], "conclusions": {}}

    page = cabinet_page("sales").replace("__DEVELOPAID_VERSION__", "test")
    file = Path(__file__).resolve().parent / "_unit_page.html"
    file.write_text(page, encoding="utf-8")
    try:
        with play.sync_playwright() as pw:
            try:
                browser = browser_launch.launch(pw)
            except Exception as exc:  # noqa: BLE001
                pytest.skip(f"Chromium недоступен: {exc}")
            try:
                tab = browser.new_page()
                tab.route("**/*", lambda route: route.abort()
                          if route.request.url.startswith("http") else route.continue_())
                tab.goto(file.as_uri())
                seen = tab.evaluate(
                    """(d) => { let box=document.querySelector('#sales');
                       if(!box){ box=document.createElement('div'); box.id='sales';
                                 document.body.appendChild(box); }
                       salesMetric='units'; renderSales(d);
                       const chart=document.querySelector('#saleschart');
                       return chart ? chart.innerHTML : ''; }""",
                    payload)
                tab.close()
            finally:
                browser.close()
    finally:
        file.unlink(missing_ok=True)
    seen = seen.split("printviews")[0]
    assert "6 лотов" in seen, seen
    assert "2 лота" in seen, seen
    assert "6 лоты" not in seen, seen
    assert "2 лоты" not in seen, seen
