"""Смена территории снимает карточку другой методики — вместе с данными.

Расчёт МО оставлял на экране карточку ГлавАПУ прошлого запроса: под свежим
итогом Подмосковья висел чужой московский участок (0,6509 га, САО), а его
кнопка «Применить к Вводным и ТЭП» унесла бы в модель старый ТЭП — скриншот
владельца, 15.08. В обратную сторону москворецкий запрос оставлял блок МО.
И сброс проекта переживал glavapuImport: «чистый» проект мог применить ТЭП
удалённого участка.

Тесты гоняют настоящие dropGlavapuPreview/dropMoPreview из PAGE через node,
а проводку (кто кого зовёт) проверяют по телу самих функций страницы.

Запуск: python3 -m pytest tests/test_switching_territory_drops_the_other_preview.py -q
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
NODE = shutil.which("node")


def drop_harness() -> str:
    match = re.search(
        r"(const GLAVAPU_STATUS_DEFAULT=.*?)\n\nlet moDistrictPrices", core.PAGE, re.S
    )
    assert match, "функции снятия карточек не найдены на странице"
    return match.group(1)


def page_function(name: str) -> str:
    match = re.search(
        r"((?:async )?function " + re.escape(name) + r"\(.*?\n\})", core.PAGE, re.S
    )
    assert match, f"функция {name} не найдена на странице"
    return match.group(1)


def run_drops() -> dict:
    if not NODE:
        pytest.skip("node недоступен")
    script = (
        "const elements={};\n"
        "function el(id){return elements[id]||(elements[id]={id,style:{},textContent:'',innerHTML:''})}\n"
        "el('glavapuStatus').textContent='Введите кадастровый номер выше — ТЭП посчитается сам.';\n"
        "const document={getElementById:el};\n"
        "let glavapuImport={source:{format:'ГлавАПУ'}},moResult={territory:{}};\n"
        + drop_harness()
        + "\n"
        "el('glavapuPreview').style.display='block';\n"
        "el('cadastralPreview').style.display='block';\n"
        "el('glavapuStatus').textContent='ТЭП посчитан штатным калькулятором ГлавАПУ.';\n"
        "dropGlavapuPreview();\n"
        "el('moPreview').style.display='block';\n"
        "el('moStatus').style.display='block';\n"
        "dropMoPreview();\n"
        "console.log(JSON.stringify({glavapuImport,moResult,\n"
        " glavapu_display:el('glavapuPreview').style.display,\n"
        " cad_display:el('cadastralPreview').style.display,\n"
        " status_text:el('glavapuStatus').textContent,\n"
        " mo_display:el('moPreview').style.display,\n"
        " mo_status_display:el('moStatus').style.display}));\n"
    )
    result = subprocess.run([NODE, "-e", script], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def test_dropping_the_glavapu_card_clears_its_data_too():
    state = run_drops()
    assert state["glavapuImport"] is None, "карточка снята, а ТЭП остался применимым"
    assert state["glavapu_display"] == "none"
    assert state["cad_display"] == "none"
    assert state["status_text"].startswith("Введите кадастровый номер")


def test_dropping_the_mo_card_clears_its_data_too():
    state = run_drops()
    assert state["moResult"] is None
    assert state["mo_display"] == "none"
    assert state["mo_status_display"] == "none"


def test_each_territory_path_drops_the_other_card():
    """Расчёт МО снимает карточку ГлавАПУ, московский путь — блок МО."""
    assert "dropGlavapuPreview();" in page_function("calculateMo")
    assert "dropMoPreview();" in page_function("obtainCadastralTep")


def test_reset_drops_both_cards_with_their_data():
    # Сброс забывает территорию тем же вызовом, что подмена проекта
    # (`forgetTerritoryState`), а тот снимает обе карточки вместе с данными.
    reset = page_function("resetAll")
    assert "forgetTerritoryState();" in reset
    forget = page_function("forgetTerritoryState")
    assert "dropGlavapuPreview();" in forget
    assert "dropMoPreview();" in forget
