"""Вписанное требованием КРТ переживает пересчёт ТЭП.

«Беру пресет Нагатино, и там херня опять с соцобъектами. Я ввожу из КРТ ГНС в
ТЭП, и автоматом всё пересчитывает — возвращает ВРИ сам, кол-во мест в садике
и ДОО вставляет из ГлавАПУ. Что я делаю не так? Мне надо по нормам КРТ вручную
вбить, и этот флажок включён» (владелец, 04.09.2026).

Ничего не так: признак защищал только ПЛОЩАДЬ и норматив соцобъекта, а места,
соцкомпенсацию и плату за ВРИ переписывали три пересчёта — пропорцией, по
нормативам Москвы и по выгрузке ГлавАПУ. Правка одного из них выглядела бы
как правка всех, поэтому список запертого объявлен один раз.

И пересчёт называет, чего он НЕ тронул: молча не тронутое поле на экране
выглядит так же, как не посчитанное.

Запуск: python3 -m pytest tests/test_a_krt_requirement_survives_a_tep_edit.py -q
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402

PAGE = core.PAGE


def _piece(name: str) -> str:
    """Функция целиком — по её объявлению и скобкам, а не по соседней строке."""
    start = PAGE.index(f"function {name}(")
    depth, i = 0, PAGE.index("{", start)
    while True:
        if PAGE[i] == "{":
            depth += 1
        elif PAGE[i] == "}":
            depth -= 1
            if depth == 0:
                return PAGE[start:i + 1]
        i += 1


def _run(script: str) -> dict:
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr[-2000:]
    return json.loads(out.stdout)


HARNESS = """
let inputs = %(inputs)s;
%(helper)s
const skipped = applyDerivedInputs(%(derived)s);
console.log(JSON.stringify({inputs, skipped}));
"""


def _apply(source: str, derived: dict, **over) -> dict:
    inputs = {"social_area_source": source, "kindergarten_places": 199,
              "school_places": 407, "clinic_capacity": 86,
              "social_compensation_mln": 1234.5, "land_rights_cost_mln": 2864.0, **over}
    helper = "\n".join(_piece(name) for name in
                       ("krtRequirementEntered", "applyDerivedInputs"))
    consts = PAGE[PAGE.index("const KRT_REQUIREMENT_INPUTS="):
                  PAGE.index("function krtRequirementEntered(")]
    return _run(HARNESS % {"inputs": json.dumps(inputs, ensure_ascii=False),
                           "helper": consts + helper,
                           "derived": json.dumps(derived, ensure_ascii=False)})


DERIVED = {"kindergarten_places": 250, "school_places": 500, "clinic_capacity": 100,
           "social_compensation_mln": 999.0, "land_rights_cost_mln": 5000.0}


def test_the_list_of_locked_inputs_is_declared_once() -> None:
    """Три пересчёта со своим списком разошлись бы молча."""
    assert PAGE.count("const KRT_REQUIREMENT_INPUTS=") == 1
    for name in ("rescaleSocialFromTep", "recalcFromTepByNorms", "recalcFromTep"):
        assert "applyDerivedInputs(" in _piece(name), \
            f"{name} пишет вводные мимо общего правила"


def test_a_krt_requirement_survives_the_recalculation() -> None:
    got = _apply("manual", DERIVED)
    assert got["inputs"]["kindergarten_places"] == 199
    assert got["inputs"]["school_places"] == 407
    assert got["inputs"]["clinic_capacity"] == 86
    assert got["inputs"]["social_compensation_mln"] == 1234.5
    assert got["inputs"]["land_rights_cost_mln"] == 2864.0


def test_the_recalculation_says_what_it_did_not_touch() -> None:
    """Молча не тронутое поле выглядит так же, как не посчитанное."""
    skipped = _apply("manual", DERIVED)["skipped"]
    for label in ("места ДОО", "места СОШ", "плата за ВРИ", "соцкомпенсация"):
        assert label in skipped, skipped


def test_without_the_flag_the_recalculation_still_writes() -> None:
    """Признак — выбор человека, а не запрет пересчёта вообще."""
    got = _apply("norm", DERIVED)
    assert got["inputs"]["kindergarten_places"] == 250
    assert got["inputs"]["land_rights_cost_mln"] == 5000.0
    assert got["skipped"] == ""


def test_the_field_label_no_longer_promises_only_the_area() -> None:
    """Подпись, обещающая меньше, чем делает признак, — та же неверная
    оговорка, что «мы этого не читаем»."""
    label = next(item for group in core.FIELD_GROUPS for item in group[1]
                 if item[0] == "social_area_source")
    assert "Площадь и норматив соцобъектов" != label[1], "подпись осталась узкой"
    assert "ВРИ" in label[1] or "ВРИ" in label[2]
