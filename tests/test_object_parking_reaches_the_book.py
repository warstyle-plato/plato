"""Паркинг отдельно стоящих объектов доезжает не только до отчёта, но и до книги.

Гараж под ОСЗ ставится на кадастр, значит продаётся машино-местами (владелец,
05.09.2026: «у осз должны быть паркинг или подземные или наземные напервых
этажах», «продают машиноместами конечно»). Число его мест задаёт ЧЕЛОВЕК:
приобъектный норматив — асфальт вдоль проезда, и в гараж он не заглядывает
(06.09.2026: «это кусок асфальта»).

Книга обязана считать то же. Методику меняют в ДВУХ местах — в движке и в
книге, — и цена забытой половины уже измерена: на вводных с живым гаражом книга
давала выручку на его мест меньше, чем движок, а CAPEX — ровно на подземный
паркинг объектов, и следом расходились EBITDA, стоимость финансирования, чистая
прибыль и пик ПФ.

**Проверка держит СВОИ вводные, и это не украшение.** В умолчаниях гараж
объектов не задан вовсе — то есть весь набор из без малого пяти тысяч проверок
в эту ветку не заходит и остаётся зелёным при полностью забытой книге. Ровно
так однажды пережила 581 тест ставка ПФ ниже специальной. Поэтому здесь стоит
предохранитель: не стало мест — тест говорит об этом, а не зеленеет впустую.

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
    # Гараж задан руками — норматив его не порождает. К1 и К2 стоят затем,
    # чтобы норматив ПОСЧИТАЛСЯ: проверка «норма ничего не строит» без
    # посчитанной нормы не значит ничего.
    x.update(offices_enabled=True, retail_enabled=True,
             parking_k1=1.0, parking_k2=0.5,
             offices_parking_under_spaces=80, offices_parking_over_spaces=20,
             offices_parking_guest_spaces=8,
             retail_parking_under_spaces=60, retail_parking_over_spaces=0)
    x.update(over)
    return x


def _tep() -> dict:
    t = copy.deepcopy(core.TEP_DEFAULT)
    t["offices"].update(gns=10000, total_area=9400, saleable=6000)
    t["standalone_retail"].update(gns=10000, total_area=9400, saleable=6000)
    return t


def test_the_project_actually_has_object_parking() -> None:
    """Предохранитель: без мест зеленеть этому файлу нельзя."""
    demand = core.apply_object_parking(_inputs(), _tep())
    assert demand["own_units"] == 160, (
        "у проверочного проекта не осталось мест гаража — "
        "остальные проверки этого файла перестали что-либо значить")
    assert demand["required_total"] > 0, (
        "норматив не посчитан — проверять, что он ничего не строит, не на чем")


def test_the_places_reach_the_tep_row_of_their_own_object() -> None:
    """Места объекта принадлежат объекту, а не общей куче."""
    t = _tep()
    demand = core.apply_object_parking(_inputs(), t)
    assert t["offices"]["parking_units"] == 100
    assert t["offices"]["under_gns"] == pytest.approx(
        80 * demand["area_per_space_sqm"])
    # Подземная площадь объекта — подземная: в наземную ГНС она не входит.
    assert t["offices"]["gns"] == 10000
    # И норматив в это число не попал ни одним местом.
    offices_norm = next(r for r in demand["rows"] if r["tep_key"] == "offices")
    assert offices_norm["required_spaces"] != 100


def test_first_floor_places_take_metres_out_of_the_saleable_not_the_gns() -> None:
    """Тот же этаж нельзя продать дважды — офисом и машино-местами."""
    t = _tep()
    core.apply_object_parking(_inputs(offices_parking_over_spaces=40,
                                      offices_parking_under_spaces=40), t)  # noqa: E501
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


def test_the_mall_builds_its_parking_and_sells_none_of_it() -> None:
    """Место в ТЦ не покупают — там обеспеченность посетителей.

    Владелец, 06.09.2026: «Если это про обеспеченность ТЦ, то там конечно
    никто купить место не может! Где ты видел такие ТЦ?» Метры и CAPEX при
    этом остаются: паркинг строится, он просто не товар.
    """
    t = _tep()
    core.apply_object_parking(_inputs(), t)
    assert t["standalone_retail"]["parking_units"] == 60, "места строятся"
    assert t["standalone_retail"]["parking_saleable_units"] == 0, "и не продаются"
    assert t["standalone_retail"]["under_gns"] == pytest.approx(60 * 35)


def test_the_office_sells_all_but_the_guest_places() -> None:
    """«Если офисник, то там продаются конечно и остается немного гостевых»."""
    t = _tep()
    core.apply_object_parking(_inputs(), t)
    assert t["offices"]["parking_units"] == 100, "построено"
    assert t["offices"]["parking_saleable_units"] == 92, "продаётся, кроме 8 гостевых"


def test_the_book_sells_the_same_places_as_the_engine() -> None:
    """Книга и движок продают одни места, а не два достоверных вида.

    Проверка держит СВОИ вводные не зря: у ТЦ мест 60, и если книга продаст их
    заодно с офисными, разрыв будет ровно на цену этих мест.
    """
    openpyxl = pytest.importorskip("openpyxl")
    from xlsx_eval import Evaluator

    x, t = _inputs(), _tep()
    content, _, meta = core.build_project_workbook(
        dict(x), copy.deepcopy(t), [], None, project_name="Паркинг")
    assert not meta.get("missing"), meta.get("missing")
    sys.setrecursionlimit(400000)
    evaluator = Evaluator(openpyxl.load_workbook(io.BytesIO(content), data_only=False))
    # Офисы продают 92 из 100, ТЦ — ни одного из 60.
    assert evaluator.cell("ОБЪЕКТЫ", "B32") == pytest.approx(92)
    assert evaluator.cell("ОБЪЕКТЫ", "B60") == pytest.approx(0)
