"""Свой паркинг отдельно стоящего объекта виден продуктом на каждой поверхности.

«У нас есть отдельно стоящие офисники, ТЦ, ФОК и т.д. Машино-места продаются
только у офисника… При этом в разделе ТЭП, результатов и отчёте PDF наличие
паркинга как продукта или как части ТЭП вообще нет» (владелец, 24.09.2026).

Движок места продавал, а поверхности их не показывали:
- ТЭП «Результатов» и печати держали места полем на строке объекта, и ни мест,
  ни продаваемых в таблице не было;
- подпись «Подземная часть (… гаражи объектов)» на вводных складывала поле,
  которое страница никогда не заполняет, — гараж офисника в неё не входил;
- продукт «Офисы» делил выручку на вводную продаваемую, а продавалась она за
  вычетом мест первых этажей — средняя цена офиса занижалась;
- продукт «паркинг объектов» брал цену места дома и календарь квартир.

Запуск: python3 -m pytest tests/test_the_object_parking_is_a_product_everywhere.py -q
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import page_blocks  # noqa: E402
import main_legacy as core  # noqa: E402

UNDER, OVER, GUEST_PCT = 1000, 1778, 10
OFFICE_GBA, OFFICE_SALEABLE = 186_180.0, 87_504.6
UNDER_PRICE_MLN, OVER_PRICE_MLN = 4.0, 2.0


def _inputs() -> dict:
    x = copy.deepcopy(core.DEFAULT_INPUTS)
    x.update({"offices_enabled": True, "offices_gba_sqm": OFFICE_GBA,
              "offices_saleable_sqm": OFFICE_SALEABLE,
              "offices_parking_under_spaces": UNDER,
              "offices_parking_over_spaces": OVER,
              "offices_parking_guest_pct": GUEST_PCT,
              "offices_parking_under_price_mln_per_space": UNDER_PRICE_MLN,
              "offices_parking_over_price_mln_per_space": OVER_PRICE_MLN,
              "offices_sales_start": "2031-01-01", "offices_start": "2030-01-01",
              "_parking_by_hand": ["offices"]})
    return x


def _tep() -> dict:
    t = copy.deepcopy(core.TEP_DEFAULT)
    t["offices"].update({"gns": OFFICE_GBA, "total_area": OFFICE_GBA * 0.94,
                         "useful": OFFICE_SALEABLE, "saleable": OFFICE_SALEABLE})
    return t


def _result(phasing: dict | None = None) -> dict:
    return core._run_authoritative_model(_inputs(), _tep(), [], phasing or {})["consolidated"]


def _office_row(result: dict) -> dict:
    return next(row for row in result["tep"]["rows"] if row["key"] == "offices")


@pytest.mark.parametrize("phasing", [{}, {"enabled": True, "phase_count": 2,
                                          "phase_gap_months": 12}])
def test_the_tep_row_says_where_the_places_stand(phasing) -> None:
    row = _office_row(_result(phasing))
    assert row["parking_under_units"] == UNDER
    assert row["parking_over_units"] == OVER
    assert row["parking_units"] == UNDER + OVER
    guests = round((UNDER + OVER) * GUEST_PCT / 100)
    assert row["parking_saleable_units"] == UNDER + OVER - guests


def test_the_office_product_is_measured_by_what_is_sold() -> None:
    """Места первых этажей занимают метры здания — их не продают офисом."""
    result = _result()
    office = next(p for p in result["report"]["products"] if p["key"] == "offices")
    sold = _office_row(result)["saleable"]
    assert sold < OFFICE_SALEABLE, "места первых этажей не вычлись — проверять нечего"
    assert office["quantity"] == pytest.approx(sold)
    assert office["avg_price_th"] == pytest.approx(office["revenue"] / sold / 1000)


def test_the_parking_product_takes_the_price_and_calendar_of_its_object() -> None:
    result = _result()
    parking = next(p for p in result["report"]["products"] if p["key"] == "object_parking")
    weighted = (UNDER * UNDER_PRICE_MLN + OVER * OVER_PRICE_MLN) / (UNDER + OVER) * 1000
    assert parking["start_price_th"] == pytest.approx(weighted)
    assert parking["start_price_th"] != pytest.approx(core.DEFAULT_INPUTS["parking_price_th"])
    assert parking["sales_start"] >= "2031-01-01", "места проданы календарём квартир"


def test_the_print_tep_names_the_object_parking() -> None:
    pytest.importorskip("reportlab", reason="reportlab нужен только для PDF")
    from market_search.krt_requirements import pdf_text

    result = _result()
    pdf = core._build_developaid_pdf({"result": result, "project_name": "Паркинг ОСЗ",
                                      "inputs": _inputs(), "tep": _tep()})
    text = " ".join(pdf_text(pdf).split())
    assert "в т.ч. паркинг объекта" in text, "паркинга объекта нет в ТЭП печати"
    assert "подземных 1 000" in text.replace(" ", " ")
    assert "на первых этажах 1 778" in text.replace(" ", " ")


def _report_tep_html(result: dict) -> str:
    page = core.PAGE
    start = page.index(" const soldUnits=x=>")
    end = page.index("</tr></tfoot>`;", start) + len("</tr></tfoot>`;")
    prelude = ("const reportTep={innerHTML:''};\n"
               f"const r={json.dumps(result, ensure_ascii=False, default=str)};\n")
    out, _ = page_blocks.run(prelude, page[start:end]
                             + "\nprocess.stdout.write(reportTep.innerHTML);")
    return out.replace(" ", " ")


def test_the_results_tep_shows_the_object_parking_row() -> None:
    """Проверяется таблица, на которую жаловались, — нарисованная кодом страницы."""
    result = _result()
    html = _report_tep_html(result)
    assert "в т.ч. паркинг объекта, машино-места" in html
    assert "подземных 1 000" in html and "на первых этажах 1 778" in html
    row = _office_row(result)
    assert f"{int(row['parking_saleable_units']):,}".replace(",", " ") in html
    # Итог штук включает места объекта: иначе подстрока не сходится с итогом.
    total_built = result["tep"]["total"]["units"] + result["tep"]["total"]["parking_units"]
    shown = f"{total_built:,.1f}".replace(",", " ").replace(".", ",").removesuffix(",0")
    assert f"<th>{shown}</th>" in html, "итог штук без мест объекта"


def test_the_input_tep_counts_the_object_garage_underground() -> None:
    """Подпись «гаражи объектов» обязана видеть гараж, посчитанный движком."""
    prelude = ("let phaseBundle=null;\n"
               "let lastResult={parking:{own:[{tep_key:'offices',enabled:true,under_gns:35000}]}};\n")
    out, _ = page_blocks.run(prelude, "process.stdout.write(String("
                             "tepRowUnderGns('offices',{gns:186180})));")
    assert float(out) == 35000, "гараж офисника не попал в подземную часть ТЭП"
    # Мёртвый контрпример: без гаража у движка подземной части у офиса нет.
    prelude_off = "let phaseBundle=null;\nlet lastResult={parking:{own:[]}};\n"
    out_off, _ = page_blocks.run(prelude_off, "process.stdout.write(String("
                                 "tepRowUnderGns('offices',{gns:186180})));")
    assert float(out_off) == 0


def test_the_object_parking_never_touches_the_house_pool() -> None:
    """Гараж и места объекта — только его объекта, никогда не МКД (27.09.2026).

    Пул дома — ровно продукты дома: паркинг объекта не забирает долю стройки
    МКД и не разбавляет своими штуками признание квартир. Его расход признаётся
    вместе со статьёй объекта, как в книге, а выручка входит в базу целиком.
    """
    assert core.COST_POOL_PRODUCTS == core.MKD_PRODUCTS
    with_places = _result()
    finance = with_places["finance"]
    tax_cost = finance["tax_cost_by_product"]
    # Пул дома признаётся только продажами дома: его маржа — выручка дома
    # минус весь его расход. Будь места в пуле, в марже стояла бы и их выручка.
    house_revenue = sum(with_places["revenue"].get(key, 0.0) for key in core.MKD_PRODUCTS)
    assert finance["tax_margin_by_product"]["core"] == pytest.approx(
        house_revenue - tax_cost["core"], rel=1e-9)
    # Гараж — в статье офиса, а не в остатке дома.
    x = _inputs()
    x.update({"offices_parking_under_spaces": 0, "offices_parking_over_spaces": 0})
    without = core._run_authoritative_model(x, _tep(), [], {})["consolidated"]
    garage = 1000 * core.OBJECT_PARKING_AREA_DEFAULT * core.DEFAULT_INPUTS["main_under_th_per_sqm"] * 1000
    assert tax_cost["offices"] == pytest.approx(
        without["finance"]["tax_cost_by_product"]["offices"] + garage, rel=1e-9)
    tax_with = tax_cost
    assert tax_with["object_parking"] == 0.0
    revenue = with_places["revenue"]["object_parking"]
    assert with_places["finance"]["tax_margin_by_product"]["object_parking"] == pytest.approx(revenue)


def test_the_report_splits_the_object_money_between_its_metres_and_places() -> None:
    result = _result()
    products = {p["key"]: p for p in result["report"]["products"]}
    object_total = result["finance"]["tax_cost_by_product"]["offices"]
    assert products["offices"]["cost"] + products["object_parking"]["cost"] == pytest.approx(object_total)
    over_building = (OVER * core.OBJECT_PARKING_OVER_AREA_DEFAULT
                     * _inputs()["offices_cost_th_per_sqm"] * 1000)
    garage = 1000 * core.OBJECT_PARKING_AREA_DEFAULT * core.DEFAULT_INPUTS["main_under_th_per_sqm"] * 1000
    assert products["object_parking"]["cost"] == pytest.approx(garage + over_building, rel=1e-9)
