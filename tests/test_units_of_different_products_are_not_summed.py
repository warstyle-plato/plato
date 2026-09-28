"""Квартиры, машино-места и места в саду не складываются в одно число.

«Конечно это не надо суммировать» (владелец, 27.09.2026) — ответ на вопрос,
оставшийся открытым после #520: итог колонки «Единиц» складывал 1 362 квартиры,
1 199 машино-мест и 250 мест ДОО в 2 811 «штук».

Беда была не только в показе. Это число ДЕЛИЛИ: обеспеченность парковкой
считалась от него (28,98 вместо 12,36), а тизер PDF печатал строку
«Машино-места — 2 811 м/м» при 1 199 настоящих. Документ для банка утверждал
величину, которой в проекте нет.

Здесь закреплено: у каждого продукта объявлена МЕРА счёта, свод группирует
штуки по ней, а общего итога штук не существует нигде — ни в движке, ни на
странице, ни в книге, ни в отчёте, ни в тизере. Складывать нечем, и отсутствие
поля надёжнее договорённости его не читать: именно из такого поля и выросла
обеспеченность в 28,98.

Запуск: python3 -m pytest tests/test_units_of_different_products_are_not_summed.py -q
"""

from __future__ import annotations

import copy
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import main_legacy as core  # noqa: E402
import page_blocks  # noqa: E402
import presentation  # noqa: E402
import v4_dashboard as vd  # noqa: E402


def _result(**overrides):
    inputs = {**core.DEFAULT_INPUTS, **overrides}
    tep = {key: dict(value) for key, value in core.TEP_DEFAULT.items()}
    return core.calculate(core.CalcRequest(inputs=inputs, tep=tep, rates=[]))


def test_the_total_has_no_single_number_for_units():
    """Поля, в котором складывалось несравнимое, больше нет.

    Договорённости «не читать это поле» недостаточно: обеспеченность парковкой
    читала его как машино-места именно потому, что оно лежало под рукой.
    """
    total = _result()["tep"]["total"]
    assert "units" not in total, "общий итог штук вернулся в свод"
    assert "saleable_units" not in total, "общий итог проданных штук вернулся в свод"
    assert total["units_by_measure"], "разбор по мере пуст"


def test_the_counts_are_grouped_by_what_they_measure():
    """Разбор, а не сумма: каждая мера отвечает сама за себя."""
    got = _result()["tep"]
    by = got["total"]["units_by_measure"]
    rows = {row["key"]: row for row in got["rows"]}
    assert abs(by[presentation.FLATS_MEASURE] - rows["apartments"]["units"]) < 0.01
    assert by[presentation.PARKING_MEASURE] == rows["underground_parking"]["units"]
    assert by[presentation.PLACES_MEASURE] == rows["kindergarten"]["units"]
    # Предохранитель: если бы всё лежало в одной мере, проверка выше прошла бы
    # на сломанном коде при одном продукте. Мер здесь трое.
    assert len(by) >= 3, by
    assert sum(by.values()) != by[presentation.PARKING_MEASURE]


def test_every_tep_row_declares_what_it_is_counted_in():
    """Новый продукт обязан назвать свою меру, а не получить «шт.» молча.

    Ровно так завёлся сам дефект: мера не объявлялась нигде, и «штуки»
    оказались общим знаменателем для несравнимого.
    """
    undeclared = [row["key"] for row in _result()["tep"]["rows"]
                  if row["key"] not in core.TEP_COUNT_MEASURE]
    assert not undeclared, f"у строк ТЭП нет объявленной меры счёта: {undeclared}"


def test_a_metre_product_is_counted_in_nothing():
    """«Сколько штук у офисного центра» — вопрос без смысла, и мера пуста."""
    assert core.tep_count_measure("offices") == presentation.AREA_MEASURE
    assert core.tep_count_measure("apartments") == presentation.FLATS_MEASURE


def test_the_parking_provision_counts_parking_and_not_everything():
    """То, что число не печаталось, а делилось: 28,98 вместо 12,36."""
    got = _result()
    bundle = core._run_authoritative_model(
        copy.deepcopy(core.DEFAULT_INPUTS),
        {key: dict(value) for key, value in core.TEP_DEFAULT.items()}, [], None)
    numbers = core.presentation_numbers(bundle["consolidated"])
    rows = {row["key"]: row for row in got["tep"]["rows"]}
    spaces = rows["underground_parking"]["units"]
    flats = rows["apartments"]["units"]
    assert numbers["parking"]["built_units"] == spaces, numbers["parking"]
    # Предохранитель: квартир в стенде много, и старое число от нового
    # отличается заметно — иначе проверка проходила бы на сломанном коде.
    assert flats > 1000
    assert numbers["parking"]["built_units"] < spaces + flats - 1


