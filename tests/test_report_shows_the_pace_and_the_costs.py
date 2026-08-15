"""Отчёт на экране — тот же документ, что уходит в печать.

Три расхождения между экраном и PDF, все одной природы.

**Расходы всего.** В плашках стояла выручка, EBITDA и прибыль, а второй
половины уравнения не было. В PDF ключевая экономика идёт «Выручка → Расходы
всего → EBITDA»; на экране EBITDA появлялась из ниоткуда, и сравнить её было
не с чем.

**График темпа продаж.** В PDF он есть, на экране не было. Человек смотрел
отчёт, печатал его и видел незнакомый раздел — та же поломка, что уже чинили
с календарём и чувствительностью. Средний темп прячет и разгон, и сезонный
провал, и обрыв после РВЭ: «40 квартир в месяц» в среднем — это может быть и
ровные сорок, и восемьдесят до РВЭ с нулём после.

**Квартиры в штуках.** Таблица темпов говорила только метрами. «2 400 м² в
месяц» отделом продаж не проверяется, «40 квартир» — проверяется. Блок ниже
штуки показывал, но смотрят туда, где стоит темп.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core
PAGE = core.PAGE


@pytest.fixture(scope="module")
def result():
    return core.calculate(core.CalcRequest(
        inputs=core.DEFAULT_INPUTS, tep=core.TEP_DEFAULT, rates=[]))


def page_function(name: str) -> str:
    start = PAGE.index(f"function {name}(")
    depth = 0
    for position in range(PAGE.index("{", start), len(PAGE)):
        if PAGE[position] == "{":
            depth += 1
        elif PAGE[position] == "}":
            depth -= 1
            if depth == 0:
                return PAGE[start:position + 1]
    raise AssertionError(f"не найдена функция {name}")


# --- расходы стоят рядом с выручкой ---------------------------------------------

def test_the_tiles_carry_the_total_expenses():
    tiles = PAGE[PAGE.index("const reportKpis=["):]
    tiles = tiles[:tiles.index("];")]
    assert "'Расходы всего'" in tiles
    assert "summary.total_expenses" in tiles


def test_the_expenses_stand_right_after_the_revenue():
    """Две половины одного уравнения читаются рядом или не читаются вовсе."""
    tiles = PAGE[PAGE.index("const reportKpis=["):]
    tiles = tiles[:tiles.index("];")]
    assert tiles.index("'Выручка'") < tiles.index("'Расходы всего'") < tiles.index("'EBITDA'")


def test_the_number_exists_in_the_result(result):
    """Плашка, которой нечего показать, — пустая рамка."""
    assert result["summary"]["total_expenses"] > 0


def test_the_screen_shows_what_the_pdf_shows(result):
    """В PDF та же строка — «Расходы всего» в ключевой экономике."""
    assert "Расходы всего" in PAGE
    summary = result["summary"]
    assert summary["revenue"] - summary["total_expenses"] == pytest.approx(
        summary["net_profit"], rel=1e-6)


# --- график темпа продаж --------------------------------------------------------

def test_the_report_has_a_place_for_the_chart():
    assert 'id="apartmentPaceChart"' in PAGE
    assert "renderApartmentPaceChart(" in PAGE


def test_the_chart_lives_in_the_income_section():
    """Раздел «Доходы», рядом с темпами — а не отдельной вкладкой."""
    income = PAGE.index('id="rsIncome"')
    finance = PAGE.index('id="rsFinance"')
    chart = PAGE.index('id="apartmentPaceChart"')
    assert income < chart < finance


def test_the_engine_supplies_the_monthly_units(result):
    rows = result["report"]["apartment_sales"]["rows"]
    assert rows and all(row["units"] > 0 for row in rows)
    assert all(re.fullmatch(r"\d{4}-\d{2}-\d{2}", row["month"]) for row in rows)


def render_chart(sales: dict) -> dict:
    """Гоняет настоящий `renderApartmentPaceChart` из PAGE через node."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    script = "\n".join([
        re.search(r"const num=.*?;\n", PAGE, re.S).group(0),
        "const box={innerHTML:'',style:{}};",
        "const document={getElementById:(id)=>id==='apartmentPaceChart'?box:null};",
        page_function("renderApartmentPaceChart"),
        f"renderApartmentPaceChart({json.dumps(sales)});",
        "console.log(JSON.stringify({html:box.innerHTML,display:box.style.display}));",
    ])
    done = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_the_chart_draws_a_bar_per_month(result):
    drawn = render_chart(result["report"]["apartment_sales"])
    months = len(result["report"]["apartment_sales"]["rows"])
    assert drawn["html"].count("<rect") == months
    assert "квартир/мес." in drawn["html"]


