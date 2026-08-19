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
    """Известна продаваемая — считаются ГНС и общая."""
    filled = _fill("offices", {"gns": 0, "total_area": 0, "saleable": 18000, "useful": 0})
    assert filled["gns"] == pytest.approx(18000 / 0.564, rel=1e-3)
    assert filled["total_area"] == pytest.approx(filled["gns"] * 0.94, rel=1e-3)
    # 60% общей — то, что владелец назвал; в таблице это записано долей от ГНС.
    assert filled["saleable"] / filled["total_area"] == pytest.approx(0.60, rel=1e-3)
    assert filled["useful"] == filled["saleable"]


def test_the_office_is_built_from_the_gns():
    """Известна ГНС — считаются общая и продаваемая."""
    filled = _fill("offices", {"gns": 30000, "total_area": 0, "saleable": 0, "useful": 0})
    assert filled["total_area"] == pytest.approx(28200.0, rel=1e-6)
    assert filled["saleable"] == pytest.approx(16920.0, rel=1e-6)


def test_housing_follows_the_calculator_chain():
    """Квартиры — 65% жилой СПП, НП — 90% СПП: цепочка калькулятора ГлавАПУ.

    Из неё же следует «продаваемая = 72% общей», названное владельцем:
    0,65 / 0,90 = 0,722. Числа сверены по двум выгрузкам калькулятора и живут
    в `vri_tep_quick` — здесь не вторая методика, а та же самая.
    """
    filled = _fill("apartments", {"gns": 100000, "total_area": 0, "saleable": 0, "useful": 0})
    assert filled["total_area"] == pytest.approx(90000.0, rel=1e-6)
    assert filled["saleable"] == pytest.approx(65000.0, rel=1e-6)
    assert filled["saleable"] / filled["total_area"] == pytest.approx(0.7222, rel=1e-3)

    quick = __import__("inspect").getsource(core.vri_tep_quick)
    assert "apartments_gns = spp * 0.94" in quick
    assert "apartments = apartments_gns * 0.65" in quick, (
        "доля квартир разошлась с калькулятором — таблица пропорций врёт")


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
    assert core.TEP_RATIOS["apartments"]["saleable_of_gns"] == 0.65


def test_a_product_without_ratios_is_left_alone():
    """Паркинг, кладовые и соцобъекты пропорциями не достраиваются."""
    row = {"gns": 0, "total_area": 0, "saleable": 5000, "useful": 0}
    assert _fill("underground_parking", row) == row


def test_the_page_takes_the_ratios_from_the_engine():
    """Копии таблицы на странице нет — подставляется движковая."""
    assert "const TEP_RATIOS=" in core.PAGE
    assert core.TEP_RATIOS_PLACEHOLDER not in core.PAGE
    assert "0.94" in json.dumps(core.TEP_RATIOS, ensure_ascii=False)


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


