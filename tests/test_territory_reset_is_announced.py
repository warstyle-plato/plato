"""Обнуление вместе с участком объявляется, а не случается молча.

Импорт участка чистит шестнадцать полей — те, что принадлежат площадке: цену
входа, плату за ВРИ, соцнагрузку, площади отдельных объектов. Это правильно, и
записано в правилах проекта: иначе второй расчёт подряд считается по цене
предыдущего проекта.

Неправильно другое — что человеку об этом не говорят. Владелец импортировал
участок, не заметил обнулённую цену входа, посчитал и получил LLCR 1,08 вместо
1,02. Разницу нашли через неделю по памяти («мы всегда получали 1,08»), а не по
экрану. Молчаливое обнуление врёт ровно так же, как молчаливый переезд значений
из прошлого проекта, — и выглядит так же достоверно.

Тест гоняет настоящий код страницы через node.

Запуск: python3 -m pytest tests -q
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


def page_fragment(marker: str, end: str) -> str:
    start = core.PAGE.index(marker)
    return core.PAGE[start:core.PAGE.index(end, start)]


def run(inputs: dict) -> dict:
    """Гоняет сброс полей участка и подпись к нему."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    keys = page_fragment("let territoryCleared=[];", "const TERRITORY_MARKERS")
    labels = page_fragment("const TERRITORY_CLEARED_LABELS=", "function resetTerritoryData(")
    reset = page_fragment(" territoryCleared=[];\n TERRITORY_INPUT_KEYS.forEach",
                          "\n TERRITORY_MARKERS.forEach")
    script = "\n".join([
        keys, labels,
        f"const inputs={json.dumps(inputs, ensure_ascii=False)};",
        reset,
        "console.log(JSON.stringify({cleared:territoryCleared,"
        "note:territoryClearedNote(),inputs}));",
    ])
    done = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[:800]
    return json.loads(done.stdout)


# --- обнуление по-прежнему происходит ----------------------------------------------

def test_the_site_fields_are_still_cleared():
    """Правило не отменяется: цена сделки принадлежит участку."""
    got = run({"purchase_price_mln": 700, "land_rights_cost_mln": 1289.73})
    assert got["inputs"]["purchase_price_mln"] == 0
    assert got["inputs"]["land_rights_cost_mln"] == 0


def test_the_analyst_assumptions_are_untouched():
    """Себестоимость, ставки и сроки — не данные участка, их не трогаем."""
    got = run({"purchase_price_mln": 700, "main_above_th_per_sqm": 190,
               "technical_supervision_pct": 5, "pre_pf_own_funds_mln": 1900})
    assert got["inputs"]["main_above_th_per_sqm"] == 190
    assert got["inputs"]["technical_supervision_pct"] == 5
    assert got["inputs"]["pre_pf_own_funds_mln"] == 1900


# --- и теперь оно названо ------------------------------------------------------------

def test_what_was_cleared_is_named():
    """Ключ поля в плашке не значит ничего, «цена входа» значит всё."""
    got = run({"purchase_price_mln": 700, "land_rights_cost_mln": 1289.73,
               "social_compensation_mln": 580.668})
    assert set(got["cleared"]) == {"purchase_price_mln", "land_rights_cost_mln",
                                   "social_compensation_mln"}
    assert "цена входа" in got["note"]
    assert "плата за смену ВРИ" in got["note"]
    assert "социальная компенсация" in got["note"]
    assert "введите заново" in got["note"]


def test_only_what_actually_had_a_value_is_named():
    """Поле, которое и так было нулём, обнулять не пришлось — и упоминать его
    значит топить настоящую потерю в перечислении пустяков."""
    got = run({"purchase_price_mln": 700, "land_rights_cost_mln": 0,
               "offices_gba_sqm": 0, "school_places": 0})
    assert got["cleared"] == ["purchase_price_mln"]
    assert "плата за смену ВРИ" not in got["note"]


def test_a_clean_import_says_nothing():
    """Нечего было обнулять — нечего и сообщать: плашка на пустом месте
    приучает её не читать."""
    got = run({"purchase_price_mln": 0, "main_above_th_per_sqm": 190})
    assert got["cleared"] == []
    assert got["note"] == ""


def test_every_cleared_field_has_a_human_label():
    """Иначе в плашке появится purchase_price_mln, и человек решит, что это
    сообщение не ему."""
    keys = page_fragment("const TERRITORY_INPUT_KEYS=[", "];")
    labels = page_fragment("const TERRITORY_CLEARED_LABELS=", "};")
    import re

    for key in re.findall(r"'([a-z_0-9]+)'", keys):
        assert f"{key}:" in labels, f"нет подписи для {key}"


def test_the_note_reaches_the_card():
    """Подпись обязана попасть в сообщение об успешном применении участка —
    иначе она есть в коде и её нет на экране."""
    body = core.PAGE[core.PAGE.index("function applyGlavapu("):]
    body = body[:body.index("await calculate()")]
    assert "territoryClearedNote()" in body
