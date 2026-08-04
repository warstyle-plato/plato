"""Места и площадь подземного паркинга — одна величина в двух видах.

В полях одновременно стояли 50 машино-мест и 3 000 м² при нормативе 35 м²:
50 × 35 = 1 750, и что из этого считает модель, по экрану понять было нельзя.
Поля были независимы, а ноль в них означал «взять норматив ГлавАПУ» — то есть
человек видел пустоту там, где ждал расчёт своего участка.

Теперь пара согласуется: правка мест пересчитывает площадь, правка площади —
места, а норматив меняет площадь при неизменных местах. Ведущее — количество
мест: норматив правят, когда меняется представление о рампах и проездах, а не
о числе машин. Поля предзаполняются расчётом ТЭП, и новый импорт ГлавАПУ
перезаписывает их расчётом нового участка.

Тесты гоняют настоящий код страницы через node, а не его пересказ.

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


def _function(name: str) -> str:
    match = re.search(r"^function " + name + r"\(.*?^\}", core.PAGE, re.S | re.M)
    assert match, f"функция {name} не найдена на странице"
    return match.group(0)


def _run(inputs: dict, changed: str, glavapu: dict | None = None) -> dict:
    """Прогоняет настоящую syncUndergroundPair из PAGE."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    script = (
        f"const inputs={json.dumps(inputs)};\n"
        f"const stored={json.dumps(glavapu)};\n"
        "const document={getElementById:()=>null};\n"
        "function undergroundAreaPerSpace(){return Number(inputs.underground_area_per_space_sqm||0)||35}\n"
        + _function("syncUndergroundPair") + "\n"
        f"syncUndergroundPair({json.dumps(changed)});\n"
        "console.log(JSON.stringify(inputs));\n"
    )
    done = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_spaces_drive_the_area():
    """50 мест при нормативе 35 — это 1 750 м², а не что угодно рядом."""
    out = _run({"underground_manual_spaces": 50, "underground_manual_gns_sqm": 3000,
                "underground_area_per_space_sqm": 35}, "underground_manual_spaces")
    assert out["underground_manual_gns_sqm"] == 1750


def test_the_area_drives_the_spaces():
    """Обратный ход: знаем площадь этажа — знаем, сколько машин влезет."""
    out = _run({"underground_manual_spaces": 50, "underground_manual_gns_sqm": 3000,
                "underground_area_per_space_sqm": 35}, "underground_manual_gns_sqm")
    assert out["underground_manual_spaces"] == 86, "3000 ÷ 35 ≈ 86"


def test_the_norm_moves_the_area_not_the_spaces():
    """Норматив правят, когда меняется представление о рампах и проездах,
    а не о числе машин: 50 мест по 30 м² — это 1 500 м²."""
    out = _run({"underground_manual_spaces": 50, "underground_manual_gns_sqm": 1750,
                "underground_area_per_space_sqm": 30}, "underground_area_per_space_sqm")
    assert out["underground_manual_spaces"] == 50
    assert out["underground_manual_gns_sqm"] == 1500


def test_zero_stays_zero():
    """Ноль по-прежнему означает «считай по нормативу ГлавАПУ»: движок ведёт
    себя как раньше, и запросы через API этого не заметят."""
    out = _run({"underground_manual_spaces": 0, "underground_manual_gns_sqm": 0,
                "underground_area_per_space_sqm": 35}, "underground_manual_spaces")
    assert out["underground_manual_gns_sqm"] == 0


def test_the_pair_cannot_disagree_after_any_edit():
    """Любая правка оставляет пару согласованной — это и есть починка."""
    for changed in ("underground_manual_spaces", "underground_manual_gns_sqm",
                    "underground_area_per_space_sqm"):
        out = _run({"underground_manual_spaces": 50, "underground_manual_gns_sqm": 3000,
                    "underground_area_per_space_sqm": 35}, changed)
        per = out["underground_area_per_space_sqm"]
        spaces = out["underground_manual_spaces"]
        area = out["underground_manual_gns_sqm"]
        assert abs(area - spaces * per) <= per, (changed, spaces, area)


def test_the_fields_are_filled_from_the_tep():
    """Поля показывают расчёт участка, а не пустоту со значением «возьми
    норматив»: ноль в поле читался как «паркинга нет»."""
    page = core.PAGE
    assert "function fillUndergroundFromTep()" in page
    assert "fillUndergroundFromTep();" in page
    # Новый участок — новый паркинг: пара перезаполняется его расчётом.
    assert re.search(r"inputs\.underground_manual_spaces=0;\s*\n\s*inputs\.underground_manual_gns_sqm=0;\s*\n\s*fillUndergroundFromTep\(\);", page)


def test_the_edit_handler_syncs_the_pair():
    """Синхронизация висит на самом поле: иначе пара расходится до пересчёта."""
    page = core.PAGE
    assert "syncUndergroundPair(id)" in page
    for field in ("underground_manual_spaces", "underground_manual_gns_sqm",
                  "underground_area_per_space_sqm"):
        assert f"'{field}'" in page


def test_the_hints_no_longer_promise_a_zero():
    """Подсказка «0 — по нормативу» описывала прежнее поведение."""
    assert "0 — по нормативу ГлавАПУ" not in core.PAGE
    assert "из расчёта ТЭП" in core.PAGE
    assert "пересчитывается из мест" in core.PAGE


def test_the_engine_still_understands_a_zero():
    """Движок не менялся: ноль означает «по нормативу», и API это сохраняет."""
    inputs = {**core.DEFAULT_INPUTS, "_glavapu_import": {
        "normalized": {"parking_permanent": 25, "parking_guest": 3}}}
    tep = {key: dict(value) for key, value in core.TEP_DEFAULT.items()}
    result = core.calculate(core.CalcRequest(inputs=inputs, tep=tep, rates=[]))
    row = next(r for r in result["tep"]["rows"] if r["key"] == "underground_parking")
    assert row["units"] == pytest.approx(28)
