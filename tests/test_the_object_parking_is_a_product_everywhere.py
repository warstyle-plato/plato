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

# Паркинг — продукт своего объекта; в этих проверках места продаёт офисник.
OFFICE_PARKING = "object_parking_offices"


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
    row = _office_row(result)
    # Строка ТЭП — площадь здания, продаётся остаток после мест первых
    # этажей (владелец, 29.09.2026: вычет — в структуре продукта).
    assert row["saleable"] == pytest.approx(OFFICE_SALEABLE)
    sold = row["parking_saleable_after_sqm"]
    assert sold < OFFICE_SALEABLE, "места первых этажей не вычлись — проверять нечего"
    assert office["quantity"] == pytest.approx(sold)
    assert office["avg_price_th"] == pytest.approx(office["revenue"] / sold / 1000)


def test_the_parking_product_takes_the_price_and_calendar_of_its_object() -> None:
    result = _result()
    parking = next(p for p in result["report"]["products"] if p["key"] == OFFICE_PARKING)
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
    # Итог считается мерой счёта, а не одной суммой: квартиры, машино-места и
    # места детсада — разные величины. Места объекта обязаны стоять в графе
    # машино-мест итога, иначе подстрока не сходится с итогом.
    places = core.tep_units_by_measure(result["tep"]["rows"])[core.COUNT_PARKING]
    assert places >= float(row["parking_units"]) > 0, "места объекта потерялись в разборе"
    shown = f"{places:,.1f}".replace(",", " ").replace(".", ",").removesuffix(",0")
    assert f"{shown} {core.COUNT_PARKING}" in html, "итог мест без мест объекта"


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
    assert tax_with[OFFICE_PARKING] == 0.0
    revenue = with_places["revenue"][OFFICE_PARKING]
    assert with_places["finance"]["tax_margin_by_product"][OFFICE_PARKING] == pytest.approx(revenue)


def test_the_report_splits_the_object_money_between_its_metres_and_places() -> None:
    result = _result()
    products = {p["key"]: p for p in result["report"]["products"]}
    object_total = result["finance"]["tax_cost_by_product"]["offices"]
    assert products["offices"]["cost"] + products[OFFICE_PARKING]["cost"] == pytest.approx(object_total)
    over_building = (OVER * core.OBJECT_PARKING_OVER_AREA_DEFAULT
                     * _inputs()["offices_cost_th_per_sqm"] * 1000)
    garage = 1000 * core.OBJECT_PARKING_AREA_DEFAULT * core.DEFAULT_INPUTS["main_under_th_per_sqm"] * 1000
    assert products[OFFICE_PARKING]["cost"] == pytest.approx(garage + over_building, rel=1e-9)


def test_the_input_tep_puts_the_object_parking_on_its_own_row() -> None:
    """ТЭП на вводных: места объекта — подстрока, а не приписка к его имени.

    Приём из PR #506; текст подстроки — тот же `objectParkingNote`, что был
    подписью, второго описания мест нет.
    """
    body = page_blocks.function("renderTep")
    assert "objectParkingNote(key)" in body
    assert "↳ Паркинг объекта" in body
    # Приписки к имени больше нет — иначе одно и то же стояло бы дважды.
    assert "label+=` <span style=\"display:block;font-size:10px;color:#777;margin-top:3px\">${escapeHtml(parkNote)}" not in body


def test_the_guest_places_are_an_engine_number() -> None:
    """Гостевые — поле движка; у непродаваемых мест их нет, а не «все места»."""
    row = _office_row(_result())
    assert row["parking_guest_units"] == round((UNDER + OVER) * GUEST_PCT / 100)
    x = _inputs()
    x.update({"retail_enabled": True, "retail_parking_under_spaces": 50,
              "_parking_by_hand": ["offices", "retail"]})
    t = _tep()
    t["standalone_retail"].update({"gns": 10_000, "total_area": 9_000,
                                   "useful": 6_000, "saleable": 6_000})
    result = core._run_authoritative_model(x, t, [], {})["consolidated"]
    retail = next(r for r in result["tep"]["rows"] if r["key"] == "standalone_retail")
    assert retail["parking_units"] == 50 and retail["parking_saleable_units"] == 0
    assert retail["parking_guest_units"] == 0
    html = _report_tep_html(result)
    assert "из них гостевых 50" not in html


@pytest.mark.parametrize("phasing", [{}, {"enabled": True, "phase_count": 2,
                                          "phase_gap_months": 12}])
