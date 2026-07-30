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


def render_periodicity(region: str, saved: float | str) -> dict:
    """Отрисовывает поле периодичности настоящим кодом страницы."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    source = core.PAGE
    start = source.index("     const mskQuarter=id==='vri_periodicity_months'")
    end = source.index("     wrap.appendChild(el)", start)
    script = (
        f"let inputs={{vri_region:{json.dumps(region)},"
        f"vri_periodicity_months:{json.dumps(saved)}}};\n"
        "const id='vri_periodicity_months', type='select';\n"
        "const el={value:'',disabled:false,title:''};\n"
        + source[start:end] + "\n"
        "console.log(JSON.stringify({value:el.value,disabled:el.disabled,"
        "stored:inputs.vri_periodicity_months}));\n"
    )
    done = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_moscow_always_shows_the_quarter():
    """Движок для Москвы считает по кварталу — поле обязано показывать его же."""
    field = render_periodicity("msk", 12)

    assert field["stored"] == 3, "в вводных осталось значение, которого расчёт не применит"
    assert field["disabled"] is True, "поле можно поменять, а расчёт это проигнорирует"


def test_the_default_for_moscow_is_the_quarter():
    assert core.DEFAULT_INPUTS["vri_periodicity_months"] == 3
    assert render_periodicity("msk", 3)["stored"] == 3


def test_the_region_outside_moscow_keeps_its_choice():
    field = render_periodicity("mo", 6)

    assert field["stored"] == 6
    assert field["disabled"] is False


def test_the_engine_agrees_with_what_the_field_shows():
    from datetime import date

    for region, chosen, expected in (("msk", 12, 3), ("msk", 3, 3), ("mo", 6, 6), ("mo", 12, 12)):
        settings = core._vri_settings(
            {"vri_region": region, "vri_periodicity_months": chosen,
             "vri_payment_mode": "installment", "vri_installment_years": 3},
            date(2028, 1, 1))
        assert settings["periodicity"] == expected, (region, chosen)


def test_the_deal_price_belongs_to_the_territory():
    """Два расчёта подряд шли по цене предыдущего проекта — это не бросалось в глаза."""
    page = core.PAGE
    start = page.index("const TERRITORY_INPUT_KEYS=[")
    block = page[start:page.index("];", start)]

    assert "'purchase_price_mln'" in block
