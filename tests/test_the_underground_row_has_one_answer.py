"""Строка ТЭП подземного паркинга выводится ОДНИМ ответом.

Считали её четверо и по-разному. Страница шла по порядку «отказ → руками →
выгрузка → норматив», движок последней ступени не имел ВОВСЕ: проект без
ручных полей и без выгрузки оставался с тем, что прислали. На умолчаниях это
1 107,51 места — дробное число мест, которых не строят, — и 38 763 м² против
1 199 и 41 965 у страницы; правка норматива 35 → 40 движок не двигала.

Кладовые лежат на том же подземном этаже: страница их вычитала, движок нет, а
базу подземной части считает как «паркинг плюс кладовые» — на 6 000 м²
кладовых это 47 965 м² против 41 965, CAPEX +877,4 млн ₽ и LLCR 0,9529 против
0,9775 на одних вводных.

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


def _page_stand(tmp_path: Path) -> Path:
    """Настоящие функции страницы, а не их пересказ."""
    stand = tmp_path / "underground.js"
    stand.write_text("\n".join((
        page_const("PARKING_2118"),
        "const num=v=>String(v);",
        "const inputs=JSON.parse(process.argv[2]);",
        "let tep=JSON.parse(process.argv[3]);",
        function("getGlavapuUnderground"),
        function("normativeUnderground"),
        function("parkingRequirement"),
        function("undergroundAreaPerSpace"),
        function("repairParkingFromGlavapu"),
        function("underlayStorageInParking"),
        "if(repairParkingFromGlavapu())underlayStorageInParking();",
        "console.log(JSON.stringify(tep.underground_parking));",
    )), encoding="utf-8")
    return stand


@pytest.mark.parametrize("case", sorted(BRANCHES))
def test_the_page_and_the_engine_say_the_same(case: str, tmp_path: Path) -> None:
    """Один пример — один ответ, на каждой ветке порядка."""
    if not shutil_which("node"):
        pytest.skip("node недоступен — страницу не погонять")
    inputs = copy.deepcopy(core.DEFAULT_INPUTS)
    inputs.update(BRANCHES[case])
    tep = _tep(STORAGE_SQM)
    stand = _page_stand(tmp_path)
    done = subprocess.run(
        ["node", str(stand), json.dumps(inputs, default=str), json.dumps(tep, default=str)],
        capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr[:800]
    page = json.loads(done.stdout)
    engine = _row(inputs, tep)
    assert round(float(page["units"]), 1) == round(engine["units"], 1), case
    assert abs(float(page["gns"]) - engine["gns"]) < 0.2, (case, page["gns"], engine["gns"])


def shutil_which(name: str) -> str | None:
    import shutil
    return shutil.which(name)


def test_the_storage_floor_is_counted_once() -> None:
    """Кладовые лежат НА этаже гаража, а не рядом с ним.

    База подземной части — «паркинг плюс кладовые», значит из строки гаража
    кладовые вычтены. Проверяется тождеством, а не числом: база обязана
    совпасть с самим этажом.
    """
    tep = _tep(STORAGE_SQM)
    inputs = copy.deepcopy(core.DEFAULT_INPUTS)
    bare = core.calculate(core.CalcRequest(
        inputs=copy.deepcopy(inputs), tep=_tep(), rows=[]))
    with_storage = core.calculate(core.CalcRequest(
        inputs=copy.deepcopy(inputs), tep=tep, rows=[]))
    envelope = next(row for row in bare["tep"]["rows"]
                    if row["key"] == "underground_parking")["gns"]
    # Предохранитель: на пустых кладовых проверка не значит ничего.
    assert STORAGE_SQM > 0 and envelope > STORAGE_SQM
    assert with_storage["tep"]["core_under_gns"] == pytest.approx(envelope, abs=0.2)


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
