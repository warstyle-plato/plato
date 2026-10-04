"""Дашборд: подземное — своей колонкой, а квартиры — со своим числом.

«Подземное опять входит в гнс, а единиц квартир нет» (владелец, 26.09.2026,
снимок листа «Дашборд»).

Померено на проекте с кладовыми и подземным гаражом объекта — четыре беды
одного корня, и все четыре про колонку, которая называет не то, что в ней
лежит:

1. Метры подземного паркинга стояли в колонке «ГНС, м²» и складывались её
   итогом: 41 965 м² под землёй читались наземной площадью.
2. Метры кладовых не доезжали до дашборда ВООБЩЕ: наземной у них нет, а
   подземной колонки не было.
3. «ГНС наземная» — делитель КАЖДОГО удельного на метр ГНС — считалась
   вычитанием из строительного объёма ТЭП, и вычитался оттуда только
   подземный паркинг: кладовые и гаражи объектов оставались в наземной, то
   есть на 5 800 м² больше движковой.
4. Числа квартир в книге не было нигде — ни на ТЭП, ни в структуре продукта,
   ни на дашборде. Считается оно теперь в блоке очередей и оттуда читается;
   в «Единицы» структуры продукта не кладётся — та колонка означает
   продаваемые МЕСТА, и квартиры сложились бы с ними.

Сверка идёт с ДВИЖКОМ, а не с прежними числами книги: книга — вторая
реализация той же методики, и «как было» здесь ничего не доказывает.

Запуск: python3 -m pytest tests/test_the_dashboard_keeps_the_underground_apart.py -q
"""

from __future__ import annotations

import copy
import io
import sys
from pathlib import Path

import openpyxl
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from xlsx_eval import Evaluator  # noqa: E402

import main as _wrapper  # noqa: E402
import v4_dashboard as vd  # noqa: E402

core = _wrapper.core

STORAGE_SQM = 1600.0
STORAGE_UNITS = 400.0
OBJECT_GARAGE_SQM = 4200.0


def _shape() -> tuple[dict, dict]:
    """Проект, на котором беды ВИДНЫ.

    На умолчаниях кладовых нет и гаража объекта нет — обе потери дают ноль, и
    проверка была бы зелёной на сломанном коде. Это предохранитель, а не
    оформление: он утверждается ниже отдельно.
    """
    inputs = copy.deepcopy(core.DEFAULT_INPUTS)
    inputs.update(project_name="Кладовые и гараж объекта",
                  storage_units=int(STORAGE_UNITS), storage_area_per_unit_sqm=4.0,
                  offices_enabled=True, offices_gba_sqm=20000,
                  offices_saleable_sqm=14000, offices_parking_under_spaces=120)
    tep = copy.deepcopy(core.TEP_DEFAULT)
    tep["storage"] = {**tep["storage"], "gns": STORAGE_SQM,
                      "total_area": STORAGE_SQM, "units": STORAGE_UNITS}
    offices = tep["offices"] if isinstance(tep["offices"], dict) else {}
    tep["offices"] = {**offices, "label": "МФОЦ / офисный центр", "gns": 20000.0,
                      "total_area": 18000.0, "useful": 14000.0, "saleable": 14000.0,
                      "transfer": 0, "units": 0, "under_gns": OBJECT_GARAGE_SQM}
    return inputs, tep


@pytest.fixture(scope="module")
def built():
    inputs, tep = _shape()
    result = core.calculate(core.CalcRequest(inputs=inputs, tep=tep, rates=[]))
    rows = {row["key"]: row for row in result["tep"]["rows"]}
    sys.setrecursionlimit(400000)
    content, _name, meta = core.build_project_workbook(inputs, tep, [], None)
    assert meta["missing"] == [], meta["missing"]
    workbook = openpyxl.load_workbook(io.BytesIO(content), data_only=False)
    return rows, workbook, Evaluator(workbook)


def _num(evaluator, sheet: str, address: str) -> float:
    return float(evaluator.cell(sheet, address) or 0)


def _product(evaluator, key: str, field: str) -> float:
    return _num(evaluator, vd.DATA_SHEET,
                f"{vd.PRODUCT_COLUMNS[field]}{vd.PRODUCT_ROWS[key]}")


def test_the_fixture_actually_has_something_underground(built):
    """Предохранитель: на умолчаниях все четыре беды дают ноль."""
    rows, _workbook, _evaluator = built
    assert rows["storage"]["gns"] == STORAGE_SQM
    assert rows["offices"]["under_gns"] == OBJECT_GARAGE_SQM
    assert rows["apartments"]["units"] > 1000


def test_the_underground_metres_are_not_in_the_above_ground_column(built):
    """То, что видно на снимке: 41 965 м² под землёй в колонке «ГНС»."""
    rows, _workbook, evaluator = built
    for key in core.UNDERGROUND_PRODUCTS:
        assert _product(evaluator, key, "gns") == 0, (
            f"у {key} наземная площадь взялась ниоткуда")
        assert abs(_product(evaluator, key, "under") - rows[key]["gns"]) <= 1.0, key


