"""Строка ТЭП подземного паркинга выводится ОДНИМ ответом.

Считали её четверо и по-разному. Страница шла по порядку «отказ → руками →
выгрузка → норматив», движок последней ступени не имел ВОВСЕ: проект без
ручных полей и без выгрузки оставался с тем, что прислали. На умолчаниях это
1 107,51 места — дробное число мест, которых не строят, — и 38 763 м² против
1 199 и 41 965 у страницы; правка норматива 35 → 40 движок не двигала.

Кладовые при этом площадь гаража НЕ уменьшают, а прибавляют свою (решение
владельца, 13.09.2026). Страница их вычитала, и норматив 35 м²/место
превращался в фактические 33,67 при 400 кладовых по 4 м²: гараж терял метры,
которых в нём и не было — ни один источник не даёт нам этаж целиком, всюду
стоит «места × норматив».

Прежний сторож этого места (`test_storage_shares_the_underground_floor.py`)
держал ОБРАТНОЕ утверждение и вместе с ним функцию страницы, которой больше
нет: он снят, а не ослаблен — двух сторожей у одного утверждения не бывает, они
расходятся молча. Страничную половину держит здесь же сверка веток: она гоняет
настоящий код страницы на ТЭП с кладовыми.

Запуск: python3 -m pytest tests/test_the_underground_row_has_one_answer.py -q
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import main_legacy as core  # noqa: E402

import page_blocks  # noqa: E402
from page_blocks import function, page_const  # noqa: E402

STORAGE_SQM = 6000.0


def _tep(storage: float = 0.0) -> dict:
    tep = copy.deepcopy(core.TEP_DEFAULT)
    if storage > 0:
        tep["storage"] = {**tep["storage"], "units": 400, "gns": storage,
                          "total_area": storage, "saleable": storage}
    return tep


def _row(inputs: dict, tep: dict) -> dict:
    result = core.calculate(core.CalcRequest(
        inputs=copy.deepcopy(inputs), tep=copy.deepcopy(tep), rows=[]))
    return next(row for row in result["tep"]["rows"]
                if row["key"] == "underground_parking")


BRANCHES = {
    "пусто — считает норматив": {},
    "руками места": {"underground_manual_spaces": 1199},
    "руками места и площадь": {"underground_manual_spaces": 1199,
                               "underground_manual_gns_sqm": 41965},
    "руками только площадь": {"underground_manual_gns_sqm": 41965},
    "отказ от подземного": {"underground_parking_disabled": True},
    "другой норматив площади": {"underground_area_per_space_sqm": 40},
}


@pytest.mark.parametrize("case", sorted(BRANCHES))
def test_the_page_and_the_engine_say_the_same(case: str) -> None:
    """Один пример — один ответ, на каждой ветке порядка.

    Куски страницы стенд добирает САМ: перечисленные руками, они отстают от
    неё — в `repairParkingFromGlavapu` появился признак типа проекта, и все
    пять примеров упали на «isNonResidential is not defined», то есть на
    неполноте стенда, а не на том, что он проверяет.
    """
    inputs = copy.deepcopy(core.DEFAULT_INPUTS)
    inputs.update(BRANCHES[case])
    tep = _tep(STORAGE_SQM)
    prelude = (
        "const num=v=>String(v);\n"
        f"const inputs={json.dumps(inputs, default=str)};\n"
        f"let tep={json.dumps(tep, default=str)};\n"
    )
    tail = ("repairParkingFromGlavapu();\n"
            "console.log(JSON.stringify(tep.underground_parking));\n")
    out, _ = page_blocks.run(prelude, tail)
    page = json.loads(out)
    engine = _row(inputs, tep)
    assert round(float(page["units"]), 1) == round(engine["units"], 1), case
    assert abs(float(page["gns"]) - engine["gns"]) < 0.2, (case, page["gns"], engine["gns"])


def shutil_which(name: str) -> str | None:
    import shutil
    return shutil.which(name)


def test_the_storage_adds_its_metres_and_the_garage_keeps_the_norm() -> None:
    """Кладовые прибавляют свои метры, а гараж остаётся «места × норматив».

    Вычитание превращало норматив в фактические 33,67 м²/место и отнимало у
    гаража метры, которых в нём не было: площадь гаража всюду считается как
    «места × норматив» — и в выгрузке ГлавАПУ, и в ручном шаблоне, и в паре
    «места ↔ площадь» на странице. Этажа целиком нам не даёт ни один источник.
    """
    inputs = copy.deepcopy(core.DEFAULT_INPUTS)
    bare = _row(inputs, _tep())
    with_storage = core.calculate(core.CalcRequest(
        inputs=copy.deepcopy(inputs), tep=_tep(STORAGE_SQM), rows=[]))
    row = next(item for item in with_storage["tep"]["rows"]
               if item["key"] == "underground_parking")
    # Предохранитель: на пустых кладовых проверка не значит ничего.
    assert STORAGE_SQM > 0 and bare["gns"] > STORAGE_SQM
    # Гараж не заметил кладовых вовсе.
    assert row["gns"] == pytest.approx(bare["gns"], abs=0.2)
    assert row["gns"] == pytest.approx(
        row["units"] * core.underground_area_per_space(inputs), abs=0.2)
    # А подземная база выросла ровно на их метры.
    assert with_storage["tep"]["core_under_gns"] == pytest.approx(
        bare["gns"] + STORAGE_SQM, abs=0.2)


def test_the_norm_moves_the_row() -> None:
    """Норматив площади на место двигает строку — иначе поле ничего не обещает.

    Прежде движок читал его только в ручной ветке и в выгрузке: на проекте,
    набранном руками, правка 35 → 40 не двигала ни метра.
    """
    inputs = copy.deepcopy(core.DEFAULT_INPUTS)
    rows = {}
    for per in (35.0, 40.0):
        rows[per] = _row({**inputs, "underground_area_per_space_sqm": per}, _tep())
    assert rows[35.0]["units"] == rows[40.0]["units"]
    assert rows[40.0]["gns"] == pytest.approx(rows[35.0]["gns"] / 35.0 * 40.0, rel=1e-9)


def test_the_default_row_is_computed_not_written() -> None:
    """Умолчание строки считается тем же ответом, что и сама строка.

    Литерал нёс 1 107,5142857 места — дробное число мест, которых не строят, —
    и площадь ещё одной, пятой методики.
    """
    row = core.TEP_DEFAULT["underground_parking"]
    computed = core.underground_tep_row(core.DEFAULT_INPUTS, core.TEP_DEFAULT)
    assert computed, "умолчание не из чего вывести — проверка не значит ничего"
    assert row["units"] == computed["units"] and row["gns"] == computed["gns"]
    assert float(row["units"]).is_integer(), row["units"]


def test_the_queues_add_up_to_the_project() -> None:
    """Очередь получает долю уже посчитанной строки, а не считает свою.

    Деление шло по ПРИСЛАННОЙ строке, а проект считался по выведенной: на
    6 000 м² кладовых сумма очередей выходила 41 965 м² против 35 965 у
    одиночного расчёта — этаж кладовых доставался очередям вторым экземпляром.
    """
    tep = _tep(STORAGE_SQM)
    inputs = copy.deepcopy(core.DEFAULT_INPUTS)
    phasing = {
        "enabled": True, "phase_count": 3, "phase_gap_months": 24,
        "cost_inflation_pct": 8,
        "phases": [{"name": f"О{i + 1}", "start_offset_months": 24 * i,
                    "construction_months": 24} for i in range(3)],
        "products": {key: [40, 35, 25] for key in
                     ("apartments", "ground_commercial", "underground_parking", "storage")},
        "social_objects": [], "discrete": {},
    }
    single = _row(inputs, tep)
    phased = core.calculate_phased(core.PhasedCalcRequest(
        inputs=copy.deepcopy(inputs), tep=copy.deepcopy(tep), rows=[], phasing=phasing))
    queues = [next(row for row in phase["result"]["tep"]["rows"]
                   if row["key"] == "underground_parking")
              for phase in phased["phases"]]
    # Предохранитель: одна очередь — не деление, и проверка была бы пустой.
    assert len(queues) == 3 and all(row["units"] > 0 for row in queues)
    assert sum(row["units"] for row in queues) == pytest.approx(single["units"])
    assert sum(row["gns"] for row in queues) == pytest.approx(single["gns"], abs=0.2)


def test_a_declared_row_is_left_alone() -> None:
    """Объявленную строку не выводят заново: у неё свой источник.

    Требование договора КРТ называет и места, и площадь, и с нормативом они не
    совпадают.
    """
    tep = _tep()
    tep["underground_parking"] = {**tep["underground_parking"], "units": 42.0,
                                  "gns": 1234.0, "total_area": 1234.0,
                                  core.TEP_ROW_DECLARED: True}
    core.apply_underground_tep_row(copy.deepcopy(core.DEFAULT_INPUTS), tep)
    assert tep["underground_parking"]["units"] == 42.0
    assert tep["underground_parking"]["gns"] == 1234.0


def test_nothing_to_compute_leaves_the_row_untouched() -> None:
    """«Не из чего вывести» — не «паркинга нет»."""
    tep = _tep()
    tep["apartments"] = {**tep["apartments"], "saleable": 0.0, "units": 0.0}
    tep["underground_parking"] = {**tep["underground_parking"], "units": 7.0, "gns": 245.0}
    inputs = copy.deepcopy(core.DEFAULT_INPUTS)
    inputs["underground_manual_spaces"] = 0
    inputs["underground_manual_gns_sqm"] = 0
    assert core.underground_tep_row(inputs, tep) is None
    core.apply_underground_tep_row(inputs, tep)
    assert tep["underground_parking"]["units"] == 7.0