def _complaint(key: str, row: dict) -> str:
    """Настоящая проверка строки со страницы, через node."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    body = re.search(r"function tepRowComplaint\(key,row\)\{.*?\n\}", core.PAGE, re.S)
    assert body, "tepRowComplaint не найдена"
    script = (
        f"const TEP_RATIOS={json.dumps(core.TEP_RATIOS, ensure_ascii=False)};\n"
        "const landNum=(v,d)=>Number(v).toFixed(d);\n"
        + body.group(0)
        + f"\nconsole.log(JSON.stringify(tepRowComplaint({json.dumps(key)},{json.dumps(row)})));"
    )
    done = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_nonsense_in_a_row_is_called_out():
    """«Вбил ерунду — ерунда и осталась» (замечание владельца, 19.08.2026).

    Пропорции достраивают только пустое, поэтому в заполненной строке они молча
    ничего не делают. Молчание читается как «ничего не работает», а числа,
    противоречащие друг другу, едут дальше в выручку и себестоимость.
    """
    # ГНС 500 000, общая 45 000, продаваемая 500 000 — ровно тот случай.
    assert "продаваемая больше общей" in _complaint(
        "apartments", {"gns": 500000, "total_area": 45000, "saleable": 500000})
    assert "общая площадь больше ГНС" in _complaint(
        "apartments", {"gns": 45000, "total_area": 500000, "saleable": 100000})
    # Расхождение с пропорцией больше четверти — предупреждение, а не запрет.
    assert "расходится с пропорцией" in _complaint(
        "offices", {"gns": 100000, "total_area": 94000, "saleable": 20000})
    # Согласованная строка молчит.
    assert _complaint("offices", {"gns": 100000, "total_area": 94000, "saleable": 56400}) == ""


def test_the_row_can_be_refilled_on_demand():
    """Кнопка делает явно то, что пропорции не делают сами: переписывает строку."""
    body = core.PAGE[core.PAGE.index("function refillTepRow"):]
    body = body[:body.index("function tepCellChanged")]
    assert "tepFillByRatios(key,base)" in body
    assert "renderTep()" in body and "calculate()" in body

    table = core.PAGE[core.PAGE.index("function renderTep(){"):]
    table = table[:table.index("function updateTepTotals")]
    assert "refillTepRow(" in table, "кнопки нет в строке таблицы"
    assert "tepRowComplaint(key,row)" in table, "предупреждение не выводится"


def test_the_note_is_one_line_not_a_wall():
    """На телефоне подпись занимала семь строк — её никто не читал.

    Правило остаётся на виду одной фразой, доли — под раскрытием: они нужны
    тому, кто спросил, а не всем и сразу.
    """
    body = core.PAGE[core.PAGE.index("function renderTepRatioNote"):]
    body = body[:body.index("function tepRowComplaint")]
    assert "<details" in body, "подробности должны быть свёрнуты"
    visible = body[body.index("box.innerHTML="):body.index("<details")]
    assert len(visible) < 260, "видимая часть подписи снова разрослась"
    assert "не перебивается" in visible, "главное правило должно остаться на виду"


def test_the_button_says_why_it_did_nothing():
    """«Нажал по пропорциям — ничего не появилось» (владелец, 19.08.2026).

    Две причины, и обе не видны на глаз: строка пустая — считать не из чего;
    объект выключен во вводных — строка обнуляется при каждом пересчёте, и любое
    число в ней исчезает. Кнопка, которая молча ничего не делает, читается как
    сломанная.
    """
    body = core.PAGE[core.PAGE.index("function refillTepRow"):]
    body = body[:body.index("const tepRefillNote")]
    assert "Нечего пересчитывать" in body
    assert "Объект выключен во вводных" in body
    assert "TEP_ROW_SWITCH" in body

    switches = core.PAGE[core.PAGE.index("const TEP_ROW_SWITCH="):]
    switches = switches[:switches.index("}")]
    assert "offices_enabled" in switches and "retail_enabled" in switches

    table = core.PAGE[core.PAGE.index("function renderTep(){"):]
    table = table[:table.index("function updateTepTotals")]
    assert "tepRefillNote[key]||tepRowComplaint(key,row)" in table


def test_the_disclosure_says_what_it_hides():
    """«Какие доли» само по себе не объясняет, что там внутри."""
    body = core.PAGE[core.PAGE.index("function renderTepRatioNote"):]
    body = body[:body.index("const TEP_ROW_SWITCH")]
    assert "показать доли, по которым считается" in body


def test_a_table_edit_reaches_the_inputs():
    """Строки офисов и ТЦ производные: вписанное в таблицу исчезало при пересчёте.

    `syncTep` пересобирает их из вводных, поэтому число надо не защищать от
    пересчёта, а вернуть туда, откуда пересчёт его берёт (замечание владельца,
    19.08.2026).
    """
    body = core.PAGE[core.PAGE.index("function tepRowToInputs"):]
    body = body[:body.index("function tepCellChanged")]
    assert "inputs[map.gns]" in body and "inputs[map.saleable]" in body
    assert "объект выключен" in body, "выключенный объект обнулит строку — об этом надо сказать"

    mapping = core.PAGE[core.PAGE.index("const TEP_ROW_INPUTS="):]
    mapping = mapping[:mapping.index("function tepRowToInputs")]
    for field in ("offices_gba_sqm", "offices_saleable_sqm",
                  "retail_gba_sqm", "retail_saleable_sqm"):
        assert field in mapping, field

    handler = core.PAGE[core.PAGE.index("function tepCellChanged"):]
    handler = handler[:handler.index("function updateTepTotals")]
    assert "tepRowToInputs(key)" in handler
    assert "renderInputs()" in handler, "поле во вводных должно показать своё число"