def test_the_garage_of_an_object_is_counted_as_parking():
    """Гараж офисника — машино-места проекта, и в ответ он входит."""
    rows = [{"key": "underground_parking", "units": 100.0},
            {"key": "offices", "units": 0.0, "parking_units": 60.0},
            {"key": "kindergarten", "units": 250.0}]
    by = core.tep_units_by_measure(rows)
    assert by[presentation.PARKING_MEASURE] == 160.0, by
    assert by[presentation.PLACES_MEASURE] == 250.0
    assert core.tep_parking_spaces(rows) == 160.0


def test_the_measure_words_have_one_owner():
    """Движок, книга и тизер называют меру одним словом.

    Вторая копия слова разошлась бы молча: на экране «м/м», в книге «шт.» —
    и человек решал бы, одна это величина или две.
    """
    assert core.COUNT_PARKING is presentation.PARKING_MEASURE
    assert core.COUNT_FLATS is presentation.FLATS_MEASURE
    source = (ROOT / "main_legacy.py").read_text(encoding="utf-8")
    declaration = source[source.index("COUNT_FLATS = "):source.index("TEP_COUNT_MEASURE")]
    assert '"квартир"' not in declaration, "движок завёл свою копию слова меры"
    assert "_presentation." in declaration


def test_the_teaser_prints_parking_and_not_every_unit():
    """Строка «Машино-места» тизера — машино-места."""
    inputs = copy.deepcopy(core.DEFAULT_INPUTS)
    tep = {key: dict(value) for key, value in core.TEP_DEFAULT.items()}
    bundle = core._run_authoritative_model(inputs, tep, [], None)
    model = core.project_presentation(bundle, inputs, tep, None)
    rows = {row["key"]: row for row in _result()["tep"]["rows"]}
    assert model["tep"]["parking_units"] == rows["underground_parking"]["units"]
    assert model["tep"]["units_by_measure"][presentation.FLATS_MEASURE] > 1000
    assert "units" not in model["tep"], "общий итог вернулся в модель представления"


# --- страница ----------------------------------------------------------------

def _stand() -> str:
    """Списки и слова берутся у движка: копия разошлась бы с ним молча."""
    return ("const TEP_COUNT_MEASURE=" + json.dumps(core.TEP_COUNT_MEASURE, ensure_ascii=False)
            + ";\nconst COUNT_PARKING=" + json.dumps(core.COUNT_PARKING, ensure_ascii=False)
            + ";\nconst UNDERGROUND_PRODUCTS="
            + json.dumps(list(core.UNDERGROUND_PRODUCTS), ensure_ascii=False)
            + ";\nconst TRANSFER_NOTE_WORD=" + json.dumps(core.TRANSFER_NOTE_WORD) + ";\n"
            + _const("num") + "\n")


def _const(name: str) -> str:
    for line in core.PAGE.split("\n"):
        if line.startswith(f"const {name}="):
            return line
    raise AssertionError(f"на странице нет объявления const {name}=")


def _piece() -> str:
    start = core.PAGE.index(" const soldUnits=x=>Number(")
    end = core.PAGE.index("const REPORT_SECTIONS", start)
    piece = core.PAGE[start:end]
    return piece[:piece.rindex("}")]


def _render() -> str:
    stand = _stand() + """
const reportTep={innerHTML:''};
const document={getElementById:()=>null};
const r={summary:{underground_gns_sqm:60690,construction_volume_sqm:270690},
 tep:{core_under_gns:60690,
  total:{gns:270690,saleable:153600,transfer:25668.5},
  rows:[
   {key:'apartments',label:'Квартиры',gns:210000,saleable:136500,transfer:0,
    units:1362,saleable_units:1362,guest_units:0,transfer_units:0},
   {key:'underground_parking',label:'Подземный паркинг',gns:60690,saleable:0,
    transfer:0,units:1199,saleable_units:1090,guest_units:109,transfer_units:0},
   {key:'offices',label:'МФОЦ',gns:20000,saleable:14000,transfer:0,units:0,
    saleable_units:0,guest_units:0,transfer_units:0,under_gns:4200,
    parking_units:60,parking_saleable_units:60},
   {key:'kindergarten',label:'ДОО',gns:6300.3,saleable:0,transfer:5670.3,
    units:250,saleable_units:0,guest_units:0,transfer_units:250}]}};
"""
    out, _taken = page_blocks.run(stand + _piece(), "console.log(reportTep.innerHTML);")
    return out


