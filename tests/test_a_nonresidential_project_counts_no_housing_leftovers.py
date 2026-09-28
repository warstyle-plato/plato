"""Нежилой проект не считает оставшееся от жилья — нигде.

Жалоба владельца на проект «Вавилов» (офисы / МФОЦ, 19 110 м² ГНС): PDF
показывал ДВА подземных паркинга — гараж МФОЦ (286 мест, это верно) и
«Подземный паркинг» 5 215 м² / 149 мест с выручкой 834,6 млн ₽, остаток
жилого расчёта. Отчёт сам писал «Осталось от жилья во вводных: Подземный
паркинг 5 215 м², 149 шт.» — и всё равно складывал его в строительный объём
(24 325 = 19 110 + 5 215), в итог мест (435), в продукты, выручку и СМР
подземной части. Строку МКД каждый расчёт заново собирал из оставшихся
`underground_manual_*`.

Правило: в нежилом режиме продукты МКД (`MKD_PRODUCTS`) и жилые вводные
(`NONRESIDENTIAL_CLEARED_INPUTS`) в расчёт не входят — решает это ОДИН
предикат `residential_excluded`, а сами вводные не стираются: вернувшись к
жилому типу, человек получает набранное назад.

Запуск: python3 -m pytest tests/test_a_nonresidential_project_counts_no_housing_leftovers.py -q
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402

OFFICE_GBA, OFFICE_SALEABLE = 19_110.0, 14_012.0
GARAGE = 286
LEFT_SPACES, LEFT_AREA = 149, 5_215.0
OFFICE_PARKING = "object_parking_offices"


def _vavilov(kind: str = core.PROJECT_KIND_NONRESIDENTIAL) -> tuple[dict, dict]:
    """Проект «Вавилов» по числам его отчёта: офисы с гаражом, а во вводных —
    жилой подземный паркинг, оставшийся от расчёта жилья."""
    x = copy.deepcopy(core.DEFAULT_INPUTS)
    t = copy.deepcopy(core.TEP_DEFAULT)
    for key in core.MKD_PRODUCTS:
        for col in ("gns", "total_area", "useful", "saleable", "transfer", "units"):
            t[key][col] = 0
    for key in core.NONRESIDENTIAL_CLEARED_INPUTS:
        x[key] = 0
    x.update({"project_kind": kind, "purchase_price_mln": 500,
              "offices_enabled": True, "offices_gba_sqm": OFFICE_GBA,
              "offices_saleable_sqm": OFFICE_SALEABLE, "offices_price_th": 300,
              "offices_parking_under_spaces": GARAGE,
              "offices_parking_over_spaces": 0,
              "offices_parking_guest_pct": 10,
              "_parking_by_hand": ["offices", "underground"],
              # Остаток жилья: пара «места ↔ площадь» подземного паркинга МКД.
              "underground_manual_spaces": LEFT_SPACES,
              "underground_manual_gns_sqm": LEFT_AREA})
    t["offices"].update({"gns": OFFICE_GBA, "total_area": OFFICE_GBA * 0.94,
                         "useful": OFFICE_SALEABLE, "saleable": OFFICE_SALEABLE})
    t["underground_parking"].update({"units": LEFT_SPACES, "gns": LEFT_AREA,
                                     "total_area": LEFT_AREA})
    return x, t


def _run(x: dict, t: dict, phasing: dict | None = None) -> dict:
    return core._run_authoritative_model(copy.deepcopy(x), copy.deepcopy(t), [],
                                         phasing or {})["consolidated"]


def _row(result: dict, key: str) -> dict:
    return next((r for r in result["tep"]["rows"] if r["key"] == key), {})


PHASINGS = [{}, {"enabled": True, "phase_count": 2, "phase_gap_months": 12}]


def test_the_leftover_is_really_there() -> None:
    """Предохранитель: в жилом режиме тот же проект паркинг МКД СЧИТАЕТ —
    иначе проверки ниже зелены на любом коде."""
    x, t = _vavilov(core.PROJECT_KIND_MIXED)
    result = _run(x, t)
    assert _row(result, "underground_parking")["units"] == LEFT_SPACES
    products = {p["key"]: p for p in result["report"]["products"]}
    assert products["underground_parking"]["revenue"] > 0


@pytest.mark.parametrize("phasing", PHASINGS)
def test_the_tep_has_one_underground_parking(phasing) -> None:
    x, t = _vavilov()
    result = _run(x, t, phasing)
    row = _row(result, "underground_parking")
    assert row.get("units", 0) == 0 and row.get("gns", 0) == 0, row
    office = _row(result, "offices")
    assert office["parking_under_units"] == GARAGE
    # Итог мест — только гараж объекта: 286, а не 435.
    # Итог по мере «машино-места» (#550): у жилого типа тот же проект даёт 435.
    total = result["tep"]["total"]
    assert total["units_by_measure"] == {"м/м": GARAGE}, total


@pytest.mark.parametrize("phasing", PHASINGS)
def test_no_money_comes_from_the_leftover(phasing) -> None:
    x, t = _vavilov()
    result = _run(x, t, phasing)
    for product in result["report"]["products"]:
        if product["key"] in core.MKD_PRODUCTS:
            assert not product.get("revenue"), product
    assert result["summary"]["project_kind_leftovers"], "остаток перестали называть"

    # Расход тоже: проект без остатка стоит столько же, сколько с ним.
    clean_x, clean_t = _vavilov()
    for key in core.NONRESIDENTIAL_CLEARED_INPUTS:
        clean_x[key] = 0
    for col in ("units", "gns", "total_area"):
        clean_t["underground_parking"][col] = 0
    clean = _run(clean_x, clean_t, phasing)
    assert clean["summary"]["project_kind_leftovers"] == []
    for key in ("revenue", "capex", "ebitda", "net_profit", "llcr"):
        assert result["summary"][key] == pytest.approx(clean["summary"][key]), key


def test_the_inputs_are_kept_for_the_way_back() -> None:
    """Участие в расчёте и сохранённое значение — разные вещи."""
    x, t = _vavilov()
    core.calculate(core.CalcRequest(inputs=x, tep=t))
    assert x["underground_manual_spaces"] == LEFT_SPACES
    assert x["underground_manual_gns_sqm"] == LEFT_AREA
    assert t["underground_parking"]["units"] == LEFT_SPACES


def test_the_predicate_is_one() -> None:
    """Жилой режим предикат не трогает; нежилой — обнуляет всё МКД и
    жилые вводные на копии."""
    x, t = _vavilov(core.PROJECT_KIND_MIXED)
    same_x, same_t = core.residential_excluded(x, t)
    assert same_x is x and same_t is t
    x, t = _vavilov()
    ex_x, ex_t = core.residential_excluded(x, t)
    assert ex_x is not x and ex_t is not t
    for key in core.MKD_PRODUCTS:
        assert all(not float(ex_t[key].get(c) or 0)
                   for c in ("gns", "total_area", "useful", "saleable", "units")), key
    for key in core.NONRESIDENTIAL_CLEARED_INPUTS:
        assert not float(ex_x.get(key) or 0), key
    assert ex_t["offices"]["gns"] == OFFICE_GBA


def test_the_pdf_shows_one_underground_parking() -> None:
    pytest.importorskip("reportlab")
    pymupdf = pytest.importorskip("pymupdf")
    x, t = _vavilov()
    bundle = core._run_authoritative_model(copy.deepcopy(x), copy.deepcopy(t), [], {})
    data = core._build_developaid_pdf({
        "result": bundle["consolidated"], "inputs": x, "tep": t,
        "rates": [], "phasing": {}, "scenario": "base", "project_name": "Вавилов"})
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        text = "\n".join(page.get_text() for page in doc)
    flat = " ".join(text.split())
    assert "Осталось от жилья" in flat
    assert "в расчёт не входит" in flat
    assert "435" not in flat.replace(" ", ""), "итог мест включает места МКД"
    assert "5215" not in flat.replace(" ", "").split("Осталосьотжилья")[0], \
        "метры паркинга МКД стоят в ТЭП до строки об остатке"
    # Цены и темп продуктов МКД — не предпосылки нежилого расчёта.
    for label in ("Стартовая цена квартир", "Цена подземного машино-места",
                  "Доля продаж до РВЭ"):
        assert label not in flat, label


def test_the_engine_marks_what_the_kind_does_not_count() -> None:
    """Строка остаётся в ответе с признаком: поверхность её прячет, а ключ
    не пропадает у тех, кто ищет строку по имени."""
    x, t = _vavilov()
    for phasing in PHASINGS:
        rows = {r["key"]: r for r in _run(x, t, phasing)["tep"]["rows"]}
        assert rows["underground_parking"]["excluded"] is True
        assert rows["kindergarten"]["excluded"] is True
        assert rows["offices"]["excluded"] is False
    mixed = _run(*_vavilov(core.PROJECT_KIND_MIXED))
    assert not any(r["excluded"] for r in mixed["tep"]["rows"])


# Настоящая страница, настоящий путь: проект из кабинета ложится во вводные
# и на экран, `calculate()` шлёт его движку и рисует ответ. Остаток приходит
# так, как пришёл он у владельца, — мимо переключателя типа.
RENDER = """async (arg)=>{
  Object.keys(arg.t).forEach(k=>{tep[k]=Object.assign(tep[k]||{},arg.t[k])});
  Object.assign(inputs, arg.x);
  renderInputs();
  const sent=[];const plain=window.fetch;
  window.fetch=(url,opts)=>{
    if(String(url).indexOf('/calculate')>=0)
      sent.push(Number(JSON.parse(opts.body).inputs.underground_manual_spaces||0));
    return plain(url,opts);
  };
  await calculate();
  window.fetch=plain;
  const rows=Array.from(document.querySelectorAll('#reportTep tbody tr'))
    .map(tr=>(tr.cells[0].textContent||'').trim());
  const foot=Array.from(document.querySelectorAll('#reportTep tfoot th'))
    .map(th=>(th.textContent||'').trim());
  return {rows:rows, foot:foot, sent:sent,
          kept:Number(inputs.underground_manual_spaces||0)};
}"""


@pytest.fixture(scope="module")
def drawn():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright
    sys.path.insert(0, str(ROOT / "tests"))
    import browser

    x, t = _vavilov()
    path = browser.chromium_or_skip()
    errors: list[str] = []
    with browser.serve(core.app, 18963) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            page = engine.new_page(viewport={"width": 1440, "height": 900})
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_timeout(1800)
            got = page.evaluate(RENDER, {"x": x, "t": t})
            page.close()
    got["errors"] = errors
    return got


def test_the_page_draws_one_underground_parking(drawn) -> None:
    assert drawn["errors"] == [], drawn["errors"]
    names = drawn["rows"]
    garage = [n for n in names if "паркинг объекта" in n]
    assert len(garage) == 1, names
    assert not any(n.startswith("Подземный паркинг") for n in names), names
    assert not any(n.startswith("Квартиры") or n.startswith("ДОО") for n in names), names
    # Итог «построено, шт.» — только гараж объекта.
    built = "".join(ch for ch in drawn["foot"][5] if ch.isdigit())
    assert built == str(GARAGE), drawn["foot"]


def test_the_page_keeps_the_saved_housing(drawn) -> None:
    """Остаток дошёл до движка (иначе проверка выше ничего не доказывает) и
    после расчёта лежит во вводных как лежал: вернётся с жилым типом."""
    assert drawn["sent"] == [LEFT_SPACES], drawn["sent"]
    assert drawn["kept"] == LEFT_SPACES


@pytest.mark.parametrize("phasing", PHASINGS)
def test_the_book_counts_what_the_engine_counts(phasing) -> None:
    """Методика в движке и книге одна: книга v4 на проекте с остатком сходится
    с движком по всем строкам паритета, а плата за ВРИ и соцкомпенсация во
    вводные книги не идут.

    Строки налога, чистой прибыли и LLCR падали и без остатка: у проекта без
    квартир общий пул расходов делился на ноль проданных штук, и IFERROR книги
    не вычитал его вовсе (`_v4_apply_core_pool_without_sales`)."""
    import io

    import openpyxl
    sys.path.insert(0, str(ROOT / "tests"))
    from xlsx_eval import Evaluator

    sys.setrecursionlimit(400000)
    x, t = _vavilov()
    x["land_rights_cost_mln"] = 1200.0
    x["social_compensation_mln"] = 300.0
    bundle = core._run_authoritative_model(copy.deepcopy(x), copy.deepcopy(t), [], phasing)
    content, _, meta = core.build_project_workbook(
        copy.deepcopy(x), copy.deepcopy(t), [], bundle.get("phasing") or phasing,
        project_name="Вавилов")
    assert meta["missing"] == [], meta["missing"]
    book = openpyxl.load_workbook(io.BytesIO(content), data_only=False)
    evaluator = Evaluator(book)
    for row in range(76, 85):
        assert book["ПРОВЕРКИ"][f"C{row}"].value is not None, f"цель строки {row}"
        assert evaluator.cell("ПРОВЕРКИ", f"F{row}") == "OK", \
            str(book["ПРОВЕРКИ"][f"A{row}"].value)
    # Цели паритета — движок, и движок без остатка: книга не может сойтись
    # с ним, считая паркинг дома или плату за ВРИ.
    clean_x, clean_t = _vavilov()
    clean_t["underground_parking"].update(units=0, gns=0, total_area=0)
    clean_x.update(underground_manual_spaces=0, underground_manual_gns_sqm=0)
    clean = _run(clean_x, clean_t, phasing)["summary"]
    revenue_row = next(r for r in range(76, 85)
                       if "ыручк" in str(book["ПРОВЕРКИ"][f"A{r}"].value or ""))
    assert float(book["ПРОВЕРКИ"][f"C{revenue_row}"].value) == pytest.approx(
        clean["revenue"] / 1e6, rel=1e-6)
