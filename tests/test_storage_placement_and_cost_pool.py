"""Размещение кладовых и себестоимость продуктов дома (владелец, 15.10.2026).

Проект «Донской» (77:05:0001008:2969, файл настроек в tests/fixtures):

1. Кладовые на первом этаже. Список подземных строк был константой, и 103 м²
   кладовых строились по ставке гаража (170 тыс/м² вместо 320) и выпадали
   из наземной части. Теперь размещение — поле проекта; наземные кладовые
   ВХОДЯТ в наземную ГНС здания (вырезаются из квартир), подземная — только
   паркинг. Отсутствующий ключ — «в подземной части».
2. Пул дома делился долей проданного количества, где метры квартир
   складывались со штуками паркинга: 26 мест несли 0,03 млрд ₽ себестоимости
   при марже 94,6 %. Теперь «прямые по месту + общие по выручке»
   (`cost_pool_product_costs`), и налоговая база признаёт себестоимость
   каждого продукта долей его продаж в своих единицах.

Запуск: python3 -m pytest tests/test_storage_placement_and_cost_pool.py -q
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import main_legacy as core  # noqa: E402

SETTINGS = json.loads((ROOT / "tests" / "fixtures" / "project_settings_donskoy_0_25_78.json")
                      .read_text(encoding="utf-8"))
ABOVE = {"storage_placement": "above"}
POOL = ("apartments", "ground_commercial", "underground_parking", "storage")


def _inputs(extra: dict | None = None) -> dict:
    return {**core.DEFAULT_INPUTS, **SETTINGS["inputs"], **(extra or {})}


def _tep() -> dict:
    return json.loads(json.dumps(SETTINGS["tep"]))


def _calc(extra: dict | None = None) -> dict:
    return core.calculate(core.CalcRequest(inputs=_inputs(extra), tep=_tep(), rates=[]))


@pytest.fixture(scope="module")
def under() -> dict:
    return _calc()


@pytest.fixture(scope="module")
def above() -> dict:
    return _calc(ABOVE)


def _products(result: dict) -> dict[str, dict]:
    return {p["key"]: p for p in result["report"]["products"]}


def _storage_gns(result: dict) -> float:
    return next(float(r["gns"]) for r in result["tep"]["rows"] if r["key"] == "storage")


def _parking_gns(result: dict) -> float:
    return next(float(r["gns"]) for r in result["tep"]["rows"]
                if r["key"] == "underground_parking")


# --- размещение кладовых ----------------------------------------------------

def test_a_missing_key_is_the_default_not_above_ground() -> None:
    assert core.underground_products({}) == ("underground_parking", "storage")
    assert core.underground_products({"storage_placement": ""}) == ("underground_parking", "storage")
    assert core.underground_products(ABOVE) == ("underground_parking",)
    assert core.DEFAULT_INPUTS["storage_placement"] == "underground"
    saved = {key: value for key, value in _inputs().items() if key != "storage_placement"}
    assert core.underground_products(saved) == core.underground_products({})


def test_above_ground_storage_is_built_at_the_above_ground_rate(under, above) -> None:
    storage = _storage_gns(under)
    assert storage == pytest.approx(103, abs=0.5), "стенд без кладовых ничего не проверяет"
    rate_under = float(_inputs()["main_under_th_per_sqm"]) * 1000
    # Наземная ГНС не растёт: кладовые уже лежат в ней, вырезанные из квартир.
    assert above["tep"]["core_above_gns"] == pytest.approx(under["tep"]["core_above_gns"])
    assert above["summary"]["project_gns_sqm"] == pytest.approx(under["summary"]["project_gns_sqm"])
    # Подземная — только паркинг.
    assert above["tep"]["core_under_gns"] == pytest.approx(_parking_gns(above))
    assert under["tep"]["core_under_gns"] == pytest.approx(_parking_gns(under) + storage)
    assert above["summary"]["underground_gns_sqm"] == pytest.approx(
        under["summary"]["underground_gns_sqm"] - storage)
    # СМР подземной части меньше ровно на кладовые по подземной ставке,
    # наземной — прежнее: метры кладовых в ней уже стояли.
    assert above["capex"]["main_under"] == pytest.approx(
        under["capex"]["main_under"] - storage * rate_under)
    assert above["capex"]["main_above"] == pytest.approx(under["capex"]["main_above"])
    assert above["tep"]["underground_products"] == ["underground_parking"]
    assert under["tep"]["underground_products"] == ["underground_parking", "storage"]


def test_above_ground_storage_takes_above_ground_direct_costs(under, above) -> None:
    """Кладовые на земле несут наземное СМР своей ГНС, а не подземное."""
    direct = core.mkd_part_gns(_inputs(ABOVE), _tep())
    assert direct["above"]["storage"] == pytest.approx(_storage_gns(above), abs=0.5)
    assert "storage" not in direct["under"]
    assert sum(direct["above"].values()) == pytest.approx(above["tep"]["core_above_gns"])
    assert _products(above)["storage"]["cost"] > _products(under)["storage"]["cost"]


# --- себестоимость продуктов -------------------------------------------------

@pytest.mark.parametrize("extra", [None, ABOVE])
def test_the_product_costs_add_up_to_the_pool(extra) -> None:
    result = _calc(extra)
    products = _products(result)
    pool = float(result["capex"]["total"])
    objects = sum(p["cost"] for key, p in products.items() if key not in POOL)
    assert sum(products[key]["cost"] for key in POOL) == pytest.approx(pool - objects, rel=1e-9)


def test_the_parking_carries_its_garage_and_a_revenue_share_of_the_rest(under) -> None:
    products = _products(under)
    x, t = _inputs(), _tep()
    op = core.build_operating_model(*_prepared(x, t))
    revenue = {key: products[key]["revenue"] for key in POOL}
    pool = sum(products[key]["cost"] for key in POOL)
    direct = op["mkd_direct_costs"]
    common = pool - direct["above"] - direct["under"]
    parts = core.mkd_part_gns(x, t)
    garage_share = parts["under"]["underground_parking"] / sum(parts["under"].values())
    expected = (direct["under"] * garage_share
                + common * revenue["underground_parking"] / sum(revenue.values()))
    parking = products["underground_parking"]
    assert parking["cost"] == pytest.approx(expected, rel=1e-9)
    # Прежде: 0,03 млрд и 94,6 %. По прикидке владельца — около 25–30 %.
    assert parking["cost"] > 0.4e9
    assert 0.25 <= parking["margin"] <= 0.30, parking["margin"]


def _prepared(x: dict, t: dict) -> tuple[dict, dict]:
    prepared = core.prepared_calculation(x, t, [])
    return prepared["x"], prepared["t"]


def test_the_tax_recognizes_each_product_in_its_own_units(under, above) -> None:
    """Итог налога за проект тот же — сдвигается только график признания."""
    for result in (under, above):
        finance = result["finance"]
        costs = finance["core_product_costs"]
        products = _products(result)
        revenue = sum(products[key]["revenue"] for key in POOL)
        margin = finance["tax_margin_by_product"]["core"]
        # Признано всё, что раздано продуктам, — ни больше, ни меньше.
        assert margin == pytest.approx(revenue - sum(costs.values()), rel=1e-9)
    # Налог «Донского» при умолчании размещения — тот же, что до правки.
    # 383,74 → 387,23 млн: база вычета НДС исключает уплаченную плату за ВРИ,
    # а не начисленную (НДС −14,0 млн, решение владельца 18.10.2026).
    # 387,23 → 407,93 млн: нежилое дома, проданное по ДДУ, освобождено от НДС
    # (пп. 23.1 п. 3 ст. 149 НК, решение владельца 25.10.2026) — прибыль выше
    # на неначисленный налог за вычетом невозмещаемой части входящего.
    assert under["summary"]["profit_tax"] == pytest.approx(407_933_951, abs=5_000)


# --- поверхности -------------------------------------------------------------

def test_the_pdf_prints_the_engine_cost() -> None:
    inputs, tep = _inputs(), _tep()
    bundle = core._run_authoritative_model(inputs, tep, [], {})
    pdf = core._build_developaid_pdf({
        "result": bundle["consolidated"], "phases": bundle.get("phases") or [],
        "inputs": inputs, "tep": tep, "rates": [], "phasing": {}, "scenario": "base",
        "cadastral_numbers": []})
    pypdf = pytest.importorskip("pypdf")
    text = " ".join(" ".join(p.extract_text() for p in pypdf.PdfReader(io.BytesIO(pdf)).pages).split())
    parking = _products(bundle["consolidated"])["underground_parking"]
    assert " ".join(core._pdf_money(parking["cost"]).split()) in text
    assert "прямые затраты" in text


def test_the_workbook_splits_the_pool_the_same_way() -> None:
    """Книга раскладывает пул налоговой базы тем же методом, что движок."""
    sys.setrecursionlimit(400000)
    openpyxl = pytest.importorskip("openpyxl")
    from xlsx_eval import Evaluator
    for extra in (None, ABOVE):
        x, t = _inputs(extra), _tep()
        bundle = core._run_authoritative_model(x, t, [], None)
        content, _, meta = core.build_project_workbook(
            x, t, [], None, project_name="Донской",
            finance_hints=core._v4_finance_hints(bundle))
        assert not [m for m in meta.get("missing") or [] if "пул" in m or "кладов" in m], meta
        book = openpyxl.load_workbook(io.BytesIO(content), data_only=False)
        evaluator = Evaluator(book)
        sheet = book["CF_1"]
        rows = {str(sheet.cell(r, 1).value or ""): r for r in range(80, sheet.max_row + 1)}
        # Методика сверяется на пуле САМОЙ книги: CAPEX книги и движка на
        # этом проекте расходятся и без этой правки (паритет «Донского»), а
        # здесь проверяется, что пул делится одинаково.
        cell = lambda name: float(evaluator.cell("CF_1", f"B{rows[name]}") or 0)  # noqa: E731
        pool = cell("Пул МКД очереди: расходы без объектов") * 1e6
        prepared = core.prepared_calculation(x, t, [])
        op = core.build_operating_model(prepared["x"], prepared["t"], [])
        assert cell("Прямые: СМР наземной части с надбавками") * 1e6 == pytest.approx(
            op["mkd_direct_costs"]["above"], rel=1e-6)
        assert cell("Прямые: СМР подземной части с надбавками") * 1e6 == pytest.approx(
            op["mkd_direct_costs"]["under"], rel=1e-6)
        engine = core.cost_pool_product_costs(
            pool, op["mkd_direct_costs"], core.mkd_part_gns(prepared["x"], prepared["t"]),
            op["revenue_by_product"])
        labels = {"apartments": "квартиры", "ground_commercial": "коммерция 1 этажа",
                  "underground_parking": "подземный паркинг", "storage": "кладовые"}
        for key, word in labels.items():
            got = cell(f"Себестоимость: {word}") * 1e6
            # ГНС очереди книга округляет до метра (`ROUND` в блоке очередей).
            assert got == pytest.approx(engine[key], rel=1e-3), (extra, key)
        assert cell("Не распределено — признаётся в РВЭ") == pytest.approx(0, abs=1e-6)
        under_area = float(evaluator.cell("CAPEX", "B22") or 0)
        rate = float(x["main_under_th_per_sqm"]) / 1000
        garage = float(next(r for r in bundle["consolidated"]["tep"]["rows"]
                            if r["key"] == "underground_parking")["gns"])
        if extra:
            assert under_area == pytest.approx(garage * rate, rel=1e-3)
        else:
            assert under_area > garage * rate * 1.05


# --- отрисованная страница ---------------------------------------------------

PORT = 18987

PROBE = r"""async (data) => {
  applyProjectSnapshot(data);
  renderInputs();
  renderTep();
  // Поле живёт галочкой у строки «Кладовые» ТЭП (владелец, 16.10.2026), а
  // группы «Кладовые» во «Вводных» нет.
  const inInputs = !!document.getElementById('f_storage_placement');
  const groups = [...document.querySelectorAll('details[data-group]')].map(d => d.dataset.group);
  const field = document.getElementById('tep_storage_placement');
  const rowText = field ? (field.closest('tr').children[0].innerText || '') : '';
  const before = field ? field.checked : null;
  let answer = null;
  const fetch0 = window.fetch;
  window.fetch = async (...args) => {
    const response = await fetch0(...args);
    if (String(args[0]).startsWith('/calculate')) {
      response.clone().json().then(body => { answer = body; });
    }
    return response;
  };
  if (field) field.click();
  const after = document.getElementById('tep_storage_placement');
  answer = null;
  await settledCalculate();
  for (let i = 0; i < 300 && !answer; i++) await new Promise(r => setTimeout(r, 100));
  window.fetch = fetch0;
  const text = el => (el.innerText || '').replace(/\s+/g, ' ').trim();
  const rows = [...document.querySelectorAll('#salesReportTable tr')].map(tr =>
    [...tr.children].map(text));
  return {
    before, inInputs, groups, rowText,
    checkedAfter: after ? after.checked : null,
    placement: inputs.storage_placement, rows,
    expected: answer ? answer.report.products.filter(p => p.sellable !== false && !p.excluded)
      .map(p => [p.label, money(p.cost || 0), p.margin == null ? '—' : pct(p.margin)]) : null,
    basis: text(document.getElementById('salesCostBasis')),
    under: answer ? answer.tep.underground_products : null,
    note: text(document.getElementById('reportTepNote') || document.body),
  };
}"""


@pytest.fixture(scope="module")
def page() -> dict:
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright
    import browser

    path = browser.chromium_or_skip()
    with browser.serve(core.app, PORT) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            tab = engine.new_page(viewport={"width": 1440, "height": 900})
            tab.goto(base, wait_until="domcontentloaded")
            browser.wait_for_result(tab)
            got = tab.evaluate(PROBE, SETTINGS)
            tab.close()
    assert got["expected"], "страница не получила ответ расчёта"
    return got


def test_the_page_offers_the_placement_and_keeps_the_default(page) -> None:
    # Галочка стоит у строки «Кладовые» ТЭП, во «Вводных» поля и группы нет.
    assert page["rowText"].startswith("Кладовые"), page["rowText"]
    assert "над землёй" in page["rowText"]
    assert not page["inInputs"]
    assert page["groups"] and "Кладовые" not in page["groups"], page["groups"]
    # Файл «Донского» поля не несёт: страница показывает умолчание — снята.
    assert page["before"] is False
    assert page["checkedAfter"] is True
    assert page["placement"] == "above"
    assert page["under"] == ["underground_parking"]


def test_the_sales_table_shows_the_engine_cost(page) -> None:
    shown = {row[0].split(" профиль")[0]: (row[6], row[7]) for row in page["rows"] if len(row) >= 8}
    for label, cost, margin in page["expected"]:
        hit = next((value for name, value in shown.items() if name.startswith(label)), None)
        assert hit == (cost, margin), (label, hit, cost, margin)
    assert "по выручке" in page["basis"]
