"""«Лоты» в динамике продаж — это не только квартиры, и столбик это говорит.

«Почему в отчёт о продажах Кутузов в лоты вместо квартир попало машиноместо»
(владелец, 12.09.2026). Метрика «лоты» складывала ВСЕ договоры месяца: на
живой выгрузке январь 2026 это 9 «лотов» из четырёх квартир и пяти
машино-мест, май — 9 из двух квартир, шести коммерческих помещений и одного
машино-места. То же делала метрика «м²»: 208,9 м² машино-мест и 281,2 м²
коммерции складывались с 3 173,1 м² квартир.

Для цены это правило уже применено — у неё своя линия квартир (`price_flats`);
объём его ждал. Рубли складываются законно, поэтому итог столбика остаётся
суммой, а слои называют, чем он набран.

Запуск: python3 -m pytest tests/test_the_lots_bar_is_split_by_product.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from market_search import contracting  # noqa: E402
from market_search.cabinet import cabinet_page  # noqa: E402


def deal(product: str, area: float, amount: float, month: str = "2026-01") -> dict:
    return {"month": month, "signed": f"{month}-05", "product": product,
            "unit": "", "kind": "", "rooms": "", "area": area, "contract": "1",
            "contract_type": "ДДУ", "state": "Действующий", "amount": amount,
            "units": 1.0, "payment_variant": "", "broker": "", "broker_fee": 0.0,
            "broker_rate": None, "sales_bonus_paid": 0.0, "escrow_paid": 0.0,
            "company_buyer": False, "escrow_schedule": []}


def summary() -> dict:
    rows = [deal("Квартира", 40.0, 24_000_000.0),
            deal("Квартира", 60.0, 36_000_000.0),
            deal("Машиноместа", 14.0, 4_000_000.0),
            deal("Машиноместа", 14.0, 4_000_000.0),
            deal("Коммерческие площади", 50.0, 38_000_000.0, "2026-02")]
    return contracting.summarise({"rows": rows, "project": "П", "missing": []})


def test_a_month_carries_its_product_mix() -> None:
    """Месяц несёт состав, а не только итог: без него слой рисовать нечем."""
    month = next(m for m in summary()["dynamics"] if m["month"] == "2026-01")
    mix = {name: item["units"] for name, item in month["by_product"].items()}
    assert mix == {"Квартира": 2.0, "Машиноместо": 2.0}, mix
    # Итог остаётся суммой — рубли и штуки складываются, вопрос был в подписи.
    assert month["units"] == 4.0
    assert month["area"] == 128.0


def test_one_product_is_called_by_one_name() -> None:
    """CRM пишет «Машиноместа», план «Машиноместо» — на экране имя одно.

    Под двумя именами один товар стоял на одном экране дважды: раздел
    «Продукты» звал его так, плитка пула иначе.
    """
    got = summary()
    names = [item["product"] for item in got["by_product"]]
    assert "Машиноместо" in names, names
    assert "Машиноместа" not in names, names


def test_the_product_order_is_declared_once() -> None:
    """Порядок слоёв один на весь свод: посчитанный в каждом месяце заново,
    он красил бы продукт то одним цветом, то другим."""
    got = summary()
    assert got["product_order"] == [item["product"] for item in got["by_product"]]
    assert got["product_order"][0] == "Квартира"


def test_the_bar_is_drawn_in_layers_and_the_legend_names_them() -> None:
    """Столбик разложен НА ЭКРАНЕ, а не только в рисовальщике.

    Тест, зовущий рисовальщик, доказывает, что слой рисуется, — не что он в
    отчёте: на этом уже попадались условия рынка. Поэтому зовётся весь
    `renderSales`, а слои считаются по отрисованному.
    """
    import pytest

    play = pytest.importorskip("playwright.sync_api")

    import browser_launch

    page = cabinet_page("sales").replace("__DEVELOPAID_VERSION__", "test")
    file = Path(__file__).resolve().parent / "_lots_page.html"
    file.write_text(page, encoding="utf-8")
    got = summary()
    payload = {
        "project": "Кутузов Сити", "total": got["total"], "dynamics": got["dynamics"],
        "by_product": got["by_product"], "product_order": got["product_order"],
        "by_payment": [], "by_channel": [], "by_size": [], "by_rooms": [],
        "terminated": [], "sources": [], "conclusions": {},
    }
    # Тот же свод с одним продуктом: слои и легенда обязаны исчезнуть — «слой»
    # из одного куска обещает состав, которого нет.
    only_flats = contracting.summarise({"rows": [deal("Квартира", 40.0, 24_000_000.0)],
                                        "project": "П", "missing": []})
    single = {**payload, "dynamics": only_flats["dynamics"],
              "by_product": only_flats["by_product"],
              "product_order": only_flats["product_order"]}
    try:
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
                draw = """d => { let box=document.querySelector('#sales');
                          if(!box){ box=document.createElement('div'); box.id='sales';
                                    document.body.appendChild(box); }
                          salesMetric='units'; renderSales(d);
                          const sec=document.querySelector('#sb-dyn');
                          return sec ? sec.innerHTML : ''; }"""
                mixed = tab.evaluate(draw, payload)
                alone = tab.evaluate(draw, single)
                tab.close()
            finally:
                browser.close()
    finally:
        file.unlink(missing_ok=True)
    assert not errors, errors
    # Слой назван своим продуктом. Считать надо ИМЕННО слои январского
    # столбика: сравнение «прямоугольников стало больше» проходило бы и на
    # выключенных слоях — там просто месяцев было больше.
    layers = mixed.count('data-tip="2026-01 &#183; ') + mixed.count('data-tip="2026-01 · ')
    assert layers >= 2, f"январский столбик не разложен: слоёв {layers}"
    assert "Машиноместо" in mixed, mixed[-1200:]
    assert "столбик разложен по продуктам" in mixed
    # Один продукт — ни легенды продуктов, ни обещания состава: «слой» из
    # одного куска обещает состав, которого нет.
    assert "столбик разложен по продуктам" not in alone
    assert alone.count('data-tip="2026-01 · ') == 0
