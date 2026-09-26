"""Автопересчёт нормативов ТЭП следует за жильём, а не за офисными долями.

Регрессия: смена продаваемой доли офисника 50→60% запускала полный пересчёт
из baseline ГлавАПУ и показывала новое население, ВРИ, соцкомпенсацию и
машино-места, хотя жилая площадь не менялась. Для населения драйвер — квартиры.

Запуск: python3 -m pytest tests/test_tep_auto_recalc_only_follows_apartments.py -q
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402

PAGE = core.PAGE


def _function(name: str) -> str:
    start = PAGE.index(f"function {name}(")
    depth = 0
    i = PAGE.index("{", start)
    while i < len(PAGE):
        if PAGE[i] == "{":
            depth += 1
        elif PAGE[i] == "}":
            depth -= 1
            if depth == 0:
                return PAGE[start:i + 1]
        i += 1
    raise AssertionError(name)


def test_scheduler_ignores_an_office_edit_but_accepts_an_apartment_edit() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    fn = _function("scheduleTepAutoRecalc")
    program = f"""
let scheduled=0;
let tepAutoTimer=null, moAutoApartments=null, moAutoBusy=false;
let inputs={{_glavapu_import:{{normalized:{{change_vri_mln:100}}}}}};
let tep={{apartments:{{saleable:100000}}}};
const clearTimeout=()=>{{}};
const setTimeout=(fn,ms)=>{{scheduled+=1;return scheduled}};
const recalcFromTep=()=>{{throw new Error('таймер не должен исполняться в тесте')}};
{fn}
scheduleTepAutoRecalc('offices');
const afterOffice=scheduled;
scheduleTepAutoRecalc('apartments');
process.stdout.write(JSON.stringify({{afterOffice,afterApartments:scheduled}}));
"""
    done = subprocess.run([node, "-e", program], capture_output=True,
                          text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    got = json.loads(done.stdout)
    assert got == {"afterOffice": 0, "afterApartments": 1}


def test_every_automatic_call_passes_the_changed_tep_key() -> None:
    assert "scheduleTepAutoRecalc();" not in PAGE
    assert PAGE.count("scheduleTepAutoRecalc(key);") == 5


def test_the_scheduler_declares_apartments_as_the_only_normative_driver() -> None:
    body = _function("scheduleTepAutoRecalc")
    assert "changedKey!=='apartments'" in body
    assert body.index("changedKey!=='apartments'") < body.index("_glavapu_import")


def test_krt_note_does_not_claim_that_locked_vri_and_compensation_changed() -> None:
    body = _function("recalcFromTep")
    gate = body.index("if(!lockedKrt)")
    vri = body.index("Плата за ВРИ, млн ₽")
    compensation = body.index("Соцкомпенсация, млн ₽")
    assert gate < vri < compensation
    assert "lockedKrt?'':' · ДОО '" in body