def _cells(html: str, label: str) -> list[str]:
    for row in re.findall(r"<tr>(.*?)</tr>", html, re.S):
        if f"<td>{label}</td>" in row:
            return [re.sub(r"<[^>]+>", " ", cell).replace(" ", " ").strip()
                    for cell in re.findall(r"<td>(.*?)</td>", row, re.S)]
    raise AssertionError(f"строки {label} нет:\n{html}")


def test_the_page_row_names_its_own_measure():
    """«250 шт.» у детского сада читались штуками, а это места."""
    html = _render()
    assert _cells(html, "ДОО")[5].startswith("250 мест"), _cells(html, "ДОО")
    assert _cells(html, "Квартиры")[5] == "1 362 квартир", _cells(html, "Квартиры")
    assert _cells(html, "Подземный паркинг")[5].startswith("1 199 м/м")
    # Метровому продукту штук не полагается вовсе.
    assert _cells(html, "МФОЦ")[5] == "—", _cells(html, "МФОЦ")


def test_the_page_total_is_a_breakdown_and_not_a_sum():
    """Итога одним числом нет: 2 811 «штук» не значили ничего."""
    html = _render()
    foot = html[html.index("<tfoot>"):]
    cells = [re.sub(r"<[^>]+>", " ", one).replace(" ", " ").strip()
             for one in re.findall(r"<th>(.*?)</th>", foot, re.S)]
    built = cells[5]
    assert "1 362 квартир" in built and "250 мест" in built, built
    # Гараж объекта — машино-места, и он в ответе: 1 199 + 60.
    assert "1 259 м/м" in built, built
    assert "2 811" not in built.replace(" ", " "), "сумма несравнимого вернулась"


def test_the_page_header_no_longer_calls_everything_pieces():
    assert "<th>Построено</th><th>Продаётся</th>" in core.PAGE
    assert "<th>Построено, шт.</th>" not in core.PAGE


# --- книга -------------------------------------------------------------------

def test_the_book_declares_pricing_and_counting_apart():
    """Чем ценится и в чём считается — разные вопросы.

    У квартиры это метр и квартира. Один признак на оба перевёл бы среднюю
    цену квартиры с метра на штуку, ничего об этом не сказав.
    """
    by_key = {item[0]: item for item in vd.PRODUCT_ITEMS}
    assert by_key["apartments"][-2] == presentation.AREA_MEASURE
    assert by_key["apartments"][-1] == presentation.FLATS_MEASURE
    assert by_key["underground_parking"][-2] == presentation.PARKING_MEASURE
    assert by_key["offices"][-1] == presentation.PARKING_MEASURE, "гараж офисника — м/м"


def test_the_book_has_no_total_of_units():
    """Проверяется ПОСТРОЕННАЯ книга, а не исходник: колонку E складывает и
    блок себестоимости, и по тексту эти два итога не различить."""
    import io

    import openpyxl

    from xlsx_eval import Evaluator

    inputs = copy.deepcopy(core.DEFAULT_INPUTS)
    tep = {key: dict(value) for key, value in core.TEP_DEFAULT.items()}
    sys.setrecursionlimit(400000)
    content, _name, meta = core.build_project_workbook(inputs, tep, [], None)
    assert meta["missing"] == [], meta["missing"]
    workbook = openpyxl.load_workbook(io.BytesIO(content), data_only=False)
    evaluator = Evaluator(workbook)
    assert evaluator.cell(vd.DATA_SHEET, f"E{vd.PRODUCT_TOTAL_ROW}") is None, (
        "итог штук вернулся в скрытый источник дашборда")
    texts = [str(cell.value) for row in workbook[vd.DASHBOARD_SHEET].iter_rows()
             for cell in row if isinstance(cell.value, str)]
    assert "Количество" in texts, "колонка количества не названа"
    assert "Единиц" not in texts, "старая подпись «Единиц» осталась"
