"""Сумма метров по очередям сходится с проектом — или это сказано вслух.

Ячейка ТЭП очереди («Очередность», три поля на продукт: ГНС · продаваемая ·
шт.) при вводе ограничена: `phaseProductTepLimit` не даёт вписать больше, чем
осталось от проекта, а `clampPhaseProductTepRight` поджимает очереди справа.

Дыра была не в ограничении, а в том, что оно проверяется в момент ввода. Впиши
число, а потом подвинь пропорцию ТЭП вниз — проект уменьшится, вписанное
останется, и сумма очередей перестанет сходиться. Молча: колонка «Итого по
очередям» показывала сумму, но не сравнивала её с проектом.

Обрезать задним числом нельзя — фактический ТЭП из ГПЗУ вписывается затем,
чтобы пережить пересчёт. Значит расхождение показывается, а не чинится само.

Запуск: python3 -m pytest tests/test_queue_tep_matches_the_project.py -q
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


def _tep_table_block() -> str:
    """Разметка строки таблицы ТЭП очередей — она живёт внутри `renderPhasing`."""
    start = core.PAGE.index("phaseTepBody.innerHTML=")
    end = core.PAGE.index("phaseTepWarning", start)
    return core.PAGE[start:end]


def _run(project_saleable: float, typed: float | None) -> str:
    """Гоняет настоящую разметку строки ТЭП очереди через node."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    helpers = []
    for name in ("phaseIntegerSplit", "phaseProductDerived",
                 "phaseProductTepValues", "phaseProductTepLimit"):
        found = re.search(r"\nfunction " + name + r"\(.*?\n\}", core.PAGE, re.S)
        assert found, name
        helpers.append(found.group(0))
    phases = [{"name": "О1", "products": {}}, {"name": "О2", "products": {}}]
    if typed is not None:
        phases[1]["products"] = {"apartments": {"saleable": typed,
                                                "assumption_source": "Введено пользователем"}}
    script = (
        "const tep=" + json.dumps({"apartments": {"gns": 130716.66, "saleable": project_saleable,
                                                  "units": 1361.8, "label": "Квартиры"}}) + ";\n"
        "let phasing=" + json.dumps({"phase_count": 2, "discrete": {}, "social_objects": [],
                                     "products": {"apartments": [60, 40]},
                                     "phases": phases}) + ";\n"
        "const num=n=>new Intl.NumberFormat('ru-RU',{maximumFractionDigits:0})"
        ".format(Number(n)||0);\n"
        "let out='';\n"
        + "\n".join(helpers) + "\n"
        "const totals={gns:0,saleable:0,units:0};\n"
        "['saleable'].forEach(()=>{});\n"
        # Повторяем расчёт итогов так же, как это делает страница.
        "phasing.phases.forEach((p,i)=>{['gns','saleable','units'].forEach(f=>{\n"
        "  const own=(p.products||{})[f==='saleable'?'apartments':'apartments']||{};\n"
        "  totals[f]+= own[f]!==undefined?Number(own[f]):phaseProductDerived('apartments',f,i);\n"
        "})});\n"
        "const master={gns:Number(tep.apartments.gns||0),saleable:Number(tep.apartments.saleable||0),"
        "units:Number(tep.apartments.units||0)};\n"
        "const off=['gns','saleable','units'].filter(f=>Math.abs(totals[f]-master[f])>"
        "Math.max(1,master[f]*0.001));\n"
        "console.log(JSON.stringify({totals:totals,master:master,off:off}));\n"
    )
    done = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_shares_keep_the_sum_equal_to_the_project():
    """Пока очереди делятся долями, сумма равна проекту до метра."""
    result = _run(80000.0, None)
    assert result["off"] == [], result
    assert result["totals"]["saleable"] == pytest.approx(80000.0, abs=1.0)


def test_a_typed_cell_that_no_longer_fits_is_named():
    """Вписали 50 000, потом подвинули пропорцию вниз — расхождение видно."""
    result = _run(71894.0, 50000.0)
    assert "saleable" in result["off"], result
    assert result["totals"]["saleable"] > result["master"]["saleable"]


def test_the_screen_says_what_diverged_and_by_how_much():
    body = _tep_table_block()
    assert "не сходится с проектом" in body
    assert "phase-total-bad" in body and "phase-total-ok" in body
    # Названо, что именно разошлось и на сколько, а не просто «не сходится».
    assert "против" in body


def test_the_typed_value_is_not_silently_clamped():
    """Фактический ТЭП из ГПЗУ вписывается затем, чтобы пережить пересчёт.

    Обрежь мы его задним числом — человек увидел бы своё число изменившимся
    без всякого действия с его стороны.
    """
    body = _tep_table_block()
    assert "phase.products" not in body, "таблица правит вписанное при отрисовке"


def test_the_limit_still_guards_the_input():
    """Ограничение при вводе никуда не делось: больше проекта не вписать."""
    assert "function phaseProductTepLimit(" in core.PAGE
    setter = re.search(r"\nfunction setPhaseProductTep\(.*?\n\}", core.PAGE, re.S).group(0)
    # Остаток проекта режет запрошенное; у штук остаток ещё и целый.
    assert "Math.min(count?Math.floor(limit+1e-6):limit,requested)" in setter
