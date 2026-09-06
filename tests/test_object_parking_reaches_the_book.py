"""Приобъектный паркинг нежилья доезжает не только до отчёта, но и до книги.

Владелец, 05.09.2026: «у осз должны быть паркинг или подземные или наземные
напервых этажах», «продают машиноместами конечно». Движок это выучил: места
считаются нормативом, размещаются двумя числами, их площадь идёт в подземную
ГНС, СМР — по подземной ставке, а сами места продаются продуктом.

Книга обязана считать то же. Методику меняют в ДВУХ местах — в движке и в
книге, — и цена забытой половины уже измерена: на вводных с живым паркингом
книга давала выручку 47 252,8 против 47 662,0 у движка (ровно выручка мест) и
CAPEX 40 783,5 против 41 682,6 (ровно подземный паркинг объектов), а следом
расходились EBITDA, стоимость финансирования, чистая прибыль и пик ПФ.

**Проверка держит СВОИ вводные, и это не украшение.** На умолчаниях К1 и К2
нулевые, московский расчёт отказывается и мест выходит ноль — то есть весь
набор из без малого пяти тысяч проверок в эту ветку не заходит вовсе и остаётся
зелёным при полностью забытой книге. Ровно так однажды пережила 581 тест ставка
ПФ ниже специальной. Поэтому здесь стоит предохранитель: не стало мест — тест
говорит об этом, а не зеленеет впустую.

Запуск: python3 -m pytest tests/test_object_parking_reaches_the_book.py -q
"""

from __future__ import annotations

import copy
import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import main_legacy as core  # noqa: E402


def _inputs(**over) -> dict:
    x = dict(core.DEFAULT_INPUTS)
    # К1 и К2 — те самые множители, без которых московский расчёт отказывается.
    # Здесь они заданы намеренно: без них у проекта нет ни одного приобъектного
    # места, и проверять было бы нечего.
    x.update(offices_enabled=True, retail_enabled=True,
             parking_k1=1.0, parking_k2=0.5)
    x.update(over)
    return x


def _tep() -> dict:
    t = copy.deepcopy(core.TEP_DEFAULT)
    t["offices"].update(gns=10000, total_area=9400, saleable=6000)
    t["standalone_retail"].update(gns=10000, total_area=9400, saleable=6000)
    return t


def test_the_project_actually_has_object_parking() -> None:
    """Предохранитель: без мест зеленеть этому файлу нельзя."""
    demand = core.parking_demand(_inputs(), _tep())
    assert demand["required_total"] > 0, (
        "у проверочного проекта не осталось приобъектных мест — "
        "остальные проверки этого файла перестали что-либо значить")
    assert demand["check"]["state"] == "ok"


def test_the_places_reach_the_tep_row_of_their_own_object() -> None:
    """Места объекта принадлежат объекту, а не общей куче."""
    t = _tep()
    demand = core.apply_object_parking(_inputs(), t)
    offices = next(r for r in demand["rows"] if r["tep_key"] == "offices")
    assert t["offices"]["parking_units"] == offices["required_spaces"]
    assert t["offices"]["under_gns"] == pytest.approx(
        offices["required_spaces"] * demand["area_per_space_sqm"])
    # Подземная площадь объекта — подземная: в наземную ГНС она не входит.
    assert t["offices"]["gns"] == 10000


def test_first_floor_places_take_metres_out_of_the_saleable_not_the_gns() -> None:
    """Тот же этаж нельзя продать дважды — офисом и машино-местами."""
    t = _tep()
    core.apply_object_parking(_inputs(offices_parking_over_spaces=40,
                                      offices_parking_under_spaces=40), t)
    assert t["offices"]["gns"] == 10000, "ГНС не меняется: этажи и так его"
    assert t["offices"]["saleable"] == pytest.approx(6000 - 40 * 35)


def test_the_book_counts_the_same_parking_as_the_engine() -> None:
    """Книга и отчёт на одном расчёте — одни числа, а не два достоверных вида."""
    openpyxl = pytest.importorskip("openpyxl")
    from xlsx_eval import Evaluator

    x, t = _inputs(), _tep()
    report = core.calculate(core.CalcRequest(
        inputs=dict(x), tep=copy.deepcopy(t), rates=[]))
    content, _, _ = core.build_project_workbook(
        dict(x), copy.deepcopy(t), [], None, project_name="Паркинг")
    sys.setrecursionlimit(400000)
    evaluator = Evaluator(openpyxl.load_workbook(io.BytesIO(content), data_only=False))
    checks = evaluator.workbook["ПРОВЕРКИ"]
    problems = []
    for row in range(1, 130):
        name = checks[f"A{row}"].value
        if not name or not str(name).lower().startswith(("паритет", "паритет с движком")):
            continue
        if evaluator.cell("ПРОВЕРКИ", f"F{row}") == "OK":
            continue
        problems.append(f"{name}: {evaluator.cell('ПРОВЕРКИ', f'B{row}')} "
                        f"против {evaluator.cell('ПРОВЕРКИ', f'C{row}')}")
    assert not problems, problems
    assert report["summary"]["revenue"] > 0
