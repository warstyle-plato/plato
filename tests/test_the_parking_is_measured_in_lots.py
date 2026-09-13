"""Машино-место меряется лотами, а пустая площадь — пропуск, а не ноль.

«А где же тот лот 1, который мы убирали из сентября? Он же машиноместо. И если
честно, в машиноместах не метры интересны, а лоты» (владелец, 13.09.2026).

Замер на живой выгрузке в тот день: сентябрь 2026 — один договор на 6,0 млн ₽,
товар «Машиноместо», «Проектная S» пуста. У остальных четырнадцати мест площадь
есть (13,8–18 м²), поэтому товар проходил отбор графика «м²» и сентябрь рисовался
столбиком НУЛЕВОЙ высоты с подсказкой «2026-09: Машиноместо, 0 м²»: проданный лот
на шесть миллионов выглядел как отсутствующий.

Ошибка двойная, и чинится обеими половинами.

1. Мера товара — часть самого товара. Место продаётся штукой: метры у него
   в выгрузке есть, но отвечают не на тот вопрос, а цена его метра ни с чем не
   сравнима. Значит метрами он не меряется вовсе, а цена у него за лот.
2. Проданный лот не бывает нулевой площади: ноль в «Проектной S» — это пропуск
   выгрузки. Сложенный как ноль, он молча занижает метры месяца; нарисованный
   как ноль — читается как измеренная величина.

Запуск: python3 -m pytest tests/test_the_parking_is_measured_in_lots.py -q
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
    """Кутузов Сити в миниатюре: квартиры метрами, места штуками, и один
    сентябрьский лот без заполненной площади — ровно тот, о котором спросили."""
    rows = [deal("Квартира", 40.0, 24_000_000.0),
            deal("Машиноместа", 14.0, 3_600_000.0),
            deal("Машиноместа", 13.8, 3_600_000.0, "2026-05"),
            deal("Машиноместа", 0.0, 6_000_000.0, "2026-09")]
    return contracting.summarise({"rows": rows, "project": "П", "missing": []})


def test_the_measure_belongs_to_the_product() -> None:
    """Мера объявлена там же, где имя товара, и приезжает со сводом.

    Второй список «кто чем меряется» на странице разошёлся бы с первым молча,
    и обе подписи выглядели бы верными.
    """
    assert contracting.product_measure("Машиноместа") == "units"
    assert contracting.product_measure("М/М") == "units"
    assert contracting.product_measure("Кладовые") == "units"
    assert contracting.product_measure("Квартира") == "area"
    assert contracting.product_measure("Коммерческие площади") == "area"
    # Незнакомый товар меряется метрами: выдумывать за источник нечего.
    assert contracting.product_measure("Апартаменты") == "area"
    measures = {p["product"]: p["measure"] for p in summary()["by_product"]}
    assert measures == {"Квартира": "area", "Машиноместо": "units"}, measures


def test_the_price_is_in_the_products_own_measure() -> None:
    """У места цена за лот, у квартиры за метр — и считает её сервер."""
    got = summary()
    parking = next(p for p in got["by_product"] if p["product"] == "Машиноместо")
    flats = next(p for p in got["by_product"] if p["product"] == "Квартира")
    assert parking["price"] == 13_200_000.0 / 3.0
    assert parking["price_per_unit"] == parking["price"]
    assert flats["price"] == 24_000_000.0 / 40.0
    assert flats["price"] == flats["price_per_sqm"]


def test_an_empty_area_is_counted_not_summed_as_zero() -> None:
    """Пустая «Проектная S» названа числом, а не растворена в сумме.

    Без этого числа занижённая площадь выглядит измеренной.
    """
    got = summary()
    september = next(m for m in got["dynamics"] if m["month"] == "2026-09")
    assert september["by_product"]["Машиноместо"]["units"] == 1.0
    assert september["by_product"]["Машиноместо"]["area_unknown"] == 1.0
    assert september["area_unknown"] == 1.0
    # Лот на месте: деньги посчитаны, цена за лот посчитана.
    assert september["by_product"]["Машиноместо"]["amount"] == 6_000_000.0
    assert september["by_product"]["Машиноместо"]["price"] == 6_000_000.0
    assert got["total"]["area_unknown"] == 1.0
    # Заполненные площади считаются как считались.
    assert round(got["total"]["area"], 1) == 67.8


def test_the_conclusion_names_the_measure_and_the_gap() -> None:
    """Свод говорит обе вещи словами: чем меряется товар и чего не хватает."""
    said = contracting.conclusions(summary()).get("products") or ""
    assert "Машиноместо продаётся штукой" in said, said
    assert "лоты, а не метры" in said, said
    assert "Проектная S" in said, said
    assert "а не ноль" in said, said
    # Число согласовано с существительным: «у 1 договора … его метры».
    assert "У 1 договора" in said, said
    assert "его метры" in said, said


def _draw(metric: str, payload: dict) -> str:
    """Отрисовать «Динамику» настоящим `renderSales`: в исходнике сломанный и
    починенный экран выглядят одинаково."""
    import pytest

    play = pytest.importorskip("playwright.sync_api")

    import browser_launch

    page = cabinet_page("sales").replace("__DEVELOPAID_VERSION__", "test")
    file = Path(__file__).resolve().parent / f"_parking_page_{metric}.html"
    file.write_text(page, encoding="utf-8")
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
                html = tab.evaluate(
                    """([d, metric]) => { let box=document.querySelector('#sales');
                       if(!box){ box=document.createElement('div'); box.id='sales';
                                 document.body.appendChild(box); }
                       salesMetric=metric; renderSales(d);
                       const chart=document.querySelector('#saleschart');
                       return chart ? chart.innerHTML : ''; }""",
                    [payload, metric])
                tab.close()
            finally:
                browser.close()
    finally:
        file.unlink(missing_ok=True)
    assert not errors, errors
    return html.split("printviews")[0]


def _payload(got: dict) -> dict:
    return {"project": "Кутузов Сити", "total": got["total"], "dynamics": got["dynamics"],
            "by_product": got["by_product"], "product_order": got["product_order"],
            "by_payment": [], "by_channel": [], "by_size": [], "by_rooms": [],
            "terminated": [], "sources": [], "conclusions": {}}


def test_the_metres_view_leaves_the_parking_out_and_says_so() -> None:
    """В «м²» машино-мест нет — и сказано, где они.

    Молча снятый товар читается как его отсутствие в продажах.
    """
    seen = _draw("area", _payload(summary()))
    assert seen.count("<svg") == 1, seen.count("<svg")
    assert "Квартира · м²" in seen, seen[:600]
    # Ни одного нулевого столбика машино-места — того самого, из-за которого
    # проданный на 6 млн лот выглядел отсутствующим.
    assert "Машиноместо, 0 " not in seen, seen
    assert "продаётся штукой" in seen, seen[-1200:]
    assert "во вкладке «лоты»" in seen, seen[-1200:]


def test_the_lots_view_shows_the_september_deal() -> None:
    """В «лотах» сентябрьский лот на месте и подписан своим товаром."""
    seen = _draw("units", _payload(summary()))
    assert 'data-tip="2026-09: Машиноместо, 1 лоты"' in seen, seen
    # Цена этого товара подписана его мерой, а не чужой.
    assert "цена, ₽ за лот" in seen, seen[:1500]
    assert "цена, ₽/м²" not in seen.split("Квартира")[0], seen[:1500]


def test_a_lot_without_an_area_is_a_gap_not_a_zero() -> None:
    """Квартира без заполненной площади рвёт линию метров, а не рисует ноль.

    После того как машино-места ушли из «м²», та же пустая ячейка может
    прийти на квартире — и тогда молчаливый ноль занизит метры месяца.
    """
    rows = [deal("Квартира", 40.0, 24_000_000.0),
            deal("Квартира", 0.0, 30_000_000.0, "2026-02"),
            deal("Квартира", 50.0, 35_000_000.0, "2026-03")]
    got = contracting.summarise({"rows": rows, "project": "П", "missing": []})
    seen = _draw("area", _payload(got))
    # Ноля нет, столбика нет — а раз столбика нет, то и подсказки: пропуск
    # называется под графиком, иначе он неотличим от «товара не продавали».
    assert 'data-tip="2026-02: Квартира, 0 ' not in seen, seen
    assert "2026-02" not in seen.split("<details")[0], seen.split("<details")[0]
    assert "площадь в выгрузке не заполнена" in seen, seen[-1200:]
    assert "его месяц стоит пропуском, а не нулём" in seen, seen[-1200:]
    # Соседние месяцы нарисованы как были.
    assert 'data-tip="2026-01: Квартира, 40 м²"' in seen, seen
    # В «лотах» тот же договор на месте — он продан, просто без метров.
    lots = _draw("units", _payload(got))
    assert 'data-tip="2026-02: Квартира, 1 лоты"' in lots, lots
    assert "площадь в выгрузке не заполнена" not in lots, lots[-800:]


def test_the_products_table_prices_each_product_in_its_measure() -> None:
    """Таблица «Продукты» не подписывает деньги места чужой единицей."""
    import pytest

    play = pytest.importorskip("playwright.sync_api")
    import browser_launch

    page = cabinet_page("sales").replace("__DEVELOPAID_VERSION__", "test")
    file = Path(__file__).resolve().parent / "_parking_page_products.html"
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
                       renderSales(d);
                       const s=document.querySelector('#sb-prod');
                       return s ? s.innerHTML : ''; }""",
                    _payload(summary()))
                tab.close()
            finally:
                browser.close()
    finally:
        file.unlink(missing_ok=True)
    assert "₽ за лот" in seen, seen
    assert "₽/м²" in seen, seen
