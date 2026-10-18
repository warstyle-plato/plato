"""Размещение кладовых — галочка «над землёй» у строки ТЭП (владелец, 16.10.2026).

«А где собственно говоря выбор келлеров под землёй или над землёй?» — поле
стояло в свёрнутой группе «Кладовые» во «Вводных»; владелец выбрал «Галочка в
ТЭП». Поле одно (`storage_placement`), у него второй дом — `TEP_ONLY_INPUTS`.

Стенд гоняет НАСТОЯЩИЙ код страницы (`tests/page_blocks.run`): галочку строки,
её обработчик и правило «чего нет во Вводных». Отрисованная страница — в
`test_storage_placement_and_cost_pool.py`.

Запуск: python3 -m pytest tests/test_storage_placement_tep_checkbox.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402
from tests import page_blocks  # noqa: E402

# Отрисовка таблицы и поход на сервер к проверяемому не относятся — их
# считаем, а не исполняем: утверждение о том, что пересчёт ВЫЗВАН.
PRELUDE = "\n".join([
    "let calls={renderTep:0,calculate:0};",
    "function renderTep(){calls.renderTep++}",
    "function calculate(){calls.calculate++}",
    "function isNonResidential(){return false}",
])


def _run(inputs: dict, tail: str) -> dict:
    prelude = PRELUDE + "\nlet inputs=" + json.dumps(inputs, ensure_ascii=False) + ";"
    out, _taken = page_blocks.run(prelude, tail)
    return json.loads(out)


def test_the_storage_row_carries_the_checkbox_unchecked_by_default() -> None:
    got = _run({}, "console.log(JSON.stringify({storage:tepRowSwitches('storage'),"
                   "flats:tepRowSwitches('apartments')}));")
    assert 'id="tep_storage_placement"' in got["storage"]
    assert "над землёй" in got["storage"]
    # Отсутствующий ключ — «в подземной части», а не «над землёй».
    assert "checked" not in got["storage"].replace("this.checked", "")
    assert got["flats"] == ""


def test_a_saved_above_ground_project_shows_it_checked() -> None:
    got = _run({"storage_placement": "above"},
               "console.log(JSON.stringify(tepRowSwitches('storage')));")
    assert "checked" in got.replace("this.checked", "")


def test_the_click_writes_the_same_field_and_recalculates() -> None:
    got = _run({}, "\n".join([
        "tepRowSwitchSet('storage_placement',true);",
        "const on=inputs.storage_placement;",
        "const origin=(inputs._field_origin||{})['inputs.storage_placement'];",
        "const c1=Object.assign({},calls);",
        "tepRowSwitchSet('storage_placement',false);",
        "console.log(JSON.stringify({on,origin,c1,off:inputs.storage_placement,c2:calls,"
        "keys:Object.keys(inputs).filter(k=>!k.startsWith('_'))}));",
    ]))
    assert got["on"] == "above"
    assert got["off"] == "underground"
    assert got["origin"]["source"] == "manual"
    assert got["c1"] == {"renderTep": 1, "calculate": 1}
    assert got["c2"] == {"renderTep": 2, "calculate": 2}
    # Новых ключей не заводится: пишется то же поле.
    assert got["keys"] == ["storage_placement"]


def test_the_field_is_not_on_inputs_and_its_group_is_gone() -> None:
    got = _run({}, "\n".join([
        "const groups=FIELD_GROUPS.filter(g=>g[1].some(f=>!notOnInputs(f[0]))).map(g=>g[0]);",
        "console.log(JSON.stringify({hidden:notOnInputs('storage_placement'),groups}));",
    ]))
    assert got["hidden"] is True
    assert "Кладовые" not in got["groups"]
    assert "Продажи" in got["groups"]


def test_the_engine_default_and_the_where_to_edit_answer() -> None:
    assert core.DEFAULT_INPUTS["storage_placement"] == "underground"
    spec = core.TEP_ONLY_INPUTS["storage_placement"]
    assert (spec["on"], spec["off"], spec["row"]) == ("above", "underground", "storage")
    place = core.input_field_place("storage_placement")
    assert place["where"] == "ТЭП"
    assert "Кладовые" in place["path"] and "над землёй" in place["path"]
    assert "Вводные" not in place["path"]
