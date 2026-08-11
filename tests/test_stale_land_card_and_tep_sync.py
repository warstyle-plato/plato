"""Два разъезда экрана с самим собой: карточка ЕГРН и таблица ТЭП.

**Карточка чужого участка.** Расчёт ТЭП по кадастровому номеру идёт через
`/cadastral/analyze` и сведения ЕГРН не запрашивает. Блок «Только сведения
ЕГРН» при этом жил сам по себе: снимок предыдущего участка восстанавливался из
проекта и оставался на экране рядом с новым ТЭП. Получались два участка сразу —
«ТЭП посчитан штатным калькулятором ГлавАПУ: 2,0844 га» и «Суммарная площадь
0,9820 га», адрес от одного, площадь от другого, и оба с виду достоверны. Тот
же снимок оставался висеть, когда запрос к НСПД падал: `lookupLand` уходил в
`catch`, а прежняя карточка не гасла.

**Таблица ТЭП.** Правка машино-мест на вкладке «Вводные» звала `syncTep(false)`,
а он обновлял только строку итогов. Данные пересчитывались, ячейки продукта в
таблице оставались с прежними числами — до следующей полной перерисовки, то
есть до расчёта модели. Человек менял 1 107 мест на 500 и видел в ТЭП всё те же
1 107. Не перерисовывать нужно ровно в одном случае: когда правят саму таблицу и
перерисовка убьёт фокус.

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


def node_run(script: str):
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    done = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def source_of(name: str) -> str:
    """Настоящий текст функции из PAGE — проверять надо код, а не его пересказ."""
    match = re.search(rf"function {name}\(.*?\n\}}", core.PAGE, re.S)
    assert match, f"функция {name} не найдена в PAGE"
    return match.group(0)


# --- снимок ЕГРН относится к своему запросу -----------------------------------

def check_fits(snapshot_query: str, field_value: str) -> bool:
    script = (
        source_of("landQueryKey") + "\n"
        + source_of("landSnapshotFits") + "\n"
        f"const landLookup={json.dumps({'query': snapshot_query})};\n"
        f"const field={{value:{json.dumps(field_value)}}};\n"
        "global.document={getElementById:()=>field};\n"
        "console.log(JSON.stringify(landSnapshotFits()));\n"
    )
    return node_run(script)


def test_a_snapshot_of_another_plot_does_not_fit():
    """Тот самый экран: в поле 77:07:0013001:7189, в карточке — 77:03:0006015:30."""
    assert check_fits("77:03:0006015:30", "77:07:0013001:7189") is False


def test_the_snapshot_of_the_same_plot_stays():
    assert check_fits("77:03:0006015:30", "77:03:0006015:30") is True


def test_spacing_and_case_do_not_count_as_another_plot():
    """Иначе блок мигал бы от лишнего пробела при вставке из буфера."""
    assert check_fits("77:03:0006015:30", "  77:03:0006015:30 ") is True
    assert check_fits("Москва, улица Мира, 1", "москва,  улица мира, 1") is True


def test_a_missing_snapshot_never_fits():
    script = (
        source_of("landQueryKey") + "\n"
        + source_of("landSnapshotFits") + "\n"
        "const landLookup=null;\n"
        "global.document={getElementById:()=>({value:'77:03:0006015:30'})};\n"
        "console.log(JSON.stringify(landSnapshotFits()));\n"
    )
    assert node_run(script) is False


# --- где гашение вызывается ---------------------------------------------------

def test_typing_another_number_drops_the_card():
    """Карточка уходит по вводу, а не по нажатию кнопки: до кнопки человек
    успевает прочитать чужой адрес как свой."""
    assert 'id="cadastralNumbers" oninput="dropStaleLandPreview()"' in core.PAGE


def test_obtaining_the_tep_drops_a_foreign_card():
    """Путь через /cadastral/analyze ЕГРН не запрашивает — значит снимок надо
    снять самому, иначе он останется от прежнего участка."""
    match = re.search(r"async function obtainTep\(\)\{.*?\n\}", core.PAGE, re.S)
    assert match, "obtainTep не найден"
    body = match.group(0)
    assert "dropStaleLandPreview()" in body
    assert body.index("dropStaleLandPreview()") < body.index("cadastral/analyze")


def test_a_failed_lookup_leaves_no_previous_card():
    """Запрос к НСПД падает — прежняя карточка не должна пережить его."""
    match = re.search(r"async function lookupLand\(options\)\{.*?\n\}", core.PAGE, re.S)
    assert match, "lookupLand не найден"
    body = match.group(0)
    assert "hideLandPreview()" in body
    assert body.index("hideLandPreview()") < body.index("await fetch")


# --- таблица ТЭП обновляется сразу --------------------------------------------

def sync_rerenders(rerender: str, editing_tep: bool) -> bool:
    """Прогоняет настоящее условие из syncTep."""
    line = re.search(
        r"const editingTep=.*?\n\s*if\(rerender\|\|!editingTep\)renderTep\(\);else updateTepTotals\(\);",
        core.PAGE, re.S)
    assert line, "условие перерисовки в syncTep не найдено"
    script = (
        f"const rerender={rerender};\n"
        "let called='';\n"
        "const renderTep=()=>{called='render'}, updateTepTotals=()=>{called='totals'};\n"
        f"const active={{}}; const tepBody={{contains:()=>{str(editing_tep).lower()}}};\n"
        "global.document={activeElement:active};\n"
        + line.group(0) + "\n"
        "console.log(JSON.stringify(called==='render'));\n"
    )
    return node_run(script)


def test_editing_inputs_redraws_the_tep_at_once():
    """Правка машино-мест на «Вводных»: фокус не в таблице, значит перерисовать
    можно и нужно — прежде число доезжало только со следующим расчётом."""
    assert sync_rerenders("false", editing_tep=False) is True


def test_editing_the_tep_table_itself_keeps_the_focus():
    """Ради чего перерисовку и отключали: человек печатает в ячейке ТЭП, и
    пересборка таблицы отняла бы у него поле на полуслове."""
    assert sync_rerenders("false", editing_tep=False) is True
    assert sync_rerenders("false", editing_tep=True) is False


def test_an_explicit_rerender_still_wins():
    assert sync_rerenders("true", editing_tep=True) is True


def test_the_parking_fields_reach_sync_tep():
    """Связь «поле → syncTep» — то, из-за чего правка вообще куда-то доходит."""
    assert "['underground_manual_spaces','underground_manual_gns_sqm'," \
           "'underground_area_per_space_sqm'].includes(id)" in core.PAGE.replace("\n", "")