def test_the_tallest_month_fills_the_plot(result):
    """Столбцы обязаны отличаться по высоте: одинаковые — признак того, что
    масштаб взят не по данным."""
    drawn = render_chart(result["report"]["apartment_sales"])
    heights = {float(value) for value in re.findall(r'height="([\d.]+)"', drawn["html"])}
    assert len(heights) > 1


def test_an_empty_chart_is_hidden_not_blank():
    """Пустая рамка обещает данные, которых нет."""
    drawn = render_chart({"rows": []})
    assert drawn["html"] == "" and drawn["display"] == "none"
    zeros = render_chart({"rows": [{"month": "2029-01-01", "units": 0}]})
    assert zeros["display"] == "none"


def test_the_month_labels_read_as_dates(result):
    drawn = render_chart(result["report"]["apartment_sales"])
    labels = re.findall(r">(\d{2}\.\d{4})<", drawn["html"])
    assert len(labels) == 3, labels
    first = result["report"]["apartment_sales"]["rows"][0]["month"]
    assert labels[0] == first[5:7] + "." + first[:4]


def test_the_chart_fills_its_width():
    """С фиксированной высотой контейнера широкий график вписывался с полями в
    треть ширины: пропорции берутся от графика в PDF, высота — от ширины."""
    assert 'id="apartmentPaceChart" class="chart" style="height:auto"' in PAGE
    assert 'style="height:auto;display:block"' in page_function("renderApartmentPaceChart")


def test_the_chart_survives_the_printout():
    """Разорванный между страницами график не читается."""
    assert "body.print-report .chart{break-inside:avoid}" in PAGE


def test_the_apartments_are_counted_in_whole_units():
    """«1 361,8 квартиры» на экране против «1 362» в PDF — расхождение на
    ровном месте: квартира штучна."""
    body = PAGE[PAGE.index("const inUnits=p=>"):]
    assert "Math.round(ap.units_total)" in body[:body.index("</tr>`).join('');")]
    assert PAGE.count("num(Math.round(ap.units_total))") == 2


# --- квартиры в штуках в самой таблице ------------------------------------------

def test_the_pace_table_names_the_apartments_in_units():
    body = PAGE[PAGE.index("salesReportHead.innerHTML='<tr><th>Продукт</th>"):]
    body = body[:body.index("</tr>`).join('');")]
    assert "apartment_sales" in body
    assert "шт." in body and "кв./мес." in body


def test_only_the_apartments_get_the_second_line():
    """У паркинга штуки и так в основной единице — дубль был бы шумом."""
    body = PAGE[PAGE.index("const inUnits=p=>"):]
    assert body[:body.index(";")].count("apartments") == 1


def test_the_units_match_the_block_below(result):
    """Две подписи об одном обязаны сходиться: штуки в таблице и в блоке ниже
    берутся из одного `apartment_sales`."""
    sales = result["report"]["apartment_sales"]
    assert sales["units_total"] > 0
    assert sales["pace_pre_rve_units"] > 0
    body = PAGE[PAGE.index("const inUnits=p=>"):]
    body = body[:body.index("</tr>`).join('');")]
    assert "ap.units_total" in body and "ap.pace_pre_rve_units" in body
