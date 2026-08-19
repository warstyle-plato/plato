"""ТЭП собирают руками, и известно обычно одно число из трёх.

Про офисный центр девелопер знает продаваемую площадь; общая и ГНС из неё
выводятся, а не выясняются заново. Про площадку по ППТ — наоборот, известна
ГНС. Пропорции работают в обе стороны (просьба владельца, 19.08.2026):

* офисы и ТЦ — общая 94% ГНС (толщина стен), продаваемая 60% общей;
* жильё и встроенная коммерция — методика ГлавАПУ: НП 90% ГНС. На ней же
  откалиброван городской норматив паркинга, поэтому число не наше.

Заполняются только пустые ячейки: введённое человеком и пришедшее из ГлавАПУ
сильнее пропорции — иначе таблица начнёт менять числа под руками.

Запуск: python3 -m pytest tests/test_tep_ratios_fill_both_ways.py -q
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


def _fill(key: str, row: dict) -> dict:
    """Гоняет настоящую функцию страницы через node."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    body = re.search(r"function tepFillByRatios\(key,row\)\{.*?\n\}", core.PAGE, re.S)
    assert body, "tepFillByRatios не найдена на странице"
    script = (
        f"const TEP_RATIOS={json.dumps(core.TEP_RATIOS, ensure_ascii=False)};\n"
        + body.group(0)
        + f"\nconsole.log(JSON.stringify(tepFillByRatios({json.dumps(key)},"
        + f"{json.dumps(row, ensure_ascii=False)})));"
    )
    done = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_the_office_is_built_from_the_saleable_area():
    """Известна продаваемая — считаются общая и ГНС."""
    filled = _fill("offices", {"gns": 0, "total_area": 0, "saleable": 18000, "useful": 0})
    assert filled["total_area"] == pytest.approx(30000.0, rel=1e-6)
    assert filled["gns"] == pytest.approx(30000.0 / 0.94, rel=1e-6)
    assert filled["useful"] == filled["saleable"]


def test_the_office_is_built_from_the_gns():
    """Известна ГНС — считаются общая и продаваемая."""
    filled = _fill("offices", {"gns": 30000, "total_area": 0, "saleable": 0, "useful": 0})
    assert filled["total_area"] == pytest.approx(28200.0, rel=1e-6)
    assert filled["saleable"] == pytest.approx(16920.0, rel=1e-6)


def test_what_is_typed_is_not_touched():
    """Пропорция достраивает пустое, а не правит введённое."""
    filled = _fill("offices", {"gns": 30000, "total_area": 26000, "saleable": 14000, "useful": 0})
    assert filled["gns"] == 30000
    assert filled["total_area"] == 26000
    assert filled["saleable"] == 14000


def test_housing_keeps_the_city_methodology():
    """У жилья доля НП — часть чужой методики, на ней стоит норматив паркинга."""
    assert core.TEP_RATIOS["apartments"]["total_of_gns"] == 0.90
    filled = _fill("apartments", {"gns": 100000, "total_area": 0, "saleable": 0, "useful": 0})
    assert filled["total_area"] == pytest.approx(90000.0, rel=1e-6)


def test_a_product_without_ratios_is_left_alone():
    """Паркинг, кладовые и соцобъекты пропорциями не достраиваются."""
    row = {"gns": 0, "total_area": 0, "saleable": 5000, "useful": 0}
    assert _fill("underground_parking", row) == row


def test_the_page_takes_the_ratios_from_the_engine():
    """Копии таблицы на странице нет — подставляется движковая."""
    assert "const TEP_RATIOS=" in core.PAGE
    assert core.TEP_RATIOS_PLACEHOLDER not in core.PAGE
    assert '"total_of_gns": 0.94' in json.dumps(core.TEP_RATIOS, ensure_ascii=False) \
        or '"total_of_gns":0.94' in json.dumps(core.TEP_RATIOS, ensure_ascii=False)


def test_the_cell_editor_fills_the_neighbours():
    """Правка одной ячейки достраивает соседние — иначе пропорции не видны."""
    handler = core.PAGE[core.PAGE.index("function tepCellChanged"):]
    handler = handler[:handler.index("function updateTepTotals")]
    assert "tepFillByRatios(key,tep[key])" in handler
    assert "calculate()" in handler


def test_the_ratios_are_printed_next_to_the_table():
    """Подставленное число, происхождение которого не видно, неотличимо от введённого."""
    body = core.PAGE[core.PAGE.index("function renderTepRatioNote"):]
    body = body[:body.index("function tepCellChanged")]
    assert "общая " in body and "% ГНС" in body and "продаваемая " in body
    assert "r.source" in body, "происхождение доли не названо"
    assert 'id="tepRatioNote"' in core.PAGE


def test_a_known_saleable_area_fills_the_gns_in_the_inputs():
    """Себестоимость объекта берётся из вводных: нулевая ГНС при живой выручке —
    расход, которого нет."""
    body = core.PAGE[core.PAGE.index("function syncTep(rerender=true){"):]
    body = body[:body.index("function addMonthsJS")]
    assert "tepFillByRatios(key," in body
    assert "inputs[gbaId]=filled.gns" in body
    assert "inputsFilled=true" in body
    assert "return inputsFilled" in body

    handler = core.PAGE[core.PAGE.index("el.onchange=()=>{"):]
    handler = handler[:handler.index("wrap.appendChild(el)")]
    assert "const derived=syncTep(false);if(filled||derived)renderInputs()" in handler