def test_the_project_and_its_queues_decide_whose_number_alike(phasing) -> None:
    """Чьё число в поле мест — один ответ у свода и у очередей.

    Очередь считала ручным всякое непустое поле, проект — только объект из
    списка «тронуто руками». Список есть, объекта в нём нет — поле заполнила
    норма, и оно идёт за ТЭП (решение прежних правок); то же — в очередях.
    """
    def own_and_queue(marks):
        x = _inputs()
        # Не равно норме: у этих вводных норма — те же 2 778, и совпадение
        # сделало бы проверку слепой.
        x.update({"offices_parking_under_spaces": 300,
                  "offices_parking_over_spaces": 200})
        x["_parking_by_hand"] = marks
        bundle = core._run_authoritative_model(x, _tep(), [], phasing)
        own = next(o for o in bundle["consolidated"]["parking"]["own"]
                   if o["tep_key"] == "offices")
        built = bundle["consolidated"]["tep"]["total"]["parking_units"]
        return own, built

    own, built = own_and_queue(["offices"])
    assert not own["by_norm"] and own["units"] == 500 == built
    own, built = own_and_queue([])
    assert own["by_norm"] and own["units"] != 500
    assert built == own["units"], "свод и очереди построили разные гаражи"


def test_opening_the_tep_tab_redraws_it_from_the_last_calculation() -> None:
    """Нагатино, 27.09.2026: поле «Задано руками», а ТЭП — прежние «544 по нормативу».

    Расчёт прошёл при открытых «Вводных», а ТЭП перерисовывался только если
    был открыт в этот момент. Проверяется настоящий `openTab` со страницы.
    """
    prelude = """
let drawn=0;
function renderTep(){drawn++}
// Счётчик чтения отчёта к ТЭП отношения не имеет — заглушка.
function feedbackWatchReport(){}
const el=()=>({classList:{add(){},remove(){}}});
const document={querySelectorAll:()=>[],getElementById:el,querySelector:el};
"""
    out, _ = page_blocks.run(prelude, "openTab('inputs');const a=drawn;openTab('tep');"
                             "process.stdout.write(JSON.stringify([a,drawn]));")
    assert json.loads(out) == [0, 1]


def _two_garages() -> dict:
    """Офис и ТЦ, у обоих свой гараж: места офиса продаются, ТЦ — нет."""
    x = _inputs()
    x.update({"retail_enabled": True, "retail_parking_under_spaces": 120,
              "_parking_by_hand": ["offices", "retail"]})
    t = _tep()
    t["standalone_retail"].update({"gns": 10_000, "total_area": 9_000,
                                   "useful": 6_000, "saleable": 6_000})
    return core._run_authoritative_model(x, t, [], {})["consolidated"]


def test_each_object_has_its_own_parking_product() -> None:
    """Владелец, 27.09.2026: «Паркинг — МФОЦ / офисы», «Паркинг — ТЦ / коммерция
    ОСЗ» — каждый со своими местами, ценой, календарём и выручкой."""
    result = _two_garages()
    keys = [p["key"] for p in result["report"]["products"]]
    office, retail = (core.object_parking_product_key(k) for k in ("offices", "standalone_retail"))
    # Строка паркинга стоит сразу за своим объектом.
    assert keys[keys.index("offices") + 1] == office
    assert keys[keys.index("standalone_retail") + 1] == retail
    products = {p["key"]: p for p in result["report"]["products"]}
    assert products[office]["revenue"] > 0 and products[retail]["revenue"] == 0
    assert products[retail]["built_units"] == 120 and products[retail]["quantity"] == 0
    assert result["revenue"][office] == pytest.approx(products[office]["revenue"])


def test_the_results_page_draws_two_parking_rows() -> None:
    """На отрисованной таблице «Темпы и цены продаж» — две строки паркинга.

    Склей их в одну общую — проверка падает: она ищет строку КАЖДОГО объекта.
    """
    page = core.PAGE
    start = page.index("   const ap=r.report.apartment_sales||{};\n   const inUnits=")
    end = page.index("</tr>`).join('');", start) + len("</tr>`).join('');")
    prelude = ("const salesReportTable={innerHTML:''};\n"
               f"const r={json.dumps(_two_garages(), ensure_ascii=False, default=str)};\n")
    out, _ = page_blocks.run(prelude, page[start:end]
                             + "\nprocess.stdout.write(salesReportTable.innerHTML);")
    rows = [row for row in out.split("<tr>") if "Паркинг — " in row]
    labels = sorted(row.split("<td>")[1].split("<")[0].strip() for row in rows)
    assert labels == ["Паркинг — МФОЦ / офисы", "Паркинг — ТЦ / коммерция ОСЗ"], labels
    retail_row = next(row for row in rows if "ТЦ" in row)
    assert "построено 120 мест" in retail_row.replace(" ", " ")
