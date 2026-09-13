"""«Лоты» и «м²» не складываются через товары — у каждого свой график.

«Почему в отчёт о продажах Кутузов в лоты вместо квартир попало машиноместо»
(владелец, 12.09.2026). Метрика «лоты» складывала ВСЕ договоры месяца: на
живой выгрузке январь 2026 это 9 «лотов» из четырёх квартир и пяти
машино-мест, май — 9 из двух квартир, шести коммерческих помещений и одного
машино-места. То же делала метрика «м²»: 208,9 м² машино-мест и 281,2 м²
коммерции складывались с 3 173,1 м² квартир.

Первый ответ — стопка по продуктам — был отвергнут владельцем в тот же день:
«это разные продукты и вводят в заблуждение эксперта». И верно: у стопки та же
общая высота, то есть та же сумма, только нарисованная. Поэтому штуки и метры
идут ПО ТОВАРУ — свой график, своя шкала, своё имя, свои числа, — а вместе
складывается только выручка: у суммы денег есть имя.

Запуск: python3 -m pytest tests/test_the_lots_chart_is_per_product.py -q
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




def test_a_month_carries_its_product_mix_and_its_own_price() -> None:
    """У месяца состав по товарам, и цена метра посчитана ВНУТРИ товара.

    Общая цена метра мешает паркинг с жильём и даёт третье число, не
    сравнимое ни с чем; линия цены на графике товара обязана быть ценой
    этого товара.
    """
    month = next(m for m in summary()["dynamics"] if m["month"] == "2026-01")
    mix = {name: item["units"] for name, item in month["by_product"].items()}
    assert mix == {"Квартира": 2.0, "Машиноместо": 2.0}, mix
    assert month["by_product"]["Квартира"]["price"] == 600_000.0
    assert month["by_product"]["Машиноместо"]["price"] == 8_000_000.0 / 28.0
    # Цена квартир — та же величина, а не второй счёт.
    assert month["price_flats"] == month["by_product"]["Квартира"]["price"]


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
    """Порядок товаров один на весь свод: посчитанный в каждом месяце заново,
    он красил бы товар то одним цветом, то другим."""
    got = summary()
    assert got["product_order"] == [item["product"] for item in got["by_product"]]
    assert got["product_order"][0] == "Квартира"


def _draw(metric: str, payload: dict) -> str:
    """Отрисовать раздел «Динамика» настоящим `renderSales` и вернуть то, что
    видно на экране (без `printviews` — это лист бумаги, не экран)."""
    import pytest

    play = pytest.importorskip("playwright.sync_api")

    import browser_launch

    page = cabinet_page("sales").replace("__DEVELOPAID_VERSION__", "test")
    file = Path(__file__).resolve().parent / f"_lots_page_{metric}.html"
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
    return html.split('printviews')[0]


def _payload(got: dict) -> dict:
    return {"project": "Кутузов Сити", "total": got["total"], "dynamics": got["dynamics"],
            "by_product": got["by_product"], "product_order": got["product_order"],
            "by_payment": [], "by_channel": [], "by_size": [], "by_rooms": [],
            "terminated": [], "sources": [], "conclusions": {}}


def test_lots_are_drawn_one_chart_per_product() -> None:
    """На экране у каждого товара свой график и свои числа, и общей высоты нет.

    Тест, зовущий рисовальщик, доказывает, что график рисуется, — не что он в
    отчёте: поэтому зовётся весь `renderSales`.
    """
    seen = _draw("units", _payload(summary()))
    assert seen.count("<svg") == 3, seen.count("<svg")
    for name in ("Квартира", "Машиноместо", "Коммерческие площади"):
        assert name in seen, name
    assert "Товары не складываются" in seen
    # Ни одного столбика без имени товара: «2026-01: 4 лоты» — это и есть та
    # сумма разных товаров, из-за которой всё затевалось.
    assert 'data-tip="2026-01: 4 ' not in seen
    assert 'data-tip="2026-01: Квартира, 2 лоты"' in seen


def test_a_single_product_promises_no_composition() -> None:
    """Один товар — один график и ни слова о том, что товары не складываются."""
    only = contracting.summarise({"rows": [deal("Квартира", 40.0, 24_000_000.0)],
                                  "project": "П", "missing": []})
    seen = _draw("units", _payload(only))
    assert seen.count("<svg") == 1, seen.count("<svg")
    assert "Товары не складываются" not in seen


def test_the_money_view_counts_no_lots() -> None:
    """Выручка складывается — у суммы есть имя; лоты и метры рядом с ней нет.

    Прежде под столбиком выручки стояла цифра «лотов всего», а в таблице
    колонки «Лотов» и «м²» — та же сумма разных товаров, только числами.
    """
    seen = _draw("amount", _payload(summary()))
    assert seen.count("<svg") == 1, seen.count("<svg")
    assert "Лотов" not in seen, seen[-1500:]
    assert "цена квартир, ₽/м²" in seen
