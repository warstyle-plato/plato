"""Сохранённое состояние не должно съедать поля, которых в нём ещё нет.

loadLocal подменял вводные целиком: inputs=x.inputs||inputs. Поле, добавленное
в модель после того, как браузер сохранил проект, в нём просто отсутствовало —
список показывал пустую строку, а число при пересчёте становилось нулём. Так
«Периодичность платежей» ВРИ оказалась 0 при расчёте по квартальной, а «Право
на участок» и «График платежей» стояли пустыми.

Тесты гоняют настоящий код страницы в node.
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


def defaults(name: str) -> str:
    return re.search(rf"const {name}=(\{{.*?\}});", core.PAGE, re.S).group(1)


def load_local_body() -> str:
    source = core.PAGE
    start = source.index("function loadLocal()")
    depth = 0
    for position in range(source.index("{", start), len(source)):
        if source[position] == "{":
            depth += 1
        elif source[position] == "}":
            depth -= 1
            if depth == 0:
                return source[start:position + 1]
    raise AssertionError("не найдена loadLocal")


def restore(saved: dict) -> dict:
    """Прогоняет настоящий loadLocal над состоянием старого браузера."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    script = (
        f"const INPUT_DEFAULT={defaults('INPUT_DEFAULT')};\n"
        f"const TEP_DEFAULT={defaults('TEP_DEFAULT')};\n"
        "let inputs=structuredClone(INPUT_DEFAULT),tep=structuredClone(TEP_DEFAULT),"
        "phasing={},rates=[];\n"
        "const scenarioSelect={value:'base'};\n"
        "function makeDefaultPhasing(){return {enabled:false}}\n"
        f"const localStorage={{getItem:()=>{json.dumps(json.dumps(saved))}}};\n"
        + load_local_body() + "\n"
        "loadLocal();\n"
        "console.log(JSON.stringify({inputs,tep}));\n"
    )
    done = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


# Проект, сохранённый браузером до появления блока ВРИ.
OLD_STATE = {
    "inputs": {"purchase_price_mln": 6500, "apartment_price_th": 420,
               "_cost_structure_version": "0.7.1", "author_supervision_pct": 0},
    "tep": {"apartments": {"saleable": 160955, "gns": 260000}},
    "scenario": "base",
}


def test_fields_added_later_keep_their_defaults():
    inputs = restore(OLD_STATE)["inputs"]

    assert inputs["vri_periodicity_months"] == 3, "периодичность потерялась и станет нулём"
    assert inputs["land_right"] == "ownership", "право на участок пустое — список без значения"
    assert inputs["vri_schedule_mode"] == "auto"


def test_the_saved_values_still_win():
    inputs = restore(OLD_STATE)["inputs"]

    assert inputs["purchase_price_mln"] == 6500
    assert inputs["apartment_price_th"] == 420


def test_products_added_later_keep_their_shape():
    tep = restore(OLD_STATE)["tep"]

    assert tep["apartments"]["saleable"] == 160955, "сохранённый ТЭП потерян"
    assert "storage" in tep and "units" in tep["storage"], "продукт, добавленный позже, исчез"


def test_an_empty_storage_falls_back_to_defaults():
    inputs = restore({})["inputs"]

    assert inputs["vri_periodicity_months"] == 3


def test_the_periodicity_is_a_list_of_choices():
    """Свободное число позволяло ввести 0, которое расчёт молча заменял на 3."""
    field = next(
        item
        for _, fields in core.FIELD_GROUPS
        for item in fields
        if item[0] == "vri_periodicity_months"
    )

    assert field[3] == "select", "поле осталось свободным числом"
    assert [value for value, _ in field[4]] == ["1", "3", "6", "12"]


def test_the_page_offers_the_same_choices():
    """Список полей продублирован в странице литералом — он должен совпадать."""
    page_groups = json.loads(re.search(r"const FIELD_GROUPS=(\[.*?\]);", core.PAGE, re.S).group(1))
    field = next(item for _, fields in page_groups for item in fields
                 if item[0] == "vri_periodicity_months")

    assert field[3] == "select"
    assert [value for value, _ in field[4]] == ["1", "3", "6", "12"]


def test_the_chosen_periodicity_reaches_the_engine():
    """Список отдаёт строку — движок обязан её понять."""
    assert core.n({"vri_periodicity_months": "6"}, "vri_periodicity_months", 3) == 6.0
