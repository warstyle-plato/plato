"""Передаваемое правится в очереди, а проектная строка — их сумма.

Владелец, 04.09.2026: «может проще в очередности передаваемую включить, меняя и
сумму в ТЭП и составляющие в очередности? приоритет в очередности», и там же —
«отдаём мы конкретные машиноместа, а не метры никакие», «это не рублёвая, а
штучная оценка». Значит у метровых продуктов передаётся площадь, у штучных —
места, а денег в этом нет вовсе: переданное строится и не продаётся.

Запуск: python3 -m pytest tests/test_the_queue_gives_away_its_own_metres.py -q
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402

PAGE = core.PAGE


def _function(name: str) -> str:
    start = PAGE.index(f"function {name}(")
    depth, index, seen = 0, PAGE.index("{", start), False
    while index < len(PAGE):
        if PAGE[index] == "{":
            depth, seen = depth + 1, True
        elif PAGE[index] == "}":
            depth -= 1
            if seen and depth == 0:
                return PAGE[start:index + 1]
        index += 1
    raise AssertionError(f"не нашёл конец функции {name}")


def test_the_measure_follows_the_product() -> None:
    """Метры у метровых, штуки у штучных — и это одно правило на странице."""
    assert "const PHASE_GIVEN_IN_UNITS=" in PAGE
    assert "'underground_parking','storage','above_parking'" in PAGE
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    program = (
        PAGE[PAGE.index("const PHASE_GIVEN_IN_UNITS="):PAGE.index("function setPhaseProductGiven(")]
        + _function("phaseGivenField") + "\n"
        "process.stdout.write(JSON.stringify({"
        "flat:phaseGivenField('apartments'),shop:phaseGivenField('ground_commercial'),"
        "park:phaseGivenField('underground_parking'),store:phaseGivenField('storage')}));"
    )
    done = subprocess.run([node, "-e", program], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[:600]
    got = json.loads(done.stdout)
    assert got == {"flat": "transfer", "shop": "transfer",
                   "park": "transfer_units", "store": "transfer_units"}


def test_the_queue_leads_and_the_project_row_is_the_sum() -> None:
    """Правка в очереди уменьшает её продаваемую, а проект становится суммой."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    program = (
        "const num=v=>String(v);\n"
        "let renders=0;\n"
        "function renderPhasing(){renders++}\nfunction renderTep(){}\n"
        "function renderInputs(){}\nfunction calculate(){}\nfunction tepRowToInputs(){}\n"
        "function syncPhaseProductSharesFromTep(){}\n"
        "function phaseProductDerived(key,field,index){return phasing.phases.length"
        "?Number((tep[key]||{})[field]||0)/phasing.phases.length:0}\n"
        "const tep={apartments:{gns:100000,saleable:60000,useful:60000,transfer:0},"
        "underground_parking:{gns:14000,units:400,saleable:0,transfer_units:0}};\n"
        "const phasing={phases:[{name:'О1',products:{}},{name:'О2',products:{}}]};\n"
        + PAGE[PAGE.index("const PHASE_GIVEN_IN_UNITS="):PAGE.index("function setPhaseProductTep(")]
        + "\nsetPhaseProductGiven(0,'apartments',5000);\n"
        "setPhaseProductGiven(1,'underground_parking',40);\n"
        "process.stdout.write(JSON.stringify({tep,phasing,renders}));"
    )
    done = subprocess.run([node, "-e", program], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[:900]
    got = json.loads(done.stdout)
    flats = got["tep"]["apartments"]
    first = got["phasing"]["phases"][0]["products"]["apartments"]
    # Отдала первая очередь: её продаваемая упала на переданное, вторая цела.
    assert first["transfer"] == 5000
    assert abs(first["saleable"] - (30000 - 5000)) < 0.01, first
    # Проектная строка — сумма очередей, и переданное в ней тоже сумма.
    assert flats["transfer"] == 5000
    assert abs(flats["saleable"] - (25000 + 30000)) < 0.01, flats
    assert flats["useful"] == flats["saleable"]
    # Машино-места: отдаются штуками, построенные не трогаются.
    park = got["tep"]["underground_parking"]
    second = got["phasing"]["phases"][1]["products"]["underground_parking"]
    assert second["transfer_units"] == 40 and park["transfer_units"] == 40
    assert park["units"] == 400 and park["saleable"] == 0
    assert got["renders"] == 2


def test_the_row_names_what_is_given_away() -> None:
    """В итоге строки переданное названо и мерой, и словами «не продаются»."""
    body = _function("renderPhasing")
    assert "передаётся ${num(givenTotal)}" in body
    assert "м² — не продаются" in body and "шт. — не продаются" in body
    assert "setPhaseProductGiven(" in body, "поле не выведено в ячейку очереди"
    assert "ГНС · продаваемая · шт. · передаётся" in PAGE