def test_the_storage_metres_reach_the_dashboard_at_all(built):
    """Метры кладовых терялись целиком: наземной нет, подземной колонки не было."""
    _rows, _workbook, evaluator = built
    assert abs(_product(evaluator, "storage", "under") - STORAGE_SQM) <= 1.0


def test_the_object_garage_is_underground_too(built):
    """Гараж объекта — подземная площадь объекта, а не его ГНС."""
    _rows, _workbook, evaluator = built
    assert abs(_product(evaluator, "offices", "under") - OBJECT_GARAGE_SQM) <= 1.0
    assert _product(evaluator, "offices", "gns") > 0, "наземная офисника пропала"


def test_the_totals_do_not_mix_the_two_heights(built):
    """Итог наземной колонки складывает только наземное."""
    _rows, _workbook, evaluator = built
    above = _num(evaluator, vd.DATA_SHEET,
                 f"{vd.PRODUCT_COLUMNS['gns']}{vd.PRODUCT_TOTAL_ROW}")
    under = _num(evaluator, vd.DATA_SHEET,
                 f"{vd.PRODUCT_COLUMNS['under']}{vd.PRODUCT_TOTAL_ROW}")
    assert under >= STORAGE_SQM + OBJECT_GARAGE_SQM
    rows_above = sum(_product(evaluator, key, "gns") for key, *_ in vd.PRODUCT_ITEMS)
    assert abs(above - rows_above) <= 1.0, "итог не равен тому, что над ним"
    for key in core.UNDERGROUND_PRODUCTS:
        assert _product(evaluator, key, "gns") == 0


def test_the_bases_of_every_unit_rate_are_the_engines():
    """Делители удельных — те же величины, что у движка (`unit_bases`).

    Прежде база «ГНС наземная» считалась вычитанием одного подземного
    паркинга, и кладовые с гаражом объекта оставались внутри. С 29.09.2026
    (решение 4 ревизии книги) баз четыре, и каждая сверяется с движком на
    проекте, где кладовые и гараж объекта есть.
    """
    inputs, tep = _shape()
    result = core.calculate(core.CalcRequest(inputs=inputs, tep=tep, rates=[]))
    sys.setrecursionlimit(400000)
    content, _name, meta = core.build_project_workbook(inputs, tep, [], None)
    evaluator = Evaluator(openpyxl.load_workbook(io.BytesIO(content), data_only=False))
    bases = result["summary"]["unit_bases"]
    for data_key, base in (("total_area_sqm", "total_area"), ("saleable_sqm", "saleable_area"),
                           ("core_above_sqm", "core_above_area"),
                           ("core_under_sqm", "core_under_area")):
        book = _num(evaluator, vd.DATA_SHEET, f"C{vd.DATA_ROWS[data_key]}")
        assert abs(book - bases[base]) <= 1.0, (data_key, book, bases[base])
    # Кладовые — в подземной базе МКД, гараж объекта — в суммарной.
    assert bases["core_under_area"] >= STORAGE_SQM
    assert bases["total_area"] >= bases["core_above_area"] + bases["core_under_area"] + OBJECT_GARAGE_SQM


def test_the_report_keeps_the_storage_metres_underground(built):
    """Источник беды: площадь кладовых писалась в «ГНС наземная» ОТЧЁТа."""
    _rows, _workbook, evaluator = built
    assert _num(evaluator, "ОТЧЕТ", f"B{core._V4_REPORT_STORAGE_ROW}") == 0
    assert abs(_num(evaluator, "ОТЧЕТ",
                    f"{core._V4_UNDER_COLUMN}{core._V4_REPORT_STORAGE_ROW}")
               - STORAGE_SQM) <= 1.0


def test_the_flats_are_counted_on_the_dashboard(built):
    """«Единиц квартир нет»: числа квартир в книге не было нигде."""
    rows, _workbook, evaluator = built
    engine = rows["apartments"]["units"]
    assert engine > 0
    assert abs(_product(evaluator, "apartments", "units") - engine) <= 1.0


def test_the_units_column_of_the_report_does_not_swallow_the_flats(built):
    """Квартиры НЕ кладутся в «Единицы» структуры продукта ОТЧЁТа.

    Итог той колонки складывает продаваемые машино-места и кладовые, и с
    движком он сверяется именно так (`test_the_report_product_block_adds_up`).
    Квартиры сложились бы с ними, и колонка перестала бы отвечать на
    какой-либо вопрос — та же беда, от которой написана эта правка, только в
    другом месте. Число квартир поэтому живёт в блоке очередей.
    """
    rows, _workbook, evaluator = built
    pieces = (rows["underground_parking"]["saleable_units"]
              + rows["offices"].get("parking_saleable_units", 0)
              + rows["storage"]["saleable_units"])
    total = _num(evaluator, "ОТЧЕТ", f"D{core._V4_PRODUCT_STRUCTURE_TOTAL_ROW}")
    assert abs(total - pieces) <= 1.0, (total, pieces)
    assert _num(evaluator, "ОТЧЕТ", "D46") == 0, "квартиры уехали в колонку мест"


def test_the_flat_count_follows_the_density_and_is_not_a_dead_number(built):
    """Правка плотности двигает метры квартир — обязана двигать и число квартир.

    Числом оно стояло бы мёртвым: книга показывала бы прежние квартиры при
    новых метрах, и обе величины выглядели бы посчитанными.
    """
    _rows, workbook, evaluator = built
    address = f"{vd.PRODUCT_COLUMNS['units']}{vd.PRODUCT_ROWS['apartments']}"
    before = _num(evaluator, vd.DATA_SHEET, address)
    saleable_before = _num(evaluator, "ОТЧЕТ", "C46")
    assert before > 0 and saleable_before > 0
    workbook[vd.QUEUE_SHEET]["K15"] = 1.2
    after_evaluator = Evaluator(workbook)
    after = float(after_evaluator.cell(vd.DATA_SHEET, address) or 0)
    saleable_after = float(after_evaluator.cell("ОТЧЕТ", "C46") or 0)
    assert abs(saleable_after - saleable_before * 1.2) <= 1.0, "стенд не тронул метры"
    assert abs(after - before * 1.2) <= 2.0, (
        f"квартиры не пошли за плотностью: {before} → {after}")


def test_a_flat_is_still_priced_by_the_metre(built):
    """Заполнить число квартир — не значит объявить квартиру штучным товаром.

    Прежде «штучным» считался продукт, у которого не заполнена продаваемая
    площадь. По такому правилу число квартир перевело бы их среднюю цену и
    удельную выручку с метра на квартиру, ничего об этом не сказав.
    """
    _rows, _workbook, evaluator = built
    revenue = _product(evaluator, "apartments", "revenue")
    saleable = _product(evaluator, "apartments", "saleable")
    units = _product(evaluator, "apartments", "units")
    assert revenue > 0 and saleable > 0 and units > 0
    assert abs(_product(evaluator, "apartments", "avg_price")
               - revenue * 1000 / saleable) <= 0.5, "средняя цена уехала на квартиру"
    # Выручка — на продаваемую (решение 4 ревизии книги), не на ГНС.
    assert abs(_product(evaluator, "apartments", "per_saleable")
               - revenue * 1000 / saleable) <= 0.5
    assert _product(evaluator, "apartments", "per_unit") == 0, "квартира не штучный товар"
    # А у машино-места удельная по-прежнему на штуку: метры гаража ни с чем
    # не сравнимы.
    parking_revenue = _product(evaluator, "underground_parking", "revenue")
    assert abs(_product(evaluator, "underground_parking", "per_unit")
               - parking_revenue * 1000
               / _product(evaluator, "underground_parking", "units")) <= 0.5


def test_the_measure_of_a_product_is_declared_not_guessed():
    """Правило «чем меряется продукт» объявлено в строке продукта.

    Пока оно выводилось из заполненности соседней колонки, заполнение колонки
    молча меняло смысл двух других.
    """
    # Чем ЦЕНИТСЯ и в чём СЧИТАЕТСЯ — разные поля: у квартиры это метр и
    # квартира (решение владельца 27.09.2026 — несравнимое не складывать).
    measures = {vd.AREA_MEASURE, vd.FLATS_MEASURE, vd.PARKING_MEASURE, vd.PIECES_MEASURE}
    for item in vd.PRODUCT_ITEMS:
        assert item[-2] in measures, (item[0], "чем ценится")
        assert item[-1] in measures, (item[0], "в чём считается")
    source = (ROOT / "v4_dashboard.py").read_text(encoding="utf-8")
    block = source[source.index("for (key, label, gns, under"):
                   source.index("t = PRODUCT_TOTAL_ROW")]
    assert "priced_by != BY_AREA" in block
    # Проверяются ДВЕ строки, которые выбирают делитель, а не весь блок:
    # «заполнена ли колонка» — законный вопрос при записи самой колонки и
    # незаконный при выборе того, чем меряется продукт.
    chooses = [line.strip() for line in block.split("\n")
               if line.strip().startswith("base =")
               or ('_cell(f"J{r}"' in line and "if " in line)]
    assert len(chooses) == 2, chooses
    for line in chooses:
        assert "piece" in line, f"делитель снова выбирается не по объявлению: {line}"
        assert "if units" not in line, f"делитель выводится из заполненности: {line}"


def test_the_visible_sheet_shows_the_underground_column(built):
    """Проверять то, что видит человек: колонка есть на самом листе «Дашборд»."""
    _rows, workbook, _evaluator = built
    sheet = workbook[vd.DASHBOARD_SHEET]
    texts = [str(cell.value) for row in sheet.iter_rows() for cell in row
             if isinstance(cell.value, str)]
    assert "Подземная, м²" in texts, "колонки подземного на листе нет"
    assert "ГНС наземная, м²" in texts, "наземная колонка не названа наземной"
    assert "ГНС, м²" not in texts, "старая двусмысленная подпись осталась"
